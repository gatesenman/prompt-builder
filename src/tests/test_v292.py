"""2.9.2 — // quick picker grouped by 角色 (2.10 flat)."""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parents[2]


def _group_like_js(items):
    """Mirror web/js/quick.js buildGroups ordering for regression checks."""
    from collections import defaultdict
    roles = {}
    for it in items:
        rid = it.get("role_id") or "_none"
        roles.setdefault(rid, {
            "id": rid,
            "name": it.get("role_name") or "",
            "order": it.get("role_order", 9999),
            "cats": {},
        })
        cid = it.get("category_id") or "_none"
        cats = roles[rid]["cats"]
        cats.setdefault(cid, {
            "id": cid,
            "name": it.get("category_name") or "",
            "order": it.get("category_order", 9999),
            "items": [],
        })
        cats[cid]["items"].append(it)
    out = []
    for r in sorted(roles.values(), key=lambda x: (x["order"], x["name"].casefold())):
        cats = []
        for c in sorted(r["cats"].values(), key=lambda x: (x["order"], x["name"].casefold())):
            c["items"].sort(key=lambda p: (
                0 if p.get("pinned") else 1,
                0 if p.get("favorite") else 1,
                0 if p.get("recent") else 1,
                -(p.get("use_count") or 0),
                (p.get("name") or "").casefold(),
            ))
            cats.append(c)
        out.append({"id": r["id"], "name": r["name"], "categories": cats})
    return out


class QuickPickGrouping(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMPTBUILDER_DATA_DIR"] = self.tmp.name
        import settings_store
        settings_store._cache["mtime"] = settings_store._cache["data"] = None

    def tearDown(self):
        os.environ.pop("PROMPTBUILDER_DATA_DIR", None)
        self.tmp.cleanup()

    def test_quick_items_have_tree_meta(self):
        from prompts_store import PromptStore
        from library_model import sort_roles, sort_categories
        s = PromptStore()
        items = s.quick_items()
        self.assertGreaterEqual(len(items), 80)
        for it in items:
            self.assertIn("role_id", it)
            self.assertIn("category_id", it)
            self.assertIn("role_name", it)
            self.assertIn("category_name", it)
            self.assertIn("role_order", it)
            self.assertIn("category_order", it)
            self.assertTrue(it["role_name"], it["id"])
            self.assertTrue(it["category_name"], it["id"])
        # orders match library tree
        role_order = {r["id"]: int(r.get("order") or 0) for r in sort_roles(s._roles)}
        cat_order = {c["id"]: int(c.get("order") or 0) for c in sort_categories(s._categories)}
        for it in items:
            self.assertEqual(it["role_order"], role_order[it["role_id"]], it["name"])
            self.assertEqual(it["category_order"], cat_order[it["category_id"]], it["name"])

    def test_grouped_order_matches_sidebar_tree(self):
        from prompts_store import PromptStore
        from library_model import sort_roles, sort_categories, DEFAULT_ROLE_ID, DEFAULT_CAT_ID
        s = PromptStore()
        items = s.quick_items()
        groups = _group_like_js(items)
        # first role should be 我的提示 when it has prompts, else first builtin with prompts
        role_ids = [g["id"] for g in groups]
        roles_sorted = [r["id"] for r in sort_roles(s._roles) if r["id"] in set(role_ids)]
        self.assertEqual(role_ids, roles_sorted)
        # within first role that has cats, cats follow order
        for g in groups:
            want = [c["id"] for c in sort_categories(s._categories)
                    if c["role_id"] == g["id"] and c["id"] in {c2["id"] for c2 in g["categories"]}]
            got = [c["id"] for c in g["categories"]]
            self.assertEqual(got, want, g["name"])
        # user default group present after creating a prompt
        mine = s.create("分组测试提示", "你好 {{名}}")
        items2 = s.quick_items()
        g2 = _group_like_js(items2)
        mine_role = next(g for g in g2 if g["id"] == DEFAULT_ROLE_ID)
        self.assertEqual(mine_role["name"], "我的提示")
        uncat = next(c for c in mine_role["categories"] if c["id"] == DEFAULT_CAT_ID)
        self.assertTrue(any(p["id"] == mine["id"] for p in uncat["items"]))

    def test_within_category_rank_pinned_fav_recent(self):
        from prompts_store import PromptStore
        s = PromptStore()
        a = s.create("AAA排序", "a {{x}}")
        b = s.create("BBB排序", "b {{x}}")
        c = s.create("CCC排序", "c {{x}}")
        s.update(a["id"], {"pinned": True})
        s.update(b["id"], {"favorite": True})
        s.touch_used(c["id"], {"x": "1"})
        items = [it for it in s.quick_items() if it["name"].endswith("排序")]
        groups = _group_like_js(items)
        flat = groups[0]["categories"][0]["items"]
        names = [p["name"] for p in flat]
        self.assertEqual(names[0], "AAA排序")  # pinned first
        self.assertEqual(names[1], "BBB排序")  # favorite
        self.assertEqual(names[2], "CCC排序")  # recent

    def test_version_292(self):
        from api import APP_VERSION
        self.assertRegex(APP_VERSION, r"^2\.1[12]\.\d+$")
        self.assertRegex((ROOT / "VERSION.txt").read_text(encoding="utf-8").strip(), r"^2\.1[12]\.\d+$")

    def test_quick_js_always_renders_role_headers(self):
        js = Path(__file__).resolve().parents[2].joinpath("web/js/quick.js").read_text(encoding="utf-8")
        self.assertIn("buildGroups", js)
        self.assertIn("qp-role", js)
        self.assertNotIn("qp-cat", js)  # 2.10: role-only headers
        self.assertIn("data-collapse", js)
        # must NOT only group when searching
        self.assertNotIn("if (q && group && group !== lastGroup)", js)


if __name__ == "__main__":
    unittest.main()
