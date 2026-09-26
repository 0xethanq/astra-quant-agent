"""CIO 终审输出的 `adopted_role` 归一化（结构优化阶段 4·B3 第二十八刀）。

原样搬自 `astra_backend/council/debate.py::execute_council_debate` 的
「Post-process & normalize adopted_role in decisions for traceability」块（28 行）。

## 这段在做什么

CIO 模型被要求在每个标的的决策里给出 `adopted_role`（采纳了哪位交易员的提案）。
但**模型经常漏填、填空串、或填字符串 `"none"`** —— 于是这里做一次归一化，
把"没填"变成可追溯的值：

| 模型给的 `adopted_role` | 归一化结果 |
|---|---|
| 非空且不是 `"none"` | `str(ar).strip()`（原样保留，**不校验是否真的是合法 role_id**） |
| 空 / `None` / `"none"`，且 `action == "WAIT"` | `"REJECT_ALL"` |
| 空 / `None` / `"none"`，且 `action != "WAIT"` | 从 `reasoning` 文本里**反查**别名 → 命中则填该 role_id，否则 `None` |

## 四处易错点（均原样保留）

1. **WAIT 直接给 `REJECT_ALL`**，不走文本反查 —— 观望本就没有"被采纳者"。
2. **"没填"的判据有三个**：`is None`、去空格后为 `""`、去空格转小写后为 `"none"`。
   少一个都会让某个形态漏过去（模型的"空"不止一种写法）。
3. **别名表是"基础两件套 + 关键字追加"**：
   每个 role 先有 `[r_k, r_name]`（role_id 与显示名），再按 role_id 里出现的
   关键字追加中文/英文别名。**追加是 `extend`，且 `trend`/`momentum`/`quant`
   是 `if/elif` 链** —— 一个 role_id 只会命中其中一支。
4. **命中即 `break`，按 `trader_keys` 的顺序取第一个命中者**。
   多个交易员的别名都在 `reasoning` 里出现时，**谁在 `trader_keys` 里靠前谁赢** ——
   这是刻意的确定性裁决，不是"最匹配者胜"。
   另有 **`if alias and ...` 的空串守卫**：`r_name` 为空时不能拿 `""` 去比
   （`"" in text` 恒真，会误判成"命中"）。

## 与门面的分工

纯函数：`roles` 与 `trader_keys` 由调用方传入。
本模块不 import `council_manager`，也不在 import 期绑定任何门面对象。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["build_alias_candidates", "resolve_adopted_role"]

#: role_id 关键字 → 追加的别名（中文/英文/风格名）。
#: 顺序即 `reasoning` 文本反查时的试探顺序；键之间是互斥的（`if/elif` 语义）。
ROLE_KEYWORD_ALIASES: Dict[str, List[str]] = {
    "trend": ["交易员 A", "交易员A", "Trader A", "trader a", "稳健型"],
    "momentum": ["交易员 B", "交易员B", "Trader B", "trader b", "动能型"],
    "quant": ["交易员 C", "交易员C", "Trader C", "trader c", "量化型"],
}


def build_alias_candidates(role_key: str, role_name: str) -> List[str]:
    """某个交易员的别名候选：`[role_key, role_name]` + 按关键字追加的一支。

    **`if/elif` 链**：`trend`/`momentum`/`quant` 只命中第一个匹配的分支。
    role_id 里同时含多个关键字时（如 `trader_trend_quant`）只追加 `trend` 那一支 ——
    原样保留的既有行为。
    """
    candidates = [role_key, role_name]
    for keyword, aliases in ROLE_KEYWORD_ALIASES.items():
        if keyword in role_key:
            candidates.extend(aliases)
            break
    return candidates


def resolve_adopted_role(dec: Dict[str, Any], roles: Dict[str, Any],
                         trader_keys: List[str]) -> Optional[str]:
    """从单条决策里解析 `adopted_role`（不修改入参）。

    `roles` 形如 `{role_key: {"name": ...}}`；`trader_keys` 的顺序决定
    多个候选同时命中时谁赢（靠前者胜）。
    """
    act = str(dec.get("action", "")).upper()
    ar = dec.get("adopted_role")
    if ar is None or str(ar).strip() == "" or str(ar).strip().lower() == "none":
        if act == "WAIT":
            return "REJECT_ALL"
        # Attempt to resolve from reasoning text
        reasoning_text = str(dec.get("reasoning", ""))
        for r_k in trader_keys:
            r_name = roles.get(r_k, {}).get("name", "")
            for alias in build_alias_candidates(r_k, r_name):
                if alias and alias.lower() in reasoning_text.lower():
                    return r_k
        return None
    return str(ar).strip()


def normalize_decisions(decisions: Dict[str, Any], roles: Dict[str, Any],
                        trader_keys: List[str]) -> Dict[str, Any]:
    """对 `decisions` 里每个标的的 dict 决策原地写入归一化后的 `adopted_role`。

    - 非 dict 的决策项**原样跳过**；
    - 返回入参本身（与门面原有的"原地改"语义一致）。
    """
    for _sym, dec in decisions.items():
        if isinstance(dec, dict):
            dec["adopted_role"] = resolve_adopted_role(dec, roles, trader_keys)
    return decisions


def process_brain_output(brain_output: Dict[str, Any], roles: Dict[str, Any],
                         trader_keys: List[str]) -> None:
    """门面调用的入口：只在 `brain_output["decisions"]` 是 dict 时归一化。"""
    decisions = brain_output.get("decisions")
    if isinstance(decisions, dict):
        normalize_decisions(decisions, roles, trader_keys)
