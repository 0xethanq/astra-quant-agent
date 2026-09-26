r"""gateway 路由拆分对拍门（结构整理 B8·第九十七刀）。

`astra_backend/routers/gateway.py`（977 行 / 34 路由）按资源拆成包
`astra_backend/routers/gateway/`（channels / gateway_ops / notifications / backups
+ `_shared.py`）。安全属性与 strategy 拆包同款：**路由表一字不变**。

## ⚠️ 路径归一化（本门特有）

`/api/v1/admin/backups/download/{filename:path}` 在 **OpenAPI 规格**里写作
`{filename}`（FastAPI 剥掉 `:path` 转换器），而源码里带 `:path`。
直接比字符串会得到一条"假缺失" —— 故两侧都按 `strip_path_converters()` 归一。
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "ec3fbd7"                       # 本刀动工前最后提交（第九十六刀收口）
BASELINE = "astra_backend/routers/gateway.py"
PKG = ROOT / "astra_backend" / "routers" / "gateway"
INCLUDE_ORDER = ("channels", "gateway_ops", "notifications", "backups")


def strip_path_converters(path: str) -> str:
    """`{filename:path}` → `{filename}`（与 OpenAPI 规格的写法对齐）。"""
    return re.sub(r"\{([^}:]+):[^}]+\}", r"{\1}", path)


def _routes_in(src: str) -> list:
    out = []
    for n in ast.parse(src).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
                    if d.args and isinstance(d.args[0], ast.Constant):
                        out.append((strip_path_converters(d.args[0].value),
                                    d.func.attr.upper(), n.name))
    return out


def _baseline_routes() -> list:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:{BASELINE}")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return _routes_in(r.stdout)


class GatewayRouterSplitTest(unittest.TestCase):
    def test_static_route_table_is_identical_and_ordered(self):
        want = _baseline_routes()
        self.assertEqual(len(want), 34, f"基线应有 34 条路由，实际 {len(want)}")
        got = []
        for name in INCLUDE_ORDER:
            got.extend(_routes_in((PKG / f"{name}.py").read_text(encoding="utf-8")))
        self.assertEqual(got, want, "路由表（路径/方法/处理器名/顺序）与拆分前不一致")

    def test_live_openapi_route_surface_unchanged(self):
        from astra_backend.app import app
        spec = app.openapi()
        live, tags = set(), {}
        for path, ops in spec["paths"].items():
            for method, op in ops.items():
                if "gateway" not in (op.get("tags") or []):
                    continue
                live.add((path, method.upper()))
                t = tuple(op.get("tags") or [])
                tags[t] = tags.get(t, 0) + 1
        want = {(p, m) for p, m, _ in _baseline_routes()}
        self.assertEqual(live, want, "线上接口面（路径×方法）与拆分前不一致")
        self.assertEqual(len(live), 34)
        self.assertEqual(tags, {("gateway",): 34},
                         "tags 必须恰好一处 ['gateway']（两处都加会重复）")

    def test_shared_helper_still_uses_injection_seam(self):
        """`_get_root()` 必须仍走 `app_attr` 注入缝（测试会往 app 模块上挂 ROOT）。"""
        src = (PKG / "_shared.py").read_text(encoding="utf-8")
        self.assertIn('app_attr("ROOT", ROOT)', src,
                      "_get_root 丢了注入缝 ⇒ 测试/多实例场景会取到真根目录")
        self.assertNotIn("def _get_root", (PKG / "backups.py").read_text(encoding="utf-8"))

    def test_aggregator_include_order_is_documented_order(self):
        src = (PKG / "__init__.py").read_text(encoding="utf-8")
        seq = []
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple):
                seq = [e.id for e in n.iter.elts if isinstance(e, ast.Name)]
        self.assertEqual(tuple(seq), INCLUDE_ORDER, "聚合顺序即匹配优先级，不得改变")
        self.assertIn("router = APIRouter()", src, "聚合器不得再加 tags")

    def test_old_module_path_still_importable(self):
        from astra_backend.routers.gateway import router
        self.assertEqual(len(router.routes), len(INCLUDE_ORDER), "应有 4 个子路由句柄")
        self.assertTrue(all(type(r).__name__ == "_IncludedRouter" for r in router.routes))

    def test_judgment_actually_notices_a_change(self):
        src = (PKG / "backups.py").read_text(encoding="utf-8")
        got = _routes_in(src)
        self.assertTrue(got)
        broken = src.replace('@router.post("/api/v1/admin/backups/restore")', '', 1)
        self.assertNotEqual(_routes_in(broken), got, "自检：判据看不见缺失的路由")


if __name__ == "__main__":
    unittest.main()
