"""单标的数据包装配（B3 抽取，`ai_brain_trader.py` 的第一块）。

从 `scripts/ai_brain_trader.py` 搬出的 `fetch_single_instrument_package`（254 行）——
主脑每 15 分钟对每个标的跑一次的行情/指标装配。搬走前门面 1839 行。

## 为什么是这块

- **全仓零测试覆盖、零源码锚点**：`grep -rn fetch_single_instrument_package tests/`
  与 `grep -rn 'split("def ' tests/` 双向实测，均无引用；
- **依赖面极窄**：整段只读 `json` / `urllib` 两个标准库模块、
  `Dict` / `Any` 两个 typing 名，外加 `fetch_candles` / `fetch_single_indicator`
  两个**注入**进来的函数（见下）；
- 因此是「整段搬走」而非「消除抄写」，收益是行数，不需要逐值对拍 —— 但仍做了
  两条路径的差分（见 `tests/extraction/test_brain_package_extraction.py`）。

## 2026-10 变更：数理引擎退场，改挂 **7 梯队量化因子**

原实现在函数尾部调用 `calculus_engine.calculate_multi_timeframe` 把
15M/1H/4H 的 K 线塞进微积分引擎，产出 `pkg["calculus"]`（v/a/j/I/E/A/概率）。
该链路已整体退场；`pkg["calculus"]` 只保留**默认的显式不可用占位**
（键位不动，供 `calculus_snapshot.json` 与台账兜底读取链使用）。

取而代之：本模块新增 `pkg["quant_factors"]` —— **直接读因子引擎的产物**
`data/factor_library_snapshot.json`（`scripts/factor_library.py` 每分钟刷新一次），
按 `instId` 取出 T0/T0.5/T1/T1.5/T2/T3/T4 各梯队。

> ⚠️ 为什么**不**在这里重算一遍：`factor_library.py` 已经为每个标的打过
> 那一整轮公开接口（费率/OI 历史/精英多空比/清算/期权/基差…）。
> 在这里重算会把外呼**翻倍**（OKX 公共行情按 IP 限频 40req/2s），
> 而且两条路径会出现两份可能漂移的因子。**单一事实源 = 那一份快照。**

## 为什么两个行情函数是注入而不是 import

与 `scripts/trader/factors.py` 同一理由：`tests/risk_test_env.py::pin_baseline_risk_env()`
的**原地 reload 名单只有** `risk_constants` / `ai_factor_trader` / `ai_brain_trader`，
**不含任何子模块**。若本模块在 import 期把 `fetch_candles` 绑死，
门面重载后指向的就不再是同一个对象；更实际的是**测试若对门面做
`patch.object(abt, "fetch_candles")` 就会失效**。注入从结构上消除这两种陷阱。

正因如此，本模块**不 import 门面的任何东西**，只在调用期接收依赖。
"""
import json
import os
import time
import urllib.request
from pathlib import Path

from typing import Any, Dict

# 行情取数失败的可观测性（第 137 刀）：只计数 + 每类一次性告警，绝不改变取值行为。
try:                      # 以脚本方式运行（SCRIPTS_DIR 在 sys.path 上）
    from market_data_health import note_failure
except ImportError:       # 以 scripts.brain.* 包被导入（PROJECT_ROOT 在 sys.path 上）
    from scripts.market_data_health import note_failure

#: 因子引擎快照（由 `scripts/factor_library.py` 每分钟原子替换）。
#: ⚠️ `ASTRA_DATA_DIR` 是测试沙箱变量（见 factor_library.py 的同名注释）：
#: 生产不设置它，故取值与"仓库根 data/"逐位相同。
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: 透传进 `pkg["quant_factors"]` 的梯队键（顺序即提示词里的展示顺序）
QUANT_FACTOR_TIERS = (
    "trend_momentum", "volatility_channel", "volume_money_flow",
    "microstructure", "smart_money_derivatives", "volume_profile",
    "options_structure",
)


def _factor_snapshot_path() -> str:
    data_dir = os.environ.get("ASTRA_DATA_DIR") or str(_PROJECT_ROOT / "data")
    return os.path.join(data_dir, "factor_library_snapshot.json")


def load_quant_factor_tiers(inst_id: str, *, path: str = None) -> Dict[str, Any]:
    """按 `instId` 从因子引擎快照里取出各梯队因子块。

    **失败语义**：文件缺失/损坏/该标的缺席 ⇒ 返回空 dict（提示词侧据此
    显示"因子快照缺失"，**绝不编造中性因子**）。本函数**永不抛异常** ——
    它在每分钟一轮的主脑循环里，抛一次就毁掉整轮决策。
    """
    target = path or _factor_snapshot_path()
    try:
        with open(target, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except Exception:
        return {}
    instruments = snap.get("instruments") if isinstance(snap, dict) else None
    if not isinstance(instruments, list):
        return {}
    for item in instruments:
        if not isinstance(item, dict):
            continue
        if str(item.get("instId")) != str(inst_id):
            continue
        return {tier: item[tier] for tier in QUANT_FACTOR_TIERS
                if isinstance(item.get(tier), dict)}
    return {}


def fetch_single_instrument_package(item: Dict[str, Any], *,
                                   fetch_candles,
                                   fetch_single_indicator) -> Dict[str, Any]:
    """装配单标的数据包；两个行情函数由门面在**调用时**注入（理由见模块 docstring）。"""
    inst_id = item["instId"]
    name = item["name"]
    ccy = item.get("ccy", "")
    headers = {"User-Agent": "Mozilla/5.0"}

    pkg = {
        "instId": inst_id,
        "name": name,
        "type": item["type"],
        "precision": item["precision"],
        "price": 0.0,
        "chg24h": 0.0,
        "bidPx": 0.0,
        "askPx": 0.0,
        "fundingRate": 0.0,
        "oiUsd": "N/A",
        "vol24h": 0.0,
        "lsRatio": "N/A",
        "takerNetUsd": "N/A",
        "atr": 0.0,
        "rsi": 50.0,
        "vwap_bias": 0.0,
        "macd_hist": 0.0,
        "macd_accel": 0.0,
        # ★「不许假数据」：1.0 会被读成"量能正常"这个**结论**；不写就是缺失
        "vol_ratio": None,
        "obv_flow": "NEUTRAL",
        "adx_1h": 0.0,
        "smart_money": {
            "available": False,
            "reason": "Top100 加权多空比/净流无公开 V5 等价接口；持仓方向证据改用 OKX 官方 top-trader 的精英账户比/精英持仓比（见 T0 衍生品梯队）",
            "weighted_long_pct": "--",
            "net_flow_usdt": "--",
            "avg_long_entry": "--",
            "avg_short_entry": "--",
            "top_win_rate": "--"
        },
        "recent_15m": [],
        "recent_1h": [],
        "recent_4h": [],
        "data_quality": "invalid"
    }

    # 1. Ticker
    t_okx0 = time.time()
    try:
        req = urllib.request.Request(f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}", headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            if d.get("code") == "0" and d.get("data"):
                t = d["data"][0]
                pkg["price"] = float(t.get("last", 0))
                pkg["bidPx"] = float(t.get("bidPx", pkg["price"]) or pkg["price"])
                pkg["askPx"] = float(t.get("askPx", pkg["price"]) or pkg["price"])
                op = float(t.get("open24h", 0) or 0)
                pkg["chg24h"] = round(((pkg["price"] - op) / op * 100) if op > 0 else 0, 2)
                pkg["vol24h"] = round(float(t.get("vol24h", 0) or 0), 2)
                pkg["okx_latency_ms"] = max(1, int(round((time.time() - t_okx0) * 1000)))
    except Exception as exc:
        note_failure("okx_ticker", exc)

    # 2. 15M Candles (recent 24, about 6 hours) & Technical Indicators Calculation
    try:
        d = {"data": fetch_candles(inst_id, bar="15m", limit=24)}
        if d["data"]:
            raw_candles = d["data"]
            pkg["recent_15m"] = [[float(c[1]), float(c[2]), float(c[3]), float(c[4]), round(float(c[5]), 1)] for c in raw_candles[:12]]

            # Calculate 15M indicators
            if len(raw_candles) >= 15:
                closes = [float(c[4]) for c in reversed(raw_candles)]
                highs = [float(c[2]) for c in reversed(raw_candles)]
                lows = [float(c[3]) for c in reversed(raw_candles)]
                vols = [float(c[5]) for c in reversed(raw_candles)]

                # ATR 15M
                tr_list = []
                for i in range(1, len(closes)):
                    tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                    tr_list.append(tr)
                if len(tr_list) >= 14:
                    pkg["atr_15m"] = round(sum(tr_list[-14:]) / 14, 4)
                    pkg["atr"] = pkg["atr_15m"]

                # RSI 15M
                diffs = [closes[i] - closes[i-1] for i in range(1, len(closes))]
                gains = [d if d > 0 else 0 for d in diffs]
                losses = [-d if d < 0 else 0 for d in diffs]
                if len(gains) >= 14:
                    avg_g = sum(gains[-14:]) / 14
                    avg_l = sum(losses[-14:]) / 14
                    rs = (avg_g / avg_l) if avg_l > 0 else 100.0
                    pkg["rsi"] = round(100.0 - (100.0 / (1.0 + rs)), 1)
                    pkg["rsi_15m"] = pkg["rsi"]

                # VWAP Bias
                pv_sum = sum(closes[i] * vols[i] for i in range(len(closes)))
                v_sum = sum(vols)
                if v_sum > 0:
                    vwap = pv_sum / v_sum
                    pkg["vwap_bias"] = round((pkg["price"] - vwap) / vwap * 100, 2)

                # Volume Ratio（**最后一根已收盘**的量 vs 它前面 5 根均量）
                #
                # ⚠️ 2026-10 实盘发现：原实现用 `vols[-1]` —— 那是 OKX 返回的
                # **正在跳动的未收盘 15M K 线**，刚开盘时成交量接近 0，
                # 于是提示词里长期出现 `15M量比=0.01x / 0.02x`，模型会读成
                # "成交量枯竭"。改用 `vols[-2]`（最近一根**已收盘**）与
                # `vols[-7:-2]` 对齐比较，比值才可解释。
                if len(vols) >= 7:
                    avg_v5 = sum(vols[-7:-2]) / 5
                    if avg_v5 > 0:
                        pkg["vol_ratio"] = round(vols[-2] / avg_v5, 2)

                # OBV Flow
                obv = 0
                for i in range(1, len(closes)):
                    if closes[i] > closes[i-1]:
                        obv += vols[i]
                    elif closes[i] < closes[i-1]:
                        obv -= vols[i]
                pkg["obv_flow"] = "BULL_FLOW" if obv > 0 else ("BEAR_FLOW" if obv < 0 else "NEUTRAL")
        else:
            print(f"[AI Brain] ⚠️ {inst_id} 15m K线获取失败（www/aws/CLI 三级容灾均未取回），本包 15M 微观指标降级缺省")
    except Exception as exc:
        print(f"[AI Brain] ⚠️ {inst_id} 15m K线处理异常: {exc}")

    # 3. 1H Candles (recent 24, about 24 hours) & 1H ATR / 1H RSI
    try:
        d = {"data": fetch_candles(inst_id, bar="1H", limit=24)}
        if d["data"]:
            raw_1h = d["data"]
            pkg["recent_1h"] = [[float(c[1]), float(c[2]), float(c[3]), float(c[4]), round(float(c[5]), 1)] for c in raw_1h[:12]]
            if len(raw_1h) >= 15:
                closes_1h = [float(c[4]) for c in reversed(raw_1h)]
                highs_1h = [float(c[2]) for c in reversed(raw_1h)]
                lows_1h = [float(c[3]) for c in reversed(raw_1h)]

                tr_list_1h = []
                for i in range(1, len(closes_1h)):
                    tr = max(highs_1h[i] - lows_1h[i], abs(highs_1h[i] - closes_1h[i-1]), abs(lows_1h[i] - closes_1h[i-1]))
                    tr_list_1h.append(tr)
                if len(tr_list_1h) >= 14:
                    pkg["atr_1h"] = round(sum(tr_list_1h[-14:]) / 14, 4)
                    pkg["atr"] = pkg["atr_1h"]  # Elevate primary ATR to 1H

                diffs_1h = [closes_1h[i] - closes_1h[i-1] for i in range(1, len(closes_1h))]
                gains_1h = [d if d > 0 else 0 for d in diffs_1h]
                losses_1h = [-d if d < 0 else 0 for d in diffs_1h]
                if len(gains_1h) >= 14:
                    avg_g_1h = sum(gains_1h[-14:]) / 14
                    avg_l_1h = sum(losses_1h[-14:]) / 14
                    rs_1h = (avg_g_1h / avg_l_1h) if avg_l_1h > 0 else 100.0
                    pkg["rsi_1h"] = round(100.0 - (100.0 / (1.0 + rs_1h)), 1)

                # 1H Swing Structure
                if len(closes_1h) >= 10:
                    ma7_1h = sum(closes_1h[-7:]) / 7
                    ma20_1h = sum(closes_1h[-20:]) / min(len(closes_1h), 20)
                    if closes_1h[-1] > ma7_1h > ma20_1h:
                        pkg["structure_1h"] = "1H_SWING_BULL"
                    elif closes_1h[-1] < ma7_1h < ma20_1h:
                        pkg["structure_1h"] = "1H_SWING_BEAR"
                    else:
                        pkg["structure_1h"] = "1H_SWING_CHOP"
        else:
            print(f"[AI Brain] ⚠️ {inst_id} 1H K线获取失败（www/aws/CLI 三级容灾均未取回），1H ATR/RSI/结构字段降级缺省")
    except Exception as exc:
        print(f"[AI Brain] ⚠️ {inst_id} 1H K线处理异常: {exc}")

    # 4. 4H Candles (recent 16, about 64 hours) & 4H Macro Structure
    try:
        d = {"data": fetch_candles(inst_id, bar="4H", limit=16)}
        if d["data"]:
            raw_4h = d["data"]
            pkg["recent_4h"] = [[float(c[1]), float(c[2]), float(c[3]), float(c[4]), round(float(c[5]), 1)] for c in raw_4h[:8]]
            if len(raw_4h) >= 8:
                closes_4h = [float(c[4]) for c in reversed(raw_4h)]
                ma5_4h = sum(closes_4h[-5:]) / 5
                ma12_4h = sum(closes_4h[-12:]) / min(len(closes_4h), 12)
                if closes_4h[-1] > ma5_4h > ma12_4h:
                    pkg["macro_4h"] = "4H_MACRO_BULL (大级别多头通道)"
                elif closes_4h[-1] < ma5_4h < ma12_4h:
                    pkg["macro_4h"] = "4H_MACRO_BEAR (大级别空头承压)"
                else:
                    pkg["macro_4h"] = "4H_MACRO_RANGE (大级别区间震荡)"
        else:
            print(f"[AI Brain] ⚠️ {inst_id} 4H K线获取失败（www/aws/CLI 三级容灾均未取回），4H 宏观结构字段降级缺省")
    except Exception as exc:
        print(f"[AI Brain] ⚠️ {inst_id} 4H K线处理异常: {exc}")

    # 5. Funding Rate & OI
    if item["type"] == "crypto":
        try:
            req = urllib.request.Request(f"https://www.okx.com/api/v5/public/funding-rate?instId={inst_id}", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if d.get("code") == "0" and d.get("data"):
                    pkg["fundingRate"] = round(float(d["data"][0].get("fundingRate", 0)) * 100, 4)
        except Exception as exc:
            note_failure("okx_funding_rate", exc)

        try:
            req = urllib.request.Request(f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst_id}", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if d.get("code") == "0" and d.get("data"):
                    usd = float(d["data"][0].get("oiUsd", 0) or 0)
                    pkg["oiUsd"] = f"{round(usd / 1e8, 2)}亿 U" if usd > 1e8 else f"{round(usd / 1e4, 1)}万 U"
        except Exception as exc:
            note_failure("okx_open_interest", exc)

        if ccy:
            try:
                req = urllib.request.Request(f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=5m", headers=headers)
                with urllib.request.urlopen(req, timeout=3) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    if d.get("code") == "0" and d.get("data") and len(d["data"]) > 0:
                        pkg["lsRatio"] = float(d["data"][0][1])
            except Exception as exc:
                note_failure("okx_ls_ratio", exc)

            try:
                req = urllib.request.Request(f"https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy={ccy}&instType=CONTRACTS&period=5m", headers=headers)
                with urllib.request.urlopen(req, timeout=3) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    if d.get("code") == "0" and d.get("data") and len(d["data"]) > 0:
                        b_vol = float(d["data"][0][1])
                        s_vol = float(d["data"][0][2])
                        net_diff = b_vol - s_vol
                        pkg["takerNetUsd"] = f"{round(net_diff / 1e4, 1)}万 U"
            except Exception as exc:
                note_failure("okx_taker_volume", exc)

        # 6. OKX ADX Trend Strength Indicator (1H) via direct REST (zero Node CLI fork)
        try:
            adx_data = fetch_single_indicator(inst_id, "ADX", bar="1H")
            if adx_data and "adx" in adx_data:
                pkg["adx_1h"] = float(adx_data.get("adx", 0.0) or 0.0)
        except Exception as exc:
            note_failure("okx_adx_1h", exc)

    required_market_data = (
        pkg["price"] > 0
        and pkg["bidPx"] > 0
        and pkg["askPx"] >= pkg["bidPx"]
        and len(pkg["recent_15m"]) >= 12
        and len(pkg["recent_1h"]) >= 8
        and len(pkg["recent_4h"]) >= 6
    )
    # 6. 已退役：微积分多周期引擎（2026-10 数理系统退场）。
    #    `pkg["calculus"]` 只保留**显式不可用**的默认占位 —— 键位不动，
    #    供 calculus_snapshot.json / 台账兜底读取链使用；**不再计算任何东西**。
    pkg["quant_factors"] = load_quant_factor_tiers(inst_id)
    pkg["data_quality"] = "valid" if required_market_data else "invalid"
    return pkg
