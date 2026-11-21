"""确定性预筛：全标的池 → 「深度分析包 + 落选观察池」（2026-11 上下文漏斗）。

## 为什么需要它

主脑每轮把**全部**标的的七梯队因子矩阵塞进同一条提示词（实测 11 标的、
全标的矩阵约 17,000 字符，占 user prompt 的 59%），模型实际上并没有逐一分析
（历史 50 个周期 300 个槽位里 85 个是「省略」而非裁决）。本模块用**已有的**
`composite_alpha_score` 做确定性排序，只让「在管持仓 + 在途挂单 + 高优先级候选」
进入深度分析，其余标的以紧凑观察池披露 —— 不新增黑盒评分。

## 纪律（改这里之前先读）

- **纯函数**：不读文件、不发网络请求。`ASTRA_BRAIN_CANDIDATE_LIMIT` 在**调用期**
  解析（本仓「配置路径调用期解析」纪律），默认 5，钳制到 `[1, pool_size]`。
- **缺分不落选**：评分缺失/损坏（`None` / `"--"` / NaN / Inf / bool / 字符串）的标的
  并入深度分析并置 `degraded=True`，绝不因缺数据缩小分析范围。
- **未知 ≠ 空**：持仓或挂单读取失败（`positions_known == False` /
  `pending_orders_known == False`）⇒ 全量回退。把「读不到」当成「没有持仓」会直接
  缩小分析范围，等于漏管仓位/挂单。
- **绝不抛**：任何内部异常都回退为全量标的，`prescreen_unavailable=True`，
  `reason=f"prescreen_error:{type(exc).__name__}"`。它在每 15 分钟一轮的主脑循环里，
  抛一次就毁掉整轮决策。
- **不静默消失**：`deep_packages ∪ screened_out` 必须覆盖传入的全部包；没有
  `instId` 的畸形包也并入深度分析（无法排序 ≠ 可以丢）。
"""
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Set

#: 候选数量环境键（`backend/env.example` 有同名说明；调用期读取，不做 import 期快照）
CANDIDATE_LIMIT_ENV = "ASTRA_BRAIN_CANDIDATE_LIMIT"
DEFAULT_CANDIDATE_LIMIT = 5


def _parse_int(raw: Any) -> Optional[int]:
    """宽松解析正整数；缺失/非数字 ⇒ None（由调用方回退默认值）。"""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError, OverflowError):
        return None


def candidate_limit(pool_size: int, raw: Any = None) -> int:
    """本轮进入深度分析的候选数量，钳制到 `[1, pool_size]`。

    `raw is None` ⇒ 调用期读取 `ASTRA_BRAIN_CANDIDATE_LIMIT`（缺省 5）。
    非数字 / 空串 / 0 / 负数一律表现为安全默认或下限，绝不抛。
    空池返回 0（没有名额可分配）。
    """
    if raw is None:
        raw = os.environ.get(CANDIDATE_LIMIT_ENV)
    parsed = _parse_int(raw)
    if parsed is None:
        parsed = DEFAULT_CANDIDATE_LIMIT
    try:
        size = int(pool_size)
    except (TypeError, ValueError, OverflowError):
        size = 0
    if size <= 0:
        return 0
    return max(1, min(parsed, size))


def _inst_id(pkg: Any) -> str:
    """包的标的标识；畸形包返回空串（由调用方并入深度分析，绝不静默丢弃）。"""
    if not isinstance(pkg, dict):
        return ""
    return str(pkg.get("instId") or "")


def _numeric_score(value: Any) -> Optional[float]:
    """只接受**真正的有限数值**：排除 bool / None / 字符串 / NaN / Inf。

    ⚠️ 不得改用 `safe_float(default=0)`：0 是合法评分（`composite_alpha_score`
    本来就是以 0 为中轴的有符号分），把缺分变成 0 会让它参与排序 ——
    既是编造数据，也违背「缺分不落选」。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(score) or math.isinf(score):
        return None
    return score


def _signal_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _meta(*, mode: str, candidate_limit_value: int, pool_size: int, deep_count: int,
          mandatory_count: int, candidate_count: int, screened_out_count: int,
          degraded: bool, missing_score_inst_ids: List[str],
          prescreen_unavailable: bool, reason: str) -> Dict[str, Any]:
    return {
        "mode": mode,
        "candidate_limit": candidate_limit_value,
        "pool_size": pool_size,
        "deep_count": deep_count,
        "mandatory_count": mandatory_count,
        "candidate_count": candidate_count,
        "screened_out_count": screened_out_count,
        "degraded": degraded,
        "missing_score_inst_ids": missing_score_inst_ids,
        "prescreen_unavailable": prescreen_unavailable,
        "reason": reason,
    }


def _full_fallback(packages: List[Any], limit_value: int, reason: str) -> Dict[str, Any]:
    """全量回退：所有包进入深度分析，观察池为空，显式披露原因。"""
    pool_size = len(packages)
    return {
        "deep_packages": list(packages),
        "screened_out": [],
        "meta": _meta(
            mode="full_fallback",
            candidate_limit_value=limit_value,
            pool_size=pool_size,
            deep_count=pool_size,
            mandatory_count=0,
            candidate_count=0,
            screened_out_count=0,
            degraded=False,
            missing_score_inst_ids=[],
            prescreen_unavailable=True,
            reason=reason,
        ),
    }


def _select(packages: Sequence[Any], mandatory_inst_ids: Set[str], *,
            positions_known: bool, pending_orders_known: bool,
            limit: Any) -> Dict[str, Any]:
    pkg_list = list(packages) if packages is not None else []
    pool_size = len(pkg_list)
    limit_value = candidate_limit(pool_size, raw=limit) if limit is not None else candidate_limit(pool_size)

    if pool_size == 0:
        return {
            "deep_packages": [],
            "screened_out": [],
            "meta": _meta(
                mode="funnel",
                candidate_limit_value=limit_value,
                pool_size=0,
                deep_count=0,
                mandatory_count=0,
                candidate_count=0,
                screened_out_count=0,
                degraded=False,
                missing_score_inst_ids=[],
                prescreen_unavailable=False,
                reason="",
            ),
        }

    if not positions_known:
        return _full_fallback(pkg_list, limit_value, "positions_unreadable")
    if not pending_orders_known:
        return _full_fallback(pkg_list, limit_value, "pending_orders_unreadable")

    mandatory_ids = {str(x) for x in (mandatory_inst_ids or set()) if str(x)}
    mandatory_pkgs: List[Any] = []
    unrankable_pkgs: List[Any] = []
    ranked: List[tuple] = []  # (package, score, signal)
    #: 全池是否有**任何**合法评分（含必选标的 —— 必选不靠排序入选，但它的评分
    #: 证明快照可用）。只看 `ranked` 会把「全池都是在管持仓」误判成
    #: `no_rankable_scores` 降级：范围没缩小，却发出假的预筛不可用披露。
    any_rankable_score = False

    for pkg in pkg_list:
        inst_id = _inst_id(pkg)
        if not inst_id:
            # 畸形包（无 instId）：无法排序 ≠ 可以丢 ⇒ 并入深度分析，
            # 也绝不进观察池（观察池按 instId 回查，空 id 只会产生假行）。
            unrankable_pkgs.append(pkg)
            continue
        ranking = pkg.get("factor_ranking") if isinstance(pkg, dict) else None
        ranking = ranking if isinstance(ranking, dict) else {}
        score = _numeric_score(ranking.get("composite_alpha_score"))
        if score is not None:
            any_rankable_score = True
        if inst_id in mandatory_ids:
            mandatory_pkgs.append(pkg)
            continue
        if score is None:
            # D3：缺分/坏分 ⇒ 不参与排序、也不落选，直接并入深度分析。
            unrankable_pkgs.append(pkg)
            continue
        ranked.append((pkg, score, _signal_text(ranking.get("signal_recommendation"))))

    # 全池没有任何可排序评分 ⇒ 预筛不可用，回退全池（绝不缩小范围）。
    # 注意：必选标的有分时不算「不可用」——候选为空但无需降级/回退披露。
    if not ranked and not any_rankable_score:
        return _full_fallback(pkg_list, limit_value, "no_rankable_scores")

    # 确定性排序：评分降序；同分按 instId 字典序（与输入顺序无关）。
    ranked.sort(key=lambda item: (-item[1], _inst_id(item[0])))
    candidates = ranked[:limit_value]

    selected_ids = {_inst_id(pkg) for pkg in mandatory_pkgs}
    selected_ids.update(_inst_id(pkg) for pkg, _score, _signal in candidates)
    selected_ids.update(_inst_id(pkg) for pkg in unrankable_pkgs)
    deep_packages = [pkg for pkg in pkg_list
                     if not _inst_id(pkg) or _inst_id(pkg) in selected_ids]

    screened_out = []
    for rank, (pkg, score, signal) in enumerate(ranked, start=1):
        if rank <= limit_value:
            continue
        inst_id = _inst_id(pkg)
        screened_out.append({
            "instId": inst_id,
            "name": str(pkg.get("name") or inst_id),
            "score": float(score),
            "signal": signal,
            "rank": rank,
            "reason": f"未进入 Top {limit_value} 候选（评分 {float(score)}）",
        })

    missing_score_inst_ids: List[str] = []
    for pkg in unrankable_pkgs:
        inst_id = _inst_id(pkg)
        if inst_id and inst_id not in missing_score_inst_ids:
            missing_score_inst_ids.append(inst_id)

    return {
        "deep_packages": deep_packages,
        "screened_out": screened_out,
        "meta": _meta(
            mode="funnel",
            candidate_limit_value=limit_value,
            pool_size=pool_size,
            deep_count=len(deep_packages),
            mandatory_count=len(mandatory_pkgs),
            candidate_count=len(candidates),
            screened_out_count=len(screened_out),
            degraded=bool(unrankable_pkgs),
            missing_score_inst_ids=missing_score_inst_ids,
            prescreen_unavailable=False,
            reason="",
        ),
    }


def select_deep_analysis_packages(
    packages: Sequence[Dict[str, Any]],
    *,
    mandatory_inst_ids: Optional[Set[str]] = None,
    positions_known: bool = True,
    pending_orders_known: bool = True,
    limit: Any = None,
) -> Dict[str, Any]:
    """确定性预筛：返回 `deep_packages` / `screened_out` / `meta`（契约见 design §2）。

    规则（**顺序敏感**，不得调换）：

    1. 持仓或挂单读取失败 ⇒ 全量回退（`positions_unreadable` / `pending_orders_unreadable`）；
    2. 必选集（在管持仓 ∪ 在途挂单）无条件入选，不占候选名额；
    3. 其余标的取 `factor_ranking.composite_alpha_score`；缺分/坏分**并入深度分析**；
    4. 可排序标的按 `(-score, instId)` 确定性排序；
    5. 候选 = 前 `limit` 个（钳制到 `[1, pool_size]`，缺省读环境变量）；
    6. 全池**没有任何**合法评分（含必选标的的评分）⇒ 全量回退（`no_rankable_scores`）；
    7. 可排序但未进前 `limit` 的 ⇒ `screened_out`（含 rank 与原因）；
    8. 任何内部异常 ⇒ 全量回退（`prescreen_error:*`）。**本函数永不抛**。

    `deep_packages` 保持传入 `packages` 的原始顺序，保证提示词逐轮稳定。
    """
    try:
        # 先**一次性物化**：异常回退时若重新迭代原始入参，生成器已被消费 ⇒
        # 回退集为空 = 静默丢掉全部标的（恰恰是本模块最不能犯的错）。
        pkg_list = list(packages) if packages is not None else []
    except Exception:  # noqa: BLE001 —— 连物化都失败时只能回退空集
        pkg_list = []
    try:
        return _select(
            pkg_list,
            set(mandatory_inst_ids or ()),
            positions_known=positions_known,
            pending_orders_known=pending_orders_known,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 —— 契约就是「绝不抛」
        limit_value = 0
        try:
            limit_value = candidate_limit(len(pkg_list), raw=limit)
        except Exception:  # noqa: BLE001
            pass
        return _full_fallback(pkg_list, limit_value, f"prescreen_error:{type(exc).__name__}")
