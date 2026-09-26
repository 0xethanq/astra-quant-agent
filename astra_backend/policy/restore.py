"""策略包恢复流程。

restore_archived_policy 会调用**必须留在门面**的 `_resolve_archive_file`
（它又依赖被 isolated() 钉住的 `_rebuild_index_from_archives`），故由薄壳在调用时
解析后注入；其余依赖（io / fingerprints / capture / schema / paths）都是同包纯模块。
结构优化阶段 2（B6 第二刀）。
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from astra_backend.policy.capture import capture_full_strategy_package, generate_policy_snapshot
from astra_backend.policy.fingerprints import canonical_package_projection, package_restore_diff
from astra_backend.policy.io import _atomic_write_json
from astra_backend.policy.paths import ARCHIVE_DIR
from astra_backend.policy.schema import _PACKAGE_UNITS

logger = logging.getLogger(__name__)


def _review_restored_lessons(lessons: Any) -> Dict[str, Any]:
    """回滚落盘前的宪法复核（审计 P1-8b）。

    旧实现只跑 `_validate`（schema），不跑 `audit_proposed_lesson` → 策略回滚是绕过
    宪法门禁的稳定通道。回滚是管理员的显式恢复动作，不宜因某条心法不合规就整体失败，
    但必须**留痕并披露**：违规条目一律改标 RESTORED_UNREVIEWED 并在结果里点名。
    """
    report: Dict[str, Any] = {"total": 0, "flagged": [], "marked": 0}
    try:
        from evolution_shield import audit_proposed_lesson
    except Exception as exc:  # 复核器不可用 → 如实披露，绝不假装审过
        report["reviewer_error"] = str(exc)[:160]
        return report
    for item in lessons or []:
        if not isinstance(item, dict):
            continue
        report["total"] += 1
        text = str(item.get("rule_text") or "").strip()
        if not text:
            continue
        try:
            passed, reason = audit_proposed_lesson(text, sample_size=int(item.get("sample_size") or 1))
        except Exception as exc:
            passed, reason = False, f"复核异常: {exc}"
        if not passed:
            report["flagged"].append({"id": item.get("id"), "reason": reason, "rule_text": text[:80]})
            item["shield_status"] = "RESTORED_UNREVIEWED"
            item["shield_reason"] = reason
            report["marked"] += 1
        elif not item.get("shield_status"):
            item["shield_status"] = "RESTORED"
            report["marked"] += 1
    return report


def restore_archived_policy(resolve_archive_file: Callable[..., Path], root: Path, 
    policy_hash: str,
    archive_dir: Optional[Path] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Atomically restores live strategy state to an archived policy version package.

    Guarantees no partial state on failure: takes a pre-restore backup snapshot
    and automatically reverts if any unit restore operation fails.
    """
    if not policy_hash or not isinstance(policy_hash, str) or not re.match(r"^[a-zA-Z0-9_-]+$", policy_hash):
        raise ValueError(f"无效的策略哈希标识: {policy_hash}")

    a_dir = archive_dir or ARCHIVE_DIR
    archive_file = resolve_archive_file(a_dir, policy_hash)
    if not archive_file.is_file():
        raise FileNotFoundError(f"未找到归档的策略版本文件: {policy_hash}")

    with open(archive_file, "r", encoding="utf-8") as f:
        package = json.load(f)

    pkg_payload = package.get("package") or {}
    r_dir = root_dir or root
    archived_package_hash = str(
        package.get("package_hash") or (package.get("metadata") or {}).get("package_hash") or "")
    # 请求键可能是整包标识（新命名）或四单元 policy_hash（历史命名）：四单元校验必须
    # 比对**归档自带的** policy_hash，否则新命名归档永远校验不过（审计 P0-3 修复配套）。
    archived_policy_hash = str(package.get("policy_hash") or policy_hash)

    # Pre-restore safety snapshot to prevent partial state on failure
    pre_restore_package = capture_full_strategy_package(root, root_dir=r_dir)

    memory_review: Dict[str, Any] = {}

    def _apply_package(payload: Dict[str, Any]) -> None:
        sys_path_added = False
        scripts_dir = str(r_dir / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
            sys_path_added = True

        try:
            # 1. Restore Prompt Profile
            if "prompt_config" in payload and payload["prompt_config"]:
                try:
                    from prompt_library import save_library
                    save_library(payload["prompt_config"])
                except (ImportError, AttributeError):
                    from prompt_library import save_prompt_config
                    save_prompt_config(payload["prompt_config"])

            # 2. Restore Evolution Memory
            if "evolution_memory" in payload:
                from evolution_shield import STRUCTURED_MEMORY_FILE, _memory_lock, _validate
                evo_data = payload["evolution_memory"]
                with _memory_lock():
                    if evo_data is None or (
                        isinstance(evo_data, dict)
                        and (evo_data.get("exists") is False or evo_data.get("version") == "missing")
                    ):
                        STRUCTURED_MEMORY_FILE.unlink(missing_ok=True)
                    elif isinstance(evo_data, dict) and "raw_text" in evo_data:
                        raw = str(evo_data["raw_text"])
                        parsed = json.loads(raw)
                        if isinstance(parsed, list):
                            _validate(parsed)
                            memory_review.clear()
                            memory_review.update(_review_restored_lessons(parsed))
                        elif isinstance(parsed, dict) and "lessons" in parsed:
                            if not isinstance(parsed["lessons"], list):
                                raise ValueError("Invalid lessons in envelope: must be a list")
                            _validate(parsed["lessons"])
                            memory_review.clear()
                            memory_review.update(_review_restored_lessons(parsed["lessons"]))
                        STRUCTURED_MEMORY_FILE.write_text(raw, encoding="utf-8")
                    elif isinstance(evo_data, list):
                        _validate(evo_data)
                        memory_review.clear()
                        memory_review.update(_review_restored_lessons(evo_data))
                        _atomic_write_json(STRUCTURED_MEMORY_FILE, evo_data)
                    elif isinstance(evo_data, dict):
                        lessons = evo_data.get("lessons")
                        if lessons is not None:
                            if not isinstance(lessons, list):
                                raise ValueError("Invalid lessons in evolution memory: must be a list")
                            _validate(lessons)
                        memory_review.clear()
                        memory_review.update(_review_restored_lessons(evo_data.get("lessons") or []))
                        _atomic_write_json(STRUCTURED_MEMORY_FILE, evo_data)
                    else:
                        raise ValueError(f"Unsupported evolution memory format: {type(evo_data)}")

            # 3. Restore Interceptors
            if (
                "interceptor_config" in payload
                and isinstance(payload["interceptor_config"], dict)
                and payload["interceptor_config"]
            ):
                from astra_backend.interceptor_manager import save_config as save_interceptor_config
                save_interceptor_config(payload["interceptor_config"])

            # 4. Restore Council
            if (
                "council_config" in payload
                and isinstance(payload["council_config"], dict)
                and payload["council_config"]
            ):
                from astra_backend.council_manager import save_council_config
                save_council_config(payload["council_config"])

            # 5. Restore Risk Config
            # 审计 P0-3(2026-09-13)：此处曾宽 except → logger.warning，于是「旧归档含已
            # 下架风控键 / 值越界」导致风控**整段没恢复**，接口仍返回 status=restored，
            # 而审计与四单元哈希都看不见。现改为不吞：异常上抛 → 外层回滚 + 明确报错。
            if (
                "risk_config" in payload
                and isinstance(payload["risk_config"], dict)
                and payload["risk_config"]
            ):
                from astra_backend import risk_config
                from astra_backend.settings_store import update_env
                env_updates = risk_config.normalize(payload["risk_config"])
                update_env(env_updates)

            # 6. Restore Venue Routing（同 5：不再吞异常）
            if (
                "venue_routing" in payload
                and isinstance(payload["venue_routing"], dict)
                and payload["venue_routing"]
            ):
                from astra_backend.exchanges.routing_policy import ROUTING_FILE
                _atomic_write_json(ROUTING_FILE, payload["venue_routing"])
        finally:
            if sys_path_added and scripts_dir in sys.path:
                try:
                    sys.path.remove(scripts_dir)
                except ValueError:
                    pass

    try:
        _apply_package(pkg_payload)
    except Exception as exc:
        logger.error("Error during strategy restore: %s. Reverting to pre-restore state...", exc)
        try:
            _apply_package(pre_restore_package.get("package") or {})
        except Exception as revert_exc:
            logger.critical("Failed to revert to pre-restore state: %s", revert_exc)
        raise RuntimeError(f"策略回滚失败且已恢复原状态: {exc}") from exc

    # Verify new restored snapshot
    new_snapshot = generate_policy_snapshot(root, root_dir=r_dir)
    if new_snapshot["policy_hash"] != archived_policy_hash:
        logger.error(
            "Restored snapshot hash mismatch: expected %s, got %s. Reverting to pre-restore state...",
            archived_policy_hash,
            new_snapshot["policy_hash"],
        )
        try:
            _apply_package(pre_restore_package.get("package") or {})
        except Exception as revert_exc:
            logger.critical("Failed to revert to pre-restore state after hash mismatch: %s", revert_exc)
        raise RuntimeError(
            f"策略回滚失败且已恢复原状态: 恢复后哈希 {new_snapshot['policy_hash']} 与目标 {archived_policy_hash} 不一致"
        )

    # 审计 P0-3：四单元哈希看不到风控/路由——它们恢复失败时上面的校验永远是绿的。
    # 现按整包规范化投影逐单元核对，任何「归档里承诺、恢复后没对上」的单元一律判定
    # 恢复失败并回滚（绝不留半套状态），并在报错里点名是哪个单元。
    new_package = capture_full_strategy_package(root, root_dir=r_dir)
    restore_gaps = package_restore_diff(pkg_payload, new_package.get("package") or {})
    if restore_gaps:
        logger.error("Restored package diff detected in units: %s. Reverting...", restore_gaps)
        try:
            _apply_package(pre_restore_package.get("package") or {})
        except Exception as revert_exc:
            logger.critical("Failed to revert to pre-restore state after unit diff: %s", revert_exc)
        raise RuntimeError(
            "策略回滚失败且已恢复原状态: 以下单元未恢复到归档值 — " + "、".join(restore_gaps)
        )

    # 归档未覆盖、但当前存在的键（旧包无法删除后加键）：如实披露，不谎报「全盘回滚」
    archived_risk_keys = set((canonical_package_projection(pkg_payload).get("risk_config") or {}).keys())
    current_risk_keys = set((canonical_package_projection(new_package.get("package") or {}).get("risk_config") or {}).keys())
    extra_risk_keys = sorted(current_risk_keys - archived_risk_keys)
    return {
        "status": "restored",
        "target_policy_hash": archived_policy_hash,
        "target_package_hash": archived_package_hash or None,
        "restored_snapshot": new_snapshot,
        "restored_units": [unit for unit in _PACKAGE_UNITS if pkg_payload.get(unit) not in (None, {}, [])],
        "uncovered_risk_keys": extra_risk_keys,
        # 审计 P1-8b：回滚落盘的心法也过了一遍宪法门禁，违规条目在此点名
        "memory_review": memory_review or None,
    }

