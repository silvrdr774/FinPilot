#!/usr/bin/env python3
"""FinPilot local full-stack server.

Features:
- Local SQLite user accounts with PBKDF2 password hashing
- Cookie-based sessions
- Per-user dashboard + portfolio state
- Per-user simulation history
- Same-origin proxy to local Ollama/qwen3:8b

Run:
    python3 server.py
Open:
    http://localhost:8000/FinPilot.html
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http import cookies
from pathlib import Path
import hashlib, hmac, json, os, secrets, sqlite3, time

HOST="0.0.0.0"
PORT=8000
OLLAMA="http://127.0.0.1:11434/api/chat"
DATA_DIR=Path.home()/".finpilot"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH=DATA_DIR/"finpilot.db"
LOCAL_DB_PATH=Path(__file__).with_name("finpilot.db")
COOKIE="finpilot_session"
SESSION_TTL=60*60*24*7

def db():
    c=sqlite3.connect(DB_PATH)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    if not DB_PATH.exists() and LOCAL_DB_PATH.exists():
        import shutil
        shutil.copy2(LOCAL_DB_PATH, DB_PATH)
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      salt TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'CEO',
      company TEXT NOT NULL DEFAULT 'My Company',
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions(
      token_hash TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS state(
      user_id INTEGER PRIMARY KEY,
      dashboard_json TEXT NOT NULL,
      portfolio_json TEXT NOT NULL,
      updated_at INTEGER NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS simulations(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      created_at INTEGER NOT NULL,
      summary_json TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    c.commit()
    c.close()

def password_hash(password,salt=None):
    salt = salt or secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,210000)
    return salt.hex(),digest.hex()

def verify_password(password,salt_hex,digest_hex):
    _,d=password_hash(password,bytes.fromhex(salt_hex))
    return hmac.compare_digest(d,digest_hex)

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def json_body(handler):
    n=int(handler.headers.get("Content-Length","0"))
    raw=handler.rfile.read(n)
    return json.loads(raw or b"{}")

def send_json(handler,status,payload,extra_headers=None):
    data=json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type","application/json; charset=utf-8")
    handler.send_header("Content-Length",str(len(data)))
    if extra_headers:
        for k,v in extra_headers.items(): handler.send_header(k,v)
    handler.end_headers()
    handler.wfile.write(data)

def current_user(handler):
    jar=cookies.SimpleCookie()
    jar.load(handler.headers.get("Cookie",""))
    morsel=jar.get(COOKIE)
    if not morsel: return None
    token=morsel.value
    c=db()
    row=c.execute("""
      SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
      WHERE s.token_hash=? AND s.expires_at>?
    """,(token_hash(token),int(time.time()))).fetchone()
    c.close()
    return dict(row) if row else None

def session_cookie(token,max_age=SESSION_TTL):
    return f"{COOKIE}={token}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Lax"

def login_user(user_id):
    token=secrets.token_urlsafe(32)
    c=db()
    c.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
              (token_hash(token),user_id,int(time.time())+SESSION_TTL))
    c.commit(); c.close()
    return token

def public_user(row):
    return {"id":row["id"],"email":row["email"],"role":row["role"],"company":row["company"]}

def default_dashboard(company):
    return {
      "company":company or "My Company",
      "industry":"Wholesale coffee roasting",
      "team":14,"payroll":31000,"cash":42000,"supplier":15000,"loan":9000
    }

def default_portfolio():
    return {
      "cash":50000,"income":50000,"expenses":30000,"debt":5000,
      "holdings":[
        {"asset":"Example Equity","units":10,"avg":1000,"current":1100},
        {"asset":"Example Fund","units":20,"avg":500,"current":520}
      ]
    }

def ensure_state(user_id,company):
    c=db()
    row=c.execute("SELECT * FROM state WHERE user_id=?",(user_id,)).fetchone()
    if not row:
        c.execute("INSERT INTO state(user_id,dashboard_json,portfolio_json,updated_at) VALUES(?,?,?,?)",
                  (user_id,json.dumps(default_dashboard(company)),json.dumps(default_portfolio()),int(time.time())))
        c.commit()
        row=c.execute("SELECT * FROM state WHERE user_id=?",(user_id,)).fetchone()
    c.close()
    return json.loads(row["dashboard_json"]),json.loads(row["portfolio_json"])

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path=="/api/me":
            u=current_user(self)
            return send_json(self,200,{"authenticated":bool(u),"user":public_user(u) if u else None})
        if self.path=="/api/state":
            u=current_user(self)
            if not u: return send_json(self,401,{"error":"Not authenticated"})
            dashboard,portfolio=ensure_state(u["id"],u["company"])
            c=db()
            sims=[json.loads(r["summary_json"]) for r in c.execute(
                "SELECT summary_json FROM simulations WHERE user_id=? ORDER BY id DESC LIMIT 10",(u["id"],)
            ).fetchall()]
            c.close()
            return send_json(self,200,{"dashboard":dashboard,"portfolio":portfolio,"simulations":sims})
        return super().do_GET()

    def do_POST(self):
        if self.path=="/api/auth/register":
            try: data=json_body(self)
            except Exception: return send_json(self,400,{"error":"Invalid JSON"})
            email=str(data.get("email","")).strip().lower()
            password=str(data.get("password",""))
            role=str(data.get("role","CEO"))[:40]
            company=str(data.get("company","My Company")).strip()[:100] or "My Company"
            if len(email)<5 or "@" not in email: return send_json(self,400,{"error":"Enter a valid email."})
            if len(password)<6: return send_json(self,400,{"error":"Password must be at least 6 characters."})
            salt,digest=password_hash(password)
            c=db()
            try:
                cur=c.execute("INSERT INTO users(email,password_hash,salt,role,company,created_at) VALUES(?,?,?,?,?,?)",
                              (email,digest,salt,role,company,int(time.time())))
                uid=cur.lastrowid
                c.execute("INSERT INTO state(user_id,dashboard_json,portfolio_json,updated_at) VALUES(?,?,?,?)",
                          (uid,json.dumps(default_dashboard(company)),json.dumps(default_portfolio()),int(time.time())))
                c.commit()
            except sqlite3.IntegrityError:
                c.close(); return send_json(self,409,{"error":"An account with that email already exists."})
            c.close()
            token=login_user(uid)
            return send_json(self,200,{"ok":True,"user":{"id":uid,"email":email,"role":role,"company":company}},
                             {"Set-Cookie":session_cookie(token)})

        if self.path=="/api/auth/login":
            try: data=json_body(self)
            except Exception: return send_json(self,400,{"error":"Invalid JSON"})
            email=str(data.get("email","")).strip().lower()
            password=str(data.get("password",""))
            c=db(); row=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone(); c.close()
            if not row or not verify_password(password,row["salt"],row["password_hash"]):
                return send_json(self,401,{"error":"Email or password is incorrect."})
            token=login_user(row["id"])
            return send_json(self,200,{"ok":True,"user":public_user(row)},
                             {"Set-Cookie":session_cookie(token)})

        if self.path=="/api/auth/logout":
            jar=cookies.SimpleCookie(); jar.load(self.headers.get("Cookie",""))
            morsel=jar.get(COOKIE)
            if morsel:
                c=db(); c.execute("DELETE FROM sessions WHERE token_hash=?",(token_hash(morsel.value),)); c.commit(); c.close()
            return send_json(self,200,{"ok":True},{"Set-Cookie":f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"})

        if self.path=="/api/state":
            u=current_user(self)
            if not u: return send_json(self,401,{"error":"Not authenticated"})
            try: data=json_body(self)
            except Exception: return send_json(self,400,{"error":"Invalid JSON"})
            dashboard=data.get("dashboard",{})
            portfolio=data.get("portfolio",{})
            c=db()
            c.execute("""INSERT INTO state(user_id,dashboard_json,portfolio_json,updated_at)
                         VALUES(?,?,?,?)
                         ON CONFLICT(user_id) DO UPDATE SET
                         dashboard_json=excluded.dashboard_json,
                         portfolio_json=excluded.portfolio_json,
                         updated_at=excluded.updated_at""",
                      (u["id"],json.dumps(dashboard),json.dumps(portfolio),int(time.time())))
            c.commit(); c.close()
            return send_json(self,200,{"ok":True})

        if self.path=="/api/simulations":
            u=current_user(self)
            if not u: return send_json(self,401,{"error":"Not authenticated"})
            try: data=json_body(self)
            except Exception: return send_json(self,400,{"error":"Invalid JSON"})
            summary=data.get("summary",{})
            c=db()
            c.execute("INSERT INTO simulations(user_id,created_at,summary_json) VALUES(?,?,?)",
                      (u["id"],int(time.time()),json.dumps(summary)))
            c.commit(); c.close()
            return send_json(self,200,{"ok":True})

        if self.path=="/api/chat":
            # Keep Ollama local; browser never needs direct access to port 11434.
            length=int(self.headers.get("Content-Length","0"))
            body=self.rfile.read(length)
            try:
                req=Request(OLLAMA,data=body,headers={"Content-Type":"application/json"},method="POST")
                with urlopen(req,timeout=90) as resp:
                    data=resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type","application/json")
                    self.send_header("Content-Length",str(len(data)))
                    self.end_headers(); self.wfile.write(data)
            except HTTPError as e:
                data=e.read(); self.send_response(e.code)
                self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(data)))
                self.end_headers(); self.wfile.write(data)
            except Exception:
                send_json(self,503,{"error":"Ollama is not reachable. Start qwen3:8b first."})
            return

        self.send_error(404,"Not found")

if __name__=="__main__":
    init_db()
    print(f"FinPilot running at http://localhost:{PORT}/FinPilot.html")
    print("SQLite database:",DB_PATH)
    print("Ollama proxy: /api/chat -> http://127.0.0.1:11434/api/chat")
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
