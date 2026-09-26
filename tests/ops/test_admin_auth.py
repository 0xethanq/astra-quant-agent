"""Administrator account, password and session security tests."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from astra_backend.admin_auth import AdminAuthStore


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = AdminAuthStore(Path(self.temp.name) / "admin.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_initialization_and_login_session(self):
        self.assertTrue(self.store.initialize_from_legacy("LegacyToken123456"))
        self.assertFalse(self.store.initialize_from_legacy("OtherPassword123"))
        result = self.store.login("admin", "LegacyToken123456")
        user = self.store.validate_session(result["session_token"])
        self.assertEqual(user["role"], "superadmin")
        self.store.logout(result["session_token"])
        self.assertIsNone(self.store.validate_session(result["session_token"]))

    def test_password_is_not_stored_in_plaintext(self):
        self.store.create_user("alice", "StrongPassword123", "admin")
        self.assertNotIn(b"StrongPassword123", self.store.path.read_bytes())

    def test_disable_revokes_sessions_and_preserves_superadmin(self):
        self.store.create_user("rootadmin", "StrongPassword123", "superadmin")
        root = self.store.login("rootadmin", "StrongPassword123")
        child = self.store.create_user("operator", "OperatorPassword123", "admin")
        child_login = self.store.login("operator", "OperatorPassword123")
        self.store.set_enabled(child["id"], False, root["user"]["id"])
        self.assertIsNone(self.store.validate_session(child_login["session_token"]))
        with self.assertRaises(ValueError):
            self.store.set_enabled(root["user"]["id"], False, root["user"]["id"])

    def test_password_change_revokes_old_session(self):
        user = self.store.create_user("operator", "OperatorPassword123", "admin")
        login = self.store.login("operator", "OperatorPassword123")
        self.store.change_password(user["id"], "NewOperatorPassword456")
        self.assertIsNone(self.store.validate_session(login["session_token"]))
        self.assertIsNotNone(self.store.login("operator", "NewOperatorPassword456"))

    def test_failed_login_reports_remaining_attempts_and_unlocks(self):
        # 审计D(2026-09-13)·枚举面收口后重写：旧钉「还可尝试 N 次/已锁定」逐态文案，
        # 正是账号枚举神谕。现在对**所有**失败态（含锁定期内输对密码）只有一句话；
        # 锁定机制本身照旧生效（用 DB 状态与 unlock_user 后行为证明），原因进 stderr。
        import io
        import sys as _sys
        from unittest.mock import patch
        user = self.store.create_user("operator", "OperatorPassword123", "admin")
        for _ in range(5):
            with self.assertRaisesRegex(PermissionError, "^账号或密码错误$"):
                self.store.login("operator", "wrong-password")
        with patch.object(_sys, "stderr", new_callable=io.StringIO) as err:
            with self.assertRaisesRegex(PermissionError, "^账号或密码错误$"):
                self.store.login("operator", "OperatorPassword123")   # 锁定期连对也不放行
        self.assertIn("账号锁定中", err.getvalue())              # 真实原因在服务器侧（预检锁定分支）
        # 「不存在账号」与「锁定账号」对外文案逐字节一致 → 无枚举差
        with self.assertRaisesRegex(PermissionError, "^账号或密码错误$"):
            self.store.login("ghost-user", "whatever")
        self.store.unlock_user(user["id"])
        self.assertEqual(self.store.login("operator", "OperatorPassword123")["user"]["username"], "operator")

    def test_remaining_counter_never_shows_negative(self):
        # max(0,…) 夹紧：残余计数漂移不得再产出「-1 次」字样（现在原因也不外露，
        # 但 stderr 理由串同样夹死）
        import io
        import sys as _sys
        from unittest.mock import patch
        self.store.create_user("drifty", "OperatorPassword123", "admin")
        for _ in range(4):
            with self.assertRaises(PermissionError):
                self.store.login("drifty", "wrong")
        with self.store.connect() as connection:
            connection.execute("UPDATE admin_users SET locked_until=0, failed_attempts=6 WHERE username='drifty'")
        with patch.object(_sys, "stderr", new_callable=io.StringIO) as err:
            with self.assertRaises(PermissionError):
                self.store.login("drifty", "wrong")
        self.assertNotIn("-1 次", err.getvalue())
        self.assertIn("触发 15 分钟锁定", err.getvalue())  # 6>=5 直接重锁

    def test_invalid_password_policy(self):
        with self.assertRaises(ValueError):
            self.store.create_user("bob", "short", "admin")


if __name__ == "__main__":
    unittest.main()
