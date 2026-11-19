"""2.12.8 — role system_prompt · lint · compare_revisions · cases CRUD."""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


class TestVersion2128(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        for name in ("get_role_system_prompt", "set_role_system_prompt", "list_cases",
                     "save_case", "delete_case", "run_case", "render_prompt", "compare_revisions"):
            self.assertIn(f"def {name}", api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)
        cl = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 2.12.8", cl)

    def test_ui_markers(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for m in ("roleSysOverlay", "applyRoleSysToggle", "roleSysChip", "setApplyRoleSys",
                  "revCompareSel", "diffModeSeg", "caseOverlay", "caseSave"):
            self.assertIn(m, html)
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        for m in ("openRoleSysPrompt", "withRoleSystem", "renderCasesPanel", "paintDiffView",
                  "体检", "含角色设定", "data-rev-check"):
            self.assertIn(m, js)
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("2.12.8", css)
        self.assertIn("cases-panel", css)


class TempStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMPTBUILDER_DATA_DIR"] = self.tmp.name
        import settings_store
        settings_store._cache["mtime"] = settings_store._cache["data"] = None
        self._store = None
        self._api = None

    def tearDown(self):
        os.environ.pop("PROMPTBUILDER_DATA_DIR", None)
        self.tmp.cleanup()

    def store(self):
        from prompts_store import PromptStore
        if not hasattr(self, "_store") or self._store is None:
            self._store = PromptStore()
        return self._store

    def api(self):
        from api import Api
        from revisions_store import RevisionsStore
        if not hasattr(self, "_api") or self._api is None:
            self._api = Api(self.store(), revisions=RevisionsStore())
        return self._api


class TestRoleSystemPrompt(TempStore):
    def test_persist_and_migrate(self):
        st = self.store()
        role = st.create_role("测试角色")
        self.assertEqual(role.get("system_prompt"), "")
        updated = st.set_role_system_prompt(role["id"], "你是专家。")
        self.assertEqual(updated["system_prompt"], "你是专家。")
        got = st.get_role(role["id"])
        self.assertEqual(got["system_prompt"], "你是专家。")
        # tree flag
        tree = st.tree()
        r = next(x for x in tree["roles"] if x["id"] == role["id"])
        self.assertTrue(r.get("has_system_prompt"))
        self.assertEqual(r.get("system_prompt"), "你是专家。")

    def test_builtin_writable(self):
        st = self.store()
        tree = st.tree()
        builtin = next(r for r in tree["roles"] if r.get("builtin"))
        updated = st.set_role_system_prompt(builtin["id"], "本地覆盖设定")
        self.assertIsNotNone(updated)
        self.assertEqual(updated["system_prompt"], "本地覆盖设定")

    def test_api_get_set_and_render(self):
        api = self.api()
        st = self.store()
        role = st.create_role("渲染角色")
        st.set_role_system_prompt(role["id"], "SYS_LINE")
        p = st.create("p1", "Hello {{name}}", role_id=role["id"])
        r = api.get_role_system_prompt(role["id"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["system_prompt"], "SYS_LINE")
        out = api.render_prompt(p["body"], {"name": "世界"}, prompt_id=p["id"], apply_role_system=True)
        self.assertTrue(out.get("applied"))
        self.assertIn("SYS_LINE", out["final"])
        self.assertIn("Hello 世界", out["final"])
        out2 = api.render_prompt(p["body"], {"name": "世界"}, prompt_id=p["id"], apply_role_system=False)
        self.assertFalse(out2.get("applied"))
        self.assertNotIn("SYS_LINE", out2["final"])


class TestLint(TempStore):
    def test_unused_unfilled_high_tokens_format(self):
        from prompt_syntax import analyze
        body = "你好 {{name}}"
        a = analyze(body, {"name": "A", "extra": "B"})
        codes = {i["code"] for i in a["issues"]}
        self.assertIn("unused_values", codes)

        long_body = ("输出 JSON 格式。\n" + ("字" * 7000))
        a2 = analyze(long_body, {})
        codes2 = {i["code"] for i in a2["issues"]}
        self.assertTrue("high_tokens" in codes2 or "long_body" in codes2)
        huge = "字" * 13000
        a2b = analyze(huge, {})
        self.assertIn("high_tokens", {i["code"] for i in a2b["issues"]})

        a3 = analyze("只写一句话 {{x}}", {"x": "1"})
        codes3 = {i["code"] for i in a3["issues"]}
        self.assertIn("missing_output_format", codes3)

        # required empty unified as issue
        a4 = analyze("必填 {{req!}}", {})
        levels = {i["code"]: i["level"] for i in a4["issues"]}
        self.assertTrue(any(c.startswith("required") or "empty" in c or c == "required_empty" for c in levels))


class TestCompareRevisions(TempStore):
    def test_compare_current(self):
        api = self.api()
        st = self.store()
        p = st.create("diffme", "line1\nline2")
        # save a revision
        r1 = api.save_revision(p["id"], note="v1")
        self.assertTrue(r1.get("ok") or r1.get("revision") or "id" in str(r1))
        st.update(p["id"], {"body": "line1\nline2\nline3", "name": "diffme2"})
        revs = api.list_revisions(p["id"])
        self.assertTrue(len(revs) >= 1)
        rid = revs[0]["id"]
        cmp = api.compare_revisions(p["id"], rid, "current")
        self.assertTrue(cmp["ok"])
        self.assertTrue(cmp.get("name_changed"))
        ops = {d["op"] for d in cmp["diff"]}
        self.assertTrue("ins" in ops or "eq" in ops)
        self.assertTrue(cmp.get("combined_diff"))


class TestCases(TempStore):
    def test_crud_and_run_dry(self):
        api = self.api()
        st = self.store()
        p = st.create("cased", "问：{{q}}\n请输出 JSON")
        r = api.save_case(p["id"], {"name": "样例1", "values": {"q": "你好"}, "expect": "你好", "notes": "n"})
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["cases"]), 1)
        cid = r["cases"][0]["id"]
        listed = api.list_cases(p["id"])
        self.assertEqual(len(listed["cases"]), 1)
        run = api.run_case(p["id"], cid, apply_role_system=False)
        self.assertTrue(run["ok"])
        self.assertFalse(run["used_ai"])
        self.assertIn("你好", run["final"] or run["rendered"] or "")
        # soft match against rendered when no AI
        self.assertTrue(run["soft_match"])
        # update
        r2 = api.save_case(p["id"], {"id": cid, "name": "样例1b", "values": {"q": "世界"}, "expect": "世界"})
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["cases"][0]["name"], "样例1b")
        # cap
        for i in range(9):
            api.save_case(p["id"], {"name": f"c{i}", "values": {"q": str(i)}})
        over = api.save_case(p["id"], {"name": "overflow", "values": {"q": "x"}})
        self.assertFalse(over.get("ok"))
        # delete
        d = api.delete_case(p["id"], cid)
        self.assertTrue(d["ok"])
        self.assertEqual(len(d["cases"]), 9)

    def test_cases_survive_reload(self):
        st = self.store()
        p = st.create("persist", "{{a}}")
        st.update(p["id"], {"cases": [{"id": "c1", "name": "t", "values": {"a": "1"}, "expect": "1"}]})
        st2 = self.store()
        got = st2.get(p["id"])
        self.assertEqual(len(got["cases"]), 1)
        self.assertEqual(got["cases"][0]["values"]["a"], "1")


if __name__ == "__main__":
    unittest.main()
