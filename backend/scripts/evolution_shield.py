#!/usr/bin/env python3
"""
ASTRA Evolution Shield & Anti-Poisoning Cognitive Guardian (evolution_shield.py)
-------------------------------------------------------------------------------
Ensures AI Self-Evolution DOES NOT become a double-edged sword:
1. Anti-Single-Event Bias / Outlier Rejection:
   Single flash-crash or anomalous spikes cannot dictate long-term strategy.
2. Constitution Red-Lines (Non-negotiable Rules):
   - Prohibits "Never go Long" or "Never go Short" biases.
   - Prohibits widening stop losses to bag-hold losses.
   - Prohibits aggressive revenge betting or Martingale sizing.
3. Structured White-Box Lesson Schema:
   - id, category, rule_text, health_score, enabled, created_at, ttl_days, sample_size
4. Cognitive Decay & Health Score:
   - Lessons lose health score if they contradict recent positive performance.
   - Decayed lessons auto-archive, preventing cognitive poisoning.
   ⚠️ 2026-10 如实修正：上面两条**长期只是文档里的承诺**（`health_score` 只在
   建档时写死 90.0、从未重算，注入排序也不读它）。现已真正落地，实现在
   `scripts/evolution/lesson_health.py`：用平仓证据析出心法的适用人群（标的/方向/
   离场机制）→ 按该人群胜率与期望值打分（按样本量向 50 回归）→ 低于
   `ARCHIVE_HEALTH_THRESHOLD` 且样本达标且**非基准**才归档（`enabled=False` 留痕，
   **绝不删除**、绝不触碰基准心法）。
"""

from __future__ import annotations

import datetime
import json
import math
import re
import copy
import fcntl
import hashlib
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.evolution.lesson_health import (
    ARCHIVE_HEALTH_THRESHOLD,
    MIN_HEALTH_SAMPLE,
    rank_lessons,
    refresh_lesson_health,
)

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE_DIR / "data"
STRUCTURED_MEMORY_FILE = DATA_DIR / "structured_trading_memory.json"
AI_MEMORY_MD_FILE = DATA_DIR / "AI_TRADING_MEMORY.md"

# ⚠️ 这里**曾经**是 4 条硬编码的"基准黄金心法"（顺势回踩 / 宽止损抗噪 /
# 浮盈0.8R保本 / 禁止同向共振堆叠）。用户 2026-10 明确要求：**系统不再预设任何心法**，
# 故常量与其配套的整套"基准机制"（`is_baseline` 字段、宪法级保护、遗漏即补回、
# 永不过期、注入优先、`rollback_to_baseline`）已**整体拆除**。
#
# 现在起点的定义就是**空集**（`reset_all_lessons()` 直接提交 `[]`）。
# **不要**在此处或任何地方重新引入预设心法清单 ——
# `tests/llm/test_evolution_shield_gates.py::NoPresetDoctrineTests` 会在有人这么做时立刻翻红。
# 需要长期生效的规则只有两条正道：自进化从真实平仓证据中学出来，或管理员手工录入。

# 宪法红线规则（任何大模型总结出的心法如果触碰以下词汇或逻辑，直接物理阻断）：
#: (正则, 拒绝原因, 禁止式豁免)。第三列为 True 时，"严禁放宽止损"这类**禁止式**表述
#: 属安全知识而非风险扩张；方向偏见两条不豁免——"永远不做多"本身就是毒（毁掉多空对称）。
POISON_PATTERNS = [
    (r"(永远不|绝对不|严禁|彻底禁止).*(做多|开多|买入)", "EXTREME_DIRECTIONAL_BIAS (极端做多偏见阻断)", False),
    (r"(永远不|绝对不|严禁|彻底禁止).*(做空|开空|卖出)", "EXTREME_DIRECTIONAL_BIAS (极端做空偏见阻断)", False),
    (r"(扩大|放宽|取消|不设|移除|关闭|删除).*(止损|SL)", "RISK_EXPANSION_VIOLATION (违规抗单放大止损)", True),
    (r"(加倍|翻倍|加仓|重仓|梭哈).*(亏损|抗单|摊平)", "MARTINGALE_POISONING (马丁格尔赌徒加仓倾向)", True),
    (r"(忽视|不看|废弃|无视|忽略|跳过|绕过|关闭|禁用|停用|移除|删除|突破).*(4H|宏观|ATR|风控|拦截器|熔断|门禁|刹车)",
     "GOVERNANCE_OVERRIDE (企图推翻硬风控拦截器)", True),
    # 审计 P1-8(2026-09-13)：子审计实跑证明旧规则对下面三类**全部 PASS**——
    #   「把单笔杠杆从 5x 提升至 20x」「把单标的累计保证金上限提高到 50%」
    #   「关闭风控拦截器以绕过 4H 方向否决」（第三类旧词表只认 忽视/不看/废弃）。
    # 这三条一旦写进记忆就会被注入主脑提示词，等于让模型自己拆掉硬风控。
    (r"(提高|提升|放大|增加|调高|拉高|加大|上调|放宽|解除).*(杠杆|leverage)",
     "RISK_EXPANSION_VIOLATION (抬升杠杆上限)", True),
    (r"(杠杆|leverage)[^。；;\n]{0,24}(提高|提升|放大|增加|调高|拉高|加大|上调|放宽|解除)",
     "RISK_EXPANSION_VIOLATION (抬升杠杆上限)", True),
    (r"(提高|提升|放大|增加|调高|拉高|加大|上调|放宽|解除|取消).*(保证金|仓位上限|持仓上限|风险预算|敞口|单笔上限|风险额度)",
     "RISK_BUDGET_EXPANSION (放宽保证金/持仓/预算上限)", True),
    (r"(保证金|仓位|持仓|风险预算|敞口|单笔)[^。；;\n]{0,24}(提高|提升|放大|增加|调高|拉高|加大|上调|放宽|解除)",
     "RISK_BUDGET_EXPANSION (放宽保证金/持仓/预算上限)", True),
    (r"(降低|下调|放宽|取消|豁免).*(置信度|门槛|阈值|标准|审查|复核|风控参数)",
     "RISK_THRESHOLD_LOWERING (下调风控阈值/审查标准)", True),
    (r"(满仓|全仓|梭哈|all[ -]?in)", "OVER_CONCENTRATION (单次满仓/全仓倾向)", True),
]

#: 变更类动词 × 风险名词的共现兜底（同句内出现即拒）：覆盖词表未枚举的改写变体。
_RISK_CHANGE_VERBS = r"(提高|提升|放大|增加|调高|拉高|加大|上调|放宽|解除|取消|关闭|禁用|停用|移除|删除|跳过|绕过|突破|降低|下调|豁免)"
_RISK_NOUNS = r"(杠杆|leverage|保证金|仓位|持仓上限|风险预算|敞口|止损|风控|熔断|拦截器|置信度|门槛|阈值|硬约束)"
#: 同句含这些"禁止类"词 = 在**禁止**风险扩张（合法），豁免共现兜底。
_RISK_PROHIBITIONS = r"(严禁|禁止|不得|绝不|杜绝|防止|防范|严禁将|不允许|拒绝)"


def _strip_prohibition_clauses(sentence: str) -> str:
    """剔除"禁止类"子句，保留其余文本（"严禁逆势加仓，但可放宽止损" → "但可放宽止损"）。"""
    clauses = [c for c in re.split(r"[，,]", sentence or "") if c.strip()]
    kept = [c for c in clauses if not re.search(_RISK_PROHIBITIONS, c)]
    return "，".join(kept)


#: 与**当前因子契约**已经脱钩的退役词汇（2026-10 新增门禁）。
#:
#: 背景：因子范式从「数理微积分动力学」整块迁移到 7 梯队（T0/T0.5/T1/T1.5/T2/T3/T4），
#: `velocity`／`power_regime`／`continuation_prob_pct`／`RANGE_LOW_VELOCITY`／
#: `KINETIC_*`／`energy_integral` 等**已不存在于任何标的的数据包**。而心法是要被注入
#: 提示词的："数据缺失纪律"又明令 `--` 不得作为证据 ⇒ 引用死因子的否决律**既无法评估、
#: 又恒以最保守方式生效**，实测直接把系统压成"只会 WAIT"（两条存量心法已由人工复核退役）。
#: 故此后**拒绝写入**引用下列词汇的新心法；存量不自动清洗（避免误伤语义仍成立的历史心法）。
RETIRED_FACTOR_TOKENS = (
    "velocity", "power_regime", "continuation_prob_pct", "RANGE_LOW_VELOCITY",
    "KINETIC_ACCELERATING", "KINETIC_EXHAUSTION", "KINETIC_DECELERATING",
    "KINETIC_REVERSAL", "STEADY_FLUX", "energy_integral", "deviation_area_integral",
    "calculus_dynamics", "math_prob_rationale", "阻力高空",
    # ── 2026-10：**中文散文形态**（补门禁漏洞）──────────────────────────────
    # 实测漏洞：存量心法 `lesson_80fab4e2…`
    #   「若 1H RSI > 72 严重超买且 1H **动能加速度 a** 明显转负…**条件延续概率**偏高」
    # 整句引用的是**已退役的动力学/概率链**（`velocity` / `energy_integral` /
    # `continuation_prob_pct`），但上一版词表**只有英文标识符** ⇒ `_retired_factor_hits`
    # 返回 `[]`、`audit_proposed_lesson` 判 `PASSED`。而这些因子在真实快照里恒为
    # `--`（数据缺失纪律又明令 `--` 不得作为证据）⇒ 这条心法落地即变成**恒真的否决律**，
    # 正是本门禁要拦的那类"不可评估"心法。
    #
    # ⚠️ 选词纪律：只收**指向具体退役因子**的复合词，不收"力竭/超买"这类**语义仍成立**
    # 的通用交易词（那会误伤本来可用的心法，比漏洞本身更糟）。故"力竭"必须写成
    # "动力学力竭"/"动能衰竭"级别的复合词才拦。
    "动能加速度", "加速度 a", "加速度a", "动力学位移", "动力学质量", "动力学力竭",
    "速度场", "加加速度", "曲率", "能量积分", "偏差面积积分", "体积作用积分",
    "条件延续概率", "延续概率", "破裂概率", "概率状态占比",
    "var_95_pct", "cvar_95_pct", "is_fat_tail", "prob_regime", "prob_score",
)
#: 上表里这些是**通用英文词**（可能出现在正常表述里），只在"像因子名"的上下文才拦。
_RETIRED_FACTOR_LOOSE = ("velocity",)


def _retired_factor_hits(rule_text: str) -> list:
    """返回心法文本里引用的**退役因子**词汇（大小写不敏感的整词匹配）。"""
    hits = []
    for token in RETIRED_FACTOR_TOKENS:
        if token in _RETIRED_FACTOR_LOOSE:
            # 通用词：要求两侧不是字母，避免命中 "velocities" 之类以外的噪音；
            # 但仍必须是独立词（"velocity > 0.8" / "velocity快照" 都算）。
            pattern = rf"(?<![A-Za-z_]){re.escape(token)}(?![A-Za-z])"
        else:
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
        if re.search(pattern, rule_text or "", re.IGNORECASE):
            hits.append(token)
    return hits


def audit_proposed_lesson(rule_text: str, sample_size: int = 1) -> Tuple[bool, str]:
    """
    Applies the Constitution Linter to verify whether a proposed lesson is safe.
    Returns (is_passed, reason).
    """
    if not rule_text or len(rule_text.strip()) < 10:
        return False, "心法文本过短，缺乏明确可复用的交易情境依据"

    # 0. 因子契约对齐（2026-10）：引用已退役因子的心法一律拒收。
    #    为什么放在宪法红线**之前**：这类心法的问题不是"坏"而是"不可评估"——
    #    它会把提示词的《数据缺失纪律》变成一串恒真的否决律，压制全部开仓。
    _dead = _retired_factor_hits(rule_text)
    if _dead:
        return False, ("触发因子契约门禁: FACTOR_CONTRACT_DRIFT "
                       f"(引用了已退役因子 {_dead}，当前 7 梯队契约中不存在；"
                       "请改用 T0/T0.5/T1/T1.5/T2/T3/T4 的现行因子重写)")

    # 1. 宪法红线：逐句判定（跨句不误伤），禁止式子句按需剥离后再匹配。
    for sentence in re.split(r"[。；;\n]", rule_text):
        if not sentence.strip():
            continue
        exempt_text = _strip_prohibition_clauses(sentence)
        for pattern, reason, prohibitive_exempt in POISON_PATTERNS:
            target = exempt_text if prohibitive_exempt else sentence
            if target and re.search(pattern, target, re.IGNORECASE):
                return False, f"触发宪法红线拦截: {reason}"

    # 1b. 共现兜底：同一句里既有"变更类动词"又有"风险名词" → 一律拒（禁止式子句先剥离）。
    for sentence in re.split(r"[。；;\n]", rule_text):
        remainder = _strip_prohibition_clauses(sentence)
        if not remainder:
            continue
        if re.search(_RISK_CHANGE_VERBS, remainder) and re.search(_RISK_NOUNS, remainder, re.IGNORECASE):
            return False, "触发宪法红线拦截: RISK_PARAMETER_TAMPERING (疑似修改杠杆/保证金/风控阈值/拦截器)"

    # 1c. 严禁硬编码绝对资金金额：资金量必须以动态风险预算或相对 R 表达
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:USDT|USD|美元|美金|万\s*U)\b", rule_text, re.IGNORECASE) or re.search(r"\b(?:USDT|USD)\s*\d+", rule_text, re.IGNORECASE):
        return False, "触发量化原则拦截: HARDCODED_ABSOLUTE_CAPITAL (心法严禁硬编码绝对资金金额，资金预算必须取自【本周期风险预算】或以 R/百分比相对表达)"

    # 2. Outlier / Single-Event Rejection Gate
    if sample_size < 2:
        return False, "样本量不足 (单笔偶发事件或极端插针噪点，拒绝写入长期心法)"

    return True, "PASSED"


class MemoryCorruptError(ValueError):
    """Invalid authority is never replaced implicitly."""


class MemoryVersionRequiredError(ValueError):
    """Administrative writes require the version from GET."""


class MemoryConflictError(ValueError):
    """The snapshot used to prepare an update is stale."""


def _validate(lessons):
    if not isinstance(lessons, list):
        raise MemoryCorruptError("Expected a lesson list")
    ids = set()
    for item in lessons:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not item["id"] or item["id"] in ids
                or not isinstance(item.get("rule_text"), str) or not item["rule_text"].strip()
                or type(item.get("enabled")) is not bool):
            raise MemoryCorruptError("Invalid lesson schema or duplicate id")
        for key in ("health_score", "ttl_days", "sample_size"):
            if key in item and (type(item[key]) not in (int, float) or not math.isfinite(item[key]) or item[key] < 0):
                raise MemoryCorruptError(f"Invalid numeric field: {key}")
        for key in ("category", "created_at", "shield_status"):
            if key in item and not isinstance(item[key], str):
                raise MemoryCorruptError(f"Invalid text field: {key}")
        ids.add(item["id"])
    return lessons


def read_memory_snapshot():
    """Pure read: missing != empty; legacy lists remain readable without migration."""
    try:
        raw = STRUCTURED_MEMORY_FILE.read_bytes()
    except FileNotFoundError:
        return {"exists": False, "version": "missing", "lessons": []}
    try:
        payload = json.loads(raw)
        if isinstance(payload, list):
            lessons = payload
        else:
            if (not isinstance(payload, dict) or payload.get("schema_version") != 1
                    or not isinstance(payload.get("revision"), str)):
                raise MemoryCorruptError("Invalid memory envelope")
            lessons = payload["lessons"]
        _validate(lessons)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise MemoryCorruptError("Structured memory is damaged; retained unchanged") from exc
    return {"exists": True, "version": hashlib.sha256(raw).hexdigest(), "lessons": lessons}


def load_structured_memory() -> List[Dict[str, Any]]:
    return read_memory_snapshot()["lessons"]


def is_lesson_expired(item: Dict[str, Any], now: Optional[datetime.datetime] = None) -> bool:
    """心法是否已超过自然半衰期（TTL 天数）。

    2026-10：随基准机制一并拆除「基准心法永不过期」的豁免 —— 基准已不存在，
    所有心法一律按 `ttl_days` 计半衰期（无差别对待，不再有宪法级例外）。
    """
    created_at_str = item.get("created_at")
    ttl_days = float(item.get("ttl_days") or 7)
    if not created_at_str:
        return False
    try:
        if created_at_str.endswith("Z"):
            created_at_str = created_at_str[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(created_at_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        cur = now or datetime.datetime.now(datetime.timezone.utc)
        return (cur - dt).total_seconds() > (ttl_days * 86400)
    except Exception:
        return False


def render_lessons(lessons):
    now = datetime.datetime.now(datetime.timezone.utc)
    active = []
    for item in lessons:
        if not item.get("enabled"):
            continue
        # If natural half-life expired, suppress from active trading prompt injection
        if is_lesson_expired(item, now):
            continue
        active.append(item)
    # Capacity limit: strictly select at most top 8 active lessons.
    # ⚠️ 2026-10（方向 4）：排序键从 `(is_baseline, created_at)` 换成
    # `lesson_health.rank_lessons` —— 旧键是**"新的赢"**，一条落地后一直亏钱的
    # 战术心法只要够新就挤掉更有效的旧心法（注入配额只有 8 条）。
    # 现在：健康分降序 ⇒ 分数相同时才比新旧（基准机制已于 2026-10 整体拆除）。
    capped_active = rank_lessons(active)[:MAX_INJECTED_LESSONS]
    return "\n".join(f"- {item['rule_text']}" for item in capped_active)


#: 提示词注入上限（基线优先，其余按时间倒序）——**超出的 active 心法不会进主脑**。
#: 审计 P1-8：旧实现把这个截断藏在读侧，页面仍把超出的算作"生效中"，文案还写
#: "实时透明注入主脑 Prompt" → 管理员以为 12 条都在生效，实际只有 8 条。
MAX_INJECTED_LESSONS = 8


def injection_report(lessons) -> Dict[str, Any]:
    """披露注入实况：active(未过期)/injected 的条数与未注入清单（供面板与审计）。"""
    now = datetime.datetime.now(datetime.timezone.utc)
    active = [i for i in (lessons or []) if isinstance(i, dict) and i.get("enabled") and not is_lesson_expired(i, now)]
    # 与 `render_lessons` 共用同一份排序（`rank_lessons`）—— 否则面板说注入了 A、
    # 提示词里却是 B（这正是"实时透明注入"文案曾经撒过的谎）。
    sorted_active = rank_lessons(active)
    injected = sorted_active[:MAX_INJECTED_LESSONS]
    injected_ids = {id(i) for i in injected}
    return {
        "active": len(active),
        "injected": len(injected),
        "limit": MAX_INJECTED_LESSONS,
        "not_injected": [
            {"id": i.get("id"), "category": i.get("category"), "rule_text": (i.get("rule_text") or "")[:60]}
            for i in sorted_active if id(i) not in injected_ids
        ],
    }


def read_trading_context(legacy_md=None, legacy_json=None):
    snapshot = read_memory_snapshot()
    if snapshot["exists"]:
        texts = [i["rule_text"] for i in snapshot["lessons"] if i["enabled"]]
        return snapshot, render_lessons(snapshot["lessons"]), texts
    # Compatibility is read-only and only used if the authority does not exist.
    md_path = Path(legacy_md) if legacy_md is not None else AI_MEMORY_MD_FILE
    text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    texts = []
    if legacy_json is not None and Path(legacy_json).is_file():
        payload = json.loads(Path(legacy_json).read_text(encoding="utf-8"))
        texts = payload.get("core_lessons", [])
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            raise MemoryCorruptError("Invalid legacy lessons")
    return snapshot, text or "\n".join(f"- {t}" for t in texts), texts


def render_trading_memory(legacy_md=None, legacy_json=None):
    text = read_trading_context(legacy_md, legacy_json)[1]
    if not text.strip():
        return ""
    return "======================= 【AstraQuant 启发式实战认知与长期记忆】 =======================\n" + text


def sync_markdown_mirror() -> bool:
    """Refresh the derived AI_TRADING_MEMORY.md mirror from the structured authority.

    The markdown file is a read-only compatibility artifact for legacy readers
    (notably the public dashboard). It must never drift behind the authority, or
    the homepage freezes on a stale snapshot while the engine keeps revising.
    The structured store remains the single authority; this mirror is rewritten
    after every review cycle.
    """
    snapshot = read_memory_snapshot()
    if not snapshot["exists"]:
        return False
    lessons = snapshot["lessons"]
    # ⚠️ 2026-10 修复：空库**必须照写**（写明"当前为空"），不能 `return False` 跳过。
    #
    # 旧实现在心法库为空时直接返回 False ⇒ 镜像文件保持上一次的内容不变。用户
    # 清空心法库后，看板/遗留读者仍会看到**已删除的 5 条心法**与"共 5 条心法"的
    # 表头 —— 也就是说"删掉"在界面上根本没发生。镜像的契约是"绝不落后于权威"
    # （见本函数 docstring），空也是一种必须如实反映的状态。
    body = render_trading_memory()
    enabled_count = sum(1 for i in lessons if i.get("enabled"))
    if not body.strip():
        body = ("======================= 【AstraQuant 启发式实战认知与长期记忆】 =======================\n"
                "（当前无生效心法：系统自 2026-10 起不再预设任何心法；"
                "心法由自进化从真实平仓证据中学出，或由管理员手工录入。）")
    stamps = [i.get("created_at") for i in lessons if i.get("created_at")]
    newest = max(stamps) if stamps else ""
    if newest:
        try:
            local = datetime.datetime.fromisoformat(newest).astimezone(
                datetime.timezone(datetime.timedelta(hours=8))
            ).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            local = str(newest)[:19]
    else:
        local = "--"
    doc = (
        "# AstraQuant AI 交易实战长期心法 (Heuristic Long-Term Memory)\n\n"
        f"> 状态：由自进化防污染认知中枢实时纳管 | 更新基准: {local} (UTC+8)\n"
        f"> 权威来源: structured_trading_memory.json | 修订 {str(snapshot.get('version'))[:8]}"
        f" | 共 {len(lessons)} 条心法（生效 {enabled_count} 条）\n"
        "> 系统不预设任何心法（2026-10 起）：库中每一条都来自真实平仓证据或管理员录入。\n\n"
        + body
        + "\n"
    )
    tmp = AI_MEMORY_MD_FILE.with_suffix(f".md.tmp.{os.getpid()}")
    try:
        AI_MEMORY_MD_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(doc, encoding="utf-8")
        os.replace(tmp, AI_MEMORY_MD_FILE)
    finally:
        if tmp.exists():
            tmp.unlink()
    return True


@contextmanager
def _memory_lock():
    STRUCTURED_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(str(STRUCTURED_MEMORY_FILE) + ".lock", "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _commit(lessons):
    _validate(lessons)
    payload = {"schema_version": 1, "revision": uuid.uuid4().hex, "lessons": lessons}
    fd, name = tempfile.mkstemp(prefix=".memory-", suffix=".tmp", dir=STRUCTURED_MEMORY_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, STRUCTURED_MEMORY_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    # Markdown is rendered on demand, never a second commit or an authority.


def _check_version(snapshot, expected_version):
    if expected_version is None or expected_version == "":
        raise MemoryVersionRequiredError("缺少 expected_version，请重新加载心法后再操作")
    if snapshot["version"] != expected_version:
        raise MemoryConflictError("心法版本已变化，请重新加载后再操作；未覆盖当前数据")


def _new_lesson(text, sample_size, category="TACTICAL"):
    """建档一条新心法。

    2026-10：`is_baseline` 字段随基准机制整体拆除 —— 新心法不再分"宪法级/战术级"，
    一律按 TTL 计半衰期、按证据重算健康度。
    """
    return {"id": "lesson_" + uuid.uuid4().hex, "category": category,
            "rule_text": text.strip(), "enabled": True, "health_score": 90.0,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ttl_days": 7, "sample_size": sample_size,
            "shield_status": "PASSED"}


def _review_candidates(texts, old, sample_size, strict, change_status=None):
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        raise ValueError("Expected text list")
    by_text = {i["rule_text"].strip(): i for i in old}
    result = []
    seen = set()
    seen_titles = set()
    for text in texts:
        text = text.strip()
        if text in seen:
            continue
        title_match = re.match(r"^\s*【([^】]+)】", text)
        title = title_match.group(1).strip() if title_match else ""
        if title and title in seen_titles:
            continue
        seen.add(text)
        if title:
            seen_titles.add(title)
        # Unchanged entries retain identity, audit metadata and disabled state.
        if text in by_text:
            result.append(copy.deepcopy(by_text[text]))
            continue
        passed, reason = audit_proposed_lesson(text, sample_size=sample_size)
        if not passed:
            if strict:
                raise ValueError(reason)
            continue
        result.append(_new_lesson(text, sample_size))
    # Preserve disabled tombstones even when omitted by a model or legacy editor.
    result.extend(copy.deepcopy(i) for i in old if not i["enabled"] and i["rule_text"].strip() not in seen)
    # 审计 P1-8c：REVISE/INVALIDATE 下，模型没复述的**已学**心法旧实现直接消失，
    # 报告只统计被宪法补回的条目 → 静默丢知识。现在改为保留为**停用存档**
    # （enabled=False + 退役留痕），既不注入提示词、也不蒸发，面板可见并可人工恢复。
    # 2026-10：基准机制拆除后不再有"基准豁免"，所有未复述的启用条目一律进停用存档。
    if str(change_status or "").upper() in {"REVISE", "INVALIDATE"}:
        for item in old:
            if not item.get("enabled"):
                continue
            if item["rule_text"].strip() in seen:
                continue
            tomb = copy.deepcopy(item)
            tomb["enabled"] = False
            tomb["retired_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            tomb["retired_reason"] = f"{str(change_status).upper()} 未复述，宿主保留为停用存档（可人工复核恢复）"
            result.append(tomb)
    return result


def publish_review(texts, *, expected_version, sample_size, change_status):
    if change_status == "NO_CHANGE":
        return False
    if change_status not in {"ADD", "REVISE", "INVALIDATE"}:
        raise ValueError("Invalid change status")
    with _memory_lock():
        snapshot = read_memory_snapshot()
        _check_version(snapshot, expected_version)
        candidates = _review_candidates(texts, snapshot["lessons"], sample_size, True, change_status)
        if not candidates or candidates == snapshot["lessons"]:
            return False
        # Rejected-only proposals must not remove existing active entries.
        if not any(i["rule_text"].strip() in {t.strip() for t in texts} for i in candidates):
            return False
        _commit(candidates)
        return True


def refresh_health_from_evidence(*, closed_trades, log_msg=None) -> Dict[str, Any]:
    """按**平仓证据**重算全部心法健康度，并按需归档（方向 4，2026-10）。

    这是把 `health_score` 从装饰品变成承重件的落地入口：由
    `self_improvement_engine.run_self_evolution` 每轮复盘调用一次。

    ## 为什么走 CAS（`expected_version`）而不是直接覆盖

    心法库是**跨进程共享的可变权威**（worker 复盘、后端 `admin_mutate` 手工编辑
    都可能同时写）。乐观并发是本仓既定纪律：版本对不上就**放弃本轮重算**、
    下一轮再来，**绝不**用陈旧快照覆盖管理员刚做的编辑。

    ## 边界（Code is Law）

    - **不删除任何条目**：归档只是 `enabled=False` ＋ `shield_status="archived"` 留痕；
    - **不触碰基准心法**：由 `lesson_health.decide_archive` 硬性保证；
    - **任何失败都只记日志**：心法健康度是**增强**，绝不许打断复盘主流程。
    """
    if not closed_trades:
        return {"status": "skipped", "reason": "无平仓样本，不重算健康度", "changes": []}
    try:
        with _memory_lock():
            snapshot = read_memory_snapshot()
            updated, changes = refresh_lesson_health(snapshot["lessons"], closed_trades=closed_trades)
            if not changes:
                return {"status": "unchanged", "version": snapshot["version"], "changes": []}
            _validate(updated)
            _commit(updated)
            version = read_memory_snapshot()["version"]
        rescored = sum(1 for c in changes if c["action"] == "rescore")
        archived = sum(1 for c in changes if c["action"] == "archive")
        if log_msg:
            log_msg(f"🩺 心法健康度重算：{rescored} 条分数更新、{archived} 条归档"
                    f"（阈值 {ARCHIVE_HEALTH_THRESHOLD}，样本门槛 {MIN_HEALTH_SAMPLE}）")
            for change in changes:
                if change["action"] == "archive":
                    log_msg(f"📦 归档心法 {change['id']}：{change['reason']}")
        return {"status": "updated", "version": version, "changes": changes}
    except Exception as exc:  # noqa: BLE001 - 健康度是增强，绝不打断复盘
        if log_msg:
            log_msg(f"心法健康度重算跳过（不影响复盘）: {exc}")
        return {"status": "error", "reason": str(exc), "changes": []}


def save_structured_memory(lessons, *, expected_version):
    """Compatibility publisher; changed/new records must pass the same audit."""
    _validate(lessons)
    with _memory_lock():
        snapshot = read_memory_snapshot()
        _check_version(snapshot, expected_version)
        disabled = {i["rule_text"].strip() for i in snapshot["lessons"] if not i["enabled"]}
        for item in lessons:
            if item["enabled"] and item["rule_text"].strip() in disabled:
                raise ValueError("Disabled text requires explicit toggle, not republication")
            if item not in snapshot["lessons"]:
                passed, reason = audit_proposed_lesson(item["rule_text"], item.get("sample_size", 1))
                if not passed:
                    raise ValueError(reason)
        _commit(lessons)


def toggle_lesson(lesson_id, *, expected_version=None):
    with _memory_lock():
        snapshot = read_memory_snapshot()
        _check_version(snapshot, expected_version)
        lessons = snapshot["lessons"]
        for item in lessons:
            if item["id"] == lesson_id:
                item["enabled"] = not item["enabled"]
                _commit(lessons)
                return item
    return None


def reset_all_lessons(*, expected_version=None):
    """**清空心法库**（2026-10 起取代 `rollback_to_baseline`）。

    历史：这个入口原叫"回滚至黄金基准"，把心法库重置为 4 条官方预设心法。
    用户已于 2026-10 要求取消全部预设（"以后不再预设心法"），故语义从
    "重置回预设"变为"清空到空白" —— 名字与面板文案一并改，避免"点回滚却清空"
    的反直觉操作（那正是最危险的按钮形态）。

    安全语义（未变）：
    - 走 `_memory_lock` ＋ `expected_version` CAS：版本不符即拒绝，不覆盖并发编辑；
    - **快照损坏时绝不被覆盖**（`read_memory_snapshot` 会抛 `MemoryCorruptError`）；
    - **删得掉、可恢复**：调用前请自行留档（`.archive/`），本函数不做备份。
    """
    with _memory_lock():
        snapshot = read_memory_snapshot()  # Corruption is never overwritten.
        _check_version(snapshot, expected_version)
        lessons: list = []          # 起点 = 空集（系统不预设任何心法）
        _commit(lessons)
        return lessons


def admin_memory_view():
    snapshot, raw, _ = read_trading_context()
    items = [i["rule_text"] for i in snapshot["lessons"] if i["enabled"]]
    if not snapshot["exists"]:
        items = [line.strip()[2:].strip() for line in raw.splitlines() if line.strip().startswith("- ")]
    return {"items": items, "count": len(items), "raw": raw,
            "structured_lessons": snapshot["lessons"], "version": snapshot["version"],
            "legacy_read_only": not snapshot["exists"]}


def admin_mutate(operation, *, texts=None, index=None, lesson_id=None, expected_version=None):
    with _memory_lock():
        snapshot = read_memory_snapshot()
        _check_version(snapshot, expected_version)
        if not snapshot["exists"]:
            raise MemoryConflictError("Legacy memory is read-only; explicit initialization required")
        old = snapshot["lessons"]
        active = [i["rule_text"] for i in old if i["enabled"]]
        removed = None
        if operation == "delete":
            if lesson_id is not None:
                target = next((i for i in old if i["id"] == lesson_id), None)
                if target is None:
                    raise IndexError("Memory id not found")
                removed = target["rule_text"]
                lessons = [i for i in old if i["id"] != lesson_id]
            else:
                if index is None or index < 0 or index >= len(active):
                    raise IndexError("Memory index not found")
                removed = active.pop(index)
                lessons = [i for i in old if i["rule_text"] != removed]
        elif operation in {"add", "replace"}:
            candidates = list(texts or [])
            if operation == "add":
                candidates += active
            lessons = _review_candidates(candidates, old, 3, True)
        else:
            raise ValueError("Unknown memory operation")
        if lessons != old:
            _commit(lessons)
        result = {"saved": True, "items": [i["rule_text"] for i in lessons if i["enabled"]]}
        if removed is not None:
            result["removed"] = removed
        return result


def add_safe_lesson(rule_text, category="TACTICAL", sample_size=3):
    passed, reason = audit_proposed_lesson(rule_text, sample_size)
    if not passed:
        return False, reason, None
    with _memory_lock():
        lessons = load_structured_memory()
        for item in lessons:
            if item["rule_text"].strip() == rule_text.strip():
                return True, "条目已存在（保留启停状态）", item
        item = _new_lesson(rule_text, sample_size, category)
        lessons.append(item)
        _commit(lessons)
        return True, "心法审查通过并成功收录", item
