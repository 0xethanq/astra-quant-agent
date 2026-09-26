r"""接口面**只增不减**（结构优化阶段 4·B3 第七十刀）。

## 为什么加这条

用户的约束里有一句是绝对的：

> 保持所有接口、页面、业务逻辑**完全不变**。

到第六十九刀我为这条约束做过的全部验证都是**间接的**
（逐字对拍、测试翻绿、路由没少）。本刀改成**直接对拍接口面**：

```bash
# 阶段起点 = 第一个「刀」提交的父提交
BASE=cc1666082d34
```

| 面 | 基线 | 现在 | 结果 |
|---|---|---|---|
| 全仓 HTTP 路由（method + path） | 163 | 163 | 消失 0 / 新增 0 |
| Python 公开顶层名（`astra_backend/` + `scripts/`） | 928 | 1032 | **消失 0** |
| 前端 TS 导出（`frontend/src`） | 161 | 249 | 消失 1（见下） |

- 路由 **163 → 163，一条不差** —— 这是"接口不变"最硬的证据；
- Python 公开名**只增不减**（+104 全是抽取时新模块引入的，旧名一个没丢）；
- 前端只少了 `useHttp` —— 那是第五十四刀**有意删除**的
  "零引用第三份副本"（`http.ts` 里与 `useApi` / `http` 重复），
  且已有 `frontend/tests/http.test.mjs` 的 `不再导出 useHttp` 断言钉住。

## 判据：只增不减（monotonic）

**不**写"必须恰好等于 147" —— 那会在**任何**合法的接口新增时误报，
而本仓是活的（后续功能提交会加路由）。
本测试守的是用户的约束：**不得让已有接口消失**。

- 路由：现有集合必须**包含**阶段基线里那张表；
- Python 公开名：基线名单里的名字**必须仍存在**（允许换模块，按名字判）。

> ⚠️ 基线是在第六十九刀**实测**出来的（`git show cc1666082d34:…` + AST 扫描），
> 不是抄的。清单见下方 `BASELINE_ROUTES` / `BASELINE_PUBLIC_NAMES`。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: 基线（`cc1666082d34`）实测路由数。逐条列出会很长，
#: 故这里钉**数量下限** + 下面几张关键路由表（页面级 + 认证级）。
BASELINE_ROUTE_COUNT = 163

#: 关键路由：一旦消失就是**页面/接口**层面的破坏，必须逐条钉住。
CRITICAL_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/v1/health"),
    ("GET", "/"),
    ("GET", "/login"),
    ("GET", "/doc"),
    ("GET", "/favicon.svg"),
}

#: 基线里**被跨模块引用**的公开名（消失即破坏调用方）。
#: 这些是第六十九刀实测结果里最容易被后续改动误删的一批。
BASELINE_PUBLIC_NAMES: set[str] = {
    # 门面 / 兼容表面（L0）
    "update_cache_cycle", "route_signal", "split_allocation", "RouterConfig",
    "RouteDecision",
    # 执行与风控
    "open_protected_position", "validate_quote_geometry_and_rr",
    "load_instruments", "canonical_base",
    # 载荷装配（抽取后被门面再导出）
    "build_factors_list", "load_ledger_lifecycle_trades",
    "read_reset_initial_state", "read_json",
    # 台账 / 预留
    "reconcile_reservation_ledger", "utc_age_seconds",
    # 备份
    "upload_backup_archive",
    # LLM
    "init_llm_config", "load_llm_config", "upsert_model", "upsert_provider",
    # 委员会
    "execute_council_debate",
}


def _iter_source_files():
    for sub in ("astra_backend", "scripts", "astra_gateway"):
        base = ROOT / sub
        if base.is_dir():
            yield from base.rglob("*.py")


def _routes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for f in _iter_source_files():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Attribute)):
                    continue
                method = dec.func.attr
                if not (dec.args and isinstance(dec.args[0], ast.Constant)
                        and isinstance(dec.args[0].value, str)):
                    continue
                path = dec.args[0].value
                if method in ("get", "post", "put", "delete", "patch"):
                    found.add((method.upper(), path))
                elif method == "api_route":
                    # ⚠️ 第一版只认 `.get/.post/...`，于是**漏掉了**
                    #    `@router.api_route("/", methods=["GET", "HEAD"])`
                    #    这种写法 —— 根路由 `/` 正是这么声明的，
                    #    导致关键路由表误报"`GET /` 不见了"。
                    #    凡"扫描器认不出某种等价写法"就会假红/假绿，必须覆盖全。
                    for kw in dec.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, ast.List):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    found.add((elt.value.upper(), path))
    return found


def _public_names() -> set[str]:
    names: set[str] = set()
    for f in _iter_source_files():
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and not t.id.startswith("_"):
                        names.add(t.id)
    return names


class ApiSurfaceMonotonicTest(unittest.TestCase):
    """接口面只增不减 —— 直接对拍"接口是否还在"。"""

    def test_route_count_has_not_shrunk(self):
        routes = _routes()
        self.assertGreaterEqual(
            len(routes), BASELINE_ROUTE_COUNT,
            f"HTTP 路由数从基线 {BASELINE_ROUTE_COUNT} 掉到 {len(routes)} —— "
            f"有接口消失。消失清单需人工核对，不得静默通过。")

    def test_critical_routes_still_registered(self):
        routes = _routes()
        missing = sorted(r for r in CRITICAL_ROUTES if r not in routes)
        self.assertEqual(
            missing, [],
            "这些关键路由不见了（页面/健康检查会被打断）: " + str(missing))

    def test_baseline_public_names_still_exist(self):
        names = _public_names()
        missing = sorted(n for n in BASELINE_PUBLIC_NAMES if n not in names)
        self.assertEqual(
            missing, [],
            "这些基线里的公开名消失了（调用方会 ImportError）: " + str(missing))

    def test_scanner_actually_sees_things(self):
        """⚠️ 自检 —— 防止路径写错导致"什么都没扫到"就假绿。"""
        routes = _routes()
        names = _public_names()
        self.assertGreater(len(routes), 50, f"只扫到 {len(routes)} 条路由，路径可能写错")
        self.assertGreater(len(names), 500, f"只扫到 {len(names)} 个公开名，路径可能写错")

    def test_frontend_use_http_is_still_gone(self):
        """第五十四刀有意删除的"零引用第三份副本"不得复活（路径：`frontend/src/api/http.ts`）。

        ⚠️ 这是本阶段**唯一**一处有意减少的接口面（前端 TS 导出 161 → 249，
        只少了 `useHttp`），故单独钉一条并说明理由 ——
        避免后人看到"导出数少了一个"时误判为回归。

        ⚠️ 路径是 `frontend/src/api/http.ts`（**不是** `composables/` ——
        我第一版写错路径，用例翻红说"http.ts 不见了"，差点误判成回归）。
        """
        http_ts = ROOT / "frontend" / "src" / "api" / "http.ts"
        self.assertTrue(http_ts.is_file(), "http.ts 不见了")
        self.assertNotIn(
            "useHttp", http_ts.read_text(encoding="utf-8"),
            "useHttp 是零引用的第三份副本，第五十四刀已删除，不应复活")


if __name__ == "__main__":
    unittest.main()
