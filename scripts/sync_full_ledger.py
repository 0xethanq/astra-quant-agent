#!/usr/bin/env python3
"""
ASTRA Authentic OKX Positions-History Ledger Synchronizer (sync_full_ledger.py)
Directly reads OKX official `account positions-history` & `account positions` API.
Eliminates bills heuristic split-error, accurately records real position-level trades!
"""

import json
import os
import sys
import datetime
import tempfile
import warnings

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import scripts.okx_rest as okx_rest
import scripts.okx_runtime as okx_runtime

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: ⚠️ `ASTRA_DATA_DIR` 是**测试沙箱专用环境变量**（由 tests/config_sandbox.isolate_config
#: 设置、由 `run_script` 拉起的子进程继承）：跑测试时把 data/ 写入重定向到沙箱，
#: **生产从不设置该变量 → 取值与原先逐位相同**。修复"测试经子进程写生产文件"
#: 的泄漏（§88/§91.6），不改任何业务行为。
DATA_DIR = os.environ.get("ASTRA_DATA_DIR") or os.path.join(WORKSPACE_DIR, "data")
LEDGER_JSON_FILE = os.path.join(DATA_DIR, "trading_ledger.json")
LEDGER_SYNC_STATUS_FILE = os.path.join(DATA_DIR, "ledger_sync_status.json")

#: 本轮同步中被准入清单挡掉的**活动持仓**（模块级：`_write_sync_status` 与同步主体
#: 不在同一函数内；每轮同步开始时由同步主体清空）。
_UNMANAGED_LIVE: list = []
# 审计 A2（数据诚实）：逐所台账同步状态旁车。任一 fetch 失败只 print-warn 后
# 返回 []，与「该所确无平仓」在 trading_ledger.json 里不可分辨；旁车记录
# ok/failed(原因)/failed(截断风险)，供 data_health/前台显式 PARTIAL。
_FETCH_STATUS = {}


def _mark(venue, status, **extra):
    rec = {"status": status}
    rec.update(extra)
    _FETCH_STATUS[venue] = rec


def _fetch_history_paged(fetch_fn, *, id_field="posId", cursor_field="uTime", limit=100, max_pages=5):
    """OKX 历史接口分页取尽（after=取更早）。

    批C(2026-09-13)：原实现单页 limit 条即止 —— 平仓笔数越 100 后更早记录永远取不到，
    台账只能靠旧 JSON 合并续命（重算/迁移即静默丢历史），data_health 也只能挂一条
    「触顶 limit=100，可能存在截断」的常驻告警。

    ⚠️ 实测校正（demo 实号，2026-09-13）：positions-history 的 after/before **只认毫秒
    时间戳**——传 posId 直接 `51000 Parameter after error`（官方文档措辞为 "earlier than
    the requested posId"，与实现不符）。故游标取末条的 uTime，after=向更早回溯。

    返回 (rows, truncated)：
      · 防漏 —— 逐页累加，按 (id, uTime) 去重（实测分页边界有 4 条重叠）；
      · 防死循环 —— 页未满即取尽；游标不再变旧/零新增（服务端忽略 after 时会把同一页
        反复返回）立即停；页满且用尽 max_pages 也停；
      · 诚实 —— 凡「停时仍未证取尽」一律 truncated=True，前台继续显式 PARTIAL，
        绝不因为「多取了几页」就假称完整。
    """
    rows: list = []
    seen: set = set()
    cursor = None
    prev_cursor = None
    truncated = False
    for _ in range(max(1, int(max_pages))):
        page = fetch_fn(limit=limit, after=cursor) or []
        if not page:
            break
        fresh = 0
        for _r in page:
            _k = (str(_r.get(id_field) or ""), str(_r.get(cursor_field) or ""))
            if _k in seen:
                continue
            seen.add(_k)
            rows.append(_r)
            fresh += 1
        _new_cursor = str(page[-1].get(cursor_field) or "")
        if len(page) < limit:
            break                      # 服务端已给尽
        if fresh == 0 or not _new_cursor or _new_cursor == prev_cursor:
            truncated = True           # 无法继续（游标无效/被忽略）→ 诚实标记
            break
        prev_cursor = _new_cursor
        cursor = _new_cursor
    else:
        truncated = True               # 页页全满且用尽页数上限
    return rows, truncated


#: 状态旁车里最多列出几条"无主活动持仓"（有界；超出只报总数，避免无界增长）。
UNMANAGED_LIST_MAX = 10


def unmanaged_positions_payload(unmanaged, *, limit: int = UNMANAGED_LIST_MAX):
    """丢弃的活仓 → 旁车载荷（**有界**）：`{"count", "items", "omitted"}`。

    有界是硬要求：这个字段会被写进每 15 分钟覆盖的旁车并进面板 source_errors，
    无界列表会随持仓数无限膨胀（本刀对"标签/列表基数必须有界"的一贯要求）。
    计数**必须**是完整数（`count` 不受 `limit` 影响）——报少一条等于没报。
    """
    rows = list(unmanaged or [])
    items = []
    for r in rows[: max(0, int(limit))]:
        items.append({"venue": str(r.get("venue") or ""),
                      "instId": str(r.get("instId") or ""),
                      "size": r.get("size"),
                      "side_raw": str(r.get("side_raw") or "")})
    return {"count": len(rows), "items": items,
            "omitted": max(0, len(rows) - len(items))}


def _write_sync_status(env):
    """原子写旁车；读侧一律容错缺文件（旧版本无旁车=按 OK 不误伤）。
    路径按调用时 DATA_DIR 解析——测试 patch 模块 DATA_DIR 即封闭（律①）。"""
    _dir = DATA_DIR
    target = os.path.join(_dir, "ledger_sync_status.json")
    payload = {
        "generated_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        "environment": "demo" if getattr(env, "simulated", False) else "live",
        "venues": dict(_FETCH_STATUS),
    }
    # 无主活动持仓：**有才写**（空/缺字段=旧版本旁车，读侧一律容错）
    _unm = unmanaged_positions_payload(_UNMANAGED_LIVE)
    if _unm["count"]:
        payload["unmanaged_positions"] = _unm
    fd, tmp = tempfile.mkstemp(prefix=".lss-", suffix=".tmp", dir=_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except Exception as exc:
        print(f"[sync_full_ledger] warn 台账同步状态旁车写入失败: {exc}")
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


INITIAL_STATE_FILE = os.path.join(DATA_DIR, "account_initial_state.json")
POSITION_TRACKER_FILE = os.path.join(DATA_DIR, "position_trackers.json")
#: 平仓证据旁车（由 `scripts/trader/close_evidence.py` 在平仓前写入）。
CLOSE_EVIDENCE_FILE = os.path.join(DATA_DIR, "closed_trade_evidence.json")

from instrument_pool import load_instruments

TARGET_INSTRUMENTS = load_instruments()

# 历史币种白名单缓存：交易所规格回退查询用（进程内一次即可）
_CTVAL_CACHE = {}

def _sqlite_traded_names():
    """SQLite 台账里出现过的币种名（已下架币种的历史事实源）。"""
    names = set()
    try:
        import sqlite3
        db = os.path.join(DATA_DIR, "astra_quant.db")
        if os.path.exists(db):
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for (inst,) in con.execute("SELECT DISTINCT inst FROM trades"):
                if inst:
                    names.add(str(inst))
            con.close()
    except Exception:
        pass
    return names

def allowed_inst_ids(existing_ledger_trades=None):
    """台账重建允许集合 = 当前标的池 ∪ 历史留痕币种。

    修复(2026-09-09)：此前重建仅认当前池，用户从池中删除币种后，下一次同步
    会把该币种的全部已平仓历史从 trading_ledger.json 抹掉（SQLite 仍在，但页面
    台账消失）；持仓中途删币还会让在途仓位在台账里隐身。历史是交易所事实，
    不随池配置消亡；噪声过滤（拦截 ASTRA 从未交易过的手动单）由并集继续保证。
    """
    allowed = {item["instId"] for item in TARGET_INSTRUMENTS}
    names = _sqlite_traded_names()
    for t in (existing_ledger_trades or []):
        inst = str(t.get("inst") or t.get("name") or "")
        if inst:
            names.add(inst)
    try:
        if os.path.exists(POSITION_TRACKER_FILE):
            with open(POSITION_TRACKER_FILE, "r", encoding="utf-8") as f:
                for key in json.load(f):
                    inst = str(key).rsplit("_", 1)[0]
                    if inst:
                        names.add(inst)
    except Exception:
        pass
    for n in names:
        n = n.strip()
        if not n:
            continue
        allowed.add(n if "-USDT-SWAP" in n or "-USD-SWAP" in n else f"{n}-USDT-SWAP")
    return allowed

def get_ct_val(inst_name):
    for item in TARGET_INSTRUMENTS:
        if item["name"] == inst_name or item["instId"] == inst_name:
            return item["ctVal"]
    # 已下架币种回退：查 OKX 公共合约规格（免费、无需鉴权），进程内缓存
    inst_id = inst_name if "-SWAP" in inst_name else f"{inst_name}-USDT-SWAP"
    if inst_id in _CTVAL_CACHE:
        return _CTVAL_CACHE[inst_id]
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId={inst_id}",
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        rows = payload.get("data") or []
        ct = float(rows[0].get("ctVal", 1.0) or 1.0) if rows else 1.0
    except Exception:
        ct = 1.0
    _CTVAL_CACHE[inst_id] = ct
    return ct


def _history_truncated_in_scope(truncated, oldest_ms, reset_time, tz_bj):
    """分页未取尽时，判断「是否仍可能漏掉在册记录」。

    台账只收 `close_time >= reset_time` 的记录（build 内同判据，见 build_lifecycle_ledger）。
    因此：取到的最早记录若已早于基线，未取尽的部分不可能含在册记录 → 不算截断。
    批C(2026-09-13)：若无此判定，max_pages 上限会让 data_health 永久挂一条假 PARTIAL
    （实测 500 条时最早到 05-15，而基线是 09-11，台账其实一条不漏），真正的取数失败
    反而淹没在常驻噪声里。
    取不到最早时间（oldest_ms<=0）时保守判为截断。
    """
    if not truncated:
        return False
    try:
        _ms = int(oldest_ms or 0)
    except Exception:
        _ms = 0
    if _ms <= 0:
        return True
    try:
        _t = datetime.datetime.fromtimestamp(_ms / 1000.0, tz=tz_bj).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return True
    return _t >= str(reset_time)


def _holding_row(p, venue, *, env, trackers, tz_bj, allowed, council_by_inst,
                 unmanaged=None):
    """活动持仓 → 台账 holding 行。

    id 带场所：`holding_{venue}_{inst}_{side}`。旧式 `holding_{inst}_{side}` 不含场所，
    同一标的重复持有即撞键（后写覆盖先写）。
    """
    pos_sz = float(p.get("pos", 0.0) or 0.0)
    if pos_sz == 0.0:
        return None
    inst_id = p.get("instId", "")
    if inst_id not in allowed:
        # ⚠️ 2026-09-20 实测：这里曾**静默丢弃**——持仓因不在准入清单而连一行 holding
        # 都没有；台账于是"看不见"这笔在持敞口，
        # 而开仓预检又把它当"外部仓"永久拒开（两处都错，且都没人说）。
        # 现在把丢弃的活仓**记入调用方收集器**（写入同步旁车 + 日志 + 面板 source_errors）：
        # 仍然**不**把它写进台账（那会改变风险界面语义，须单独拍板），但**不许再无声**。
        if unmanaged is not None:
            unmanaged.append({"venue": str(venue or ""), "instId": inst_id,
                              "size": pos_sz,
                              "side_raw": str(p.get("posSide", p.get("side", "")) or "")})
        return None
    inst = inst_id.replace("-USDT-SWAP", "")
    side_raw = str(p.get("posSide", p.get("side", ""))).lower()
    side = judge_position_side(
        p=p,
        side_raw=side_raw    )
    avg_px = float(p.get("avgPx", 0) or 0)
    mark_px = float(p.get("markPx", 0) or 0)
    upl = float(p.get("upl", 0) or 0)
    try:
        lever = int(float(p.get("lever", "3") or 3))
    except (TypeError, ValueError):
        lever = 3
    fee = float(p.get("fee", 0.0) or 0.0)
    funding_fee = float(p.get("funding_fee", 0.0) or 0.0)
    ct_val = get_ct_val(inst)

    raw_notional = abs(float(p.get("notional", 0.0) or 0.0))
    if raw_notional > 0:
        notional = raw_notional
    else:
        notional = pos_sz * ct_val * mark_px

    raw_margin = float(p.get("margin", 0.0) or 0.0)
    margin_usdt = round(raw_margin, 2) if raw_margin > 0 else (round(notional / lever, 2) if lever > 0 else round(notional, 2))
    roi_pct = round((upl / margin_usdt * 100) if margin_usdt > 0 else 0.0, 2)

    _c_raw = p.get("cTime", 0) or 0
    try:
        c_ts = float(_c_raw) / 1000.0
    except (TypeError, ValueError):
        c_ts = 0.0
    open_time = datetime.datetime.fromtimestamp(c_ts, tz=tz_bj).strftime("%Y-%m-%d %H:%M:%S") if c_ts > 0 else "--"

    pos_k = f"{inst_id}_{'long' if side == '多' else 'short'}"
    t_info = trackers.get(pos_k, {})
    strat_tag = t_info.get("strategy_tag") or ("🌊 低吸" if side == "多" else "⚡ 高空")

    duration_str = format_holding_duration(
        datetime=datetime,
        open_time=open_time,
        tz_bj=tz_bj    )

    return {
        "id": f"holding_{venue}_{inst}_{side}",
        "inst": inst,
        "side": side,
        "venue": venue,
        "account_mode": env.mode.upper(),
        "environment": env.mode.lower(),
        "lever": f"{lever}x",
        "strategy": strat_tag,
        "margin": margin_usdt,
        "sz": pos_sz,
        "open_time": open_time,
        "open_px": avg_px,
        "close_time": "持仓中...",
        "close_px": mark_px,
        "gross_pnl": round(upl, 2),
        "open_fee": round(fee, 4),
        "close_fee": 0.0,
        "fee": round(fee, 2),
        "funding_fee": round(funding_fee, 4),
        "pnl": round(upl, 2),
        "net_pnl": round(upl, 2),
        "roi_pct": roi_pct,
        "duration": duration_str,
        "status": "holding",
        "exit_reason": t_info.get("stage_desc") or ("🎯 半仓保本奔跑中" if t_info.get("scale_out_phase", 0) >= 1 else "⏳ 运行监控中"),
        "scale_out_phase": int(t_info.get("scale_out_phase", 0) or 0),
        "council": council_by_inst.get(inst),
        "signal_snapshot": t_info.get("signal_snapshot"),
    }


from scripts.ledger.okx_history import build_okx_trade
from scripts.ledger.evidence_join import enrich_closed_rows_with_evidence
from scripts.trader.close_evidence import load_close_evidence
from scripts.ledger.merge import merge_lifecycle_trades
from scripts.ledger.notify import notify_newly_closed_trades
from scripts.ledger.holdings import (
    format_holding_duration,
    judge_position_side,
    purge_stale_holding_rows,
)


def build_lifecycle_ledger():
    reset_time = "1970-01-01 00:00:00"
    if os.path.exists(INITIAL_STATE_FILE):
        try:
            with open(INITIAL_STATE_FILE, "r", encoding="utf-8") as f:
                acc = json.load(f)
                reset_time = acc.get("reset_time", "1970-01-01 00:00:00")
        except Exception:
            pass

    existing_closed_ids = set()
    old_trades = []
    if os.path.exists(LEDGER_JSON_FILE):
        try:
            with open(LEDGER_JSON_FILE, "r", encoding="utf-8") as f:
                old_trades = json.load(f)
                existing_closed_ids = {t["id"] for t in old_trades if t.get("status") == "closed"}
        except Exception:
            old_trades = []

    # 重建白名单 = 当前池 ∪ 历史留痕（SQLite/旧台账/持仓追踪），下架币种历史永久保留
    allowed = allowed_inst_ids(old_trades)

    trackers = {}
    if os.path.exists(POSITION_TRACKER_FILE):
        try:
            with open(POSITION_TRACKER_FILE, "r", encoding="utf-8") as f:
                trackers = json.load(f)
        except Exception:
            pass

    # 投委会溯源（2026-09-10）：持仓行的决策来源徽章来自最新 per-symbol 决策缓存。
    # 历史平仓行不伪造该数据——开仓当周期的委员会状态从未持久化，缺失就显示缺失。
    council_by_inst = {}
    try:
        with open(os.path.join(DATA_DIR, "ai_brain_decisions.json"), "r", encoding="utf-8") as f:
            _brain_cache = json.load(f)
        for _k, _v in (_brain_cache or {}).items():
            if not isinstance(_v, dict):
                continue
            _c = _v.get("council")
            if isinstance(_c, dict):
                _name = str(_v.get("name") or str(_k).split("-")[0])
                council_by_inst[_name] = _c
    except Exception:
        council_by_inst = {}

    tz_bj = datetime.timezone(datetime.timedelta(hours=8))

    env = okx_runtime.current_environment()

    if not env.configured:
        raise okx_rest.OKXNotConfigured("OKX API Key 未配置 — 台账同步 fail-closed（既有 trading_ledger.json 保持不动）")

    pos_history = []
    pos_data = []
    close_orders = []
    # 批E：显式记录「活动持仓取数是否成功」——空列表既可能是「确无持仓」也可能是
    # 「取数失败」，二者对清理幽灵持仓的含义完全相反（成功才允许清理）。
    _okx_positions_ok = False

    if env.configured:
        try:
            # 批C(2026-09-13)：分页取尽。原单页 limit=100 即止 —— 平仓越 100 笔后更早记录
            # 永久取不到，且每轮都挂「触顶 limit=100」常驻告警。truncated 仍由分页器诚实给出
            # （取不尽才标），不再用 len>=100 反推。
            pos_history, _ph_trunc = _fetch_history_paged(okx_rest.positions_history, id_field="posId")
            pos_data = okx_rest.positions() or []
            _okx_positions_ok = True
            orders_history, _oh_trunc = _fetch_history_paged(okx_rest.orders_history, id_field="ordId")
            close_orders = [o for o in orders_history if str(o.get('reduceOnly', '')).lower() == 'true' and o.get('state') == 'filled']
            # 截断判定按「在册窗口」收口：取到的最早记录若已早于 reset_time，未取尽的部分
            # 不可能含在册记录 → 不标截断（否则分页上限会让 data_health 永久假 PARTIAL）。
            _ph_old = min((int(r.get("uTime") or 0) for r in pos_history), default=0)
            _oh_old = min((int(r.get("uTime") or r.get("cTime") or 0) for r in orders_history), default=0)
            _okx_trunc = bool(
                _history_truncated_in_scope(_ph_trunc, _ph_old, reset_time, tz_bj)
                or _history_truncated_in_scope(_oh_trunc, _oh_old, reset_time, tz_bj)
            )
            _mark("okx", "partial" if _okx_trunc else "ok",
                  **({"truncated_at": 100} if _okx_trunc else {}))
        except Exception as _okx_err:
            _mark("okx", "failed", reason=str(_okx_err)[:200])
            print(f"[sync_full_ledger] OKX 台账同步跳过: {_okx_err}")

    trades_lifecycle = []

    # Process Active Holding Positions FIRST（批E）
    # 用户报「台账和活动持仓对不上」根因：本 builder 全源 OKX V5，holding 行只由
    # okx_rest.positions() 生成；而旧行靠 id 合并续命，OKX 平掉后那条 holding 行
    # 永不消失（幽灵持仓）。
    _holding_rows = []
    _unmanaged_live = []           # 被准入清单挡掉的活动持仓（不许静默）
    _UNMANAGED_LIVE.clear()
    _queried_venues = set()
    if _okx_positions_ok:
        _queried_venues.add("okx")
    for p in pos_data:
        _row = _holding_row(p, "okx", env=env, trackers=trackers, tz_bj=tz_bj,
                            allowed=allowed, council_by_inst=council_by_inst,
                            unmanaged=_unmanaged_live)
        if _row:
            _holding_rows.append(_row)

    trades_lifecycle.extend(_holding_rows)

    # 不许静默：把被准入清单挡掉的活动持仓同时**写进旁车、打进日志**
    _UNMANAGED_LIVE.extend(_unmanaged_live)
    if _unmanaged_live:
        _nm = unmanaged_positions_payload(_unmanaged_live)
        _desc = ", ".join(f"{i['instId']} {i['size']:g}" if isinstance(i.get("size"), (int, float))
                          else f"{i['instId']}" for i in _nm["items"])
        print(f"⚠️ [sync_full_ledger] {_nm['count']} 个活动持仓不在准入清单，"
              f"**未进台账**（风险界面看不到、可能无人管理）: {_desc}"
              + (f" …另有 {_nm['omitted']} 个" if _nm["omitted"] else ""))
        warnings.warn(
            f"[sync_full_ledger] {_nm['count']} 个活动持仓不在准入清单而未进台账: {_desc}",
            RuntimeWarning)

    # Process Official Closed Positions
    # 审计批7(2026-09-13)·同 posId 多轮往返吞腿修复：PEPE 当日两笔平仓（06:33→10:31
    # +7.89、15:37→16:30 -18.18）在 OKX positions-history 里**共享同一 posId**
    # (391748010248)——旧 `id=pos_hist_{posId}_{inst}` 撞键，合并进 trades_map 时后者
    # 覆盖前者，一条真实亏损从台账蒸发（前台与台账对不上的根因之一）。id 追加开仓
    # 时刻 c_ts + 同键自增序号，保证「每一笔平仓」有唯一稳定身份。
    _pos_id_seen: dict = {}
    for h in pos_history:
        # 去重键所需的两个时间戳在此单独取一次（翻译函数内部会再取，见其文档）。
        # 交叉行状态（_pos_id_seen）属于本循环，不属于单行翻译，故序号在此算出后传入。
        _c_ts = int(h.get("cTime", 0) or 0) / 1000.0
        _u_ts = int(h.get("uTime", 0) or 0) / 1000.0
        _stable_for_key = (str(h.get("posId") or "").strip()
                           or (str(int(_c_ts)) if _c_ts > 0 else str(int(_u_ts))))
        _key = f"{_stable_for_key}|{int(_c_ts)}"
        _seq = _pos_id_seen.get(_key, 0)
        _pos_id_seen[_key] = _seq + 1
        _id_suffix = f"_{int(_c_ts)}" + (f"#{_seq}" if _seq else "")
        _trade = build_okx_trade(
            h=h, reset_time=reset_time, allowed=allowed, close_orders=close_orders,
            env=env, tz_bj=tz_bj, id_suffix=_id_suffix,
            datetime=datetime, get_ct_val=get_ct_val)
        if _trade is None:
            continue
        trades_lifecycle.append(_trade)

    # 聚合去重合并（按 id 去重，按 close_time 降序）
    trades_map = merge_lifecycle_trades(
        old_trades=old_trades,
        trades_lifecycle=trades_lifecycle    )

    _purged_holdings = purge_stale_holding_rows(
        _holding_rows=_holding_rows,
        _queried_venues=_queried_venues,
        trades_map=trades_map    )
    if _purged_holdings:
        print(f"[sync_full_ledger] 清理失效持仓行 {len(_purged_holdings)} 条："
              f"{', '.join(_purged_holdings[:8])}")

    combined_trades = sorted(
        trades_map.values(),
        key=lambda x: str(x.get("close_time") or x.get("time") or x.get("open_time") or ""),
        reverse=True
    )

    # 平仓证据 join（2026-10）：把"开仓快照＋MFE/MAE＋机制级离场原因＋决策来源"
    # 从旁车 `closed_trade_evidence.json` 搬进平仓行，并给每一行打上
    # `exit_reason_source`（`mechanism` = 机制确认 / `inferred` = 交易所侧推断）。
    #
    # ⚠️ 刻意放在**合并/排序后、写盘前**，且**不改 `build_okx_trade`** —— 那个函数被
    # `tests/extraction/test_ledger_okx_history_extraction.py` 以 AST ＋逐行双重钉死，
    # 在里面加字段等于把六个历史判定一起置于风险中。本步是纯派生，去掉即回滚。
    try:
        _evidence_rows = load_close_evidence(CLOSE_EVIDENCE_FILE)
        combined_trades, _evidence_stats = enrich_closed_rows_with_evidence(
            trades=combined_trades, evidence=_evidence_rows)
        if _evidence_stats["closed_rows"]:
            print(f"[sync_full_ledger] 平仓证据 join: {_evidence_stats['matched']}/"
                  f"{_evidence_stats['closed_rows']} 行命中（机制确认 "
                  f"{_evidence_stats['mechanism']}、推断 {_evidence_stats['inferred']}）")
    except Exception as _evidence_exc:
        # fail-soft：证据旁车是**增强**，坏了绝不许阻断台账写盘（与 council 溯源同纪律）
        print(f"[sync_full_ledger] 平仓证据 join 跳过（不影响台账落盘）: {_evidence_exc}")


    fd, tmp_path = tempfile.mkstemp(prefix=".ledger-", suffix=".tmp", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(combined_trades, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, LEDGER_JSON_FILE)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # 审计 A2：台账原子写成功后同步落逐所状态旁车（读侧容错缺文件）。
    _write_sync_status(env)

    notify_newly_closed_trades(
        existing_closed_ids=existing_closed_ids,
        trades_lifecycle=trades_lifecycle    )

    # 批E：trades_lifecycle 现含「OKX 平仓 + OKX 活动持仓」，输出必须分开报。
    _okx_closed_n = sum(1 for t in trades_lifecycle if t.get("status") != "holding")
    print(f"✅ Authentic OKX Ledger: {len(combined_trades)} total trades "
          f"(OKX 平仓: {_okx_closed_n}, 活动持仓: {len(_holding_rows)}).")
    return combined_trades

if __name__ == "__main__":
    try:
        build_lifecycle_ledger()
    except okx_rest.OKXNotConfigured as exc:
        print(f"[NOT READY] {exc}")
        raise SystemExit(3)
