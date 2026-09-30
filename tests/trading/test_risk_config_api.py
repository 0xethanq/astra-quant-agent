"""后台「风控管理页」API 契约与安全回归测试。

覆盖：
- RBAC：未登录 401、普通 admin 只读、superadmin 可写；
- schema 与执行层 DEFAULTS 零漂移；
- 保存回写 .env（沙箱 ENV_FILE，绝不触碰生产配置与 os.environ 残留）；
- 越界 / 未知键 / 跨字段矛盾一律 400 并给出中文原因；
- 一键重置回退默认基线。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi.testclient import TestClient

import astra_backend.app as app_module
import astra_backend.settings_store as settings_store
from astra_backend.admin_auth import AdminAuthStore
from astra_backend.risk_config import GROUPS, schema
from scripts.risk_constants import DEFAULTS, RISK_ENV_KEYS

RISK_KEYS = set(RISK_ENV_KEYS)


_READ_SCOPE = None


def setUpModule():
    """显式声明生产读（第二百三十六刀）：
    本文件抄线上池/提示词库做对齐核对（如 `test_section_titles_match_live_layout`
    「线上布局是否与契约一致」）—— 有意的线上守卫。

    只读、不改；声明在此是为了把「依赖线上配置内容」从**静默**变成**可审计**
    （守卫见 `tests/__init__.py`；`ASTRA_TESTS_STRICT_READS=1` 下未声明的读会报错）。
    """
    global _READ_SCOPE
    from tests import allow_real_data_reads
    _READ_SCOPE = allow_real_data_reads()
    _READ_SCOPE.__enter__()


def tearDownModule():
    global _READ_SCOPE
    if _READ_SCOPE is not None:
        _READ_SCOPE.__exit__(None, None, None)
        _READ_SCOPE = None


class RiskConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_auth = app_module.admin_auth
        app_module.admin_auth = AdminAuthStore(Path(self.temp.name) / "admin.db")
        app_module.admin_auth.initialize_from_legacy("InitialAdmin123456")
        # 沙箱化 .env，防止测试写入生产配置
        self.original_env_file = settings_store.ENV_FILE
        settings_store.ENV_FILE = Path(self.temp.name) / ".env"
        # 隔离生产 .env 回灌：refresh_settings 会 load_dotenv(真实 .env)，
        # 用户可能已在后台应用风控套件，测试进程必须对生产配置无感
        import astra_backend.config as backend_config
        self.original_loader = backend_config.load_dotenv
        backend_config.load_dotenv = lambda path: None
        # 快照并清空风控环境变量，保证断言起点干净
        self.saved_env = {k: os.environ.pop(k, None) for k in RISK_KEYS}
        self.client = TestClient(app_module.app)

    def tearDown(self):
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import astra_backend.config as backend_config
        backend_config.load_dotenv = self.original_loader
        settings_store.ENV_FILE = self.original_env_file
        app_module.admin_auth = self.original_auth
        self.temp.cleanup()

    def login(self, username: str, password: str, role: str = "superadmin") -> dict[str, str]:
        if role == "admin":  # 创建一个普通管理员
            root = self.login("admin", "InitialAdmin123456")
            self.client.post("/api/v1/admin/users", headers=root,
                             json={"username": username, "password": password, "role": "admin"})
        response = self.client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return {"X-Astra-Session": response.json()["session_token"]}

    # ── RBAC ──
    def test_get_requires_auth(self):
        self.assertEqual(self.client.get("/api/v1/admin/risk").status_code, 401)

    def test_operator_can_read_but_not_write(self):
        operator = self.login("operator", "OperatorPassword123", role="admin")
        self.assertEqual(self.client.get("/api/v1/admin/risk", headers=operator).status_code, 200)
        denied = self.client.post("/api/v1/admin/risk", headers=operator,
                                  json={"values": {"ASTRA_TIME_STOP_HOURS": 6}})
        self.assertEqual(denied.status_code, 403)

    # ── schema 契约 ──
    def test_schema_matches_execution_defaults(self):
        headers = self.login("admin", "InitialAdmin123456")
        res = self.client.get("/api/v1/admin/risk", headers=headers)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        params = body["schema"]["params"]
        keys = {p["key"] for p in params}
        self.assertEqual(keys, set(DEFAULTS), "UI schema 与执行层 DEFAULTS 漂移")
        self.assertEqual({g["id"] for g in body["schema"]["groups"]}, {g["id"] for g in GROUPS})
        for p in params:
            self.assertEqual(p["default"], DEFAULTS[p["key"]])
            self.assertLessEqual(p["min"], p["default"])
            self.assertGreaterEqual(p["max"], p["default"])
        # 未配置时当前值 = 默认值
        for key, value in body["values"].items():
            self.assertAlmostEqual(value, float(DEFAULTS[key]), places=6)

    # ── 保存与回写 ──
    def test_update_persists_env_and_reflects_values(self):
        headers = self.login("admin", "InitialAdmin123456")
        res = self.client.post("/api/v1/admin/risk", headers=headers, json={"values": {
            "ASTRA_MAX_SAME_DIRECTION_POSITIONS": 5,
            "ASTRA_MAX_MARGIN_EQUITY_RATIO": 0.15,
            "ASTRA_TIME_STOP_HOURS": 12,
        }})
        self.assertEqual(res.status_code, 200, res.text)
        values = res.json()["values"]
        self.assertEqual(values["ASTRA_MAX_SAME_DIRECTION_POSITIONS"], 5)
        self.assertAlmostEqual(values["ASTRA_MAX_MARGIN_EQUITY_RATIO"], 0.15)
        self.assertAlmostEqual(values["ASTRA_TIME_STOP_HOURS"], 12.0)
        # .env 沙箱文件与进程环境同步
        env_text = settings_store.ENV_FILE.read_text(encoding="utf-8")
        self.assertIn("ASTRA_MAX_SAME_DIRECTION_POSITIONS=5", env_text)
        self.assertIn("ASTRA_MAX_MARGIN_EQUITY_RATIO=0.15", env_text)
        self.assertAlmostEqual(float(os.environ["ASTRA_TIME_STOP_HOURS"]), 12.0)
        # GET 再读一致
        again = self.client.get("/api/v1/admin/risk", headers=headers).json()["values"]
        self.assertEqual(again["ASTRA_MAX_SAME_DIRECTION_POSITIONS"], 5)

    def test_int_field_rounds_fractional_input(self):
        headers = self.login("admin", "InitialAdmin123456")
        res = self.client.post("/api/v1/admin/risk", headers=headers,
                               json={"values": {"ASTRA_STOP_COOLDOWN_MINUTES": 44.9}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["values"]["ASTRA_STOP_COOLDOWN_MINUTES"], 45)

    # ── 校验防线 ──
    def test_out_of_range_rejected_with_reason(self):
        headers = self.login("admin", "InitialAdmin123456")
        res = self.client.post("/api/v1/admin/risk", headers=headers,
                               json={"values": {"ASTRA_MAX_MARGIN_EQUITY_RATIO": 5.0}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("单笔保证金占比", res.json()["detail"])

    def test_unknown_key_rejected(self):
        headers = self.login("admin", "InitialAdmin123456")
        res = self.client.post("/api/v1/admin/risk", headers=headers,
                               json={"values": {"ASTRA_EVIL_SWITCH": 1}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("未知风控参数", res.json()["detail"])

    def test_cross_field_contradiction_rejected(self):
        headers = self.login("admin", "InitialAdmin123456")
        res = self.client.post("/api/v1/admin/risk", headers=headers, json={"values": {
            "ASTRA_MAX_CONCURRENT_POSITIONS": 3,
            "ASTRA_MAX_SAME_DIRECTION_POSITIONS": 6,
        }})
        self.assertEqual(res.status_code, 400)
        self.assertIn("同向持仓上限", res.json()["detail"])

    def test_empty_values_rejected(self):
        headers = self.login("admin", "InitialAdmin123456")
        self.assertEqual(self.client.post("/api/v1/admin/risk", headers=headers,
                                          json={"values": {}}).status_code, 400)

    # ── 重置 ──
    def test_reset_requires_confirmation_phrase(self):
        headers = self.login("admin", "InitialAdmin123456")
        self.client.post("/api/v1/admin/risk", headers=headers,
                         json={"values": {"ASTRA_MIN_RISK_REWARD": 2.5}})
        bad = self.client.post("/api/v1/admin/risk/reset", headers=headers,
                               json={"confirmation": "RESET"})
        self.assertEqual(bad.status_code, 400)
        good = self.client.post("/api/v1/admin/risk/reset", headers=headers,
                                json={"confirmation": "reset risk"})
        self.assertEqual(good.status_code, 200, good.text)
        self.assertAlmostEqual(good.json()["values"]["ASTRA_MIN_RISK_REWARD"], float(DEFAULTS["ASTRA_MIN_RISK_REWARD"]))
        self.assertNotIn("ASTRA_MIN_RISK_REWARD", os.environ)
        self.assertNotIn("ASTRA_MIN_RISK_REWARD", settings_store.ENV_FILE.read_text(encoding="utf-8"))

    # ── 优质预设套件 ──
    def test_suites_exposed_and_valid(self):
        headers = self.login("admin", "InitialAdmin123456")
        body = self.client.get("/api/v1/admin/risk", headers=headers).json()
        suites = body["suites"]
        self.assertEqual({s["id"] for s in suites}, {"conservative", "balanced", "aggressive"})
        from astra_backend.risk_config import normalize
        for s in suites:
            self.assertEqual(set(s["values"]), RISK_KEYS, f"套件 {s['id']} 未覆盖全部参数")
            normalize(s["values"])  # 越界会 raise

    def test_apply_suite_writes_env_and_explicit_override_wins(self):
        headers = self.login("admin", "InitialAdmin123456")
        res = self.client.post("/api/v1/admin/risk", headers=headers,
                               json={"suite_id": "conservative", "values": {"ASTRA_MAX_LEVERAGE": 2.0}})
        self.assertEqual(res.status_code, 200, res.text)
        values = res.json()["values"]
        self.assertEqual(values["ASTRA_MAX_SCALE_IN_COUNT"], 0)          # 稳健套件禁止加仓
        self.assertEqual(values["ASTRA_MIN_ENTRY_CONFIDENCE"], 85.0)     # 稳健套件高门禁
        self.assertEqual(values["ASTRA_MAX_LEVERAGE"], 2.0)              # 显式值覆盖套件值
        self.assertEqual(res.json()["applied_suite"], "conservative")
        self.assertIn("ASTRA_MAX_SCALE_IN_COUNT=0", settings_store.ENV_FILE.read_text(encoding="utf-8"))

    def test_unknown_suite_rejected(self):
        headers = self.login("admin", "InitialAdmin123456")
        res = self.client.post("/api/v1/admin/risk", headers=headers, json={"suite_id": "yolo"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("未知风控预设套件", res.json()["detail"])

    def test_pool_leverage_caps_synced_on_risk_update(self):
        """风控管理页保存杠杆区间（如 5~7x）时，标的池必须同步刷新 max_leverage（蓝筹 7x，动量 6x）。"""
        from unittest.mock import patch
        import scripts.instrument_pool as ip
        self.assertEqual(ip.derive_instrument_leverage_cap("tier_1_bluechip", 2.0, 5.0), 5)
        self.assertEqual(ip.derive_instrument_leverage_cap("tier_2_momentum", 2.0, 5.0), 3)
        self.assertEqual(ip.derive_instrument_leverage_cap("tier_1_bluechip", 5.0, 7.0), 7)
        self.assertEqual(ip.derive_instrument_leverage_cap("tier_2_momentum", 5.0, 7.0), 6)

        # ⚠️ 夹具不再抄**运行态**池文件（2026-09-30）：那份文件可被后台随时增删
        # （本次收敛 8 → 6 就把 SUI 删掉了，本用例当场 StopIteration）。改用出厂默认清单
        # —— 它有独立门禁（tests/audit/test_audit_config_p4_cleanup.py::DefaultRosterIntegrityTests）
        # 保证合法且含 BTC，是**稳定的**夹具来源。
        sandbox_pool = Path(self.temp.name) / "instrument_pool.json"
        sandbox_pool.write_text(json.dumps({"version": 1, "instruments": ip.DEFAULT_INSTRUMENTS},
                                           ensure_ascii=False, indent=2), encoding="utf-8")

        with patch.object(ip, "POOL_FILE", sandbox_pool):
            headers = self.login("admin", "InitialAdmin123456")
            res = self.client.post("/api/v1/admin/risk", headers=headers,
                                   json={"values": {"ASTRA_MIN_LEVERAGE": 5.0, "ASTRA_MAX_LEVERAGE": 7.0}})
            self.assertEqual(res.status_code, 200, res.text)

            pool = ip.load_instruments()
            btc = next(item for item in pool if item["instId"] == "BTC-USDT-SWAP")
            sol = next(item for item in pool if item["instId"] == "SOL-USDT-SWAP")
            self.assertEqual(btc["max_leverage"], 7)
            self.assertEqual(sol["max_leverage"], 6)

            res_reset = self.client.post("/api/v1/admin/risk/reset", headers=headers, json={"confirmation": "RESET RISK"})
            self.assertEqual(res_reset.status_code, 200)
            pool_reset = ip.load_instruments()
            btc_reset = next(item for item in pool_reset if item["instId"] == "BTC-USDT-SWAP")
            sol_reset = next(item for item in pool_reset if item["instId"] == "SOL-USDT-SWAP")
            self.assertEqual(btc_reset["max_leverage"], 5)
            self.assertEqual(sol_reset["max_leverage"], 3)


class PromptRiskContractTests(unittest.TestCase):
    """SYSTEM_PROMPT 与风控常量、线上布局的三重契约。

    v7.6.0 架构：System 宪法静态（快照安全），动态风控阈值全部由每轮
    construct_full_market_prompt 注入的【本周期风险预算】小节实时携带。
    """

    def setUp(self):
        import astra_backend.config as backend_config
        self.saved_env = {k: os.environ.pop(k, None) for k in RISK_KEYS}
        self.original_loader = backend_config.load_dotenv
        backend_config.load_dotenv = lambda path: None
        self._reload_clean()

    def tearDown(self):
        import astra_backend.config as backend_config
        backend_config.load_dotenv = self.original_loader
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._reload_clean()

    @staticmethod
    def _reload_clean():
        import importlib
        import risk_constants
        import ai_brain_trader
        importlib.reload(risk_constants)
        return importlib.reload(ai_brain_trader)

    def test_system_prompt_is_static_constitution(self):
        """代码所有的 System 文本必须**静态**（快照安全），动态口径一律只做"指向"。

        ⚠️ 2026-09-30 由提示词来源迁移重钉：代码里**只剩输出 JSON Schema**
        （`SYSTEM_PROMPT == READONLY_OUTPUT_SCHEMA`），角色/军规等正文搬进了
        `data/prompt_library.json`。故本用例拆成两层，两层都保留原意图：

        ① **代码所有的那一份**（= 宪法本体）必须逐字等于 `READONLY_OUTPUT_SCHEMA`，
           且不得内嵌任何具体风控数值字面量 —— 这是"宪法静态 = 快照安全"的本体，
           与提示词正文搬到哪无关；
        ② **口径指向**（"一切金额/盈亏比/置信度以【本周期风险预算】为准"）现在由
           JSON 方案模块承载，故改在 **effective** 提示词上断言。
        """
        import ai_brain_trader
        prompt = ai_brain_trader.SYSTEM_PROMPT
        # ① 宪法本体 = 只读 JSON Schema（逐字，静态）
        self.assertEqual(prompt, ai_brain_trader.READONLY_OUTPUT_SCHEMA,
                         "SYSTEM_PROMPT 必须逐字等于代码所有的只读 JSON Schema")
        self.assertIn("macro_assessment", prompt)
        for forbidden in ("同向持仓上限 3 笔", "同向持仓上限 4 笔", "杠杆不超过 5x",
                          "门禁为 80%", "绝对底线 2.0", "{same_dir}", "{rr_floor}",
                          "目标 R:R ≥ 2.2", "目标 R:R ≥ 2.5", "78% ~ 88%", "5%~10%"):
            self.assertNotIn(forbidden, prompt, f"宪法内嵌了动态风控字面量: {forbidden}")
        # ② 口径指向（JSON 方案模块）：金额/盈亏比/置信度一律指向运行期推导值
        from scripts.prompt_library import active_profile
        effective = ai_brain_trader.get_effective_system_prompt(active_profile())
        self.assertIn("以每轮用户消息【本周期风险预算】小节的实时推导值为准", effective,
                      "金额类参数必须指向运行期风险预算，不得内嵌固定值")
        self.assertIn("目标盈亏比不得低于执行层声明的硬底线", effective,
                      "盈亏比底线必须指向执行层声明值（不得写死具体数字）")
        self.assertIn("按置信度弹性取【本周期风险预算】常规区间", effective,
                      "保证金/杠杆必须按运行期风险预算区间弹性取值")

    def test_risk_budget_carries_live_values(self):
        abt = self._reload_clean()
        os.environ["ASTRA_MAX_SAME_DIRECTION_POSITIONS"] = "5"
        os.environ["ASTRA_MAX_SCALE_IN_COUNT"] = "0"
        try:
            abt = self._reload_clean()
            ctx = {}
            abt.construct_full_market_prompt([], "无", [], [], "2026-09-08 12:00:00",
                                             usdt_available=1000.0, runtime_context_out=ctx)
            budget = ctx["risk_budget"]
            self.assertIn("全系统同向持仓上限: 5 笔", budget)
            self.assertIn("金字塔加仓: 已禁用", budget)   # scale=0 自动切换禁令文案
            self.assertIn("盈亏比 R:R 硬底线: 2.0", budget)
            self.assertIn("新开仓最低置信度门禁: 80%", budget)
            self.assertIn("止损后同标的冷静期: 30 分钟", budget)
            # System 宪法保持逐字不变（快照安全）。
            # ★ 2026-09-30 重钉：`_SYSTEM_CORE` / `_PYRAMID` 已删除（那是提示词正文，
            # 已迁入 data/prompt_library.json）；代码所有的那一份现在就是只读 Schema。
            self.assertEqual(abt.SYSTEM_PROMPT, abt.READONLY_OUTPUT_SCHEMA)
        finally:
            del os.environ["ASTRA_MAX_SAME_DIRECTION_POSITIONS"]
            del os.environ["ASTRA_MAX_SCALE_IN_COUNT"]

    def test_rendered_system_prompt_carries_each_base_section_exactly_once(self):
        """出厂方案的渲染结果里，8 段代码基座必须**各出现一次**（2026-09-30 重写）。

        旧写法（`test_section_titles_match_live_layout`）把线上 `profiles["stable"]`
        的 base 模块与代码文本逐字比对。它抓到了真问题，但判据本身有两个缺陷：
        ① 硬编码 `stable` —— 该预设已被用户淘汰（换成单条「全形态波段策略(提示词样板)」），
           旧判据会直接 KeyError；
        ② 它只比"存下来的快照"，而**快照本身就是病根**：线上 stable 把 8 段基座抄进了
           方案里，其中 3 段是旧版文本 —— 于是代码新加的 `UPDATE_TP` 与
           `suggested_tp1_price` 被快照吃掉，模型**从未见过**这些新能力。

        新判据改为**渲染级**（与方案怎么存无关）：
        · 每段基座标题在渲染文本里恰好出现 1 次（缺失 = 掉段；重复 = 快照变第二事实源）；
        · 渲染两次逐字节一致（前缀缓存的前提）；
        · 方案里若仍带 `source=base` 的非空快照，其内容必须与代码逐字相同（不许留旧版）。
        """
        import json as _json
        import re
        import ai_brain_trader
        import prompt_library as pl
        live_library = ROOT / "data" / "prompt_library.json"
        if not live_library.exists():
            self.skipTest("无出厂基线（全新部署），跳过渲染对齐检查")
        lib = _json.loads(live_library.read_text(encoding="utf-8"))
        active = lib.get("active_profile_id")
        profiles = lib.get("profiles") or {}
        self.assertIn(active, profiles, f"出厂基线的 active 方案 {active} 不在 profiles 里")

        code_map = {m["title"]: m["content"]
                    for m in pl.text_to_modules(ai_brain_trader.SYSTEM_PROMPT, "base")}
        for pid, prof in profiles.items():
            with self.subTest(profile=pid):
                rendered = pl.apply_module_layout(
                    ai_brain_trader.SYSTEM_PROMPT, prof, "trading_system", f"{pid} 渲染")
                for title in code_map:
                    hits = len(re.findall(r"==== 【" + re.escape(title) + r"】 ====", rendered))
                    self.assertEqual(hits, 1,
                                     f"{pid}: 基座段「{title}」在渲染里出现 {hits} 次"
                                     f"（0=掉段，>1=快照成了第二事实源）")
                for module in (prof.get("pipelines") or {}).get("trading_system", []):
                    if module.get("source") != "base":
                        continue
                    stored = str(module.get("content") or "")
                    live_text = code_map.get(str(module.get("title") or ""))
                    if live_text is not None and stored:
                        self.assertEqual(stored, live_text,
                                         f"{pid}: 方案里存的基座快照与代码漂移（{module.get('title')}）"
                                         f" ⇒ 模型会收到过期硬约束")

    def test_rendered_system_prompt_is_byte_stable(self):
        """渲染两次必须逐字节一致 —— 前缀缓存与"看到的=收到的"都依赖这一点。

        用**代码出厂预设**渲染（本用例所在模块的方案库被沙箱化，不读线上文件）。
        """
        import copy
        import ai_brain_trader
        import prompt_library as pl
        prof = pl._clean_profile(copy.deepcopy(pl.PRESETS["allpattern_swing"]), "allpattern_swing")
        first = pl.apply_module_layout(ai_brain_trader.SYSTEM_PROMPT, prof, "trading_system", "t")
        second = pl.apply_module_layout(ai_brain_trader.SYSTEM_PROMPT, prof, "trading_system", "t")
        self.assertEqual(first, second)
        # 代码新加的能力不得再被快照吃掉（本次事故的指纹）
        self.assertIn("UPDATE_TP", first)
        self.assertIn("suggested_tp1_price", first)


class RiskExecutionWiringTests(unittest.TestCase):
    """执行层必须真的引用单一事实源，防止页面改了参数但代码没接线。"""

    def test_trader_sources_use_shared_constants(self):
        root = Path(__file__).resolve().parents[2]
        # 领域定位：下面 forbidden 是**负向**断言。单文件定位在搬家后会静默空转
        # （写死的风控常量跟着搬进子包，门面里查不到 → 永远通过）。
        from tests.source_scan import combined
        trader = combined("scripts/ai_factor_trader.py", pkg_name="trader")
        self.assertIn("from risk_constants import", trader)
        for forbidden in ('os.getenv("ASTRA_MAX_DAILY_LOSS_USDT"', 'MAX_SAME_DIRECTION_POSITIONS = 3',
                          "rem_sec = 1800", "hold_duration_sec > 28800", "ai_conf >= 80.0"):
            self.assertNotIn(forbidden, trader, f"执行层仍存在写死风控: {forbidden}")
        order_risk = (root / "scripts" / "order_risk.py").read_text(encoding="utf-8")
        self.assertIn("MIN_RISK_REWARD_RATIO", order_risk)
        brain = (root / "scripts" / "ai_brain_trader.py").read_text(encoding="utf-8")
        self.assertIn("from risk_constants import", brain)


if __name__ == "__main__":
    unittest.main()
