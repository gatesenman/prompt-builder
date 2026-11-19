"""2.12.4 — remove side-header 复制结果; lib icons unified; title+save-state tight."""
from __future__ import annotations
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestVersion2123(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)


class TestNoCopyResultInSideHeader(unittest.TestCase):
    def test_copy_removed_from_tabs(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        # side tabs block must not contain 复制结果 button
        i0 = html.find('id="sidePanel"')
        i1 = html.find('id="tab-form"', i0)
        tabs = html[i0:i1]
        self.assertIn('role="tablist"', tabs)
        self.assertNotIn("复制结果", tabs)
        self.assertNotIn('id="copyBtn"', tabs)
        # quieter places keep copy
        self.assertIn('id="copyBtn"', html)
        self.assertIn('id="tab-preview"', html)
        prev = html[html.find('id="tab-preview"'):html.find('id="tab-debug"')]
        self.assertIn('id="copyBtn"', prev)
        self.assertIn('id="copyResultMenuBtn"', html)
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("async function copyResult()", js)
        self.assertIn("copyResultMenuBtn", js)
        self.assertIn("copyResult()", js)
        # Ctrl+Enter still wired
        self.assertIn("copyResult(); return;", js)


class TestLibHeadIconButtons(unittest.TestCase):
    def test_new_icon_only_and_no_head_fav(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        # 2.12.8: standalone #favFilter removed from lib head; scope tabs instead
        self.assertNotIn('id="favFilter"', html)
        self.assertIn('id="libScopeAll"', html)
        self.assertIn('id="libScopeFav"', html)
        self.assertIn('id="libScopeArch"', html)
        m2 = re.search(r'<button[^>]*id="newBtn"[^>]*>.*?</button>', html, re.S)
        self.assertIsNotNone(m2)
        nb = m2.group(0)
        self.assertIn("icon", nb)
        self.assertIn('title="新建提示词 (Ctrl+N)"', nb)
        self.assertNotIn("新建</", nb)
        # peers already icon; 2.12.8: no libMore
        self.assertNotIn('id="libMoreBtn"', html)
        self.assertIn('id="newRoleBtn"', html)
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("flex-wrap: nowrap", css)
        self.assertIn(".lib-head-actions", css)
        self.assertRegex(css, r"#listPanel \.lib-head-actions[^}]*flex-wrap:\s*nowrap")
        self.assertIn("width: 30px; height: 30px", css)


class TestTitleSaveStateTight(unittest.TestCase):
    def test_title_not_flex_grow_middle(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        left = html[html.find("editor-head-left"):html.find("editor-head-actions")]
        self.assertIn('id="titleInput"', left)
        self.assertIn('id="saveState"', left)
        # title before saveState
        self.assertLess(left.find('id="titleInput"'), left.find('id="saveState"'))
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        block = css[css.find("#editorPanel .editor-head-left"):css.find("#editorPanel .editor-head-actions")]
        self.assertIn("max-width: 58%", block)
        # title must NOT flex:1 inside editor-head-left
        title_rule = css[css.find("#editorPanel .editor-head-left .title-input"):]
        title_rule = title_rule[: title_rule.find("}") + 1]
        self.assertIn("flex: 0 1 auto", title_rule)
        self.assertNotIn("flex: 1", title_rule)
        self.assertIn("field-sizing: fixed", title_rule)  # 2.12.4: JS px measure
        self.assertIn("margin-left: auto", css)
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function syncTitleWidth()", js)


class TestAiFootQuietAndSweep(unittest.TestCase):
    def test_no_verbose_ai_tips_and_prior_sweep(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("仅在点击生成时联网", js)
        self.assertNotIn("清单式评审", js)
        self.assertNotIn("仅在点击生成时联网", html)
        self.assertNotIn("aipMakeDef", js)
        self.assertNotIn("aiAudience", js)
        self.assertNotIn("aiExtra", js)
        self.assertNotIn("aiModelSel", js)
        self.assertIn('<span class="tb-ai-label">AI</span>', html)
        self.assertIn('class="tb-group"', html)
        # io in titlebar, not list foot
        self.assertEqual(html.count('id="ioBtn"'), 1)
        list_chunk = html[html.find('id="listPanel"'):html.find('id="editorPanel"')]
        self.assertNotIn('id="ioBtn"', list_chunk)


if __name__ == "__main__":
    unittest.main()
