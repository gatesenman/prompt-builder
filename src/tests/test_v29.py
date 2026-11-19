"""2.9 skill-distilled builtin templates."""
import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SKILL_ROLES = {"role-agentflow", "role-design", "role-pm", "role-edu"}


def skill_prompts():
    from library_model import load_builtins
    return [p for p in load_builtins()["prompts"] if any(str(t).startswith("skill:") for t in p.get("tags") or [])]


class SkillTemplates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMPTBUILDER_DATA_DIR"] = self.tmp.name
        import settings_store
        settings_store._cache["mtime"] = settings_store._cache["data"] = None

    def tearDown(self):
        os.environ.pop("PROMPTBUILDER_DATA_DIR", None)
        self.tmp.cleanup()

    def test_no_parser_errors_and_variables(self):
        from prompt_syntax import analyze
        ps = skill_prompts()
        self.assertGreaterEqual(len(ps), 44)
        self.assertLessEqual(len(ps), 60)
        controls = set()
        for p in ps:
            r = analyze(p["body"])
            errs = [i for i in r["issues"] if i["level"] == "error"]
            self.assertEqual(errs, [], p["name"])
            self.assertTrue(r["variables"], p["name"])
            controls |= {v["control"] for v in r["variables"]}
        self.assertTrue({"text", "multiline", "number", "select"} <= controls)

    def test_tree_consistency(self):
        from library_model import load_builtins
        b = load_builtins()
        roles = {r["id"] for r in b["roles"]}
        cats = {c["id"]: c for c in b["categories"]}
        self.assertTrue(SKILL_ROLES <= roles)
        for c in cats.values():
            self.assertIn(c["role_id"], roles, c["id"])
        ids = [p["id"] for p in b["prompts"]]
        self.assertEqual(len(ids), len(set(ids)))
        for p in skill_prompts():
            self.assertIn(p["role_id"], roles, p["name"])
            # 2.10: builtins ship flat — category_id optional/empty

    def test_tags_survive_and_merge_keeps_user_data(self):
        from prompts_store import PromptStore, prompts_path
        s = PromptStore()
        mine = s.create("我的私有提示", "你好 {{名}}")
        # simulate a 2.8 data file: no skill roles/categories/prompts
        path = prompts_path()
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        d["prompts"] = [p for p in d["prompts"] if not p["id"].startswith("bp-sk-")]
        d["roles"] = [r for r in d["roles"] if r["id"] not in SKILL_ROLES]
        d["categories"] = [c for c in d["categories"] if c["role_id"] not in SKILL_ROLES and c["id"] != "cat-fullstack-git"]
        Path(path).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        s2 = PromptStore()
        got = s2.get(mine["id"])
        self.assertEqual(got["body"], "你好 {{名}}")
        self.assertEqual(got["name"], "我的私有提示")
        have = {p["id"] for p in s2.list()}
        for p in skill_prompts():
            self.assertIn(p["id"], have, p["name"])
        long_tag = "skill:improve-codebase-architecture"
        hit = [p for p in s2.list() if long_tag in (s2.get(p["id"]).get("tags") or [])]
        self.assertTrue(hit)

    def test_no_step_split_prompts(self):
        ps = skill_prompts()
        for p in ps:
            self.assertNotIn("步骤", p.get("tags") or [], p["name"])
        # at most a few skills may have a second independent prompt
        from collections import Counter
        c = Counter()
        for p in ps:
            st = next(t for t in p["tags"] if str(t).startswith("skill:"))
            c[st] += 1
        self.assertGreaterEqual(len(c), 40)
        multi = {k: v for k, v in c.items() if v > 1}
        self.assertLessEqual(len(multi), 10)
        self.assertTrue(all(v == 2 for v in multi.values()), multi)

    def test_version(self):

        from api import APP_VERSION
        self.assertRegex(APP_VERSION, r"^2\.1[12]\.\d+$")


if __name__ == "__main__":
    unittest.main()
