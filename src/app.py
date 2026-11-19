"""提示词 Builder 2.6 — Markdown prompts → forms, debug panel, "//" quick-pick popup.

CLI (used for verification of packaged builds):
  PromptBuilder.exe --selftest out.json           headless checks, no window
  PromptBuilder.exe --smoke out.json [--seconds N] [--accept-injected] [--show]
  PromptBuilder.exe --verify-ui out.json [--show]   load the real main window + popup, prove
                                                    both pages render, write JSON, exit
                                                    (or set PB_VERIFY_UI=out.json, e.g. when
                                                    launching through the Start-menu shortcut)
                                                   start the GUI hidden, log events, auto-quit
  PromptBuilder.exe --tray                        start in the tray (autostart)
  PromptBuilder.exe --from-task                   started by the admin-mode scheduled task
  PromptBuilder.exe --pb-register-task [--autostart] / --pb-unregister-task
                                                   elevated helper for the admin-mode option
Environment: PROMPTBUILDER_DATA_DIR overrides the data folder (used by tests so the
user's real %LOCALAPPDATA%\\PromptBuilder is never touched).
"""
from __future__ import annotations
import json, os, sys, threading, time, traceback

T_START = time.perf_counter()

if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api import APP_VERSION  # noqa: E402
import applog  # noqa: E402

log = applog.log
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def webview2_version() -> str:
    """Installed Evergreen WebView2 runtime version ('' if missing). Registry only — fast."""
    if sys.platform != "win32":
        return "n/a"
    import winreg
    guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"),
    ]
    for root, key in keys:
        try:
            with winreg.OpenKey(root, key) as k:
                v, _ = winreg.QueryValueEx(k, "pv")
                if v and v != "0.0.0.0":
                    return str(v)
        except OSError:
            continue
    # (registry only, same rule pywebview uses to pick Edge Chromium over legacy MSHTML)
    return ""


def ensure_webview2() -> bool:
    """Explain and offer the download instead of crashing when WebView2 is missing."""
    v = webview2_version()
    if v:
        log.info("WebView2 runtime %s", v)
        return True
    log.error("WebView2 runtime not found")
    import ctypes
    r = ctypes.windll.user32.MessageBoxW(
        None,
        "提示词 Builder 需要 Microsoft Edge WebView2 运行时，但本机没有检测到。\n\n"
        "Windows 10/11 通常自带；如果被精简或卸载了，请安装后再启动。\n\n"
        "现在打开微软官方下载页面吗？",
        "缺少 WebView2 运行时", 0x34)  # MB_YESNO | MB_ICONWARNING
    if r == 6:  # IDYES
        try:
            os.startfile(WEBVIEW2_URL)  # type: ignore[attr-defined]
        except Exception:
            pass
    return False


def system_dark() -> bool:
    """Windows app theme (Settings → Personalization → Colors)."""
    if sys.platform != "win32":
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return int(v) == 0
    except OSError:
        return False


def resolved_theme(theme: str) -> str:
    if theme in ("dark", "light"):
        return theme
    return "dark" if system_dark() else "light"


def fatal_dialog(msg: str) -> None:
    log.critical(msg)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, f"{msg}\n\n日志：{applog.path() or '（无法写入日志）'}", "提示词 Builder 出错了", 0x10)
        except Exception:
            pass

__version__ = APP_VERSION


def _arg(name: str, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
        return True
    return default


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


INSTANCE_MUTEX = "Local\\PromptBuilder.SingleInstance"
SHOW_EVENT = "Local\\PromptBuilder.ShowWindow"
QUIT_EVENT = "Local\\PromptBuilder.Quit"   # signalled by the installer before upgrading


def _signal(name: str) -> bool:
    if sys.platform != "win32":
        return False
    from winapi import F
    h = F.OpenEventW(0x0002, False, name)  # EVENT_MODIFY_STATE
    if not h:
        return False
    try:
        return bool(F.SetEvent(h))
    finally:
        F.CloseHandle(h)


def _instance_running(suffix: str = "") -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from winapi import F
    h = F.OpenMutexW(0x00100000, False, INSTANCE_MUTEX + suffix)  # SYNCHRONIZE
    if h:
        F.CloseHandle(h)
        return True
    return ctypes.get_last_error() == 5  # exists but belongs to an elevated instance


def admin_redirect() -> bool:
    """Admin mode: a normal launch hands over to the elevated scheduled task and exits.
    Returns True if this process should exit now."""
    if (sys.platform != "win32" or _arg("--from-task") or _arg("--smoke") or _arg("--verify-ui")
            or os.environ.get("PB_VERIFY_UI")):
        return False
    try:
        from settings_store import load_settings
        from winapi import self_elevated
        if not load_settings().get("admin_mode") or self_elevated():
            return False
        import elevation
        if _instance_running():
            _signal(SHOW_EVENT)
            log.info("admin mode: instance already running -> show")
            return True
        if not elevation.task_exists():
            log.warning("admin mode is on but the scheduled task is missing; starting normally")
            return False
        elevation.write_intent("tray" if _arg("--tray") else "show")
        if elevation.run_task():
            log.info("admin mode: handed over to the elevated task")
            return True
        log.warning("admin mode: could not run the task; starting normally")
    except Exception as e:
        log.warning("admin redirect failed: %s", e)
    return False


class AppController:
    def __init__(self, smoke: dict | None = None):
        self.smoke = smoke
        self._quitting = False
        self.start_hidden = bool(smoke and not smoke.get("show")) or bool(_arg("--tray"))
        if _arg("--from-task"):
            try:
                import elevation
                intent = elevation.take_intent()
                self.start_hidden = intent != "show"
            except Exception:
                self.start_hidden = True
        # single-instance first: a second launch must not load (or migrate) the library
        self.single_ok = self._single_instance()
        if not self.single_ok:
            return
        from prompts_store import PromptStore
        from revisions_store import RevisionsStore
        from history_store import HistoryStore
        from quickpick import PopupApi, QuickPick
        from settings_store import load_settings
        from api import Api
        self.smoke = smoke
        self.events: list = []
        self.store = PromptStore()
        self.revisions = RevisionsStore()
        self.history = HistoryStore()
        if self.store.recovered:
            log.warning("prompt library recovered from %s", self.store.recovered)
        self.window = None
        self.popup = None
        self.tray = None
        self._quitting = False
        from settings_store import save_settings
        self.quick = QuickPick(self.store, load_settings,
                               accept_injected=bool(smoke and smoke.get("accept_injected")),
                               log=self._log, notify=self.notify, show_main=self.show,
                               save_settings=self._save_settings_from_popup,
                               history=self.history)
        self.popup_api = PopupApi(self.quick)
        self.api = Api(self.store, on_hide=self.hide, on_quit=self.quit,
                       on_settings_changed=self._settings_changed,
                       get_quick_status=self.quick.status,
                       revisions=self.revisions, history=self.history)
        self.api.set_restart(self.restart)
        self._main_loaded = threading.Event()
        self.page_urls: dict = {}
        self.page_checks: dict = {}
        self._page_failed: dict = {}
        if not smoke and getattr(sys, "frozen", False):
            threading.Thread(target=self._refresh_autostart, daemon=True).start()

    @staticmethod
    def _refresh_autostart() -> None:
        """Upgrade an existing Run entry to the current exe path + --tray (start silently).
        In admin mode the scheduled task handles autostart and the Run entry is removed."""
        try:
            import winreg
            from autostart import RUN_VALUE, _exe_path, is_autostart_enabled, set_autostart
            from settings_store import load_settings
            from winapi import self_elevated
            if not is_autostart_enabled():
                return
            if load_settings().get("admin_mode") and self_elevated():
                import elevation
                if elevation.task_exists():
                    set_autostart(False)
                    elevation.register(True)
                    log.info("admin mode: autostart moved from the Run key to the task")
                    return
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                cur, _ = winreg.QueryValueEx(k, RUN_VALUE)
            if cur != _exe_path():
                set_autostart(True)
                log.info("autostart entry updated: %s", _exe_path())
        except Exception as e:
            log.warning("autostart refresh failed: %s", e)

    # ------------------------------------------------------------ logging
    def _log(self, ev: dict) -> None:
        ev = {"t": round(time.time(), 3), **ev}
        self.events.append(ev)
        if len(self.events) > 500:
            del self.events[:100]
        log.info("event %s", json.dumps(ev, ensure_ascii=False, default=str)[:600])
        if self.smoke:
            self._flush_smoke()

    def _flush_smoke(self, final: bool = False) -> None:
        try:
            _write_json(self.smoke["out"], {
                "version": APP_VERSION, "final": final,
                "main_loaded": self._main_loaded.is_set(),
                "page_urls": self.page_urls,
                "page_checks": self.page_checks,
                "pages_ok": all(self.page_checks.get(k, {}).get("ok") for k in ("main", "quick")),
                "cwd": os.getcwd(),
                "popup_loaded": self.quick.loaded.is_set(),
                "popup_hwnd": self.quick.hwnd,
                "quick": self.quick.status(),
                "prompts": len(self.store.list()),
                "latencies_ms": [round(x, 1) for x in self.quick.latencies],
                "recovered": self.store.recovered,
                "events": self.events,
            })
        except Exception:
            pass

    def _save_settings_from_popup(self, patch: dict) -> dict:
        from settings_store import save_settings
        r = save_settings(patch)
        self._push_main("window.__pbSettingsChanged && window.__pbSettingsChanged()")
        return r

    def _push_main(self, code: str) -> None:
        """Fire-and-forget JS into the main window (state changed from tray / popup)."""
        w = getattr(self, "window", None)
        if not w or not self._main_loaded.is_set():
            return

        def run():
            try:
                (getattr(w, "run_js", None) or w.evaluate_js)(code)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def notify(self, msg: str) -> None:
        """Small system notification (used when the popup cannot paste)."""
        self._log({"event": "notify", "msg": msg})
        try:
            if self.tray:
                self.tray.notify(msg)
        except Exception:
            pass

    # ------------------------------------------------------------ window ops
    def show(self):
        if not getattr(self, "window", None):
            return
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass

    def hide(self):
        try:
            if self.window:
                self.window.hide()
        except Exception:
            pass

    def _flush_ui(self) -> None:
        """Ask the main window to save a pending edit (debounced autosave) before exiting."""
        if not getattr(self, "window", None) or not self._main_loaded.is_set():
            return
        done = threading.Event()

        def run():
            try:
                self.window.evaluate_js("window.__pbFlush ? window.__pbFlush() : 0")
            except Exception:
                pass
            done.set()
        threading.Thread(target=run, daemon=True).start()
        done.wait(1.5)
        time.sleep(0.25)  # the save itself runs through the js_api on another thread

    def restart(self, elevated: bool) -> dict:
        """Restart into admin mode (via the task) or back to a normal instance."""
        import elevation
        if elevated:
            if not elevation.task_exists():
                return {"ok": False, "error": "计划任务不存在"}
            elevation.write_intent("show")
            self._flush_ui()
            self._release_instance()
            if not elevation.run_task():
                return {"ok": False, "error": "无法启动计划任务"}
        else:
            self._flush_ui()
            if not elevation.restart_unelevated():
                return {"ok": False, "error": "无法重新启动"}
        threading.Thread(target=lambda: (time.sleep(0.3), self.quit(flush=False)), daemon=True).start()
        return {"ok": True}

    def _release_instance(self) -> None:
        try:
            from winapi import F
            if getattr(self, "_mutex", None):
                F.ReleaseMutex(self._mutex)
                F.CloseHandle(self._mutex)
                self._mutex = None
        except Exception:
            pass

    def quit(self, flush: bool = True):
        if self._quitting:
            return
        if flush:
            self._flush_ui()
        self._quitting = True
        for fn in (lambda: self.quick.stop(), lambda: self.tray and self.tray.stop(),
                   lambda: self.window and self.window.destroy()):
            try:
                fn()
            except Exception:
                pass
        os._exit(0)

    def _settings_changed(self, settings: dict) -> dict:
        return self.quick.start()

    def _on_closing(self):
        if self._quitting:
            return True
        threading.Thread(target=self.hide, daemon=True).start()
        return False  # keep running in the tray

    # ------------------------------------------------------------ run
    def _single_instance(self) -> bool:
        """Per-session named mutex (owned by the main thread for the app's lifetime).

        The mutex/events carry a permissive security descriptor so a normal and an elevated
        instance (admin mode) still see each other. A second launch signals the running
        instance to show its window and exits. An instance started by the admin-mode task waits
        for the instance that is handing over to exit."""
        if sys.platform != "win32":
            return True
        import ctypes
        from winapi import F, shared_security_attributes
        self._sa = shared_security_attributes()
        psa = ctypes.byref(self._sa) if self._sa else None
        suffix = "_smoke" if self.smoke else ""
        self._mutex = F.CreateMutexW(psa, True, INSTANCE_MUTEX + suffix)
        err = ctypes.get_last_error()
        already = (not self._mutex and err == 5) or err == 183
        if already and self._mutex and _arg("--from-task"):
            r = F.WaitForSingleObject(self._mutex, 10000)
            already = r not in (0, 0x80)  # WAIT_OBJECT_0 / WAIT_ABANDONED → we own it now
        if already:
            if not self.smoke and not _signal(SHOW_EVENT + suffix):
                ctypes.windll.user32.MessageBoxW(
                    None, "提示词 Builder 已在运行。\n请从系统托盘打开，或在任意输入框输入 // 唤醒浮框。",
                    "提示词 Builder", 0x40)
            log.info("another instance is running; exiting")
            return False
        self._show_event = F.CreateEventW(psa, False, False, SHOW_EVENT + suffix)
        self._quit_event = F.CreateEventW(psa, False, False, QUIT_EVENT + suffix)

        def listen():
            from ctypes import wintypes
            handles = (wintypes.HANDLE * 2)(self._show_event, self._quit_event)
            while not self._quitting:
                r = F.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF)
                if self._quitting:
                    return
                if r == 0:
                    log.info("second launch -> show window")
                    self.show()
                elif r == 1:
                    log.info("quit requested (installer)")
                    self.quit()
                    return
                else:
                    time.sleep(1)
        if self._show_event and self._quit_event:
            threading.Thread(target=listen, name="pb-instance", daemon=True).start()
        return True

    def _after_start(self):
        self.quick.loaded.wait(10)
        if self.smoke and self.smoke.get("verify_ui"):
            # --verify-ui: load both real pages exactly as a normal launch does, prove they are
            # the real UI, write the result and exit. No keyboard hook is installed.
            end = time.time() + float(self.smoke.get("seconds") or 25)
            while time.time() < end and not all(k in self.page_checks for k in ("main", "quick")):
                time.sleep(0.25)
            time.sleep(0.3)
            self._flush_smoke(final=True)
            self.quit(flush=False)
            return
        self.quick.start()
        if self.smoke:
            secs = float(self.smoke.get("seconds") or 8)
            end = time.time() + secs
            while time.time() < end:
                time.sleep(0.5)
                self._flush_smoke()
            self._flush_smoke(final=True)
            self.quit()

    # ------------------------------------------------------------ page verification
    def _verify_page_async(self, page: str, win) -> None:
        if self._page_failed.get(page):
            return  # the error page itself just loaded
        threading.Thread(target=self._verify_page, args=(page, win), name=f"pb-verify-{page}",
                         daemon=True).start()

    def _verify_page(self, page: str, win) -> None:
        """pywebview fires `loaded` even for Chromium's error page, so prove the real UI is
        showing: the page sets window.__pbPage. Fail closed with an in-app error that names
        the file, and log it."""
        info: dict = {}
        for _ in range(3):
            try:
                raw = win.evaluate_js(
                    "JSON.stringify({page: window.__pbPage || '', href: location.href, title: document.title})")
                info = json.loads(raw) if isinstance(raw, str) else (raw or {})
                if info.get("page"):
                    break
            except Exception as e:  # noqa: BLE001
                info = {"error": repr(e)}
            time.sleep(0.4)
        try:
            cur = win.get_current_url()
        except Exception:
            cur = None
        expected = self.page_urls.get(page)
        ok = info.get("page") == page
        res = {"ok": ok, "expected": expected, "current_url": cur, **info}
        self.page_checks[page] = res
        if ok:
            log.info("page %s OK: %s", page, cur)
            self._log({"event": "page_ok", "page": page})
            return
        self._page_failed[page] = True
        log.error("page %s FAILED to load: expected %s, got %s (%s)", page, expected, cur, info)
        self._log({"event": "page_failed", **res})
        self._show_load_error(page, res)

    def _show_load_error(self, page: str, res: dict) -> None:
        import html as _h
        from paths import PAGES, logs_dir
        self._page_failed["main"] = True
        name = PAGES.get(page, page)
        rows = "".join(
            f"<tr><th>{_h.escape(k)}</th><td>{_h.escape(str(v or '—'))}</td></tr>"
            for k, v in (("界面文件", name), ("应加载", res.get("expected")),
                         ("实际地址", res.get("current_url") or res.get("href")),
                         ("日志", str(logs_dir() / "promptbuilder.log"))))
        doc = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>提示词 Builder</title>
<style>body{{font:14px/1.6 "Microsoft YaHei UI","Segoe UI",sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:48px}}
h1{{font-size:20px;margin:0 0 8px}}p{{color:#9da7b3;margin:0 0 20px}}table{{border-collapse:collapse;width:100%;max-width:860px}}
th{{text-align:left;color:#9da7b3;font-weight:400;padding:6px 16px 6px 0;white-space:nowrap;vertical-align:top}}
td{{font-family:Consolas,monospace;word-break:break-all;padding:6px 0}}</style>
<h1>界面加载失败（版本 {APP_VERSION}）</h1>
<p>提示词 Builder 没能打开它的界面文件，你的提示词数据没有受到影响。请重新安装最新版本；如果问题仍然存在，请把下面的信息和日志发给开发者。</p>
<table>{rows}</table></html>"""
        try:
            if self.window is not None:
                self.window.load_html(doc)
                if not self.smoke:
                    self.show()
        except Exception:
            log.exception("could not show the load-error page")
        try:
            if self.tray:
                self.tray.notify(f"界面文件加载失败：{name}，详情见主窗口。", "提示词 Builder")
        except Exception:
            pass

    def run(self):
        import webview
        from paths import web_dir
        from quickpick import POPUP_H, POPUP_TITLE, POPUP_W
        from settings_store import load_settings
        if not self.single_ok:
            return
        if not self.smoke and not ensure_webview2():
            return
        from paths import page_url
        # Absolute file:// URLs from the bundle (never cwd), with NO query string: WebView2
        # percent-encodes "?" in file URLs, which broke 2.6.0 (ERR_FILE_NOT_FOUND).
        self.page_urls = {"main": page_url("main"), "quick": page_url("quick")}
        log.info("web pages: %s", self.page_urls)
        theme_pref = load_settings().get("theme", "system")
        theme = resolved_theme(theme_pref)
        bg = "#0d1117" if theme == "dark" else "#f6f7f9"
        start_hidden = self.start_hidden

        self.window = webview.create_window(
            title="提示词 Builder", url=self.page_urls["main"], js_api=self.api,
            width=1280, height=800, min_size=(1000, 640), background_color=bg,
            text_select=True, hidden=start_hidden)
        self.api.set_window(self.window)

        def on_main_loaded():
            first = not self._main_loaded.is_set()
            self._main_loaded.set()
            if first:
                self._log({"event": "main_loaded", "startup_ms": round((time.perf_counter() - T_START) * 1000)})
            self._verify_page_async("main", self.window)
        self.window.events.loaded += on_main_loaded
        self.window.events.closing += self._on_closing

        self.popup = webview.create_window(
            title=POPUP_TITLE, url=self.page_urls["quick"], js_api=self.popup_api,
            width=POPUP_W, height=POPUP_H, frameless=True, easy_drag=False, on_top=True,
            resizable=False, hidden=True, shadow=True, focus=True,
            background_color="#151a22" if theme == "dark" else "#ffffff")
        self.quick.attach_window(self.popup)
        def on_popup_loaded():
            self._log({"event": "popup_loaded"})
            self._verify_page_async("quick", self.popup)
        self.popup.events.loaded += on_popup_loaded

        if start_hidden and not self.smoke:
            log.info("started in tray")
        if not self.smoke:
            from tray_icon import TrayApp
            from settings_store import save_settings
            from winapi import self_elevated

            def toggle(on: bool):
                save_settings({"quick_enabled": bool(on)})
                self.quick.start()
                self.tray.refresh()
                self._push_main("window.__pbSettingsChanged && window.__pbSettingsChanged()")
            self.tray = TrayApp(on_show=self.show, on_quit=self.quit,
                                is_enabled=lambda: bool(load_settings().get("quick_enabled", True)),
                                on_toggle=toggle, admin=self_elevated())
            self.tray.start()
        webview.start(func=self._after_start, debug=False, private_mode=False)


# ---------------------------------------------------------------- selftest
def selftest(out: str) -> int:
    res: dict = {"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
                 "executable": sys.executable, "checks": {}}
    checks = res["checks"]

    def check(name, fn):
        try:
            v = fn()
            checks[name] = {"ok": True, "value": v}
        except Exception as e:
            checks[name] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                            "trace": traceback.format_exc()[-800:]}

    def imports():
        mods = ["webview", "api", "prompts_store", "prompt_syntax", "settings_store", "paths",
                "quickpick", "keyhook", "caret", "winput", "winapi", "tray_icon",
                "autostart", "atomic_io", "applog", "textcheck", "elevation", "pystray", "PIL", "clr",
                "webview.platforms.edgechromium", "webview.platforms.winforms"]
        got = {}
        import importlib
        for m in mods:
            mod = importlib.import_module(m)
            got[m] = getattr(mod, "__file__", "builtin") or "frozen"
        return got
    check("imports", imports)

    def syntax():
        from prompt_syntax import analyze
        r = analyze("你好{{名字}}，语气{{语气:正式/轻松|正式}}{{坏", {"名字": "小王"})
        assert r["rendered"].startswith("你好小王，语气正式"), r["rendered"]
        assert any(i["code"] == "unclosed" for i in r["issues"])
        return {"vars": [v["name"] for v in r["variables"]], "issues": r["issue_counts"]}
    check("syntax", syntax)

    def webview2():
        v = webview2_version()
        assert v, "WebView2 runtime missing"
        return v
    check("webview2_runtime", webview2)

    def web_assets():
        from paths import web_dir, examples_path, icon_path
        need = ["index.html", "quick.html", "css/base.css", "css/app.css", "css/quick.css",
                "js/app.js", "js/quick.js", "js/md.js", "js/icons.js"]
        missing = [n for n in need if not (web_dir() / n).exists()]
        assert not missing, missing
        assert examples_path().exists() and icon_path().exists()
        return {"web": str(web_dir()), "files": len(need)}
    check("web_assets", web_assets)

    def slash_detector():
        from keyhook import SlashDetector
        d = SlashDetector()
        hits = [d.feed(0xBF, True, 0.0), d.feed(0xBF, False, 0.02), d.feed(0xBF, True, 0.2)]
        assert hits == [False, False, True], hits
        return "ok"
    check("double_slash_detector", slash_detector)

    def hook():
        from keyhook import KeyHook
        k = KeyHook(lambda *a: None, lambda fg: False)
        st = k.start()
        time.sleep(0.3)
        k.stop()
        assert st["mode"] == "hook", st
        return st
    check("keyboard_hook", hook)

    def text_verify():
        import textcheck as tc
        assert tc.classify("ab//") == "match" and tc.classify("、、") == "match"
        assert tc.classify("ab") == "mismatch" and tc.classify(None) == "unknown"
        assert tc.decide("unknown", 0x11, True) == "keep" and tc.decide("unknown", 0x04, True) == "delete"
        return "ok"
    check("text_verify", text_verify)

    def admin_task_xml():
        import elevation
        x = elevation.task_xml(True)
        assert "HighestAvailable" in x and "LogonTrigger" in x and elevation.FROM_TASK_ARG in x
        return {"command": elevation.app_command()[0], "task_exists": elevation.task_exists()}
    check("admin_task_xml", admin_task_xml)

    def dwm_cloak():
        from winapi import F
        assert F.DwmSetWindowAttribute and F.DwmGetWindowAttribute, "dwmapi missing"
        return "available"
    check("dwm_cloak", dwm_cloak)

    def uia():
        import caret
        return {"uia": caret.uia_available(), "err": caret._uia_state.get("err", "")}
    check("uia", uia)

    def caret_capture():
        import caret
        t = caret.capture("caret")
        r = caret.popup_rect(t, 460, 440)
        return {"method": t.method, "tried": t.tried, "mouse": t.mouse, "rect": r}
    check("caret_capture", caret_capture)

    def clipboard():
        import subprocess
        import winapi as W
        import winput

        def locked() -> bool:
            # On the Win10/11 lock screen the input desktop is still "Default" (LockApp
            # runs there), but the clipboard is not usable. Detect it explicitly.
            try:
                fg = W.F.GetForegroundWindow()
                pid, _ = W.window_pid_tid(fg)
                if (W.process_exe_name(pid) or "").lower() == "lockapp.exe":
                    return True
            except Exception:
                pass
            try:
                r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq LogonUI.exe", "/NH"],
                                   capture_output=True, text=True, timeout=5,
                                   creationflags=0x08000000)
                return "logonui.exe" in (r.stdout or "").lower()
            except Exception:
                return False
        if locked():
            return {"skipped": "workstation locked (the clipboard is unavailable on the lock screen)"}
        before = winput.get_text()
        snap = winput.snapshot()
        winput.set_text("pb-selftest-✓", transient=True)
        got = winput.get_text()
        winput.restore(snap)
        after = winput.get_text()
        assert got == "pb-selftest-✓", got
        assert after == before, (before[:40], after[:40])
        return {"formats_saved": len(snap or []), "restored_equal": after == before}
    check("clipboard_roundtrip", clipboard)

    def web_pages():
        # Every URL a window can load: built exactly as AppController.run builds it.
        from paths import PAGES, all_web_refs, page_url
        urls = {k: page_url(k) for k in PAGES}
        for k, u in urls.items():
            assert u.startswith("file:///") and "?" not in u and "#" not in u, u
        missing = {k: v for k, v in all_web_refs().items() if v}
        assert not missing, missing
        return {"urls": urls, "assets_checked": True, "cwd": os.getcwd()}
    check("web_pages", web_pages)

    mig_dir = os.environ.get("PB_SELFTEST_MIGRATE_DIR")
    if mig_dir:
        def migration():
            os.environ["PROMPTBUILDER_DATA_DIR"] = mig_dir
            from prompts_store import PromptStore
            s = PromptStore()
            return {"migration": s.migration, "prompts": [p["name"] for p in s.list()]}
        check("migration", migration)

    res["ok"] = all(c["ok"] for c in checks.values())
    _write_json(out, res)
    return 0 if res["ok"] else 1


def main():
    applog.setup(APP_VERSION)
    try:
        _main()
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001
        log.exception("fatal")
        fatal_dialog(f"启动失败：{type(e).__name__}: {e}")
        sys.exit(1)


def _main():
    if _arg("--pb-register-task") or _arg("--pb-unregister-task"):
        import elevation
        code = elevation.helper_main(sys.argv)
        log.info("elevated helper %s -> %s", sys.argv[1:], code)
        sys.exit(code)
    st = _arg("--selftest")
    if st:
        sys.exit(selftest(st if isinstance(st, str) else "selftest.json"))
    smoke_out = _arg("--smoke")
    smoke = None
    verify_out = _arg("--verify-ui") or os.environ.get("PB_VERIFY_UI")
    if verify_out:
        smoke = {"out": verify_out if isinstance(verify_out, str) else "verify-ui.json",
                 "seconds": _arg("--seconds", 25), "accept_injected": False,
                 "show": bool(_arg("--show")), "verify_ui": True}
    elif smoke_out:
        smoke = {"out": smoke_out if isinstance(smoke_out, str) else "smoke.json",
                 "seconds": _arg("--seconds", 8), "accept_injected": bool(_arg("--accept-injected")),
                 "show": bool(_arg("--show"))}
    if admin_redirect():
        return
    AppController(smoke).run()


if __name__ == "__main__":
    main()
