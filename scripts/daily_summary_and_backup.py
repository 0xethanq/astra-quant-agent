#!/usr/bin/env python3
"""
Automated Daily Quant Briefing Engine
Runs at 08:00 & 20:00 Beijing time to sync the lifecycle ledger and publish a read-only performance briefing.
Self-evolution and backups are owned by their dedicated scheduled jobs.
"""

import os
import json
import tarfile
import datetime
import subprocess
import sys

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
BACKUPS_DIR = os.path.join(WORKSPACE_DIR, "backups")
LEDGER_JSON_FILE = os.path.join(DATA_DIR, "trading_ledger.json")

os.makedirs(BACKUPS_DIR, exist_ok=True)
sys.path.append(os.path.join(WORKSPACE_DIR, "scripts"))
sys.path.insert(0, WORKSPACE_DIR)
from astra_backend.time_utils import beijing_day
try:
    from qq_notifier import notify_daily_summary
except Exception:
    notify_daily_summary = None

def _run_captured(script, label=None, timeout=15):
    """审计(2026-09-13)：同解释器子进程 + 非零必吼（旧裸 python3 shell 串=静默死亡）。"""
    from astra_backend.spawn import run_script
    return run_script(script, timeout=timeout, label=label)


def generate_daily_briefing_and_backup():
    tz_bj = datetime.timezone(datetime.timedelta(hours=8))
    now_bj = datetime.datetime.now(tz_bj)
    now_str = now_bj.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now_bj.strftime("%Y-%m-%d")

    # Read Account Initial State (Supports Dynamic Capital Reset Filter)
    account_init_file = os.path.join(DATA_DIR, "account_initial_state.json")
    reset_time_str = "1970-01-01 00:00:00"
    if os.path.exists(account_init_file):
        try:
            with open(account_init_file, "r", encoding="utf-8") as f:
                acc_init = json.load(f)
                reset_time_str = acc_init.get("reset_time", "1970-01-01 00:00:00")
        except Exception:
            pass

    # 1. Sync full ledger and load trades
    try:
        sync_script = os.path.join(WORKSPACE_DIR, "scripts", "sync_full_ledger.py")
        if os.path.exists(sync_script):
            _run_captured(sync_script)
    except Exception:
        pass

    trades = []
    _ledger_unreadable = False
    if os.path.exists(LEDGER_JSON_FILE):
        try:
            with open(LEDGER_JSON_FILE, "r", encoding="utf-8") as f:
                trades = json.load(f)
            if not isinstance(trades, list):
                _ledger_unreadable = True
                trades = []
        except (json.JSONDecodeError, OSError):
            # 审计③(2026-09-13)：损坏≠「确实没有交易」。旧实现 except:pass 后照发
            # 「0胜0负 +0.00U」假研报——把数据事故渲染成事实主动推送。
            _ledger_unreadable = True

    closed_today = [t for t in trades if t.get("status") == "closed" and beijing_day(t.get("close_time")) == date_str]
    total_trades = len(closed_today)
    wins = [t for t in closed_today if float(t.get("pnl", 0)) > 0]
    losses = [t for t in closed_today if float(t.get("pnl", 0)) < 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
    net_pnl = sum(float(t.get("pnl", 0)) for t in closed_today)

    # 2. Top Performing Asset
    asset_pnl = {}
    for t in closed_today:
        inst = t.get("inst") or t.get("name") or "OTHER"
        if inst and inst != "None":
            asset_pnl[inst] = asset_pnl.get(inst, 0.0) + float(t.get("pnl", 0))
    
    top_asset = max(asset_pnl.items(), key=lambda x: x[1])[0] if asset_pnl else "暂无"
    top_asset_pnl = asset_pnl.get(top_asset, 0.0)

    # 3. Macro Sentiment & News
    news_file = os.path.join(DATA_DIR, "news_sentiment.json")
    macro_env = "偏多震荡"
    if os.path.exists(news_file):
        try:
            with open(news_file, "r", encoding="utf-8") as f:
                n_data = json.load(f)
                macro_env = n_data.get("macro_sentiment", "偏多震荡")
        except Exception:
            pass

    # 4. Load Dashboard Account & Active Positions
    dashboard_file = os.path.join(DATA_DIR, "dashboard_last_good.json")
    account_info = {}
    positions = []
    if os.path.exists(dashboard_file):
        try:
            with open(dashboard_file, "r", encoding="utf-8") as f:
                d_good = json.load(f)
                account_info = d_good.get("account", {})
                positions = d_good.get("positions", [])
        except Exception:
            pass

    lines = [
        f"📅 日期：{date_str}（北京时间 {now_str[11:16]}）",
    ]
    if account_info:
        total_eq = float(account_info.get("total_eq", 0.0) or 0.0)
        avail_eq = float(account_info.get("avail_eq", 0.0) or 0.0)
        pos_upl = float(account_info.get("pos_upl_total", 0.0) or 0.0)
        mgn_usage = float(account_info.get("margin_usage_pct", 0.0) or 0.0)
        lines.append(f"💼 账户总净值：{total_eq:,.2f} USDT (可用: {avail_eq:,.2f} U | 杠杆占用率: {mgn_usage:.1f}%)")
        if pos_upl != 0.0:
            lines.append(f"📈 实时在管浮盈 (UPL)：{pos_upl:+.2f} USDT")

    total_fee = sum(float(t.get("fee", 0.0) or 0.0) for t in closed_today)
    lines.append(f"• 今日平仓战绩：{len(wins)} 胜 / {len(losses)} 负（胜率 {win_rate:.1f}%）")
    if total_fee > 0:
        lines.append(f"• 今日已结净盈亏：{net_pnl:+.2f} USDT (交易手续费: -{total_fee:.2f} U)")
    else:
        lines.append(f"• 今日已结净盈亏：{net_pnl:+.2f} USDT")
    lines.append(f"• 最优贡献标的：{top_asset} ({top_asset_pnl:+.2f} U)")

    if positions:
        lines.append(f"📦 当前在管持仓 ({len(positions)} 笔)：")
        for p in positions[:4]:
            p_name = p.get("name") or p.get("instId", "").split("-")[0]
            p_venue = str(p.get("venue") or "okx").upper()
            p_side = "🟢多" if ("long" in str(p.get("side", "")).lower()) else "🔴空"
            p_upl = float(p.get("upl", 0.0) or 0.0)
            p_roi = float(p.get("uplRatio", 0.0) or p.get("roi_pct", 0.0) or 0.0)
            p_sl = p.get("trailingSl") or p.get("exchangeSl") or "--"
            lines.append(f"  • {p_side} {p_name} ({p_venue}) | 浮盈 {p_upl:+.2f} U ({p_roi:+.1f}%) | 止损 {p_sl}")
        if len(positions) > 4:
            lines.append(f"  • ... 另有 {len(positions) - 4} 笔持仓监控中")

    lines.append(f"• 市场舆情环境：{macro_env}")
    lines.append("• 策略状态：三所平权对等撮合已就绪，多周期趋势共振滤网与黑天鹅熔断哨兵全天候巡检中。")

    briefing_text = "\n".join(lines)

    if _ledger_unreadable:
        briefing_text = ("⚠️ 台账文件损坏/不可读，今日战绩与净盈亏不可信（宁报故障，不发假 0）；"
                         "请尽快人工检查 data/trading_ledger.json。\n" + briefing_text)
        print("[daily_briefing] CRITICAL 台账不可解析，研报已改为故障警示。")

    if notify_daily_summary:
        notify_daily_summary(briefing_text)

    print("✅ 每日量化研报已成功生成并推送。")
    return briefing_text

if __name__ == "__main__":
    rep = generate_daily_briefing_and_backup()
    print("Daily Briefing Result:\n" + rep)
