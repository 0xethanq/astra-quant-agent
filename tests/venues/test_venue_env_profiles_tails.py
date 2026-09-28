"""OKX 环境档枚举（`astra_backend/exchanges/env_profiles.py`）残余分支收口测试。

OKX 专用化后，多所候选域网络探测（`_probe_candidate`）与端点钉死持久化
（`_persist` / `_load_persisted` / `PROFILE_FILE` / `PROBE_PATH`）已随多所拆除
一并移除；本模块只收口仍然存活的 `environments_of` 行为。
"""
from __future__ import annotations

import unittest

from astra_backend.exchanges.env_profiles import environments_of


class VenueEnvProfilesTailsTests(unittest.TestCase):
    def test_environments_of_okx_returns_sorted_list(self):
        envs = environments_of("okx")
        self.assertEqual(envs, ["demo", "live"])
        self.assertEqual(envs, sorted(envs))
        # 场所名大小写不敏感
        self.assertEqual(environments_of("OKX"), envs)

    def test_environments_of_unknown_venue_is_empty(self):
        self.assertEqual(environments_of("unknown_venue"), [])
        # 已移除场所不再有任何环境档
        self.assertEqual(environments_of("gate"), [])
        self.assertEqual(environments_of("binance"), [])


if __name__ == "__main__":
    unittest.main()
