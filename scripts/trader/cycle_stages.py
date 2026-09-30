"""execute_portfolio 的阶段函数（B3 抽取·第九十一刀）。

从 `scripts/ai_factor_trader.py::execute_portfolio`（294 行）中
**纯搬家**两段：

| 函数 | 段长 | 原相位 |
|---|---|---|
| `fetch_universe_and_manage_positions` | 14 行 | 相位 2-3：并发取标的池因子 + 逐仓追踪止损退出 |
| `persist_state_and_sync_ledger` | 30 行 | 相位 5-6：面板状态持久化 + 生命周期台账/SQLite 实时同步 |
| `scan_risk_gates_and_ai_brain` | 50 行 | 相位 4 前段：熔断判定 + 单标的保证金上限自适应 + 主脑批量扫描（LLM 批次 + 持仓全景装配 + AI 健康告警）+ 池可信闸（**无 return；4 项输出**） |
| `fetch_positions_and_reconcile` | 相位 1：取真实持仓 + 挂单盲区守卫 + 预留对账（**4 处 `return None` = 本周期中止**；11 项输出） |
| `preflight_reconcile_and_housekeeping` | 26 行 | 相位 0/0a：引擎就绪闸 + 挂单对账 + 陈旧单回收 + 舆情采集（**段内 `return None` = 本周期中止**） |

## 准入判据（沿用第九十刀定式）

两段均 **0 个 `return`、0 个 `break`**；段内写入的外围量要么作为返回值回传，
要么无人再读（`persist_state_and_sync_ledger` 无输出 ⇒ 纯副作用段）。
所有自由名（外围局部量 + 门面全局）一律**同名 kw-only 入参** ⇒ 段体 **AST 逐字**。

⚠️ **OKX 专用化**：跨所汇总（外所持仓快照 / 外所挂单枚举 / 外所凭证坏所探测 /
外所仓位接管 `venue_position_record`）与跨所保护巡检
（`venue_protection_watchdog_stage` + 防抖状态读写）已随多所执行面整体移除。
本系统只在 OKX 上持仓；历史/外所行一律**只读容错**（不接管、不清算、不进配额）。
"""
from __future__ import annotations


def fetch_universe_and_manage_positions(*,
        all_positions,
        real_pos_dict,
        timestamp_full,
        usdt_available,
        TARGET_INSTRUMENTS,
        ThreadPoolExecutor,
        fetch_single_instrument_data,
        load_trackers,
        manage_position_tp_and_trailing,
        prune_trackers,
        save_trackers):
    with ThreadPoolExecutor(max_workers=len(TARGET_INSTRUMENTS)) as executor:
        all_factors = list(executor.map(lambda item: fetch_single_instrument_data(item, all_positions, usdt_available), TARGET_INSTRUMENTS))

    # 3. Process Positions & Dynamic Trailing Exits
    executed_actions = []
    trackers = load_trackers()
    stale_tracker_count = prune_trackers(trackers, real_pos_dict)
    if stale_tracker_count:
        executed_actions.append(f"清理 {stale_tracker_count} 条已失效持仓追踪记录")
    for f in all_factors:
        curr_pos = f["position"]
        if curr_pos:
            manage_position_tp_and_trailing(f, curr_pos, trackers, timestamp_full, executed_actions)
    save_trackers(trackers)
    # ⚠️ 不返回 `f`：原文段后对 `f` 的那次读（`f.write(log_entry)`）是
    # `with open(LOG_FILE) as f` **自己绑定的文件句柄**，与标的字典无关
    # （首版误判为外围输出，冒烟例当场抓出 UnboundLocalError）。
    return (all_factors, executed_actions, trackers)


def persist_state_and_sync_ledger(*,
        venue_position_span,
        active_pos_count,
        all_factors,
        cb_active,
        cb_reason,
        executed_actions,
        long_count,
        short_count,
        timestamp_full,
        DATA_DIR,
        LEDGER_AUTOSYNC_ENABLED,
        LOG_FILE,
        MAX_CONCURRENT_POSITIONS,
        WORKSPACE_DIR,
        __version__,
        _atomic_write_json,
        _run_captured,
        build_state_payload,
        evaluate_asset_signal,
        os):
    state_payload = build_state_payload(
        timestamp_full=timestamp_full, active_pos_count=active_pos_count,
        max_positions=MAX_CONCURRENT_POSITIONS, long_count=long_count,
        short_count=short_count, cb_active=cb_active, cb_reason=cb_reason,
        executed_actions=executed_actions, all_factors=all_factors,
        evaluate_asset_signal=evaluate_asset_signal)

    # 审计③：原子替换（读者=面板/巡检；旧直写有撕裂窗）。异常语义不变：照旧上抛。
    _atomic_write_json(os.path.join(DATA_DIR, "trading_state.json"), state_payload)

    # 6. Always Sync Full Lifecycle Ledger and SQLite DB in Realtime
    # 批E(2026-09-13)·测试封闭闸：这两条 spawn 会重写生产台账/数据库。
    # 测试若在进程内跑一轮交易员巡检（多处如此），就会连带改写 data/trading_ledger.json
    # 与 SQLite——违反「测试不触生产文件」。tests/__init__.py 在任何测试模块导入前置位
    # ASTRA_LEDGER_SYNC_DISABLED=1，下面的模块级快照即 False；生产不设 → 行为不变。
    if LEDGER_AUTOSYNC_ENABLED:
        try:
            sync_script = os.path.join(WORKSPACE_DIR, "scripts", "sync_full_ledger.py")
            if os.path.exists(sync_script):
                _run_captured(sync_script)
            db_script = os.path.join(WORKSPACE_DIR, "scripts", "db_manager.py")
            if os.path.exists(db_script):
                _run_captured(db_script)
        except Exception as e:
            print(f"[Ledger Sync Warning] {e}")

    position_span = venue_position_span(okx_count=active_pos_count, okx_long=long_count,
                                        okx_short=short_count,
                                        max_positions=MAX_CONCURRENT_POSITIONS)
    log_entry = f"[{timestamp_full}] ⚡ AstraQuant v{__version__} 巡检完成 | {position_span} | 动作: {', '.join(executed_actions) if executed_actions else '无开平仓操作'}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)
    print(log_entry.strip())


def preflight_reconcile_and_housekeeping(*,
        WORKSPACE_DIR,
        _run_captured,
        clean_stale_open_orders,
        current_environment,
        datetime,
        load_trackers,
        os,
        reconcile_pending_orders):
    """相位 0/0a：引擎就绪闸 + 挂单对账 + 陈旧单回收 + 舆情采集。

    段内 `return None` 语义 = **本周期中止** ⇒ 调用点据此提前 `return None`。
    """
    _engine_env = current_environment()
    if not _engine_env.configured:
        print(f"[Engine NOT READY] OKX {_engine_env.mode.upper()} API Key 未配置：V5 直签是唯一交易通道，本周期拒绝交易。")
        return None
    tz_bj = datetime.timezone(datetime.timedelta(hours=8))
    now_dt = datetime.datetime.now(tz_bj)
    timestamp_full = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 0a. US-006 周期级挂单对账：重启/新周期接管或撤销存量挂单（在新增下单之前）
    reconcile_ok, reconciled_kept_ord_ids = reconcile_pending_orders(trackers=load_trackers())
    if not reconcile_ok:
        # fail-closed：仅禁止本周期新增下单（不是清库），持仓管理照常执行
        print("[挂单对账] fail-closed：本周期禁止新增下单（对账失败，不清库）")
    entries_blocked = not reconcile_ok

    # 0. Clean Stale Open Orders & Harvest Real-time News Sentiment
    orders_ok, orders_error = clean_stale_open_orders(keep_ord_ids=reconciled_kept_ord_ids)
    if not orders_ok:
        print(f"[Trader] Abort: unable to verify/cancel stale open orders: {orders_error}")
        return None
    try:
        harvester_script = os.path.join(WORKSPACE_DIR, "scripts", "news_sentiment_harvester.py")
        if os.path.exists(harvester_script):
            _run_captured(harvester_script, label="news_harvester", timeout=25)
    except Exception as e:
        print(f"News Harvester sync warning: {e}")
    return (entries_blocked, timestamp_full)


def fetch_positions_and_reconcile(*,
        entries_blocked,
        current_environment,
        okx_rest,
        query_positions,
        reconcile_reservation_ledger):
    """相位 1：取真实持仓 + 挂单盲区统计 + 预留对账。

    段内 4 处 `return None` 语义 = **本周期中止**（调用点判 None 后 `return None`）。
    `entries_blocked` 是 **in-out**：原实现只在"跨所读取失败"分支里被置 True，
    该分支已随多所执行面移除 ⇒ 本段现在原样透传上游（preflight）的值。
    其余输出在本段内均"必然绑定"（确定赋值分析），无需入参。

    ⚠️ **输入失败语义表**（改动前先读）：

    | 输入 | 读失败时的行为 | 决策方是否被告知 |
    |---|---|---|
    | OKX 持仓 `query_positions` | **整周期 abort**（`return None`） | 日志 |
    | OKX 挂单 `pending_orders` | **整周期 abort** | 日志 |
    | OKX 余额 `balances` | **整周期 abort** | 日志 |
    | 清理存量挂单 `clean_stale_open_orders` | **整周期 abort** | 日志 |
    | OKX 挂单对账（preflight `reconcile_pending_orders`） | `entries_blocked=True`（禁新开仓） | 日志 |

    ⚠️ **OKX 专用化**：跨所持仓快照 / 外所挂单枚举 / 外所凭证坏所探测 / 外所仓位
    接管（`venue_position_record`）已随多所执行面整体移除——本系统只在 OKX 上持仓，
    历史外所行只做**只读容错**（不接管、不清算），绝不进配额与敞口。
    """
    positions_ok, all_positions, positions_error = query_positions()
    if not positions_ok:
        print(f"[Trader] Abort: unable to verify exchange positions: {positions_error}")
        return None
    real_pos_dict = {}
    real_long_count = 0
    real_short_count = 0

    if isinstance(all_positions, list):
        for p in all_positions:
            pos_sz = float(p.get("pos", 0) or 0)
            if pos_sz > 0:
                side = p.get("posSide", "net").lower()
                inst_id = p.get("instId")
                if inst_id in real_pos_dict:
                    print(f"[Trader] Abort: simultaneous long/short positions for {inst_id} are not supported")
                    return None
                real_pos_dict[inst_id] = p
                if "long" in side:
                    real_long_count += 1
                elif "short" in side:
                    real_short_count += 1

    active_pos_count = len(real_pos_dict)
    long_count = real_long_count
    short_count = real_short_count

    try:
        pending_orders = okx_rest.pending_orders()
    except Exception as pending_exc:
        print(f"[Trader] Abort: unable to verify pending orders: {pending_exc}")
        return None
    pending_inst_ids = set()
    pending_long_count = 0
    pending_short_count = 0
    if isinstance(pending_orders, list):
        for order in pending_orders:
            if str(order.get("state", "live")).lower() not in {"live", "partially_filled"}:
                continue
            inst_id = str(order.get("instId", ""))
            if inst_id:
                pending_inst_ids.add(inst_id)
            pos_side = str(order.get("posSide", "")).lower()
            if pos_side == "long":
                pending_long_count += 1
            elif pos_side == "short":
                pending_short_count += 1
    try:
        _env_mode = str(current_environment().mode or "")
    except Exception as _env_exc:
        _env_mode = ""
        print(f"[周期环境] warn 周期冻结环境不可得（{_env_exc}），按不可信环境处理")
    reserved_slot_count = active_pos_count + len(pending_inst_ids)
    reserved_long_count = long_count + pending_long_count
    reserved_short_count = short_count + pending_short_count

    # 1b. US-010 预留对账：基于本周期刚核验的持仓/挂单实况回笼陈旧占用
    #     （活仓/在途挂单一律保留；无仓无挂且超 TTL 才 closed——宁慢不错杀）。
    #     跨所实况旗标不再需要：系统只有一个场所，上面两个枚举就是全量。
    try:
        reconcile_reservation_ledger(real_pos_dict, pending_inst_ids, _env_mode)
    except Exception as _rc_exc:
        print(f"[预留对账] warn 对账器异常（不影响本周期交易）: {_rc_exc}")

    try:
        bal_res = okx_rest.balances()
    except Exception as bal_exc:
        print(f"[Trader] Abort: unable to verify account balance: {bal_exc}")
        return None
    usdt_available = 0.0
    if bal_res:
        for d in bal_res[0].get("details", []):
            if d.get("ccy") == "USDT":
                usdt_available = float(d.get("availBal", 0.0))
                break
    return (active_pos_count, all_positions, entries_blocked, long_count, pending_inst_ids, real_pos_dict, reserved_long_count, reserved_short_count, reserved_slot_count, short_count, usdt_available)


def scan_risk_gates_and_ai_brain(*,
        venue_position_span,
        active_pos_count,
        all_factors,
        executed_actions,
        long_count,
        short_count,
        timestamp_full,
        trackers,
        usdt_available,
        MAX_CONCURRENT_POSITIONS,
        _collect_okx_position_payloads,
        effective_single_asset_margin,
        execute_ai_position_management,
        execute_batch_ai_brain_cycle,
        is_circuit_breaker_active,
        pool_is_trustworthy,
        pool_state,
        query_positions,
        read_cycle_health,
        real_pos_dict,
        save_trackers,
        session_restricted=False):
    """相位 4 前段：熔断判定 + 单标的保证金上限自适应 + 主脑批量扫描 + 池可信闸。

    段内不动控制流（无 return/break）：`executed_actions` 由**原地 append** 回传
    （故只入参、不返回）；`brain_cache` 在段内顶层初始化为 `{}` ⇒ 必然绑定。
    4 项输出见调用点解包。

    ⚠️ `session_restricted`（2026-09-30 交易时段闸门）：为真时**不叫大模型** ——
    交易主脑实测占全系统模型消耗的 94%（≈4.2M token/天），窗口外让它继续跑
    就是纯烧钱。**默认 False** 是刻意的：既有调用点（含各测试的 `_scan_kwargs`）
    不传它时必须与改造前逐位一致。抑制发生在**本段内部**而不是门面传 `None`：
    门面调用点受 `test_facade_calls_pass_every_parameter_once_same_name` 约束
    （每个关键字必须与参数同名、且顺序一致），传三元表达式会当场翻红。
    """
    cb_active, cb_reason = is_circuit_breaker_active(usdt_available)
    # 单标的累计保证金上限按可用余额自适应，与提示词 {{risk_budget}} 同口径
    ASSET_MARGIN_CAP = effective_single_asset_margin(usdt_available)

    brain_cache = {}
    # One LLM call covers the full six-instrument universe and all active positions.
    if not cb_active and execute_batch_ai_brain_cycle and not session_restricted:
        try:
            pos_desc = "当前系统总" + venue_position_span(
                okx_count=active_pos_count, okx_long=long_count, okx_short=short_count,
                max_positions=MAX_CONCURRENT_POSITIONS)
            # 持仓全景装配（阶段 4·B3 第三十一刀：迁至 scripts/trader/position_universe.py）
            active_pos_list = _collect_okx_position_payloads(all_factors, trackers)
            brain_cache = execute_batch_ai_brain_cycle(pos_desc, active_pos_list, usdt_available=usdt_available) or {}
            if brain_cache:
                refreshed_ok, refreshed_positions, refreshed_error = query_positions()
                if not refreshed_ok:
                    executed_actions.append(f"AI持仓管理跳过：无法刷新真实仓位 ({refreshed_error})")
                else:
                    refreshed_pos_dict = {
                        p.get("instId"): p for p in refreshed_positions
                        if float(p.get("pos", 0) or 0) > 0
                    }
                    # 刷新的是 OKX 直签链的权威持仓（`query_positions` 只读 OKX）；
                    # OKX 专用化后它就是全部持仓，无需再并回任何外所记录。
                    execute_ai_position_management(refreshed_pos_dict, trackers, timestamp_full, executed_actions)
                    save_trackers(trackers)
            else:
                _hf = read_cycle_health() if read_cycle_health else {}
                if _hf.get("last_status") == "failed":
                    _cf = int(_hf.get("consecutive_failures", 0) or 0)
                    _warn = f"本轮AI推理失败（连续{_cf}轮｜{_hf.get('last_error') or '未知原因'}），禁止复用旧持仓指令"
                    if _cf >= 3:
                        _warn = "🔴 AI决策链连续" + str(_cf) + "轮失败——非并发跳过，模型/密钥/额度需人工核查！" + _warn
                    executed_actions.append(_warn)
                    if _cf >= 3:
                        print(f"[AI Health] 🔴 连续 {_cf} 轮批次决策失败，最近错误: {_hf.get('last_error')}")
                else:
                    executed_actions.append("本轮AI推理并发跳过（旧指令不违规复用），禁止复用旧持仓指令")
        except Exception as e:
            print(f"[AI Brain Batch Scan Warning] {e}")
    elif not cb_active and session_restricted:
        # 窗口外：必须留下**一条可检索**的动作行，否则"这一轮为什么什么都没做"在日志里无从解释
        executed_actions.append("🕒 非交易时段：跳过 AI 大模型决策与新开仓（机械风控照常）")

    # 审计 P2-11：标的池不可信（文件损坏/为空/条目非法）时，旧实现会拿 10 币出厂默认
    # 清单继续开新仓 —— 管理员删掉的标的会因"文件坏了"重新被交易。这里 fail-closed：
    # 只保留持仓风控接管（止损/移动止损/AI 平仓在上面的分支已跑完），不开新仓。
    if not cb_active and not pool_is_trustworthy():
        _ps = pool_state()
        _pool_warn = (f"⛔ 标的池不可信（{_ps.get('status')}: {_ps.get('detail')}）"
                      f"——本轮只做持仓风控接管，禁止开新仓")
        print(f"[交易池闸门] {_pool_warn}")
        executed_actions.append(_pool_warn)
    return (ASSET_MARGIN_CAP, brain_cache, cb_active, cb_reason)


def data_shape_preflight_stage(*, intents_path, trackers_path,
                               validate_intents_file, validate_trackers_file) -> list:
    """周期开跑前的**只读形状预检**（第 49 刀）：把"静默忽略"变成"指名道姓"。

    与加载侧的分工（刻意如此）：

    | 侧 | 负责 |
    |---|---|
    | 加载侧（`load_open_intents` / `load_trackers`）| **行为**：读不出来 ⇒ fail-closed / 拒绝覆盖 |
    | 本阶段 | **可见性**：读得到但形状不合规 ⇒ 打印并指出下游后果 |

    ⚠️ 本阶段**只警告、不阻断、不写盘**。它要抓的典型是那些"读得到却会被静默忽略"的
    形状问题 —— 例如追踪器键名拼写不合约定（`BTC_USDT_long`）会让水位查找落空、
    状态静默丢失，而不触发任何异常。

    返回违规行列表（调用方只用于展示/测试；不做控制流判定）。
    """
    violations = []
    for label, path, checker in (("意图", intents_path, validate_intents_file),
                                 ("追踪器", trackers_path, validate_trackers_file)):
        for line in checker(path):
            violations.append(f"[数据形状预检] {label}: {line}")
    for line in violations:
        print(line)
    if not violations:
        print("[数据形状预检] 意图/追踪器形状合规")
    return violations

def cycle_disclosure_payload(*, broken_venues=(), entries_blocked=False,
                            shape_violations=(), session=None) -> dict:
    """周期披露的**结构化**载荷（第 51 刀）：供"渲染一条行"与"落盘成指标"共用。

    单一事实源：`cycle_disclosure_summary` 只负责把它渲染成一行；
    `write_cycle_disclosure_snapshot` 只负责把它原子落盘给后端 `/metrics` 读。
    两处都不再各自解释"什么算跳过" —— 这正是本仓反复吃过的"同一语义两处写"。

    ⚠️ 绝不抛异常（`None` 集合、含 `None` 的列表一律宽容）：报告器不得成为新的
    单点故障。跨所保护巡检（roadmap G8）已随多所执行面移除 ⇒ `watchdog_*` 三个
    字段一并删除（`/metrics` 侧用 `.get`，读不到即不发对应计数）。

    ⚠️ `session`（2026-09-30 交易时段闸门）：为 `None` 或 `mode == "full"` 时
    载荷与 `clean` **逐键不变**（既有测试 `test_clean_cycle` 钉住整行文案）；
    只有在窗口外降级时才追加 `session_*` 三个键并把 `clean` 置 False ——
    "没开闸/降级跑"不是错误，但**必须被看见**（与 `entries_blocked` 同一哲学）。
    """
    # ⚠️ `str(None)` 是 `"None"`（真值！）—— 旧写法会把列表里的 `None` 渲染成
    # "一所名叫 None 的坏所"，披露行里就多出一条假场所（"UI 不说谎"的反面）。
    # 空串/纯空白同理：不是场所名，不该进披露。
    venues = sorted({str(v).strip() for v in (broken_venues or [])
                     if v is not None and str(v).strip()})
    bad = [str(b) for b in (shape_violations or [])]
    restricted = bool(isinstance(session, dict) and session.get("restricted"))
    payload = {
        "broken_venues": venues,
        "broken_venue_count": len(venues),
        "entries_blocked": bool(entries_blocked),
        "shape_violation_count": len(bad),
        "shape_violation_head": bad[:3],
        "clean": not (venues or entries_blocked or bad or restricted),
    }
    if restricted:
        payload["session_mode"] = str(session.get("mode") or "")
        payload["session_reason"] = str(session.get("reason") or "")
        payload["session_restricted"] = True
    return payload


def cycle_disclosure_summary(payload: dict) -> str:
    """把披露载荷渲染成**一条可检索**的行（渲染器；判定/落盘见 payload 与快照写入）。

        [周期披露] 本轮无跳过/未核验项
        [周期披露] 本轮跳过/未核验：凭证坏所=2(...); 对账失败（禁本轮新开仓）

    判据很朴素但有效：**这条行必须每轮都出现**（门禁钉调用点）⇒ 有人删掉某处披露时，
    汇总行里的数字会随之变化，评审看日志就能发现"怎么不报了"。
    """
    payload = payload if isinstance(payload, dict) else {}
    parts = []
    n_ven = int(payload.get("broken_venue_count") or 0)
    if n_ven:
        parts.append(f"凭证坏所={n_ven}({','.join(payload.get('broken_venues') or [])})")
    if payload.get("entries_blocked"):
        parts.append("对账失败（禁本轮新开仓）")
    if payload.get("session_restricted"):
        # 2026-09-30：休市降级必须出现在**这一行**里 —— 它每轮都打印、也可检索，
        # 是"这一轮为什么什么都没做"的唯一常驻线索。
        mode = str(payload.get("session_mode") or "")
        parts.append("时段限制=" + ("完全停跑" if mode == "off" else "只做机械风控"))
    n_bad = int(payload.get("shape_violation_count") or 0)
    if n_bad:
        head = "; ".join(payload.get("shape_violation_head") or [])
        more = f" …共{n_bad}条" if n_bad > 3 else ""
        parts.append(f"数据形状违规={n_bad}（{head}{more}）")
    return ("[周期披露] 本轮跳过/未核验：" + "; ".join(parts)) if parts \
        else "[周期披露] 本轮无跳过/未核验项"


def write_cycle_disclosure_snapshot(*, path, payload, _atomic_write_json) -> bool:
    """把披露载荷**原子**落盘给后端 `/metrics` 跨进程读取（第 51 刀）。

    与行情取数健康快照同一路数（worker 写、后端读）；`written_at_ms` 用于算新鲜度，
    让"很久没更新"与"本轮很干净"在指标上可区分（读不到 ≠ 没有）。
    失败只返回 False（绝不抛、绝不改变交易行为）。
    """
    import time as _time
    body = dict(payload or {})
    body["written_at_ms"] = int(_time.time() * 1000)
    try:
        _atomic_write_json(path, body)
        return True
    except Exception as exc:      # noqa: BLE001 - 可观测性失败绝不拖垮周期
        print(f"[周期披露] warn 快照写入失败（不影响交易）: {exc!r}")
        return False
