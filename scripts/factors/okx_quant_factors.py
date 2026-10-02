"""OKX 核心量化因子引擎（7 梯队）—— 替代"微积分/定积分/概率论"数理噱头。

## 为什么新增这个模块

旧因子库的 Pillar 6/7/8 把离散 K 线序列套上连续物理学的导数与积分
（速度 v、加速度 a、冲量 I、做功 E、偏离面积 A、条件延续概率、高阶矩），
再让大模型据此裁决多空。实盘复盘显示：这些量**噪音大、滞后、且没有可交易的
经济学含义** —— 真正决定盈亏的是**资金博弈、清算踩踏、订单流意图与筹码成本中枢**。

本模块落地 `okx_factor_library.md` 的 7 梯队因子，并给出经研究标定的时段与参数：

| 梯队 | 因子分类 | 本模块落地的因子 | 数据来源（**逐个实测过**） |
|---|---|---|---|
| T0 | 衍生品持仓与杠杆 | 当期资金费率 / 预测资金费率 / OI 总量 / 1H ΔOI / 全网账户多空比 / **精英账户多空比** / **精英持仓多空头寸比** / 清算脉冲 | OKX 公开 REST |
| T0.5 | 主动流动性与订单流 | 5M/1H CVD、Taker 买卖比、CVD 量价背离 | OKX Rubik 公开 REST |
| T1 | 盘口与微观清算结构 | 订单簿失衡度 OBI、Top5/Top20 深度比、有效点差 bps | OKX 公开 REST |
| T1.5 | 期权微观结构 | ATM IV、25d Risk Reversal 偏度、**Put/Call OI 比** | OKX 公开 REST（仅 BTC/ETH） |
| T2 | 结构与宏观资金利差 | 季度交割合约基差年化率、杠杆借贷利率 | OKX 公开 REST（仅 BTC/ETH） |
| T3 | 筹码分布与统计中枢 | 24H 滚动 VWAP、±1σ/±2σ 带、VPVR 筹码密集峰 POC | **本地 K 线计算** |
| T4 | 动量确认与波动挤压 | 1H MACD(12,26,9) 柱/加速度/顶底背离、1H+15M RSI(14) 动态区间、布林带宽挤压 | **本地 K 线计算** |

### 实测确认的官方端点（2026-10 逐条 curl 验证）

| 用途 | 端点 |
|---|---|
| 资金费率（含 `nextFundingRate`） | `/api/v5/public/funding-rate` |
| OI 快照 | `/api/v5/public/open-interest` |
| **ΔOI 官方小时序列** | `/api/v5/rubik/stat/contracts/open-interest-history?instId=…&period=1H` → `[ts, oi, oiCcy, oiUsd]` |
| 全网账户多空比 | `/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=…` |
| **精英账户多空比** | `/api/v5/rubik/stat/contracts/long-short-account-ratio-contract-top-trader?instId=…` |
| **精英持仓多空头寸比** | `/api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader?instId=…` |
| CVD / Taker 比 | `/api/v5/rubik/stat/taker-volume?ccy=…&instType=CONTRACTS` |
| 清算明细 | `/api/v5/public/liquidation-orders?instType=SWAP&uly=…&state=filled` |
| **Put/Call OI 比** | `/api/v5/rubik/stat/option/open-interest-volume-ratio?ccy=…` → `[ts, oiRatio, volRatio]` |
| 期权链（IV / Delta / fwdPx） | `/api/v5/public/opt-summary?instFamily=…` |
| 季度合约元数据与价格 | `/api/v5/public/instruments?instType=FUTURES&uly=…` + `/api/v5/market/ticker` |
| 指数价（基差基准） | `/api/v5/market/index-tickers?instId=…` |
| 杠杆借贷利率 | `/api/v5/public/interest-rate-loan-quota` |

> **列不出来的两项，如实标注**：`Liquidation Heatmap`（清算热力密集区距离）是
> 第三方由清算数据反推的构造物，OKX 官方不提供；`Max Pain` 需要"按行权价的 OI"
> 分布接口（`option/open-interest-volume-strike` 实测返回 400，参数口径未公开），
> 故一律显式返回 `--` + reason，**不用 0 冒充**。

## ⚠️ 顺手修掉一个真缺陷：Taker 买卖列被读反了

OKX 官方文档原文：*"The data returned will be arranged in an array like this:
`[ts, sellVol, buyVol]`"* —— 即**索引 1 是卖出、索引 2 是买入**。
旧门面写的是 `b_vol = data[0][1]; s_vol = data[0][2]`，于是提示词里的
「5M主动吃单净差」**符号整体颠倒**（主动买入被显示成净卖出）。
本模块按官方口径读取，并由测试钉住。

## 时段与参数标定（研究结论，写在常量里可测）

- **MACD 基准参数 = (12, 26, 9)，跑在 1H**：加密市场 24/7 交易，但过快参数
  （5,13,3）在日内震荡里频繁假交叉；标准参数是机构共识最强、假信号最少的一档。
- **RSI(14) 跑 1H 与 15M**：静态 30/70 在单边趋势里必然失效（牛市 RSI 长期
  65~80，照 70 做空必被扫）。故本模块输出 **情境自适应区间** `rsi_zone`
  （多头 38~52 低吸区 / 空头 46~62 做空区 / 箱体 32/68 极值区）。
- **VWAP 窗口 = 24H（96 根 15M）**，价值区 = VWAP ± 1.0σ（约 70% 成交量），
  统计极值带 = VWAP ± 2.0σ（约 95%）；**VPVR 用 30 个价格桶**取最大成交量桶中点作 POC。
- **ΔOI 用 OKX `open-interest-volume` 官方小时序列**（不是自己攒快照），
  与 1H 价格变动组成**衍生品四象限**（真突破 / 空头回补 / 真跌破 / 多头清算）。

## 契约（三条，必须守住）

1. **取数失败 = 显式缺失**：任何接口失败一律回落到默认结构里的 `--` / `available=False`
   / 中性值，并在 `reason` 里写明原因；**绝不用 0 或 50 冒充真实信号**
   （那会让前端把"没有数据"渲染成"信号中性"）。
2. **K 线一律 newest-first 传入**（OKX 原始顺序），模块内部 `reversed` 成时间正序；
   忘了 reverse 不会报错，只会静默算错 —— 与 `candles_15m.py` 同一约定。
3. **纯计算与取数分离**：`compute_*` / `classify_*` 全部是离线可测的纯函数；
   `fetch_*` 才碰网络，并带 TTL 缓存避免同一轮多标的重复打同一个池级接口。

> ⚠️ 本模块**不 import 门面**（`scripts/factor_library.py`），只被门面调用。
> 门面里的 `patch.object(fetch_candles)` 缝不受影响：K 线仍由门面取回后传进来。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

from astra_backend.math_utils import safe_float as _sf

__all__ = [
    "MACD_FAST", "MACD_SLOW", "MACD_SIGNAL",
    "VWAP_WINDOW_15M", "VPVR_BUCKETS", "VALUE_AREA_SIGMA", "EXTREME_BAND_SIGMA",
    "FUNDING_CROWDED_PCT", "FUNDING_EXTREME_PCT", "OI_FLAT_THRESHOLD_PCT",
    "OBI_STRONG_BID_PCT", "OBI_STRONG_ASK_PCT",
    "derive_series", "macd_series", "compute_macd_factors", "classify_rsi_zone",
    "detect_divergence", "compute_rsi_factors", "compute_vwap_volume_profile",
    "compute_cvd_factors", "classify_derivatives_quadrant", "compute_depth_factors",
    "annualized_basis_pct", "compute_options_factors", "classify_funding_crowding",
    "fetch_derivatives_snapshot", "fetch_option_snapshot", "fetch_loan_rate_snapshot",
    "fetch_quarterly_basis_inputs", "apply_derivatives_tier", "apply_orderflow_tier",
    "apply_microstructure_tier", "apply_volume_profile_tier", "apply_momentum_tier",
]

# ---------------------------------------------------------------------------
# 参数常量（研究结论，测试逐条钉住）
# ---------------------------------------------------------------------------

#: 1H MACD 基准参数（机构共识最强、假交叉最少的一档）
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
#: 顶底背离的观察窗口（1H 根数）
DIVERGENCE_LOOKBACK = 20
#: 24H 滚动 VWAP 窗口（96 根 15M = 24 小时）
VWAP_WINDOW_15M = 96
#: VPVR 价格桶数量
VPVR_BUCKETS = 30
#: 价值区带（约 70% 成交量）
VALUE_AREA_SIGMA = 1.0
#: 统计极值带（约 95%）
EXTREME_BAND_SIGMA = 2.0
#: 资金费率拥挤门槛（当期费率绝对值，单位 %）——0.03% 即年化约 32.9%
FUNDING_CROWDED_PCT = 0.03
#: 资金费率极端门槛（%）
FUNDING_EXTREME_PCT = 0.05
#: ΔOI 视为"有效增/减仓"的门槛（%）
OI_FLAT_THRESHOLD_PCT = 1.5
#: OBI（订单簿失衡度）强买/强卖墙门槛（%）
OBI_STRONG_BID_PCT = 20.0
OBI_STRONG_ASK_PCT = -20.0
#: CVD 背离观察窗口（1H 根数）
CVD_DIVERGENCE_LOOKBACK = 6

_OKX_HOSTS = ("https://www.okx.com", "https://aws.okx.com")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

#: 中性缺失占位（与 defaults.py 的 `--` 语义一致：缺失就该大声缺）
_NA = "--"


# ---------------------------------------------------------------------------
# 池级接口的 TTL 缓存
# ---------------------------------------------------------------------------
#
# 为什么需要：`factor_library.py` 用线程池并发跑 8 个标的，而
# `loan-quota`（全局）、`opt-summary`（按 instFamily）、
# `instruments?instType=FUTURES`（按 ccy）都是**池级**数据 ——
# 每个标的各打一次会白烧 8 倍配额（OKX 公共行情按 IP 限频 40req/2s）。
# TTL 缓存让"同一轮"只打一次，且**不影响**"失败必须留痕"的语义。

_CACHE: Dict[str, Tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: str, ttl: float) -> Any:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > ttl:
        return None
    return value


def _cache_put(key: str, value: Any) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)


def _reset_cache_for_tests() -> None:
    """测试专用（生产不调用）：清空 TTL 缓存 **并关闭 Rubik 限频等待**。

    为什么连限频一起关：打桩的测试里每个 Rubik 路由都会"成功返回"，
    于是记账生效、后续调用真的各睡 0.42s —— 实测把
    `tests/ops/test_factor_library.py` 从 3s 拖到 33s（CPU 只用了 3s）。
    生产间隔由 `_RUBIK_MIN_INTERVAL` 常量决定，测试要验节流行为时
    自己 `mock.patch.object(qf, "_RUBIK_MIN_INTERVAL", 真实值)` 即可。
    """
    global _RUBIK_MIN_INTERVAL
    with _CACHE_LOCK:
        _CACHE.clear()
    with _RUBIK_LOCK:
        _RUBIK_LAST_AT[0] = 0.0
        _RUBIK_MIN_INTERVAL = 0.0


#: OKX Rubik 系列限频为 **5 次 / 2 秒**（按 IP），而本引擎每标的要打 5 个 Rubik
#: 接口（全网多空比 + 精英账户比 + 精英持仓比 + Taker 5m + Taker 1H），
#: 6 标的池 = 30 次/轮 —— 实测突发会把其中一两次打成 429 并**静默退化成 0**
#: （实盘快照里 `cvd_1h_usd` 长期为 0、`taker_buy_sell_ratio` 恒为 1.0 就是这个原因）。
#: 故进程内串行节流到 0.42s 一次（≈ 4.8 次/2s，留出余量）。
_RUBIK_MIN_INTERVAL = 0.42
_RUBIK_LOCK = threading.Lock()
_RUBIK_LAST_AT = [0.0]


def _throttle_rubik(path: str) -> None:
    """Rubik 路径的进程内节流（非 Rubik 路径零开销）。

    ⚠️ 这里**只等待、不记账**：记账在 `_mark_rubik_called()`，且只在
    "请求真的到达了服务器"（拿到响应或拿到 HTTP 状态码）时才记。
    理由有两层：

    1. 正确的限频口径是"**交易所收到的请求数**" —— DNS 解析失败 / 连接被拒的
       本地失败根本没占用配额，不该让后续请求为它排队；
    2. 测试里所有外呼都是打桩的（`urlopen` 直接抛 OSError），若在等待处记账，
       同一进程内每测一次都要真睡 0.42s —— 实测把 `tests/ops/test_factor_library.py`
       从 3 秒拖到 **5 分钟**（user CPU 只有 1.8s，全在 `time.sleep`）。
    """
    if "/rubik/" not in path:
        return
    with _RUBIK_LOCK:
        wait = _RUBIK_MIN_INTERVAL - (time.time() - _RUBIK_LAST_AT[0])
        if wait > 0:
            time.sleep(wait)


def _mark_rubik_called(path: str) -> None:
    """记录一次"确实到达服务器"的 Rubik 调用（本地失败不记，见上）。"""
    if "/rubik/" not in path:
        return
    with _RUBIK_LOCK:
        _RUBIK_LAST_AT[0] = time.time()


def _public_get(path: str, params: Optional[Dict[str, Any]] = None,
                timeout: float = 4.0, *, cache_key: Optional[str] = None,
                ttl: float = 0.0) -> Optional[List[Any]]:
    """www → aws 双域直连取 OKX 公开数据；全失败返回 `None`（调用方显式降级）。

    `cache_key` + `ttl`（可选）给**慢变量**用：带 TTL 的接口在一轮里不会重复外呼，
    直接减少 Rubik 限频压力（见 `_RUBIK_MIN_INTERVAL` 的注释）。
    只缓存**成功**结果 —— 失败不缓存，下一轮会重试（不许把一次抖动固化 5 分钟）。
    """
    if cache_key:
        hit = _cache_get(cache_key, ttl)
        if hit is not None:
            return hit
    query = ""
    if params:
        query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
    for host in _OKX_HOSTS:
        url = f"{host}{path}{query}"
        # 429（按 IP 限频）**指数退避重试**：直接吞掉会静默退化成"因子为 0/中性"
        # （实盘已观测到 1H taker 长期取空）。三次尝试后仍失败才走下一个主机。
        for attempt, backoff in enumerate((0.0, 0.5, 1.5, 0.0)):
            if backoff:
                time.sleep(backoff)
            _throttle_rubik(path)
            try:
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                _mark_rubik_called(path)      # 服务器确实收到了这次请求
                if str(payload.get("code")) == "0":
                    data = payload.get("data")
                    if isinstance(data, list) and cache_key:
                        _cache_put(cache_key, data)
                    return data if isinstance(data, list) else None
                break
            except urllib.error.HTTPError as exc:
                _mark_rubik_called(path)      # 有状态码 ⇒ 也到了服务器（如 429）
                if exc.code == 429 and attempt < 2:
                    continue
                break
            except Exception:
                break                       # 本地失败 ⇒ 不记账、不占用限频额度
    return None


# ---------------------------------------------------------------------------
# T4 · 动量：MACD / RSI / 背离（纯计算）
# ---------------------------------------------------------------------------

def derive_series(raw_candles: Sequence[Sequence[Any]]
                  ) -> Tuple[List[float], List[float], List[float], List[float]]:
    """OKX newest-first 原始 K 线 → `(closes, highs, lows, vols)` **时间正序**。

    ⚠️ `reversed` 必须保留：忘了它不会抛异常，只会让所有指标按反向时间算。
    """
    chron = list(reversed(list(raw_candles)))
    closes = [_sf(c[4]) for c in chron]
    highs = [_sf(c[2]) for c in chron]
    lows = [_sf(c[3]) for c in chron]
    vols = [_sf(c[5]) for c in chron]
    return closes, highs, lows, vols


def macd_series(closes: Sequence[float], fast: int = MACD_FAST,
                slow: int = MACD_SLOW, signal: int = MACD_SIGNAL
                ) -> Tuple[List[float], List[float], List[float]]:
    """返回 `(dif, dea, hist)` 三条**完整序列**（用于背离检测）。

    与 `astra_backend.execution.calc_macd_histogram_acceleration` **同源同种子**
    （首值取 `prices[0]`），故其末值与该函数返回值逐位一致 ——
    这条一致性由测试钉住，防止两处漂移出两个不同的 MACD。
    """
    if not closes:
        return [], [], []
    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_sig = 2.0 / (signal + 1)

    fast_ema = _sf(closes[0])
    slow_ema = _sf(closes[0])
    dif: List[float] = []
    for p in closes:
        px = _sf(p)
        fast_ema = px * k_fast + fast_ema * (1 - k_fast)
        slow_ema = px * k_slow + slow_ema * (1 - k_slow)
        dif.append(fast_ema - slow_ema)

    dea: List[float] = []
    sig_ema = dif[0]
    hist: List[float] = []
    for m in dif:
        sig_ema = m * k_sig + sig_ema * (1 - k_sig)
        dea.append(sig_ema)
        hist.append(m - sig_ema)
    return dif, dea, hist


def detect_divergence(closes: Sequence[float], oscillator: Sequence[float],
                      lookback: int = DIVERGENCE_LOOKBACK, *, eps: float = 1e-9) -> str:
    """窗口内价格与振荡器（MACD 柱 / RSI）的**顶底背离**。

    算法（刻意简单、可解释、无参数魔法）：把最近 `lookback` 根二分，
    比较两半的极值点及其对应的振荡器值 ——

    - 价格**创更低低点**、振荡器低点却**抬高** ⇒ `BULLISH`（空头动能衰竭）；
    - 价格**创更高高点**、振荡器高点却**走低** ⇒ `BEARISH`（多头动能衰竭）。

    样本不足或数值退化一律返回 `NONE`（不猜）。
    """
    eff_lb = max(1, int(lookback)) if lookback is not None else DIVERGENCE_LOOKBACK
    n = min(len(closes), len(oscillator), eff_lb)
    if n < 6:
        return "NONE"
    px = [_sf(v) for v in closes[-n:]]
    osc = [_sf(v) for v in oscillator[-n:]]
    half = n // 2

    first_px, second_px = px[:half], px[half:]
    first_osc, second_osc = osc[:half], osc[half:]

    i_low_1 = min(range(len(first_px)), key=lambda i: first_px[i])
    i_low_2 = half + min(range(len(second_px)), key=lambda i: second_px[i])
    if px[i_low_2] < px[i_low_1] - eps and osc[i_low_2] > osc[i_low_1] + eps:
        return "BULLISH"

    i_high_1 = max(range(len(first_px)), key=lambda i: first_px[i])
    i_high_2 = half + max(range(len(second_px)), key=lambda i: second_px[i])
    if px[i_high_2] > px[i_high_1] + eps and osc[i_high_2] < osc[i_high_1] - eps:
        return "BEARISH"
    return "NONE"


def classify_macd_momentum_state(macd_hist: Optional[float],
                                 macd_accel: Optional[float]) -> str:
    """MACD 柱与加速度组成的四态动能（供形态与提示词直接引用）。

    ⚠️ 缺失（`None`）⇒ `INSUFFICIENT_DATA`，**不许**退化成 `NEUTRAL`
    —— 那会被读成"真实的中性动量"（2026-10「不许假数据」审计）。
    """
    if macd_hist is None or macd_accel is None:
        return "INSUFFICIENT_DATA"
    h = _sf(macd_hist)
    a = _sf(macd_accel)
    if h > 0:
        return "BULL_EXPANDING" if a > 0 else "BULL_EXHAUSTING"
    if h < 0:
        return "BEAR_EXPANDING" if a < 0 else "BEAR_EXHAUSTING"
    return "NEUTRAL"


def compute_macd_factors(closes_1h: Sequence[float], price: float = 0.0) -> Dict[str, Any]:
    """1H MACD 因子块（柱、加速度、四态、顶底背离）。

    ## 为什么要输出"占现价 %"（2026-10 实盘暴露的展示事故）

    MACD 柱/加速度都是**价格单位**的量：BTC 柱=27.88，而 ARB 柱=−1.8e−05。
    前端按两位小数渲染 ⇒ ARB/DOGE 显示成 `-0.00 / 0.00`，看上去像"没有动能"
    （实盘截图就是这样）。而两者其实是同一量级的信息（ARB 柱/价 = −0.0089%）。

    ⇒ 同时给出**归一化**口径 `macd_hist_pct` / `macd_accel_pct`（柱 ÷ 现价 × 100），
    使 6 个标的可横向比较、且不受价格量级影响。价格缺失（≤0）时归一化键给 `None`
    —— 与全仓"缺失即缺失"同纪律，不用 0 冒充。

    ⚠️ **K 线不足时不许给 0**（2026-10 实测踩到）：MACD(12,26,9) 需要
    `slow + signal = 35` 根收盘价；调用方若只取 24 根，原实现会静默返回
    「柱=0、加速度=0、态=NEUTRAL」—— 那会被下游读成**真实的中性动量**
    （实盘快照里就是这样：BTC 1H MACD 恒为 0，而 RSI 正常）。
    现在改为显式缺失：数值键 `None`、状态 `INSUFFICIENT_DATA`。
    """
    dif, dea, hist = macd_series(closes_1h)
    px = _sf(price)
    if len(hist) < MACD_SLOW + MACD_SIGNAL:
        return {
            "macd_dif": None, "macd_dea": None, "macd_hist": None, "macd_accel": None,
            "macd_hist_pct": None, "macd_accel_pct": None,
            "macd_momentum_state": "INSUFFICIENT_DATA",
            "macd_divergence": "INSUFFICIENT_DATA",
        }
    accel = hist[-1] - hist[-2]
    return {
        "macd_dif": round(dif[-1], 6),
        "macd_dea": round(dea[-1], 6),
        "macd_hist": round(hist[-1], 6),
        "macd_accel": round(accel, 6),
        "macd_hist_pct": (round(hist[-1] / px * 100.0, 4) if px > 0 else None),
        "macd_accel_pct": (round(accel / px * 100.0, 4) if px > 0 else None),
        "macd_momentum_state": classify_macd_momentum_state(hist[-1], accel),
        "macd_divergence": detect_divergence(closes_1h, hist),
    }


def mark_momentum_missing(factors: Dict[str, Any]) -> None:
    """T4 输入缺失时把 `trend_momentum` 的 MACD/RSI 键**显式标缺失**。

    ⚠️ 2026-10 实盘：调用点原先是 `if closes_1h: apply_momentum_tier(...)`，**没有 else**
    ⇒ 1H K 线取不到时，`trend_momentum` 会留着 `build_default_factors` 的伪中性默认值
    （柱=0.0、加速度=0.0、RSI=50.0、态=NEUTRAL）并被下游当成**真实的中性动量**读走
    （看板上表现为"柱 0.00 / RSI 50"，看着像没动能，其实是没数据）。

    同一个教训在 `compute_macd_factors` 里已经吃过一次（K 线不足 ⇒ 返回 None +
    `INSUFFICIENT_DATA`）；这里补齐**调用点**那一层。
    """
    tm = factors.setdefault("trend_momentum", {})
    for key in ("macd_dif", "macd_dea", "macd_hist", "macd_accel",
                "macd_hist_pct", "macd_accel_pct"):
        tm[key] = None
    tm["macd_momentum_state"] = "INSUFFICIENT_DATA"
    # ★ 背离同纪律：`NONE` 是"已检测且无背离"这个**结论**，缺失就该说缺失
    tm["macd_divergence"] = "INSUFFICIENT_DATA"
    for key in ("rsi_1h", "rsi_15m"):
        tm[key] = None
    tm["rsi_zone"] = "INSUFFICIENT_DATA"
    tm["rsi_divergence"] = "INSUFFICIENT_DATA"


def mark_volume_profile_missing(factors: Dict[str, Any]) -> None:
    """T3 输入缺失时把筹码分布键显式标缺失（同理：别让 0.0 假装"价格就在 VWAP 上"）。"""
    vp = factors.setdefault("volume_profile", {})
    for key in ("vwap_24h", "vwap_upper_1", "vwap_lower_1", "vwap_upper_2",
                "vwap_lower_2", "vwap_bias_pct", "poc_price", "poc_distance_pct",
                "value_area_high", "value_area_low"):
        if key in vp:
            vp[key] = None


def classify_rsi_zone(rsi: float, trend: str) -> str:
    """情境自适应 RSI 区间（静态 30/70 在单边趋势里必然失效）。

    - 多头大势：`38~52` 回踩低吸区 / `52~72` 健康运行区 / `>75` 超买禁追区；
    - 空头大势：`46~62` 反弹做空区 / `28~46` 健康运行区 / `<25` 超卖禁追区；
    - 箱体震荡：`<=32` 超跌区 / `>=68` 超买区 / 其余中性。
    """
    if rsi is None:
        return "INSUFFICIENT_DATA"      # 缺失不许退化成"中性区间"
    r = _sf(rsi)
    t = str(trend or "").upper()
    if "BULL" in t:
        if r > 75.0:
            return "OVERBOUGHT_NO_CHASE"
        if 52.0 <= r <= 72.0:
            return "BULL_HEALTHY"
        if 38.0 <= r < 52.0:
            return "BULL_PULLBACK_BUY"
        return "NEUTRAL"
    if "BEAR" in t:
        if r < 25.0:
            return "OVERSOLD_NO_CHASE"
        if 28.0 <= r <= 46.0:
            return "BEAR_HEALTHY"
        if 46.0 < r <= 62.0:
            return "BEAR_RALLY_SELL"
        return "NEUTRAL"
    if r <= 32.0:
        return "RANGE_OVERSOLD"
    if r >= 68.0:
        return "RANGE_OVERBOUGHT"
    return "NEUTRAL"


def compute_rsi_factors(closes_1h: Sequence[float], closes_15m: Sequence[float],
                        trend: str) -> Dict[str, Any]:
    """1H/15M RSI(14) + 情境区间 + 1H 顶底背离。

    RSI 数值沿用门面既有口径（最近 14 根简单均值）——**不引入第二套 RSI 定义**。
    """
    def _rsi(closes: Sequence[float]) -> Optional[float]:
        vals = [_sf(c) for c in closes]
        if len(vals) < 15:
            # ★ 原实现返回 50.0 ⇒ 提示词显示"RSI=50.0 (中性)"，而打分侧
            #   `rsi >= 50 ⇒ +15` 会因此**凭空加 15 分趋势分**（2026-10 审计）。
            return None
        diffs = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
        gains = [d if d > 0 else 0.0 for d in diffs[-14:]]
        losses = [-d if d < 0 else 0.0 for d in diffs[-14:]]
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14
        rs = (avg_g / avg_l) if avg_l > 0 else 100.0
        return round(100.0 - (100.0 / (1.0 + rs)), 1)

    rsi_1h = _rsi(closes_1h)
    rsi_15m = _rsi(closes_15m)
    rsi_series: List[float] = []
    vals = [_sf(c) for c in closes_1h]
    for end in range(15, len(vals) + 1):
        seg = vals[:end]
        diffs = [seg[i] - seg[i - 1] for i in range(1, len(seg))]
        gains = [d if d > 0 else 0.0 for d in diffs[-14:]]
        losses = [-d if d < 0 else 0.0 for d in diffs[-14:]]
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14
        rs = (avg_g / avg_l) if avg_l > 0 else 100.0
        rsi_series.append(100.0 - (100.0 / (1.0 + rs)))
    return {
        "rsi_1h": rsi_1h,
        "rsi_15m": rsi_15m,
        "rsi_zone": classify_rsi_zone(rsi_1h, trend),
        "rsi_divergence": (detect_divergence(vals, rsi_series) if rsi_series
                           else "INSUFFICIENT_DATA"),
    }


# ---------------------------------------------------------------------------
# T3 · 筹码分布：24H 滚动 VWAP ± σ 带 与 VPVR POC（纯计算）
# ---------------------------------------------------------------------------

def compute_vwap_volume_profile(raw_candles_15m: Sequence[Sequence[Any]], price: float,
                                *, window: int = VWAP_WINDOW_15M,
                                buckets: int = VPVR_BUCKETS) -> Dict[str, Any]:
    """24H 滚动 VWAP 统计分布 + VPVR 筹码密集峰。

    - VWAP / σ 用**典型价** `(h+l+c)/3` 与成交量加权；
    - 价值区 `VAH/VAL = VWAP ± 1.0σ`（约 70% 成交量）、极值带 `± 2.0σ`（约 95%）；
    - POC = 把窗口高低区间等分 `buckets` 桶后**成交量最大的桶中点**（主力成本峰）。
    """
    closes, highs, lows, vols = derive_series(raw_candles_15m)
    n = min(len(closes), window)
    # ★ 缺失 ⇒ `None`（提示词渲染 `--`）：0.0 的 VWAP/POC 会被读成"价位在 0"
    #   或"无筹码峰"，`NEUTRAL` 会被读成"位置中性"——都是假结论。
    out: Dict[str, Any] = {
        "vwap_24h": None, "vwap_sigma_pct": None, "vah": None, "val": None,
        "vpvr_poc": None, "value_area_position": "INSUFFICIENT_DATA",
        "vwap_extreme_band": "INSUFFICIENT_DATA",
    }
    if n < 10:
        return out
    closes, highs, lows, vols = closes[-n:], highs[-n:], lows[-n:], vols[-n:]
    typ = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    total_v = sum(vols)
    if total_v <= 0:
        return out

    vwap = sum(typ[i] * vols[i] for i in range(n)) / total_v
    var = sum(vols[i] * (typ[i] - vwap) ** 2 for i in range(n)) / total_v
    sigma = var ** 0.5
    sigma_pct = (sigma / vwap * 100.0) if vwap > 0 else 0.0

    lo, hi = min(lows), max(highs)
    poc = 0.0
    if hi > lo and buckets > 0:
        width = (hi - lo) / buckets
        hist = [0.0] * buckets
        for i in range(n):
            idx = int((typ[i] - lo) / width)
            idx = 0 if idx < 0 else (buckets - 1 if idx >= buckets else idx)
            hist[idx] += vols[i]
        best = max(range(buckets), key=lambda k: hist[k])
        poc = lo + (best + 0.5) * width

    px = _sf(price)
    pos = "NEUTRAL"
    band = "NONE"
    if vwap > 0 and sigma > 0 and px > 0:
        z = (px - vwap) / sigma
        if z >= EXTREME_BAND_SIGMA:
            band = "UPPER_EXTREME"
        elif z <= -EXTREME_BAND_SIGMA:
            band = "LOWER_EXTREME"
        elif z >= VALUE_AREA_SIGMA:
            band = "UPPER_VALUE_AREA"
        elif z <= -VALUE_AREA_SIGMA:
            band = "LOWER_VALUE_AREA"
        else:
            band = "INSIDE_VALUE_AREA"
        if px > vwap:
            pos = "ABOVE_VWAP"
        elif px < vwap:
            pos = "BELOW_VWAP"

    return {
        "vwap_24h": round(vwap, 6),
        "vwap_sigma_pct": round(sigma_pct, 4),
        "vah": round(vwap + VALUE_AREA_SIGMA * sigma, 6),
        "val": round(vwap - VALUE_AREA_SIGMA * sigma, 6),
        "vpvr_poc": round(poc, 6),
        "value_area_position": pos,
        "vwap_extreme_band": band,
    }


# ---------------------------------------------------------------------------
# T0.5 · 订单流：CVD / Taker 比 / 量价背离（纯计算）
# ---------------------------------------------------------------------------

def compute_cvd_factors(taker_rows_5m: Optional[Sequence[Sequence[Any]]],
                        taker_rows_1h: Optional[Sequence[Sequence[Any]]],
                        closes_1h: Sequence[float],
                        *, lookback: int = CVD_DIVERGENCE_LOOKBACK) -> Dict[str, Any]:
    """主动成交净差（CVD）与 Taker 买卖比，并按 1H 量价方向判背离。

    行格式（OKX Rubik taker-volume，newest-first）：`[ts, sellVol, buyVol]`
    —— ⚠️ 索引 1 是**卖出**、索引 2 是**买入**，写反不会报错、只会把方向整体颠倒。
    """
    # ★ 2026-10「不许假数据」：缺失一律 `None`（提示词渲染 `--`），
    #   不用 0.0/1.0 冒充"零净流/买卖均衡"，也不用 "NONE" 冒充"无背离"。
    out: Dict[str, Any] = {
        "cvd_5m_usd": None, "cvd_1h_usd": None, "taker_buy_sell_ratio": None,
        "cvd_divergence": "INSUFFICIENT_DATA",
    }

    def _row_delta(row: Sequence[Any]) -> Tuple[float, float]:
        sell = _sf(row[1]) if len(row) > 1 else 0.0
        buy = _sf(row[2]) if len(row) > 2 else 0.0
        return buy, sell

    if taker_rows_5m:
        buy, sell = _row_delta(taker_rows_5m[0])
        out["cvd_5m_usd"] = round(buy - sell, 2)
    if taker_rows_1h:
        buy, sell = _row_delta(taker_rows_1h[0])
        out["cvd_1h_usd"] = round(buy - sell, 2)
        out["taker_buy_sell_ratio"] = round(buy / sell, 4) if sell > 0 else None

    # 量价背离：窗口内价格方向 vs 逐根 CVD 累积方向
    rows = list(reversed(list(taker_rows_1h or [])))
    n = min(len(rows), len(closes_1h), lookback + 1)
    if n >= 4:
        out["cvd_divergence"] = "NONE"        # 有数据才能说"无背离"
        seg_rows = rows[-n:]
        seg_px = [_sf(c) for c in list(closes_1h)[-n:]]
        deltas = []
        for r in seg_rows:
            buy, sell = _row_delta(r)
            deltas.append(buy - sell)
        cvd_delta = sum(deltas)
        px_delta = seg_px[-1] - seg_px[0]
        if px_delta > 0 and cvd_delta < 0:
            out["cvd_divergence"] = "BEARISH"   # 价涨但主动买盘净流出 ⇒ 隐蔽派发
        elif px_delta < 0 and cvd_delta > 0:
            out["cvd_divergence"] = "BULLISH"   # 价跌但主动买盘净流入 ⇒ 隐蔽吸筹
    return out


# ---------------------------------------------------------------------------
# T0 · 衍生品：费率拥挤度 / ΔOI 四象限 / 清算脉冲（纯计算 + 分类）
# ---------------------------------------------------------------------------

def classify_funding_crowding(funding_rate_pct: Optional[float]) -> str:
    """资金费率拥挤度：`|rate|` 超门槛即标记（年化 0.03% ≈ 32.9%）。

    ⚠️ 缺失 ⇒ `INSUFFICIENT_DATA`：`NEUTRAL` 会被读成"费率不拥挤"（是个结论）。
    """
    if funding_rate_pct is None:
        return "INSUFFICIENT_DATA"
    r = _sf(funding_rate_pct)
    if r >= FUNDING_EXTREME_PCT:
        return "EXTREME_LONG_CROWDED"
    if r <= -FUNDING_EXTREME_PCT:
        return "EXTREME_SHORT_CROWDED"
    if r >= FUNDING_CROWDED_PCT:
        return "LONG_CROWDED"
    if r <= -FUNDING_CROWDED_PCT:
        return "SHORT_CROWDED"
    return "NEUTRAL"


def classify_derivatives_quadrant(price_chg_pct: Optional[float],
                                  oi_chg_pct: Optional[float],
                                  *, flat: float = OI_FLAT_THRESHOLD_PCT) -> str:
    """价变 × ΔOI 的四象限（区分"真突破"与"踩踏虚动"）。

    | 价 | ΔOI | 含义 | 本函数返回 |
    |---|---|---|---|
    | 涨 | 增 | 主力真金白银开多，真突破 | `LONG_BUILDUP` |
    | 涨 | 减 | 空头爆仓被动回补，虚涨 | `SHORT_COVERING` |
    | 跌 | 增 | 主力主动重金压盘，真跌破 | `SHORT_BUILDUP` |
    | 跌 | 减 | 多头踩踏清算，恐慌出清 | `LONG_LIQUIDATION` |
    """
    if price_chg_pct is None or oi_chg_pct is None:
        return "INSUFFICIENT_DATA"      # 缺失不许退化成"四象限中性"
    p = _sf(price_chg_pct)
    o = _sf(oi_chg_pct)
    if abs(o) < flat:
        return "NEUTRAL"
    if p >= 0 and o > 0:
        return "LONG_BUILDUP"
    if p >= 0 and o < 0:
        return "SHORT_COVERING"
    if p < 0 and o > 0:
        return "SHORT_BUILDUP"
    return "LONG_LIQUIDATION"


def classify_elite_divergence(retail_ratio: Optional[float],
                              elite_ratio: Optional[float]) -> str:
    """散户（全网账户比）与**精英账户比**的分歧诊断。

    - 散户 > 1.6 且精英 < 0.95 ⇒ `RETAIL_TRAP`（散户死扛多、主力反手空）；
    - 散户 < 0.8 且精英 > 1.25 ⇒ `SMART_ACCUMULATION`（散户交筹码、主力吸筹）；
    - 两者同向 ⇒ `ALIGNED_LONG` / `ALIGNED_SHORT`；
    - 数据缺失 ⇒ `INSUFFICIENT_DATA`（2026-10 修正：原先返回 `NEUTRAL`，
      会被读成"已诊断且无分歧"这个**结论**，属于假数据）。
    """
    if retail_ratio is None or elite_ratio is None:
        return "INSUFFICIENT_DATA"
    r = _sf(retail_ratio, 1.0)
    e = _sf(elite_ratio, 1.0)
    if r > 1.6 and e < 0.95:
        return "RETAIL_TRAP"
    if r < 0.8 and e > 1.25:
        return "SMART_ACCUMULATION"
    if r > 1.1 and e > 1.1:
        return "ALIGNED_LONG"
    if r < 0.9 and e < 0.9:
        return "ALIGNED_SHORT"
    return "NEUTRAL"


def summarize_liquidations(liq_details: Optional[Sequence[Dict[str, Any]]],
                           ct_val: float) -> Tuple[float, float, str]:
    """清算明细 → `(long_liq_usd, short_liq_usd, bias)`。

    `posSide=long` 表示**多头被清算**（强制卖出，利空踩踏）；
    `posSide=short` 表示**空头被清算**（强制买入，轧空反抽）。
    """
    long_usd = 0.0
    short_usd = 0.0
    if ct_val is None or _sf(ct_val) <= 0:
        # 合约面值未知 ⇒ 张→U 的折算会**整体错一个倍数**，宁可显式缺失
        return None, None, "INSUFFICIENT_DATA"
    cv = _sf(ct_val)
    for row in (liq_details or []):
        if not isinstance(row, dict):
            continue
        sz = _sf(row.get("sz"))
        px = _sf(row.get("bkPx"))
        notional = abs(sz) * cv * px
        if str(row.get("posSide")).lower() == "long":
            long_usd += notional
        elif str(row.get("posSide")).lower() == "short":
            short_usd += notional
    if long_usd > short_usd * 1.5 and long_usd > 0:
        bias = "LONG_CASCADE"
    elif short_usd > long_usd * 1.5 and short_usd > 0:
        bias = "SHORT_SQUEEZE"
    else:
        bias = "BALANCED"
    return round(long_usd, 2), round(short_usd, 2), bias


def annualized_basis_pct(futures_px: float, index_px: float,
                         exp_time_ms: Any, now_ms: Any) -> float:
    """季度交割合约基差年化率（%）。到期不足一天或价格非法 ⇒ 0.0。"""
    f = _sf(futures_px)
    i = _sf(index_px)
    exp = _sf(exp_time_ms)
    now = _sf(now_ms) or time.time() * 1000.0
    if f <= 0 or i <= 0 or exp <= now:
        return 0.0
    days = (exp - now) / 86400000.0
    if days < 0.5:
        return 0.0
    return round((f - i) / i * 100.0 * (365.0 / days), 4)


# ---------------------------------------------------------------------------
# T1 · 盘口微观结构（纯计算）
# ---------------------------------------------------------------------------

def compute_depth_factors(depth: Optional[Dict[str, Any]], price: float,
                          *, top_n: int = 20,
                          min_multi_order_levels: int = 3) -> Dict[str, Any]:
    """订单簿失衡度 OBI / Top5 与 Top20 深度比 / 有效点差 bps。

    ## ⚠️ 2026-10 实测：盘口**触价档**会被单笔可撤挂单支配（但极端失衡本身可能为真）

    连续三次抓 BTC-USDT-SWAP Top20 盘口（间隔 2s），拿到的买一是
    **574 → 3.44 → 89.6 张**（同一价位、numOrders=1），而买 2~5 档始终
    不足 5 张 —— 触价档在几秒内跳动两个数量级，OBI 也随之从 +14% 翻到 −94%。

    同一次采样里卖侧却**逐档都厚**（卖一 897 张 n=57、其余多档 75~226 张），
    全簿合计 买 17.7 张 vs 卖 1786 张 ⇒ **−95%~−98% 的极端 OBI 是真实状态**，
    不能一律当噪音丢掉。所以这里的处理是"分开看"，而不是"把极端值砍掉"：

    1. `obi_pct`（原始 Top20）与 `depth_ratio_20` 照给（诊断/展示用）；
    2. **`obi_robust_pct`**：只累计 `numOrders >= min_multi_order_levels` 的档位
       —— 单笔挂单是可秒撤的报价，不计入"真实厚度"，用来抵消**触价档**
       被单笔挂单支配带来的抖动；
    3. `depth_reliable`：两侧各有 ≥3 个多笔档才为 True。为 False（例如全簿
       只有单笔挂单、或盘口没取回）时，下游（打分/信号）**必须把 OBI 当缺失**，
       不许当 0 或中性用。

    故本函数改为**双口径**并显式标注可信度：

    1. `obi_pct`（原始 Top20）与 `depth_ratio_20` 仍然给（诊断/展示用）；
    2. **`obi_robust_pct`**：只统计 `numOrders >= min_multi_order_levels` 的档位
       —— OKX 每档都返回 `numOrders`，单笔挂单（numOrders=1）是可秒撤的报价，
       不计入"真实厚度"；
    3. `depth_reliable`：稳健口径**两侧各有 ≥3 个多笔档**才为 True。
       为 False 时下游（打分/信号）**必须把 OBI 当作缺失**，不许当 0 或中性用。
    """
    # ★ 缺失 ⇒ `None`（提示词渲染 `--`）：1.0 会被读成"买卖深度均衡"、
    #   0.0 会被读成"零失衡"，两者都是**结论**而非缺失。
    out: Dict[str, Any] = {
        "bid_ask_depth_ratio": None, "depth_ratio_20": None, "obi_pct": None,
        "obi_robust_pct": None, "depth_reliable": False,
        "depth_note": "盘口未取回", "spread_bps": None,
        "depth_bias": "INSUFFICIENT_DATA",
    }
    if not isinstance(depth, dict):
        return out
    bids = [b for b in (depth.get("bids") or []) if isinstance(b, (list, tuple)) and len(b) >= 2]
    asks = [a for a in (depth.get("asks") or []) if isinstance(a, (list, tuple)) and len(a) >= 2]
    if not bids or not asks:
        out["depth_note"] = "盘口单侧为空"
        return out

    def _sz(rows: Sequence[Sequence[Any]], n: int) -> float:
        return sum(_sf(r[1]) for r in rows[:n])

    def _robust(rows: Sequence[Sequence[Any]]) -> Tuple[float, int]:
        """只累计**多笔档**（`numOrders >= min_multi_order_levels`）的张数与档数。"""
        total, levels = 0.0, 0
        for r in rows[:top_n]:
            n_orders = int(_sf(r[3])) if len(r) > 3 else 0
            if n_orders >= min_multi_order_levels:
                total += _sf(r[1])
                levels += 1
        return total, levels

    bid5, ask5 = _sz(bids, 5), _sz(asks, 5)
    bid20, ask20 = _sz(bids, top_n), _sz(asks, top_n)

    out["bid_ask_depth_ratio"] = round(bid5 / ask5, 4) if ask5 > 0 else None
    out["depth_ratio_20"] = round(bid20 / ask20, 4) if ask20 > 0 else None
    denom = bid20 + ask20
    if denom > 0:
        obi = (bid20 - ask20) / denom * 100.0
        out["obi_pct"] = round(obi, 2)
        # 有可算的 OBI ⇒ 才允许下"均衡"这个结论（缺失时保持 INSUFFICIENT_DATA）
        out["depth_bias"] = "NEUTRAL"
        if obi >= OBI_STRONG_BID_PCT:
            out["depth_bias"] = "STRONG_BID"
        elif obi <= OBI_STRONG_ASK_PCT:
            out["depth_bias"] = "STRONG_ASK"

    rb, rb_levels = _robust(bids)
    ra, ra_levels = _robust(asks)
    if rb + ra > 0:
        out["obi_robust_pct"] = round((rb - ra) / (rb + ra) * 100.0, 2)
    if rb_levels >= 3 and ra_levels >= 3 and rb > 0 and ra > 0:
        out["depth_reliable"] = True
        out["depth_note"] = ""
    else:
        out["depth_note"] = (
            f"盘口厚度由单笔可撤挂单支配（多笔档 买{rb_levels}/卖{ra_levels} < 3）"
            "⇒ OBI 不可作为方向证据")

    best_bid = _sf(bids[0][0])
    best_ask = _sf(asks[0][0])
    px = _sf(price) or ((best_bid + best_ask) / 2.0)
    if best_bid > 0 and best_ask > 0 and px > 0:
        out["spread_bps"] = round((best_ask - best_bid) / px * 10000.0, 4)
    return out


# ---------------------------------------------------------------------------
# T1.5 · 期权微观结构（纯计算，仅 BTC/ETH 有链）
# ---------------------------------------------------------------------------

def compute_options_factors(opt_rows: Optional[Sequence[Dict[str, Any]]],
                            forward_px: float,
                            official_put_call_ratio: Any = None,
                            oi_rows: Optional[Sequence[Dict[str, Any]]] = None
                            ) -> Dict[str, Any]:
    """ATM IV / 25d Risk Reversal 偏度 / Put-Call OI 比 / Max Pain（自算）。

    数据缺失（山寨币无期权链）⇒ `available=False` + 明确 reason，
    **绝不填 0 冒充"波动率为零"**。

    `official_put_call_ratio` 来自 OKX `option/open-interest-volume-ratio`
    （官方口径的 Call/Put OI 比）；缺失时回落为 `--`，不由本地瞎凑。
    """
    out = {
        "available": False, "reason": "无期权链数据（仅 BTC/ETH 具备完备期权市场）",
        "atm_iv_pct": _NA, "risk_reversal_25d_pct": _NA, "put_call_oi_ratio": _NA,
        "max_pain_price": _NA, "expiry": _NA,
    }
    rows = [r for r in (opt_rows or []) if isinstance(r, dict)]
    if official_put_call_ratio is not None:
        out["put_call_oi_ratio"] = round(_sf(official_put_call_ratio), 4)
    if not rows:
        return out

    fwd = _sf(forward_px) or _sf(rows[0].get("fwdPx"))
    if fwd <= 0:
        return out

    def _iv(row: Dict[str, Any]) -> float:
        for key in ("markVol", "bidVol", "askVol"):
            v = _sf(row.get(key))
            if v > 0:
                return v * 100.0
        return 0.0

    # 取最近到期的一档（按 instId 里的到期日分组，选最近的一组）
    def _expiry_of(row: Dict[str, Any]) -> str:
        parts = str(row.get("instId", "")).split("-")
        return parts[2] if len(parts) > 2 else ""

    expiries = sorted({_expiry_of(r) for r in rows if _expiry_of(r)})
    if not expiries:
        return out
    expiry = expiries[0]
    near = [r for r in rows if _expiry_of(r) == expiry]

    atm_iv = 0.0
    best_dist = None
    call_25 = put_25 = 0.0
    best_call_dist = best_put_dist = None
    for r in near:
        delta = abs(_sf(r.get("delta")))
        iv = _iv(r)
        if iv <= 0:
            continue
        d = abs(delta - 0.5)
        if best_dist is None or d < best_dist:
            best_dist, atm_iv = d, iv
        is_call = str(r.get("instId", "")).endswith("-C")
        d25 = abs(delta - 0.25)
        if is_call and (best_call_dist is None or d25 < best_call_dist):
            best_call_dist, call_25 = d25, iv
        elif (not is_call) and (best_put_dist is None or d25 < best_put_dist):
            best_put_dist, put_25 = d25, iv

    put_oi = 0.0
    call_oi = 0.0
    out.update({
        "available": atm_iv > 0,
        "reason": "" if atm_iv > 0 else "期权链返回但缺少有效隐含波动率",
        "expiry": expiry,
        "atm_iv_pct": round(atm_iv, 4) if atm_iv > 0 else _NA,
        "risk_reversal_25d_pct": round(call_25 - put_25, 4)
        if (call_25 > 0 and put_25 > 0) else _NA,
    })
    # Max Pain：2026-10 起**自算**（官方 strike 端点参数口径未公开，但
    # `/public/open-interest?instType=OPTION` 给每档 OI，实测 1838 行）。
    out.update(compute_max_pain(oi_rows, forward_px=forward_px))
    return out


def compute_max_pain(oi_rows: Optional[Sequence[Dict[str, Any]]],
                     *, forward_px: float = 0.0,
                     min_oi_share: float = 0.20) -> Dict[str, Any]:
    """从**每档期权的持仓量**自算 Max Pain（最大痛点）。

    ## 为什么自己算（2026-10 解决"Max Pain 拿不到"的限制）

    官方 `rubik/stat/option/open-interest-volume-strike` 报
    `Parameter expTime error`（参数口径未公开），而
    `GET /api/v5/public/open-interest?instType=OPTION&instFamily=BTC-USD`
    **直接给每张合约的 `oi`**（实测 1838 行）—— 数据其实一直在，只是要自己聚合。

    ## 定义（交易所通行的"最大痛点"）

    对每个候选行权价 `K`，计算**所有到期时为实值的期权总赔付**：

        payout(K) = Σ_{call 行权价<K} (K - strike)·oi_call
                  + Σ_{put  行权价>K} (strike - K)·oi_put

    `argmin payout(K)` 即 Max Pain —— 该价位下买方总盈利最小（卖方最舒服），
    常被视为到期前的"价格磁吸位"。

    ## 口径选择

    - 只在**单一到期日**上计算（Max Pain 是到期日概念，跨到期混算是错的）；
    - 默认取"**持仓量最大的到期日**"，但若最近的到期日持仓已达该值的
      `min_oi_share`（默认 20%），则优先用最近到期 —— 实盘最近到期的磁吸效应
      更强，且 OI 太小的远端到期算出来没有意义；
    - 数据缺失 ⇒ 返回 `max_pain_price = "--"` 并给出原因，**绝不用 0 冒充**。
    """
    out: Dict[str, Any] = {"max_pain_price": _NA, "max_pain_expiry": _NA,
                           "max_pain_total_oi": None, "max_pain_reason": "期权持仓量未取回"}
    rows = [r for r in (oi_rows or []) if isinstance(r, dict) and r.get("instId")]
    if not rows:
        return out

    # instId 形如 BTC-USD-260915-71000-C → 到期 260915、行权价 71000、C/P
    by_exp: Dict[str, Dict[float, Dict[str, float]]] = {}
    for r in rows:
        parts = str(r.get("instId", "")).split("-")
        if len(parts) < 5:
            continue
        exp, strike_s, cp = parts[2], parts[3], parts[4].upper()
        try:
            strike = float(strike_s)
        except (TypeError, ValueError):
            continue
        oi = _sf(r.get("oi"))
        if oi <= 0:
            continue
        slot = by_exp.setdefault(exp, {})
        side = "call" if cp.startswith("C") else "put"
        slot.setdefault(strike, {"call": 0.0, "put": 0.0})[side] += oi
    if not by_exp:
        out["max_pain_reason"] = "期权链上的持仓量全为 0"
        return out

    totals = {exp: sum(v["call"] + v["put"] for v in strikes.values())
              for exp, strikes in by_exp.items()}
    max_exp = max(totals, key=lambda e: totals[e])
    nearest = min(by_exp)
    exp = nearest if totals[nearest] >= totals[max_exp] * min_oi_share else max_exp
    strikes_map = by_exp[exp]
    levels = sorted(strikes_map)

    def _payout(k: float) -> float:
        total = 0.0
        for strike in levels:
            oi = strikes_map[strike]
            if strike < k:
                total += (k - strike) * oi["call"]
            elif strike > k:
                total += (strike - k) * oi["put"]
        return total

    payouts = {k: _payout(k) for k in levels}
    best = min(payouts, key=lambda k: (payouts[k], abs(k - _sf(forward_px))))
    out.update({
        "max_pain_price": best,
        "max_pain_expiry": exp,
        "max_pain_total_oi": round(totals[exp], 2),
        "max_pain_reason": "",
    })
    return out


def summarize_liquidation_clusters(details: Optional[Sequence[Dict[str, Any]]],
                                   ct_val: float, price: float,
                                   *, top_n: int = 3) -> Dict[str, Any]:
    """把**真实强平成交**按价位分桶 ⇒ 自建"强平价位堆积图"（替代第三方清算热力图）。

    ## 为什么能替代

    第三方清算热力图卖的是"各价位堆积的杠杆仓位"。OKX 公开的
    `public/liquidation-orders` 给的是**已经发生的强平成交明细**（`bkPx` 强平价 +
    `sz` 张数 + `posSide`）—— 实测一次 limit=100 覆盖约 **416 分钟（≈7 小时）**。
    把它按价位分桶，得到的就是一份**真实发生过**的清算堆积图（而不是模型估算）。

    诚实边界：窗口只有最近 100 笔（实测量级 7 小时），**不是 24 小时**，
    故输出里带 `liquidation_window_min` 让调用方知道它代表多长时间，
    绝不把它说成"24h 热力图"。
    """
    out: Dict[str, Any] = {"liquidation_clusters": [], "liquidation_window_min": None,
                          "liquidation_cluster_top": _NA}
    rows = [d for d in (details or []) if isinstance(d, dict)]
    if not rows:
        return out
    cv = _sf(ct_val, 1.0) or 1.0
    px = _sf(price)
    band = max(px * 0.001, 1e-9) if px > 0 else 0.0   # 0.1% 价格带宽；无价时退化为精确价位
    buckets: Dict[Tuple[float, str], Dict[str, float]] = {}
    times: List[float] = []
    for d in rows:
        try:
            bk = float(d.get("bkPx") or 0.0)
            sz = float(d.get("sz") or 0.0)
        except (TypeError, ValueError):
            continue
        if bk <= 0 or sz <= 0:
            continue
        side = str(d.get("posSide") or "").lower()
        key_px = round(bk / band) * band if band > 0 else bk
        slot = buckets.setdefault((key_px, side), {"usd": 0.0, "count": 0.0,
                                                   "sz": 0.0, "px_sz": 0.0})
        slot["usd"] += sz * cv * bk
        slot["count"] += 1
        # 报告口径用**量加权平均强平价**（比"带宽整数倍"可读得多：
        # 后者会出现 82999.0 这种明显人造的价位）
        slot["sz"] += sz
        slot["px_sz"] += sz * bk
        try:
            times.append(float(d.get("time") or d.get("ts") or 0.0))
        except (TypeError, ValueError):
            pass
    if not buckets:
        return out
    ordered = sorted(buckets.items(), key=lambda kv: -kv[1]["usd"])[:top_n]
    clusters = []
    for k, v in ordered:
        avg_px = (v["px_sz"] / v["sz"]) if v["sz"] > 0 else k[0]
        clusters.append({
            "price": round(avg_px, 2),
            "side": k[1],
            "usd": round(v["usd"], 2),
            "count": int(v["count"]),
            "distance_pct": round((avg_px - px) / px * 100.0, 3) if px > 0 else None,
        })
    out["liquidation_clusters"] = clusters
    if times:
        span_ms = max(times) - min(times)
        out["liquidation_window_min"] = round(span_ms / 60000.0, 1)
    top = clusters[0]
    out["liquidation_cluster_top"] = (
        f"{top['price']}（{'多头' if top['side'] == 'long' else '空头'}强平 "
        f"{top['usd'] / 10000.0:.1f}万 U，距现价 {top['distance_pct']:+.2f}%）"
        if top.get("distance_pct") is not None else str(top["price"]))
    return out


# ---------------------------------------------------------------------------
# 取数层（带 TTL 缓存与显式降级）
# ---------------------------------------------------------------------------

def fetch_derivatives_snapshot(ccy: str, inst_id: str, ul_y: str, *,
                               timeout: float = 4.0) -> Dict[str, Any]:
    """T0 衍生品取数：费率、OI 总量与官方 1H OI 序列、散户/精英多空比、清算脉冲。

    每一项失败都只把对应键留 `None`（调用方据此保持占位符），不影响其他项。
    """
    snap: Dict[str, Any] = {
        "funding_rate_pct": None, "next_funding_rate_pct": None,
        "oi_usd": None, "oi_series_usd": None, "long_short_ratio": None,
        "elite_account_ratio": None, "elite_position_ratio": None,
        "liquidation_details": None,
    }
    base = str(ccy or "").upper().strip()
    if not base:
        return snap

    rows = _public_get("/api/v5/public/funding-rate", {"instId": inst_id}, timeout)
    if rows and isinstance(rows[0], dict):
        snap["funding_rate_pct"] = round(_sf(rows[0].get("fundingRate")) * 100, 4)
        nxt = _sf(rows[0].get("nextFundingRate"), default=-1.0)
        snap["next_funding_rate_pct"] = round(nxt * 100, 4) if nxt > -1.0 else None

    rows = _public_get("/api/v5/public/open-interest",
                       {"instType": "SWAP", "instId": inst_id}, timeout)
    if rows and isinstance(rows[0], dict):
        snap["oi_usd"] = _sf(rows[0].get("oiUsd"))

    # ΔOI：用官方 `open-interest-history` 的 oiUsd 列（索引 3），不是自己攒快照
    rows = _public_get("/api/v5/rubik/stat/contracts/open-interest-history",
                       {"instId": inst_id, "period": "1H"}, timeout)
    if rows:
        snap["oi_series_usd"] = [_sf(r[3]) for r in rows[:6]
                                 if isinstance(r, (list, tuple)) and len(r) > 3]

    # 持筹类多空比是**慢变量**（5m 粒度、决策周期 15min），故各自带 300s TTL。
    # 这不只是省流量：Rubik 限频 5 次/2 秒，本引擎每标的要打 5 个 Rubik 接口，
    # 6 标的池一轮 30 次 —— 加 TTL 后降到 12 次/轮，节流等待从 ~13s 降到 ~5s，
    # 单轮 wall time 从 ~20s 回到 ~12s（实测 max 56s，逼近 60s 调度周期）。
    rows = _public_get("/api/v5/rubik/stat/contracts/long-short-account-ratio",
                       {"ccy": base, "period": "5m"}, timeout,
                       cache_key=f"lsratio:{base}", ttl=300.0)
    if rows and isinstance(rows[0], (list, tuple)) and len(rows[0]) > 1:
        snap["long_short_ratio"] = _sf(rows[0][1])

    # 精英账户多空比 / 精英持仓多空头寸比（OKX 官方 top-trader 两个端点）
    rows = _public_get(
        "/api/v5/rubik/stat/contracts/long-short-account-ratio-contract-top-trader",
        {"instId": inst_id, "period": "5m"}, timeout,
        cache_key=f"elite-acct:{inst_id}", ttl=300.0)
    if rows and isinstance(rows[0], (list, tuple)) and len(rows[0]) > 1:
        snap["elite_account_ratio"] = _sf(rows[0][1])

    rows = _public_get(
        "/api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader",
        {"instId": inst_id, "period": "5m"}, timeout,
        cache_key=f"elite-pos:{inst_id}", ttl=300.0)
    if rows and isinstance(rows[0], (list, tuple)) and len(rows[0]) > 1:
        snap["elite_position_ratio"] = _sf(rows[0][1])

    rows = _public_get("/api/v5/public/liquidation-orders",
                       {"instType": "SWAP", "uly": ul_y, "state": "filled", "limit": 100},
                       timeout)
    if rows and isinstance(rows[0], dict):
        details = rows[0].get("details")
        if isinstance(details, list):
            snap["liquidation_details"] = details
    return snap


def fetch_taker_volume(ccy: str, period: str, *, timeout: float = 4.0
                       ) -> Optional[List[Any]]:
    """T0.5 主动成交量序列（Rubik taker-volume，newest-first，TTL 30s）。

    ⚠️ 必须带 TTL：本函数每轮对**每个标的**都要 5m + 1H 两次外呼，
    6 标的池 = 每分钟 12 次；实测不加缓存会偶发 429 并把 CVD 静默打成 0。
    """
    base = str(ccy or "").upper().strip()
    if not base:
        return None
    cache_key = f"taker:{base}:{period}"
    cached = _cache_get(cache_key, 30.0)
    if cached is not None:
        return cached
    rows = _public_get("/api/v5/rubik/stat/taker-volume",
                       {"ccy": base, "instType": "CONTRACTS", "period": period}, timeout)
    if rows:
        _cache_put(cache_key, rows)
    return rows


def fetch_quarterly_basis_inputs(ccy: str, *, timeout: float = 4.0) -> Dict[str, Any]:
    """T2 季度基差输入：最近到期线性季度合约价 + 指数价 + 到期时间（TTL 1h）。"""
    base = str(ccy or "").upper().strip()
    if not base:
        return {}
    cache_key = f"basis:{base}"
    cached = _cache_get(cache_key, 3600.0)
    if cached is not None:
        return cached

    result: Dict[str, Any] = {}
    rows = _public_get("/api/v5/public/instruments",
                       {"instType": "FUTURES", "uly": f"{base}-USD"}, timeout)
    if rows:
        linear = [r for r in rows
                  if isinstance(r, dict) and str(r.get("ctType")) == "linear"
                  and str(r.get("settleCcy")) == "USD"]
        linear.sort(key=lambda r: _sf(r.get("expTime")))
        if linear:
            contract = linear[0]
            tick = _public_get("/api/v5/market/ticker",
                               {"instId": contract.get("instId")}, timeout)
            idx = _public_get("/api/v5/market/index-tickers",
                              {"instId": f"{base}-USD"}, timeout)
            if tick and isinstance(tick[0], dict) and idx and isinstance(idx[0], dict):
                result = {
                    "inst_id": contract.get("instId"),
                    "futures_px": _sf(tick[0].get("last")),
                    "index_px": _sf(idx[0].get("idxPx")),
                    "exp_time_ms": _sf(contract.get("expTime")),
                }
    _cache_put(cache_key, result)
    return result


def fetch_option_snapshot(inst_family: str, ccy: str = "", *,
                          timeout: float = 5.0) -> Dict[str, Any]:
    """T1.5 期权取数：期权链汇总（IV/Delta/fwdPx）+ 官方 Put/Call OI 比（TTL 300s）。"""
    family = str(inst_family or "").upper().strip()
    if not family:
        return {}
    cache_key = f"opt:{family}"
    cached = _cache_get(cache_key, 300.0)
    if cached is not None:
        return cached

    out: Dict[str, Any] = {}
    summary = _public_get("/api/v5/public/opt-summary", {"instFamily": family}, timeout)
    if summary:
        out["opt_summary"] = summary
        out["forward_px"] = _sf(summary[0].get("fwdPx")) if isinstance(summary[0], dict) else 0.0
    base = str(ccy or family.split("-")[0]).upper().strip()
    pcr = _public_get("/api/v5/rubik/stat/option/open-interest-volume-ratio",
                      {"ccy": base, "period": "8H"}, timeout)
    if pcr and isinstance(pcr[0], (list, tuple)) and len(pcr[0]) > 1:
        out["put_call_oi_ratio"] = _sf(pcr[0][1])
    # 每档期权的**持仓量**（自算 Max Pain 的原料）。非 Rubik 端点，无限频压力。
    oi_rows = _public_get("/api/v5/public/open-interest",
                          {"instType": "OPTION", "instFamily": family}, timeout)
    if oi_rows:
        out["opt_oi_rows"] = oi_rows
    _cache_put(cache_key, out)
    return out


def fetch_loan_rate_snapshot(*, timeout: float = 4.0) -> Dict[str, Any]:
    """T2 杠杆借贷利率（全局池级，TTL 30min）。"""
    cached = _cache_get("loan", 1800.0)
    if cached is not None:
        return cached
    out: Dict[str, Any] = {}
    rows = _public_get("/api/v5/public/interest-rate-loan-quota", None, timeout)
    if rows and isinstance(rows[0], dict):
        basic = rows[0].get("basic")
        if isinstance(basic, list):
            for row in basic:
                if isinstance(row, dict) and str(row.get("ccy")) in ("USDT", "USD"):
                    out["loan_rate_usdt"] = _sf(row.get("rate"))
                    break
    _cache_put("loan", out)
    return out


# ---------------------------------------------------------------------------
# 装配入口：把各梯队写进 factors 字典（门面逐段调用）
# ---------------------------------------------------------------------------

def apply_momentum_tier(factors: Dict[str, Any], *, closes_1h: Sequence[float],
                        closes_15m: Sequence[float], trend: str,
                        price: float = 0.0) -> None:
    """T4：MACD 与 RSI 因子写入 `trend_momentum`（含归一化 MACD 口径）。"""
    factors["trend_momentum"].update(compute_macd_factors(closes_1h, price))
    factors["trend_momentum"].update(compute_rsi_factors(closes_1h, closes_15m, trend))


def apply_volume_profile_tier(factors: Dict[str, Any], *,
                              raw_candles_15m: Sequence[Sequence[Any]],
                              price: float) -> None:
    """T3：24H VWAP 统计分布与 VPVR POC 写入 `volume_profile`。"""
    vp = compute_vwap_volume_profile(raw_candles_15m, price)
    factors["volume_profile"].update(vp)
    if _sf(vp.get("vwap_24h")) > 0:
        factors["trend_momentum"]["vwap_bias_pct"] = round(
            (price - vp["vwap_24h"]) / vp["vwap_24h"] * 100.0, 2)


def apply_orderflow_tier(factors: Dict[str, Any], *, taker_5m: Optional[List[Any]],
                         taker_1h: Optional[List[Any]],
                         closes_1h: Sequence[float]) -> None:
    """T0.5：CVD / Taker 比 / 量价背离写入 `volume_money_flow`。"""
    factors["volume_money_flow"].update(
        compute_cvd_factors(taker_5m, taker_1h, closes_1h))


def apply_microstructure_tier(factors: Dict[str, Any], *,
                              depth: Optional[Dict[str, Any]], price: float) -> None:
    """T1：OBI / 深度比 / 点差写入 `microstructure`。"""
    factors["microstructure"].update(compute_depth_factors(depth, price))


def apply_derivatives_tier(factors: Dict[str, Any], *, snapshot: Dict[str, Any],
                          ct_val: float, price_chg_1h_pct: float,
                          price: float = 0.0,
                          options_block: Optional[Dict[str, Any]] = None,
                          basis_block: Optional[Dict[str, Any]] = None,
                          loan_block: Optional[Dict[str, Any]] = None) -> None:
    """T0 / T1.5 / T2：衍生品、期权、期限结构写入 `smart_money_derivatives` 等。

    ★ 2026-10「不许假数据」：先把**本梯队会显示的键**全部预置为缺失，再由下面
    的守卫写真实值。原因：这些守卫是 `if fr is not None:` / `if oi_usd:` 形态，
    **取数失败时不写入** ⇒ `build_default_factors` 的默认值会留在原地
    （`funding_crowding="NEUTRAL"`、`oi_price_quadrant="NEUTRAL"`、
    `liquidation_*_usd=0.0`、`basis_annualized_pct=0.0`…），提示词于是显示
    "费率不拥挤 / 四象限中性 / 零清算"——三个**假结论**。
    """
    sm = factors["smart_money_derivatives"]
    for _k in ("funding_rate_pct", "next_funding_rate_pct", "oi_chg_1h_pct",
               "elite_account_ratio", "elite_position_ratio",
               "liquidation_long_usd", "liquidation_short_usd", "liquidation_net_usd",
               "basis_annualized_pct", "loan_rate_usdt"):
        sm[_k] = None
    # 字符串型字段沿用既有缺失标记 "--"（与类型一致，消费端不会拿到意外的 None 形态）
    sm["oi_usd"] = "--"
    sm["long_short_ratio"] = "--"
    for _k in ("funding_crowding", "oi_price_quadrant", "elite_divergence",
               "liquidation_bias"):
        sm[_k] = "INSUFFICIENT_DATA"

    fr = snapshot.get("funding_rate_pct")
    if fr is not None:
        sm["funding_rate_pct"] = fr
        sm["funding_crowding"] = classify_funding_crowding(fr)
    nfr = snapshot.get("next_funding_rate_pct")
    if nfr is not None:
        sm["next_funding_rate_pct"] = nfr

    oi_usd = snapshot.get("oi_usd")
    if oi_usd:
        sm["oi_usd"] = (f"{round(oi_usd / 1e8, 2)}亿 U" if oi_usd >= 1e8
                        else f"{round(oi_usd / 1e4, 1)}万 U")
    series = snapshot.get("oi_series_usd") or []
    oi_chg = 0.0
    if len(series) >= 2 and series[1] > 0:
        oi_chg = round((series[0] - series[1]) / series[1] * 100.0, 4)
        sm["oi_chg_1h_pct"] = oi_chg
        sm["oi_price_quadrant"] = classify_derivatives_quadrant(price_chg_1h_pct, oi_chg)

    lsr = snapshot.get("long_short_ratio")
    if lsr:
        sm["long_short_ratio"] = str(round(lsr, 4))
    elite_acct = snapshot.get("elite_account_ratio")
    elite_pos = snapshot.get("elite_position_ratio")
    if elite_acct:
        sm["elite_account_ratio"] = round(elite_acct, 4)
    if elite_pos:
        sm["elite_position_ratio"] = round(elite_pos, 4)
    sm["elite_divergence"] = classify_elite_divergence(lsr, elite_acct)

    long_liq, short_liq, bias = summarize_liquidations(
        snapshot.get("liquidation_details"), ct_val)
    if long_liq or short_liq:
        sm["liquidation_long_usd"] = long_liq
        sm["liquidation_short_usd"] = short_liq
        sm["liquidation_net_usd"] = round(short_liq - long_liq, 2)
        sm["liquidation_bias"] = bias
    # 自建"强平价位堆积图"（真实强平成交分桶；窗口实测量级 ~7h，输出里带分钟数）
    ref_px = _sf(price) or _sf(factors.get("microstructure", {}).get("bid_px"))
    sm.update(summarize_liquidation_clusters(
        snapshot.get("liquidation_details"), ct_val, ref_px))

    if basis_block:
        basis = annualized_basis_pct(basis_block.get("futures_px", 0.0),
                                     basis_block.get("index_px", 0.0),
                                     basis_block.get("exp_time_ms", 0),
                                     time.time() * 1000.0)
        if basis:
            sm["basis_annualized_pct"] = basis
    if loan_block and loan_block.get("loan_rate_usdt"):
        sm["loan_rate_usdt"] = round(_sf(loan_block["loan_rate_usdt"]) * 100, 4)

    if options_block is not None:
        factors["options_structure"].update(
            compute_options_factors(options_block.get("opt_summary"),
                                    options_block.get("forward_px", 0.0),
                                    options_block.get("put_call_oi_ratio"),
                                    options_block.get("opt_oi_rows")))
