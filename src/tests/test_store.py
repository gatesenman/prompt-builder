"""Storage / migration / settings tests (isolated temp data dir).
Run:  python -m unittest discover -s src/tests -v"""
import json, os, sys, tempfile, threading, unittest
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # src/


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


class AtomicIO(TempData):
    def test_write_keeps_backup_and_no_tmp(self):
        from atomic_io import write_json_atomic
        p = self.dir / "x.json"
        write_json_atomic(p, {"v": 1})
        write_json_atomic(p, {"v": 2})
        self.assertEqual(json.loads(p.read_text("utf-8"))["v"], 2)
        self.assertEqual(json.loads((self.dir / "x.json.bak").read_text("utf-8"))["v"], 1)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_unserialisable_never_touches_file(self):
        from atomic_io import write_json_atomic
        p = self.dir / "x.json"
        write_json_atomic(p, {"v": 1})
        with self.assertRaises(TypeError):
            write_json_atomic(p, {"v": object()})
        self.assertEqual(json.loads(p.read_text("utf-8"))["v"], 1)

    def test_concurrent_writes(self):
        from atomic_io import write_json_atomic
        p = self.dir / "c.json"
        errs = []

        def w(i):
            try:
                for k in range(20):
                    write_json_atomic(p, {"i": i, "k": k, "pad": "x" * 2000})
            except Exception as e:  # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=w, args=(i,)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        json.loads(p.read_text("utf-8"))


class Library(TempData):
    def test_fresh_seeds_examples_once(self):
        s = self.store()
        names = [p["name"] for p in s.list()]
        self.assertTrue(any("周报" in n for n in names))
        # delete user/example prompts only; builtins are re-merged unless hidden
        for p in list(s.list()):
            if not p.get("builtin"):
                s.delete(p["id"])
        s2 = self.store()
        self.assertFalse(any("周报" in (p["name"] or "") and not p.get("builtin") for p in s2.list()))

    def test_crud_duplicate_search(self):
        s = self.store()
        p = s.create("测试", "你好 {{名}}\r\n第二行")
        self.assertNotIn("\r", s.get(p["id"])["body"])
        d = s.duplicate(p["id"])
        self.assertEqual(d["name"], "测试 副本")
        self.assertEqual(s.get(d["id"])["body"], s.get(p["id"])["body"])
        d2 = s.duplicate(p["id"])
        self.assertEqual(d2["name"], "测试 副本 2")
        s.update(p["id"], {"name": "改名"})
        self.assertEqual(s.list("改名")[0]["id"], p["id"])
        self.assertTrue(s.delete(d2["id"]))
        self.assertIsNone(s.get(d2["id"]))
        # persisted
        s2 = self.store()
        self.assertEqual(s2.get(p["id"])["name"], "改名")

    def test_touch_used_last_values_and_order(self):
        s = self.store()
        for p in s.list():
            s.delete(p["id"])
        a = s.create("A", "{{x}}")
        b = s.create("B", "{{y}}")
        c = s.create("C", "plain")
        s.touch_used(a["id"], {"x": "1", "unknown": "z"})
        s.touch_used(a["id"], {"x": "2"})
        s.touch_used(b["id"], {"y": "q"})
        got = s.get(a["id"])
        self.assertEqual(got["use_count"], 2)
        self.assertEqual(got["last_values"], {"x": "2"})
        order = [i["name"] for i in s.quick_items()]
        self.assertEqual(order[:2], ["B", "A"])  # most recent first
        self.assertTrue(s.quick_items()[0]["recent"])
        self.assertIn("C", order)

    def test_corrupt_library_recovers_from_backup(self):
        s = self.store()
        p = s.create("重要", "{{a}}")
        s.update(p["id"], {"body": "{{a}} v2"})  # second write → .bak holds a good copy
        path = self.dir / "prompts.json"
        path.write_text("{ broken json", encoding="utf-8")
        s2 = self.store()
        self.assertEqual(s2.recovered, "bak")
        self.assertIsNotNone(s2.get(p["id"]))
        self.assertTrue(list(self.dir.glob("prompts.corrupt-*.json")))
        json.loads(path.read_text("utf-8"))  # main file repaired

    def test_corrupt_without_backup_keeps_copy(self):
        (self.dir / "prompts.json").write_text("garbage", encoding="utf-8")
        s = self.store()
        self.assertEqual(s.recovered, "default")
        self.assertTrue(list(self.dir.glob("prompts.corrupt-*.json")))

    def test_duplicate_ids_are_fixed(self):
        data = {"format": "promptbuilder-prompts", "version": 3,
                "prompts": [{"id": "same", "name": "1", "body": "a"}, {"id": "same", "name": "2", "body": "b"}]}
        (self.dir / "prompts.json").write_text(json.dumps(data), encoding="utf-8")
        (self.dir / "settings.json").write_text(json.dumps({"examples_seeded": True}), encoding="utf-8")
        s = self.store()
        ids = [p["id"] for p in s.list()]
        self.assertEqual(len(ids), len(set(ids)))  # every id unique after repair
        user = [p for p in s.list() if not p.get("builtin")]
        self.assertEqual(len(user), 2)

    def test_v24_library_loads_unchanged(self):
        data = {"format": "promptbuilder-prompts", "version": 3,
                "prompts": [{"id": "p-1", "name": "旧", "body": "{{a|1}}", "test_values": {"a": "9"},
                             "created_at": "2026-01-01T00:00:00+08:00", "updated_at": "2026-01-02T00:00:00+08:00",
                             "last_used_at": ""}]}
        (self.dir / "prompts.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (self.dir / "settings.json").write_text(json.dumps({"examples_seeded": True, "theme": "light"}), encoding="utf-8")
        s = self.store()
        p = s.get("p-1")
        self.assertEqual((p["name"], p["body"], p["test_values"]), ("旧", "{{a|1}}", {"a": "9"}))
        self.assertEqual(p["use_count"], 0)
        self.assertEqual(p["last_values"], {})
        self.assertTrue((self.dir / "backups").exists())  # startup snapshot

    def test_v2x_migration_keeps_legacy_files(self):
        templates = {"templates": [
            {"id": "u1", "name": "我的模板", "template": "写 {{主题}}，参考 {{代码}}，时间 {{时间:上午}}", "builtin": False},
            {"id": "b1", "name": "内置未用", "template": "x", "builtin": True},
            {"id": "b2", "name": "内置收藏", "template": "{{内容|默认}}", "builtin": True, "favorite": True},
        ]}
        (self.dir / "templates.json").write_text(json.dumps(templates, ensure_ascii=False), encoding="utf-8")
        (self.dir / "last_values.json").write_text(json.dumps({"u1": {"主题": "AI"}}, ensure_ascii=False), encoding="utf-8")
        (self.dir / "history.json").write_text("[]", encoding="utf-8")
        (self.dir / "settings.json").write_text(json.dumps({"theme": "light", "old_key": 1}), encoding="utf-8")
        s = self.store()
        self.assertTrue(s.migration["migrated"])
        names = [p["name"] for p in s.list()]
        self.assertIn("我的模板", names)
        self.assertIn("内置收藏", names)
        self.assertNotIn("内置未用", names)
        p = s.get("u1")
        self.assertIn("{{代码:多行}}", p["body"])
        self.assertIn("{{时间-上午}}", p["body"])
        self.assertEqual(p["test_values"], {"主题": "AI"})
        for f in ("templates.json", "last_values.json", "history.json"):
            self.assertFalse((self.dir / f).exists())
            self.assertTrue((self.dir / "legacy-2.x" / f).exists())
        from settings_store import load_settings
        st = load_settings()
        self.assertEqual(st["theme"], "light")
        self.assertNotIn("old_key", st)
        # second start: no re-migration, data stays
        s2 = self.store()
        self.assertEqual(sorted(p["name"] for p in s2.list()), sorted(names))

    def test_unreadable_v2_file_is_left_alone(self):
        (self.dir / "templates.json").write_text("{not json", encoding="utf-8")
        s = self.store()
        self.assertFalse(s.migration["migrated"])
        self.assertTrue((self.dir / "templates.json").exists())

    def test_import_formats(self):
        s = self.store()
        before = len(s.list())
        r = s.import_payload({"prompts": [{"id": "i1", "name": "导入", "body": "{{a}}"}]})
        self.assertEqual((r["ok"], r["added"]), (True, 1))
        r = s.import_payload({"prompts": [{"id": "i1", "name": "导入2", "body": "{{b}}"}]})
        self.assertEqual(r["replaced"], 1)
        r = s.import_payload([{"id": "t1", "name": "老模板", "template": "{{x}}"}])
        self.assertEqual(r["kind"], "2.x")
        r = s.import_payload({"name": "单个", "body": "hi"})
        self.assertTrue(r["ok"])
        self.assertFalse(s.import_payload("nonsense")["ok"])
        self.assertEqual(len(s.list()), before + 3)
        self.assertTrue(list((self.dir / "backups").glob("prompts-*.json")))

    def test_import_markdown_encodings(self):
        s = self.store()
        f1 = self.dir / "utf8.md"
        f1.write_bytes("\ufeff# 标题\r\n{{名}}".encode("utf-8"))
        f2 = self.dir / "gbk.md"
        f2.write_bytes("中文 {{变量}}".encode("gbk"))
        p1 = s.import_markdown(str(f1))
        p2 = s.import_markdown(str(f2))
        self.assertEqual(p1["body"], "# 标题\n{{名}}")
        self.assertEqual(p1["name"], "utf8")
        self.assertIn("{{变量}}", p2["body"])
        p3 = s.import_markdown(str(f1))
        self.assertEqual(p3["name"], "utf8 2")


class Settings(TempData):
    def test_normalize_and_exclude(self):
        from settings_store import exclude_set, load_settings, save_settings
        s = save_settings({"quick_exclude": "Code; C:\\Tools\\game.EXE ,code.exe，mstsc", "theme": "purple",
                           "quick_follow": "x", "unknown": 1})
        self.assertEqual(s["quick_exclude"], "code.exe, game.exe, mstsc.exe")
        self.assertEqual(exclude_set(s), frozenset({"code.exe", "game.exe", "mstsc.exe"}))
        self.assertEqual(s["theme"], "system")
        self.assertEqual(s["quick_follow"], "caret")
        self.assertNotIn("unknown", load_settings())
        self.assertTrue(load_settings()["quick_skip_fullscreen"])

    def test_corrupt_settings_fall_back(self):
        from settings_store import load_settings
        (self.dir / "settings.json").write_text("{{{", encoding="utf-8")
        self.assertEqual(load_settings()["theme"], "system")


if __name__ == "__main__":
    unittest.main()
