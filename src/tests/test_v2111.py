"""2.11.1 — titles/keywords/summary, search, AI drawer, multi-model judge + last_ai_run."""
from __future__ import annotations
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMPTBUILDER_DATA_DIR"] = self.tmp.name
        try:
            import settings_store
            settings_store._cache["mtime"] = settings_store._cache["data"] = None
        except Exception:
            pass

    def tearDown(self):
        os.environ.pop("PROMPTBUILDER_DATA_DIR", None)
        self.tmp.cleanup()

    def store(self):
        from prompts_store import PromptStore
        return PromptStore()


class TestVersion2111(unittest.TestCase):
    def test_version(self):
        from api import APP_VERSION
        self.assertRegex(APP_VERSION, r"^2\.1[12]\.\d+$")
        self.assertRegex((ROOT / "VERSION.txt").read_text(encoding="utf-8").strip(), r"^2\.1[12]\.\d+$")
        cl = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")[:2000]
        self.assertTrue(any(x in cl for x in ("2.11.1", "2.12.0", "2.12.1", "2.12.2", "2.12.3", "2.12.4", "2.12.5", "2.12.8")))


class TestBuiltinTitlesKeywords(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "data" / "builtins.json").read_text(encoding="utf-8"))
        self.prompts = self.data["prompts"]

    def test_count(self):
        self.assertEqual(len(self.prompts), 147)

    def test_every_prompt_has_keywords(self):
        for p in self.prompts:
            self.assertIsInstance(p.get("keywords"), list, p.get("name"))
            self.assertGreaterEqual(len(p["keywords"]), 1, p.get("name"))
            for kw in p["keywords"]:
                self.assertTrue(isinstance(kw, str) and kw.strip(), p.get("name"))
            s = p.get("summary") or ""
            if s:
                self.assertFalse(s.strip().startswith("{{"))

    def test_titles_style(self):
        for p in self.prompts:
            name = p["name"]
            self.assertGreaterEqual(len(name), 4, name)
            self.assertLessEqual(len(name), 20, name)
            self.assertNotIn("完整流程", name)
            self.assertFalse(name.endswith(("。", ".", "！", "!", "？", "?")))

    def test_unique_names(self):
        names = [p["name"] for p in self.prompts]
        self.assertEqual(len(names), len(set(names)))


class TestKeywordsStoreSearch(TempData):
    def test_norm_and_set_keywords(self):
        from prompts_store import _norm_keywords
        self.assertEqual(_norm_keywords("a, b；c"), ["a", "b", "c"])
        self.assertEqual(_norm_keywords(["  x ", "", "x", "y"]), ["x", "y"])
        s = self.store()
        p = s.create(name="测试关键词提示", body="请审查 {{代码}}",
                     keywords=["code review", "审查", "PR"], summary="代码审查短摘要")
        updated = s.set_keywords(p["id"], ["新词", "alias"])
        self.assertEqual(updated["keywords"], ["新词", "alias"])

    def test_search_hits_keywords_and_summary(self):
        s = self.store()
        p = s.create(name="测试关键词提示", body="请审查 {{代码}}",
                     keywords=["code review", "审查", "PR"], summary="代码审查短摘要")
        hits = s.list(query="code review")
        self.assertIn(p["id"], {h["id"] for h in hits})
        hits2 = s.list(query="代码审查短摘要")
        self.assertIn(p["id"], {h["id"] for h in hits2})

    def test_old_user_missing_keywords_migrates(self):
        from prompts_store import _clean_prompt
        raw = {"id": "u1", "name": "旧", "body": "hi", "role_id": "", "category_id": ""}
        cleaned = _clean_prompt(raw)
        self.assertEqual(cleaned["keywords"], [])
        self.assertEqual(cleaned.get("last_ai_run"), {})

    def test_summary_in_list(self):
        s = self.store()
        p = s.create(name="摘要预览提示", body="很长的正文内容用于预览回退 {{x}}",
                     keywords=["alias"], summary="代码审查短摘要")
        mine = next(x for x in s.list() if x["id"] == p["id"])
        self.assertEqual(mine["preview"], "代码审查短摘要")
        self.assertIn("alias", mine["keywords"])

    def test_last_ai_run_persist(self):
        s = self.store()
        p = s.create(name="试跑保存", body="请审查 {{x}}")
        run = {
            "at": "2026-10-26T10:00:00+08:00",
            "rendered_preview": "请审查 foo",
            "sort": "score",
            "results": [{
                "id": "t1", "label": "gpt", "model": "gpt-4o-mini", "ok": True,
                "text": "ok", "error": "", "latency_ms": 120,
                "user_score": 4, "ai_score": 5, "ai_note": "完整",
            }],
        }
        updated = s.update(p["id"], {"last_ai_run": run})
        self.assertEqual(updated["last_ai_run"]["results"][0]["user_score"], 4)
        got = s.get(p["id"])
        self.assertEqual(got["last_ai_run"]["rendered_preview"], "请审查 foo")


class TestAiJudgeAndSaveRun(TempData):
    def test_run_judge_parses_scores(self):
        from ai_service import run_judge
        fake = {
            "ok": True, "text": '[{"i":0,"score":4,"note":"好"},{"i":1,"score":2,"note":"缺"}]',
            "error": "", "latency_ms": 10,
        }
        with mock.patch("ai_service.chat_completion", return_value=fake):
            r = run_judge(
                {"kind": "openai", "base_url": "https://x", "api_key": "k", "model": "m"},
                "提示词",
                [{"label": "A", "text": "答1"}, {"label": "B", "text": "答2"}],
            )
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["scores"]), 2)
        self.assertEqual(r["scores"][0]["score"], 4)
        self.assertEqual(r["scores"][1]["score"], 2)

    def test_api_save_ai_run_caps(self):
        from api import Api
        s = self.store()
        p = s.create(name="n", body="b {{x}}")
        api = Api(s)
        big = "字" * 20000
        r = api.save_ai_run(p["id"], {
            "at": "t", "rendered_preview": "预览" * 100,
            "results": [{"id": "1", "label": "m", "model": "m", "ok": True,
                         "text": big, "user_score": 3, "ai_score": 4, "ai_note": "n"}],
        })
        self.assertTrue(r["ok"])
        saved = r["prompt"]["last_ai_run"]["results"][0]
        self.assertLessEqual(len(saved["text"]), 8000)
        self.assertLessEqual(len(r["prompt"]["last_ai_run"]["rendered_preview"]), 400)


class TestUiDrawerAndMm(unittest.TestCase):
    def test_ai_drawer_not_overlay(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="aiPanel"', html)
        self.assertNotIn("aiOverlay", html)
        self.assertIn("--ai-w", css)
        self.assertIn("ai-open", css)
        self.assertIn("closeAiDrawer", js)
        self.assertIn("function renderMmSection", js)
        self.assertIn("开始试跑", js)
        self.assertIn("ai_judge", js)
        self.assertIn("save_ai_run", js)
        self.assertIn("tagsRow", html)  # 2.12.1: kwRow removed
        self.assertIn("renderKwUI", js)

    def test_quick_searches_keywords(self):
        js = (ROOT / "web" / "js" / "quick.js").read_text(encoding="utf-8")
        self.assertIn("item.keywords", js)
        self.assertIn("qp-kws", js)


class TestBuiltinMergeRefresh(TempData):
    def test_merge_refreshes_existing_builtin_title_keywords(self):
        from prompts_store import PromptStore, prompts_path
        s = self.store()
        builtins = [p for p in s.list() if p.get("builtin")]
        self.assertGreater(len(builtins), 10)
        sample = s.get(builtins[0]["id"])
        old_name = sample["name"]
        path = prompts_path()
        raw = json.loads(path.read_text(encoding="utf-8"))
        for p in raw["prompts"]:
            if p["id"] == sample["id"]:
                p["name"] = "旧标题完整流程"
                p["keywords"] = []
                p["summary"] = ""
                break
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        store2 = PromptStore()
        refreshed = store2.get(sample["id"])
        self.assertNotEqual(refreshed["name"], "旧标题完整流程")
        self.assertEqual(refreshed["name"], old_name)
        self.assertGreaterEqual(len(refreshed.get("keywords") or []), 1)


if __name__ == "__main__":
    unittest.main()
