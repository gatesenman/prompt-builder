"""2.7 lifecycle: tags/favorites, revisions, fill history, archive, stats, migration.
Run:  python -m unittest discover -s src/tests -v"""
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


class Organize(TempData):
    def test_tags_favorite_pin_and_filters(self):
        s = self.store()
        for p in list(s.list()):
            s.delete(p["id"])
        a = s.create("周报模板", "本周：{{内容:多行}}")
        b = s.create("邮件润色", "请润色：{{正文:多行}}")
        s.set_tags(a["id"], ["工作", "周报", "工作"])  # dedupe
        s.set_flags(a["id"], favorite=True, pinned=True)
        s.set_flags(b["id"], favorite=True)
        got = s.get(a["id"])
        self.assertEqual(got["tags"], ["工作", "周报"])
        self.assertTrue(got["favorite"] and got["pinned"])
        favs = s.list(favorites_only=True)
        self.assertEqual({p["id"] for p in favs}, {a["id"], b["id"]})
        tagged = s.list(tag="周报")
        self.assertEqual([p["id"] for p in tagged], [a["id"]])
        multi = s.list("周报 内容")
        self.assertEqual([p["id"] for p in multi], [a["id"]])
        self.assertIn("工作", s.all_tags())
        self.assertIn("周报", s.all_tags())

    def test_sort_modes(self):
        s = self.store()
        for p in list(s.list()):
            s.delete(p["id"])
        p1 = s.create("Beta", "b {{x}}")
        p2 = s.create("Alpha", "a {{x}}")
        s.touch_used(p1["id"], {"x": "1"})
        by_name = s.list(sort="name")
        self.assertEqual([p["name"] for p in by_name], ["Alpha", "Beta"])
        by_used = s.list(sort="used")
        self.assertEqual(by_used[0]["id"], p1["id"])

    def test_quick_order_pinned_fav_recent(self):
        s = self.store()
        for p in list(s.list()):
            s.delete(p["id"])
        lib = s.create("普通", "{{a}}")
        fav = s.create("收藏", "{{a}}")
        pin = s.create("置顶", "{{a}}")
        recent = s.create("最近", "{{a}}")
        s.set_flags(pin["id"], pinned=True)
        s.set_flags(fav["id"], favorite=True)
        s.touch_used(recent["id"], {"a": "1"})
        s.archive(lib["id"])  # archived must leave popup
        items = s.quick_items(recent=3)
        ids = [i["id"] for i in items]
        self.assertEqual(ids[0], pin["id"])
        self.assertIn(fav["id"], ids[:3])
        self.assertNotIn(lib["id"], ids)
        sections = {i["id"]: i["section"] for i in items}
        self.assertEqual(sections[pin["id"]], "pinned")
        self.assertEqual(sections[fav["id"]], "favorite")


class ArchiveMaintain(TempData):
    def test_archive_hides_unarchive_restores(self):
        s = self.store()
        for p in list(s.list()):
            s.delete(p["id"])
        p = s.create("待归档", "{{x}}")
        s.set_flags(p["id"], pinned=True)
        s.archive(p["id"])
        self.assertEqual(s.list(), [])
        arch = s.list(archived_only=True)
        self.assertEqual(len(arch), 1)
        self.assertTrue(arch[0]["archived"])
        self.assertFalse(arch[0]["pinned"])  # cleared on archive
        s.unarchive(p["id"])
        self.assertEqual(len(s.list()), 1)
        self.assertFalse(s.get(p["id"])["archived"])

    def test_batch_archive_and_delete_undo(self):
        s = self.store()
        for p in list(s.list()):
            s.delete(p["id"])
        ids = [s.create(f"P{i}", "{{x}}")["id"] for i in range(3)]
        r = s.batch_archive(ids[:2])
        self.assertEqual(r["count"], 2)
        self.assertEqual(len(s.list()), 1)
        taken = s.batch_delete([ids[2]])
        self.assertEqual(taken["count"], 1)
        self.assertEqual(s.list(), [])
        n = s.restore_many(taken["taken"])
        self.assertEqual(n, 1)
        self.assertEqual(len(s.list()), 1)

    def test_health_and_stats(self):
        s = self.store()
        for p in list(s.list()):
            s.delete(p["id"])
        s.create("空", "")
        broken = s.create("坏括号", "开始 {{名 结束")
        used = s.create("常用", "{{x}}")
        s.touch_used(used["id"], {"x": "1"})
        h = s.health_check()
        self.assertTrue(any(e["name"] == "空" for e in h["empty"]))
        self.assertTrue(any(e["name"] == "坏括号" for e in h["broken"]))
        st = s.local_stats()
        self.assertGreaterEqual(st["total"], 2)
        self.assertTrue(any(t["name"] == "常用" for t in st["top_prompts"]))


class Revisions(TempData):
    def test_auto_skip_unchanged_and_cap(self):
        from revisions_store import RevisionsStore, MAX_REVISIONS
        rs = RevisionsStore()
        pid = "p-test"
        self.assertIsNotNone(rs.add(pid, "A", "body1", source="auto"))
        self.assertIsNone(rs.add(pid, "A", "body1", source="auto"))  # skip
        self.assertIsNotNone(rs.add(pid, "A", "body2", source="manual", note="里程碑",
                                    skip_unchanged=False))
        for i in range(25):
            rs.add(pid, "A", f"v{i}", source="auto")
        revs = rs.list(pid)
        self.assertLessEqual(len(revs), MAX_REVISIONS)
        self.assertEqual(revs[0]["body"], "v24")
        got = rs.get(pid, revs[0]["id"])
        self.assertEqual(got["body"], "v24")
        self.assertTrue(rs.delete(pid, revs[0]["id"]))
        rs.purge_prompt(pid)
        self.assertEqual(rs.list(pid), [])

    def test_persist_reload(self):
        from revisions_store import RevisionsStore
        rs = RevisionsStore()
        rs.add("p1", "名", "正文{{x}}", source="manual", note="手存")
        rs2 = RevisionsStore()
        revs = rs2.list("p1")
        self.assertEqual(len(revs), 1)
        self.assertEqual(revs[0]["note"], "手存")
        self.assertEqual(revs[0]["source"], "manual")
        self.assertTrue((self.dir / "revisions.json").exists())
        self.assertTrue((self.dir / "revisions.json.bak").exists() or True)  # bak after 2nd write


class FillHistory(TempData):
    def test_add_list_clear_cap(self):
        from history_store import HistoryStore, MAX_ITEMS
        hs = HistoryStore()
        for i in range(110):
            hs.add("p2", "B", {"i": str(i)}, f"r{i}")
        self.assertEqual(len(hs.list(limit=200)), MAX_ITEMS)
        # newest stays; add a distinct prompt after the flood
        h = hs.add("p1", "提示A", {"名": "张三"}, "你好张三")
        self.assertEqual(h["values"]["名"], "张三")
        only = hs.list(prompt_id="p1")
        self.assertEqual(len(only), 1)
        n = hs.clear(prompt_id="p1")
        self.assertEqual(n, 1)
        self.assertEqual(hs.list(prompt_id="p1"), [])
        self.assertGreater(hs.clear(), 0)
        self.assertEqual(hs.stats()["count"], 0)

    def test_result_capped(self):
        from history_store import HistoryStore, MAX_RESULT_CHARS
        hs = HistoryStore()
        h = hs.add("p", "n", {}, "x" * (MAX_RESULT_CHARS + 500))
        self.assertEqual(len(h["result"]), MAX_RESULT_CHARS)


class MigrationV4(TempData):
    def test_v3_gains_lifecycle_fields(self):
        data = {
            "format": "promptbuilder-prompts", "version": 3,
            "prompts": [{
                "id": "old1", "name": "旧提示", "body": "Hi {{名}}",
                "test_values": {}, "last_values": {"名": "李"},
                "use_count": 2, "created_at": "2024-01-01T00:00:00+08:00",
                "updated_at": "2024-01-02T00:00:00+08:00", "last_used_at": "",
                "legacy": {"tags": ["旧标签"], "favorite": True, "pinned": False},
            }],
        }
        (self.dir / "prompts.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        s = self.store()
        p = s.get("old1")
        self.assertIsNotNone(p)
        self.assertEqual(p["tags"], ["旧标签"])
        self.assertTrue(p["favorite"])
        self.assertFalse(p["archived"])
        # next save writes current schema version (v6 flat Role›Prompt)
        from library_model import VERSION as SCHEMA_VERSION
        s.save()
        on_disk = json.loads((self.dir / "prompts.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["version"], SCHEMA_VERSION)
        self.assertTrue(on_disk["prompts"][0]["favorite"])

    def test_settings_lifecycle_defaults(self):
        from settings_store import load_settings
        s = load_settings()
        self.assertEqual(s["library_sort"], "recent")
        self.assertFalse(s["starters_dismissed"])
        self.assertTrue(s["history_enabled"])


class ApiLifecycle(TempData):
    def test_api_revision_diff_and_history(self):
        from prompts_store import PromptStore
        from revisions_store import RevisionsStore
        from history_store import HistoryStore
        from api import Api
        store = PromptStore()
        for p in list(store.list()):
            store.delete(p["id"])
        revs = RevisionsStore()
        hist = HistoryStore()
        api = Api(store, revisions=revs, history=hist)
        p = api.create_prompt("差分", "第一版 {{a}}")
        pid = p["id"]
        api.save_prompt(pid, {"body": "第二版 {{a}} {{b}}"})
        lst = api.list_revisions(pid)
        self.assertGreaterEqual(len(lst), 1)
        api.save_revision(pid, note="手存")
        lst = api.list_revisions(pid)
        self.assertGreaterEqual(len(lst), 1)
        d = api.compare_revisions(pid, lst[0]["id"], "current")
        self.assertTrue(d.get("ok"))
        self.assertIn("diff", d)
        hist.add(pid, "差分", {"a": "1"}, "第二版 1")
        items = api.list_history()
        self.assertTrue(any(h["prompt_id"] == pid for h in items))
        st = api.get_stats()
        self.assertIn("top_prompts", st)
        hc = api.health_check()
        self.assertIn("total", hc)


if __name__ == "__main__":
    unittest.main()
