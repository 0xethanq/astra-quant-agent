import unittest
from fastapi.testclient import TestClient
from astra_backend.app import app
from astra_backend.settings_store import mask_url
from astra_backend.interceptor_manager import get_plugin_detail, save_plugin_code, create_plugin, delete_plugin

class SecurityFixesTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_cache_ledger_requires_authentication(self):
        resp = self.client.get("/api/v1/cache/ledger")
        self.assertEqual(resp.status_code, 401)

    def test_cache_non_sensitive_allowed_without_auth(self):
        resp = self.client.get("/api/v1/cache/sentiment")
        self.assertIn(resp.status_code, (200, 404))

    def test_mask_url_masks_webhook_tokens(self):
        raw = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=693a91f6-7xxx-4bc4-97a0-0b2e53e15fa6"
        masked = mask_url(raw)
        self.assertNotIn("693a91f6", masked)
        self.assertTrue(masked.startswith("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="))

    def test_interceptor_path_traversal_prevention(self):
        with self.assertRaises((FileNotFoundError, ValueError)):
            get_plugin_detail("../../../etc/passwd")
        with self.assertRaises(ValueError):
            save_plugin_code("../../malicious.py", "print('hack')")
        with self.assertRaises(ValueError):
            create_plugin("../../malicious.py", "print('hack')")
        with self.assertRaises(ValueError):
            delete_plugin("../../malicious.py")

if __name__ == "__main__":
    unittest.main()
