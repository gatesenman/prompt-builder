"""2.12.5 / 2.12.8 — library scope tabs · labeled count · prune rare UI."""
from __future__ import annotations
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestVersion2125(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)


class TestLibScopeTabs(unittest.TestCase):
    def test_tabs_between_search_and_list(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="favFilter"', html)
        i_search = html.find('id="search"')
        i_scope = html.find('id="libScope"')
        i_list = html.find('id="list"')
        self.assertGreater(i_scope, i_search)
        self.assertGreater(i_list, i_scope)
        chunk = html[i_scope : i_list]
        self.assertIn('role="tablist"', chunk)
        self.assertIn('id="libScopeAll"', chunk)
        self.assertIn('id="libScopeFav"', chunk)
        self.assertIn('id="libScopeArch"', chunk)
        self.assertIn("全部", chunk)
        self.assertIn("收藏", chunk)
        self.assertIn("归档", chunk)
        self.assertIn('aria-selected="true"', chunk)
        self.assertIn('aria-selected="false"', chunk)
        # 2.12.8: no library more menu / batch chrome
        self.assertNotIn('id="libMoreBtn"', html)
        self.assertNotIn('id="libMoreMenu"', html)
        self.assertNotIn('id="batchToggle"', html)
        self.assertNotIn('id="batchBar"', html)
        self.assertNotIn('id="archFilter"', html)
        head = html[html.find('id="libFilters"') : html.find('class="lib-search"')]
        self.assertNotIn('id="favFilter"', head)
        # head actions: sort + newRole + new (no ⋯)
        self.assertIn('id="sortSel"', head)
        self.assertNotIn('id="libMoreBtn"', head)
        self.assertIn('id="newRoleBtn"', html)
        self.assertIn('id="newBtn"', html)

    def test_js_wires_favOnly_via_tabs(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function setLibScope(", js)
        self.assertIn("function syncLibScopeUI(", js)
        self.assertIn('S.favOnly = wantFav', js)
        self.assertNotIn("#favFilter", js)
        self.assertIn('data-empty="goto-all"', js)
        # clear search must not wipe fav tab
        self.assertIn("keep 全部/收藏/归档 tab", js)
        self.assertIn("还没有收藏", js)

    def test_css_scope_tabs(self):
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".lib-scope", css)
        self.assertIn(".lib-scope-tab", css)
        self.assertIn('aria-selected="true"', css)
        self.assertNotIn("#favFilter", css)


class TestCountLabelAlwaysVisible(unittest.TestCase):
    def test_title_and_count_cluster(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        title = html[html.find('id="libTitle"') : html.find('id="libTitle"') + 80]
        self.assertIn("提示词", title)
        self.assertIn('id="listCount"', html)
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        # compact must NOT hide panel-title (bare count ban)
        self.assertIn("never bare count", css)
        # no display:none on panel-title in compact / CQ
        compact = css[css.find("lib-compact") :]
        # allow display:inline but not display:none on panel-title
        for block in re.findall(r"\.lib-head-title \.panel-title\s*\{[^}]+\}", css):
            self.assertNotIn("display: none", block)
            self.assertNotIn("display:none", block)


class TestPrunedRareUI(unittest.TestCase):
    def test_io_menu_keeps_import_export_backup_only(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        io = html[html.find('id="ioMenu"') : html.find('id="aiBtn"')]
        self.assertIn('data-io="import-json"', io)
        self.assertIn('data-io="import-md"', io)
        self.assertIn('data-io="export-json"', io)
        self.assertIn('data-io="export-md"', io)
        self.assertIn('data-io="backup"', io)
        self.assertIn('data-io="restore"', io)
        self.assertNotIn('data-io="health"', io)
        self.assertNotIn('data-io="stats"', io)
        self.assertNotIn('data-io="history"', io)

    def test_settings_library_pruned(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        lib = html[html.find('data-pane="library"') : html.find('data-pane="ai"')]
        self.assertNotIn("记录填写历史", lib)
        self.assertNotIn("setHistory", lib)
        self.assertNotIn("setHealth", lib)
        self.assertNotIn("setClearHistory", lib)
        self.assertNotIn("健康检查", lib)
        self.assertNotIn("清空填写历史", lib)
        self.assertIn("setBackup", lib)
        self.assertIn("setRestore", lib)
        self.assertIn("setSort", lib)
        # sort options simplified
        self.assertNotIn('value="used"', lib)
        self.assertNotIn('value="created"', lib)
        self.assertIn('value="recent"', lib)
        self.assertIn('value="updated"', lib)
        self.assertIn('value="name"', lib)

    def test_overlays_removed(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for eid in ("histOverlay", "statsOverlay", "healthOverlay"):
            self.assertNotIn(f'id="{eid}"', html)
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("function openHistory", js)
        self.assertNotIn("function openStats", js)
        self.assertNotIn("function openHealth", js)

    def test_sort_simplified_in_lib_head(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        sel = html[html.find('id="sortSel"') : html.find('id="sortCompactBtn"')]
        self.assertIn('value="recent"', sel)
        self.assertIn('value="updated"', sel)
        self.assertIn('value="name"', sel)
        self.assertNotIn('value="used"', sel)
        self.assertNotIn('value="created"', sel)
        menu = html[html.find('id="sortCompactMenu"') : html.find('id="newRoleBtn"')]
        self.assertIn('data-sort="recent"', menu)
        self.assertIn('data-sort="updated"', menu)
        self.assertIn('data-sort="name"', menu)
        self.assertNotIn('data-sort="used"', menu)
        self.assertNotIn('data-sort="created"', menu)

    def test_pin_moved_to_editor_more(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        actions = html[html.find("editor-head-actions") : html.find('id="metaRow"')]
        # fav still visible in head actions
        self.assertIn('id="favBtn"', actions)
        # pin only inside editorMoreMenu
        before_more = actions[: actions.find('id="editorMoreMenu"')]
        self.assertNotIn('id="pinBtn"', before_more)
        more = actions[actions.find('id="editorMoreMenu"') :]
        self.assertIn('id="pinBtn"', more)
        self.assertIn("置顶", more)
        # keep core more items
        self.assertIn("copyResultMenuBtn", more)
        self.assertIn("syntaxBtn", more)
        self.assertIn("revBtn", more)
        self.assertIn("archBtn", more)


if __name__ == "__main__":
    unittest.main()
