"""台账合并去重（`scripts/ledger/` 部件，从 `sync_full_ledger.py` 纯计算段搬出）。

`build_lifecycle_ledger()` 里"聚合去重合并"那 19 行 —— 见函数 docstring。
**零注入面**：不读任何模块级名字（无 `patch.object` 接缝风险），
所有输入都是显式入参，是 `ledger/` 包约定里最干净的一类。
"""

from __future__ import annotations


def merge_lifecycle_trades(*,
        old_trades,
        trades_lifecycle):
    """把旧台账与本轮新成交**合并去重**（纯计算，无 IO）。

    合并顺序与原实现一致：旧台账 → （D8 迁移清理）→ 本轮生命周期，
    后来的同 id 覆盖先前的。

    ## D8 迁移去重（原注释照录）

    去重键由 `u_ts` 换为 `posId` 后首跑，同一笔持仓的新旧行 id 不同会并存双计。
    对 okx 历史行按 `(venue, inst, open_time, close_time)` 稳定签名撞键 ——
    旧键行让位于本轮再生成的新键行；**窗口外无法再生的旧行一律不动**（防迁移误删）。
    这条"不动"是安全边界，行为例专门钉它。

    段体 **AST 逐字**（对拍门 `tests/extraction/test_ledger_merge_extraction.py`）。
    """
    trades_map = {}
    for t in old_trades:
        if t.get("id"):
            trades_map[t["id"]] = t

    # 审计 D8 迁移：去重键由 u_ts 换为 posId 后首跑，同一笔持仓的新旧行 id 不同
    # 会并存双计。对 okx 历史行按 (venue, inst, open_time, close_time) 稳定签名
    # 撞键——旧键行让位于本轮再生成的新键行；窗口外无法再生的旧行一律不动（防迁移误删）。
    def _sig(t):
        return (str(t.get("venue") or ""), str(t.get("inst") or ""),
                str(t.get("open_time") or ""), str(t.get("close_time") or ""))
    _new_sigs = {_sig(t) for t in trades_lifecycle}
    for _oid in [k for k, v in trades_map.items()
                 if str(k).startswith("pos_hist_") and isinstance(v, dict) and _sig(v) in _new_sigs]:
        trades_map.pop(_oid)

    for t in trades_lifecycle:
        if t.get("id"):
            trades_map[t["id"]] = t
    return trades_map
