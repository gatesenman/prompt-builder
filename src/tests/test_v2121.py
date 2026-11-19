"""2.12.1 — selection, AI models, editor HL, radio/multi, AI fill, no kw row, prune step titles."""
from __future__ import annotations
import json, os, re, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestVersion2121(unittest.TestCase):
    def test_version_files(self):
        ver = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(ver, "2.12.8")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', api)
        iss = (ROOT / "installer" / "PromptBuilder.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "2.12.8"', iss)
        setup = (ROOT / "installer" / "setup_main.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "2.12.8"', setup)


class TestSelectionIndicator(unittest.TestCase):
    def test_main_leaf_single_bar(self):
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".item.tree-leaf.active::before { content: none;", css)
        self.assertIn("box-shadow: inset 2px 0 0", css)
        # no accent recolor stacking on active indent
        block = css[css.find(".item.tree-leaf.active"): css.find(".item.tree-leaf.active") + 350]
        self.assertNotIn("border-left-color: var(--primary)", block)
        self.assertNotIn("border-left-color: var(--accent)", block)

    def test_quick_single_bar(self):
        css = (ROOT / "web" / "css" / "quick.css").read_text(encoding="utf-8")
        self.assertIn(".qp-item.sel::before { content: none;", css)
        self.assertIn("box-shadow: inset 2px 0 0 var(--primary)", css)
        self.assertNotIn(".qp-item.sel { border-left-color: var(--primary); }", css)


class TestEditorChrome2121(unittest.TestCase):
    def test_merged_head_no_toolbar_row(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="panel-head editor-head"', html)
        self.assertIn('id="insertBtn"', html)
        # AI button lives in titlebar, not editor toolbar
        self.assertIn('id="aiBtn"', html)
        # single aiBtn occurrence in titlebar area
        self.assertEqual(html.count('id="aiBtn"'), 1)
        tb_start = html.find('class="tb-actions"')
        tb_end = html.find("</header>", tb_start)
        tb = html[tb_start:tb_end]
        self.assertIn('id="aiBtn"', tb)
        self.assertIn('class="tb-group"', tb)
        # no standalone editor .toolbar row with insert
        self.assertNotIn('<div class="toolbar">', html.split('id="editorPanel"')[1].split('id="sidePanel"')[0])

    def test_editor_var_highlight_layer(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="editorHL"', html)
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".editor-hl", css)
        self.assertIn(".editor-hl .v", css)
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("updateEditorHL", js)
        self.assertIn("buildEditorHL", js)
        self.assertIn("roleName === \"我的提示\"", js)

    def test_no_item_meta_in_rows(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        # promptRowHTML should not inject item-meta
        self.assertNotIn("item-meta", js[js.find("function promptRowHTML"): js.find("function promptRowHTML") + 800]
                         if "function promptRowHTML" in js else "")

    def test_ai_tabs_no_parallel(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        # AI drawer tabs should not advertise 并行测
        ai = html[html.find('id="aiPanel"'): html.find('id="aiPanel"') + 1200]
        self.assertNotIn("并行测", ai)
        self.assertIn("生成", ai)
        self.assertIn("改写", ai)
        self.assertIn("评审", ai)


class TestListAiModels(unittest.TestCase):
    def test_api_and_provider(self):
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn("def list_ai_models", api)
        ap = (ROOT / "src" / "ai_providers.py").read_text(encoding="utf-8")
        self.assertIn("def list_models", ap)
        self.assertIn("def preset_models", ap)

    def test_list_models_preset_fallback(self):
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from ai_providers import list_models, preset_models
        r = list_models(kind="openai", base_url="", api_key="", preset="openai")
        self.assertTrue(r.get("ok"))
        self.assertEqual(r.get("source"), "preset")
        self.assertTrue(r.get("models"))
        self.assertEqual(r["models"], preset_models("openai"))


class TestPinIcon(unittest.TestCase):
    def test_pin_path_not_yen(self):
        ic = (ROOT / "web" / "js" / "icons.js").read_text(encoding="utf-8")
        m = re.search(r"pin:\s*'([^']+)'", ic)
        self.assertTrue(m)
        path = m.group(1)
        self.assertNotIn("¥", path)
        self.assertIn("M12 17v5", path)



class TestRadioMultiselect(unittest.TestCase):
    def test_parse_and_render(self):
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from prompt_syntax import analyze, render, MULTI_JOIN
        body = "优先级={{优先级:单选:高/中/低|中}} 标签={{标签:多选:技术/产品/设计}}"
        a = analyze(body, {})
        names = {v["name"]: v for v in a["variables"]}
        self.assertEqual(names["优先级"]["control"], "radio")
        self.assertEqual(names["优先级"]["options"], ["高", "中", "低"])
        self.assertEqual(names["优先级"]["default"], "中")
        self.assertFalse(names["优先级"]["required"])  # has default
        self.assertEqual(names["标签"]["control"], "multiselect")
        self.assertEqual(names["标签"]["options"], ["技术", "产品", "设计"])
        out = render(body, {"优先级": "高", "标签": MULTI_JOIN.join(["技术", "设计"])})
        self.assertIn("优先级=高", out)
        self.assertIn("标签=技术、设计", out)

    def test_ui_snippets_and_forms(self):
        app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("单选:高/中/低", app)
        self.assertIn("多选:A/B/C", app)
        self.assertIn('data-choice="radio"', app)
        self.assertIn('data-choice="multi"', app)
        self.assertIn("function readFormValue", app)
        qj = (ROOT / "web" / "js" / "quick.js").read_text(encoding="utf-8")
        self.assertIn('data-choice="radio"', qj)
        self.assertIn("function readFieldValue", qj)
        self.assertIn("runAiFill", qj)
        self.assertIn("ai_fill_form", qj)
        qh = (ROOT / "web" / "quick.html").read_text(encoding="utf-8")
        self.assertIn('id="aiFill"', qh)
        self.assertIn('id="aiNeed"', qh)
        self.assertIn("AI 填写", qh)


class TestAiFillForm(unittest.TestCase):
    def test_coerce_and_api_surface(self):
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from ai_service import _coerce_fill_values, SYS_FILL_FORM
        self.assertIn("JSON", SYS_FILL_FORM)
        vars_ = [
            {"name": "语气", "control": "select", "options": ["正式", "轻松"]},
            {"name": "优先级", "control": "radio", "options": ["高", "中", "低"]},
            {"name": "标签", "control": "multiselect", "options": ["A", "B", "C"]},
            {"name": "字数", "control": "number", "options": []},
            {"name": "主题", "control": "text", "options": []},
        ]
        raw = {"语气": "轻松", "优先级": "urgent", "标签": "A,B,X", "字数": "abc", "主题": "周报"}
        out = _coerce_fill_values(vars_, raw)
        self.assertEqual(out.get("语气"), "轻松")
        self.assertNotIn("优先级", out)  # invalid enum dropped
        self.assertEqual(out.get("标签"), "A、B")  # X dropped, joined
        self.assertNotIn("字数", out)  # non-number dropped
        self.assertEqual(out.get("主题"), "周报")
        api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertIn("def ai_fill_form", api)
        self.assertIn("need_settings", api)

    def test_run_fill_form_empty(self):
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from ai_service import run_fill_form
        r = run_fill_form({"kind": "openai", "base_url": "", "api_key": "x", "model": "m"}, [], "hello")
        self.assertFalse(r["ok"])
        r2 = run_fill_form({"kind": "openai", "base_url": "", "api_key": "x", "model": "m"},
                           [{"name": "a", "control": "text"}], "")
        self.assertFalse(r2["ok"])


class TestNoKwRow(unittest.TestCase):
    def test_no_kw_row(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="kwRow"', html)
        self.assertNotIn('id="kwInput"', html)
        self.assertIn('id="tagsRow"', html)
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("#kwInput", js)
        self.assertNotIn("#kwChips", js)
        self.assertIn("function persistKeywords", js)




STEP_NAME_RE = re.compile(r"第[一二三四五六七八九十\d]+步|第\d+步")


class TestBuiltinTitlesNoSteps(unittest.TestCase):
    def _load(self, rel):
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))

    def test_builtins_and_import_names(self):
        for rel in ("data/builtins.json", "PromptBuilder-skills-import.json", "data/_skills_only.json"):
            data = self._load(rel)
            prompts = data.get("prompts") or []
            names = [p.get("name") or "" for p in prompts]
            for name in names:
                self.assertFalse(STEP_NAME_RE.search(name), f"{rel}: {name}")
                self.assertNotIn("完整流程", name)
                self.assertFalse(name.endswith(("。", ".", "！", "!", "？", "?", "：", ":")))
            # expected clean product titles
            if rel.endswith("builtins.json"):
                for want in ("竞品分析", "产品指标复盘", "用户故事拆解"):
                    self.assertIn(want, names)

    def test_skills_only_synced(self):
        b = self._load("data/builtins.json")
        so = self._load("data/_skills_only.json")
        bp = {p["id"] for p in b["prompts"] if any(str(t).startswith("skill:") for t in (p.get("tags") or []))}
        sop = {p["id"] for p in so["prompts"]}
        self.assertEqual(bp, sop)
        # retired step/sibling id from 2.11 gone list
        self.assertNotIn("bp-sk-836cf0f052", sop)


class TestPruneObsoleteBuiltins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PROMPTBUILDER_DATA_DIR"] = self.tmp.name
        sys.path.insert(0, str(ROOT / "src"))
        import settings_store
        settings_store._cache["mtime"] = settings_store._cache["data"] = None

    def tearDown(self):
        os.environ.pop("PROMPTBUILDER_DATA_DIR", None)
        self.tmp.cleanup()

    def test_prunes_step_split_builtin_keeps_user(self):
        from prompts_store import PromptStore, prompts_path
        s = PromptStore()
        mine = s.create("我的私有提示", "你好 {{名}}")
        path = prompts_path()
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        # simulate leftover 2.9.0 step-split builtins still in library
        d["prompts"].append({
            "id": "bp-sk-obsolete-step-demo",
            "name": "竞品分析-第三步-第四步: Porter 五力分析",
            "body": "旧分步正文 {{产品}}",
            "role_id": "role-pm",
            "category_id": "",
            "builtin": True,
            "system": True,
            "tags": ["步骤", "skill:竞品分析"],
            "keywords": [],
            "summary": "",
            "order": 0,
        })
        # also a user custom that looks like a step name — must survive
        d["prompts"].append({
            "id": "user-custom-step-looking",
            "name": "我的流程第一步",
            "body": "自定义 {{x}}",
            "role_id": d["prompts"][0]["role_id"] if d["prompts"] else "role-mine",
            "category_id": "",
            "builtin": False,
            "system": False,
            "tags": [],
            "keywords": [],
            "summary": "",
            "order": 0,
        })
        Path(path).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        import settings_store
        settings_store._cache["mtime"] = settings_store._cache["data"] = None
        s2 = PromptStore()
        ids = {p["id"] for p in s2.list()}
        self.assertNotIn("bp-sk-obsolete-step-demo", ids)
        self.assertIn(mine["id"], ids)
        self.assertIn("user-custom-step-looking", ids)
        # live 竞品分析 keeps clean title
        hit = [s2.get(p["id"]) for p in s2.list() if s2.get(p["id"]).get("name") == "竞品分析"]
        self.assertTrue(hit)
        self.assertTrue(hit[0].get("builtin"))


class TestNoItemMeta(unittest.TestCase):
    def test_list_row_has_no_item_meta(self):
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("item-meta", js)
        i = js.find("function promptRowHTML")
        j = js.find("function renderList", i)
        block = js[i:j if j > i else i + 2500]
        self.assertIn("item-name", block)
        self.assertNotIn("变量 ·", block)
        # relativeTime helper may still mention 天前; list rows must not
        self.assertNotIn("${n} 天前", block)
        self.assertNotIn("变量 ·", block)



if __name__ == "__main__":
    unittest.main()
