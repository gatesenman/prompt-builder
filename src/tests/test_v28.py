"""2.8 Role › Category › Prompt tree, builtins, migration."""
import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ["PROMPTBUILDER_DATA_DIR"] = str(self.dir)
        import settings_store
        settings_store._cache["mtime"] = settings_store._cache["data"] = None

    def tearDown(self):
        os.environ.pop("PROMPTBUILDER_DATA_DIR", None)
        self.tmp.cleanup()

    def store(self):
        from prompts_store import PromptStore
        return PromptStore()


class BuiltinsAndTree(TempData):
    def test_builtins_load_and_tree(self):
        from library_model import load_builtins, DEFAULT_ROLE_ID, DEFAULT_CAT_ID
        bun = load_builtins()
        self.assertGreaterEqual(len(bun["roles"]), 10)
        self.assertGreaterEqual(len(bun["prompts"]), 60)
        s = self.store()
        self.assertTrue(any(r["id"] == DEFAULT_ROLE_ID for r in s.roles()))
        self.assertTrue(any(c["id"] == DEFAULT_CAT_ID for c in s.categories()))
        tree = s.tree()
        role_ids = {r["id"] for r in tree["roles"]}
        self.assertIn(DEFAULT_ROLE_ID, role_ids)
        self.assertIn("role-backend", role_ids)
        # every builtin prompt has variables
        for p in s.list():
            if p.get("builtin"):
                body = s.get(p["id"])["body"]
                self.assertIn("{{", body, p["name"])
        # counts roughly match
        total = sum(r["count"] for r in tree["roles"])
        self.assertGreaterEqual(total, 60)

    def test_user_prompt_lands_in_mine_uncategorized(self):
        from library_model import DEFAULT_ROLE_ID, DEFAULT_CAT_ID
        s = self.store()
        p = s.create("我的测试", "你好 {{名}}")
        self.assertEqual(p["role_id"], DEFAULT_ROLE_ID)
        self.assertEqual(p["category_id"], DEFAULT_CAT_ID)
        self.assertFalse(p.get("builtin"))

    def test_create_under_category(self):
        s = self.store()
        role = s.create_role("自定义角色")
        cats = s.categories(role["id"])
        self.assertTrue(cats)
        p = s.create("分类下的提示", "x {{a}}", role_id=role["id"], category_id=cats[0]["id"])
        self.assertEqual(p["category_id"], cats[0]["id"])
        self.assertEqual(p["role_id"], role["id"])

    def test_builtin_copy_on_edit(self):
        s = self.store()
        builtin = next(p for p in s.list() if p.get("builtin"))
        r = s.update(builtin["id"], {"name": "改掉内置"})
        self.assertTrue(r.get("_copied_from_builtin") or not r.get("builtin"))
        self.assertNotEqual(r["id"], builtin["id"])
        # original still present and unchanged name-wise on disk id
        orig = s.get(builtin["id"])
        self.assertTrue(orig.get("builtin"))
        self.assertNotEqual(orig["name"], "改掉内置")

    def test_copy_builtin_explicit(self):
        s = self.store()
        builtin = next(p for p in s.list() if p.get("builtin"))
        c = s.copy_builtin(builtin["id"])
        self.assertFalse(c.get("builtin"))
        self.assertIn("可编辑", c["name"])

    def test_hide_builtin_on_delete(self):
        s = self.store()
        builtin = next(p for p in s.list() if p.get("builtin"))
        pid = builtin["id"]
        taken = s.take(pid)
        self.assertTrue(taken.get("hidden_builtin"))
        self.assertIsNone(s.get(pid))
        from settings_store import load_settings
        self.assertIn(pid, load_settings().get("hidden_builtins") or [])
        # reload does not resurrect
        s2 = self.store()
        self.assertIsNone(s2.get(pid))

    def test_role_category_crud(self):
        s = self.store()
        r = s.create_role("临时角色")
        c = s.create_category(r["id"], "临时分类")
        self.assertEqual(c["role_id"], r["id"])
        self.assertTrue(s.rename_role(r["id"], "改名角色"))
        self.assertTrue(s.rename_category(c["id"], "改名分类"))
        # cannot delete builtin role
        bad = s.delete_role("role-backend")
        self.assertFalse(bad.get("ok"))
        # can delete user role (prompts move)
        p = s.create("将移动", "z", category_id=c["id"])
        ok = s.delete_role(r["id"])
        self.assertTrue(ok["ok"])
        from library_model import DEFAULT_CAT_ID
        self.assertEqual(s.get(p["id"])["category_id"], DEFAULT_CAT_ID)

    def test_v4_migration_to_mine(self):
        from library_model import DEFAULT_ROLE_ID, DEFAULT_CAT_ID, VERSION
        from paths import prompts_path
        # write a v4 library without roles/categories
        payload = {
            "format": "promptbuilder-prompts",
            "version": 4,
            "prompts": [{
                "id": "user-legacy-1",
                "name": "旧提示",
                "body": "旧 {{内容}}",
                "tags": ["x"],
                "favorite": True,
            }],
        }
        prompts_path().write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        s = self.store()
        raw = json.loads(prompts_path().read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], VERSION)
        self.assertTrue(raw.get("roles"))
        self.assertTrue(raw.get("categories"))
        p = s.get("user-legacy-1")
        self.assertEqual(p["role_id"], DEFAULT_ROLE_ID)
        self.assertEqual(p["category_id"], DEFAULT_CAT_ID)
        self.assertTrue(p["favorite"])

    def test_search_by_role_name(self):
        s = self.store()
        hits = s.list("后端")
        self.assertTrue(any(p.get("builtin") for p in hits))

    def test_export_includes_tree(self):
        from library_model import VERSION as SCHEMA_VERSION
        s = self.store()
        payload = s.export_payload()
        self.assertEqual(payload["version"], SCHEMA_VERSION)
        self.assertTrue(payload["roles"])
        # 2.10 flat: categories may be empty or storage-only
        self.assertIn("categories", payload)

    def test_app_version(self):
        from api import APP_VERSION
        self.assertRegex(APP_VERSION, r"^2\.(8|9|10|11|12)\.\d+$")


if __name__ == "__main__":
    unittest.main()
