"""品牌与命名空间门禁：**对外面必须叫 AstraQuant，内部命名空间必须叫 astra。**

## 这条门禁的来历（两次事故）

### 事故一（2026-09-27 之前）：改名只改了"主品牌串"
2026-09 把对外品牌改成 `AstraQuant` 时，只动了版本常量、路由标题和几个组件。
于是这些**用户直接看得见**的地方还散着旧品牌与旧域名：

| 面 | 残留 | 用户会怎么撞上 |
|---|---|---|
| SEO 元数据 | `frontend/index.html` 的 canonical / og:* / twitter:* / JSON-LD 全指 `www.r20.cn` | 搜索引擎按 canonical 认为正主是**旧域名** —— 新站点的权重全被让出去 |
| 站点地图 | `sitemap.xml` / `robots.txt` 六条 URL 全是旧域名 | 提交给搜索引擎的就是错的 |
| 运行时 SEO 兜底 | `astra_backend/routers/dashboard.py` 里写死的域名 | 与静态资源不一致 |
| 界面文案 | `locales/*/admin/login.ts`（`R20 控制台`）、`dash/about.ts`（`关于 R20`）、`dash/matrix.ts`（剪贴板 `【R20 风控测算】`） | 顶栏、关于浮层、**用户粘贴到群里的文案** |
| 路由标题 | `router/index.ts` 里 5 处 ` · R20` | 浏览器标签页 |
| 部署物料 | `deploy/r20-*.service` 的 `Description`、Grafana 面板标题、`LICENSE` 版权行 | `systemctl status` / 面板 / GitHub 仓库页 |

### 事故二（2026-09-27）：内部代号 `r20` 全量改名 `astra`
包名、154 个文件名、129 个 `R20_*` 环境变量键、会话头、确认短语、运行态文件名
全部改为 `astra`。**硬切**：旧的 `R20_*` 不再被读取，用户必须改自己的 `.env`。

## 本门守三件事

### 判据一：旧品牌/旧域名串不得回潮
`R20 Quantum Trader` / `R20-Quantum-Trader` / `www.r20.cn` / `关于 R20` /
`R20 控制台` / `About R20` / `R20 Console` 出现在**任何被跟踪文件**即为翻红。

### 判据二：旧命名空间前缀 `r20` 只许出现在**已声明并写明理由**的地方
全量改名之后，`r20` 这个词本不该再出现。但确实有几处**必须**保留它，
每一处都在 `LEGACY_ALLOWED` 里逐文件登记并写明理由（见该表的注释）。

> 为什么这条比"禁止 r20"更值钱：单说"禁止"会把有意的兼容也一起判红，
> 于是下一个人只能去放宽门禁；逐条登记理由则让**每一次新增例外都必须解释**。

### 判据三：站点 URL 必须单一来源、多处同源
`https://www.astraquant.tech` 是规范形态（**带 www**，与 DNS 实际解析一致；
裸域 `astraquant.tech` 在 2026-09-27 实测**无 A 记录**、不可达）。
它必须在这五处完全一致：

1. `astra_backend/version.py::APP_SITE` —— 后端单一来源
2. `frontend/src/config/version.ts::OFFICIAL_SITE`
3. `frontend/index.html` 的 `rel="canonical"`
4. 同文件的 `og:url` 与 `twitter:url`
5. 同文件 JSON-LD 的 `@id` 前缀

**为什么值得钉**：canonical 与 og:url 不一致时，搜索引擎会自己挑一个 ——
而历史上挑中的那个正是**旧域名**。这就是事故一的真实形态。

顺带钉住：`astra_backend/routers/dashboard.py` 里**不得再写死域名**（必须走 `APP_SITE`），
以及仓库 URL 不得回退到旧仓库名 `r20-quantum-trader`。
"""
from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: 旧**品牌/域名**形态（必须彻底消失）。
BANNED = (
    "R20 Quantum Trader",
    "R20 QUANTUM TRADER",
    "R20-Quantum-Trader",
    "www.r20.cn",
    "关于 R20",
    "R20 控制台",
    "About R20",
    "R20 Console",
)

#: 判据二的允许表：**路径 → 为什么这里必须留着 `r20`**。
#: 新增一条例外 = 必须在这里解释清楚，否则门禁翻红。
LEGACY_ALLOWED: "dict[str, str]" = {
    # —— 交易所侧的历史数据兼容（改不了别人服务器上的单子）——
    "scripts/tag_markers.py":
        "交易所上改名前创建的保护腿带的是 `t-r20sl*` 标记。只认新标记会让这些腿被判成"
        "「不是我们的」⇒ 云端棘轮对已有仓位静默失效。这里保留的是**历史数据**的识别字面量，"
        "不是旧配置兼容（`R20_*` 环境变量已硬切）。",
    "scripts/backup_runtime.py":
        "`LEGACY_MAGIC`：改名前的备份归档魔数。用户手里已有的归档必须仍能解密，"
        "否则「改名」= 「备份全废」。与新魔数**等长**，故头部偏移不变。",
    # —— 抽取门禁：基线取自"改名前的提交"，且要显式声明这次迁移 ——
    "tests/extraction/rename_baseline.py":
        "基线适配层：它的**全部作用**就是把老提交里的 `r20_*` 记号映射到新记号。"
        "文件名与函数体里的 `r20` 正是这条映射本身。",
    "tests/extraction/test_trader_cycle_stages_extraction.py":
        "SEGMENT_DELTAS 的 **old_text 侧必须与老提交逐字一致** —— 把这里的 `r20` 改掉，"
        "这道门就失去与基线对拍的能力。",
    "tests/extraction/test_trader_cloud_protection_extraction.py":
        "同上：`_DELTA_BLOCKS` 与注释在说明这次改名对段体做了哪一处有意修改。",
    "tests/extraction/test_trader_circuit_guard_extraction.py":
        "`_src()` 的注释与 `normalize()` 调用在显式声明：这道门取的基线来自改名前的提交，"
        "段体差异来自那次命名空间迁移，不是搬运事故。",
    "tests/extraction/test_trader_order_submit_extraction.py":
        "同上：`BODY_DELTAS` 与注释记录段体的有意变更来源。",
    "tests/extraction/test_trader_routing_policy_extraction.py":
        "`_base_text()` 的注释与 `normalize()` 调用在显式声明：基线取自改名前的提交，"
        "段体差异源于那次命名空间迁移。",
    "scripts/migrate_r20_to_astra.py":
        "一次性迁移工具的**文件名与内容本来就带旧代号**（它的职责就是把 r20 时代的数据"
        "搬到 astra）；登记它是为了让人搜得到迁移入口，而不是把它改名藏起来。",
    "tests/extraction/test_gateway_pidfile_extraction.py":
        "注释在说明白名单为什么必须放行一次性迁移工具（它要按新旧两个名字搬迁 pid 文件）。",
    "tests/trading/test_venue_protection.py":
        "注释在记录本类原来写死的行号被改名打红这件事，以及为什么改为由 AST 现求。",
    "tests/ops/test_migrate_r20_to_astra.py":
        "迁移工具自身的门禁：它必须写出旧名与旧记号，才能验证「搬迁」这件事真的发生"
        "（`RUNTIME_FILE_NAMES`、`CONFIG_TEXT_TOKENS`、退出码 3 等）。",
    "tests/ui/test_sync_web_data_single_read.py":
        "注释在说明依赖对拍为什么要先做命名空间归一（基线取自改名前的提交，"
        "直接比会把迁移误判成「新增第三方依赖」），必须点出旧包名才能讲清。",
    "tests/llm/test_rename_keeps_prompt_module_ids_safe.py":
        "种子安全性判据本身：它必须写出**改名前的种子**才能断言活代码里不再用它，"
        "并证明出厂基线没持久化这类 id、合并按标题而非 id 匹配。",
    "tests/audit/test_runtime_config_has_no_legacy_namespace.py":
        "运行态配置判据自身：它必须写出 `R20_` 形态的记号，才能定义什么算旧名，"
        "并逐条登记 `R20_Backups` 这类有意保留的外部位置名。",
    # —— 其它门禁的注释/夹具 ——
    "tests/core/test_dependency_manifest_unchanged.py":
        "注释记录「改名只动了 requirements.txt 的表头注释、依赖项零变动」这件事本身。",
    "tests/ops/test_backup_runtime_internals.py":
        "双魔数兼容的判据用例：它必须把**旧魔数**写出来才能验证老归档可解。",
    "tests/llm/test_evolution_observability.py":
        "夹具里的 `https://cpa.r20.cn/v1` 是**用户自有域名**（其模型网关），不是我们的命名空间。",
    "tests/llm/test_llm_v4_url_and_scoped_delete.py":
        "同上：`cpa.r20.cn` 是用户自有域名。",
    "scripts/prompt_templates.py":
        "注释记录 base 模块 id 种子从 `r20-base-module::` 改为 `astra-base-module::` "
        "这件事与三条安全性证据（种子不是持久化契约）。",
    "tests/audit/test_brand_strings_are_consistent.py":
        "门禁自身：`BANNED` 列表必须写出被禁的旧串，否则它无法判红。",
    ".gitignore":
        "过渡期守卫：改名前的运行态文件（`.r20_gateway_heartbeat` / `.r20_*.lock` …）"
        "在数据迁移跑完前仍在磁盘上，且**没有扩展名** —— 不忽略它们就会重演"
        "「无扩展名文件绕过扩展名白名单被 `git add -A` 加进仓库」那次事故。",
    "scripts/README.md":
        "脚本导航必须登记 `migrate_r20_to_astra.py`（一次性迁移工具，文件名里带旧代号）"
        "并说明 `tag_markers.py` 归一的是旧标记 —— 去掉这两处会让人找不到迁移入口。",
    "tests/audit/test_directory_docs_current.py":
        "子包判据的注释在记录一个历史洞：旧包名 `r20_backend` 含数字，正则 `[a-z_]+` "
        "匹配不到，所以那个误判直到改名成 `astra_backend` 才暴露。",
    "deploy/docker-entrypoint.sh":
        "启动前置检查的注释必须写明被检查的是什么（改名前的运行态数据），"
        "否则下一个人看到这段 fail-closed 会不知道它在防哪一类事故。",
    "start.sh":
        "与 docker-entrypoint 同一段前置检查：两个启动入口都必须接上，"
        "漏接一个就等于那条 fail-closed 形同虚设（注释里必须点明被检查的是什么）。",
    # —— 文档与历史素材 ——
    "README.md":
        "「Brand & codename」一节必须写明**哪些历史形态是有意保留的**（含旧域名与旧魔数），"
        "否则下一个人会再来一次「改名不彻底」。",
    "README.zh-CN.md":
        "中文版「品牌与内部代号」一节必须写明哪些历史形态（旧域名、旧归档魔数、旧标记）"
        "是有意保留的 —— 否则下一个人会再来一次「改名不彻底」。",
    "docs/images/v751_features_summary.png":
        "历史功能截图（二进制）。它记录的是**当时**的界面，改写截图等于篡改历史记录；"
        "`docs/images/` 按快照对待。",
}

#: 判据一的允许表：**路径 → 为什么这里必须写出被禁串**。
#: 只有两种正当理由：①它对拍基线必须逐字一致；②它在记录"旧串到底是什么"。
BANNED_ALLOWED: "dict[str, str]" = {
    "tests/extraction/test_trader_cycle_stages_extraction.py":
        "`SEGMENT_DELTAS` 的 old_text 侧必须与**改名前的提交**逐字一致；"
        "这里正是那个旧串本身，改掉它这道对拍门就废了。",
    "tests/core/test_dependency_manifest_unchanged.py":
        "注释需要写明被改掉的那行**原文**（`requirements.txt` 的表头注释），"
        "否则下次变更的人无法判断这次哈希更新是否合理。",
}

#: 规范站点与仓库（判据三的期望值）。
EXPECTED_SITE = "https://www.astraquant.tech"
EXPECTED_REPO = "https://github.com/0xethanq/astra-quant-agent"


def _tracked_files() -> "list[str]":
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, f"git ls-files 失败：{out.stderr[:200]}"
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""       # 二进制资源（png 等）不参与文本判据


#: 判据一/二扫描时**排除门禁自身**：它必须把被禁串与 `r20` 字面量写出来才能判红，
#: 否则这道门会因为"自己提到自己"而永远翻红（本仓记录过同类自匹配事故）。
SELF = "tests/audit/test_brand_strings_are_consistent.py"


def _grep_literal(token: str, *, ignore_case: bool = False) -> "list[str]":
    """在被跟踪文件里找字面量，返回命中文件列表。

    ⚠️ **为什么走 `git grep` 而不是 Python 读文件**：本判据要扫的 `data/` 下文件
    （出厂预设标题就是用户可见的品牌面）在 `tests/__init__.py` 的「生产配置读守卫」
    保护名单里，Python 侧读 `data/` 会在严格模式 `ASTRA_TESTS_STRICT_READS=1` 下
    **直接抛错** —— 而"严格模式全绿"是本仓的不变量（见 `docs/FAILURE_SEMANTICS.md`）。
    走 git 子进程能扫到同一份工作树内容，又完全不触发那条守卫。
    """
    cmd = ["git", "grep", "-F", "-l", "-e", token]
    if ignore_case:
        cmd.insert(2, "-i")
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if out.returncode not in (0, 1):        # 1 = 无命中，不是错误
        raise AssertionError(f"git grep 失败（token={token!r}）：{out.stderr[:200]}")
    return [ln for ln in out.stdout.splitlines() if ln.strip() and ln.strip() != SELF]


class BrandStringsNotRegressedTest(unittest.TestCase):
    """判据一：旧品牌串不得回潮。"""

    def test_scan_is_not_vacuous(self):
        """闸自检：被扫文件数必须够多，否则"零命中"毫无意义。"""
        files = _tracked_files()
        self.assertGreater(len(files), 200, f"只扫到 {len(files)} 个被跟踪文件 ⇒ 扫描范围失效")

    def test_detector_actually_matches(self):
        """闸自检：**检索通道**本身要能命中。

        只断言"BANNED 里的串非空"是不够的 —— 检索一旦坏掉（cwd 错、git grep 参数错、
        范围被写成空集），"零命中"同样是绿。故加一条**正向对照**：仓库里必然存在的
        新品牌串必须被同一通道找出来。
        """
        self.assertEqual([t for t in BANNED if not t.strip()], [], "BANNED 里有空串")
        hits = _grep_literal("AstraQuant")
        self.assertGreaterEqual(
            len(hits), 5,
            f"正向对照失败：`git grep AstraQuant` 只命中 {len(hits)} 个文件 —— 检索通道坏了，"
            "此时'没有旧品牌串'是假绿")

    def test_no_banned_brand_string_anywhere(self):
        offenders: "dict[str, list[str]]" = {}
        for tok in BANNED:
            for rel in _grep_literal(tok):
                if rel in BANNED_ALLOWED:
                    continue
                offenders.setdefault(rel, []).append(tok)
        self.assertEqual(
            offenders, {},
            "对外面出现旧品牌/旧域名 —— 用户看得到的地方仍是旧名字：\n  "
            + "\n  ".join(f"{f}: {sorted(set(t))}" for f, t in sorted(offenders.items())))


class LegacyNamespaceIsContainedTest(unittest.TestCase):
    """判据二：旧命名空间前缀 `r20` 只许出现在**已登记例外**里。"""

    def test_the_allowlist_entries_all_exist_and_explain_themselves(self):
        files = set(_tracked_files())
        for rel, reason in LEGACY_ALLOWED.items():
            with self.subTest(f=rel):
                self.assertIn(rel, files, f"允许表里的 {rel} 不在仓库里（表过期了）")
                self.assertGreater(len(reason), 20,
                                   f"{rel} 的例外理由太短 —— 必须说清为什么必须留着 r20")

    def test_allowlist_is_not_stale(self):
        """反向断言：允许表里的每条都**真的**命中过 `r20`。

        否则表会越积越长：某人删掉了 `r20` 却留着允许条目，
        于是"允许表"渐渐变成一份与现实无关的清单。
        """
        stale = []
        for rel in LEGACY_ALLOWED:
            if not rel.endswith(".png") and "r20" not in _read(rel).lower():
                stale.append(rel)
        self.assertEqual(stale, [], f"这些文件已经不含 r20 了，请从 LEGACY_ALLOWED 里删掉：{stale}")

    def test_r20_namespace_appears_only_in_declared_places(self):
        hits = set(_grep_literal("r20", ignore_case=True))
        undeclared = sorted(hits - set(LEGACY_ALLOWED))
        self.assertEqual(
            undeclared, [],
            "全量改名后 `r20` 不该再出现；以下文件里还有它却**没有登记理由**：\n  "
            + "\n  ".join(undeclared)
            + "\n（若确属必须保留的历史兼容，请连同理由加进 LEGACY_ALLOWED；"
            "否则请把它改成 astra。）")

    def test_the_rename_actually_happened(self):
        """正向断言：改名的主力成果必须还在（防止有人"回滚"了改名）。"""
        files = _tracked_files()
        self.assertIn("astra_backend/version.py", files)
        self.assertIn("astra_gateway/worker.py", files)
        self.assertNotIn("r20_backend/version.py", files)
        self.assertNotIn("r20_gateway/worker.py", files)
        # ⚠️ 唯一允许带旧代号的文件名：一次性迁移工具。它的名字必须让人一眼看懂"这是把
        #    r20 时代的数据搬到 astra 的入口"，改成别的名字反而会让人找不到它。
        MIGRATION_TOOL = "scripts/migrate_r20_to_astra.py"
        MIGRATION_GATE = "tests/ops/test_migrate_r20_to_astra.py"
        legacy = [f for f in files
                  if "r20" in f.lower() and f not in (MIGRATION_TOOL, MIGRATION_GATE)]
        self.assertEqual(legacy, [], f"仍有文件名带 r20：{legacy}")


class SiteUrlIsSingleSourceTest(unittest.TestCase):
    """判据三：规范站点 URL 必须单一来源、多处同源。"""

    def _py_app_site(self) -> str:
        m = re.search(r'^APP_SITE\s*=\s*"([^"]+)"', _read("astra_backend/version.py"), re.M)
        self.assertIsNotNone(m, "astra_backend/version.py 缺少 APP_SITE 常量")
        return m.group(1)

    def _ts_official_site(self) -> str:
        m = re.search(r"OFFICIAL_SITE\s*=\s*'([^']+)'",
                      _read("frontend/src/config/version.ts"))
        self.assertIsNotNone(m, "frontend/src/config/version.ts 缺少 OFFICIAL_SITE 常量")
        return m.group(1)

    def test_python_and_typescript_brand_sources_agree(self):
        self.assertEqual(self._py_app_site(), EXPECTED_SITE,
                         "后端 APP_SITE 不是规范形态（注意：**带 www**；裸域无 A 记录）")
        self.assertEqual(self._ts_official_site(), EXPECTED_SITE,
                         "前端 OFFICIAL_SITE 不是规范形态（注意：**带 www**）")

    def test_index_html_seo_metadata_is_same_origin(self):
        html = _read("frontend/index.html")
        self.assertTrue(html, "frontend/index.html 读不到")
        got = {
            "rel=canonical": re.search(r'rel="canonical" href="([^"]+)"', html),
            "og:url": re.search(r'property="og:url" content="([^"]+)"', html),
            "twitter:url": re.search(r'name="twitter:url" content="([^"]+)"', html),
        }
        for label, m in got.items():
            self.assertIsNotNone(m, f"index.html 缺少 {label}（会被搜索引擎当成无主页面）")
        origins = {m.group(1).rstrip("/") for m in got.values()}
        self.assertEqual(len(origins), 1,
                         f"canonical / og:url / twitter:url 不同源：{sorted(origins)} "
                         "⇒ 搜索引擎会自己挑一个，历史教训是它挑中了旧域名")
        self.assertEqual(origins.pop(), EXPECTED_SITE, "SEO 元数据指向的不是规范站点")

    def test_jsonld_ids_point_at_the_canonical_site(self):
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                            _read("frontend/index.html"), re.S)
        self.assertEqual(len(blocks), 1, "index.html 应恰好有一段 JSON-LD")
        graph = json.loads(blocks[0])["@graph"]
        self.assertTrue(graph, "JSON-LD @graph 为空")
        for node in graph:
            self.assertTrue(node.get("@id", "").startswith(EXPECTED_SITE),
                            f"JSON-LD @id 不在规范站点下：{node.get('@id')!r}")
            self.assertTrue(str(node.get("url", "")).startswith(EXPECTED_SITE),
                            f"JSON-LD url 不在规范站点下：{node.get('url')!r}")

    def test_robots_and_sitemap_use_the_canonical_origin(self):
        """⚠️ 只判**站点自身的 URL**：sitemap 的 XML 命名空间（w3.org / sitemaps.org）
        是协议要求的固定常量，把它们算进来只会制造噪音。"""
        robots = _read("frontend/public/robots.txt")
        self.assertTrue(robots, "frontend/public/robots.txt 读不到")
        robots_urls = re.findall(r"^(?:Host|Sitemap):\s*(\S+)\s*$", robots, re.M)
        self.assertTrue(robots_urls, "robots.txt 里没有 Host/Sitemap 行 ⇒ 判据失效")
        bad = sorted({u for u in robots_urls if not u.startswith(EXPECTED_SITE)})
        self.assertEqual(bad, [], f"robots.txt 指向了非规范站点：{bad}")

        sitemap = _read("frontend/public/sitemap.xml")
        self.assertTrue(sitemap, "frontend/public/sitemap.xml 读不到")
        locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
        self.assertTrue(locs, "sitemap.xml 里没有 <loc> ⇒ 判据失效")
        bad_loc = sorted({u for u in locs if not u.startswith(EXPECTED_SITE)})
        self.assertEqual(bad_loc, [], f"sitemap.xml 的 <loc> 指向了非规范站点：{bad_loc}")

    def test_runtime_seo_endpoints_have_no_hardcoded_domain(self):
        """运行期兜底（`/robots.txt` `/sitemap.xml`）必须走单一来源，不得再写死域名。"""
        src = _read("astra_backend/routers/dashboard.py")
        self.assertTrue(src, "astra_backend/routers/dashboard.py 读不到")
        self.assertIn("from astra_backend.version import APP_SITE", src,
                      "运行期 SEO 兜底应引用 APP_SITE 单一来源")
        for hard in ("www.r20.cn", "astraquant.tech"):
            self.assertNotIn(hard, src,
                             f"routers/dashboard.py 又写死了域名 {hard!r} —— 请改用 APP_SITE")

    def test_repository_url_is_the_renamed_repo(self):
        """⚠️ 只判**仓库 URL**形态。裸串 `r20-quantum-trader` 仍会合法出现 ——
        它是有意保留的部署路径 / Grafana UID（见 README「品牌与内部代号」），
        一刀切会让那条有意为之的说明反而过不了门。"""
        stale_url = "github.com/555cute/r20-quantum-trader"
        for rel in ("README.md", "README.zh-CN.md", "frontend/src/config/version.ts",
                    "astra_backend/routers/system.py", "frontend/src/views/docs/DocsView.vue"):
            self.assertNotIn(stale_url, _read(rel),
                             f"{rel} 里还有旧仓库 URL（改名后是 404 链接）")
        self.assertIn(EXPECTED_REPO, _read("frontend/src/config/version.ts"))
        self.assertIn(EXPECTED_REPO, _read("astra_backend/routers/system.py"))


if __name__ == "__main__":
    unittest.main()
