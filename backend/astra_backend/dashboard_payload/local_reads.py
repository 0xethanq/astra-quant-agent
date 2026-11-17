"""`update_cache_cycle` 内的本地文件读取块（结构优化阶段 2·B2 第六刀）。

迁出的是原函数第 8/9/10 段（复盘/自适应配置、快照曲线、新闻与 AI 决策历史）
外加心法渲染与系统磁盘信息 —— 全部是**本地文件读取 + 纯计算**，不碰网络。

接缝纪律同前几刀：所读路径（report_file / snapshots_file /
news_file / last_prompt_file / history_file / factor_file）
与 `load_trading_memory_md` 都由门面在调用时注入，核心不自持副本。

**逐字保留的细节**：原代码把 `ai_last_prompt_text` 读了两遍（第 972 行与第 996 行），
第一遍只用于写进 review_data、第二遍才是载荷里的值。这里照样读两遍，不做"顺手去重"——
本刀只搬不改。
"""
from __future__ import annotations

import json
import os
import shutil

from astra_backend.dashboard_payload.readers import read_json, read_text
from astra_backend.time_utils import beijing_text

__all__ = ["load_local_reads"]


def load_local_reads(report_file, snapshots_file, news_file, last_prompt_file, history_file,
                     factor_file, load_memory_md, reset_time_str, initial_capital_val,
                     total_eq, timestamp_full, disk_path="/"):
    # 8. Read Review & Adaptive Config
    review_data = read_json(report_file, {})

    adaptive_cfg = {}

    # 9. Read Snapshots
    snapshots_list = []
    if os.path.exists(snapshots_file):
        try:
            with open(snapshots_file, "r", encoding="utf-8") as f:
                snaps = json.load(f)
                if isinstance(snaps, list):
                    # Filter strictly >= reset_time
                    for s in snaps:
                        s_time = beijing_text(s.get("time"))
                        if s_time and s_time >= beijing_text(reset_time_str):
                            t_eq = float(s.get("total_eq", s.get("equity", initial_capital_val)) or initial_capital_val)
                            pnl_v = round(t_eq - initial_capital_val, 2)
                            roi_v = round((pnl_v / initial_capital_val * 100), 2)
                            snapshots_list.append({
                                "time": s_time,
                                "total_eq": round(t_eq, 2),
                                "pnl": pnl_v,
                                "roi": roi_v
                            })
                    snapshots_list = snapshots_list[-60:]
        except Exception:
            pass

    # Append live current point
    snapshots_list.append({
        "time": timestamp_full.replace(" (北京时间)", ""),
        "total_eq": round(total_eq, 2),
        "pnl": round(total_eq - initial_capital_val, 2),
        "roi": round((total_eq - initial_capital_val) / initial_capital_val * 100, 2)
    })

    # 10. Read News & AI Decisions History
    news_data = read_json(news_file, {})

    ai_last_prompt_text = read_text(last_prompt_file)

    ai_history_list = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                raw_history = json.load(f)
                # Keep up to 25 records and trim heavy repeated prompts in older history
                for idx, item in enumerate(raw_history[:25]):
                    c = dict(item)
                    if idx > 0 and "ai_last_prompt" in c and len(str(c["ai_last_prompt"])) > 500:
                        c["ai_last_prompt"] = str(c["ai_last_prompt"])[:200] + "...(历史已收敛)"
                    ai_history_list.append(c)
        except Exception:
            pass

    # Inject latest prompt into review payload if running under older worker
    if isinstance(review_data, dict):
        review_data["ai_last_prompt"] = ai_last_prompt_text

    factor_lib_snapshot = read_json(factor_file, {})

    ai_memory_md_content = load_memory_md()

    ai_last_prompt_text = read_text(last_prompt_file)

    # System Disk info
    total_b, used_b, free_b = shutil.disk_usage(disk_path)
    disk_free_gb = round(free_b / (1024 ** 3), 1)
    return {
        "adaptive_cfg": adaptive_cfg,
        "ai_history_list": ai_history_list,
        "ai_last_prompt_text": ai_last_prompt_text,
        "ai_memory_md_content": ai_memory_md_content,
        "disk_free_gb": disk_free_gb,
        "factor_lib_snapshot": factor_lib_snapshot,
        "news_data": news_data,
        "review_data": review_data,
        "snapshots_list": snapshots_list,
    }
