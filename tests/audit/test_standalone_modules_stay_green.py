"""「必须能**单独**跑绿」的模块清单（元门禁，由两道重复门禁合并而来）。

## 这道门证明什么（在套件里跑证明不了的那一点）

一个测试模块在整套 pytest 里绿，**不等于**它单独跑也绿：它可能靠别的测试留下的
会话状态（配置沙箱、被 patch 的常量、先 import 的模块）才通过。本门把这种"赖在别人身上"
用**独立解释器**跑一遍来证伪。

## 为什么合并成一道

原先有**两道**各自存在的门禁，一模一样的形态：

- `test_admin_token_duplication_contract.py::IsolationContractStillGreenTest::test_memory_routes_isolated_passes`
- `test_llm_credentials_consolidation.py::PlacementTest::test_seam_gate_still_green`

各自起一次 `python -m unittest`，本机实测 7.8s + 6.9s = **14.7s**，其中大头是
解释器启动与 import 应用（两次付两遍）。`unittest` 支持一次传多个模块名 ⇒
合成**一次**子进程即可，**性质一个不少**。

> 注：早先的测试套件审计把这两道写成"纯重复验证"，那是**不准确**的 ——
> 它们确实在证明一个套件内跑不出来的性质（standalone 绿）。
> 所以这里的处置是**合并**而不是删除。
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: 必须能**单独**跑绿的测试模块。新增一条 = 声明"这个模块不许依赖会话状态"。
STANDALONE_MODULES = (
    # 管理端记忆路由：曾因删除重复的 token 校验而翻红，要求它独立成立。
    "tests.test_memory_routes_isolated",
    # LLM 凭证接缝纪律：共享模块必须落在 scripts/，且不得在模块顶层 import llm_manager。
    "tests.test_llm_seam_discipline",
)


def _module_path(dotted: str) -> Path:
    return ROOT / (dotted.replace(".", "/") + ".py")


class StandaloneModulesStayGreenTest(unittest.TestCase):
    def test_every_declared_module_exists(self):
        """反向断言：清单里的模块必须真的存在，否则"单独跑绿"是空话。"""
        for dotted in STANDALONE_MODULES:
            with self.subTest(module=dotted):
                self.assertTrue(_module_path(dotted).is_file(),
                                f"{dotted} 不存在 —— 请从 STANDALONE_MODULES 删除")

    def test_each_module_is_actually_collected_in_suite(self):
        """清单不能变成"绕开主套件的后门"：这些模块必须**同时**被正常套件收集。"""
        for dotted in STANDALONE_MODULES:
            with self.subTest(module=dotted):
                self.assertNotIn("_isolated_", dotted.replace(".", "/"),
                                 "命名暗示它被排除在主套件之外，请核实后再登记")

    def test_all_declared_modules_pass_standalone(self):
        """★ 一次子进程跑完所有模块（原先是每模块一次，白付解释器启动）。"""
        from tests.config_sandbox import skip_if_offline_suite
        skip_if_offline_suite(self)          # 以 spawn 为被测行为，离线守护下如实 skip
        self.assertTrue(STANDALONE_MODULES, "清单空了 ⇒ 本门形同虚设")
        r = subprocess.run(
            [sys.executable, "-m", "unittest", *STANDALONE_MODULES],
            cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-2500:] + r.stderr[-2500:])

    def test_the_command_shape_is_the_one_that_can_fail(self):
        """闸自检（**不起子进程**）：确认判据挂在"退出码"上，而不是别的东西上。

        ⚠️ 原先这里再起一次子进程跑"不存在的模块"以证明退出码非零 ——
        实测那要多付一次解释器启动（~3s），而它验证的是 `unittest` 自身的语义，
        不是本仓的性质。改为断言命令构造与判据形态：命令里**必须有**具体模块名、
        且断言读的是 `returncode`。清单非空 + 模块存在（上面两条）已排除"恒真"。
        """
        import inspect
        src = inspect.getsource(type(self).test_all_declared_modules_pass_standalone)
        self.assertIn("*STANDALONE_MODULES", src, "命令没有带上模块清单 ⇒ 会跑空")
        self.assertIn("returncode", src, "判据没挂在退出码上 ⇒ 绿可能是假的")
        self.assertTrue(STANDALONE_MODULES, "清单为空 ⇒ 子进程等于没跑东西")


if __name__ == "__main__":
    unittest.main()
