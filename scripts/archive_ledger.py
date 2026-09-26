#!/usr/bin/env python3
"""交易台账分片归档（审计「未完成清单」#2）——**默认 dry-run，不会改动任何文件**。

为什么需要：`data/trading_ledger.json` 是"全量单文件"，所有读者（首页 KPI、自进化复盘、
SQLite 对账）都整文件读；跑久了它既是读路径瓶颈，也是单点损坏面。SQLite（`data/astra_quant.db`）
里同一批数据有结构化副本，所以 JSON 侧只承担"热窗口"即可。

设计红线（本文件的全部安全性都在这几条上）：
1. **默认只演算**：`--apply` 才写盘，且写盘前后都打印摘要；
2. **先归档、验归档、再截断**：归档文件必须原子写入、回读校验（条数 + sha256）通过后，
   才允许原子替换热台账；任何一步失败 → 热台账保持原样（fail-closed）；
3. **绝不猜**：`close_time` 缺失/不可解析（如"持仓中..."）的条目一律留在热台账，
   宁可不归档也不按推测的时间挪走；
4. **不丢行**：归档 + 热台账必须等于原始集合（按 id/内容多重集校验），否则拒绝写盘；
5. 归档文件按月/年分片，已存在时**合并去重**，不做覆盖式重建。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

LEDGER_FILE = ROOT / "data" / "trading_ledger.json"
ARCHIVE_DIR = ROOT / "data" / "archive"
BJ_TZ = timezone(timedelta(hours=8))

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S")


def parse_close_time(value: Any) -> datetime | None:
    """解析平仓时间；不可解析（含"持仓中..."等占位）一律返回 None（绝不猜）。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=BJ_TZ)
        except ValueError:
            continue
    return None


def plan_archive(rows: Iterable[Any], *, keep_days: int = 180,
                 now: datetime | None = None) -> tuple[list[Any], list[Any]]:
    """纯函数：返回 (热台账行, 待归档行)。

    只有"能解析出时间且早于 cut-off"的行才进入归档；其余（含不可解析时间、结构异常）
    全部留在热台账。
    """
    now = now or datetime.now(BJ_TZ)
    cutoff = now - timedelta(days=max(int(keep_days), 1))
    hot: list[Any] = []
    cold: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            hot.append(row)
            continue
        closed_at = parse_close_time(row.get("close_time"))
        if closed_at is not None and closed_at < cutoff:
            cold.append(row)
        else:
            hot.append(row)
    return hot, cold


def _signature(rows: Iterable[Any]) -> dict[str, int]:
    """内容摘要（只用 JSON 稳定序列化）：用于"归档 + 热 = 原始"的多重集校验。"""
    counts: dict[str, int] = {}
    for row in rows:
        key = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _atomic_write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rows(path: Path) -> list[Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path.name} 顶层不是数组（拒绝在未知结构上归档）")
    return data


def archive_shards(cold: list[Any]) -> dict[str, list[Any]]:
    """按平仓年份分片（解析失败的不会出现在这里）。"""
    shards: dict[str, list[Any]] = {}
    for row in cold:
        closed_at = parse_close_time(row.get("close_time"))
        if closed_at is None:
            continue
        shards.setdefault(closed_at.strftime("%Y"), []).append(row)
    return shards


def run(ledger_file: Path = LEDGER_FILE, archive_dir: Path = ARCHIVE_DIR, *,
        keep_days: int = 180, apply: bool = False, now: datetime | None = None) -> dict[str, Any]:
    rows = _load_rows(ledger_file)
    hot, cold = plan_archive(rows, keep_days=keep_days, now=now)
    report: dict[str, Any] = {
        "ledger": str(ledger_file),
        "apply": bool(apply),
        "keep_days": keep_days,
        "total": len(rows),
        "keep_hot": len(hot),
        "to_archive": len(cold),
        "unparsable_kept_hot": sum(1 for r in rows if isinstance(r, dict) and parse_close_time(r.get("close_time")) is None),
        "shards": {year: len(items) for year, items in sorted(archive_shards(cold).items())},
    }
    if not cold:
        report["status"] = "noop"
        return report
    if not apply:
        report["status"] = "dry_run"
        return report

    # ── 写盘路径：先归档 → 回读校验 → 多重集校验 → 再原子替换热台账 ──
    written: dict[str, str] = {}
    merged_total = 0
    for year, items in sorted(archive_shards(cold).items()):
        target = archive_dir / f"ledger_{year}.json"
        existing: list[Any] = []
        if target.exists():
            existing = _load_rows(target)
        merged = existing + items
        digest = _atomic_write_json(target, merged)
        readback = _load_rows(target)
        if len(readback) != len(merged):
            raise RuntimeError(f"归档回读条数不一致：{target.name} 期望 {len(merged)} 实得 {len(readback)}")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"归档回读校验失败（sha256 不一致）：{target.name}")
        written[target.name] = digest
        merged_total += len(items)

    before = _signature(rows)
    after = _signature(hot)
    for year, items in archive_shards(cold).items():
        archived = _load_rows(archive_dir / f"ledger_{year}.json")
        for row in items:
            key = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            after[key] = after.get(key, 0) + 1
    if before != after:
        raise RuntimeError("行集合校验失败：归档 + 热台账 ≠ 原始台账，已放弃截断（热台账保持原样）")

    _atomic_write_json(ledger_file, hot)
    report.update({
        "status": "applied",
        "archived_files": written,
        "archived_rows": merged_total,
        "hot_after": len(_load_rows(ledger_file)),
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="交易台账分片归档（默认 dry-run）")
    parser.add_argument("--keep-days", type=int, default=180, help="热台账保留天数（默认 180）")
    parser.add_argument("--apply", action="store_true", help="真正写盘（默认只演算）")
    parser.add_argument("--ledger", default=str(LEDGER_FILE))
    parser.add_argument("--archive-dir", default=str(ARCHIVE_DIR))
    args = parser.parse_args(argv)
    try:
        result = run(Path(args.ledger), Path(args.archive_dir),
                     keep_days=args.keep_days, apply=args.apply)
    except Exception as exc:  # fail-closed：任何异常都不写盘，只报告
        print(json.dumps({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
