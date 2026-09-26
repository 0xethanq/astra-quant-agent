"""审计 D7 封闭单测：均衡选所/新闻 id 的跨进程确定性（PYTHONHASHSEED 免疫）。

用两个不同 hash seed 的真实子进程跑同一表达式——旧 abs(hash(...)) 写法在这
对种子下几乎必然漂移；sha256 新实现必须逐字节一致。零网络零生产写入（律①）。
"""
from __future__ import annotations
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])

_SNIPPET_PICK = (
    "import sys; sys.path.insert(0, %r);"
    "from astra_backend.venue_router import _balanced_pick;"
    "print(_balanced_pick('BTC', ['binance', 'gate', 'okx']))" % REPO
)
_SNIPPET_NEWS = (
    "import hashlib;"
    "title='美联储宣布维持利率不变';"
    "print(hashlib.sha256(title.encode('utf-8')).hexdigest()[:8])"
)


def _run_with_seed(snippet: str, seed: str) -> str:
    proc = subprocess.run([sys.executable, "-c", snippet],
                          capture_output=True, text=True, timeout=60,
                          env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


class BalancedPickDeterminismTests(unittest.TestCase):
    def test_same_result_across_hash_seeds(self):
        # 第七十八刀：以 spawn 为被测行为，离线守护下如实 skip（守卫在 spawn 前）。
        from tests.config_sandbox import skip_if_offline_suite
        skip_if_offline_suite(self)
        results = {_run_with_seed(_SNIPPET_PICK, s) for s in ("1", "7", "12345")}
        self.assertEqual(len(results), 1, f"均衡选所跨进程漂移: {results}")
        self.assertIn(next(iter(results)), {"binance", "gate", "okx"})

    def test_matches_direct_computation(self):
        from astra_backend.venue_router import _balanced_pick
        venues = ["binance", "gate", "okx"]
        expected = venues[int(hashlib.sha256(b"BTC").hexdigest(), 16) % 3]
        self.assertEqual(_balanced_pick("BTC", venues), expected)

    def test_distribution_spreads_assets(self):
        # 「均衡轮换」的灵魂：不同标的应打散到多个所（全落一所=哈希写错）
        from astra_backend.venue_router import _balanced_pick
        venues = ["binance", "gate", "okx"]
        picks = {_balanced_pick(a, venues) for a in ("BTC", "ETH", "SOL", "LINK", "AVAX", "DOGE")}
        self.assertGreater(len(picks), 1, "均衡选所退化为单所固定")

    def test_empty_venues_honest_empty(self):
        from astra_backend.venue_router import _balanced_pick
        self.assertEqual(_balanced_pick("BTC", []), "")

    def test_builtin_hash_would_drift(self):
        # 第七十八刀：以 spawn 为被测行为，离线守护下如实 skip（守卫在 spawn 前）。
        from tests.config_sandbox import skip_if_offline_suite
        skip_if_offline_suite(self)
        # 反证锚点：证明旧 abs(hash(x)) 确实随种子漂移（本测试环境内模拟）
        outs = {_run_with_seed("import sys;print(abs(hash('BTC'))%3)", s) for s in ("1", "7", "12345")}
        self.assertGreater(len(outs), 1, "种子环境失效——此锚测失去意义时请调整种子")


if __name__ == "__main__":
    unittest.main()
