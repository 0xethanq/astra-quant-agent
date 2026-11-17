"""策略快照的文件位置。

注意：本模块比 policy_snapshot.py 深一层，`Path(__file__).resolve().parents[N]`
的 N 必须相应 +1（原 parents[1] → 现 parents[2]），否则 ROOT 会算成 astra_backend 目录。
结构优化阶段 2（B6）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
ARCHIVE_DIR = DATA_DIR / "policy_archives"
ARCHIVE_INDEX_FILE = ARCHIVE_DIR / "index.json"
