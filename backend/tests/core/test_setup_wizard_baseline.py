"""开箱向导的初始本金基线（2026-11-17）。

## 守什么

`/api/v1/system/setup/apply` 原先只写 OKX / LLM / 风控 env，**从不碰本金基线**，
于是全新安装永远落回 `DEFAULT_CAPITAL = 10_000`，用户看到的累计盈亏/ROI
只是“当前权益减默认 10,000”，并非真实投入。

本文件钉住：

1. `SystemSetupRequest.initial_capital` 可选且必须 > 0；
2. 只有显式传入时才调用 `update_initial_capital`（留空不覆盖现有值）；
3. 向导前端确实把该字段送进 setup apply；
4. 中英文案都包含基线设置，且四步引导提到它。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

from astra_backend.routers import system as A
from astra_backend.schemas import SystemSetupRequest

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
MODAL = ROOT / "frontend" / "src" / "components" / "dashboard" / "QuickSetupModal.vue"
ZH = ROOT / "frontend" / "src" / "locales" / "zh" / "dash" / "firstRun.ts"
EN = ROOT / "frontend" / "src" / "locales" / "en" / "dash" / "firstRun.ts"


class SetupApplyBaselineTest(unittest.TestCase):
    def _apply(self, **overrides):
        payload = SystemSetupRequest(llm_model="", **overrides)
        with mock.patch.object(A, "admin_auth") as auth, \
                mock.patch.object(A, "update_env"), \
                mock.patch.object(A, "refresh_settings"), \
                mock.patch.object(A, "audit_record"), \
                mock.patch.object(A, "update_initial_capital") as update:
            auth.has_users.return_value = False
            result = A.system_setup_apply(payload)
        return result, update

    def test_explicit_capital_is_written_once(self):
        result, update = self._apply(initial_capital=4915.89)
        self.assertTrue(result["ok"])
        update.assert_called_once_with(4915.89)

    def test_blank_capital_keeps_the_existing_baseline(self):
        result, update = self._apply()
        self.assertTrue(result["ok"])
        update.assert_not_called()

    def test_zero_or_negative_capital_is_rejected_before_any_write(self):
        for bad in (0, -1, -0.01):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    SystemSetupRequest(initial_capital=bad)


class WizardWiringTest(unittest.TestCase):
    def test_modal_collects_and_posts_initial_capital(self):
        src = MODAL.read_text(encoding="utf-8")
        self.assertIn("initialCapital", src)
        self.assertIn("initial_capital: parsedInitialCapital.value", src)
        self.assertIn('id="wiz-initial-capital"', src)

    def test_locales_expose_the_baseline_field_and_hint(self):
        for path in (ZH, EN):
            src = path.read_text(encoding="utf-8")
            for key in ("capitalBaseline:", "capitalBaselinePlaceholder:",
                        "capitalBaselineHint:", "capitalBaselineInvalid:"):
                self.assertIn(key, src, f"{path.name} 缺少 {key}")

    def test_first_run_steps_mention_the_baseline(self):
        zh = ZH.read_text(encoding="utf-8")
        en = EN.read_text(encoding="utf-8")
        self.assertIn("初始本金基线", zh)
        self.assertIn("initial capital baseline", en)


class SchemaAndRouterWiringTest(unittest.TestCase):
    def test_request_schema_has_optional_positive_capital(self):
        field = SystemSetupRequest.model_fields["initial_capital"]
        self.assertIsNone(field.default, "默认必须是 None（留空不覆盖）")

    def test_router_calls_the_baseline_writer(self):
        src = (BACKEND / "astra_backend" / "routers" / "system.py").read_text(encoding="utf-8")
        self.assertIn("update_initial_capital(float(payload.initial_capital))", src)


if __name__ == "__main__":
    unittest.main()
