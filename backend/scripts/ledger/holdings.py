"""持仓行构造的两个判定件（`scripts/ledger/` 部件，从 `sync_full_ledger.py` 搬出）。

| 函数 | 规则 |
|---|---|
| `judge_position_side` | **审计 C8**：net-mode 行 `posSide="net"` 使旧式 `"long" in side_raw` 恒 False ⇒ 净模式多仓被**系统性标成"空"**（策略/追踪 join 全错位）。改为按符号回退判向；符号不可判 → 诚实标"未知"，绝不猜 |
| `format_holding_duration` | 持仓时长：`<60分钟` 显示"N分钟"，否则"N时M分"；时间戳解析失败 → `"--"`（不得抛错） |

## 为什么只搬这两段，不搬 `_holding_row` 本体

既有门 `test_ledger_okx_history_extraction::test_facade_still_exposes_the_public_surface_tests_use`
明确要求 `_holding_row` **仍以 `def` 形式定义在门面**（该名被测试直接调用 + 双导入路径）。
故只抽它内部的**判定段**，本体留在门面（与第一百零三刀被拦下的那次同一类边界）。

两函数皆**纯计算**（无 IO、无 print），`datetime` 按调用方注入。
"""
def judge_position_side(*,
        p,
        side_raw):
    # 审计 C8：net-mode 行 posSide="net"，旧式 `"long" in side_raw` 恒 False
    # → 净模式多仓被系统性标成"空"（策略/追踪 join 全错位）。按符号回退判向，
    # 符号不可判 → 诚实标"未知"，绝不猜。
    if "long" in side_raw:
        side = "多"
    elif "short" in side_raw:
        side = "空"
    else:
        try:
            _signed = float(p.get("pos", 0) or 0)
        except (TypeError, ValueError):
            _signed = 0.0
        side = "多" if _signed > 0 else ("空" if _signed < 0 else "未知")
    return side


def format_holding_duration(*,
        datetime,
        open_time,
        tz_bj):
    try:
        # ⚠️ 原有 bug 修复（第一百零七刀）：`open_time` 由 `fromtimestamp(..., tz=tz_bj)`
        # 格式化而来，但 `strptime` 得到的是 **naive** datetime，而 `now(tz_bj)` 是 **aware**
        # ⇒ 相减必抛 TypeError ⇒ `except` 生效 ⇒ **持仓时长恒为 `"--"`**
        # （QQ 通知里显示成"⏱️ 持仓时长：--"）。按语义把 open_time 标回北京时区，
        # 使两侧 aware 一致；`t2 - t1` 那种 naive−naive 的写法（ledger/okx_history.py）本来就对，未动。
        t1 = datetime.datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_bj)
        now_dt = datetime.datetime.now(tz_bj)
        dur_mins = int((now_dt - t1).total_seconds() / 60)
        duration_str = f"{dur_mins}分钟" if dur_mins < 60 else f"{dur_mins//60}时{dur_mins%60}分"
    except Exception:
        duration_str = "--"
    return duration_str



def purge_stale_holding_rows(*,
        _holding_rows,
        _queried_venues,
        trades_map):
    # 批E·幽灵持仓清理：台账 holding 行必须以「本轮成功取数的场所的实时持仓」为准。
    # 旧实现只按 id 覆盖新行、从不删除失效行 → 平仓后 holding 行永久留存（实测
    # holding_ALGO_多 标 venue=okx 而 OKX 已零持仓，前台台账里挂着一条不存在的仓）。
    # 仅对 _queried_venues 内的场所生效：取数失败的场所保守保留旧行（缺失≠已平仓）。
    _live_holding_ids = {t["id"] for t in _holding_rows}
    _purged_holdings = []
    for _oid in [k for k, v in trades_map.items()
                 if isinstance(v, dict) and v.get("status") == "holding"
                 and str(v.get("venue") or "").lower() in _queried_venues
                 and k not in _live_holding_ids]:
        trades_map.pop(_oid)
        _purged_holdings.append(_oid)
    return _purged_holdings
