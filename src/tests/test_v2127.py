"""2.12.8 — move prompt to role · reorder roles · MD toolbar / split · DnD markers."""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


class TestVersion2127(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        self.assertIn("def move_prompt_to_role", api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)
        cl = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 2.12.8", cl)


class TempStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMPTBUILDER_DATA_DIR"] = self.tmp.name
        import settings_store
        settings_store._cache["mtime"] = settings_store._cache["data"] = None

    def tearDown(self):
        os.environ.pop("PROMPTBUILDER_DATA_DIR", None)
        self.tmp.cleanup()

    def store(self):
        from prompts_store import PromptStore
        return PromptStore()


class TestMovePromptToRole(TempStore):
    def test_move_user_prompt_sets_role_and_storage_cat(self):
        s = self.store()
        role = s.create_role("目标角色")
        p = s.create("可拖拽", "你好 {{名}}")
        self.assertNotEqual(p["role_id"], role["id"])
        moved = s.move_prompt_to_role(p["id"], role["id"])
        self.assertIsNotNone(moved)
        self.assertEqual(moved["role_id"], role["id"])
        live = s.get(p["id"])
        self.assertEqual(live["role_id"], role["id"])
        cats = s.categories(role["id"])
        self.assertTrue(any(c["id"] == live["category_id"] for c in cats))

    def test_builtin_cannot_move(self):
        s = self.store()
        builtin = next(p for p in s.list() if p.get("builtin"))
        role = s.create_role("别处")
        self.assertIsNone(s.move_prompt_to_role(builtin["id"], role["id"]))

    def test_api_bridge_builtin_error(self):
        from api import Api
        store = self.store()
        api = Api(store)
        builtin = next(p for p in store.list() if p.get("builtin"))
        role = store.create_role("API目标")
        r = api.move_prompt_to_role(builtin["id"], role["id"])
        self.assertFalse(r["ok"])
        self.assertIn("复制后编辑", r.get("error") or "")
        user = store.create("用户提示", "x {{a}}")
        r2 = api.move_prompt_to_role(user["id"], role["id"])
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["prompt"]["role_id"], role["id"])


class TestReorderRoles(TempStore):
    def test_reorder_persists_order(self):
        s = self.store()
        a = s.create_role("甲组")
        b = s.create_role("乙组")
        ids = [r["id"] for r in s.roles()]
        # put b before a among user roles while keeping others
        new_order = []
        seen = set()
        for rid in ids:
            if rid == a["id"]:
                if b["id"] not in seen:
                    new_order.append(b["id"]); seen.add(b["id"])
                new_order.append(a["id"]); seen.add(a["id"])
            elif rid == b["id"]:
                continue
            else:
                new_order.append(rid); seen.add(rid)
        if b["id"] not in seen:
            new_order.insert(0, b["id"])
        r = s.reorder_roles(new_order)
        self.assertTrue(r.get("ok"))
        roles = s.roles()
        pos = {r["id"]: i for i, r in enumerate(roles)}
        self.assertLess(pos[b["id"]], pos[a["id"]])


class TestUiMarkers2127(unittest.TestCase):
    def test_html_md_toolbar_and_split(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="mdToolbar"', html)
        self.assertIn('data-md="bold"', html)
        self.assertIn('data-md="table"', html)
        self.assertIn('id="editorStack"', html)
        self.assertIn('id="mdLivePreview"', html)
        self.assertIn('id="splitMd"', html)
        self.assertIn('id="mdPreviewToggle"', html)
        # 2.12.6 tabs still there
        self.assertIn('id="libScopeArch"', html)
        self.assertNotIn('id="libMoreBtn"', html)
        self.assertNotIn('id="batchBar"', html)
        self.assertIn(">提示词<", html[html.find('id="libTitle"'): html.find('id="libTitle"') + 60])

    def test_js_dnd_and_md(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("application/x-pb-prompt", js)
        self.assertIn("application/x-pb-role", js)
        self.assertIn("move_prompt_to_role", js)
        self.assertIn("reorder_roles", js)
        self.assertIn('data-pb-drag="prompt"', js)
        self.assertIn('data-pb-drag="role"', js)
        self.assertIn("内置提示词请先复制后编辑", js)
        self.assertIn("已移到「", js)
        self.assertIn("已调整分组顺序", js)
        self.assertIn("MiniMD.render", js)
        self.assertIn("pb.editor.mdSplit", js)
        self.assertIn("function applyMdAction", js)
        self.assertIn("md-preview-collapsed", js)
        # flat mode disables drag
        self.assertIn("if (S.flatMode)", js)

    def test_css_markers(self):
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".md-toolbar", css)
        self.assertIn(".editor-stack", css)
        self.assertIn(".md-preview-pane", css)
        self.assertIn(".pb-drop-role", css)
        self.assertIn("pb-drop-before", css)

    def test_icons_md(self):
        icons = (ROOT / "web" / "js" / "icons.js").read_text(encoding="utf-8")
        for k in ("bold", "italic", "strike", "quote", "link", "table", "minus", "listOrdered", "eyeOff"):
            self.assertIn(f"{k}:", icons)

    def test_store_has_move_to_role(self):
        src = (ROOT / "src" / "prompts_store.py").read_text(encoding="utf-8")
        self.assertIn("def move_prompt_to_role", src)


if __name__ == "__main__":
    unittest.main()
