"""Unit tests for server-side per-route SEO injection and crawler headers."""
from __future__ import annotations

import json
import re
import unittest
from fastapi.responses import FileResponse, HTMLResponse

from astra_backend.seo import NOINDEX_ROBOTS, PUBLIC_ROBOTS, inject_route_seo, normalize_public_path
from astra_backend.version import APP_SITE


SAMPLE_HTML = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>AstraQuant | 量化交易终端</title>
  <meta name="description" content="首页描述" />
  <meta name="robots" content="{PUBLIC_ROBOTS}" />
  <link rel="canonical" href="{APP_SITE}/" />
  <meta property="og:title" content="AstraQuant" />
  <meta property="og:description" content="首页 OG" />
  <meta property="og:url" content="{APP_SITE}/" />
  <meta property="og:image" content="{APP_SITE}/images/dashboard_preview.png" />
  <meta name="twitter:title" content="AstraQuant" />
  <meta name="twitter:description" content="首页 TW" />
  <meta name="twitter:url" content="{APP_SITE}/" />
  <meta name="twitter:image" content="{APP_SITE}/images/dashboard_preview.png" />
  <script type="application/ld+json">
  {{"@context":"https://schema.org","@graph":[{{"@type":"WebSite","@id":"{APP_SITE}/#website","url":"{APP_SITE}/"}}]}}
  </script>
</head>
<body><div id="app"></div></body>
</html>
"""


class SeoInjectionTests(unittest.TestCase):
    def test_normalize_public_path_maps_doc_aliases_to_docs(self):
        self.assertEqual(normalize_public_path("/doc"), "/docs")
        self.assertEqual(normalize_public_path("/doc/"), "/docs")
        self.assertEqual(normalize_public_path("/docs/architecture"), "/docs")
        self.assertEqual(normalize_public_path("/factors/"), "/factors")
        self.assertEqual(normalize_public_path("/"), "/")

    def test_public_subroute_rewrites_title_canonical_social_and_jsonld(self):
        src = HTMLResponse(SAMPLE_HTML, headers={"Cache-Control": "no-cache"})
        out = inject_route_seo(src, "/factors", is_public=True)
        body = out.body.decode("utf-8")
        self.assertIn("<title>AI 决策 | AstraQuant</title>", body)
        self.assertIn(f'<link rel="canonical" href="{APP_SITE}/factors"', body)
        self.assertIn(f'<meta property="og:url" content="{APP_SITE}/factors"', body)
        self.assertIn(f'<meta property="og:image" content="{APP_SITE}/images/v920_decisions.png"', body)
        self.assertIn(f'<meta name="twitter:image" content="{APP_SITE}/images/v920_decisions.png"', body)
        self.assertEqual(out.headers.get("cache-control"), "no-cache")
        self.assertNotIn("x-robots-tag", out.headers)
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S)
        assert match is not None
        graph_types = {node["@type"] for node in json.loads(match.group(1))["@graph"]}
        self.assertEqual(graph_types, {"WebSite", "WebPage", "BreadcrumbList"})

    def test_admin_route_sets_noindex_header_and_meta(self):
        src = HTMLResponse(SAMPLE_HTML)
        out = inject_route_seo(src, "/admin/agent", is_public=False)
        body = out.body.decode("utf-8")
        self.assertEqual(out.headers.get("x-robots-tag"), NOINDEX_ROBOTS)
        self.assertIn(f'content="{NOINDEX_ROBOTS}"', body)
        self.assertIn("<title>控制台 | AstraQuant</title>", body)

    def test_non_head_or_file_response_preserves_contract(self):
        plain = HTMLResponse("spa")
        self.assertIs(inject_route_seo(plain, "/trading", is_public=True), plain)
        admin_plain = HTMLResponse("spa")
        out = inject_route_seo(admin_plain, "/admin", is_public=False)
        self.assertEqual(out.headers.get("x-robots-tag"), NOINDEX_ROBOTS)
        f_resp = FileResponse(__file__)
        out_f = inject_route_seo(f_resp, "/admin/legacy.html", is_public=False)
        self.assertEqual(out_f.headers.get("x-robots-tag"), NOINDEX_ROBOTS)


if __name__ == "__main__":
    unittest.main()
