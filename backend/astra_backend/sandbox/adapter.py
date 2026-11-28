"""Sandbox Exchange Adapter: In-memory deterministic simulation matching BaseExchangeAdapter.

Enables zero-code switching between Live, Demo, and Backtesting/Sandbox environments
with zero look-ahead bias and realistic order execution models.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

from astra_backend.exchanges.base import (
    BaseExchangeAdapter,
    ExchangeCapabilities,
    InstrumentSpec,
    canonical_base,
)


class SandboxExchangeAdapter(BaseExchangeAdapter):
    """Deterministic in-memory exchange simulation adhering strictly to BaseExchangeAdapter."""

    capabilities = ExchangeCapabilities(
        venue="sandbox",
        display_name="ASTRA 离线高保真仿真沙箱",
        symbol_template="{base}-USDT-SWAP",
        quantity_unit="contracts",
        signed_size=False,
        supports_attached_tp_sl=True,
        trigger_price_default="last",
        max_candle_limit=1000,
        bar_case="lower",
        has_top_trader_ratio=True,
        has_taker_ratio=True,
        supports_account=True,
        supports_orders=True,
        mainland_ip_restricted=False,
        rate_limit_note="内存零延迟，无网络与限频瓶颈",
        order_id_type="string",
        native_amend=True,
        decimal_amount=True,
        position_modes=("net", "long_short"),
        conditional_family="attached",
        protection_semantics="沙箱内存原子挂单；按真实步进的高低价驱动 TP/SL 触发",
        adapter_execution_flag="ASTRA_SANDBOX_EXECUTION",
    )

    def __init__(
        self,
        initial_balance: float = 10000.0,
        maker_fee: float = 0.0002,
        taker_fee: float = 0.0005,
        slippage: float = 0.0002,
        environment: str = "sandbox",
        instrument_specs: Optional[Dict[str, Dict[str, Any]]] = None,
        maintenance_margin_rate: float = 0.005,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.environment = environment
        self.initial_balance = float(initial_balance)
        self.maker_fee = float(maker_fee)
        self.taker_fee = float(taker_fee)
        self.slippage = float(slippage)
        self.maintenance_margin_rate = max(0.001, float(maintenance_margin_rate))
        self._instrument_specs: Dict[str, Dict[str, Any]] = {}
        if isinstance(instrument_specs, dict):
            for k, v in instrument_specs.items():
                if isinstance(v, dict):
                    self._instrument_specs[canonical_base(k)] = dict(v)
        self.reset(self.initial_balance)

    def _ct_val_for(self, base: str) -> float:
        spec = self._instrument_specs.get(canonical_base(base))
        if spec:
            try:
                ct = float(spec.get("ctVal") or spec.get("ct_val") or 1.0)
                if ct > 0:
                    return ct
            except (TypeError, ValueError):
                pass
        return 1.0

    def reset(self, initial_balance: Optional[float] = None) -> None:
        """Reset simulation state to fresh initial conditions."""
        if initial_balance is not None:
            self.initial_balance = float(initial_balance)
        self.cash = self.initial_balance
        self.sim_time_ms: int = 0
        self._has_sim_ts: bool = False
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._open_orders: Dict[str, Dict[str, Any]] = {}
        self._algo_orders: Dict[str, Dict[str, Any]] = {}
        self._current_candles: Dict[str, Dict[str, Any]] = {}
        self._candle_history: Dict[str, List[List[Any]]] = {}
        self._funding_rates: Dict[str, float] = {}
        self._trades: List[Dict[str, Any]] = []
        self._order_counter: int = 1000
        self._algo_counter: int = 5000
        self._last_funding_slot: Optional[int] = None

    def set_funding_rate(self, symbol: str, rate: float) -> None:
        self._funding_rates[canonical_base(symbol)] = float(rate)

    # -------------------------------------------------------------------------
    # Simulation Feeding & Time Stepping
    # -------------------------------------------------------------------------
    def set_historical_candles(self, symbol: str, bar: str, candles: List[List[Any]]) -> None:
        """Pre-load historical candles for point-in-time querying [[ts, o, h, l, c, v], ...]."""
        base = canonical_base(symbol)
        key = f"{base}:{bar.lower()}"
        sorted_candles = sorted(candles, key=lambda x: int(x[0]))
        self._candle_history[key] = sorted_candles

    def step(self, candle_snapshot: Dict[str, Dict[str, Any]]) -> None:
        """Advance simulation clock by one bar across active instruments.

        保守撮合序（无未来函数）：
        1. 先刷新在途持仓：检查强平/止损/移动止损/分批止盈/时间止损；
        2. 8H 整点结算资金费率；
        3. 再撮合未成交限价挂单（新成交挂单绝不在同根 K 线共享保护单止盈触发）。
        """
        for sym_or_base, c in candle_snapshot.items():
            base = canonical_base(sym_or_base)
            self._current_candles[base] = c
            ts_val = c.get("ts_ms") if "ts_ms" in c else c.get("ts")
            if ts_val is not None:
                ts_i = int(ts_val)
                self.sim_time_ms = ts_i if not self._has_sim_ts else max(self.sim_time_ms, ts_i)
                self._has_sim_ts = True
            if "funding_rate" in c and c["funding_rate"] is not None:
                self._funding_rates[base] = float(c["funding_rate"])

        # 1. Check active positions FIRST (Liquidation & SL before BE & TP — zero same-bar lookahead)
        self._check_protective_triggers()
        # 2. Apply 8H funding settlements on surviving positions
        self._apply_funding_settlement()
        # 3. Check pending limit orders for fills
        self._match_open_orders()

    def _apply_funding_settlement(self) -> None:
        if self.sim_time_ms <= 0:
            return
        slot = int(self.sim_time_ms // (8 * 3600 * 1000))
        if self._last_funding_slot is None:
            self._last_funding_slot = slot
            return
        if slot <= self._last_funding_slot:
            return
        self._last_funding_slot = slot
        if not self._positions:
            return
        for pos in self._positions.values():
            base = pos["base"]
            rate = float(self._funding_rates.get(base, 0.0))
            if rate == 0.0:
                continue
            ct_val = float(pos.get("ct_val") or self._ct_val_for(base))
            mark = float(pos.get("mark_price") or pos.get("entry_price") or 0.0)
            notional = float(pos["amount"]) * ct_val * mark
            pos_side = str(pos.get("posSide") or "net").lower()
            # 正费率：多头付、空头收；负费率相反
            funding_pnl = (-notional * rate) if pos_side == "long" else (notional * rate)
            self.cash += funding_pnl
            pos["funding_paid_usd"] = float(pos.get("funding_paid_usd", 0.0)) + funding_pnl

    def _match_open_orders(self) -> None:
        to_remove = []
        for ord_id, o in list(self._open_orders.items()):
            base = o["base"]
            candle = self._current_candles.get(base)
            if not candle:
                continue

            low = float(candle.get("low") or candle.get("close", 0))
            high = float(candle.get("high") or candle.get("close", 0))
            limit_px = float(o["price"])
            side = o["side"].lower()

            fill = False
            fill_px = limit_px
            if side == "buy" and low <= limit_px:
                fill = True
                fill_px = min(limit_px, float(candle.get("open", limit_px)))
            elif side == "sell" and high >= limit_px:
                fill = True
                fill_px = max(limit_px, float(candle.get("open", limit_px)))

            if fill:
                self._execute_fill(o, fill_px, is_maker=True)
                to_remove.append(ord_id)

        for ord_id in to_remove:
            self._open_orders.pop(ord_id, None)

    def _execute_fill(self, order: Dict[str, Any], fill_px: float, is_maker: bool = True) -> None:
        base = order["base"]
        contracts = float(order["contracts"])
        side = order["side"].lower()
        pos_side = order.get("pos_side") or ("long" if side == "buy" else "short")
        ct_val = self._ct_val_for(base)
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        notional = contracts * ct_val * fill_px
        fee = notional * fee_rate
        lev = max(1.0, float(order.get("leverage", 3.0) or 3.0))
        margin_req = notional / lev

        self.cash -= fee
        pos_key = f"{base}:{pos_side}"
        curr_pos = self._positions.get(pos_key)

        if not curr_pos:
            self._positions[pos_key] = {
                "venue": "sandbox",
                "exchange": "sandbox",
                "symbol": f"{base}-USDT-SWAP",
                "instId": f"{base}-USDT-SWAP",
                "base": base,
                "side": pos_side,
                "posSide": pos_side,
                "amount": contracts,
                "ct_val": ct_val,
                "size_signed": contracts if pos_side == "long" else -contracts,
                "entry_price": fill_px,
                "mark_price": fill_px,
                "unrealized_pnl": 0.0,
                "upl": 0.0,
                "leverage": lev,
                "margin_locked": margin_req,
                "margin_mode": "cross",
                "opened_ts_ms": self.sim_time_ms,
                "entry_fee": fee,
                "funding_paid_usd": 0.0,
                "peak_favorable_px": fill_px,
                "scale_out_done": False,
                "atr_entry": float(order.get("atr") or 0.0),
                "initial_sl_px": float(order.get("initial_sl_px") or 0.0),
                "tp1_px": float(order.get("tp1_px") or 0.0),
                "scale_out_ratio": float(order.get("scale_out_ratio") or 0.35),
                "be_offset_pct": float(order.get("be_offset_pct") or 0.0030),
                "time_stop_hours": float(order.get("time_stop_hours") or 0.0),
            }
        else:
            old_amt = curr_pos["amount"]
            old_entry = curr_pos["entry_price"]
            new_amt = old_amt + contracts
            curr_pos["entry_price"] = ((old_amt * old_entry) + (contracts * fill_px)) / new_amt if new_amt > 0 else fill_px
            curr_pos["amount"] = new_amt
            curr_pos["size_signed"] = new_amt if pos_side == "long" else -new_amt
            curr_pos["margin_locked"] = float(curr_pos.get("margin_locked", 0.0)) + margin_req
            curr_pos["entry_fee"] = float(curr_pos.get("entry_fee", 0.0)) + fee

        self._trades.append({
            "order_id": order["order_id"],
            "base": base,
            "side": side,
            "pos_side": pos_side,
            "contracts": contracts,
            "price": fill_px,
            "fee": fee,
            "is_maker": is_maker,
            "ts_ms": self.sim_time_ms,
        })

    def _check_protective_triggers(self) -> None:
        to_close = []
        for pos_key, pos in list(self._positions.items()):
            base = pos["base"]
            candle = self._current_candles.get(base)
            if not candle:
                continue

            low = float(candle.get("low") or candle.get("close", 0))
            high = float(candle.get("high") or candle.get("close", 0))
            cur_px = float(candle.get("close", 0))
            pos_side = pos["posSide"].lower()
            entry_px = float(pos["entry_price"])
            amt = float(pos["amount"])
            ct_val = float(pos.get("ct_val") or self._ct_val_for(base))

            # Update unrealized pnl
            if pos_side == "long":
                upl = (cur_px - entry_px) * amt * ct_val
            else:
                upl = (entry_px - cur_px) * amt * ct_val
            pos["unrealized_pnl"] = round(upl, 4)
            pos["upl"] = round(upl, 4)
            pos["mark_price"] = cur_px

            # 0. Check Liquidation BEFORE anything else
            lev = max(1.0, float(pos.get("leverage", 3.0) or 3.0))
            margin_locked = max(1e-9, float(pos.get("margin_locked") or (amt * ct_val * entry_px / lev)))
            mm_usd = amt * ct_val * entry_px * self.maintenance_margin_rate
            worst_px = low if pos_side == "long" else high
            worst_upl = ((worst_px - entry_px) if pos_side == "long" else (entry_px - worst_px)) * amt * ct_val
            if margin_locked + worst_upl <= mm_usd:
                liq_px = entry_px * (1.0 - max(0.0, 1.0 / lev - self.maintenance_margin_rate)) if pos_side == "long" else entry_px * (1.0 + max(0.0, 1.0 / lev - self.maintenance_margin_rate))
                for a in self._algo_orders.values():
                    if a["base"] == base and a.get("pos_side") == pos_side and a.get("state") == "live":
                        a["state"] = "cancelled"
                to_close.append((pos_key, liq_px, "LIQUIDATION"))
                continue

            # Find live algo order for this position
            active_algo = next(
                (a for a in self._algo_orders.values() if a["base"] == base and a.get("pos_side") == pos_side and a.get("state") == "live"),
                None,
            )
            if active_algo is None:
                continue

            tp_px = active_algo.get("tp_trigger_px")
            sl_px = active_algo.get("sl_trigger_px")
            initial_sl = float(pos.get("initial_sl_px") or sl_px or 0.0)
            if not pos.get("initial_sl_px") and sl_px:
                pos["initial_sl_px"] = float(sl_px)

            # CONSERVATIVE ORDER:
            # 1) Check STOP LOSS FIRST against current active SL (before updating BE or ratchets on this bar!)
            if pos_side == "long" and sl_px and low <= sl_px:
                active_algo["state"] = "filled"
                to_close.append((pos_key, float(sl_px) * (1.0 - self.slippage), "STOP_LOSS"))
                continue
            if pos_side == "short" and sl_px and high >= sl_px:
                active_algo["state"] = "filled"
                to_close.append((pos_key, float(sl_px) * (1.0 + self.slippage), "STOP_LOSS"))
                continue

            # 2) Partial TP1 (scale out 35% + move SL to fee-covering BE) if configured
            tp1_px = float(pos.get("tp1_px") or 0.0)
            if tp1_px > 0 and not pos.get("scale_out_done"):
                hit_tp1 = (high >= tp1_px) if pos_side == "long" else (low <= tp1_px)
                if hit_tp1 and amt > 0:
                    ratio = max(0.1, min(0.8, float(pos.get("scale_out_ratio") or 0.35)))
                    close_amt = amt * ratio
                    rem_amt = amt - close_amt
                    if rem_amt > 0:
                        self._settle_partial_close(pos, close_amt, tp1_px, exit_reason="SCALE_OUT_TP1")
                        pos["scale_out_done"] = True
                        be_off = float(pos.get("be_offset_pct") or 0.0030)
                        be_px = entry_px * (1.0 + be_off) if pos_side == "long" else entry_px * (1.0 - be_off)
                        if pos_side == "long":
                            active_algo["sl_trigger_px"] = max(float(sl_px or 0.0), be_px)
                        else:
                            active_algo["sl_trigger_px"] = min(float(sl_px or 1e18), be_px)
                        sl_px = active_algo["sl_trigger_px"]

            # 3) Check TAKE PROFIT 2
            if pos_side == "long" and tp_px and high >= tp_px:
                active_algo["state"] = "filled"
                to_close.append((pos_key, float(tp_px) * (1.0 - self.slippage), "TAKE_PROFIT"))
                continue
            if pos_side == "short" and tp_px and low <= tp_px:
                active_algo["state"] = "filled"
                to_close.append((pos_key, float(tp_px) * (1.0 + self.slippage), "TAKE_PROFIT"))
                continue

            # 4) Ratcheting Trailing / Fee-covering BE (for next bar!)
            atr_e = float(pos.get("atr_entry") or 0.0)
            if atr_e > 0:
                be_off = float(pos.get("be_offset_pct") or 0.0030)
                if pos_side == "long":
                    pos["peak_favorable_px"] = max(float(pos.get("peak_favorable_px") or entry_px), high)
                    mfe_px = high - entry_px
                    new_sl = float(sl_px or 0.0)
                    if mfe_px >= 2.3 * atr_e:
                        new_sl = max(new_sl, entry_px + 1.0 * atr_e)
                    elif mfe_px >= 1.25 * atr_e:
                        new_sl = max(new_sl, entry_px * (1.0 + be_off))
                    if new_sl > float(sl_px or 0.0):
                        active_algo["sl_trigger_px"] = new_sl
                else:
                    pos["peak_favorable_px"] = min(float(pos.get("peak_favorable_px") or entry_px), low)
                    mfe_px = entry_px - low
                    new_sl = float(sl_px or 1e18)
                    if mfe_px >= 2.3 * atr_e:
                        new_sl = min(new_sl, entry_px - 1.0 * atr_e)
                    elif mfe_px >= 1.25 * atr_e:
                        new_sl = min(new_sl, entry_px * (1.0 - be_off))
                    if sl_px is None or new_sl < float(sl_px):
                        active_algo["sl_trigger_px"] = new_sl

            # 5) Time stop check
            ts_hours = float(pos.get("time_stop_hours") or 0.0)
            opened_ms = int(pos.get("opened_ts_ms") or self.sim_time_ms)
            if ts_hours > 0 and atr_e > 0 and (self.sim_time_ms - opened_ms) >= ts_hours * 3600 * 1000:
                cur_move = abs(cur_px - entry_px)
                if cur_move < atr_e * 0.15:
                    active_algo["state"] = "filled"
                    exit_p = cur_px * (1.0 - self.slippage) if pos_side == "long" else cur_px * (1.0 + self.slippage)
                    to_close.append((pos_key, exit_p, "TIME_STOP"))

        for pos_key, exit_px, reason in to_close:
            self._close_virtual_position(pos_key, exit_px, exit_reason=reason)

    def _settle_partial_close(self, pos: Dict[str, Any], close_amt: float, exit_px: float, exit_reason: str = "SCALE_OUT_TP1") -> None:
        base = pos["base"]
        pos_side = pos["posSide"].lower()
        entry_px = float(pos["entry_price"])
        ct_val = float(pos.get("ct_val") or self._ct_val_for(base))
        gross_pnl = ((exit_px - entry_px) if pos_side == "long" else (entry_px - exit_px)) * close_amt * ct_val
        fee = close_amt * ct_val * exit_px * self.taker_fee
        net_pnl = gross_pnl - fee
        self.cash += net_pnl
        init_sl = float(pos.get("initial_sl_px") or 0.0)
        init_risk = abs(entry_px - init_sl) * close_amt * ct_val if init_sl > 0 else 0.0
        r_mult = (net_pnl / init_risk) if init_risk > 0 else 0.0
        frac = min(1.0, close_amt / max(1e-9, float(pos["amount"])))
        pos["margin_locked"] = float(pos.get("margin_locked", 0.0)) * (1.0 - frac)
        pos["amount"] = float(pos["amount"]) - close_amt
        pos["size_signed"] = pos["amount"] if pos_side == "long" else -pos["amount"]
        self._trades.append({
            "base": base,
            "pos_side": pos_side,
            "contracts": close_amt,
            "entry_price": entry_px,
            "exit_price": exit_px,
            "gross_pnl": gross_pnl,
            "fee": fee,
            "net_pnl": net_pnl,
            "initial_risk_usd": init_risk,
            "r_multiple": r_mult,
            "exit_reason": exit_reason,
            "ts_ms": self.sim_time_ms,
        })

    def _close_virtual_position(self, pos_key: str, exit_px: float, exit_reason: str = "CLOSE") -> Dict[str, Any]:
        pos = self._positions.pop(pos_key, None)
        if not pos:
            return {}
        base = pos["base"]
        amt = float(pos["amount"])
        entry_px = float(pos["entry_price"])
        pos_side = pos["posSide"].lower()
        ct_val = float(pos.get("ct_val") or self._ct_val_for(base))

        pnl = ((exit_px - entry_px) if pos_side == "long" else (entry_px - exit_px)) * amt * ct_val
        fee = amt * ct_val * exit_px * self.taker_fee
        net_pnl = pnl - fee
        self.cash += net_pnl
        init_sl = float(pos.get("initial_sl_px") or 0.0)
        init_risk = abs(entry_px - init_sl) * amt * ct_val if init_sl > 0 else 0.0
        r_mult = (net_pnl / init_risk) if init_risk > 0 else 0.0

        record = {
            "base": base,
            "pos_side": pos_side,
            "contracts": amt,
            "entry_price": entry_px,
            "exit_price": exit_px,
            "gross_pnl": pnl,
            "fee": fee,
            "net_pnl": net_pnl,
            "initial_risk_usd": init_risk,
            "r_multiple": r_mult,
            "exit_reason": exit_reason,
            "funding_paid_usd": float(pos.get("funding_paid_usd", 0.0)),
            "ts_ms": self.sim_time_ms,
        }
        self._trades.append(record)
        return record

    # -------------------------------------------------------------------------
    # BaseExchangeAdapter Protocol Implementation
    # -------------------------------------------------------------------------
    def fetch_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        base = canonical_base(symbol)
        c = self._current_candles.get(base)
        if not c:
            return None
        cur_px = float(c.get("close", 0))
        return {
            "venue": "sandbox",
            "inst_id": f"{base}-USDT-SWAP",
            "last": cur_px,
            "mark_price": cur_px,
            "bid": cur_px * 0.9998,
            "ask": cur_px * 1.0002,
            "open_24h": float(c.get("open", cur_px)),
            "high_24h": float(c.get("high", cur_px)),
            "low_24h": float(c.get("low", cur_px)),
            "chg_24h_pct": 0.0,
            "vol_24h_base": float(c.get("volume", 0)),
            "quote_vol_24h": float(c.get("volume", 0)) * cur_px,
            "ts_ms": self.sim_time_ms,
        }

    def fetch_candles(self, symbol: str, bar: str = "15m", limit: int = 100) -> Optional[List[List[Any]]]:
        """Strictly point-in-time: returns only candles where timestamp <= current simulation time."""
        base = canonical_base(symbol)
        key = f"{base}:{bar.lower()}"
        candles = self._candle_history.get(key)
        if not candles:
            c = self._current_candles.get(base)
            if c:
                return [[self.sim_time_ms, c.get("open"), c.get("high"), c.get("low"), c.get("close"), c.get("volume")]]
            return None

        # Filter strictly up to sim_time_ms to guarantee ZERO future data leak (Look-Ahead Barrier)
        slice_candles = [row for row in candles if int(row[0]) <= self.sim_time_ms]
        if not slice_candles:
            return None
        return slice_candles[-min(limit, len(slice_candles)) :]

    def fetch_orderbook(self, symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
        t = self.fetch_ticker(symbol)
        if not t or not t.get("last"):
            return None
        mid = float(t["last"])
        step = mid * 0.0002
        bids = [[round(mid - (i + 1) * step, 4), round(10.0 + i * 2, 2)] for i in range(min(depth, 50))]
        asks = [[round(mid + (i + 1) * step, 4), round(10.0 + i * 2, 2)] for i in range(min(depth, 50))]
        return {"venue": "sandbox", "bids": bids, "asks": asks}

    def fetch_funding_rate(self, symbol: str) -> Optional[float]:
        return 0.0001  # Standard 0.01% simulated rate

    def fetch_top_trader_ratio(self, symbol: str) -> Optional[float]:
        return 1.85

    def _load_spec(self, inst_id: str) -> Optional[InstrumentSpec]:
        base = canonical_base(inst_id)
        return InstrumentSpec(
            venue="sandbox",
            inst_id=f"{base}-USDT-SWAP",
            base=base,
            tick_size=0.1,
            step_size=0.01,
            ct_val=1.0,
            min_size=0.01,
            max_leverage=20.0,
            status="trading",
            raw={"simulated": True},
        )

    def positions(self) -> List[Dict[str, Any]]:
        return list(self._positions.values())

    def open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if not symbol:
            return list(self._open_orders.values())
        base = canonical_base(symbol)
        return [o for o in self._open_orders.values() if o.get("base") == base]

    def place_order(
        self,
        symbol: str,
        side: str,
        contracts: float,
        price: Optional[float] = None,
        order_type: str = "limit",
        pos_side: Optional[str] = None,
        client_order_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        base = canonical_base(symbol)
        self._order_counter += 1
        ord_id = f"sb_ord_{self._order_counter}"
        c = self._current_candles.get(base)
        cur_px = float(c.get("close", 0) if c else (price or 1.0))
        exec_price = float(price or cur_px)

        order_obj = {
            "venue": "sandbox",
            "order_id": ord_id,
            "id": ord_id,
            "client_order_id": client_order_id or f"cl_{ord_id}",
            "symbol": f"{base}-USDT-SWAP",
            "instId": f"{base}-USDT-SWAP",
            "base": base,
            "side": side.lower(),
            "pos_side": (pos_side or ("long" if side.lower() == "buy" else "short")).lower(),
            "price": exec_price,
            "contracts": float(contracts),
            "order_type": order_type.lower(),
            "state": "live",
            "created_time_ms": self.sim_time_ms,
            "leverage": kwargs.get("leverage", 3.0),
            "atr": kwargs.get("atr", 0.0),
            "initial_sl_px": kwargs.get("initial_sl_px", 0.0),
            "tp1_px": kwargs.get("tp1_px", 0.0),
            "scale_out_ratio": kwargs.get("scale_out_ratio", 0.35),
            "be_offset_pct": kwargs.get("be_offset_pct", 0.0030),
            "time_stop_hours": kwargs.get("time_stop_hours", 0.0),
        }

        if order_type.lower() == "market":
            # Immediate taker execution with slippage
            slippage_factor = (1.0 + self.slippage) if side.lower() == "buy" else (1.0 - self.slippage)
            fill_px = cur_px * slippage_factor
            self._execute_fill(order_obj, fill_px, is_maker=False)
            order_obj["state"] = "filled"
        else:
            self._open_orders[ord_id] = order_obj

        return {"venue": "sandbox", "symbol": f"{base}-USDT-SWAP", "result": order_obj, "order_id": ord_id, "id": ord_id}

    def cancel_order(self, symbol: str, order_id: Optional[str] = None, client_order_id: Optional[str] = None) -> Dict[str, Any]:
        target_id = None
        for oid, o in list(self._open_orders.items()):
            if order_id and oid == str(order_id):
                target_id = oid
                break
            if client_order_id and o.get("client_order_id") == str(client_order_id):
                target_id = oid
                break
        if target_id:
            self._open_orders.pop(target_id, None)
            return {"venue": "sandbox", "order_id": target_id, "cancelled": True}
        return {"venue": "sandbox", "order_id": order_id, "cancelled": False, "reason": "not found"}

    def attach_protective_orders(
        self,
        symbol: str,
        side: str,
        tp_px: Optional[float] = None,
        sl_px: Optional[float] = None,
        expiration: int = 604800,
        contracts: Optional[float] = None,
    ) -> Dict[str, Any]:
        base = canonical_base(symbol)
        pos_s = ("long" if str(side).lower() in ("buy", "long") else "short").lower()
        self._algo_counter += 1
        algo_id = f"sb_algo_{self._algo_counter}"

        algo_obj = {
            "venue": "sandbox",
            "id": algo_id,
            "algo_id": algo_id,
            "base": base,
            "symbol": f"{base}-USDT-SWAP",
            "pos_side": pos_s,
            "tp_trigger_px": float(tp_px) if tp_px else None,
            "sl_trigger_px": float(sl_px) if sl_px else None,
            "contracts": float(contracts) if contracts else None,
            "state": "live",
            "created_time_ms": self.sim_time_ms,
        }
        self._algo_orders[algo_id] = algo_obj
        if sl_px and float(sl_px) > 0:
            pos_key = f"{base}:{pos_s}"
            pos = self._positions.get(pos_key)
            if pos is not None and not pos.get("initial_sl_px"):
                pos["initial_sl_px"] = float(sl_px)
        return {"venue": "sandbox", "tp": f"tp_{algo_id}", "sl": f"sl_{algo_id}", "algo_id": algo_id, "id": algo_id}

    def list_protective_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if not symbol:
            return list(self._algo_orders.values())
        base = canonical_base(symbol)
        return [a for a in self._algo_orders.values() if a.get("base") == base and a.get("state") == "live"]

    def fast_close_position(self, symbol: str) -> Dict[str, Any]:
        base = canonical_base(symbol)
        matching_keys = [k for k in self._positions if k.startswith(f"{base}:")]
        if not matching_keys:
            raise ValueError(f"未找到 {symbol} 的活动沙箱持仓")
        c = self._current_candles.get(base)
        cur_px = float(c.get("close", 0) if c else 1.0)
        results = []
        for k in matching_keys:
            res = self._close_virtual_position(k, cur_px)
            results.append(res)
        return {"venue": "sandbox", "symbol": f"{base}-USDT-SWAP", "result": results}

    @property
    def equity(self) -> float:
        unrealized = sum(float(p.get("unrealized_pnl", 0) or 0) for p in self._positions.values())
        return round(self.cash + unrealized, 2)
