"""重置基准（reset_time / initial_capital）读取（结构优化阶段 2·B2 第九刀）。

原样搬自 update_cache_cycle 的「# 3. Read Reset Initial State」段（11 行）。
data_dir 由门面注入（测试会把 DATA_DIR 指向沙箱）。
"""
from __future__ import annotations

import os

from astra_backend.dashboard_payload.readers import read_json

__all__ = ["read_reset_initial_state"]


def read_reset_initial_state(data_dir):
    # 3. Read Reset Initial State
    account_init_file = os.path.join(data_dir, "account_initial_state.json")
    reset_time_str = "1970-01-01 00:00:00"
    initial_capital_val = float(os.getenv("INITIAL_CAPITAL", "10000.0"))
    acc_init = read_json(account_init_file, {})
    try:
        reset_time_str = acc_init.get("reset_time", "1970-01-01 00:00:00")
        initial_capital_val = float(acc_init.get("initial_capital", 10000.0) or 10000.0)
    except Exception:
        pass

    return reset_time_str, initial_capital_val
