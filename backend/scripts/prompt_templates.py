"""提示词模板编译：文本 ⇄ 模块 ⇄ 管线布局（结构优化阶段 4·B3 第五十三刀）。

## 为什么单独成模块

`scripts/prompt_library.py`（1035 行）里有两块职责：

| 簇 | 内容 |
|---|---|
| **模板编译** | 文本↔模块互转、模块标签继承、管线布局套用与视图（本模块） |
| 配置库 CRUD | `load_library` / `save_library` / profile 增删改查 / 导入导出 / 校验 |

实测（传递纯度扫描）：**CRUD 簇全部经 `BASELINE_FILE` / `LOCAL_FILE` / `MAX_PROFILE_CHARS`
被"污染"，而模板编译簇是纯的**。故抽出本簇，
门面 `prompt_library.py` **1035 → 973 行**。

## ⚠️ 依赖处理：三项注入、一项随簇搬走

| 模块级名 | 本簇里的读点 | 处理 |
|---|---|---|
| `MAX_TEMPLATE_CHARS` | 仅 `_module` | **注入**（配置面口径，留在门面以便 patch） |
| `_BASE_TEMPLATE_SOURCES` | 仅 `base_template_text` | **注入**（它是"管线→基座来源"注册表） |
| `_BASE_TEMPLATE_CACHE` | 仅 `base_template_text` | **注入**（**可变**缓存，见下） |
| `_SECTION_RE` | 仅 `text_to_modules` | **随簇搬走**（只服务模板分节解析） |
| `BJ_TZ` | 本簇**零读点**（只有留在门面的 `_now` 读） | 不搬 |

⚠️ `_BASE_TEMPLATE_CACHE` 是**可变** dict，且门面另有
`register_base_template()` 往它里面写。若本模块 import 期绑一份，
门面登记的基座就**永远读不到**（两处状态分叉）—— 故必须由门面在调用时传入
**同一个对象**。

> ⚠️ **我在本刀的两次自我纠错**（都记下来）：
> 1. 第一版 docstring 我写"`_SECTION_RE` 在本簇里没有被读到（实测）"——
>    **是错的**。`text_to_modules` 明确用了它。我读错了自己工具的扫描输出。
>    正确处置是随簇搬走，并删掉门面那份已无读点的副本。
> 2. 第一版导入清单我是**手写的**，漏了 `hashlib` → 21 例 `NameError`。
>    改为**用 AST 求自由名**再补，才发现还漏了 `importlib` / `sys` / `copy`
>    以及那两个缓存的注入。

## ⚠️ 为什么 `_now` / `_default` **没有**跟着搬

它们看着像工具函数，但被**两个簇共用**：`_now()` 在 `_migrate` / `_revision` /
`create_profile` / `update_profile` / `rollback_profile` 里都用（CRUD 侧）；
`_default()` 在 `_migrate` / `load_library` 里用。搬过来会制造反向依赖。故留在门面。
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import re
import sys
import uuid
from typing import Any, Callable

# 分节标题解析（纯正则、无路径常量）。它**只**服务 `text_to_modules`，
# 故随簇搬来；门面里那份同名副本已因"读点随函数一起搬走"而删除。
_SECTION_RE = re.compile(r"(?m)(?=^={0,30}\s*【[^\n】]+】[^\n]*$)")

#: 语义变量插槽的语法（与 `scripts/prompt_library.py::_VAR_RE` **同形**：
#: 门面那份带 `ALLOWED_VARIABLES` 校验，本模块只做"这段文本带不带插槽"的结构判定，
#: 故不引入门面的白名单（否则纯模块反向依赖配置面）。
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _base_module_id(module: dict[str, Any]) -> str:
    """基座模块的 id：有就用，没有就按**标题**确定性派生（与 `_module` 同一派生器）。"""
    return str(module.get("id") or stable_base_module_id(str(module.get("title") or "")))


def _base_index(out: list[dict[str, Any]], title: str) -> int:
    """在已排好的模块序列里定位某条**基座**模块的下标（供稳定插入使用）。

    ⚠️ 刻意做成**模块级**函数而不是 `normalize_base_modules` 里的嵌套闭包：
    `tests/extraction/test_prompt_templates_extraction.py::test_shared_module_has_no_free_names`
    用 AST 只收集**模块级** FunctionDef 作为绑定名，嵌套闭包会被算成"未定义自由名"当场报错
    （2026-09-30 实测：`_index_of` 被判自由名）。
    """
    return next(i for i, m in enumerate(out)
                if str(m.get("title") or "") == title
                and str(m.get("source") or "") == "base")


def overlay_module_id(title: str, content: str) -> str:
    """`legacy` 覆盖层的**确定性** id（由标题 + 正文派生）。

    ⚠️ 为什么不能沿用被降级基座模块的 id（2026-09-30 实测撞车）：用户改过的基座降级成
    覆盖层后，读路径的 `normalize_base_modules` 会按标题回插现网基座，而基座 id 是
    `stable_base_module_id(title)` **确定性**的 ⇒ 覆盖层与回插的基座**同 id**，
    `validate_profile` 当场判「模块 ID 缺失或重复」，保存直接失败。

    用内容派生即可稳定（同一改动反复保存不churn）且与基座 id 天然不同。
    """
    digest = hashlib.sha1(f"astra-overlay::{title}::{content}".encode("utf-8")).hexdigest()[:10]
    return f"module-overlay-{digest}"


def _carries_unique_slot(stored: str, canonical: str) -> bool:
    """存档内容带着**基座文本没有**的插槽吗？

    ⚠️ 这条判定救回过一次真实回归（2026-09-30，本次改动自身引入），而且**差点没被发现**：

    `trading_user` 的代码基座登记在 `astra_backend/prompt_views.py::TRADING_USER_TEMPLATE`，
    但那是**给编辑器看的说明版**（"实时插槽：自进化引擎沉淀的可审计长期记忆…"）；
    真正实发的主脑用户消息基座是 `scripts/brain/prompt.py` 逐周期生成的 f-string，
    而**实时数据是靠这些插槽注入的**。`trading_user` 的 7 条基座里有 **6 条**是插槽载体：

    | 基座分节 | 存档携带的插槽 | 说明版长度差 |
    |---|---|---|
    | AstraQuant 启发式实战认知与长期记忆 | `{{trading_memory}}` | 92 → 105 |
    | 全网实时重大快讯与宏观情报 | `{{news_intelligence}}` | 85 → 82 |
    | 账户当前持仓与风险敞口全景 | `{{account_positions}}` | 85 → 93 |
    | 在途未成交限价挂单 | `{{pending_orders}}` | 101 → 112 |
    | 全标的池原生行情、技术指标与筹码矩阵 | `{{market_matrix}}` | 86 → 110 |
    | 当前决策时间戳与市场时效 | `{{decision_timestamp}}`/`{{account_balance}}`/`{{risk_budget}}` | 121 → 80 |

    ★ 危险之处在于**总长度只差 +12 字符**（有增有减互相抵消）：一旦被说明文本覆盖，
    模型将**收不到任何实时账户数据**，而字符数看起来只是"多了十几个字"。
    故这里必须按**插槽集合**判定，不能按长度或文本相似度判定。

    判定规则：存档带着基座没有的插槽 ⇒ 存档是**插槽载体**，不得被基座说明文本覆盖。
    """
    stored_slots = set(_PLACEHOLDER_RE.findall(str(stored or "")))
    if not stored_slots:
        return False
    return bool(stored_slots - set(_PLACEHOLDER_RE.findall(str(canonical or ""))))


def stable_base_module_id(title: str) -> str:
    """基座模块的**确定性** id（由标题派生）。

    旧实现给每个模块随机 uuid：同一段基座文本每次重建都换 id，于是
    「同 id/同标题继承来源」只能靠标题兜底，方案库里 base 模块 id 每存一次就翻新一遍
    （P1-2/批5 同族）。基座模块内容由代码决定，id 派生自标题即可稳定。
    """
    # ⚠️ 种子串随 2026-09-27「r20 → astra 全量改名」一起改了（`r20-base-module::` →
    #    `astra-base-module::`）。**已核实这是安全的**，三条证据：
    #      ① 出厂基线 `data/prompt_library.json` 里**没有任何** `module-base-*` id
    #         （实测 0 条）—— 它不持久化这类 id，id 每次都由标题现算；
    #      ② 模块合并是**按标题**匹配的（`prompt_library.py` 的 `base_by_title`），
    #         且残留基座模块只在"标题未被匹配"时才追加 ⇒ 用户本地库里就算存着
    #         旧种子算出的 id，也只是被重新派生一次，不会产生重复预设；
    #      ③ 这个串是**哈希输入**，不对用户显示，也不参与任何对外契约。
    #    换言之：改它只会让 id 换一批，而 id 与标题是 1:1 的确定性映射。
    digest = hashlib.sha1(f"astra-base-module::{title}".encode("utf-8")).hexdigest()[:10]
    return f"module-base-{digest}"

def _module(module: dict[str, Any], index: int = 0, *,
            max_template_chars: int) -> dict[str, Any]:
    title = str(module.get("title") or f"模块 {index+1}").strip()[:100]
    source = str(module.get("source") or "custom")[:40]
    fallback_id = stable_base_module_id(title) if source == "base" else f"module-{uuid.uuid4().hex[:10]}"
    return {"id":str(module.get("id") or fallback_id)[:80],"title":title,"content":str(module.get("content") or "").strip()[:max_template_chars],"enabled":bool(module.get("enabled",True)),"locked":bool(module.get("locked",False)),"source":source}

def text_to_modules(text: str, source: str = "legacy", locked: bool = False, *,
                    max_template_chars: int) -> list[dict[str, Any]]:
    chunks=[chunk.strip() for chunk in _SECTION_RE.split(str(text or "")) if chunk.strip()]
    if not chunks and str(text or "").strip(): chunks=[str(text).strip()]
    result=[]
    for i,chunk in enumerate(chunks):
        first=chunk.splitlines()[0].strip(" =") if chunk.splitlines() else f"模块 {i+1}"
        title=(re.search(r"【([^】]+)】",first).group(1) if re.search(r"【([^】]+)】",first) else first)[:100]
        result.append(_module({"title":title,"content":chunk,"locked":locked,"source":source},i,
                          max_template_chars=max_template_chars))
    return result

def compile_modules(modules: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        str(item.get("content") or "")
        for item in modules
        if isinstance(item, dict) and item.get("enabled", True) and str(item.get("content") or "").strip()
    ).strip()

def base_template_modules(text: str, pipeline: str, *,
                          max_template_chars: int,
                          base_text_resolver: Callable[[str], str]) -> list[dict[str, Any]]:
    modules = text_to_modules(text, "base", locked=False,
                  max_template_chars=max_template_chars)
    for module in modules:
        module["locked"] = False
    return modules

def normalize_base_modules(modules: list[dict[str, Any]], base_text: str, pipeline: str, *,
                           max_template_chars: int,
                           canonical_modules: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """把方案里的基座模块与**现网代码基座**对齐（基座只读 + 缺失回插）。

    ## 为什么必须存在

    出厂方案若在 `trading_system` / `evolution_system` 上**一个 base 模块都不登记**，
    `apply_module_layout` 会走「无 base ⇒ 基座整段前置」的兜底：模型收到的提示词完好，
    但提示词工坊只列出方案自己那几段覆盖层（实测 1356 字符 vs 实发 9700 字符）——
    用户在工坊里既**看不到**也**改不动**真正的系统军规与 JSON 契约，且工坊的排序/启停
    对那几条管线**完全无效**。反过来，`source=="base"` 却存着陈旧快照时，工坊显示的是
    存档内容而运行期用的是现网基座（两条相反的静默路径）。

    本函数把「方案里的基座」变成**现网基座的显式登记**，让工坊所见即实发所见。

    ## 三条语义（都属"绝不静默"族）

    1. `source=="base"` 且标题命中现网基座 ⇒ **内容恒取现网基座**（基座只读），
       保留原 `id` 与 `enabled`、位置不变；
    2. `source=="base"` 但标题已不在现网基座（代码改了分节标题，实测
       `逐笔历史交易明细 (按时间排序)` → `逐笔历史交易明细`）⇒ **先按内容认亲**：
       内容与某个现网基座模块逐字相同的，就地认作那个基座模块（用现网标题/id，位置不变）；
       内容也对不上的（代码真删了该分节）才降级为 `legacy` 并**保留内容** ——
       用户库里那份不许无声消失。若这里直接降级 + 回插，同一段文本会**出现两遍**
       （实测 evolution_user 模板重复 34 字符分节）；
    3. 现网基座里尚未出现的标题 ⇒ 按**基座规范顺序稳定插入**（插到"其后第一个已存在的
       基座项"之前；其后没有基座项时插到"其前最后一个已存在的基座项"之后；都没有则置首）。
       绝不整体追加到末尾 —— 那会把自定义覆盖层挤到基座前面。

    ⚠️ 取不到基座文本（空串）或模块为空 ⇒ **原样返回**，绝不臆造（与
    `align_pipeline_sources` 同一纪律）。本函数**幂等**：归一后的结果再跑一遍不变。
    """
    if not isinstance(modules, list):
        return []
    items = [m for m in modules if isinstance(m, dict)]
    if not items or not str(base_text or "").strip():
        return items
    # `canonical_modules` 快路径：`apply_module_layout` / `pipeline_view` 已经算过同一份
    # 基座模块，直接复用可省掉每个交易周期两次 9.7k 字符的正则切分。
    canonical = canonical_modules if isinstance(canonical_modules, list) and canonical_modules else \
        text_to_modules(base_text, "base", locked=False, max_template_chars=max_template_chars)
    if not canonical:
        return items
    by_title = {str(m.get("title") or ""): m for m in canonical}
    by_content: dict[str, dict[str, Any]] = {}
    for module in canonical:
        by_content.setdefault(str(module.get("content") or ""), module)

    kept: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "")
        if str(item.get("source") or "") != "base":
            kept.append(item)
            continue
        live = by_title.get(title)
        if live is None:
            # 标题对不上：先按**内容**认亲（改标题不改正文的基座升级）
            live = by_content.get(str(item.get("content") or ""))
        if live is not None:
            stored_content = str(item.get("content") or "")
            # ⚠️ 基座模块的 `id` 一律用 `_base_module_id` 兜底，**不得**直接索引 `live["id"]`：
            # `canonical_modules` 是调用方传进来的（门面传 `base_template_modules` 的结果，
            # 但测试替身/未来调用点可能给的是**裸 dict**）。实测 `KeyError: 'id'` 让
            # `tests/core/test_apply_module_layout_main.py` 连红 12 例 —— 单元测试的价值所在。
            live_id = _base_module_id(live)
            if _carries_unique_slot(stored_content, str(live.get("content") or "")):
                # 插槽载体（如 {{trading_memory}}）：基座文本只是说明版，不得覆盖
                kept.append({**item, "source": "base",
                             "id": str(item.get("id") or live_id),
                             "enabled": bool(item.get("enabled", True))})
            else:
                kept.append({**live,
                             "id": str(item.get("id") or live_id),
                             "enabled": bool(item.get("enabled", True))})
        else:
            kept.append({**item, "source": "legacy",
                         "id": overlay_module_id(title, str(item.get("content") or ""))})

    out = list(kept)
    present = {str(m.get("title") or "") for m in out
               if str(m.get("source") or "") == "base"}

    for idx, live in enumerate(canonical):
        title = str(live.get("title") or "")
        if title in present:
            continue
        later = next((str(m.get("title") or "") for m in canonical[idx + 1:]
                      if str(m.get("title") or "") in present), None)
        if later is not None:
            pos = _base_index(out, later)
        else:
            earlier = next((str(m.get("title") or "") for m in reversed(canonical[:idx])
                            if str(m.get("title") or "") in present), None)
            pos = 0 if earlier is None else _base_index(out, earlier) + 1
        out.insert(pos, {**live, "id": _base_module_id(live), "enabled": True})
        present.add(title)
    return out


def demote_edited_base_modules(modules: list[dict[str, Any]], base_text: str, pipeline: str, *,
                               max_template_chars: int) -> list[dict[str, Any]]:
    """**保存路径**：把"被改过的基座模块"降级为 `legacy` 覆盖层，让改动真正生效。

    ## 为什么必须与 `normalize_base_modules` 配对

    读路径的归一会把 `source=="base"` 的内容**无条件治愈成现网基座**（基座只读）。
    于是若保存时不先把"用户改过的基座"降级，用户的改动会在下一次读到时被**静默抹掉** ——
    从"运行期丢弃"变成"读路径抹除"，问题只是换了个地方。

    故职责切分成两半，且**只有这两半合起来**才自洽：

    | 时机 | 函数 | 语义 |
    |---|---|---|
    | 保存 | 本函数 | 内容偏离基座（且不带独有插槽）⇒ 降级 `legacy`，改动落为覆盖层 |
    | 读取 | `normalize_base_modules` | `source=="base"` 一律等于现网基座，缺失则回插 |

    降级后，读路径会把它当普通覆盖层原位保留，同时把该分节的现网基座按规范顺序回插 ⇒
    实发 = 基座 + 你的覆盖层，工坊同时看到两者（覆盖层带「已改写」徽标）。

    ⚠️ 内容与基座**逐字相同**的不降级（照旧是 base，继续跟随发版更新）；
    带着基座没有的插槽的（如 `{{trading_memory}}`）也不降级 —— 它是插槽载体，
    基座里那份只是给编辑器看的说明文本。
    """
    if not isinstance(modules, list):
        return []
    items = [m for m in modules if isinstance(m, dict)]
    if not items or not str(base_text or "").strip():
        return items
    canonical = text_to_modules(base_text, "base", locked=False,
                                max_template_chars=max_template_chars)
    if not canonical:
        return items
    by_title = {str(m["title"]): m for m in canonical}
    out: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("source") or "") != "base":
            out.append(item)
            continue
        live = by_title.get(str(item.get("title") or ""))
        content = str(item.get("content") or "")
        if (live is not None
                and content != str(live.get("content") or "")
                and not _carries_unique_slot(content, str(live.get("content") or ""))):
            out.append({**item, "source": "legacy",
                        "id": overlay_module_id(str(item.get("title") or ""), content)})
        else:
            out.append(item)
    return out


def base_template_text(pipeline: str, *,
                       sources: dict[str, Any],
                       cache: dict[str, str]) -> str:
    """取代码基座文本；取不到时返回空串（调用方必须退化为"不改来源"，绝不臆造）。"""
    if pipeline in cache:
        return cache[pipeline]
    entry = sources.get(pipeline)
    if not entry:
        return ""
    attribute, candidates = entry
    module = next((sys.modules[name] for name in candidates if name in sys.modules), None)
    if module is None:
        for name in candidates:
            try:
                module = importlib.import_module(name)
                break
            except Exception:
                continue
    if module is None:
        return ""
    text = str(getattr(module, attribute, "") or "")
    if text:
        cache[pipeline] = text
    return text

def align_pipeline_sources(modules: list[dict[str, Any]], pipeline: str, *,
                           max_template_chars: int,
                           base_text_resolver: Callable[[str], str]) -> list[dict[str, Any]]:
    """把重建出来的模块与代码基座对齐（只按**逐字相同**判定，避免误认亲）。"""
    base_text = base_text_resolver(pipeline)
    if not base_text or not modules:
        return modules
    base_by_title = {m["title"]: m for m in text_to_modules(base_text, "base",
                                                max_template_chars=max_template_chars)}
    aligned: list[dict[str, Any]] = []
    for module in modules:
        candidate = base_by_title.get(str(module.get("title") or ""))
        if candidate and candidate.get("content") == module.get("content"):
            aligned.append({**candidate, "enabled": bool(module.get("enabled", True))})
        else:
            aligned.append(module)
    return aligned

def _inherit_module_tags(submitted: list[Any], stored: Any) -> list[Any]:
    """提交的模块缺 source/locked 时，从同 id（或同标题）的已存模块继承。

    审计 P1-2 同族：UI 的模块视图会把 base 模块的 locked 抹平；若再丢掉 source=base
    标签，`apply_module_layout` 就会认为「这条管线没有 base 模块」→ 把整段 base 前置，
    叠加已含同样内容的模块 = 提示词翻倍。显式传入的值永远优先。
    """
    if not isinstance(stored, list) or not stored:
        return submitted
    by_id = {str(m.get("id")): m for m in stored if isinstance(m, dict) and m.get("id")}
    by_title = {str(m.get("title")): m for m in stored if isinstance(m, dict) and m.get("title")}
    out: list[Any] = []
    for item in submitted:
        if not isinstance(item, dict):
            out.append(item)
            continue
        ref = by_id.get(str(item.get("id"))) or by_title.get(str(item.get("title")))
        if isinstance(ref, dict):
            merged = dict(item)
            for field in ("source", "locked"):
                if field not in item and field in ref:
                    merged[field] = ref[field]
            out.append(merged)
        else:
            out.append(item)
    return out

def pipeline_view(base: str, profile: dict[str, Any], pipeline: str, *,
                  max_template_chars: int,
                  base_text_resolver: Callable[[str], str]) -> list[dict[str, Any]]:
    base_modules = base_template_modules(base, pipeline,
                                        max_template_chars=max_template_chars,
                                        base_text_resolver=base_text_resolver)
    current = ((profile.get("pipelines") or {}).get(pipeline) if isinstance(profile.get("pipelines"), dict) else [])
    if isinstance(current, list) and current:
        # 基座归一（2026-09-30）：**预览侧**与渲染侧同款，否则工坊仍看不到基座。
        # 出厂方案若在 trading_system / evolution_system 上一个 base 模块都没登记，
        # 这里原本只返回方案自己那几段覆盖层（实测 1356 字符 vs 实发 9700 字符）⇒
        # 用户在工坊里既看不到也改不动真正的系统军规与 JSON 契约。
        # 归一后预览 = 渲染侧拿到的那份编排，"工坊所见 = 实发所见"。
        view = normalize_base_modules(copy.deepcopy(current), base, pipeline,
                                      max_template_chars=max_template_chars,
                                      canonical_modules=base_modules)
        for m in view:
            m["locked"] = False
        return view
    return base_modules + (text_to_modules(str(profile.get(pipeline) or ""), "custom",
                               max_template_chars=max_template_chars) if profile.get(pipeline) else [])

def append_layer(base: str, layer: str, label: str) -> str:
    layer = (layer or "").strip()
    return base if not layer else f"{base.rstrip()}\n\n======================= 【{label}】 =======================\n{layer}"
