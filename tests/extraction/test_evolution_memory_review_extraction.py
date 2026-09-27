r"""进化复盘"心法合并 + 发布"抽取对拍门（第一百零四刀）。

`scripts/self_improvement_engine.py::run_self_evolution`（179 行）里 33 行的
`if not preserve_existing_memory:` 块 → `scripts/evolution/memory_review.py::apply_memory_review`。
门面 782 → **761**，函数 179 → **157**。

## 为什么这块值得单独成门（它是**宪法级保护**）

- 基准心法不允许被进化输出物理删除（2026-09-10 事故换来的规则）：
  遗漏/试图删除的基准心法由宿主补回并计数（报告位 `baseline_memory_protected`）；
- 审计 P1-8c：被模型省略的**已学（非基准）**心法不再"静默消失"，改为停用存档；
- 发布失败 ⇒ 保留既有权威（`preserve_existing_memory = True`），不静默放宽。

## 三处 in-out（本门把规则钉死）

`constitution_readded` / `retired_lessons` / `preserve_existing_memory` 都只在
**该分支内**被赋值，分支跳过时保持调用方原值，块后又被报告消费 ——
只按"段内是否赋值"判必然绑定会误判，故一律 in-out（门面在 L636 就已预初始化）。
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "281bbb5"                  # 本刀动工前最后提交（第一百零三刀收口）
FACADE = ROOT / "scripts" / "self_improvement_engine.py"
MOD = ROOT / "scripts" / "evolution" / "memory_review.py"
OWNER = "run_self_evolution"
HELPER = "apply_memory_review"
SEG = 38                          # 基线语句下标


def _baseline_fn() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/self_improvement_engine.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return next(n for n in ast.parse(normalize(r.stdout)).body
                if isinstance(n, ast.FunctionDef) and n.name == OWNER)


def _impl() -> ast.FunctionDef:
    t = ast.parse(MOD.read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == HELPER)


def _call() -> ast.Call:
    for n in ast.walk(ast.parse(FACADE.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == HELPER:
            return n
    raise AssertionError("门面里找不到调用点")


def _kwargs(**over):
    """构造一次最小调用的全部关键字（helper 无默认值 ⇒ 必须全给）。"""
    base = dict(change_status="applied", constitution_readded=[], log_msg=lambda *a, **k: None,
                long_term_memory=[], memory_service=None, memory_snapshot={"version": 7, "lessons": []},
                merge_memory_with_constitution=lambda *a, **k: ([], []),
                preserve_existing_memory=True, retired_lessons=[], total_trades=0)
    base.update(over)
    return base


class EvolutionMemoryReviewTest(unittest.TestCase):
    def test_call_unpacks_three_in_out_values(self):
        call = _call()
        params = [a.arg for a in _impl().args.kwonlyargs]
        self.assertEqual(call.args, [])
        self.assertEqual([k.arg for k in call.keywords], params)
        for k in call.keywords:
            self.assertEqual(ast.unparse(k.value), k.arg)
        # 调用点必须是三目标解包（in-out 回传）
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == OWNER)
        tgt = [n.targets[0] for n in ast.walk(fn) if isinstance(n, ast.Assign)
               and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == HELPER]
        self.assertEqual(len(tgt), 1)
        names = [e.id for e in tgt[0].elts]
        self.assertEqual(names, ["constitution_readded", "preserve_existing_memory", "retired_lessons"])

    def test_non_definite_outputs_are_passed_in(self):
        """三处 in-out 必须在入参里（否则分支跳过时 UnboundLocalError）。"""
        params = {a.arg for a in _impl().args.kwonlyargs}
        for nm in ("constitution_readded", "preserve_existing_memory", "retired_lessons"):
            self.assertIn(nm, params, f"{nm} 必须 in-out")

    def test_no_undeclared_free_names(self):
        module = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = {n.name for n in module.body if isinstance(n, ast.FunctionDef)}
        fn = _impl()
        local = {a.arg for a in fn.args.kwonlyargs}
        for n in ast.walk(fn):
            if isinstance(n, ast.Lambda):
                local |= {a.arg for a in n.args.args}
            if isinstance(n, ast.comprehension):
                tg = n.target
                for e in (tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg]):
                    if isinstance(e, ast.Name):
                        local.add(e.id)
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                local.add(n.id)
            if isinstance(n, ast.ExceptHandler) and n.name:
                local.add(n.name)
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    local.add(a.asname or a.name.split(".")[0])
        reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        missing = sorted(reads - local - set(dir(builtins)) - mod_names)
        self.assertEqual(missing, [], f"解析不到: {missing}")

    # ---------- 行为例 ----------

    def test_skipped_branch_returns_inputs_untouched_and_never_publishes(self):
        from scripts.evolution.memory_review import apply_memory_review
        calls = []
        svc = type("S", (), {"publish_review": lambda *a, **k: calls.append(k)})()
        got = apply_memory_review(**_kwargs(preserve_existing_memory=True, memory_service=svc,
                                            constitution_readded=["keep"]))
        self.assertEqual(got, (["keep"], True, []), "跳过分支必须原样回传 in-out 值")
        self.assertEqual(calls, [], "跳过分支**不得**触碰记忆服务")

    def test_publish_success_clears_preserve_flag(self):
        from scripts.evolution.memory_review import apply_memory_review
        svc = type("S", (), {"publish_review": lambda *a, **k: "v8"})()
        got = apply_memory_review(**_kwargs(preserve_existing_memory=False, memory_service=svc,
                                            long_term_memory=["rule A"], total_trades=42))
        self.assertEqual(got[1], False, "发布成功 ⇒ preserve_existing_memory=False")

    def test_publish_failure_retains_authority_and_logs(self):
        from scripts.evolution.memory_review import apply_memory_review
        logs = []
        def _boom(*a, **k):
            raise RuntimeError("rejected")
        svc = type("S", (), {"publish_review": _boom})()
        got = apply_memory_review(**_kwargs(preserve_existing_memory=False, memory_service=svc,
                                            log_msg=lambda m: logs.append(m)))
        self.assertEqual(got[1], True, "发布失败 ⇒ 保留既有权威")
        self.assertTrue(any("retaining authority" in m for m in logs))

    def test_constitution_re_added_is_logged(self):
        from scripts.evolution.memory_review import apply_memory_review
        logs = []
        got = apply_memory_review(**_kwargs(
            preserve_existing_memory=False,
            memory_service=type("S", (), {"publish_review": lambda *a, **k: "v9"})(),
            long_term_memory=["rule A"],
            merge_memory_with_constitution=lambda *a, **k: (["rule A", "baseline"], ["baseline"]),
            log_msg=lambda m: logs.append(m)))
        self.assertEqual(got[0], ["baseline"], "补回的基准心法必须回传（供报告计数）")
        self.assertTrue(any("基准心法" in m for m in logs), "补回必须留痕")

    def test_dropped_non_baseline_lessons_are_archived_not_lost(self):
        """审计 P1-8c：模型漏述的已学心法 ⇒ 停用存档（回传 retired_lessons），不得静默消失。"""
        from scripts.evolution.memory_review import apply_memory_review
        logs = []
        snap = {"version": 3, "lessons": [
            {"rule_text": "kept", "enabled": True, "is_baseline": False},
            {"rule_text": "dropped", "enabled": True, "is_baseline": False},
            {"rule_text": "baseline-x", "enabled": True, "is_baseline": True},
            {"rule_text": "disabled", "enabled": False, "is_baseline": False},
        ]}
        got = apply_memory_review(**_kwargs(
            preserve_existing_memory=False,
            memory_service=type("S", (), {"publish_review": lambda *a, **k: "v10"})(),
            long_term_memory=["kept"], memory_snapshot=snap, log_msg=lambda m: logs.append(m),
            # ⚠️ 桩必须与真实协作方契约一致：`merge_memory_with_constitution` 返回的是
            # **合并后**的 safe 列表；"本轮已复述"的判定基于它，不是模型原始输出。
            merge_memory_with_constitution=lambda status, safe, lessons: (safe, [])))
        self.assertEqual(got[2], ["dropped"],
                         "只归档「启用中的非基准且本轮未复述」的心法（基准走补回、停用不重复记）")
        self.assertTrue(any("停用存档" in m for m in logs))

    def test_merge_receives_change_status_and_snapshot_lessons(self):
        from scripts.evolution.memory_review import apply_memory_review
        seen = {}
        def _merge(status, safe, lessons):
            seen.update(status=status, safe=list(safe), lessons=list(lessons))
            return safe, []
        snap = {"version": 1, "lessons": [{"rule_text": "b", "enabled": True, "is_baseline": True}]}
        apply_memory_review(**_kwargs(
            change_status="rolled_back", preserve_existing_memory=False, memory_snapshot=snap,
            long_term_memory=[{"rule_text": "from-dict"}, "plain"],
            memory_service=type("S", (), {"publish_review": lambda *a, **k: "v"})(),
            merge_memory_with_constitution=_merge))
        self.assertEqual(seen["status"], "rolled_back")
        self.assertEqual(seen["safe"], ["from-dict", "plain"], "对象/字符串两种心法都要压平成字符串")
        self.assertEqual(seen["lessons"], snap["lessons"])

if __name__ == "__main__":
    unittest.main()
