"""台账（lifecycle ledger）构建的可复用部件。

`scripts/sync_full_ledger.py` 是公开门面（`scripts.sync_full_ledger` 与
`sync_full_ledger` 两种导入路径都被测试使用），本子包承载它的**实现细节**。

## 为什么不直接改门面结构

门面里的 `build_lifecycle_ledger()` 长 330 行，但它是**唯一入口**：读初始状态、
读旧台账、拉 OKX 历史、合并、去重、原子落盘。它不适合整体搬走（会牵动
`__main__` 与全部测试接缝），适合的是把其中**自成一体的计算段**逐个抽出来。

## 抽取约定（与 scripts/trader、scripts/brain 一致）

- 需要时间/工具函数时**由调用方传入**，不在 import 期绑定 ——
  门面里的模块级名字会被测试 `patch.object`，import 期绑定会绕过接缝。
- 只搬"纯计算"，不搬副作用：文件读写、`print`、全局状态更新留在门面。

## 模块清单

| 模块 | 内容 | 注入面 |
|---|---|---|
| `okx_history.py` | `build_okx_trade(...)` —— 把 OKX 成交/账单原始行折成台账行 | 无（纯转换） |
| `merge.py` | `merge_lifecycle_trades(...)` —— 旧台账 + 本轮新成交的**合并去重**（含审计 D8 迁移：撞键旧键行让位、窗口外旧行不动） | **零注入面**（纯入参） |
| `holdings.py` | `judge_position_side(...)`（**审计 C8** 方向判定：net-mode 按符号回退，不可判即"未知"）/ `format_holding_duration(...)`（时长格式化；**本刀修掉 naive/aware 失配**） —— 本体 `_holding_row` 因既有 pin 仍留门面 | `datetime` 调用方注入 |
| `notify.py` | `notify_newly_closed_trades(...)` —— 台账落盘后把**新平仓**逐条推给 QQ （`id` 不在本轮既有已平集合 且 `status=="closed"`）；`qq_notifier` 惰性导入，失败只告警绝不影响落盘 | 依赖由参数传入（唯一有外部副作用的 ledger 部件，故单列） |

## 待办（如实记录）

`build_lifecycle_ledger()` 本身仍有 200+ 行（OKX 取数编排 + 合并去重 + 原子落盘），
**尚未拆分**。它的难点是"取数编排"与"落盘副作用"交织，切它需要先明确
哪一段是纯计算（可搬）哪一段是 I/O（留门面）。
"""
