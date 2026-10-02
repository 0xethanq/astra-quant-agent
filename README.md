<div align="center">

[简体中文](README.zh-CN.md) · [**English**](README.md)

# AstraQuant

### Autonomous OKX-Native Quant Trading Terminal & Multi-Agent Operating System

[![Release](https://img.shields.io/badge/Release-v8.5.0-00E599.svg?style=flat-square)](https://github.com/0xethanq/astra-quant-agent/releases)
[![Website](https://img.shields.io/badge/Site-www.astraquant.tech-6E56CF.svg?style=flat-square)](https://www.astraquant.tech)
[![License](https://img.shields.io/badge/License-AGPLv3%20%2B%20Commons%20Clause-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5%2B-4FC08D.svg?style=flat-square&logo=vuedotjs&logoColor=white)](https://vuejs.org/)
[![Tests](https://img.shields.io/badge/Tests-9.5k%2B%20Passing-brightgreen.svg?style=flat-square)](tests/)
[![Community](https://img.shields.io/badge/Community-LINUX%20DO-F97316.svg?style=flat-square&logo=linux&logoColor=white)](https://linux.do/)

**Named AI seats debate → CIO arbitrates → a physical Python risk pipeline vetoes → OKX receives maker limit orders with atomic conditional protection.**

*Cognition belongs to the models; physical risk control belongs to the base layer. Zero black-box magic.*

[Quick start](#-quick-start) · [Architecture](#-architecture) · [Design principles](#-design-principles) · [Scheduling](#-scheduling) · [Prompt system](#-prompt-system) · [Prompt Caching](#-prompt-caching--session-affinity) · [Risk model](#-risk-model) · [Visual tour](#-visual-tour) · [Deploy](#-deploy) · [Code map](#-code-map)

</div>

> 🌟 **This project is officially launched with, and proudly endorses, the [LINUX DO (linux.do)](https://linux.do/) open-source technical community.**

---

## 🚀 Quick start

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
./setup.sh                  # Interactive onboarding wizard (recommended, 2 minutes)
# Or container launch: ./deploy/docker-start.sh. Bare metal: ./deploy/install.sh && ./start.sh
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
   │ 1 · 7-TIER QUANT FACTOR MATRIX & MICROSTRUCTURE                        │
   │   T0 Basis/Funding · T0.5 Orderflow CVD · T1 L2 Orderbook Depth/OBI     │
   │   T1.5 Options IV Surface/Max Pain · T2 Term Basis · T3 Volume/VWAP     │
   │   T4 MACD Velocity/Acceleration/ADX · News sentiment                    │
   │   → regime label (bull trend / wide chop / liquidity drought / …)       │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 2 · MULTI-MODEL COMMITTEE            (user-defined seats, any provider)│
   │   Trend seat · Momentum seat · Quant-math seat · Macro/news seat        │
   │   cross-examination rounds  →  CIO seat arbitrates one order intent     │
   │   Prompt Caching: shared market/rules prefix (>90% cached)              │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 3 · EXECUTION-LAYER PHYSICAL CHECKS + CIRCUIT BREAKER                  │
   │   data validity · price geometry · R:R floor · daily-loss breaker       │
   │   leverage & margin caps · anti-hedging check · exposure quota          │
   │   ⚠️ any check that cannot be evaluated  =  HARD REJECT                 │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 4 · OKX-NATIVE EXECUTION                                               │
   │   maker / BBO limit · attached TP1 · TP2 · cloud stop-loss legs         │
   │   scale-out (35% at 1.8×ATR) · profit ratchet · time stop (8h)          │
   └────────────────────────────────────────────────────────────────────────┘
```

Every arrow is observable: the full Chain-of-Thought, each seat's transcript, the 7-tier factor snapshot, the physical-check verdict, and the final `policy_hash` are persisted per decision.

---

## 🎯 Design principles

1. **Cognition belongs to the model; physical risk control belongs to the base layer.**
   LLMs and committees hold only the **right to propose**. Before an order reaches an exchange socket it must pass 100% of the Python risk gates. Any physical check that raises or times out causes a **fail-closed block**. Model hallucinations cannot become losses.

2. **Market-regime auto-detection, not curve fitting.**
   Trend-following bleeds in chop; mean-reversion grids blow up in breakouts. Regime is derived continuously from momentum factors and volatility structure, and the active prompt strategy and leverage band adapt with it.

3. **OKX-native by design.**
   One venue, one credential set, one signing path, one order contract. The old venue-abstraction layer is gone: no divergent exchange code paths, no parity claims, no inter-venue matrix. Every entry carries native attached conditional protection from the same single path.

4. **White-box explainability and closed-loop evolution.**
   Every decision records its reasoning chain, debate transcripts, factor evidence, and execution evidence. Four times a day the self-evolution engine mines the **real closed-trade ledger** and distils lessons into long-term heuristic memory — under strict anti-fabrication rules (see [Prompt system](#-prompt-system)).

---

## ⏱ Scheduling

All cadences are declared in one place (`astra_gateway/scheduler.py`), so this table is the contract:

| Job | Cadence | Timeout | What it does |
|---|---|---|---|
| `trader` | **every 15 min** | 1260 s | Full brain cycle: market data → committee → risk gates → OKX execution |
| `news` | every 10 min | 300 s | Harvests and weights macro/crypto headlines for the news seat |
| `factor_library` | every 60 s | 55 s | Refreshes technical & microstructure factor library |
| `self_improvement` | **02:00 / 08:00 / 14:00 / 20:00** | 1200 s | Closed-trade attribution → long-term memory update |
| `daily_briefing` | 08:00 / 20:00 | 600 s | Daily summary, system audit, and cold backup |

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

**Live variable slots** — 8 semantic slots carry the runtime state: `{{decision_timestamp}}` `{{account_balance}}` `{{risk_budget}}` `{{account_positions}}` `{{pending_orders}}` `{{market_matrix}}` `{{news_intelligence}}` `{{trading_memory}}`.

**No raw K-line clutter in the market matrix** — each symbol carries the processed 7-tier factors and market microstructure calculus:
- **T0 · Settlement & Positioning**: Funding rates, Open Interest (OI), and elite long/short ratio.
- **T0.5 · Flow & Pressure**: Cumulative Volume Delta (CVD) orderflow divergence and whale net volume.
- **T1 · Orderbook & Liquidity**: L2 orderbook depth, Order Book Imbalance (OBI), and spread dynamics.
- **T1.5 · Options Surface**: Implied Volatility (IV) smile and Max Pain strike levels.
- **T2 · Term Structure**: Annualized basis yield across delivery expirations.
- **T3 · Institutional Footprint**: Volume-Weighted Average Price (VWAP) bands (±1σ/±2σ) and VPVR POC.
- **T4 · Dynamics & Velocity**: MACD histogram first-order velocity & second-order acceleration, and ADX momentum regime.

Missing data is explicitly flagged as `--` — never falsified or disguised with neutral filler.

📖 Full authoring guide, slot dictionary, and the shipped doctrine: **[`docs/PROMPT_GUIDE.md`](docs/PROMPT_GUIDE.md)**

---

## ⚡ Prompt Caching & Session Affinity

AstraQuant implements an institutional-grade **Prompt Caching & Session Affinity Architecture** designed to drastically cut LLM operational costs and latency during multi-agent council rounds:

1. **Shared Market & Rules Prefix (>90% cached)**: In every cycle, common system doctrine, risk constraints, and the multi-symbol 7-tier factor matrix are positioned in the static prefix. Council seats (Trend, Momentum, Quant, Macro) share this prefix, hitting upstream KV cache with sub-second time-to-first-token.
2. **Monotonic Volatility Hierarchy**: Prompt sections are strictly ordered by update frequency:
   - **Zone 0 (Immutable)**: Role identity, core quant doctrine, and read-only JSON schema.
   - **Zone 1 (Slow-moving)**: 6-hour self-evolution memory and lesson repository.
   - **Zone 2 (Medium-moving)**: 10-minute news intelligence and macro sentiment tags.
   - **Zone 3 (Cycle-moving)**: 15-minute 7-tier factor matrix and symbol technical indicators.
   - **Zone 4 (Fast-moving)**: High-frequency orderbook ticks and milliseconds timestamps.
3. **Claude Ephemeral Breakpoints**: Native injection of `cache_control: {"type": "ephemeral"}` at Zone boundaries for Anthropic models; 64/128-token chunk alignment for OpenAI and DeepSeek models.
4. **Float Anti-Jitter**: Mathematical rounding stabilization prevents minute decimal fluctuations from busting upstream cache keys.
5. **L1 In-Memory + SQLite Persistent Cache**: Eliminates redundant remote roundtrips during council debate and failover sequences.

---

## 🧩 Strategy configuration centers

> *The right to define strategy belongs to the trader, never to hardcoded logic.*

| # | Module | What it governs |
|---|---|---|
| 1 | 🎨 **Prompt Studio** | Edit the four prompt pipelines as ordered modules; inject live slots; duplicate / import / export profiles; anti-poisoning guardrails; the output schema stays locked |
| 2 | 👥 **Multi-Model Committee** | User-defined seats bound to any OpenAI- or Anthropic-compatible provider; voting weights, cross-examination rounds, CIO arbitration |
| 3 | 🛡️ **Execution Checks & Circuit Breaker** | Non-bypassable Python floor: daily-loss circuit breaker, data validity, price geometry and the R:R floor. The model decides entry; the base layer enforces physical safety |
| 4 | 🧬 **Self-Evolution Engine** | 6-hourly closed-trade attribution; distils operational lessons into prompt memory with outlier rejection and anti-fabrication rules |
| 5 | 📦 **Policy Snapshots** | Hashes prompts + doctrine + committee seats + instrument parameters into fingerprints; sub-second atomic rollback; audit `policy_hash` per trade |
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
| Leverage clamp band | `3x – 8x`, tightened per instrument | clamped | clamped |
| Reward:risk floor / cap | `≥ 2.0`, `≤ 5.0` | — | — |
| Stop-loss distance | `1.8x – 2.2x × ATR(1H)` | — | — |
| Scale-out (TP1) | `35% – 50%` via independent `reduceOnly` leg at `1.8 × ATR` | — | — |
| Runner (TP2) | Terminal target; ratchet stop to breakeven after TP1 hit | — | — |
| Stop coverage | **100%** coverage across both legs with attached cloud OCO | — | — |
| Time stop | `8 h` max hold duration | — | — |
| Post-stop cooldown (per instrument) | `15 min` | — | — |
| Max same-direction positions | `4` | — | — |
| Pyramiding | `≤ 2` adds, each `≥ 68%` confidence and `≥ 0.6%` in profit | — | — |
| Minimum entry confidence | `70%` | — | — |

> ⚙️ These are defaults, not dogma: every one of them is editable in the Risk Control Center and takes effect on the next cycle.

---

## 📸 Visual tour

| | |
|---|---|
| **Live trading workstation**<br>![Live trading workstation](docs/images/v850_live_dashboard.png) | **Chain-of-Thought reasoning drawer**<br>![Chain-of-Thought](docs/images/v850_trajectory_cot.png) |
| **7-tier quant factor matrix**<br>![Factor matrix](docs/images/v850_calculus_factors.png) | **Multi-model committee board**<br>![Committee](docs/images/v850_council_board.png) |
| **Visual Prompt Studio**<br>![Prompt Studio](docs/images/v850_prompt_studio.png) | **Self-evolution engine**<br>![Self-evolution](docs/images/v850_self_evolution.png) |
| **Execution risk control**<br>![Risk control](docs/images/v850_risk_control.png) | **Policy snapshots & rollback**<br>![Policy snapshot](docs/images/v850_policy_snapshot.png) |
| **LLM gateway & reasoning config**<br>![LLM hub](docs/images/v850_llm_hub.png) | **Admin control plane**<br>![Admin overview](docs/images/v850_admin_overview.png) |
| **Security & Accounts Plaza**<br>![Security](docs/images/v850_security_plaza.png) | **Trading Matrix Microstructure**<br>![Live trading](docs/images/v850_live_dashboard.png) |

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
# 1) Backend — fast concurrent regression (or quick business gate: tests/trading tests/venues tests/risk)
.venv/bin/pytest tests/ -n auto -q

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
./setup.sh                  # Interactive onboarding wizard (recommended, 2 minutes)
./deploy/docker-start.sh    # == docker compose up -d --build

docker compose ps           # status
docker compose logs -f      # aggregated logs
```

> 💡 The launcher pre-flight-checks for the classic Docker trap where a missing host `./.env` gets silently created as a **directory**, which would make every config save fail. If it happens, the entrypoint refuses to start and prints the exact fix.

### Option B Bare metal

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git
cd astra-quant-agent
sh deploy/install.sh        # creates .venv, upgrades pip, and installs dependencies
./setup.sh                  # creates and hardens .env

cd frontend && npm install && npm run build && cd ..
./start.sh                  # starts Uvicorn on 0.0.0.0:8080
```

Windows: `start.ps1`. Systemd units: `deploy/astra-quant.service`, `deploy/astra-gateway.service`.

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

AstraQuant is distributed under the **[GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE)** with the **[Commons Clause Condition v1.0](LICENSE)** and Special Anti-Scam / Anti-Reskin Addendum.

- 🔓 **Free for Research & Self-Trading**: Full source code available for academic study, individual backtesting, and self-hosted private trading.
- 🛡️ **Network-Use Copyleft (AGPLv3)**: Any modified or derivative version made accessible over a computer network (Web UI, API, or bot service) must release its complete corresponding source code under the same terms.
- 🚫 **No Commercial Resale or Paid Signals (Commons Clause)**: You may not sell the software, package it as closed-source commercial software, or operate paid signal/copy-trading subscription services derived from this software without explicit written permission.
- ⚖️ **Anti-Scam Rider**: Strictly prohibits any use of this project for fraudulent financial schemes, token issuance, or unauthorized commercial endorsement.
