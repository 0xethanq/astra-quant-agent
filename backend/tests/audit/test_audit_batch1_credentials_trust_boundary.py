"""批1 凭证与信任边界止血（审计 2026-09-13）的回归钉。

覆盖：
- A1 admin_runtime 不再直发 get_active_llm_runtime() 整包（明文 api_key/base_url 必须消失）
- A2 通知掩码回写环：mask()/mask_url() 产物回传一律视为「未改动」，绝不落盘（toggle+PUT 双路）
- A2 补充：PUT 整页保存把密钥字段分流加密库，不再明文进 update_env
- A3 备份强制排除表挡住「嵌在业务 JSON 里的凭证」与嵌套备份
- A6 telegram 通道补外呼校验；异常文本脱敏 bot token
- B  /api/v1/status 匿名面不再吐 position_trackers / last_decisions
- C  secrets 库损坏≠空库：写路径拒写保全现场 + .bak；读路径仍 fail-soft
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astra_backend.settings_store import mask, mask_url, is_masked  # noqa: E402
import astra_backend.routers.system as sysmod  # noqa: E402
import astra_backend.routers.gateway as gwmod  # noqa: E402
# 第九十七刀：gateway 拆包 ⇒ patch/调用必须落到**归属子模块**
from astra_backend.routers.gateway import channels as gw_channels  # noqa: E402
from astra_backend.routers.gateway import notifications as gw_notifications  # noqa: E402
import astra_gateway.secrets as gws  # noqa: E402
from astra_backend.schemas import ChannelToggleRequest, NotificationConfigUpdate  # noqa: E402
import astra_backend.notifications as notif  # noqa: E402


def _raw(fn):
    return getattr(fn, "__wrapped__", fn)


class TestA1AdminRuntimeWhitelist(unittest.TestCase):
    def _call(self, runtime_result=None, runtime_exc=None):
        def _get():
            if runtime_exc:
                raise runtime_exc
            return runtime_result
        with patch.object(sysmod, "require_admin_header", return_value={"username": "t"}), \
             patch.object(sysmod, "refresh_settings"), \
             patch.object(sysmod, "get_active_llm_runtime", _get), \
             patch.object(sysmod, "read_json", return_value={}), \
             patch.object(sysmod, "script_state", return_value={"name": "x", "exists": False}):
            return _raw(sysmod.admin_runtime)()

    def test_runtime_handler_strips_credentials(self):
        payload = self._call(runtime_result={
            "model": "gemini-3.8-flash", "name": "主脑", "provider_name": "gp",
            "provider_id": "p1", "base_url": "https://evil.example/see/me",
            "api_key": "sk-PLAINTEXT-SECRET-123", "api_format": "openai_chat",
            "reasoning_effort": "high",
        })
        rt = payload["llm_runtime"]
        self.assertNotIn("api_key", rt)
        self.assertNotIn("base_url", rt)
        self.assertEqual(rt["model"], "gemini-3.8-flash")
        self.assertNotIn("sk-PLAINTEXT-SECRET-123", json.dumps(payload, ensure_ascii=False))

    def test_runtime_handler_survives_llm_misconfig(self):
        payload = self._call(runtime_exc=RuntimeError("base_url 未配置"))
        self.assertIn("model", payload["llm_runtime"])  # 不再 500


class TestA2MaskedWriteback(unittest.TestCase):
    def setUp(self) -> None:
        # 批1 P0-2 配套：toggle_channel 会调 channels.update_env（真实 settings_store），
        # 此前直接把测试 URL 写进生产 .env（tests/__init__ 的写闸现已拦下）→ 显式沙箱化。
        import astra_backend.settings_store as settings_store
        self._env_tmp = tempfile.TemporaryDirectory(prefix="astra-gwtest-")
        self.addCleanup(self._env_tmp.cleanup)
        self._env_patcher = patch.object(settings_store, "ENV_FILE",
                                        Path(self._env_tmp.name) / ".env")
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)

    def test_is_masked_detects_both_shapes(self):
        self.assertTrue(is_masked(mask("abcdefg1234567")))
        self.assertTrue(is_masked(mask_url("https://x.example/hook?key=supersecret9")))
        self.assertTrue(is_masked("********"))
        self.assertTrue(is_masked("****"))
        self.assertFalse(is_masked("https://oapi.example/hook?key=REAL"))
        self.assertFalse(is_masked(""))
        self.assertFalse(is_masked("short*star"))

    def _toggle(self, req, channel="webhook"):
        saved: dict = {}
        removed: list = []
        with patch.object(gw_channels, "require_admin_header", return_value={"username": "t"}), \
             patch.object(gw_channels, "refresh_settings"), \
             patch.object(gws, "save_secrets", side_effect=lambda v: saved.update(v)), \
             patch.object(gw_channels, "remove_env", side_effect=lambda ks: removed.extend(ks)):
            _raw(gw_channels.toggle_channel)(channel, req)
        return saved, removed

    def test_toggle_does_not_overwrite_with_masked_url(self):
        saved, removed = self._toggle(ChannelToggleRequest(
            enabled=False, webhook_url=mask_url("https://hooks.example/send?key=realtoken999")))
        self.assertNotIn("ASTRA_NOTIFICATION_WEBHOOK", saved)
        self.assertNotIn("ASTRA_NOTIFICATION_WEBHOOK", removed)  # 也没被 remove_env 误拔

    def test_toggle_still_accepts_real_url(self):
        saved, _ = self._toggle(ChannelToggleRequest(
            enabled=False, webhook_url="https://hooks.example/send?key=realtoken999"))
        self.assertEqual(saved.get("ASTRA_NOTIFICATION_WEBHOOK"), "https://hooks.example/send?key=realtoken999")

    def test_put_sanitizes_masked_and_routes_secrets_to_encrypted_store(self):
        env_writes: dict = {}
        sec_writes: dict = {}
        with patch.object(gw_notifications, "require_superadmin", return_value={"username": "root"}), \
             patch.object(gw_notifications, "refresh_settings"), \
             patch.object(gw_notifications, "notification_env", return_value={
                 "ASTRA_NOTIFICATION_WEBHOOK": "https://hooks.example/send?key=realtoken999",
                 "ASTRA_QQ_APP_ID": "app1", "ASTRA_QQ_OPENID": "oid1"}), \
             patch.object(gw_notifications, "update_env", side_effect=lambda d: env_writes.update(d)), \
             patch.object(gw_notifications, "save_secrets", side_effect=lambda d: sec_writes.update(d)), \
             patch.object(gw_notifications, "remove_env"), \
             patch.object(gw_notifications, "audit_record"):
            payload = NotificationConfigUpdate(
                webhook_enabled=True,
                webhook_url=mask_url("https://hooks.example/send?key=realtoken999"),   # 未动 → 整体跳过
                wechat_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=NEW-REAL",  # 新值 → 密文库
            )
            _raw(gw_notifications.admin_update_notifications)(payload)
        self.assertNotIn("ASTRA_NOTIFICATION_WEBHOOK", env_writes)   # 掩码未回写 env
        self.assertNotIn("ASTRA_NOTIFICATION_WEBHOOK", sec_writes)   # 掩码未回写密文库
        self.assertEqual(sec_writes.get("ASTRA_WECHAT_WEBHOOK"),
                         "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=NEW-REAL")
        self.assertNotIn("ASTRA_WECHAT_WEBHOOK", env_writes)         # 真密钥不再明文落 .env


class TestA3BackupExclusions(unittest.TestCase):
    def test_credential_bearing_files_are_mandatory_excluded(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        import backup_runtime  # noqa: PLC0415
        for rel in ("data/llm_models.json", "data/llm_providers.json", "data/admin_auth.db",
                    "data/backups/archive_x/trading_ledger.json", "backups/local/a.tar.gz"):
            self.assertTrue(backup_runtime._excluded(rel, []), f"应被强制排除: {rel}")
        self.assertFalse(backup_runtime._excluded("data/trading_ledger.json", []))  # 正常灾备不误伤


class TestA6TelegramSafety(unittest.TestCase):
    def test_scrub_masks_bot_token(self):
        raw = "unknown url type: 'api.telegram.org/bot123456789:AAF-verysecret-tokenXYZ/sendMessage'"
        out = notif._scrub_url_secret(raw)
        self.assertNotIn("AAF-verysecret-tokenXYZ", out)
        self.assertIn("bot***REDACTED***", out)

    def test_post_json_error_scrubs_token(self):
        ok, detail, _ = notif._post_json("api.telegram.org/bot123456789:AAFsecretTOK/sendMessage", {})
        self.assertFalse(ok)
        self.assertNotIn("AAFsecretTOK", detail)  # 旧写法此处 ValueError 裸穿或泄 token

    def test_telegram_invalid_base_rejected_before_socket(self):
        env = {
            "ASTRA_TELEGRAM_BOT_TOKEN": "123456789:AAFsecretTOK",
            "ASTRA_TELEGRAM_CHAT_ID": "42",
            "ASTRA_TELEGRAM_API_BASE": "api.telegram.org",  # 无 scheme
        }
        ok, msg = notif.send_channel("telegram", "hello", env=env)
        self.assertFalse(ok)
        self.assertNotIn("AAFsecretTOK", msg)  # 校验拒绝文本必须脱敏


class TestBStatusNoPositionLeaks(unittest.TestCase):
    def test_status_strips_trackers_and_decisions(self):
        with patch.object(sysmod, "script_state", return_value={"name": "x", "exists": False}), \
             patch.object(sysmod, "read_json", side_effect=AssertionError("status 不应再读 decisions/trackers")):
            out = _raw(sysmod.status)()
        self.assertNotIn("position_trackers", out)
        self.assertNotIn("last_decisions", out)
        self.assertIn("version", out)


class TestCSecretsStoreCorruption(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="astra-secrets-test-"))
        self._orig = (gws.KEY_FILE, gws.STORE_FILE)
        gws.KEY_FILE = self.tmp / ".astra_secret_key"
        gws.STORE_FILE = self.tmp / "astra_secrets.enc"
        gws._CORRUPT_REPORTED = False

    def tearDown(self):
        gws.KEY_FILE, gws.STORE_FILE = self._orig

    def test_healthy_roundtrip_and_bak(self):
        gws.save_secrets({"LLM_API_KEY": "k1"})
        self.assertEqual(gws.load_secrets().get("LLM_API_KEY"), "k1")
        gws.save_secrets({"ASTRA_QQ_CLIENT_SECRET": "s2"})
        self.assertTrue((self.tmp / "astra_secrets.enc.bak").exists())  # 覆盖前留旧密文
        self.assertEqual(gws.load_secrets().get("LLM_API_KEY"), "k1")  # merge 不丢

    def test_missing_key_refuses_write_not_wipe(self):
        gws.save_secrets({"LLM_API_KEY": "precious"})
        original_cipher = gws.STORE_FILE.read_bytes()
        gws.KEY_FILE.unlink()                       # 事故模拟：key 被误删
        self.assertEqual(gws.load_secrets(), {})    # 读面 fail-soft
        with self.assertRaises(gws.SecretsStoreError):
            gws.save_secrets({"LLM_API_KEY": "overwrite"})  # 写面拒写
        self.assertEqual(gws.STORE_FILE.read_bytes(), original_cipher)  # 现场未覆盖
        with self.assertRaises(gws.SecretsStoreError):
            gws.delete_secrets(["LLM_API_KEY"])

    def test_tampered_store_raises_on_write(self):
        gws.save_secrets({"LLM_API_KEY": "k1"})
        gws.STORE_FILE.write_bytes(b"garbage-not-fernet")
        with self.assertRaises(gws.SecretsStoreError):
            gws.save_secrets({"ASTRA_ADMIN_TOKEN": "x"})
        self.assertEqual(gws.load_secrets(), {})  # 读面告警回退，不炸服务


if __name__ == "__main__":
    unittest.main(verbosity=2)
