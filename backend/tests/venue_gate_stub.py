"""直签所（OKX）入场闸门的**零网络适配器替身**（2026-09-28 三所平权配套）。

## 为什么需要它

`submit_protected_limit_order` 现在会在**多所分发之前**对不经 `execution_router`
的直签所跑一遍共用入场闸门（池 / 跨所敞口 / 持仓模式）。闸门为了算 `max_open`
与体检持仓模式，会通过 `astra_backend.exchanges.registry.get_adapter(venue)`
取一个适配器。

那些用例（下单守卫、路由阶段、venue wiring 等）注入的是**假 `okx_rest`**，
而适配器走的是**真的** `scripts.okx_rest` ⇒ 测试里会真的触网（或抛 OKX 50011），
闸门于是按 fail-closed 拒单，用例测的就不再是它本来要测的东西。

这与 router 侧既有的做法一致：`tests/audit/test_audit_config_p1b_guards.py`
的 `_Stub` 也**显式**给出 `detect_position_mode()`，并在注释里写明
「桩必须像真适配器一样**明确**给出模式，否则这些用例测的就不再是它们本来要测的东西」。

## 用法

    from tests.venue_gate_stub import direct_venue_gate_adapter

    with direct_venue_gate_adapter(mode="long_short"):
        submit_protected_limit_order(...)      # 闸门拿到零网络适配器

`declared_modes=()` 会让闸门**跳过**模式体检（`mode_checked=False`）——
想在用例里完全绕开模式项时用它。
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Optional
from unittest.mock import patch

#: 与真实 OKX 适配器一致（`astra_backend/exchanges/okx.py`）
OKX_DECLARED_MODES = ("net", "long_short")
OKX_ENTRY_READY_MODES = ("long_short",)


class _GateStubAdapter:
    """只实现闸门会碰的那几样：`capabilities` / `positions` / `detect_position_mode`。"""

    def __init__(self, *, positions: Optional[Iterable[Dict[str, Any]]] = None,
                 mode: str = "long_short",
                 declared_modes: Iterable[str] = OKX_DECLARED_MODES,
                 entry_ready_modes: Iterable[str] = OKX_ENTRY_READY_MODES,
                 positions_raises: Optional[BaseException] = None):
        self.calls: list = []
        self._positions = list(positions or [])
        self._mode = mode
        self._raises = positions_raises
        self.capabilities = SimpleNamespace(
            position_modes=tuple(declared_modes),
            entry_ready_position_modes=tuple(entry_ready_modes),
        )

    def positions(self):
        self.calls.append(("positions",))
        if self._raises is not None:
            raise self._raises
        return list(self._positions)

    def detect_position_mode(self) -> str:
        self.calls.append(("mode",))
        return self._mode


@contextmanager
def direct_venue_gate_adapter(**kwargs):
    """把**任何**场所的适配器换成零网络替身，作用域内有效。

    `kwargs` 透传给 `_GateStubAdapter`（`positions` / `mode` / `declared_modes` /
    `entry_ready_modes` / `positions_raises`）。
    """
    stub = _GateStubAdapter(**kwargs)
    with patch("astra_backend.exchanges.registry.get_adapter", return_value=stub):
        yield stub
