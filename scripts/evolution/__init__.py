"""自进化领域的可复用实现（结构优化阶段 4·B3 第四十二刀起）。

门面仍是单文件 `scripts/self_improvement_engine.py`
（`run_self_evolution` / `call_llm_evolution_review` / `compose_evolution_prompts` /
`EVOLUTION_SYSTEM_PROMPT` / 记忆合并 / 文件与锁等）。
本子包承接从那个文件里抽出的**成块领域逻辑**。

## 模块清单

| 模块 | 职责 | 注入面 |
|---|---|---|
| `observability.py` | 数理快照**可观测性**审计：字段表 / 门槛 / 逐单分类 / 剔除 null / 汇总 / 渲染摘要；2026-10 起汇总同时给出**证据链覆盖**计数（开仓现场快照数 ＋ 离场原因 mechanism/inferred/未标记三档） | 无（纯计算；仅依赖 `astra_backend.time_utils.parse_beijing`） |
| `exit_quality.py` | **离场质量分析**（方向 3）：逐行折算 MFE/MAE 与实收 ⇒ `give_back_r`（吐回多少）/ `exit_efficiency_pct`（兑现率）；机制化出场表（**只认机制确认**）＋ 时间止损有效性 ＋ 逐标的离场矩阵；每张表带样本量与"不可据以断言"清单 | 零副作用、零全局读取（纯计算） |
| `lesson_health.py` | **心法健康度生命周期**（方向 4）：`extract_cohort`（从正文析出适用人群：标的/方向/离场机制）＋ `score_lesson_against_trades`（按人群胜率与期望值打分，**按样本量向 50 回归**，样本不足返回 `None`）＋ `rank_key`/`rank_lessons`（基准→健康分→新旧）＋ `decide_archive`（低分**且**样本达标**且**非基准才归档，**绝不删除**）＋ `refresh_lesson_health`（纯函数，不写盘） | 零副作用、零全局读取（纯计算） |
| `memory_review.py` | `apply_memory_review(...)` —— 复盘心法合并（**2026-10 起只做追加与去重**；原"宪法级保护/基准心法补回"已随基准机制整体拆除）+ 已学心法漏述即停用存档（审计 P1-8c）+ 发布到记忆服务（失败即保留既有权威） | `log_msg` / `merge_lesson_texts` 传入；`preserve_existing_memory`/`retired_lessons` 两处 **in-out** |
| `review_context.py` | `summarize_closed_trades(...)` 平仓统计 + 可观测性摘要（8 输出）；`build_host_constitution(...)` **宿主宪章**（Code is Law 代码层硬约束，profile 不可覆盖）；`parse_review_json(...)` 复盘回复解析（只裁围栏、失败必上抛）；`repair_json_object(...)` **容错 JSON 修复**（裸控制字符/尾逗号/前后散文，修不动抛原错；与交易主脑 `brain/dispatch.py` 共用同一份） —— 皆为纯函数 | 依赖全部显式入参（零模块全局） |
| `report.py` | `build_evolution_report(...)` —— 自进化**报告载荷**形状（13 入参 / 1 输出）：**20 个键即前端契约**（含 `insights`/`diagnosis_insights` 同对象、`retired_count` 等计数快照、`llm_error` 透出上游失败；2026-10 增 `evidence_coverage_pct`/`exit_cause_coverage_pct`/`evidence_gap_reasons` **由 `snapshot_audit` 内部派生**；同月**移除 `baseline_memory_protected` 键与 `constitution_readded` 入参**）＋ `derive_evidence_coverage(...)` 证据链健康度派生 | 零副作用、零全局读取 |

## 约定

1. **门面必须继续提供被搬走的名字**（`from scripts.evolution.observability import …`
   在门面里**再导出**）。外部（`astra_backend/routers/strategy/prompts.py`、
   `scripts/prompt_library.py`）与既有测试都按门面解析这些名字。
2. **`SNAPSHOT_MAX_STALE_SECONDS` / `SIDE_ALIASES` 留在门面** ——
   它们属于 **join 侧**（`_match_snapshot` 的 6 小时窗口与多空别名），
   与"可观测性判定"是两件事，**勿**顺手一起搬。
3. `DYNAMICS_OBSERVED_MIN` 必须**由字段表推导**，不得写死
   （`17 × 0.85 → 14 + 1 = 15`）。
"""
