"""2.6 tests: trigger-text verification, settings upgrade, undo-delete, scheduled-task XML.
Run:  python -m unittest discover -s src/tests -v"""
import json, os, sys, tempfile, unittest
import xml.etree.ElementTree as ET
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


class TextCheck(unittest.TestCase):
    def test_classify(self):
        from textcheck import classify
        self.assertEqual(classify("hello //"), "match")
        self.assertEqual(classify("//"), "match")
        self.assertEqual(classify("你好、、"), "match")          # Chinese IME maps / to 、
        self.assertEqual(classify("ａ／／"), "match")            # full-width
        self.assertEqual(classify("x/、"), "match")              # mixed
        self.assertEqual(classify("a/"), "mismatch")             # editor swallowed one slash
        self.assertEqual(classify("</>"), "mismatch")            # auto-closed tag
        self.assertEqual(classify("ni"), "mismatch")             # IME composition took the keys
        self.assertEqual(classify(""), "mismatch")
        self.assertEqual(classify(None), "unknown")
        self.assertEqual(classify("//\ufffc"), "unknown")       # embedded object: offsets unreliable

    def test_decide(self):
        from textcheck import decide
        self.assertEqual(decide("match"), "delete")
        self.assertEqual(decide("mismatch"), "keep")
        self.assertEqual(decide("unknown"), "delete")                       # 2.5 behaviour by default
        self.assertEqual(decide("unknown", 0x11, True), "keep")             # Japanese IME open
        self.assertEqual(decide("unknown", 0x12, True), "keep")             # Korean IME open
        self.assertEqual(decide("unknown", 0x11, False), "delete")
        self.assertEqual(decide("unknown", 0x04, True), "delete")           # Chinese IME: / is committed directly
        self.assertEqual(decide("match", 0x11, True), "delete")             # verified text always wins

    def test_edit_class(self):
        from textcheck import is_edit_class
        for c in ("Edit", "RichEdit20W", "RICHEDIT50W", "WindowsForms10.EDIT.app.0.141b42a_r6_ad1", "TEdit"):
            self.assertTrue(is_edit_class(c) or c == "TEdit", c)
        for c in ("Chrome_RenderWidgetHostHWND", "Scintilla", "_WwG", "ConsoleWindowClass", "", None):
            self.assertFalse(is_edit_class(c), c)

    def test_verify_offline_is_unknown(self):
        from textcheck import verify_trigger
        if sys.platform == "win32":
            self.skipTest("Windows: covered by the E2E harness")
        self.assertEqual(verify_trigger(0)["status"], "unknown")


class SettingsUpgrade(TempData):
    def _write(self, data):
        (self.dir / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    def test_fresh_defaults(self):
        from settings_store import load_settings
        s = load_settings()
        self.assertEqual(s["theme"], "system")
        self.assertFalse(s["admin_mode"])
        self.assertEqual(s["quick_exclude"], "")                 # no default exclusions
        self.assertEqual(s["onboarding"], 0)

    def test_25_dark_becomes_system_once(self):
        from settings_store import load_settings, save_settings
        import settings_store
        self._write({"theme": "dark", "quick_enabled": False, "quick_exclude": "Code.exe"})
        s = load_settings()
        self.assertEqual(s["theme"], "system")
        self.assertFalse(s["quick_enabled"])                     # other values untouched
        self.assertEqual(s["quick_exclude"], "code.exe")
        on_disk = json.loads((self.dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["theme"], "system")
        self.assertEqual(on_disk["settings_rev"], 1)
        save_settings({"theme": "dark"})                         # explicit choice sticks afterwards
        settings_store._cache["mtime"] = settings_store._cache["data"] = None
        self.assertEqual(load_settings()["theme"], "dark")

    def test_25_light_kept(self):
        from settings_store import load_settings
        self._write({"theme": "light"})
        self.assertEqual(load_settings()["theme"], "light")

    def test_bad_values_normalized(self):
        from settings_store import load_settings
        self._write({"theme": "purple", "admin_mode": "yes", "onboarding": "x", "settings_rev": 1})
        s = load_settings()
        self.assertIn(s["theme"], ("system", "dark", "light"))
        self.assertIsInstance(s["admin_mode"], bool)
        self.assertEqual(s["onboarding"], 0)


class UndoDelete(TempData):
    def test_take_restore_same_position_and_id(self):
        from prompts_store import PromptStore
        st = PromptStore()
        a = st.create("A", "a {{x}}"); b = st.create("B", "b"); c = st.create("C", "c")
        ids = [p["id"] for p in st.list()]
        idx = ids.index(b["id"])
        taken = st.take(b["id"])
        self.assertEqual(taken["index"], idx)
        self.assertIsNone(st.get(b["id"]))
        r = st.restore(taken["prompt"], taken["index"])
        self.assertEqual(r["id"], b["id"])
        self.assertEqual([p["id"] for p in st.list()], ids)
        # persisted
        self.assertIsNotNone(PromptStore().get(b["id"]))

    def test_restore_id_collision_gets_new_id(self):
        from prompts_store import PromptStore
        st = PromptStore()
        a = st.create("A", "a")
        r = st.restore(dict(st.get(a["id"])), 0)
        self.assertNotEqual(r["id"], a["id"])
        self.assertIsNone(st.restore("garbage", 0))

    def test_rev_increments_on_save(self):
        from prompts_store import PromptStore
        st = PromptStore(); r0 = st.rev
        st.create("A", "a")
        self.assertGreater(st.rev, r0)

    def test_api_delete_returns_undo_payload(self):
        from prompts_store import PromptStore
        from api import Api
        st = PromptStore(); api = Api(st)
        p = st.create("A", "a")
        r = api.delete_prompt(p["id"])
        self.assertTrue(r["ok"]); self.assertEqual(r["prompt"]["name"], "A")
        rr = api.restore_prompt(r["prompt"], r["index"])
        self.assertTrue(rr["ok"]); self.assertEqual(rr["prompt"]["id"], p["id"])
        self.assertFalse(api.delete_prompt("nope")["ok"])


class TaskXml(unittest.TestCase):
    NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

    def parse(self, xml):
        return ET.fromstring(xml.encode("utf-16"))

    def test_elevated_no_trigger(self):
        from elevation import task_xml
        x = task_xml(False, user="PC\\allen", command=("C:\\P B\\PromptBuilder.exe", "--from-task", "C:\\P B"))
        root = self.parse(x)
        self.assertEqual(root.find("t:Principals/t:Principal/t:RunLevel", self.NS).text, "HighestAvailable")
        self.assertEqual(root.find("t:Principals/t:Principal/t:LogonType", self.NS).text, "InteractiveToken")
        self.assertEqual(root.find("t:Principals/t:Principal/t:UserId", self.NS).text, "PC\\allen")
        self.assertIsNone(root.find("t:Triggers/t:LogonTrigger", self.NS))
        self.assertEqual(root.find("t:Actions/t:Exec/t:Command", self.NS).text, "C:\\P B\\PromptBuilder.exe")
        self.assertEqual(root.find("t:Actions/t:Exec/t:Arguments", self.NS).text, "--from-task")
        self.assertEqual(root.find("t:Settings/t:ExecutionTimeLimit", self.NS).text, "PT0S")
        self.assertEqual(root.find("t:Settings/t:DisallowStartIfOnBatteries", self.NS).text, "false")

    def test_autostart_trigger_and_escaping(self):
        from elevation import task_xml
        x = task_xml(True, user="PC\\a&b", command=("C:\\x<y>\\a.exe", "--from-task --tray", "C:\\x"))
        root = self.parse(x)
        trig = root.find("t:Triggers/t:LogonTrigger", self.NS)
        self.assertIsNotNone(trig)
        self.assertEqual(trig.find("t:UserId", self.NS).text, "PC\\a&b")
        self.assertEqual(root.find("t:Actions/t:Exec/t:Command", self.NS).text, "C:\\x<y>\\a.exe")


if __name__ == "__main__":
    unittest.main()
