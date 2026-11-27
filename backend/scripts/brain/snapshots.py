"""主脑周期的**本地快照落盘**（B3 抽取，`ai_brain_trader.py` 第三块）。

从 `scripts/ai_brain_trader.py::execute_batch_ai_brain_cycle` 搬出两处"写本地快照"：

| 函数 | 内容 |
|---|---|
| `update_factor_library_snapshot` | 因子库自更新（`sys.path` 追加 + `factor_library.update_factor_library()`，失败仅告警） |
| `write_prompt_snapshot` | 实时提示词快照落盘（Web 透明检视用；tmp + replace 原子替换） |

注：原 `write_calculus_snapshot` 已随数理退役链路整体拆除（2026-10）。

## 为什么能安全搬

- 两段**都是纯副作用**（0 个输出、0 个 `return`）—— 失败被各自的 `try/except` 吞掉并打印告警，
  控制流不依赖它们的产物；
- 段体 **AST 逐字**（对拍门 `tests/extraction/test_brain_snapshots_extraction.py`）；
- 全部自由名**同名 kw-only 入参**（`os`/`sys`/`json` 亦按名注入）⇒ 门面调用期解析。
"""
from __future__ import annotations


def update_factor_library_snapshot(*,
        WORKSPACE_DIR,
        os,
        sys):
    try:
        import time as _time
        snap_file = os.path.join(WORKSPACE_DIR, "data", "factor_library_snapshot.json")
        try:
            fresh_ttl = float(os.getenv("ASTRA_FACTOR_SNAPSHOT_FRESH_SECONDS", "180") or 180)
        except (TypeError, ValueError):
            fresh_ttl = 180.0
        if fresh_ttl > 0 and os.path.exists(snap_file):
            try:
                if os.path.getsize(snap_file) > 50:
                    age_s = _time.time() - os.path.getmtime(snap_file)
                    if 0 <= age_s < fresh_ttl:
                        print(f"[AI Brain Batch] 复用新鲜因子库快照（age={age_s:.0f}s < {fresh_ttl:.0f}s），跳过重复同步刷新")
                        return
            except OSError:
                pass
        sys.path.append(os.path.join(WORKSPACE_DIR, "scripts"))
        import factor_library
        factor_library.update_factor_library()
    except Exception as e:
        print(f"[AI Brain Batch] Factor Library update warning: {e}")


def write_prompt_snapshot(*,
        AI_LAST_PROMPT_FILE,
        _build_effective_prompt_text,
        effective_system_prompt,
        os,
        prompt,
        time_str):
    try:
        tmp_prompt = AI_LAST_PROMPT_FILE + ".tmp"
        with open(tmp_prompt, "w", encoding="utf-8") as f:
            f.write(_build_effective_prompt_text(
                effective_system_prompt=effective_system_prompt, policy_version="",
                time_str=time_str, prompt=prompt))
        os.replace(tmp_prompt, AI_LAST_PROMPT_FILE)
    except Exception:
        pass

