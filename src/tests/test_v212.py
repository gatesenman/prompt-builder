"""2.12.0 — resizable columns, responsive layout chrome, IA tidy."""
from __future__ import annotations
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestVersion212(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)


class TestSplittersAndLayout(unittest.TestCase):
    def test_html_splitters_and_panels(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="splitList"', html)
        self.assertIn('id="splitSide"', html)
        self.assertIn('id="aiResize"', html)
        self.assertIn('id="listPanel"', html)
        self.assertIn('id="editorPanel"', html)
        self.assertIn('id="sidePanel"', html)
        self.assertIn('id="aiPanel"', html)
        self.assertIn("提示词库", html)
        self.assertIn('id="metaRow"', html)
        self.assertIn('id="tagsRow"', html)  # 2.12.1: kwRow removed
        self.assertIn('id="tagsRow"', html)
        self.assertIn('id="toggleListBtn"', html)
        self.assertIn('id="toggleSideBtn"', html)
        self.assertIn('id="editorMoreBtn"', html)
        
    def test_css_layout_vars(self):
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("--list-w", css)
        self.assertIn("--side-w", css)
        self.assertIn("--ai-w", css)
        self.assertIn(".splitter", css)
        self.assertIn("list-collapsed", css)
        self.assertIn("side-collapsed", css)
        self.assertIn("col-resize", css)

    def test_js_layout_helpers(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("pb.layout.w.list", js)
        self.assertIn("pb.layout.w.side", js)
        self.assertIn("pb.aiWidth", js)
        self.assertIn("bindColumnSplitter", js)
        self.assertIn("initLayoutChrome", js)
        self.assertIn("setPanelCollapsed", js)
        self.assertIn("persistLayoutWidths", js)
        self.assertIn("fitColumnsToViewport", js)
        self.assertIn("dblclick", js)
        # form foot only on form tab
        self.assertIn('foot.hidden = t !== "form"', js)
        # AI drawer still independent
        self.assertIn("closeAiDrawer", js)
        self.assertIn("ai-open", js)


class TestIaIdsPreserved(unittest.TestCase):
    """Existing handlers and 2.11.1 tests rely on these ids."""

    def test_critical_ids(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for eid in (
            "libScopeAll", "libScopeFav", "libScopeArch", "sortSel",
            "syntaxBtn", "revBtn", "archBtn", "insertBtn", "aiBtn",
            "formFoot", "copyBtn", "search", "editor", "titleInput",
        ):
            self.assertIn(f'id="{eid}"', html)
        for gone in ("libMoreBtn", "libMoreMenu", "archFilter", "batchToggle", "batchBar"):
            self.assertNotIn(f'id="{gone}"', html)


if __name__ == "__main__":
    unittest.main()
