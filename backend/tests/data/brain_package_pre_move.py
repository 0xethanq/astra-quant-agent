def fetch_single_instrument_package(item: Dict[str, Any]) -> Dict[str, Any]:
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
        "vol_ratio": 1.0,
        "obv_flow": "NEUTRAL",
        "adx_1h": 0.0,
        "smart_money": {
            "available": False,
            "reason": "OKX CLI 已移除，smartmoney 无公开 V5 等价接口（待接新数据源）",
            "weighted_long_pct": "--",
            "net_flow_usdt": "--",
            "avg_long_entry": "--",
            "avg_short_entry": "--",
            "top_win_rate": "--"
        },
        "recent_15m": [],
        "recent_1h": [],
        "recent_4h": [],
        "calculus": {"valid": False, "regime": "DATA_UNRELIABLE", "quality": 0.0},
        "data_quality": "invalid"
    }

    # 1. Ticker
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
    except Exception:
        pass

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

                # Volume Ratio (Last vs MA5)
                if len(vols) >= 6:
                    avg_v5 = sum(vols[-6:-1]) / 5
                    if avg_v5 > 0:
                        pkg["vol_ratio"] = round(vols[-1] / avg_v5, 2)

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
        except Exception:
            pass

        try:
            req = urllib.request.Request(f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst_id}", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if d.get("code") == "0" and d.get("data"):
                    usd = float(d["data"][0].get("oiUsd", 0) or 0)
                    pkg["oiUsd"] = f"{round(usd / 1e8, 2)}亿 U" if usd > 1e8 else f"{round(usd / 1e4, 1)}万 U"
        except Exception:
            pass

        if ccy:
            try:
                req = urllib.request.Request(f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=5m", headers=headers)
                with urllib.request.urlopen(req, timeout=3) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    if d.get("code") == "0" and d.get("data") and len(d["data"]) > 0:
                        pkg["lsRatio"] = float(d["data"][0][1])
            except Exception:
                pass

            try:
                req = urllib.request.Request(f"https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy={ccy}&instType=CONTRACTS&period=5m", headers=headers)
                with urllib.request.urlopen(req, timeout=3) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    if d.get("code") == "0" and d.get("data") and len(d["data"]) > 0:
                        b_vol = float(d["data"][0][1])
                        s_vol = float(d["data"][0][2])
                        net_diff = b_vol - s_vol
                        pkg["takerNetUsd"] = f"{round(net_diff / 1e4, 1)}万 U"
            except Exception:
                pass

        # 6. OKX ADX Trend Strength Indicator (1H) via direct REST (zero Node CLI fork)
        try:
            adx_data = fetch_single_indicator(inst_id, "ADX", bar="1H")
            if adx_data and "adx" in adx_data:
                pkg["adx_1h"] = float(adx_data.get("adx", 0.0) or 0.0)
        except Exception:
            pass

    required_market_data = (
        pkg["price"] > 0
        and pkg["bidPx"] > 0
        and pkg["askPx"] >= pkg["bidPx"]
        and len(pkg["recent_15m"]) >= 12
        and len(pkg["recent_1h"]) >= 8
        and len(pkg["recent_4h"]) >= 6
    )
    try:
        from calculus_engine import calculate_multi_timeframe
        pkg["calculus"] = calculate_multi_timeframe({
            "15M": pkg["recent_15m"],
            "1H": pkg["recent_1h"],
            "4H": pkg["recent_4h"],
        })
    except Exception as exc:
        pkg["calculus"] = {"valid": False, "regime": "DATA_UNRELIABLE", "quality": 0.0, "error": str(exc)}
    pkg["data_quality"] = "valid" if required_market_data else "invalid"
    return pkg
