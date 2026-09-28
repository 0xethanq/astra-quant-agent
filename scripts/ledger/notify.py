"""台账同步后的新平仓通知（从 sync_full_ledger.build_lifecycle_ledger 搬出）。

判定"新平仓"= id 不在本轮既有已平集合里、且 status == "closed"；三路来源
（OKX 生命周期 + Binance + Gate）合并后逐条通知。

qq_notifier 用**惰性导入**（函数内），保持原语义以免拖慢/拖挂在未配置通知的环境；
通知失败只打印告警，绝不影响台账落盘（整段在 try 内）。

返回值为空：副作用是外部通知，与本模块纯判定部分不同，故单列一个文件。
"""
def notify_newly_closed_trades(*,
        binance_trades,
        existing_closed_ids,
        gate_trades,
        trades_lifecycle):
    # Notify newly closed trades via QQ
    try:
        from qq_notifier import notify_trade_close
        for t in (trades_lifecycle + binance_trades + gate_trades):
            if t["id"] not in existing_closed_ids and t.get("status") == "closed":
                _kw = dict(
                    inst=t.get("inst", "CRYPTO"),
                    pnl=float(t.get("pnl", 0.0) or 0.0),
                    stage=t.get("exit_reason", "平仓结清"),
                    exit_px=float(t.get("close_px", 0.0) or 0.0),
                    roi_pct=float(t.get("roi_pct", 0.0) or 0.0),
                    duration_str=str(t.get("duration", "")),
                )
                if t.get("venue"):
                    _kw["venue"] = str(t.get("venue")).lower()
                if t.get("side") or t.get("action"):
                    _kw["side"] = str(t.get("side") or t.get("action"))
                if t.get("open_px"):
                    _kw["entry_px"] = float(t["open_px"])
                if t.get("fee") is not None:
                    _kw["fee"] = float(t["fee"])
                if t.get("net_pnl") is not None:
                    _kw["net_pnl"] = float(t["net_pnl"])
                notify_trade_close(**_kw)
    except Exception as e:
        print(f"[Ledger Sync Notify Warning] {e}")

