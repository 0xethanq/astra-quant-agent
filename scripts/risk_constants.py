"""ASTRA 执行层风控参数 —— 单一事实源 (Single Source of Truth).

所有硬风控阈值集中在此，按环境变量读取；后台「风控管理页」写入 .env 后，
交易引擎子进程在下一个巡检周期 import 本模块时自动生效（无需重启）。

约定：
- 每个参数的环境变量键以 ASTRA_ 前缀命名，默认值与历史硬编码值完全一致；
- DEFAULTS 表同时被 astra_backend/risk_config.py（管理页 schema）引用，
  防止 UI 默认值与执行层默认值漂移；
- 提示词侧（ai_brain_trader 的 {{risk_budget}} 等）必须从这里取值插值，
  保持「提示词口径 == 代码口径」。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 独立运行（cron/手动）时也要拿到 .env 里的最新风控配置；backend 调度路径下重复加载无害。
try:
    from astra_backend.config import load_dotenv as _load_dotenv
    _load_dotenv(_PROJECT_ROOT / ".env")
except Exception:
    pass


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, "") or default))
    except (TypeError, ValueError):
        return default


# ── 组1 · 仓位与敞口 ──────────────────────────────────────────────
# 最大并发持仓数。0 = 自动跟随标的池容量（历史行为 len(TARGET_INSTRUMENTS)）。
MAX_CONCURRENT_POSITIONS_CAP = _env_int("ASTRA_MAX_CONCURRENT_POSITIONS", 0)
# 同向持仓上限（多/空各自封顶），与提示词「同向单上限」共用同一口径。
MAX_SAME_DIRECTION_POSITIONS = _env_int("ASTRA_MAX_SAME_DIRECTION_POSITIONS", 3)
# 单笔下单保证金占可用余额硬顶。
MAX_MARGIN_EQUITY_RATIO = _env_float("ASTRA_MAX_MARGIN_EQUITY_RATIO", 0.20)
# 单标的累计占用保证金（含金字塔加仓）占可用余额比例上限。
SINGLE_ASSET_EQUITY_RATIO = _env_float("ASTRA_SINGLE_ASSET_EQUITY_RATIO", 0.30)
# 单标的累计保证金绝对封顶（USDT，小资金账户按上面的比例自动收紧）。
MAX_SINGLE_ASSET_MARGIN = _env_float("ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT", 600.0)
# 单笔杠杆区间（AI 在 [下限, 上限] 内按信心自主裁决，执行层强制钳制到区间）。
MAX_LEVERAGE = _env_float("ASTRA_MAX_LEVERAGE", 5.0)
MIN_LEVERAGE = _env_float("ASTRA_MIN_LEVERAGE", 2.0)
# 交叉守卫：下限只允许更保守，不允许越过上限（后台分次保存时的中间态兜底）。
if MIN_LEVERAGE > MAX_LEVERAGE:
    MIN_LEVERAGE = MAX_LEVERAGE

# ── 组2 · 单笔风险 ────────────────────────────────────────────────
# 单笔 1R 风险额占可用余额比例（与池内绝对值取小）。
RISK_PER_TRADE_EQUITY_RATIO = _env_float("ASTRA_RISK_PER_TRADE_RATIO", 0.02)
# 最小盈亏比 R:R 硬底线，低于该值的报价被 order_risk 物理拦截。
MIN_RISK_REWARD_RATIO = _env_float("ASTRA_MIN_RISK_REWARD", 2.0)
# 最大盈亏比 R:R 上限（防把止盈画到天际线导致无法止盈，须 >= MIN_RISK_REWARD）。
MAX_RISK_REWARD_RATIO = _env_float("ASTRA_MAX_RISK_REWARD", 3.5)
if MAX_RISK_REWARD_RATIO < MIN_RISK_REWARD_RATIO:
    MAX_RISK_REWARD_RATIO = MIN_RISK_REWARD_RATIO
# 新开仓最低 AI 置信度门禁。
MIN_ENTRY_CONFIDENCE = _env_float("ASTRA_MIN_ENTRY_CONFIDENCE", 80.0)

# ── 组3 · 止损与熔断 ──────────────────────────────────────────────
# 单笔基准止损 ATR 宽度（× 1H ATR）。
STOP_LOSS_ATR_MULT = _env_float("ASTRA_STOP_LOSS_ATR_MULT", 2.0)
# 单日亏损熔断绝对封顶（USDT）。
MAX_DAILY_LOSS_USDT = _env_float("ASTRA_MAX_DAILY_LOSS_USDT", 150.0)
# 单日亏损熔断占可用余额比例（与绝对封顶取小）。
DAILY_LOSS_EQUITY_RATIO = _env_float("ASTRA_DAILY_LOSS_EQUITY_RATIO", 0.05)
# 最长持仓时间（小时）：超时且波幅不足带宽的横盘仓位触发时间止损平仓。
TIME_STOP_HOURS = _env_float("ASTRA_TIME_STOP_HOURS", 8.0)
# 时间止损横盘判定带宽（×ATR），浮盈绝对值小于该带宽才视为无突破。
TIME_STOP_ATR_BAND = _env_float("ASTRA_TIME_STOP_ATR_BAND", 0.15)
# 止损出局后同标的同向冷静期（分钟）。
STOP_COOLDOWN_MINUTES = _env_int("ASTRA_STOP_COOLDOWN_MINUTES", 30)

# ── 组4 · 顺势金字塔加仓门禁 ─────────────────────────────────────
# 单标的最大顺势加仓次数（0 = 禁止加仓）。
MAX_SCALE_IN_COUNT = _env_int("ASTRA_MAX_SCALE_IN_COUNT", 1)
# 允许加仓的最小底仓浮盈率（0.008 = +0.8%）。
MIN_SCALE_IN_PROFIT_RATIO = _env_float("ASTRA_MIN_SCALE_IN_PROFIT_RATIO", 0.008)
# 加仓必须达到的最低 AI 置信度（%）。
MIN_SCALE_IN_CONFIDENCE = _env_float("ASTRA_MIN_SCALE_IN_CONFIDENCE", 75.0)

# ── 组5 · 持仓退出与分批止盈 ─────────────────────────────────────
# 是否启用分批平仓止盈机制（1 = 开启，0 = 关闭）。
SCALE_OUT_ENABLED = bool(_env_int("ASTRA_SCALE_OUT_ENABLED", 1) > 0)
# 分批平仓比例（默认 0.50 即平仓 50%，锁定本金利润，剩余仓位博大波段）。
SCALE_OUT_RATIO = _env_float("ASTRA_SCALE_OUT_RATIO", 0.50)
# 分批平仓触发浮盈门槛（×ATR，达到该门槛时触发分批落袋，默认 1.2x ATR）。
SCALE_OUT_TRIGGER_ATR = _env_float("ASTRA_SCALE_OUT_TRIGGER_ATR", 1.20)
# 单笔最大止盈 ATR 宽度（× 1H ATR，超出此倍数的止盈单会被执行层平滑收窄钳制，防止止盈过远）。
MAX_TAKE_PROFIT_ATR = _env_float("ASTRA_MAX_TAKE_PROFIT_ATR", 3.50)

# 组合风险总预算（USDT，跨所合算的顶层总闸；0 = 不封顶）。
# 审计⑫(2026-09-13) 注释正名：旧注释承诺「0=自动按持仓上限×单标的封顶派生」，但执行层
# 从未实现该派生（裸 getenv，0→None→无顶）——派生公式只存在于 dashboard 的 UI 展示，
# 属展示启发式而非引擎策略。现引擎侧 budget>0 时按 gross_exposure 跨所合算强制。
PORTFOLIO_RISK_BUDGET_USDT = _env_float("ASTRA_PORTFOLIO_RISK_BUDGET_USDT", 0.0)

# 跨所同向合并敞口上限（USDT；0 = 不限制）。
# 审计 P2-1(2026-09-13)：该键自 US-005 起就写在 settings_store.MANAGED_KEYS（后台可写、
# 可落 .env），但**全仓 0 个读者** —— 设了等于没设，UI 却把它当风控项。现落地为
# execution_router 发送前判定：同向（base 相同且方向一致）已开仓名义额 + 本单名义额
# 超过本上限即拒开（不夹取——敞口超限意味着这笔根本不该发）。
MAX_TOTAL_EXPOSURE_USDT = _env_float("ASTRA_MAX_TOTAL_EXPOSURE_USDT", 0.0)

# ── 默认值表（供后台风控管理页 schema 引用，键 = 环境变量名） ────
# 注意：必须是字面量默认值，绝不能引用上面「已按 .env 解析」的常量——
# 否则后台进程在用户应用过套件后重启，DEFAULTS 会被 .env 污染，
# 导致「均衡波段」套件写入用户当前值、UI「默认」提示失真。
DEFAULTS = {
    "ASTRA_PORTFOLIO_RISK_BUDGET_USDT": 0.0,
    "ASTRA_MAX_TOTAL_EXPOSURE_USDT": 0.0,
    "ASTRA_MAX_CONCURRENT_POSITIONS": 0,
    "ASTRA_MAX_SAME_DIRECTION_POSITIONS": 3,
    "ASTRA_MAX_MARGIN_EQUITY_RATIO": 0.20,
    "ASTRA_SINGLE_ASSET_EQUITY_RATIO": 0.30,
    "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT": 600.0,
    "ASTRA_MIN_LEVERAGE": 2.0,
    "ASTRA_MAX_LEVERAGE": 5.0,
    "ASTRA_RISK_PER_TRADE_RATIO": 0.02,
    "ASTRA_MIN_RISK_REWARD": 2.0,
    "ASTRA_MAX_RISK_REWARD": 3.5,
    "ASTRA_MIN_ENTRY_CONFIDENCE": 80.0,
    "ASTRA_STOP_LOSS_ATR_MULT": 2.0,
    "ASTRA_MAX_DAILY_LOSS_USDT": 150.0,
    "ASTRA_DAILY_LOSS_EQUITY_RATIO": 0.05,
    "ASTRA_TIME_STOP_HOURS": 8.0,
    "ASTRA_TIME_STOP_ATR_BAND": 0.15,
    "ASTRA_STOP_COOLDOWN_MINUTES": 30,
    "ASTRA_MAX_SCALE_IN_COUNT": 1,
    "ASTRA_MIN_SCALE_IN_PROFIT_RATIO": 0.008,
    "ASTRA_MIN_SCALE_IN_CONFIDENCE": 75.0,
    "ASTRA_SCALE_OUT_ENABLED": 1,
    "ASTRA_SCALE_OUT_RATIO": 0.50,
    "ASTRA_SCALE_OUT_TRIGGER_ATR": 1.20,
    "ASTRA_MAX_TAKE_PROFIT_ATR": 3.50,
}

RISK_ENV_KEYS = tuple(DEFAULTS.keys())


def effective_max_positions(pool_size: int) -> int:
    """并发持仓上限 = min(配置值或池容量, 池容量)；同向上限再钳制不超过总仓上限。"""
    pool = max(int(pool_size or 0), 1)
    cap = MAX_CONCURRENT_POSITIONS_CAP
    total = pool if cap <= 0 else max(1, min(cap, pool))
    same = max(1, min(MAX_SAME_DIRECTION_POSITIONS, total))
    return total, same


# ── 两个「绝对封顶 ∩ 权益占比」的 min() 口径（审计 P1-1，2026-09-13）──────────
# 病灶：同一组公式曾存在三份拷贝——ai_factor_trader 本地两份、astra_backend/execution/sizing
# 两份、而提示词构建器（ai_brain_trader）压根没做 min()，只写「权益×5% / 权益×30%」，
# 于是模型看到单标的 1496.82U、日亏 −249.47U，引擎实际执行 600U / −150U（虚高 2.49×/1.66×），
# 而 SYSTEM PROMPT 却要求模型"一切金额以【本周期风险预算】小节为准"。
# 现收敛到此：引擎、执行面、提示词共用同一函数，任何一处改动全链路同步。
def effective_daily_loss_limit(usdt_available: float = None) -> float:
    """单日亏损熔断线 = min(绝对封顶, 可用余额 5%)，小资金账户自动收紧。"""
    cap = MAX_DAILY_LOSS_USDT
    if usdt_available and usdt_available > 0:
        cap = min(cap, max(round(float(usdt_available) * DAILY_LOSS_EQUITY_RATIO, 2), 1.0))
    return cap


def effective_single_asset_margin(usdt_available: float = None) -> float:
    """单标的累计保证金上限 = min(绝对封顶, 可用余额 30%)，与提示词风险预算同口径。"""
    cap = MAX_SINGLE_ASSET_MARGIN
    if usdt_available and usdt_available > 0:
        cap = min(cap, max(round(float(usdt_available) * SINGLE_ASSET_EQUITY_RATIO, 2), 1.0))
    return cap


# ── 单一实例（审计批6）─────────────────────────────────────────────────
# 本文件既能被 `import risk_constants`（scripts/ 在 sys.path 上，交易脚本走这条）
# 也能被 `import scripts.risk_constants`（仓库根在 sys.path 上，后端/测试走这条）导入。
# Python 对这两个名字会创建**两个模块对象**，各自独立读一次 .env，于是"单一事实源"
# 名不副实：测试 `importlib.reload(risk_constants)` 之后，`scripts.risk_constants` 里
# 仍是旧值（反向亦然），而 sizing/execution 引用的是后者。
# 这里把自己同时登记到两个名字下：先执行者胜出，后来者直接命中 sys.modules，不再二次执行。
for _alias in ("risk_constants", "scripts.risk_constants"):
    sys.modules.setdefault(_alias, sys.modules[__name__])
del _alias
