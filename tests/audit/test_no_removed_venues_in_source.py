"""反向门：**已移除的多所源码不得回潮**（OKX 专用化配套）。

## 这道门在守什么

本仓已把 Binance 与 Gate 两家交易所的**源码面**整体移除（适配器、签名/下单构造器、
多所执行路由、选所路由包、跨所证据与看板聚合），系统收口为 OKX 专用。

"删干净"最怕的不是删错，而是**悄悄长回来**：一次复制粘贴、一段从旧提交里捞回来的
工具函数，就足以让"OKX 专用"变成一句空话。所以这里钉一道**反向**扫描门。

## 判据（结构化，不是 `contains` 放行）

1. `astra_backend/` 与 `scripts/` 下每个 `.py` 的**代码**（注释与文档字符串**除外**）
   不得出现下列字样（大小写不敏感）：

   `binance` / `BinanceAdapter` / `gate.py` / `GateAdapter` /
   `ASTRA_GATE_` / `ASTRA_BINANCE_` / `venue_routing` / `execution_router`

2. **"注释与文档字符串"是结构化排除的，不是"包含即过"**：本门用 `ast` 取出
   Module/Class/Function 的 docstring 节点位置、再用 `tokenize` 逐 token 剔除
   `COMMENT` 与**这些** `STRING`。普通代码里的字符串字面量（如 `"binance"`、
   `f"{venue}_API_KEY"`）**仍然在扫描范围内** —— 否则 `if venue == "binance"`
   这种真正的回潮会被放过。
   （理由：历史沿革说明留在 docstring/注释里是有价值的资产，删除它们反而丢信息；
   而它们的**行为**为零。）

3. 确有必须保留的**代码字面量** ⇒ 登记进 `ALLOWLIST`，键为 `(相对路径, 字样)`
   且**必须写明理由**；不允许按文件、按目录或按字样整体放行。登记表还会被反向
   自检（见下），不会腐烂。

## 自检（防空转）

- `test_scan_is_not_vacuous`：扫到的文件数必须够多（否则路径写错也会"全绿"）；
- `test_gate_has_teeth`：合成的回潮代码必须被抓；合成的**纯 docstring** 提及必须**不**被抓；
- `test_allowlist_is_explicit_and_alive`：每条放行都非空理由、文件存在、字样**真的出现**
  （过期登记会让门慢慢变成白名单垃圾桶）；
- `test_removed_modules_are_gone`：被删模块的路径确实不在树里。
"""

from __future__ import annotations

import ast
import io
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCAN_DIRS = ("astra_backend", "scripts")

#: 不得出现在**代码**里的字样（大小写不敏感）。
REMOVED_TOKENS = (
    "binance",
    "BinanceAdapter",
    "gate.py",
    "GateAdapter",
    "ASTRA_GATE_",
    "ASTRA_BINANCE_",
    "venue_routing",
    "execution_router",
)

#: 已删除的模块路径（存在即回潮）。
REMOVED_PATHS = (
    "astra_backend/exchanges/binance.py",
    "astra_backend/exchanges/binance_algo.py",
    "astra_backend/exchanges/binance_orders.py",
    "astra_backend/exchanges/binance_signing.py",
    "astra_backend/exchanges/gate.py",
    "astra_backend/execution_router.py",
    "astra_backend/venue_router.py",
    "astra_backend/venue_routing/__init__.py",
    "astra_backend/venue_routing/selection.py",
    "scripts/trader/venue_evidence.py",
    "scripts/brain/xvenue.py",
)

#: 显式白名单：`(相对路径, 字样) -> 理由`。**只允许具体到"某文件里的某个字样"**，
#: 且必须写明为什么这个代码字面量必须保留。
ALLOWLIST: dict[tuple[str, str], str] = {
    ("astra_backend/exchanges/routing_policy.py", "venue_routing"):
        "配置文件路径字面量 `data/venue_routing.json`：该配置文件由用户自行处置，"
        "本仓保留它的读写入口（preferred_venue / routing_mode 两个顶层键）；"
        "本模块内的函数名与日志前缀已全部去掉 venue_routing 字样，仅此一处路径常量。",
    ("scripts/news/importance.py", "binance"):
        "新闻**主题词表** `CRYPTO_MACRO_RELEVANT_KEYWORDS`：`binance` 在这里是"
        "「这条快讯是否与加密行业相关」的关键词之一（Binance 作为新闻主体依然存在），"
        "与交易所适配器/下单/凭证**毫无关系** —— 删掉它只会让新闻相关性过滤变差。",
    ("scripts/news/selection.py", "binance"):
        "同上：`CRYPTO_PLATFORMS` / `CRYPTO_SPECIFIC_KEYWORDS` 是新闻**来源白名单与"
        "主题词表**（判断一条快讯是不是币圈新闻），不是交易所集成面。"
        "Binance 仍是加密行业的新闻主体，保留该关键词是内容判定，不是回潮。",
}


def _docstring_positions(tree: ast.AST) -> set:
    """所有 Module/Class/Function docstring 的 `(行, 列)` 起点。"""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add((body[0].value.lineno, body[0].value.col_offset))
    return out


def code_text(source: str) -> str:
    """去掉注释与文档字符串后的**代码**文本（普通字符串字面量保留）。"""
    raw = source.encode("utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source                      # 解析不了就按原文判（更严，不放水）
    docs = _docstring_positions(tree)
    pieces = []
    try:
        for tok in tokenize.tokenize(io.BytesIO(raw).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and (tok.start[0], tok.start[1]) in docs:
                continue
            pieces.append(tok.string)
    except Exception:
        return source                      # tokenize 失败同上：按原文判
    return "\n".join(pieces)


def _iter_py():
    for root in SCAN_DIRS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path.relative_to(ROOT).as_posix(), path


def scan_source(source: str, rel: str) -> list:
    """该文件的回潮命中（已扣除白名单）→ `[(字样, 理由 or None)]`。"""
    code = code_text(source)
    low = code.lower()
    hits = []
    for token in REMOVED_TOKENS:
        if token.lower() not in low:
            continue
        hits.append((token, ALLOWLIST.get((rel, token))))
    return hits


class NoRemovedVenuesInSourceTest(unittest.TestCase):
    def test_no_removed_venue_token_in_code(self):
        problems = []
        for rel, path in _iter_py():
            for token, reason in scan_source(path.read_text(encoding="utf-8"), rel):
                if reason:
                    continue
                problems.append(f"{rel}: 代码里出现已移除字样 {token!r}")
        self.assertEqual(problems, [], "已移除的多所源码回潮了（本系统已 OKX 专用）：\n"
                                       + "\n".join(problems))

    def test_removed_modules_are_gone(self):
        present = [p for p in REMOVED_PATHS if (ROOT / p).exists()]
        self.assertEqual(present, [], f"已删除的模块又出现了：{present}")

    def test_scan_is_not_vacuous(self):
        files = list(_iter_py())
        self.assertGreaterEqual(len(files), 150, f"只扫到 {len(files)} 个 .py ⇒ 扫描路径可能写错")
        rels = {rel for rel, _ in files}
        for must in ("scripts/ai_factor_trader.py",
                     "scripts/trader/order_submit.py",
                     "astra_backend/exchanges/registry.py"):
            self.assertIn(must, rels, f"{must} 未被扫描 ⇒ 范围失效")

    def test_gate_has_teeth(self):
        """合成回潮必须被抓；纯 docstring 提及必须**不**被抓。"""
        hit = scan_source('def f(venue):\n    return venue == "binance"\n', "scripts/x.py")
        self.assertIn(("binance", None), hit, "代码里的 'binance' 没被抓到 ⇒ 门没有牙齿")
        hit2 = scan_source(
            'import os\n\n\ndef f():\n    """历史：曾支持 Binance 与 Gate。"""\n'
            '    # 旧实现读 ASTRA_GATE_EXECUTION\n'
            '    return os.environ.get("OKX_API_KEY")\n', "scripts/y.py")
        self.assertEqual(hit2, [], "纯注释/文档字符串的历史说明不该被判红（结构化排除失效）")
        # …但同一段文字若出现在**普通字符串**里，必须照抓（排除规则不得放宽）
        hit3 = scan_source('X = "曾支持 Binance"\n', "scripts/z.py")
        self.assertIn(("binance", None), hit3, "普通字符串字面量里的回潮被放过了 ⇒ 排除过宽")

    def test_allowlist_is_explicit_and_alive(self):
        for (rel, token), reason in ALLOWLIST.items():
            self.assertGreaterEqual(len(str(reason).strip()), 20, f"{(rel, token)} 的理由太短")
            path = ROOT / rel
            self.assertTrue(path.is_file(), f"白名单过期：{rel} 不存在")
            hits = {t for t, _ in scan_source(path.read_text(encoding="utf-8"), rel)}
            self.assertIn(token, hits, f"白名单过期：{rel} 里已不再出现 {token!r}，请删除该条登记")
        # 白名单不得按目录/按 token 整体放行
        for rel, _token in ALLOWLIST:
            self.assertTrue(rel.endswith(".py"), f"白名单必须精确到文件：{rel}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
