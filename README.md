# FinPilot

**An AI decision-simulation cockpit for small and medium business finance.**
Rehearse a cash crisis before it happens. Make the call, watch the consequence, replay the decision that cost you, and get a multi-agent AI review of how you handled it.

> **Status: Hackathon prototype.** This build is designed to run on one machine (or one local network) for a live demo. It is not a production deployment — see [Prototype Scope & Production Roadmap](#prototype-scope--production-roadmap) below before treating any part of this as a finished product.

---

## What this is

FinPilot puts a business's real numbers — cash on hand, payroll, supplier terms, loan installments — into a live simulation of a cash crisis. Across a horizon the user picks (1 month), the user makes a sequence of hard financial calls: delay a payment, draw a credit line, take on debt, expand, refinance. Each choice has an immediate cash effect and a delayed, realistic consequence. At the end, the app doesn't just say "you survived" or "you crashed" — it **replays every alternative option you could have picked at each decision**, scores your actual choice against the best available alternative, and tells you exactly which decision cost you the most.

A local multi-agent AI layer (Finance, Operations, Risk, and Data agents, synthesized by a Scenario Analyst) then reviews the same simulation state and gives a plain-language debrief — running entirely on your machine, through a local model, with no data leaving the network.

---

## Tech stack & resources used

| Layer | What we used | Why |
|---|---|---|
| **Frontend** | Single-page HTML/CSS/JS (`FinPilot.html`) — no build step, no framework | Fast to iterate on for a hackathon; runs from a static file served by our own backend |
| **Backend** | Python 3 standard library (`http.server`, `sqlite3`) — `server.py` | Zero external dependencies to install; runs anywhere Python 3 runs |
| **Database** | SQLite (`~/.finpilot/finpilot.db`) | Per-user accounts, session tokens, dashboard/portfolio state, and simulation history persist across restarts |
| **Authentication** | Cookie-based sessions, PBKDF2-HMAC-SHA256 password hashing (210,000 iterations), per-account salt | Real password hashing, not plaintext — see [Prototype Scope](#prototype-scope--production-roadmap) for what's still missing before this is production-grade |
| **Generative AI** | [Ollama](https://ollama.com) running **Qwen3:8B** locally, proxied through our own backend (`/api/chat`) so the browser never talks to the model directly | Keeps all business financial data on-device — nothing is sent to a third-party API. Free, no API key, runs on a laptop |
| **Multi-agent AI architecture** | Four fixed-role agents (**Finance, Operations, Risk, Data**) each read the same simulation state and produce a deterministic, grounded finding; a fifth agent (**Scenario Analyst**, LLM-backed) synthesizes their findings into a Key Lesson / Key Trade-off / Next Question summary | A fixed pipeline, not an autonomous/self-directing workflow — the sequence is always known in advance, only the content each agent produces is dynamic. This keeps the simulation's numbers trustworthy (deterministic agents) while still using generative AI where it adds real value (synthesis and plain-language explanation) |
| **Simulation engine** | Deterministic, hand-authored event scheduler in JavaScript — payroll, supplier, and loan cycles recur on a schedule; each decision injects a scripted cash effect plus a delayed consequence | All cash math is rule-based, never LLM-generated, so nothing on screen is hallucinated |
| **Decision-quality scoring** | **Counterfactual replay** — for every decision the user made, the engine re-simulates every other option available at that point (holding all other decisions constant), ranks the outcomes by survival → crash timing → ending cash → minimum cash, and scores the user's actual pick against that ranked field | This is the mechanism behind the "Decision Quality" score and the "Revive" replay feature — it is not a static/hardcoded rating |
| **Fonts** | Space Grotesk (UI), IBM Plex Mono (numeric readouts) via Google Fonts | Aviation-instrument-panel visual language to match the "flight simulator for business finance" concept |
| **Language support** | English, Hindi, Tamil, Telugu — UI chrome (navigation, labels, buttons) | Small business owners across India were the design target for language coverage |

**Why a local model instead of a hosted API?** Business financial data (cash position, payroll, debt) is sensitive. Running Qwen3:8B locally through Ollama means none of it leaves the device or network during the demo, and there's no API key or billing account required for the hackathon build.

---

## What FinPilot is not (be upfront about this)

- It is **not a financial forecast**. Nothing in this app predicts what will actually happen to a real business on a real future date. The simulation injects realistic, domain-informed pressure scenarios so a team can rehearse a decision — closer to a flight simulator's engine-fire drill than a weather forecast. See the AI disclaimers built into every prompt in the app (`analyzePortfolio`, `runAIMultiAgent`, `sendChat`) — each one explicitly instructs the model not to invent prices, returns, or market facts, and to say so when data is missing.
- It is **not regulated financial advice**. The portfolio analyst and chat copilot are explicitly prompted to describe, not recommend — they do not tell a user what to buy, sell, or hold.
- It is **not production-hardened**. See below.

---

## Prototype scope & production roadmap

This build is intentionally scoped for a local demo. Before any real business's data touches this app, the following would need to change:

| Area | Prototype (now) | Production |
|---|---|---|
| **Data storage** | Local SQLite file on one machine, no backup | Managed database with automated backups, encryption at rest |
| **Authentication** | Password + session cookie, no email verification, no account recovery flow | Email verification, password reset, optional MFA, rate-limited login attempts |
| **Transport security** | Plain HTTP, suitable for a local network only (see `README`'s LAN instructions) | HTTPS/TLS everywhere, HSTS, secure cookie flags |
| **AI inference speed & quality** | Local 8B model on a laptop — usable, but noticeably slower and less capable than a hosted frontier model | Hosted inference (with appropriate data-handling agreements) or a larger self-hosted model on real GPU infrastructure, for faster, higher-quality analysis |
| **Multi-tenant isolation** | Single shared SQLite file; fine for a handful of hackathon accounts | Proper multi-tenant data isolation and access controls |
| **Input validation** | Basic length/type checks | Full server-side validation and rate limiting on every endpoint |

---

## Running it locally

1. Install [Ollama](https://ollama.com) and pull the model:
   ```
   ollama pull qwen3:8b
   ollama run qwen3:8b
   ```
   (leave this running in its own terminal)
2. In a second terminal, from this folder:
   ```
   python3 server.py
   ```
3. Open `http://127.0.0.1:8000/FinPilot.html` — or, to demo across multiple devices on the same Wi-Fi (e.g. one device per department input), use the machine's LAN address instead, e.g. `http://<your-local-ip>:8000/FinPilot.html`.

Accounts and simulation history persist in `~/.finpilot/finpilot.db` between restarts.

**Use only these files together:** `FinPilot.html` + `server.py`. This build shows `BUILD · 2026.09.17` under the sidebar brand — if that marker isn't visible, the browser is loading a different copy of `FinPilot.html`.

---

## Project structure

```
FinPilot.html   — the entire frontend: simulation engine, dashboard, AI assistant UI, i18n
server.py       — auth, per-user state, simulation history, and the local Ollama proxy
```
