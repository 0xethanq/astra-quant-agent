# AstraQuant Standalone Deployment

ASTRA runs independently of QwenPaw. The product is composed of:

- `astra_backend.app`: standalone FastAPI control plane and read-only monitoring API.
- `astra_gateway.worker`: the AstraQuant-native, single-owner scheduler and durable notification-delivery worker for the 15-minute trader, 60-second factor refresh, 10-minute news refresh, daily reports, evolution review, and nightly backup.
- `scripts/`: strategy and execution modules, run as isolated Python processes.
- `.env` + encrypted ASTRA Secret Store: LLM, OKX API Key, and notification credentials. A complete OKX key trio is required for private requests and trading; public market data needs no credentials.
- Native OKX V5 REST signing: the single private connectivity path for the strategy, control plane, and ledger.

## Install

```sh
sh deploy/install.sh
. .venv/bin/activate
```

The installer creates the Python environment, installs requirements, copies `env.example` only when `.env` is absent, and restricts `.env` to mode `0600`. Node.js/npm is needed only if you build the Vue frontend from source (`cd frontend && npm install && npm run build`), not for backend installation or OKX connectivity.

Set `LLM_*` and a random `ASTRA_SETUP_TOKEN` before the first launch. Open `/admin` to complete administrator setup, then configure **API Key / Secret Key / Passphrase** in Account Access. Create separate **DEMO and LIVE** trios, grant only necessary read/trade permissions (never withdrawal), and bind server IPs where possible. Keep `ASTRA_OKX_ENV=demo` for initial validation.

The admin form stores credentials locally with **Fernet encryption**; **blank fields keep existing values**. Direct `OKX_DEMO_*` / `OKX_LIVE_*` entries in `.env` are a plaintext bootstrapping alternative. Never commit either credentials or encryption material. Both services need access to the same project configuration and secret store under appropriate file permissions.

An incomplete selected profile is **NOT READY**: private operations and trading fail closed. Public REST market data remains available without a key. Server restarts no longer depend on a short-lived login grant: persist `data/astra_secrets.enc` and its matching `data/.astra_secret_key`. Revoked keys, changed IP restrictions, and network faults can still prevent exchange access.

The authenticated `GET /api/v1/admin/okx/runtime` (management session in `X-Astra-Session`) reports `environment`, `mode_configured`, `live_configured`, `demo_configured`, `fingerprint`, `base_url`, `connection: "static-v5-key"`, and `status: "READY" | "NOT_READY"`; `not_ready_reason` is present when unconfigured. This is a **local configuration check**, not an exchange connectivity or permission test. Use a read-only account snapshot to confirm connectivity before enabling trading.

## Docker Deployment (Recommended)

To deploy with zero host dependencies on a remote server:

```sh
# 1. Prepare configuration
cp env.example .env && vim .env

# 2. Build and launch with Docker Compose
docker compose up -d --build
# Or run: ./deploy/docker-start.sh
```

Both `astra-backend` (Web & API) and `astra-gateway` (quant scheduler worker) will start automatically with persistent volumes for `data/`, `logs/`, and `backups/`.

## Run Locally (Native Python)

Terminal 1:

```sh
. .venv/bin/activate
python -m uvicorn astra_backend.app:app --host 0.0.0.0 --port 8080
```

Terminal 2:

```sh
. .venv/bin/activate
python -m astra_gateway.worker
```

The backend exposes only read-only control-plane endpoints:

- `GET /api/v1/health`
- `GET /api/v1/status`
- `GET /api/v1/cache/{decisions|factors|ledger|sentiment|self-improvement}`
- `GET /api/v1/market/{instId}`
- `GET /api/v1/account/positions`

No HTTP trade-trigger endpoint is exposed except the separately enabled, confirmation-protected manual close action. The admin console also supports a protected update check and `git pull --ff-only`; it refuses to update a dirty worktree and never restarts services automatically.

### 分批止盈（Scale-Out）与交易所侧双腿

- 首批止盈（TP1 = 建仓价 ± `ASTRA_SCALE_OUT_TRIGGER_ATR` × 1H ATR）默认在
  **交易所侧**以一条独立 sized `reduceOnly` 算法腿挂出（`ASTRA_SCALE_OUT_LEG_MODE`，
  默认 `always`）：触发是瞬时的，不依赖 15 分钟巡检。
- 真机实测（2026-09-29，模拟盘）：OKX **原生** `closeFraction`（分批止盈）被拒
  `51000 Parameter closeFraction error`；而"多挂一条带 `sz` 的 reduceOnly OCO 腿"
  受理。故本仓用**双腿**实现，不依赖该原生能力。两条腿各自带同一个止损 ⇒
  止损覆盖率恒为 100%（覆盖率统计只认同时带 TP 与 SL 的 reduceOnly 腿）。
- **模型可在持仓中调整止盈**（`position_management.action = UPDATE_TP`，字段
  `suggested_tp1_price` / `suggested_tp2_price`）。默认只允许向有利方向移动且
  变动 ≥ `ASTRA_TP_AMEND_MIN_STEP_ATR` × ATR；分批已发生后只允许调整 tp2。
  允许下调需显式 `ASTRA_TP_ALLOW_ADVERSE=1`（通知与台账会标红）。
- 事件流水：`data/scale_out_events.jsonl`（只追加）。后台台账按平仓单 `clOrdId`
  前缀 `SO` 把"首批分批止盈"与"AI 主动止盈平仓"分开 —— 旧实现按盈亏金额猜原因，
  于是分批止盈一直显示成"目标止盈达成"，看不出它发生过。

### Prompt-cache warm-up is OFF by default

`astra_gateway.worker` used to send a cache keep-alive ping every 4.5 idle minutes. Measured on-box (2026-09-29): the upstream prompt cache does work (an identical 28.4k prompt hits 24544 cached tokens ≈86% on the second call), but its lifetime is minutes while the trader cycle is 15 minutes, the upstream reports in ~4092-token blocks, and only the 7.7k-token stable head is reusable — so a warm-up request always pays full price for its uncacheable tail and costs more than the one block it saves. The warm-up is therefore **off**; `ASTRA_CACHE_WARMUP_MODE=jit` re-enables a per-cycle warm-up (its own token cost is recorded in `model_calls` with `caller=cache_warmer`). Cache hits/misses are now recorded per call (`cached_tokens` / `cache_status` ∈ hit|miss|unreported) and shown on the admin runtime-units page.

## QwenPaw Container Coexistence

When `www.astraquant.tech` is already reverse-proxied into a QwenPaw container, keep QwenPaw on its existing port and let the AstraQuant standalone gateway own port `8080`. `astra_backend.app` mounts the existing dashboard at `/`, while `/admin` and `/api/v1/*` remain AstraQuant-native routes. This preserves the hostname, reverse-proxy rules, dashboard paths, QwenPaw process, and QwenPaw backup layout.

Add the `[program:astra-backend]` block from the container supervisor configuration and restart the container during a maintenance window so supervisord adopts it. Do not run the legacy `astra_backend.dashboard_cache` Uvicorn process at the same time as `astra_backend.app`.

## systemd

Copy `deploy/astra-quant.service` and `deploy/astra-gateway.service` to `/etc/systemd/system/`, update `WorkingDirectory` and `EnvironmentFile`, then:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now astra-quant astra-gateway
```

Before enabling `astra-gateway`, disable the old QwenPaw cron jobs to prevent duplicate execution. Do not run both schedulers simultaneously. The current Gateway worker owns the scheduler; the legacy `astra_backend.scheduler` and `deploy/astra-scheduler.service` are retained only for compatibility and must not run alongside it.

Before starting the Gateway, open `/admin` and verify the selected DEMO key profile and a read-only account snapshot. A `NOT_READY` runtime response means trading must remain disabled; `READY` alone does not prove exchange acceptance or override risk controls. Ensure the dedicated service user can read the project configuration and matching encrypted store/key; do not print their contents for diagnostics.
