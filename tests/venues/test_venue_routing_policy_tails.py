"""多所路由分配策略（`astra_backend/exchanges/routing_policy.py`）残余分支收口测试 —— 第 345 刀。

本模块 308 行，是多所平权资产池、路由模式与首选场所持久化配置核心：
- 资产白名单规范化（`_normalize_assets`）：空值防御与非字符串丢弃；
- 交易所资产池加载（`load_venue_pool` / `load_binance_pool` / `gate_pool_assets`）：坏 JSON 容错与非数值风控覆盖项容错；
- Gate 实盘执行就绪判定（`_gate_execution_ready`）：秘钥读取异常防御；
- 原始配置读取与原子落盘容错（`_read_raw_routing` / `save_routing_mode` / `save_preferred_venue`）：坏 JSON 自愈、磁盘写入异常捕获与临时文件清理。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_backend.exchanges.routing_policy import (
    _read_raw_routing,
    save_preferred_venue,
    save_routing_mode,
)


class VenueRoutingPolicyTailsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="astra_routing_policy_tails_")
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.test_routing_file = self.tmp_path / "venue_routing.json"

        # 严防测试向生产 data/venue_routing.json 写入
        p = patch("astra_backend.exchanges.routing_policy.ROUTING_FILE", self.test_routing_file)
        p.start()
        self.addCleanup(p.stop)

    # -------------------------------------------------------------------------
    # 原始配置读取与保存容错 (_read_raw_routing, save_routing_mode, save_preferred_venue)
    # -------------------------------------------------------------------------
    def test_read_raw_routing_corrupt_file_returns_empty_dict(self):
        # 坏 JSON 时捕获异常返回空字典 (line 183)
        self.test_routing_file.write_text("bad_content", encoding="utf-8")
        self.assertEqual(_read_raw_routing(), {})

    def test_save_routing_mode_disk_error_cleans_tmp_and_returns_false(self):
        # 原子落盘异常时删除临时文件并返回 False (lines 249-254)
        with patch("os.replace", side_effect=OSError("disk read-only")):
            res = save_routing_mode("balanced")
            self.assertFalse(res)
            tmp_file = self.test_routing_file.with_suffix(".json.tmp")
            self.assertFalse(tmp_file.exists())

        # 当删除临时文件也抛异常时静默忽略 pass (line 253)
        with patch("os.replace", side_effect=OSError("disk read-only")):
            with patch.object(Path, "unlink", side_effect=OSError("unlink error")):
                res_pass = save_routing_mode("balanced")
                self.assertFalse(res_pass)

    def test_save_preferred_venue_disk_error_cleans_tmp_and_returns_false(self):
        # 原子落盘异常时删除临时文件并返回 False (lines 278-283)
        with patch("os.replace", side_effect=OSError("disk read-only")):
            res = save_preferred_venue("okx")
            self.assertFalse(res)
            tmp_file = self.test_routing_file.with_suffix(".json.tmp")
            self.assertFalse(tmp_file.exists())

        # 当删除临时文件也抛异常时静默忽略 pass (line 282)
        with patch("os.replace", side_effect=OSError("disk read-only")):
            with patch.object(Path, "unlink", side_effect=OSError("unlink error")):
                res_pass = save_preferred_venue("okx")
                self.assertFalse(res_pass)


if __name__ == "__main__":
    unittest.main()
