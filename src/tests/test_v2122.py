"""2.12.4 — debug IA, AI studio slim, no modal make-default checkbox, AI chip label."""
from __future__ import annotations
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestVersion2122(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)


class TestAiModalNoMakeDefCheckbox(unittest.TestCase):
    def test_no_aipMakeDef(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("aipMakeDef", js)
        self.assertNotIn("设为默认配置", js)
        self.assertIn("data-ai-def", js)
        self.assertIn("设默认", js)
        self.assertIn("if (isNew) return !AI.defaultId || AI.profiles.length === 0", js)
        self.assertIn("if (existing && existing.id === AI.defaultId) return true", js)


class TestDebugPanel2122(unittest.TestCase):
    def test_collapsible_and_star_local(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("pb.debug.sections", js)
        self.assertIn("dbg-sec", js)
        self.assertIn("updateMmCardScores", js)
        self.assertIn("refreshMmResults", js)
        self.assertIn('data-dbg="sample"', js)
        # star path must not call full renderDebug
        needle = "const star = e.target.closest("
        i = js.find(needle)
        self.assertGreater(i, 0)
        block = js[i:i + 500]
        self.assertIn("updateMmCardScores", block)
        self.assertNotIn("renderDebug()", block)
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".dbg-top", css)
        self.assertIn(".dbg-sec", css)
        self.assertIn(".dbg-var", css)


class TestAiStudioSlim2122(unittest.TestCase):
    def test_no_scene_extra_model_select(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("aiAudience", js)
        self.assertNotIn("aiExtra", js)
        self.assertNotIn("aiModelSel", js)
        self.assertIn("resolveDefaultAiTarget", js)
        self.assertIn('call("ai_generate", $("#aiGoal").value, "", "", t.profile_id, t.model)', js)
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn(">AI</span>", html)
        self.assertIn('id="aiBtn"', html)
        self.assertIn("AI 工作室", html)  # aria/tooltip
        self.assertNotIn('id="aiTitle"', html)


class TestAiStudioLabel(unittest.TestCase):
    def test_titlebar_short_label(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<span class="tb-ai-label">AI</span>', html)
        self.assertNotIn('<span class="tb-ai-label">AI 工作室</span>', html)


class TestTitlebarGroups2122(unittest.TestCase):
    def test_grouped_actions(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="tb-group"', html)
        self.assertIn('class="tb-sep"', html)
        self.assertIn('aria-label="库与数据"', html)
        self.assertIn('aria-label="系统"', html)
        # IO lives in titlebar, not list panel footer
        self.assertEqual(html.count('id="ioBtn"'), 1)
        self.assertEqual(html.count('id="ioMenu"'), 1)
        list_chunk = html[html.find('id="listPanel"'):html.find('id="editorPanel"')]
        self.assertNotIn('id="ioBtn"', list_chunk)
        self.assertNotIn("panel-foot", list_chunk)
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".tb-group", css)
        self.assertIn(".tb-sep", css)


class TestLibAndEditorChrome2122(unittest.TestCase):
    def test_single_lib_row_and_editor_head(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="panel-head lib-head"', html)
        self.assertIn('class="lib-head-actions"', html)
        self.assertIn('class="lib-search"', html)
        self.assertNotIn("lib-toolbar", html)
        self.assertIn("editor-head-left", html)
        self.assertIn("editor-head-actions", html)
        # save-state sits with title, not between flags and insert
        left = html[html.find("editor-head-left"):html.find("editor-head-actions")]
        self.assertIn('id="saveState"', left)
        self.assertIn('id="titleInput"', left)
        a0 = html.find("editor-head-actions")
        a1 = html.find("</div>", html.find('id="editorMoreMenu"', a0))
        actions = html[a0:a1]
        self.assertIn('id="favBtn"', actions)
        self.assertIn('id="insertBtn"', actions)
        self.assertNotIn('id="saveState"', actions)
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".editor-head-left", css)
        self.assertIn(".editor-head-actions", css)
        self.assertIn(".lib-head-actions", css)
