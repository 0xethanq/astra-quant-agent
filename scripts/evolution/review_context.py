"""自进化复盘的**上下文装配**（`scripts/evolution/` 部件，从门面搬出）。

| 函数 | 职责 |
|---|---|
| `summarize_closed_trades` | 平仓统计汇总（笔数/胜负/胜率/净利/手续费）+ 数理快照可观测性审计摘要 |
| `build_host_constitution` | **宿主宪章**文本：代码层硬约束，profile 只能调措辞风格，永远无法删改证据纪律与基准心法保护（Code is Law，2026-09-10） |
| `parse_review_json` | 复盘回复 → `(cleaned, review_json)`：只裁 Markdown 围栏、**不** trim（门面按 `len(cleaned)` 记 `output_chars`）；解析失败**必须上抛** |
| `repair_json_object` | 容错 JSON 修复（2026-09-30）：取最外层平衡对象 / 转义字符串内裸控制字符 / 删尾逗号；**修不动就抛原错**。与交易主脑 `scripts/brain/dispatch.py` 共用同一份实现 |

## 为什么单独成模块

宿主宪章是**安全语义文本**：它规定"字段缺失不得解读为证据""基准心法不得静默删除"
"证据不足必须 NO_CHANGE"。埋在 95 行提示词装配里时，改错一行不会有人发现；
独立成函数后，门可以直接断言四条硬约束**逐条存在**且 `observability_brief` 真的被插值。

`repair_json_object` 为什么也放这里：它是**模型输出容错面**的公共入口 —— 实测一次
"字符串里裸换行"让整轮复盘零产出（唯一回退模型还欠费 402），而同一类坏输出同样会
打掉交易主脑一整个周期。放在这里由两侧共用，避免各写一份必然漂移的容错实现。

全部函数都是**纯函数**（零副作用、零模块全局读取 —— 依赖全部显式入参）；
修复诊断只报**结构化计数**，绝不回传响应正文（与遥测层"不存提示词/响应内容"同纪律）。
"""


from __future__ import annotations

import json

from typing import Any, Dict, List, Tuple


def summarize_closed_trades(*,
        audit_snapshot_observability,
        closed_trades,
        render_observability_brief):
    total = len(closed_trades)
    wins = [t for t in closed_trades if t["net_pnl"] > 0]
    losses = [t for t in closed_trades if t["net_pnl"] <= 0]
    win_rate = round(len(wins) / total * 100, 1) if total > 0 else 0.0
    total_net = round(sum(t["net_pnl"] for t in closed_trades), 2)
    total_fees = round(sum(t["fee"] for t in closed_trades), 2)
    snapshot_audit = audit_snapshot_observability(closed_trades)
    observability_brief = render_observability_brief(snapshot_audit)
    return (total, wins, losses, win_rate, total_net, total_fees, snapshot_audit, observability_brief)


def build_host_constitution(*,
        observability_brief):
    host_constitution = (
        "\n\n======================= 【宿主宪章·代码层硬约束（任何提示词风格档案不可覆盖）】 =======================\n"
        f"1. 数理快照可观测性审计（宿主确定性统计，非模型推断）：{observability_brief}。\n"
        "2. 逐单标注含义：DYNAMICS_OBSERVED=开仓动力学/积分/概率链完整，可作数理因果归因；"
        "PARTIAL=仅可引用 entry_snapshot 中实际非空字段；PRICE_ONLY / NONE=数理快照不可观测，"
        "严禁编造或倒推 v/a/j/I、energy_integral、deviation_area_integral、延续/击穿概率、VaR/CVaR 因果，"
        "字段缺失本身不得解读为任何证据。\n"
        "3. ai_long_term_memory 给出生效后完整清单时必须原样包含全部现有基准心法（is_baseline）："
        "省略条目会被宿主原样补回并留痕；认定基准失效只能写入 diagnosis_insights 交人工复核，禁止静默删除。\n"
        "4. 证据不足必须 NO_CHANGE；NO_CHANGE 永不覆盖或清空长期记忆。\n"
    )
    return (host_constitution)


#: 字符串字面量里被**非法裸写**的控制字符 → 合法转义序列。
#: JSON 规范不允许字符串内出现裸控制字符（`json.loads` 报
#: `Invalid control character at: line N column M`），但大模型输出里极常见。
_CONTROL_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _extract_outermost_object(*, text):
    """字符串感知地取出最外层**平衡**的 `{...}`（前后有散文时用）。

    返回 `None` 表示找不到平衡对象（例如整段就不是 JSON）—— 调用方应让
    `json.loads` 去抛**原始**错误，绝不在这里臆造一个对象。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _escape_control_chars_in_strings(*, text):
    """只把**字符串字面量内部**的裸控制字符转义（字符串外的换行是合法空白，不能动）。

    返回 `(修复后的文本, 修复条数)`。条数用于日志**结构性**诊断
    （绝不记录响应正文，遵守 `astra_gateway/telemetry.py` 的"不存提示词/响应内容"）。
    """
    out = []
    in_string = False
    escaped = False
    fixed = 0
    for char in text:
        if in_string:
            if escaped:
                escaped = False
                out.append(char)
                continue
            if char == "\\":
                escaped = True
                out.append(char)
                continue
            if char == '"':
                in_string = False
                out.append(char)
                continue
            if char < " ":
                out.append(_CONTROL_ESCAPES.get(char, "\\u%04x" % ord(char)))
                fixed += 1
                continue
            out.append(char)
            continue
        if char == '"':
            in_string = True
        out.append(char)
    return "".join(out), fixed


def _drop_trailing_commas(*, text):
    """字符串感知地删掉 `}` / `]` 前的尾逗号（模型输出的另一高频低级错误）。"""
    out = []
    in_string = False
    escaped = False
    dropped = 0
    length = len(text)
    index = 0
    while index < length:
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            out.append(char)
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == ",":
            probe = index + 1
            while probe < length and text[probe] in " \t\r\n":
                probe += 1
            if probe < length and text[probe] in "}]":
                dropped += 1
                index += 1
                continue
        out.append(char)
        index += 1
    return "".join(out), dropped


def repair_json_object(*, content):
    """容错解析一个 JSON 对象；**修不动就抛原错**。

    ## 为什么需要它（实测事故 2026-09-30 08:02）

    自进化复盘的真实日志：

    ```
    Error in LLM evolution review: Invalid control character at: line 26 column 126 (char 1923)
    ⚠️ 复盘主模型失败（JSONDecodeError…），回退 glm-5.3-flash 重试一次
    Error in LLM evolution review: LLM 网关返回 HTTP 402（模型 glm-5.3-flash）：余额不足
    ```

    主模型只错在一处**字符串里的裸换行**，而唯一回退模型欠费 ⇒ 整轮复盘落成
    `NO_CHANGE` + `insights: []`，用户侧表现为"自进化看起来没更新"。
    这类错误的修复成本是零，不该消耗掉整轮预算。

    ## 修复次序（每一步都字符串感知）

    1. 前后有散文 ⇒ 取最外层平衡 `{...}`；
    2. 字符串内的裸控制字符 ⇒ 转义（**这正是本次报错**）；
    3. `}`/`]` 前的尾逗号 ⇒ 删除；
    4. `json.loads`；仍失败 ⇒ 抛异常（**绝不吞**，门面靠 `except` 把它变成
       `__llm_error__` 上报，见 `test_invalid_json_propagates`）。

    返回 `(对象, 诊断)`；解析成功但非对象 ⇒ 归一为 `{}`（与 `parse_review_json` 既有行为一致）。
    诊断只含结构化计数，**不含任何响应正文**。
    """
    body = str(content or "").strip()
    report = {"extracted_object": False, "escaped_control_chars": 0, "dropped_trailing_commas": 0}
    candidate = _extract_outermost_object(text=body)
    if candidate is not None and candidate != body:
        report["extracted_object"] = True
        body = candidate
    body, escaped = _escape_control_chars_in_strings(text=body)
    report["escaped_control_chars"] = escaped
    body, dropped = _drop_trailing_commas(text=body)
    report["dropped_trailing_commas"] = dropped
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, report


def parse_review_json(*,
        content):
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]

    # ⚠️ `cleaned`（返回值第一项）**只裁围栏、不 trim**：门面用 `len(cleaned)` 记
    # `output_chars`，那 2 个换行照旧计入（见 test_fenced_json_is_stripped_and_cleaned_content_returned）。
    try:
        review_json = json.loads(content.strip())
    except ValueError as original_error:
        # 容错修复（2026-09-30）：模型输出里的裸控制字符 / 尾逗号 / 前后散文。
        # 修不动 ⇒ 抛**原始**异常：它的行号列号是排障线索，也是既有可观测性契约。
        try:
            review_json, _repair_report = repair_json_object(content=content)
        except ValueError:
            raise original_error
    if not isinstance(review_json, dict):
        review_json = {}
    return content, review_json


def normalize_asset_multipliers(*,
        TARGET_INSTRUMENTS,
        clamp,
        llm_review):
    raw_asset_mults = llm_review.get("asset_multipliers", {})
    if not isinstance(raw_asset_mults, dict):
        raw_asset_mults = {}
    asset_mults = {
        asset: clamp(raw_asset_mults.get(asset, 1.0), 0.5, 1.5, 1.0)
        for asset in TARGET_INSTRUMENTS
    }
    return asset_mults
