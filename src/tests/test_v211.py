"""2.11.x — builtins dedupe, indent CSS, AI workshop (mocked HTTP)."""
from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class TestVersion211(unittest.TestCase):
    def test_version(self):
        from api import APP_VERSION
        self.assertRegex(APP_VERSION, r"^2\.1[12]\.\d+$")
        self.assertRegex((ROOT / "VERSION.txt").read_text(encoding="utf-8").strip(), r"^2\.1[12]\.\d+$")


class TestBuiltinsDedupe(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "data" / "builtins.json").read_text(encoding="utf-8"))

    def test_counts(self):
        self.assertEqual(len(self.data["prompts"]), 147)
        self.assertEqual(len(self.data.get("categories") or []), 0)
        self.assertGreaterEqual(len(self.data["roles"]), 10)

    def test_unique_ids_and_names(self):
        ids = [p["id"] for p in self.data["prompts"]]
        names = [p["name"] for p in self.data["prompts"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))

    def test_removed_overlap_ids_gone(self):
        gone = {
            "bp-ef57922977", "bp-9064ca30e7", "bp-na24c89f03", "bp-n522e5f0aa",
            "bp-94e0282b81", "bp-f108a03ddd", "bp-ec3e0965b6", "bp-sk-836cf0f052",
        }
        have = {p["id"] for p in self.data["prompts"]}
        self.assertFalse(gone & have)

    def test_skills_import_refreshed(self):
        p = ROOT / "PromptBuilder-skills-import.json"
        self.assertTrue(p.is_file())
        d = json.loads(p.read_text(encoding="utf-8"))
        prompts = d.get("prompts") or d if isinstance(d, list) else d.get("prompts") or []
        if isinstance(d, dict) and "prompts" in d:
            prompts = d["prompts"]
        self.assertGreaterEqual(len(prompts), 40)


class TestIndentUI(unittest.TestCase):
    def test_sidebar_depth_css(self):
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".item.tree-leaf.depth-1", css)
        self.assertIn("border-left", css)
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("promptRowHTML(p, idx++, 1)", js)

    def test_quick_indent(self):
        css = (ROOT / "web" / "css" / "quick.css").read_text(encoding="utf-8")
        self.assertIn("padding-left: 30px", css)  # 2.12.1 indent
        self.assertIn(".qp-role", css)
        js = (ROOT / "web" / "js" / "quick.js").read_text(encoding="utf-8")
        self.assertIn("qp-role", js)
        self.assertIn("data-collapse", js)


class TestAiCrypto(unittest.TestCase):
    def test_roundtrip(self):
        from ai_crypto import encrypt_secret, decrypt_secret, mask_secret
        plain = "sk-test-secret-abcdef"
        enc = encrypt_secret(plain)
        self.assertNotEqual(enc, plain)
        self.assertEqual(decrypt_secret(enc), plain)
        m = mask_secret(plain)
        self.assertNotIn("abcdef", m)
        self.assertTrue(m.startswith("sk-") or "•" in m)


class TestAiProviders(unittest.TestCase):
    def test_presets_cover_regions(self):
        from ai_providers import list_presets
        presets = list_presets()
        ids = {p["id"] for p in presets}
        for need in ("openai", "anthropic", "gemini", "dashscope", "zhipu",
                     "deepseek", "moonshot", "baichuan", "doubao",
                     "openrouter", "siliconflow", "custom"):
            self.assertIn(need, ids)
        regions = {p["region"] for p in presets}
        self.assertIn("international", regions)
        self.assertIn("domestic", regions)
        self.assertIn("aggregator", regions)

    def test_chat_mocked(self):
        from ai_providers import chat_completion
        fake = {"ok": True, "status": 200, "data": {
            "choices": [{"message": {"content": "## 角色\n\n请根据 {{问题}} 回答。"}}]
        }}
        with mock.patch("ai_providers._http_json", return_value=fake) as http:
            r = chat_completion(kind="openai", base_url="https://api.openai.com/v1",
                                api_key="sk-x", model="gpt-4o-mini",
                                messages=[{"role": "user", "content": "hi"}], timeout=5)
            self.assertTrue(r["ok"])
            self.assertIn("{{问题}}", r["text"])
            self.assertTrue(http.called)

    def test_parallel_mocked(self):
        from ai_providers import parallel_chat
        def fake_http(method, url, headers, body, timeout):
            return {"ok": True, "status": 200, "data": {
                "choices": [{"message": {"content": f"out:{body.get('model')}"}}]
            }}
        targets = [
            {"id": "a", "kind": "openai", "base_url": "https://x/v1", "api_key": "k", "model": "m1", "label": "A"},
            {"id": "b", "kind": "openai", "base_url": "https://x/v1", "api_key": "k", "model": "m2", "label": "B"},
        ]
        with mock.patch("ai_providers._http_json", side_effect=fake_http):
            rows = parallel_chat(targets, [{"role": "user", "content": "ping"}], timeout=5, max_workers=2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["ok"] for r in rows))


class TestAiApiBridge(unittest.TestCase):
    def test_generate_rewrite_review_parallel(self):
        from api import Api
        api = Api.__new__(Api)
        # minimal stubs
        api._store = None
        api._on_hide = api._on_quit = api._on_settings_changed = None
        api._autostart_on = lambda: False
        api._apply_autostart = lambda on: ""

        profile = {
            "id": "aip-test", "name": "Mock", "preset": "openai", "kind": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key_enc": "", "default_model": "gpt-4o-mini", "models": ["gpt-4o-mini"],
        }
        from ai_crypto import encrypt_secret
        profile["api_key_enc"] = encrypt_secret("sk-mock")

        settings = {"ai_profiles": [profile], "ai_default_profile": "aip-test"}

        with mock.patch("api.load_settings", return_value=settings), \
             mock.patch("api.save_settings", side_effect=lambda patch: {**settings, **patch}), \
             mock.patch("ai_providers._http_json") as http:
            http.return_value = {"ok": True, "status": 200, "data": {
                "choices": [{"message": {"content": "# 模板\n\n{{目标}}\n"}}]
            }}
            g = api.ai_generate("写一个代码审查提示词", "IDE", "", "aip-test", "gpt-4o-mini")
            self.assertTrue(g["ok"], g)
            self.assertIn("{{", g["text"])

            http.return_value = {"ok": True, "status": 200, "data": {
                "choices": [{"message": {"content": "# 改写\n\n{{代码:多行}}\n"}}]
            }}
            rw = api.ai_rewrite("旧正文", "更清晰", "aip-test", "gpt-4o-mini")
            self.assertTrue(rw["ok"], rw)

            http.return_value = {"ok": True, "status": 200, "data": {
                "choices": [{"message": {"content": "## 总评\n良\n"}}]
            }}
            rev = api.ai_review("待审", "aip-test", "gpt-4o-mini")
            self.assertTrue(rev["ok"], rev)

            http.return_value = {"ok": True, "status": 200, "data": {
                "choices": [{"message": {"content": "模型回答"}}]
            }}
            par = api.ai_parallel_test("填好的样例", [{"profile_id": "aip-test", "model": "gpt-4o-mini"}])
            self.assertTrue(par["ok"], par)
            self.assertEqual(len(par["results"]), 1)
            self.assertTrue(par["results"][0]["ok"])

    def test_no_key_error(self):
        from api import Api
        api = Api.__new__(Api)
        with mock.patch("api.load_settings", return_value={"ai_profiles": [], "ai_default_profile": ""}):
            r = api.ai_generate("goal")
            self.assertFalse(r["ok"])
            self.assertIn("API Key", r["error"])

    def test_settings_redacts_keys(self):
        from api import Api
        from ai_crypto import encrypt_secret
        api = Api.__new__(Api)
        api._autostart_on = lambda: False
        profiles = [{
            "id": "aip-1", "name": "X", "preset": "openai", "kind": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key_enc": encrypt_secret("sk-secret-key-zzzz"),
            "default_model": "gpt-4o-mini", "models": ["gpt-4o-mini"],
        }]
        with mock.patch("api.load_settings", return_value={"ai_profiles": profiles, "ai_default_profile": "aip-1",
                                                          "quick_enabled": True, "theme": "system"}):
            s = api.get_settings()
            blob = json.dumps(s, ensure_ascii=False)
            self.assertNotIn("sk-secret-key-zzzz", blob)
            self.assertNotIn("api_key_enc", blob)
            self.assertTrue(s["ai_profiles"][0]["has_key"])


class TestAiWorkshopUI(unittest.TestCase):
    def test_html_and_js_wired(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="aiPanel"', html)  # 2.11.1: right drawer, not overlay
        self.assertIn('id="aiBtn"', html)
        self.assertIn('data-pane="ai"', html)
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        for needle in ("openAiStudio", "ai_generate", "ai_rewrite", "ai_review",
                       "ai_parallel_test", "save_ai_profile", "renderAiProfiles"):
            self.assertIn(needle, js)


if __name__ == "__main__":
    unittest.main()
