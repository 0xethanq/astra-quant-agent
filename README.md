<div align="center">

[简体中文](README.zh-CN.md) · [**English**](README.md)

# AstraQuant

### Autonomous Multi-Exchange Quant Trading Terminal & Multi-Agent Operating System

[![Release](https://img.shields.io/badge/Release-v8.4.0-00E599.svg?style=flat-square)](https://github.com/0xethanq/astra-quant-agent/releases/tag/v8.4.0)
[![Website](https://img.shields.io/badge/Site-www.astraquant.tech-6E56CF.svg?style=flat-square)](https://www.astraquant.tech)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=flat-square)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?style=flat-square)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5%2B-4FC08D.svg?style=flat-square)](https://vuejs.org/)
[![Tests](https://img.shields.io/badge/Tests-10k%2B%20Passing-brightgreen.svg?style=flat-square)](tests/)
[![Community](https://img.shields.io/badge/Community-LINUX%20DO-F97316.svg?style=flat-square&logo=linux&logoColor=white)](https://linux.do/)

**Named AI seats debate → CIO arbitrates the final call → Physical Python risk pipeline vetoes → OKX / Binance / Gate receive live maker limit orders with atomic conditional protection.**

*Cognition belongs to the models; physical risk control belongs to the base layer. Zero black-box magic.*

[Quick start](#-quick-start) · [What it is](#-what-it-is) · [Design principles](#-four-core-design-principles) · [Visual showcase](#-visual-showcase) · [Strategy configuration centers](#-strategy-configuration-centers) · [Capital & risk](#-capital-scaling-and-tiered-risk) · [Deploy](#-deploy) · [Code map](#-code-map-for-developers--handoff-agents) · [Brand & codename](#-brand-and-internal-codename-read-before-renaming)

</div>

> 🌟 **This project is officially launched with, and proudly endorses, the [LINUX DO (linux.do)](https://linux.do/) open-source technical community.**

---

## 🚀 Quick start

Get up and running in **60 seconds**:

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
./deploy/docker-start.sh          # Docker (recommended); for host install run ./deploy/install.sh
```

| Surface | URL | Default Access |
|---|---|---|
| **Trading Workstation** (Dashboard) | `http://localhost:8080/trading` (or `/`) | Public |
| **Admin Control Plane** | `http://localhost:8080/admin/login` | User: `admin` |
| **System Docs & API Specs** | `http://localhost:8080/docs` | Public |

> 🛡️ **Safety first**: AstraQuant boots in **paper / demo simulation mode** by default. It will never touch live exchange funds until you explicitly configure both your **LLM provider keys** and **Exchange API keys**, then switch the environment toggle on `/admin/security`.

---

## 🧭 What it is

AstraQuant is an **institutional-grade, multi-exchange autonomous quant decision and execution operating system** engineered for professional trading desks, prop firms, and systematic crypto traders.

Every **15 minutes**, the autonomous trading brain initiates an execution cycle:
1. **Dynamic Market Regime Detection**: Analyzes cross-venue order books and kinematic calculus derivatives (velocity $v$, acceleration $a$, integral energy $E$, and volatility distributions) to identify macro regimes (e.g. Bull Trend, Wide Chop, Liquidity Flush).
2. **Multi-Model Investment Committee**: Specialized AI seats (Trend, Momentum, Quantitative Math, Macro/News) debate in cross-examination rounds. A Chief Investment Officer (**CIO**) seat synthesizes proposals into an actionable order intent.
3. **Fail-Closed Physical Risk Interception**: Before reaching any exchange gateway, every proposed order must penetrate a non-bypassable, physical Python risk pipeline (order geometry check, minimum risk/reward ratio, 4H counter-trend veto, same-direction exposure quotas).
4. **Three-Venue Parity Execution**: Orders are submitted to **OKX, Binance, and Gate.io** as maker limit orders (or smart market orders), accompanied by atomic native conditional Stop-Loss and Take-Profit brackets (TP1/TP2 + trailing profit ratchets).

```
   ┌──────────────────────────────────────────────────────────────┐
   │                     15-Minute Brain Cycle                    │
   └──────────────────────────────┬───────────────────────────────┘
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │         Market Regime Auto-Detection & Calculus Matrix       │
   │      Velocity v · Acceleration a · Energy E · ADX · Depth    │
   └──────────────────────────────┬───────────────────────────────┘
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │             Multi-Model Investment Committee                 │
   │  Trend Officer · Momentum Officer · Quant Math · CIO Seat    │
   │        (Claude 3.7 / DeepSeek-R1 / GPT-4o / Gemini)          │
   └──────────────────────────────┬───────────────────────────────┘
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │           Fail-Closed Physical Python Risk Pipeline          │
   │   Geometry Check · 2.0R Floor · 4H Trend Veto · Exposure    │
   │           (Any error / timeout = Hard Reject)                │
   └──────────────────────────────┬───────────────────────────────┘
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │               Three-Venue Parity Execution                   │
   │         OKX  ◄──────────►  Binance  ◄──────────►  Gate       │
   │   Maker Limit / BBO · Atomic Native TP1/TP2 · Cloud SL Legs  │
   └──────────────────────────────────────────────────────────────┘
```

---

## 🎯 Four core design principles

1. **Cognition belongs to the model; physical risk control belongs to the base layer.**  
   LLMs and multi-agent committees hold only the **right to propose** trade intents. Before an order touches an exchange socket, it must pass 100% of underlying Python risk gates. If any interceptor raises an exception or times out, position opening is **fail-closed: unconditionally blocked**. This physically eliminates model hallucinations from becoming real-world losses.

2. **Market-regime auto-detection (No curve fitting).**  
   Trend-following strategies bleed out in chops; mean-reversion grids blow up in single-direction breakouts. AstraQuant continuously derives regime state from calculus velocity $v$, acceleration $a$, integral energy $E$, and multi-timeframe volatility distributions, automatically adapting prompt strategies and leverage bands.

3. **Three-venue equal parity.**  
   OKX, Binance, and Gate.io are treated as equal first-class venues. The platform delivers a unified multi-exchange asset view, transparently reconciles one-way and hedge-mode positions, and attaches native conditional protection orders on each venue.

4. **Full white-box explainability & closed-loop self-evolution.**  
   Every single decision records its complete Chain-of-Thought (CoT), seat debate transcripts, calculus features, and venue routing evidence. Every 6 hours, the self-evolution engine mines the real closed-trade ledger, distilling empirical lessons into long-term heuristic memory with anti-bias guardrails and a 7–14 day sharpness half-life.

---

## 📸 Visual showcase

### 1. 🖥️ Live trading workstation & depth chart
Modern obsidian-emerald terminal (`#00E599` emerald accent on deep obsidian slate). Integrates portfolio equity across 3 venues, active position tickets with 100% stop-loss protection coverage, and native KLineChart v10 with real-time multi-target TP1/TP2 and trailing stop lines:

![Trading workstation](docs/images/v840_live_dashboard.png)

---

### 2. 🌊 Chain-of-Thought (CoT) deep reasoning drawer
Press `⌘J` or click **决策轨迹** to inspect the live multi-seat deliberations: kinematic velocity $v$, acceleration $a$, ADX momentum, probability distributions, and the raw CoT drafts:

![Decision trajectory and CoT](docs/images/v840_trajectory_cot.png)

---

### 3. 🌐 Cross-venue causal calculus dynamics matrix
Live mathematical monitoring across the entire instrument universe: real-time prices, 24h price action, 1H velocity $v$, acceleration $a$, ADX trend strength, long/short ratios, and AI consensus recommendations:

![Cross-venue causal calculus matrix](docs/images/v840_calculus_factors.png)

---

### 4. ⚙️ Enterprise admin control plane & telemetry
Real-time operational dashboard monitoring FastAPI engine PID, LLM reasoning latency, 3-venue connection heartbeats, memory usage, and the fail-closed physical risk gate status:

![Admin control plane](docs/images/v840_admin_overview.png)

---

### 5. 🎨 Visual Prompt Studio & dynamic semantic variable slots
Visually compose system core rules and market feature prompts with 9 real-time semantic variable slots (`{{market_regime}}`, `{{market_matrix}}`, `{{risk_budget}}`, `{{news_intelligence}}`, `{{trading_memory}}`, `{{account_positions}}`, …):

![Prompt Studio](docs/images/v840_prompt_studio.png)

---

### 6. 👥 Multi-model investment committee
Seats are 100% user-defined. Independently bind different providers and models to individual seats (e.g. Trend Officer on Claude 3.7, Quant Math on DeepSeek-R1, Arbitrator on Gemini), configure voting weights, and choose Standard, Cross-Examination, or Debate consensus modes:

![Multi-model committee](docs/images/v840_council_board.png)

---

### 7. 🛡️ Fail-closed physical interceptor pipeline
A non-bypassable Python plugin pipeline. Four factory gates: 4H macro-trend filter, confidence gatekeeper, 1H ADX chop filter, and true risk-reward gatekeeper. Test any plugin interactively in the sandbox:

![Fail-closed interceptor pipeline](docs/images/v840_interceptors_failclosed.png)

---

### 8. 📦 Unified policy snapshots & fast rollback
Bundles prompts, interceptors, committee seats, and instrument pools into a single SHA-256 fingerprint (e.g. `v8.4.0@f34844fc`). Supports 0.5-second atomic rollbacks and attaches the active `policy_version` and `policy_hash` to every order:

![Unified policy snapshots](docs/images/v840_policy_snapshot.png)

---

### 9. 🎛️ Execution risk control center
Tune all 26 execution risk knobs with three one-click presets (🛡️ Conservative / ⚖️ Balanced / 🚀 Aggressive Hunter). Supports pure proportional equity scaling with zero hardcoded USD ceilings:

![Execution risk control center](docs/images/v840_risk_control.png)

---

### 10. 🤖 LLM gateway & reasoning config
Connect to OpenAI, Claude, Gemini, DeepSeek, Qwen, and custom OpenAI-compatible gateways. Configure thinking budgets (10s to 1800s for deep CoT models), reasoning effort, and automatic provider failover:

![LLM gateway and reasoning config](docs/images/v840_llm_hub.png)

---

### 11. 🧬 Closed-loop self-evolution engine
Every 6 hours, the engine mines the real closed-trade ledger, calculating profit factor, win rates, and attribution slices. Lessons learned are distilled into prompt memory with outlier rejection and a 7–14 day half-life:

![Self-evolution engine](docs/images/v840_self_evolution.png)

---

### 12. 🔐 Security, venue routing & Strategy Plaza sharing
Manage OKX, Binance, and Gate credentials, toggle between Demo and Live environments with preflight safety checks, and configure privacy-safe Strategy Plaza sharing:

![Security and venue routing](docs/images/v840_security_plaza.png)

---

### 13. 📋 Consolidated system logs & 3-channel Error Center
Unified observability across trading cycles, backend API requests, and scheduler daemons, with a dedicated Error Center for rapid diagnostics:

![System logs and error center](docs/images/v840_decisions_errors.png)

---

## 🧩 Strategy configuration centers

> **"The right to define trading strategy always belongs to the trader, never to hardcoded system logic."**

AstraQuant decouples strategy into nine visual control centers accessible directly from the web admin:

| # | Module | What it governs |
|---|---|---|
| 1 | 🎨 **Prompt Studio** | Visually edit System Rules and User Templates; inject 9 live semantic variables; duplicate profiles, import/export JSON, with anti-prompt-poisoning guardrails |
| 2 | 👥 **Multi-Model Committee** | User-defined seats; independently bind model providers (Claude, DeepSeek, GPT, Gemini); configure voting weights, cross-examination, and CIO arbitration |
| 3 | 🛡️ **Fail-Closed Interceptors** | Non-bypassable Python plugin gates: 4H macro trend, entry confidence, 1H ADX chop filter, 2.0R risk-reward floor; any plugin fault halts position entry |
| 4 | 🧬 **Self-Evolution Engine** | 6-hour closed-trade ledger attribution mining; distils operational insights into prompt memory; outlier rejection, anti-bias rules, 7–14 day sharpness half-life |
| 5 | 📦 **Policy Snapshots** | Hashes prompts + interceptors + committee seats + instrument parameters into SHA-256 fingerprints; 0.5s atomic rollbacks; audits `policy_hash` per trade |
| 6 | 🎛️ **Risk Control Center** | All 26 physical execution knobs configurable via UI; Conservative / Balanced / Aggressive presets; destructive actions require typed confirmation |
| 7 | 🤖 **LLM Gateway** | Multi-provider direct connections; thinking budget from 10s to 1800s for reasoning models; sub-second failover on rate-limits (HTTP 429) or outages |
| 8 | 🌐 **Three-Venue Topology** | Native connectivity to OKX, Binance, and Gate with independent credentials; cross-venue spread, funding fee, and momentum arbitrage matrix |
| 9 | 🧪 **Backtest & Sandboxing** | Multi-instrument portfolio backtesting and sandbox replays executing the exact same Python risk and sizing code paths as live trading |

---

## 💰 Capital scaling and tiered risk

Every risk parameter scales **dynamically with account equity** — eliminating rigid dollar floors so that a 20 USDT demo test and a 10,000+ USDT institutional desk execute with identical precision:

| Metric | Rule (Default Balanced Baseline) | 20 USDT Demo Account | 4,000 USDT Live Account |
| :--- | :--- | ---: | ---: |
| **1R Risk Per Trade** | `min(per-asset cap, equity × 2.0%)` | 0.40 USDT | 80.0 USDT |
| **Max Margin Per Trade** | `equity × 20.0%` | 4.00 USDT | 800.0 USDT |
| **Cumulative Margin Limit** | `equity × 40.0%` | 8.00 USDT | 1,600.0 USDT |
| **Daily Drawdown Circuit Breaker** | `min(500, equity × 5.0%)` | 1.00 USDT | 200.0 USDT |
| **Leverage Clamping Band** | Dynamic by tier (default 3x – 8x) | Clamped to 3x | Clamped to 6x |

---

## 📊 Observability and logging architecture

| Logger | Log File Path | Generating Process | Scope & Coverage |
| :--- | :--- | :--- | :--- |
| `trader` | `logs/ai_factor_trader.log` | Brain cycle daemon | Quotes, committee debate, confidence grading, venue routing, bracket orders, and trailing stop ratchets |
| `backend` | `logs/uvicorn.log` | FastAPI / Uvicorn | REST request/response lifecycles, authentication, CORS, exception traces, and telemetry feeds |
| `scheduler` | `logs/astra_gateway.log` | Scheduler daemon | Distributed lock leases, cron dispatch, heartbeat checks, and log fragment cleanup |
| `audit` | `logs/astra_admin_audit.jsonl` | Security audit subsystem | Append-only JSONL: timestamp, IP, actor, action (logins, password updates, risk tuning, emergency closes) |

> 📈 **Prometheus & Grafana**: See [`deploy/observability/README.md`](deploy/observability/README.md) for pre-built dashboards that visualize `/api/v1/admin/metrics`.

---

## 🧪 Tests and verification gates

Every metric and path documented in this repository is enforced by automated test suites. We treat passing gates as an essential deliverable:

```bash
# 1) Backend: Audit, LLM, UI, and Multi-Venue Contract Gate
.venv/bin/pytest tests/audit tests/llm tests/ui tests/venues -q

# 2) Backend: Full Offline Regression Suite
.venv/bin/pytest tests/ -q

# 3) Frontend: Type Check, Production Bundle Build & Component Tests
cd frontend
npx vue-tsc --noEmit -p tsconfig.app.json
npm run build
node --test tests/*.test.mjs
cd ..
```

> ⚠️ **Python Virtual Environment**: Always execute with `.venv/bin/python` and `.venv/bin/pytest`.

---

<a id="code-map"></a>
## 🗂️ Code map (for developers / handoff agents)

> ⚠️ **Note**: This repository has **never contained an `OPENCODE.md`** — any external prompts pointing to that non-existent file are erroneous. The authoritative entry points are:

| To learn about | Read | Purpose |
|---|---|---|
| **Backend layering** | `astra_backend/README.md` | L0 facade / L1 wiring / L2 routers / L3 domain / L4 subpackages and module extraction guidelines |
| **Runtime scripts & daemons** | `scripts/README.md` | Which file is an entry point vs. a background daemon, root module directory, and dual-spelling import rules |
| **Frontend components & state** | `frontend/src/components/admin/README.md` | Vue 3 components, composables, pinia stores, and trading workstation state machines |
| **Standalone deployment** | `STANDALONE.md` | Local bare-metal deployment, environment variable configuration, and manual service startup |
| **Emergency recovery** | `RECOVERY_GUIDE.md` | Emergency stop procedures, cold data restoration, and process reset playbooks |
| **Prompt engineering** | `docs/PROMPT_GUIDE.md` | Live semantic variable dictionary, band-breathing rules, and investment committee seat templates |
| **Observability** | `deploy/observability/README.md` | Prometheus scrape targets, alert rules, and Grafana dashboard provisioning |

**Architectural gates watching this repository:**
1. `tests/audit/test_directory_docs_current.py`: Ensures every newly created module in subpackages is registered in its `__init__.py` and corresponding `README.md`.
2. `tests/core/test_readme_baseline_numbers.py`: Prevents documented test numbers from rotting by ensuring documented test counts align with AST discovery.
3. `tests/audit/test_doc_paths_are_committed.py`: Verifies that every source path backticked in markdown documentation actually exists and is committed to git.
4. `tests/audit/test_brand_strings_are_consistent.py`: Ensures brand terminology and internal namespaces remain completely consistent across the repository.

---

## 🚀 Deploy

### Option A: 🐳 Docker (Recommended, Zero Host Dependencies)

Packages Python 3.11, compiles the Vue 3 frontend bundle, and orchestrates the web application and background scheduler:

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git
cd astra-quant-agent
cp env.example .env && vim .env        # Configure LLM and exchange credentials
./deploy/docker-start.sh               # Equivalent to: docker compose up -d --build

docker compose ps                      # View container status
docker compose logs -f                 # Follow aggregated logs
```

Both containers configure `restart: unless-stopped` with in-container supervision and internal heartbeats.

### Option B: Bare-Metal / Host Install

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git
cd astra-quant-agent
sh deploy/install.sh                   # Creates .venv and installs Python dependencies
vim .env

source .venv/bin/activate
cd frontend && npm install && npm run build && cd ..

./start.sh                             # Starts Uvicorn on 0.0.0.0:8080 and background daemons
```

*For Windows PowerShell users, run `start.ps1`. Systemd unit templates are located in `deploy/astra-quant.service`.*

---

## 🏷️ Brand and internal codename (read before renaming)

- **Public Brand**: **AstraQuant** (Official website: <https://www.astraquant.tech>; documentation in [README.md](README.md) and [README.zh-CN.md](README.zh-CN.md)).
- **Internal Namespace**: **`astra`** (Python packages `astra_backend`, `astra_gateway`, configuration prefix `ASTRA_*`).

### Intentional legacy markers (Do Not Rename)

Three historical elements are intentionally retained to protect running production data and live user positions (`tests/audit/test_brand_strings_are_consistent.py`):
1. **Exchange leg tags `t-r20sl*` / `t-r20tp*`**: Conditional orders placed before the namespace upgrade remain live on exchange matching engines. `scripts/tag_markers.py` preserves them so the cloud ratchet continues managing them; new orders use `astrasl` / `astratp`.
2. **Encrypted backup archive magic (`R20GCM2` + NUL)**: Existing encrypted backup archives held by users must remain decryptable. New archives are created with `ASTRAGCM`.
3. **`cpa.r20.cn` in test fixtures**: Represents the maintainer's dedicated upstream DNS gateway for LLM endpoints, not a repository namespace.

---

## 🤝 Community & acknowledgements

AstraQuant officially links to and endorses the **[LINUX DO (linux.do)](https://linux.do/)** open-source community:

- 🐧 **Technical soil** — Special thanks to LINUX DO for technical discussions, strategy inspiration, and community feedback.
- 💬 **Join the conversation** — Discuss multi-agent prompt engineering, risk parameters, and live crypto quant execution on [linux.do](https://linux.do/).

---

## ⚠️ Disclaimer

1. This project is **open-source algorithmic trading software and a quantitative research framework**, provided for research, education, and simulation testing only.
2. Cryptocurrency derivatives trading involves substantial risk of capital loss and extreme volatility. Past performance and simulated backtest results do not guarantee future returns.
3. Users must possess adequate risk management knowledge and should thoroughly evaluate strategies in a **DEMO / Paper Trading** environment before deploying real funds.
4. The authors and open-source contributors assume no liability for any financial losses or damages incurred through the use of this software.

---

## 📄 License

Distributed under the [MIT License](LICENSE). Free and open-source.
