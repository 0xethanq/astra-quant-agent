# tests/ 目录说明（第一百三十八刀按域整理）

## 布局

| 目录 | 文件数 | 内容 |
|---|---:|---|
| `extraction/` | 75 | 结构优化各刀的对拍门（段体 AST 逐字、调用点传参、行为例） |
| `venues/` | 24 | 三所适配器 / 行情 / 标的池 / 下单链路 |
| `llm/` | 24 | LLM 配置与传输 / 投委会 / 提示词 / 自进化 / 因子 |
| `ops/` | 23 | 管理端 / 备份 / 环境与凭证 / 定时与守护 / 策略快照 / 台账 |
| `audit/` | 21 | 审计批次、卫生检查、外泄与隔离、文档/基线数字门 |
| `core/` | 21 | 通用与跨域（时间契约、配置沙箱、控制面、加解密等） |
| `ui/` | 11 | 看板载荷 / 图表前端契约 |
| `trading/` | 10 | 交易员 / 订单 / 风控 / 持仓 / 回测 |
| 根目录 | 3 个测试 + 辅助 | 见下 |

## 规格（新增文件请遵守）

1. **域目录名不得与标准库或仓库顶层包重名** —— 由 `audit/test_test_tree_layout.py` 钉死。
   踩过两次：`tests/platform/` 遮蔽标准库 `platform`（pydantic 连锁崩、报错却是
   `cannot import name 'BaseModel'`）；`tests/dashboard/` 因为是常规包，抢在仓库根
   `dashboard/` 之前被 import，导致 `import astra_backend.dashboard_cache` 失败。
2. **移到子目录后必须给 `Path(__file__)` 路径"加一层"**，三种等价写法都要改：
   `parents[1]` → `parents[2]`、`.parent.parent` → `.parent.parent.parent`、
   `Path(__file__).resolve().parent / ...` → 多加一个 `.parent`。
   （`ROOT = Path(__file__).resolve().parents[2]` 是仓库根，`tests/data/` 走
   `ROOT / "tests" / "data"`。）
3. **内嵌脚本模板例外**：若测试把一段脚本**写成字符串**再落到别处执行
   （如 `extraction/test_dashboard_bills_extraction.py` 的 `_CYCLE_PROBE`，
   它落到 `tests/` 根），模板里的 `__file__` 深度要按**落地位置**算，不要跟着测试文件改。
4. **留在根目录的东西**：
   - 被别的测试按模块名引用的 3 个文件（`test_memory_routes_isolated.py`、
     `test_llm_seam_discipline.py`、`test_gate_execution_router.py`）；
   - 辅助模块 `config_sandbox.py`（配置沙箱）、`source_scan.py`（源码扫描）、
     `risk_test_env.py`、`okx_algo_http_fixture.py`、`_free_names_scan.py`、`__init__.py`；
   - `offline_suite.py`（离线/无外泄套件）、`data/`（黄金样本）。
5. **跑法不变**：`python -m unittest discover -s tests -t .`（顶层目录仍是仓库根，
   子目录都带 `__init__.py`）；离线套件 `python tests/offline_suite.py`。
