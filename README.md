<div align="center">

[简体中文](README.zh-CN.md) · [**English**](README.md)

# AstraQuant

### Autonomous OKX-Native Quant Trading Terminal & Multi-Agent Operating System

[![Release](https://img.shields.io/badge/Release-v8.5.0--preview-00E599.svg?style=flat-square)](https://github.com/0xethanq/astra-quant-agent/releases)
[![Website](https://img.shields.io/badge/Site-www.astraquant.tech-6E56CF.svg?style=flat-square)](https://www.astraquant.tech)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5%2B-4FC08D.svg?style=flat-square&logo=vuedotjs&logoColor=white)](https://vuejs.org/)
[![Tests](https://img.shields.io/badge/Tests-9.5k%2B%20Passing-brightgreen.svg?style=flat-square)](tests/)
[![Community](https://img.shields.io/badge/Community-LINUX%20DO-F97316.svg?style=flat-square&logo=linux&logoColor=white)](https://linux.do/)

**Named AI seats debate → CIO arbitrates → a physical Python risk pipeline vetoes → OKX receives maker limit orders with atomic conditional protection.**

*Cognition belongs to the models; physical risk control belongs to the base layer. Zero black-box magic.*

[Quick start](#-quick-start) · [Architecture](#-architecture) · [Design principles](#-design-principles) · [Scheduling](#-scheduling) · [Prompt system](#-prompt-system) · [Risk model](#-risk-model) · [Visual tour](#-visual-tour) · [Deploy](#-deploy) · [Code map](#-code-map)

</div>

> 🌟 **This project is officially launched with, and proudly endorses, the [LINUX DO (linux.do)](https://linux.do/) open-source technical community.**

---

## 🚀 Quick start

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
./deploy/docker-start.sh     # Docker (recommended). Bare metal: ./deploy/install.sh && ./start.sh
```

| Surface | URL | Access |
|---|---|---|
| **Trading Workstation** | `http://localhost:8080/trading` | Public |
| **Admin Control Plane** | `http://localhost:8080/admin/login` | User `admin` |
| **System Docs & OpenAPI** | `http://localhost:8080/docs` | Public |

> 🛡️ **Safety first.** AstraQuant boots in **demo / paper mode** and will not touch live funds until you configure **both** LLM provider keys **and** OKX API keys, then flip the environment toggle on `/admin/security`. Until a complete key trio exists for the selected environment the system reports `NOT READY` and refuses all trading.

---

## 🏛 Architecture

One 15-minute cycle, four hard boundaries. Everything below the line is ordinary Python you can read, test, and patch:

```text
                    ┌───────────────────────────────────────────────┐
                    │        Scheduler · 15-minute brain cycle       │
                    │  trader · news(10m) · factors(60s) · evolve(6h)│
                    └───────────────────────┬───────────────────────┘
                                            ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 1 · MARKET REGIME & CALCULUS                                           │
   │   velocity v · acceleration a · impulse I · energy ∫E · deviation ∫A   │
   │   probability (skew / kurtosis / VaR / CVaR) · ADX · depth · OI · news │
   │   → regime label (bull trend / wide chop / low-velocity range / …)      │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 2 · MULTI-MODEL COMMITTEE            (user-defined seats, any provider)│
   │   Trend seat · Momentum seat · Quant-math seat · Macro/news seat        │
   │   cross-examination rounds  →  CIO seat arbitrates one order intent     │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 3 · FAIL-CLOSED PHYSICAL RISK PIPELINE        (non-bypassable Python)  │
   │   data validity · price geometry · R:R floor · 4H direction veto        │
   │   leverage & margin caps · exposure quota · interceptor plugins         │
   │   ⚠️ any exception or timeout  =  HARD REJECT (never "open anyway")     │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 4 · OKX-NATIVE EXECUTION                                               │
   │   maker / BBO limit · attached TP1 · TP2 · cloud stop-loss legs         │
   │   scale-out (35% at 2.0×ATR) · profit ratchet · time stop (8h)          │
   └────────────────────────────────────────────────────────────────────────┘
```

Every arrow is observable: the full Chain-of-Thought, each seat's transcript, the calculus snapshot, the interceptor verdicts, and the final `policy_hash` are persisted per decision.

---

## 🎯 Design principles

1. **Cognition belongs to the model; physical risk control belongs to the base layer.**
   LLMs and committees hold only the **right to propose**. Before an order reaches an exchange socket it must pass 100% of the Python risk gates. Any interceptor that raises or times out causes a **fail-closed block**. Model hallucinations cannot become losses.

2. **Market-regime auto-detection, not curve fitting.**
   Trend-following bleeds in chop; mean-reversion grids blow up in breakouts. Regime is derived continuously from calculus and volatility structure, and the active prompt strategy and leverage band adapt with it.

3. **OKX-native by design.**
   One venue, one credential set, one signing path, one order contract. The old venue-abstraction layer is gone: no divergent exchange code paths, no parity claims, no inter-venue matrix. Every entry carries native attached conditional protection from the same single path.

4. **White-box explainability and closed-loop evolution.**
   Every decision records its reasoning chain, debate transcripts, calculus features, and execution evidence. Four times a day the self-evolution engine mines the **real closed-trade ledger** and distils lessons into long-term heuristic memory — under strict anti-fabrication rules (see [Prompt system](#-prompt-system)).

---

## ⏱ Scheduling

All cadences are declared in one place (`astra_gateway/scheduler.py`), so this table is the contract:

| Job | Cadence | Timeout | What it does |
|---|---|---|---|
| `trader` | **every 15 min** | 1260 s | Full brain cycle: market data → committee → risk gates → OKX execution |
| `news` | every 10 min | 300 s | Harvests and weights macro/crypto headlines for the news seat |
| `factor_library` | every 60 s | 55 s | Refreshes the technical-factor library |
| `self_improvement` | **02:00 / 08:00 / 14:00 / 20:00** | 1200 s | Closed-trade attribution → long-term memory update |
| `daily_briefing` | 08:00 / 20:00 | 600 s | Daily summary and backup |

---

## 🎨 Prompt system

> **This is the part most people get wrong about AstraQuant, so it is stated plainly.**

**All prompt text lives in one file** — `data/prompt_library.json` (the shipped baseline, git-tracked; your edits go to `data/prompt_library.local.json`). There is **no prompt prose in Python**.

| Piece | Owned by | Editable? |
|---|---|---|
| **Output JSON schema** — the machine contract for the model's reply | **Code** (`scripts/ai_brain_trader.py`) | ❌ **Read-only**: the studio disables it, the API rejects changes, and the renderer re-inserts it if deleted |
| Role, doctrine, entry rules, rhythm rules, task lists, review rules | `data/prompt_library.json` | ✅ Fully editable in the visual Prompt Studio |
| Live data (price matrix, positions, budget, memory, news) | Code, regenerated each cycle | injected through `{{slot}}` variables |

**Why the schema is read-only.** It is not documentation — it is the contract the parser depends on. Renaming one field can make an entire decision cycle fail to parse. It therefore ships with the code and moves only by release, never by a studio edit.

**Why prose left Python.** The same text used to exist in three copies (Python constants, the JSON baseline, and your local edits). Changing one left the others stale, which surfaced as *"I edited it in the studio but the live prompt never changed."* One source of truth removes that whole failure class.

**Live variable slots** — 8 semantic slots carry the runtime state: `{{decision_timestamp}}` `{{account_balance}}` `{{risk_budget}}` `{{account_positions}}` `{{pending_orders}}` `{{market_matrix}}` `{{news_intelligence}}` `{{trading_memory}}` (24 variables in total across all pipelines, including the evolution pipeline's ledger slots).

📖 Full authoring guide, slot dictionary, and the shipped doctrine: **[`docs/PROMPT_GUIDE.md`](docs/PROMPT_GUIDE.md)**

---

## 🧩 Strategy configuration centers

> *The right to define strategy belongs to the trader, never to hardcoded logic.*

| # | Module | What it governs |
|---|---|---|
| 1 | 🎨 **Prompt Studio** | Edit the four prompt pipelines as ordered modules; inject live slots; duplicate / import / export profiles; anti-poisoning guardrails; the output schema stays locked |
| 2 | 👥 **Multi-Model Committee** | User-defined seats bound to any OpenAI- or Anthropic-compatible provider; voting weights, cross-examination rounds, CIO arbitration |
| 3 | 🛡️ **Fail-Closed Interceptors** | Non-bypassable Python plugin gates (4H macro direction, entry confidence, ADX chop filter, R:R floor). Any plugin fault halts entry |
| 4 | 🧬 **Self-Evolution Engine** | 6-hourly closed-trade attribution; distils operational lessons into prompt memory with outlier rejection and anti-fabrication rules |
| 5 | 📦 **Policy Snapshots** | Hashes prompts + interceptors + committee seats + instrument parameters into fingerprints; sub-second atomic rollback; audit `policy_hash` per trade |
| 6 | 🎛️ **Risk Control Center** | All **27** physical execution knobs configurable from the UI, with conservative / balanced / aggressive presets and typed confirmation on destructive actions |
| 7 | 🤖 **LLM Gateway** | Multi-provider connections; thinking budget up to 1800 s for reasoning models; failover on rate limits (HTTP 429) or outages |
| 8 | 🌐 **OKX Connectivity** | Native OKX V5 with separate demo / live credential profiles; funding, open interest, and momentum analytics |
| 9 | 🧪 **Backtest & Sandbox** | Multi-instrument portfolio backtests and sandbox replays that execute the **same** Python risk and sizing code paths as live trading |

---

## 💰 Risk model

Every parameter scales with **account equity** — a 20 USDT demo and a 10,000 USDT desk run identical logic. Values below are the shipped *balanced* baseline and are the same constants the executor enforces (`scripts/risk_constants.py`):

| Rule | Formula / value | 20 USDT demo | 4,000 USDT live |
| :--- | :--- | ---: | ---: |
| Risk per trade (1R) | `min(per-asset cap, equity × 4.5%)` | 0.90 USDT | 180 USDT |
| Max margin per trade | `equity × 40%` | 8.00 USDT | 1,600 USDT |
| Single-asset cumulative margin | `equity × 48%` | 9.60 USDT | 1,920 USDT |
| Daily drawdown circuit breaker | `min(500 USDT, equity × 10%)` | 2.00 USDT | 400 USDT |
| Leverage clamp band | `6x – 12x`, tightened per instrument | clamped | clamped |
| Reward:risk floor / cap | `≥ 2.0`, `≤ 5.0` | — | — |
| Stop-loss distance | `2.0 × ATR(1H)` | — | — |
| Take-profit distance cap | `≤ 4.5 × ATR` | — | — |
| Scale-out | `35%` of the base position at `2.0 × ATR` | — | — |
| Time stop | `8 h` | — | — |
| Post-stop cooldown (per instrument) | `15 min` | — | — |
| Max same-direction positions | `5` | — | — |
| Pyramiding | `≤ 2` adds, each `≥ 68%` confidence and `≥ 0.6%` in profit | — | — |
| Minimum entry confidence | `68%` | — | — |

> ⚙️ These are defaults, not dogma: every one of them is editable in the Risk Control Center and takes effect on the next cycle.

---

## 📸 Visual tour

| | |
|---|---|
| **Live trading workstation**<br>![Live trading workstation](docs/images/v840_live_dashboard.png) | **Chain-of-Thought reasoning drawer**<br>![Chain-of-Thought](docs/images/v840_trajectory_cot.png) |
| **Causal calculus dynamics**<br>![Calculus factors](docs/images/v840_calculus_factors.png) | **Multi-model committee board**<br>![Committee](docs/images/v840_council_board.png) |
| **Visual Prompt Studio**<br>![Prompt Studio](docs/images/v840_prompt_studio.png) | **Self-evolution engine**<br>![Self-evolution](docs/images/v840_self_evolution.png) |
| **Fail-closed interceptors**<br>![Interceptors](docs/images/v840_interceptors_failclosed.png) | **Policy snapshots & rollback**<br>![Policy snapshot](docs/images/v840_policy_snapshot.png) |
| **Execution risk control**<br>![Risk control](docs/images/v840_risk_control.png) | **LLM gateway & reasoning config**<br>![LLM hub](docs/images/v840_llm_hub.png) |
| **Admin control plane**<br>![Admin overview](docs/images/v840_admin_overview.png) | **Security & Strategy Plaza**<br>![Security](docs/images/v840_security_plaza.png) |

---

## 📊 Observability

| Logger | Path | Emitted by | Scope |
| :--- | :--- | :--- | :--- |
| `trader` | `logs/ai_factor_trader.log` | Brain cycle daemon | Quotes, debate, confidence grading, orders, brackets, trailing ratchets |
| `backend` | `logs/uvicorn.log` | FastAPI / Uvicorn | Request lifecycle, auth, CORS, exceptions, telemetry |
| `scheduler` | `logs/astra_gateway.log` | Scheduler daemon | Lock leases, cron dispatch, heartbeats, log pruning |
| `audit` | `logs/astra_admin_audit.jsonl` | Security subsystem | Append-only JSONL: time, IP, actor, action |

Both Docker containers run an in-container watchdog and expose health checks, because `restart:` only covers *exits* — a hung-but-alive process would otherwise go unnoticed.

> 📈 **Prometheus & Grafana**: pre-built dashboards in [`deploy/observability/README.md`](deploy/observability/README.md) visualise `/api/v1/admin/metrics`.

---

## 🧪 Tests

Documentation claims in this repository are backed by automated gates; passing them is part of the deliverable.

```bash
# 1) Backend — full offline regression (structural gates, LLM contract, venue contract, UI)
.venv/bin/pytest tests/ -q

# 2) Frontend — type check, production bundle, component tests
cd frontend
npx vue-tsc --noEmit -p tsconfig.app.json
npm run build
node --test tests/*.test.mjs
```

> ⚠️ Always use `.venv/bin/python` and `.venv/bin/pytest` — this repository deliberately does **not** rely on a global Python.

---

## 🚀 Deploy

### Option A 🐳 Docker (recommended — zero host dependencies)

Packages Python 3.11, compiles the Vue 3 bundle, and runs the web app plus the scheduler:

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git
cd astra-quant-agent
cp env.example .env && vim .env      # configure LLM + OKX credentials
./deploy/docker-start.sh             # == docker compose up -d --build

docker compose ps                    # status
docker compose logs -f               # aggregated logs
```

> 💡 The launcher pre-flight-checks for the classic Docker trap where a missing host `./.env` gets silently created as a **directory**, which would make every config save fail. If it happens, the entrypoint refuses to start and prints the exact fix.

### Option B Bare metal

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git
cd astra-quant-agent
sh deploy/install.sh                 # creates .venv and installs dependencies
vim .env

cd frontend && npm install && npm run build && cd ..
./start.sh                           # starts Uvicorn on 0.0.0.0:8080
```

Windows: `start.ps1`. Systemd units: `deploy/astra-quant.service`, `deploy/astra-gateway.service`, `deploy/astra-scheduler.service`.

---

<a id="code-map"></a>
## 🗂 Code map

> ⚠️ This repository has **never contained an `OPENCODE.md`** — external prompts pointing at that path are erroneous. The authoritative entry points are:

| To learn about | Read |
|---|---|
| **Architecture & module layout** | [`docs/STRUCTURE_OVERVIEW.md`](docs/STRUCTURE_OVERVIEW.md) |
| **Backend layering (L0→L4)** | [`astra_backend/README.md`](astra_backend/README.md) |
| **Runtime scripts & daemons** | [`scripts/README.md`](scripts/README.md) |
| **Prompt engineering** | [`docs/PROMPT_GUIDE.md`](docs/PROMPT_GUIDE.md) |
| **Failure semantics (why each gate exists)** | [`docs/FAILURE_SEMANTICS.md`](docs/FAILURE_SEMANTICS.md) |
| **Beijing-time contract** | [`docs/BEIJING_TIME_CONTRACT.md`](docs/BEIJING_TIME_CONTRACT.md) |
| **Frontend components & state** | [`frontend/src/components/admin/README.md`](frontend/src/components/admin/README.md) |
| **Standalone deployment** | [`STANDALONE.md`](STANDALONE.md) |
| **Emergency recovery** | [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md) |
| **Observability** | [`deploy/observability/README.md`](deploy/observability/README.md) |

**Gates watching this repository:**

| Gate | What it prevents |
|---|---|
| `tests/audit/test_directory_docs_current.py` | A module existing without being registered in its `__init__.py` **and** its `README.md` |
| `tests/core/test_readme_baseline_numbers.py` | Documented test counts rotting away from reality |
| `tests/audit/test_doc_paths_are_committed.py` | Documentation pointing at paths that do not exist or are not committed |
| `tests/audit/test_brand_strings_are_consistent.py` | Brand / namespace drift that would break live production data |
| `tests/audit/test_deployment_scripts_are_sound.py` | Startup or Docker scripts that cannot actually start the project |

---

## 🏷 Brand and internal codename (read before renaming)

- **Public brand**: **AstraQuant** — <https://www.astraquant.tech>
- **Internal namespace**: **`astra`** (packages `astra_backend`, `astra_gateway`; config prefix `ASTRA_*`)

### Intentional legacy markers — do not rename

Three historical markers are retained to protect live production data and open positions (`tests/audit/test_brand_strings_are_consistent.py`):

1. **Exchange leg tags `t-r20sl*` / `t-r20tp*`** — conditional orders placed before the namespace upgrade are still live on the matching engine. `scripts/tag_markers.py` preserves them so cloud ratchets keep managing them; new orders use `astrasl` / `astratp`.
2. **Encrypted backup magic `R20GCM2` + NUL** — existing user archives must remain decryptable. New archives use `ASTRAGCM`.
3. **`cpa.r20.cn` in test fixtures** — the maintainer's upstream DNS gateway for LLM endpoints, not a repository namespace.

---

## 🤝 Community

AstraQuant officially links to and endorses the **[LINUX DO (linux.do)](https://linux.do/)** open-source community.

- 🐧 **Technical soil** — thanks to LINUX DO for discussion, strategy inspiration, and feedback.
- 💬 **Join in** — multi-agent prompt engineering, risk parameters, live crypto quant execution.

---

## ⚠️ Disclaimer

1. This project is **open-source algorithmic trading software and a quantitative research framework**, for research, education, and simulation only.
2. Crypto derivatives trading carries substantial risk of loss and extreme volatility. Past performance and backtests do not guarantee future returns.
3. Users must understand risk management and should validate strategies in a **DEMO / paper** environment before deploying real funds.
4. The authors and contributors accept no liability for financial losses arising from use of this software.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
