r"""隔离沙箱必须**保住读语义** —— 不许把"已配置"悄悄变成"内置默认"。

## 这道门抓到的是什么（真实缺陷，已复现）

`tests/config_sandbox.isolate_config()` 把白名单模块里所有指向 `project/data/…` 的
**大写路径常量**重定向到它自己的临时目录。但它**只建目录、从不写文件** ——
于是隔离窗口里，任何"按 `PATH.exists()` 分支、或按配置值走不同分支"的生产代码
都会静默落到**内置默认值**。探针实测（`load_venue_pool("gate")`）：

| | `ROUTING_FILE` | exists | assets |
|---|---|---|---|
| 隔离前（会话沙箱夹具） | 会话沙箱 | True | 8 |
| 隔离后（修复前） | `<per-test>/data/venue_routing.json` | **False** | **0** |
| 隔离后（修复后） | 同上 | True | 8 |

`assets` 从 8 变 0 不是"少了个夹具"，而是**判定分支变了**：池为空 ⇒
`open_protected_position` 会走 `venue_pool`（"空池=不发单"）拒绝分支，
而不是它本该走的那条。同理，凭证库被重定向进空沙箱后
`_gate_execution_ready()` 变 False ⇒ gate 池被强制 `dry_run=True`
（"实盘姿态"被判成"本地演算"）—— 这正是本仓那批
`venue_dry_run != protective/leverage/sizing` 红例的形态。

## 本门钉两条

1. **夹具完整性**：会话沙箱提供的每个夹具文件，在按测试沙箱里必须存在且内容一致。
2. **"被清空"必须有据可查**：遍历白名单模块的大写路径常量，找出
   "生产里存在、但在沙箱里不存在"的那些 —— 每一个都必须登记在
   `DELIBERATE_EMPTY` 里并写明理由。**新出现一个静默清空点就会翻红。**

第 2 条是本门的价值所在：它把"隔离悄悄改语义"这件不可见的事，
变成一份必须逐条解释的清单。
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tests import session_sandbox_roots
from tests.config_sandbox import SANDBOXED_MODULES, isolate_config

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

#: ── 桶 A：**失败关闭**型 —— 空 = "没配置 / 没持仓 / 没在跑"，是安全的那一侧 ──
#: 这类**绝不能**继承生产值：继承了就等于让用例依赖你的真实持仓与凭证，
#: 甚至可能真去下单。为空是设计意图，不是遗漏。
FAIL_CLOSED_EMPTY: "dict[str, str]" = {
    ".astra_secret_key": "凭证库密钥。为空 ⇒ 解不开任何凭证 ⇒ 需要凭证的功能判「未就绪」（fail-closed）。",
    "astra_secrets.enc": "交易所/LLM 凭证密文。**绝不能**继承进沙箱 —— 否则用例可能真去调用交易所。",
    ".astra_gateway.lock": "网关单实例锁。为空 ⇒ 「未持有锁」= 未运行，是安全默认。",
    ".astra_gateway_heartbeat": "网关存活心跳。为空 ⇒ 「无心跳」= 未运行；继承生产心跳会让存活判据假绿。",
    "astra_gateway.pid": "网关进程号。为空 ⇒ 「没有进程」= 未运行。",
    "trading_ledger.json": "交易台账。为空 ⇒ 「无成交」；继承生产台账会让用例依赖你的真实成交记录。",
    "position_trackers.json": "持仓跟踪。为空 ⇒ 「无持仓」；这是用例该有的初态（它也是只读保护文件之一）。",
    "trading_state.json": "交易状态机快照。为空 ⇒ 冷启动状态；继承生产快照会让用例"
                             "依赖上一轮的运行残留。",
    "account_initial_state.json": "账户初始权益快照。为空 ⇒ 走内置默认，不泄露真实权益。",
}

#: ── 桶 B：**确定性默认**型 —— 代码有内置默认，我们**要**让用例跑在默认上 ──
#: 这些是"运维调参"类配置。继承生产值会让用例随**你的**线上调参而红/绿，
#: 违背本仓"把形状/常量抄成固定夹具，而不是每次去读生产"的既定政策。
DETERMINISTIC_DEFAULTS_EMPTY: "dict[str, str]" = {
    "prompt_library.json": "出厂基线。为空好让 `load_library()` 走 `_default()` 的确定性回退；"
                           "要断言线上模板的用例必须自带夹具。",
    "prompt_library.local.json": "用户改动落点（写入目标）。为空正是「未改过」的正确初态，"
                                 "且绝不能落回生产的 `.local.json`。",
    "llm_models.json": "模型注册表。为空 ⇒ 走内置模型清单，用例不随你的线上模型配置漂移。",
    "llm_providers.json": "供应商表。理由同上（其中还有你自己的网关域名）。",
    "council_config.json": "投委会席位配置。为空 ⇒ 内置席位；不随线上调参漂移。",
    "backup_methods.json": "备份作业清单。为空 ⇒ 内置默认作业；不随你的存储目标漂移。",
    "interceptor_plugins.json": "拦截器插件清单。为空 ⇒ 无自定义拦截器。",
    "venue_env_profile.json": "场所×环境档位映射。为空 ⇒ 内置映射；不随你在线上"
                                   "给各所配的环境档位漂移。",
}

#: ── 桶 C：**可再生记录**型 —— 缓存 / 记忆 / 报告，空了只表示"还没有历史" ──
REGENERABLE_EMPTY_REASON = (
    "由代码自身生成、可重建的缓存/记忆/报告产物；没有任何判定分支依赖其内容，"
    "为空只表示「还没有历史」，不改变任何决策走向。"
)
REGENERABLE_EMPTY = (
    "AI_TRADING_MEMORY.md",
    "ai_brain_decisions.json",
    "ai_brain_history.json",
    "ai_brain_last_prompt.txt",
    "dashboard_last_good.json",
    "factor_library_snapshot.json",
    "llm_failover_events.json",
    "news_sentiment.json",
    "policy_archives/index.json",
    "self_improvement_report.json",
    "snapshots.json",
    "structured_trading_memory.json",
)

#: ⚠️ 这些在**本机**生产里可能根本不存在（"用户不做就没有"的文件），
#: 因此允许它们出现在声明里、但不在实测"被清空"集合中。除此之外，
#: 声明必须与实测**严格对齐** —— 否则这份清单会变成一份与现实无关的说明文。
CONDITIONALLY_ABSENT: "dict[str, str]" = {
    "prompt_library.local.json":
        "用户改动落点：本机没有本地改动时它就不存在。一旦存在，沙箱里同样必须为空——"
        "否则用例会随你私人的提示词改动漂移。",
}

#: 三个桶的并集。本门要求"每一个被清空的配置都在、且仅在一个桶里"。
DELIBERATE_EMPTY: "dict[str, str]" = {
    **FAIL_CLOSED_EMPTY,
    **DETERMINISTIC_DEFAULTS_EMPTY,
    **{n: REGENERABLE_EMPTY_REASON for n in REGENERABLE_EMPTY},
}

#: 会话沙箱提供的夹具里，**必须**被按测试沙箱继承的那些（缺一个就会出现上表那种默认漂移）。
REQUIRED_INHERITED = ("venue_routing.json", "instrument_pool.json")


class FixturesAreInheritedTest(unittest.TestCase):
    def test_every_session_fixture_is_present_in_the_per_test_sandbox(self):
        roots = session_sandbox_roots()
        if not roots:
            self.skipTest("会话沙箱未启用（ASTRA_TESTS_ALLOW_REAL_DATA=1）")
        fixtures = {}
        for sroot in roots:
            for src in sroot.rglob("*"):
                if src.is_file():
                    fixtures[src.relative_to(sroot).as_posix()] = src
        self.assertTrue(fixtures, "会话沙箱里没有任何夹具 ⇒ 本判据失效")

        root = isolate_config(self)           # addCleanup 自动清理
        missing = []
        for rel, src in sorted(fixtures.items()):
            for candidate in (root / "data" / rel, root / rel):
                if candidate.exists():
                    break
            else:
                missing.append(rel)
        self.assertEqual(
            missing, [],
            "会话沙箱夹具没有被按测试沙箱继承 —— 隔离会把'已配置'变成'内置默认'：\n  "
            + "\n  ".join(missing))

    def test_the_semantic_anchor_is_actually_covered(self):
        """反向锚点：真正踩过坑的那两个夹具必须在夹具集合里，否则本门会"恰好在需要它的地方瞎掉"。"""
        roots = session_sandbox_roots()
        if not roots:
            self.skipTest("会话沙箱未启用")
        present = {p.name for sroot in roots for p in sroot.rglob("*") if p.is_file()}
        for name in REQUIRED_INHERITED:
            self.assertIn(name, present,
                          f"会话沙箱不再提供 {name} —— 本门的语义锚点失效，请重新评估")


class EmptiedConfigsMustBeDeclaredTest(unittest.TestCase):
    """★ 核心判据：把"隔离清空了哪些配置"变成一份必须逐条解释的清单。"""

    #: ⚠️ 扫描范围 = **沙箱自己声明的白名单**（`SANDBOXED_MODULES`），
    #    而不是"`sys.modules` 里所有命中前缀的模块"。后者会让清空集合随
    #    **测试收集顺序**变化 —— 本门第一版就是这样"单跑绿、全量红"的（实测）。
    #    同源之后，"被静默清空的配置"是一个**确定**集合。
    TARGETS = SANDBOXED_MODULES

    def _emptied(self) -> "list[str]":
        """返回"生产里存在、沙箱里不存在"的 data/ 相对路径集合。"""
        root = isolate_config(self)
        sandbox_data = (root / "data").resolve()
        import sys

        emptied = set()
        for name in self.TARGETS:
            module = sys.modules.get(name)
            if module is None:
                continue
            for key, value in list(vars(module).items()):
                if not key.isupper() or not isinstance(value, (str, Path)):
                    continue
                try:
                    rel = Path(value).resolve().relative_to(sandbox_data)
                except (ValueError, OSError):
                    continue                     # 没被重定向到这个沙箱
                if (sandbox_data / rel).exists():
                    continue                     # 沙箱里有内容
                if (DATA / rel).exists():
                    emptied.add(rel.as_posix())
        return sorted(emptied)

    def test_scan_is_not_vacuous(self):
        root = isolate_config(self)
        self.assertTrue((root / "data").is_dir(), "隔离沙箱没有 data/ 目录 ⇒ 判据失效")
        self.assertGreaterEqual(len(self.TARGETS), 15,
                                "沙箱白名单被削空了 —— 本门的扫描范围随之失效")

    def test_every_emptied_config_is_declared_with_a_reason(self):
        emptied = self._emptied()
        undeclared = [rel for rel in emptied if rel not in DELIBERATE_EMPTY]
        self.assertEqual(
            undeclared, [],
            "这些生产配置在隔离沙箱里被**静默清空**（读代码会静默落到内置默认）：\n  "
            + "\n  ".join(undeclared)
            + "\n（要么让沙箱继承它，要么连同理由登记进 DELIBERATE_EMPTY。"
            "本仓就因为这个坑出过一批 `venue_dry_run` 漂移红例。）")

    def test_declared_empty_list_is_not_stale(self):
        """反向断言：登记为"有意清空"的，必须**真的**在沙箱里是空的。

        否则这份清单会慢慢变成一份与现实无关的说明文。
        """
        emptied = self._emptied()
        stale = [rel for rel in DELIBERATE_EMPTY
                 if rel not in emptied and rel not in CONDITIONALLY_ABSENT]
        self.assertEqual(stale, [],
                         f"这些登记项现在已经不是「被清空」状态了，请从对应桶里删除：{stale}")

    def test_the_three_buckets_are_disjoint(self):
        """一个文件只能属于一个桶 —— 否则"为什么允许它为空"就有两种说法，必有一种是错的。"""
        names = (list(FAIL_CLOSED_EMPTY) + list(DETERMINISTIC_DEFAULTS_EMPTY)
                 + list(REGENERABLE_EMPTY))
        dupes = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(dupes, [], f"这些名字同时出现在多个桶里：{dupes}")

    def test_fail_closed_bucket_really_fails_closed(self):
        """桶 A 必须真的是"失败关闭"那一侧：空 ⇒ 凭证读不到 / 无持仓 / 未运行。

        负向保护：别把 `llm_models.json` 这种"调参类"塞进桶 A 混过去 ——
        它的空值会让代码落回**内置默认**而非判「未就绪」，性质完全不同。
        """
        for rel in FAIL_CLOSED_EMPTY:
            with self.subTest(rel=rel):
                self.assertTrue(
                    rel.startswith(".astra") or "secret" in rel or "ledger" in rel
                    or "position" in rel or "trading_state" in rel
                    or "account_initial" in rel
                    or rel.endswith((".pid", ".lock")) or "heartbeat" in rel,
                    f"{rel} 看着不像「失败关闭」型（空 ⇒ 未就绪/无持仓/未运行），"
                    "请改放 DETERMINISTIC_DEFAULTS_EMPTY 或 REGENERABLE_EMPTY")

    def test_every_declaration_explains_itself(self):
        for rel, reason in DELIBERATE_EMPTY.items():
            with self.subTest(rel=rel):
                self.assertGreater(len(reason), 20,
                                   f"{rel} 的理由太短 —— 必须说清为什么允许它在沙箱里消失")


if __name__ == "__main__":
    unittest.main()
