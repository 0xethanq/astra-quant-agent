"""快讯信号处理的纯判断逻辑（结构优化阶段 4·B3 第四十四刀起）。

门面仍是单文件 `scripts/news_sentiment_harvester.py`（`fetch_*` 取数、
`trigger_circuit_breaker` 落盘、`fetch_and_analyze_news_sentiment` 编排）。
本子包承接从那个文件里抽出的**纯判断**逻辑。

## 模块清单

| 模块 | 职责 | 注入面 |
|---|---|---|
| `importance.py` | 快讯重要度分级（`_classify_importance`）+ 币种识别（`_extract_coins`） | 无（纯文本进、纯值出；不读任何模块常量） |
| `selection.py` | 快讯智能分类与提示词加权选择（`select_weighted_news` / `format_news_for_prompt`） | 无（纯判断与格式化进出） |

## 约定

1. **只抽纯函数**。门面用 `patch.object(nh, "NEWS_CACHE_FILE", ...)` 之类做接缝注入，
   把**读路径常量的函数**搬进子模块会让补丁静默失效（读真实路径）——
   正是 `tests/test_llm_seam_discipline.py` 警告的事故类型。
2. `_classify_importance` / `_extract_coins` **不得** import `os` / `pathlib` / `json`。
3. 门面**再导出**这两个名字（既有测试按门面名直接调用）。
"""
