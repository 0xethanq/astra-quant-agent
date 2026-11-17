"""AI 健康度、交易心法渲染与行情/健康快照装配（结构优化阶段 2 / B2 第四刀）。

这组函数都要读被测试 patch/沙箱重定向的路径（AI_MEMORY_MD_FILE / DATA_DIR /
AI_DECISIONS_FILE），故同 B4/B5/B6 与前三刀：**门面薄壳调用时解析全局并注入，
核心以参数接收**。直接重导出会让 patch 静默失效、读到真实项目文件。
"""
from __future__ import annotations

import datetime
import json
import os
import time

__all__ = ["load_trading_memory_md", "_memory_freshness_note",
           "build_ai_health", "_load_cross_venue_data"]



def load_trading_memory_md(memory_file: str | os.PathLike[str], data_dir: str | os.PathLike[str], ) -> str:
    """Render the live heuristic memory library.

    The structured store (data/structured_trading_memory.json) is the single
    authority written by the self-evolution engine; the legacy markdown file is
    only a fallback. Reading the file alone freezes the homepage panel on the
    last hand-edited snapshot while the engine keeps revising lessons.
    """
    rendered = ""
    try:
        from scripts.evolution_shield import render_trading_memory
        rendered = render_trading_memory(memory_file, os.path.join(data_dir, "ai_trading_memory.json")) or ""
    except Exception:
        rendered = ""
    if rendered.strip():
        return rendered + _memory_freshness_note(data_dir)
    if os.path.exists(memory_file):
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
    return ""


def _memory_freshness_note(data_dir: str | os.PathLike[str], ) -> str:
    """One-line provenance footer so the panel visibly tracks engine revisions."""
    structured = os.path.join(data_dir, "structured_trading_memory.json")
    try:
        with open(structured, "r", encoding="utf-8") as f:
            store = json.load(f)
        lessons = store.get("lessons") or []
        stamps = [i.get("created_at") for i in lessons if i.get("created_at")]
        newest = max(stamps) if stamps else ""
        if newest:
            try:
                local = datetime.datetime.fromisoformat(newest).astimezone(
                    datetime.timezone(datetime.timedelta(hours=8))
                ).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                local = str(newest)[:19]
            return (
                f"\n\n> 权威来源: structured_trading_memory.json"
                f" | 修订 {str(store.get('revision'))[:8]} | 共 {len(lessons)} 条心法"
                f" | 最近更新 {local} (UTC+8)"
            )
        return f"\n\n> 权威来源: structured_trading_memory.json | 共 {len(lessons)} 条心法"
    except Exception:
        return ""


def build_ai_health(data_dir: str | os.PathLike[str], ai_history_list):
    """AI 决策健康度（2026-09-10）：用户反馈"委员会不能正常运行"却无从判断——
    把决策缓存年龄、委员会开关态、最近周期结果直接摆上推演页，失败可见。"""
    out: dict = {}
    try:
        _dec_file = os.path.join(data_dir, "ai_brain_decisions.json")
        if os.path.exists(_dec_file):
            with open(_dec_file, "r", encoding="utf-8") as f:
                _dec = json.load(f)
            _ts = [int(v.get("timestamp") or 0) for v in _dec.values() if isinstance(v, dict)]
            if _ts:
                out["decision_age_seconds"] = max(0, int(time.time() - max(_ts)))
    except Exception:
        pass
    try:
        with open(os.path.join(data_dir, "council_config.json"), "r", encoding="utf-8") as f:
            _cc = json.load(f)
        out["council_enabled"] = bool(_cc.get("enabled"))
        out["council_timeout"] = _cc.get("timeout_seconds")
    except Exception:
        pass
    if ai_history_list:
        out["last_cycle_time"] = ai_history_list[0].get("time")
        _cs = ai_history_list[0].get("council_status")
        out["last_council_status"] = _cs if isinstance(_cs, dict) else None
    return out


def _load_cross_venue_data(data_dir: str | os.PathLike[str], decisions_file: str | os.PathLike[str], ) -> dict:
    """US-007：行情/健康快照透传装配（只读，零网络；已收口为 OKX 专用）。

    数据源两路，各自独立兜底，任一缺失/损坏只降级该部分，绝不影响主缓存：
      1) data/venue_health.json —— 健康徽标(venues/updated_utc/package_count)
         + brain 逐币快照 symbols；
      2) data/ai_brain_decisions.json —— 各币 OKX 最新价（`raw_ticker.last`）。
    by_asset = 两路合并（symbols 优先，决策缓存补缺），键位恒为 {okx_last}，
    缺值置 ""（前端渲染 "--"）。

    历史外所基差/多空比/资金费字段已随外所下架一并移除。`venues` 与 `symbols`
    仍**按原样透传**：数据文件不改（历史文件里可能仍有外所行），未知键由读侧忽略
    —— 只读容忍，绝不因未知场所字段抛错或删数据。
    """
    out = {"updated_utc": "", "package_count": 0, "venues": {}, "symbols": {}, "by_asset": {}}

    sym_rows = {}
    try:
        with open(os.path.join(data_dir, "venue_health.json"), "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            out["updated_utc"] = str(raw.get("updated_utc") or "")
            out["package_count"] = int(raw.get("package_count") or 0)
            venues = raw.get("venues")
            out["venues"] = venues if isinstance(venues, dict) else {}
            symbols = raw.get("symbols")
            if isinstance(symbols, dict):
                sym_rows = {str(k).upper(): v for k, v in symbols.items() if isinstance(v, dict)}
    except Exception:
        pass
    out["symbols"] = sym_rows

    # 决策缓存侧素材：asset -> okx_last
    src = {}
    try:
        with open(decisions_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if isinstance(cache, dict):
            for inst_id, entry in cache.items():
                if not isinstance(entry, dict):
                    continue
                asset = str(entry.get("name") or str(inst_id).split("-")[0]).upper().strip()
                if not asset:
                    continue
                rt = entry.get("raw_ticker")
                src[asset] = {"okx_last": (rt.get("last") if isinstance(rt, dict) else None) or ""}
    except Exception:
        pass

    for asset in src.keys() | sym_rows.keys():
        sym = sym_rows.get(asset) or {}
        okx = sym.get("okx") or src.get(asset, {}).get("okx_last") or ""
        out["by_asset"][asset] = {"okx_last": okx}
    return out
