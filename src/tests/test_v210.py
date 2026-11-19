"""2.10.0 — flat Role › Prompt tree + v5 category migration."""
from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class TestFlatTree(unittest.TestCase):
    def test_version(self):
        from api import APP_VERSION
        self.assertRegex(APP_VERSION, r"^2\.1[12]\.\d+$")
        self.assertRegex((ROOT / "VERSION.txt").read_text(encoding="utf-8").strip(), r"^2\.1[12]\.\d+$")

    def test_tree_payload_flat(self):
        from library_model import tree_payload, VERSION
        self.assertEqual(VERSION, 6)
        roles = [
            {"id": "role-a", "name": "A", "icon": "folder", "description": "",
             "builtin": True, "system": True, "order": 10},
            {"id": "role-b", "name": "B", "icon": "folder", "description": "",
             "builtin": True, "system": True, "order": 20},
        ]
        cats = [
            {"id": "cat-a1", "role_id": "role-a", "name": "旧分类1", "builtin": True, "system": True, "order": 1},
            {"id": "cat-a2", "role_id": "role-a", "name": "旧分类2", "builtin": True, "system": True, "order": 2},
        ]
        prompts = [
            {"id": "p1", "name": "一", "role_id": "role-a", "category_id": "cat-a1",
             "pinned": False, "favorite": False, "order": 1},
            {"id": "p2", "name": "二", "role_id": "role-a", "category_id": "cat-a2",
             "pinned": False, "favorite": True, "order": 2},
            {"id": "p3", "name": "三", "role_id": "role-b", "category_id": "cat-a1",
             "pinned": False, "favorite": False, "order": 1},
        ]
        tree = tree_payload(roles, cats, prompts)
        self.assertTrue(tree.get("flat"))
        self.assertEqual(len(tree["roles"]), 2)
        a = tree["roles"][0]
        self.assertEqual(a["count"], 2)
        self.assertEqual(len(a.get("categories") or []), 0)
        names = [p["name"] for p in a["prompts"]]
        # favorite first
        self.assertEqual(names[0], "二")
        self.assertEqual(set(names), {"一", "二"})

    def test_builtins_no_categories_and_rich_ide(self):
        raw = json.loads((ROOT / "data" / "builtins.json").read_text(encoding="utf-8"))
        self.assertEqual(raw.get("categories"), [])
        prompts = raw["prompts"]
        self.assertGreaterEqual(len(prompts), 140)
        nonsk = [p for p in prompts if not any(str(t).startswith("skill:") for t in (p.get("tags") or []))]
        self.assertGreaterEqual(len(nonsk), 90)
        lens = [len(p["body"]) for p in nonsk]
        self.assertGreaterEqual(sorted(lens)[len(lens) // 2], 500)
        # every nonskill has variables or structured sections
        for p in nonsk:
            self.assertTrue("{{" in p["body"] or "##" in p["body"], p["name"])

    def test_store_loads_flat_and_migrates_tags(self):
        from prompts_store import PromptStore, VERSION
        self.assertEqual(VERSION, 6)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # simulate v5 user file with categories
            data = {
                "format": "promptbuilder-prompts",
                "version": 5,
                "roles": [
                    {"id": "role-mine", "name": "我的提示", "icon": "folder",
                     "description": "", "builtin": False, "system": True, "order": 0},
                    {"id": "role-custom", "name": "自定义角色", "icon": "folder",
                     "description": "", "builtin": False, "system": False, "order": 50},
                ],
                "categories": [
                    {"id": "cat-mine-uncat", "role_id": "role-mine", "name": "未分类",
                     "builtin": False, "system": True, "order": 0},
                    {"id": "cat-custom-work", "role_id": "role-custom", "name": "工作流",
                     "builtin": False, "system": False, "order": 10},
                ],
                "prompts": [
                    {"id": "u1", "name": "用户提示", "body": "hello {{x}}",
                     "role_id": "role-custom", "category_id": "cat-custom-work",
                     "builtin": False, "system": False, "tags": [],
                     "order": 0, "favorite": False, "pinned": False, "archived": False,
                     "use_count": 0, "test_values": {},
                     "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"},
                ],
            }
            # point paths at temp
            import prompts_store as ps
            import settings_store as ss
            (td / "backups").mkdir(parents=True, exist_ok=True)
            (td / "prompts.json").write_text(json.dumps(data), encoding="utf-8")
            (td / "settings.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(ps, "prompts_path", lambda: td / "prompts.json"), \
                 mock.patch.object(ps, "backups_dir", lambda: td / "backups"), \
                 mock.patch.object(ss, "settings_path", lambda: td / "settings.json"):
                # clear flat flag so migration runs
                store = PromptStore()
                tree = store.tree()
                self.assertTrue(tree.get("flat"))
                roles = {r["id"]: r for r in tree["roles"]}
                self.assertIn("role-custom", roles)
                ids = [p["id"] for p in (roles["role-custom"].get("prompts") or [])]
                self.assertIn("u1", ids)
                full = store.get("u1")
                self.assertEqual(full["role_id"], "role-custom")
                self.assertIn("工作流", full.get("tags") or [])
                # every role.prompts nested; categories empty in payload
                for r in tree["roles"]:
                    self.assertEqual(r.get("categories"), [])


class TestQuickRoleOnly(unittest.TestCase):
    def test_quick_js_has_no_qp_cat_loop(self):
        src = (ROOT / "web" / "js" / "quick.js").read_text(encoding="utf-8")
        self.assertIn("buildGroups", src)
        self.assertTrue(any(x in src for x in ("2.10", "2.11", "2.12")))
        # should group by role items directly
        self.assertIn("byRole.get(rid).items.push(it)", src)
        self.assertNotIn("role.cats", src)


if __name__ == "__main__":
    unittest.main()
