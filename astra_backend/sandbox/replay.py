"""Point-in-Time Backtest & Decision Replay Engine with strict look-ahead isolation."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from astra_backend.sandbox.adapter import SandboxExchangeAdapter


@dataclass
class ReplayMetrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    initial_equity: float = 10000.0
    final_equity: float = 10000.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    avg_r_multiple: float = 0.0
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    trades: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PointInTimeReplayEngine:
    """Orchestrates deterministic historical replay with SandboxExchangeAdapter."""

    def __init__(
        self,
        initial_balance: float = 10000.0,
        maker_fee: float = 0.0002,
        taker_fee: float = 0.0005,
        slippage: float = 0.0002,
    ) -> None:
        self.adapter = SandboxExchangeAdapter(
            initial_balance=initial_balance,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            slippage=slippage,
        )

    def run_replay(
        self,
        symbols_candles: Dict[str, List[List[Any]]],
        strategy_step_fn: Callable[[SandboxExchangeAdapter, int], Optional[List[Dict[str, Any]]]],
        bar: str = "15m",
    ) -> ReplayMetrics:
        """Run step-by-step point-in-time replay.

        symbols_candles: {
            "BTC": [[ts_0, o, h, l, c, v], [ts_1, o, h, l, c, v], ...],
            "ETH": [[ts_0, o, h, l, c, v], [ts_1, o, h, l, c, v], ...],
        }
        strategy_step_fn: (adapter, current_ts_ms) -> optional order signals
        """
        self.adapter.reset()

        # Load full historical buffers into adapter
        for sym, candles in symbols_candles.items():
            self.adapter.set_historical_candles(sym, bar, candles)

        # Collect and sort all distinct simulation timestamps
        all_timestamps = set()
        candle_lookup: Dict[str, Dict[int, List[Any]]] = {}
        for sym, candles in symbols_candles.items():
            candle_lookup[sym] = {int(c[0]): c for c in candles}
            all_timestamps.update(candle_lookup[sym].keys())

        sorted_ts = sorted(all_timestamps)
        if not sorted_ts:
            return ReplayMetrics(initial_equity=self.adapter.initial_balance, final_equity=self.adapter.initial_balance)

        equity_curve: List[Dict[str, Any]] = [{"ts_ms": sorted_ts[0], "equity": self.adapter.initial_balance}]
        peak_equity = self.adapter.initial_balance
        max_drawdown = 0.0
        equity_snapshots: List[float] = [self.adapter.initial_balance]

        for ts in sorted_ts:
            # Build current snapshot across active instruments
            snapshot = {}
            for sym, lookup in candle_lookup.items():
                if ts in lookup:
                    c = lookup[ts]
                    snapshot[sym] = {
                        "ts_ms": ts,
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]) if len(c) > 5 else 0.0,
                    }

            # 1. Step the exchange clock (matches open orders & triggers SL/TP)
            self.adapter.step(snapshot)

            # 2. Invoke strategy (isolated from future data: adapter only returns data <= ts)
            signals = strategy_step_fn(self.adapter, ts)
            if signals:
                for sig in signals:
                    sym = sig.get("symbol") or sig.get("asset")
                    side = sig.get("side") or ("buy" if "BUY" in str(sig.get("action", "")) else "sell")
                    contracts = float(sig.get("contracts") or sig.get("size") or 0.1)
                    price = float(sig.get("price") or sig.get("entry_price") or 0.0)
                    order_type = sig.get("order_type", "market")
                    pos_side = sig.get("pos_side") or ("long" if side == "buy" else "short")

                    # Place virtual order
                    self.adapter.place_order(
                        symbol=sym,
                        side=side,
                        contracts=contracts,
                        price=price if order_type == "limit" else None,
                        order_type=order_type,
                        pos_side=pos_side,
                    )
                    # If protective prices attached, attach them
                    tp_px = sig.get("take_profit_price") or sig.get("tp_px")
                    sl_px = sig.get("stop_loss_price") or sig.get("sl_px")
                    if tp_px or sl_px:
                        self.adapter.attach_protective_orders(
                            symbol=sym,
                            side=side,
                            tp_px=float(tp_px) if tp_px else None,
                            sl_px=float(sl_px) if sl_px else None,
                            contracts=contracts,
                        )

            # 3. Track Equity Curve & Drawdown
            current_eq = self.adapter.equity
            equity_snapshots.append(current_eq)
            peak_equity = max(peak_equity, current_eq)
            if peak_equity > 0:
                dd = (peak_equity - current_eq) / peak_equity * 100.0
                max_drawdown = max(max_drawdown, dd)
            equity_curve.append({"ts_ms": ts, "equity": current_eq})

        # Calculate institutional statistics
        final_equity = self.adapter.equity
        total_return_pct = round(((final_equity - self.adapter.initial_balance) / self.adapter.initial_balance) * 100.0, 2)

        trades = [t for t in self.adapter._trades if "net_pnl" in t]
        total_trades = len(trades)
        winning = [t for t in trades if t["net_pnl"] > 0]
        losing = [t for t in trades if t["net_pnl"] < 0]
        win_rate = round((len(winning) / total_trades) * 100.0, 2) if total_trades > 0 else 0.0

        gross_profit = sum(t["net_pnl"] for t in winning)
        gross_loss = abs(sum(t["net_pnl"] for t in losing))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        # Sharpe, Sortino, Calmar
        returns = []
        for i in range(1, len(equity_snapshots)):
            prev = equity_snapshots[i - 1]
            returns.append((equity_snapshots[i] - prev) / prev if prev > 0 else 0.0)

        sharpe = 0.0
        sortino = 0.0
        if len(returns) >= 2:
            mean_ret = sum(returns) / len(returns)
            var = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            std_dev = math.sqrt(var)
            if std_dev > 1e-9:
                sharpe = round((mean_ret / std_dev) * math.sqrt(365 * 24 * 4), 2)

            downside_var = sum((r - mean_ret) ** 2 for r in returns if r < 0) / len(returns)
            downside_std = math.sqrt(downside_var)
            if downside_std > 1e-9:
                sortino = round((mean_ret / downside_std) * math.sqrt(365 * 24 * 4), 2)

        calmar = round(total_return_pct / max_drawdown, 2) if max_drawdown > 0 else (99.0 if total_return_pct > 0 else 0.0)

        return ReplayMetrics(
            total_trades=total_trades,
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            initial_equity=self.adapter.initial_balance,
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            max_drawdown_pct=round(max_drawdown, 2),
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            avg_r_multiple=round((gross_profit / (len(winning) or 1)) / (gross_loss / (len(losing) or 1)), 2) if losing else 1.0,
            equity_curve=equity_curve,
            trades=trades,
        )
