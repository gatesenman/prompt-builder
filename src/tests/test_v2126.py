"""2.12.8 — archive scope tab · remove library more/batch chrome."""
from __future__ import annotations
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestVersion2126(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)
        cl = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 2.12.8", cl)


class TestLibScopeArchTab(unittest.TestCase):
    def test_three_tabs_order(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        chunk = html[html.find('id="libScope"') : html.find('id="list"')]
        i_all = chunk.find('id="libScopeAll"')
        i_fav = chunk.find('id="libScopeFav"')
        i_arch = chunk.find('id="libScopeArch"')
        self.assertGreater(i_fav, i_all)
        self.assertGreater(i_arch, i_fav)
        self.assertIn('data-scope="archived"', chunk)
        self.assertIn("归档", chunk)
        # 归档 appears as tab label after 收藏
        fav_label = chunk.find(">收藏<")
        arch_label = chunk.find(">归档<")
        self.assertGreater(arch_label, fav_label)

    def test_no_lib_more_or_batch_chrome(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for eid in ("libMoreBtn", "libMoreMenu", "archFilter", "batchToggle", "batchBar",
                    "batchExport", "batchArchive", "batchDelete", "batchCancel", "batchCount"):
            self.assertNotIn(f'id="{eid}"', html)
        # editor single-item archive remains
        self.assertIn('id="archBtn"', html)
        head = html[html.find('id="libFilters"') : html.find('class="lib-search"')]
        self.assertIn('id="sortSel"', head)
        self.assertIn('id="newRoleBtn"', head)
        self.assertIn('id="newBtn"', head)
        self.assertNotIn('data-icon="more"', head)

    def test_js_mutual_exclusion_and_archived_tab(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function setLibScope(", js)
        self.assertIn("function syncLibScopeUI(", js)
        self.assertIn('scope === "archived"', js)
        self.assertIn('S.archivedOnly = wantArch', js)
        self.assertIn('S.favOnly = wantFav', js)
        self.assertIn("libScopeArch", js)
        self.assertNotIn("archFilter", js)
        self.assertNotIn("libMoreBtn", js)
        self.assertNotIn("libMoreMenu", js)
        self.assertNotIn("toggleLibMore", js)
        self.assertNotIn("batchToggle", js)
        self.assertNotIn("batchBar", js)
        self.assertNotIn("renderBatchBar", js)
        self.assertNotIn("S.batch", js)
        # editor archive still wired
        self.assertIn("#archBtn", js)
        self.assertIn("archive_prompt", js)
        self.assertIn("unarchive_prompt", js)
        self.assertIn("归档是空的", js)
        self.assertIn("「归档」页签", js)

    def test_css_three_tab_segment(self):
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".lib-scope", css)
        self.assertIn(".lib-scope-tab", css)
        self.assertIn('aria-selected="true"', css)
        self.assertNotIn("#libMoreMenu", css)
        self.assertNotIn(".batch-bar", css)
        self.assertNotIn(".item.batch", css)


if __name__ == "__main__":
    unittest.main()
