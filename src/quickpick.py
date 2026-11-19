""""//" quick-pick popup controller.

Flow
  "//" typed (both slashes reach the app) ─▶ capture target (foreground hwnd, focused child,
  caret) ─▶ move the pre-rendered popup next to the caret ─▶ un-cloak + take focus ─▶ pick
  ├─ commit: hide → re-focus the original window/control → verify it is really in front →
  │          verify the two chars in front of the caret are the "//" (textcheck) →
  │          Backspace × 2 (only if verified / safe) → paste via clipboard → restore clipboard
  └─ cancel (Esc / click outside): hide → re-focus the original window. Nothing is sent.

Speed (2.6) — the popup is never created, shown or re-rendered on the hot path:
  * at startup the popup window is shown once, *cloaked* (DWM_CLOAK: invisible, still
    composed and rendered by WebView2), parked off-screen next to the monitor it was last used
    on (same DPI, so moving it back needs no re-layout) and marked WS_EX_NOACTIVATE so Windows
    can never hand it keyboard focus while parked;
  * the list is pushed into it ahead of time whenever the library changes (store.rev);
  * opening = SetWindowPos + un-cloak + SetForegroundWindow (≈ 1 frame);
  * if cloaking is not available the 2.5 show/hide path is used ("classic").
Safety: keystrokes (Backspace / Ctrl+V) are only sent after confirming that the original window
is the foreground window again; otherwise the text is left on the clipboard (with a notice).
"""
from __future__ import annotations
import ctypes, json, os, threading, time
from typing import Callable

import caret as caretmod
import textcheck
import winput
from keyhook import TRIGGER_TEXT, KeyHook
from settings_store import exclude_set, normalize_exclude
from winapi import (F, GWL_EXSTYLE, HWND_TOPMOST, IS_WIN, MONITOR_DEFAULTTONEAREST, MONITORINFO,
                    POINT, RECT, SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE,
                    SWP_NOZORDER, WS_EX_APPWINDOW, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
                    gui_thread_busy, hval, ime_state, is_cloaked, is_fullscreen, is_shell_window,
                    per_monitor_dpi, process_elevated, process_exe_name, root_window,
                    self_elevated, set_cloak, window_pid_tid, window_rect)

POPUP_TITLE = "PromptBuilder QuickPick"
POPUP_W, POPUP_H = 460, 440


def _monitor_dpi(mon) -> int:
    if not F.GetDpiForMonitor or not mon:
        return 96
    dx, dy = ctypes.c_uint(96), ctypes.c_uint(96)
    return dx.value if F.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 else 96


def park_rect(w: int, h: int, near: tuple[int, int]) -> tuple[int, int, int, int]:
    """An off-screen rectangle whose nearest monitor has the same DPI as the monitor at `near`
    (physical px). Parking there keeps WebView2 from re-laying out when the popup comes back."""
    with per_monitor_dpi():
        vx, vy = F.GetSystemMetrics(76), F.GetSystemMetrics(77)
        vw, vh = F.GetSystemMetrics(78), F.GetSystemMetrics(79)
        mon = F.MonitorFromPoint(POINT(*near), MONITOR_DEFAULTTONEAREST)
        dpi = _monitor_dpi(mon)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        F.GetMonitorInfoW(mon, ctypes.byref(mi))
        m = mi.rcMonitor
        gap = 64
        cands = [(m.left, vy + vh + gap), (m.left, vy - h - gap),
                 (vx - w - gap, m.top), (vx + vw + gap, m.top)]
        for x, y in cands:
            r = RECT(x, y, x + w, y + h)
            if F.MonitorFromRect(ctypes.byref(r), 0):        # MONITOR_DEFAULTTONULL: on screen
                continue
            if _monitor_dpi(F.MonitorFromRect(ctypes.byref(r), MONITOR_DEFAULTTONEAREST)) == dpi:
                return (x, y, w, h)
        x, y = cands[0]
        return (x, y, w, h)


class QuickPick:
    def __init__(self, store, get_settings: Callable[[], dict], accept_injected: bool = False,
                 log: Callable[[dict], None] | None = None,
                 notify: Callable[[str], None] | None = None,
                 show_main: Callable[[], None] | None = None,
                 save_settings: Callable[[dict], dict] | None = None,
                 history=None):
        self.store = store
        self.history = history
        self.get_settings = get_settings
        self.accept_injected = accept_injected
        self.log = log or (lambda e: None)
        self.notify = notify or (lambda m: None)
        self.show_main = show_main or (lambda: None)
        self.save_settings = save_settings
        self.window = None
        self.hwnd = 0
        self.loaded = threading.Event()
        self.hook: KeyHook | None = None
        self.visible = False
        self.target: caretmod.Target | None = None
        self.target_exe = ""
        self._session = 0
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._self_elevated = self_elevated()
        self.last_error = ""
        self._exclude: frozenset = frozenset()
        self._skip_fullscreen = True
        self._pushed_sig = None
        self._prep_lock = threading.Lock()
        self._prep_timer: threading.Timer | None = None
        self.latencies: list[float] = []
        self.skipped: dict[str, int] = {}
        self.mode = os.environ.get("PB_POPUP_MODE", "fast")   # fast | classic (A/B + fallback)
        self.parked = False
        self._last_rect: tuple | None = None
        self._park: tuple | None = None
        self.commits: list[dict] = []
        if hasattr(store, "listeners"):
            store.listeners.append(self.schedule_prepare)

    # -------------------------------------------------------------- setup
    def attach_window(self, window) -> None:
        self.window = window
        window.events.loaded += self._on_loaded

    def _on_loaded(self) -> None:
        self._find_hwnd()
        threading.Thread(target=self._warm, name="pb-qp-warm", daemon=True).start()

    def _warm(self) -> None:
        self.loaded.set()
        self.prepare(force=True)
        if self.mode == "fast":
            with self._lock:
                if not self._park_init():
                    self.mode = "classic"
        self.log({"event": "popup_mode", "mode": self.mode, "parked": self.parked})
        caretmod.prewarm()
        threading.Thread(target=self._park_watchdog, name="pb-qp-park", daemon=True).start()

    def _find_hwnd(self) -> int:
        if IS_WIN and not self.hwnd:
            self.hwnd = hval(F.FindWindowW(None, POPUP_TITLE))
            if self.hwnd:
                self._style_window()
        return self.hwnd

    def _ex_style(self, add: int = 0, remove: int = 0) -> None:
        h = self.hwnd
        ex = F.GetWindowLongPtrW(h, GWL_EXSTYLE)
        new = (ex | add) & ~remove
        if new != ex:
            F.SetWindowLongPtrW(h, GWL_EXSTYLE, new)

    def _style_window(self) -> None:
        """No taskbar button / Alt+Tab entry; rounded corners on Windows 11."""
        h = self.hwnd
        self._ex_style(add=WS_EX_TOOLWINDOW, remove=WS_EX_APPWINDOW)
        F.SetWindowPos(h, None, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        if F.DwmSetWindowAttribute:
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            F.DwmSetWindowAttribute(h, 33, ctypes.byref(pref), 4)

    def _js(self, code: str, wait: bool = False):
        """Run JS in the popup (run_js skips pywebview's eval wrapper)."""
        if not self.window:
            return None
        fn = None if wait else getattr(self.window, "run_js", None)
        try:
            return (fn or self.window.evaluate_js)(code)
        except Exception as e:
            self.log({"event": "js_error", "error": str(e)[:200]})
            return None

    # -------------------------------------------------------------- parking (fast mode)
    def _move(self, rect, flags: int = SWP_NOACTIVATE) -> None:
        x, y, w, h = rect[:4]
        with per_monitor_dpi():
            F.SetWindowPos(self.hwnd, ctypes.c_void_p(HWND_TOPMOST), x, y, w, h, flags)

    def _park_target(self) -> tuple:
        if self._last_rect:
            near = (self._last_rect[0] + 10, self._last_rect[1] + 10)
            w, h = self._last_rect[2], self._last_rect[3]
        else:
            with per_monitor_dpi():
                pt = POINT()
                (F.GetPhysicalCursorPos or F.GetCursorPos)(ctypes.byref(pt))
            near = (pt.x, pt.y)
            mon = F.MonitorFromPoint(POINT(*near), MONITOR_DEFAULTTONEAREST)
            scale = _monitor_dpi(mon) / 96.0
            w, h = int(POPUP_W * scale), int(POPUP_H * scale)
        return park_rect(w, h, near)

    def _park_init(self) -> bool:
        """Show the popup once: cloaked, off-screen, non-activatable. Returns False if DWM
        cloaking is unavailable (→ classic mode)."""
        if not IS_WIN or not self._find_hwnd():
            return False
        h = self.hwnd
        if not set_cloak(h, True):
            return False
        self._ex_style(add=WS_EX_NOACTIVATE)
        self._park = self._park_target()
        self._move(self._park)
        F.ShowWindow(h, 4)  # SW_SHOWNOACTIVATE: WinForms sees WM_SHOWWINDOW → WebView2 visible
        self._move(self._park)
        ok = bool(F.IsWindowVisible(h)) and is_cloaked(h)
        if not ok:
            set_cloak(h, False)
            F.ShowWindow(h, 0)
            self._ex_style(remove=WS_EX_NOACTIVATE)
            return False
        self.parked = True
        return True

    def _park_now(self) -> None:
        """Hide (fast mode): cloak + move off-screen + non-activatable."""
        h = self.hwnd
        set_cloak(h, True)
        self._ex_style(add=WS_EX_NOACTIVATE)
        self._park = self._park_target()
        self._move(self._park, SWP_NOACTIVATE)

    def _unpark_fallback(self, why: str) -> None:
        """Something is off (e.g. the cloaked popup still owns the keyboard focus): really hide
        it so no keystroke can ever go into an invisible window; re-park later."""
        try:
            F.ShowWindow(self.hwnd, 0)  # SW_HIDE → Windows activates the next window
        except Exception:
            pass
        self.parked = False
        self.log({"event": "unpark", "reason": why})

    def _park_watchdog(self) -> None:
        """Every second while idle: re-park after display changes, re-init after a fallback,
        and make sure a parked popup never holds the foreground."""
        while True:
            time.sleep(1.0)
            if self.mode != "fast" or self.visible:
                continue
            with self._lock:
                if self.visible:
                    continue
                try:
                    if not self.parked:
                        if self._park_init():
                            self.log({"event": "repark"})
                        continue
                    if hval(F.GetForegroundWindow()) == self.hwnd:
                        self._unpark_fallback("parked_foreground")
                        continue
                    r = window_rect(self.hwnd)
                    if r and self._park and (r[0], r[1]) != (self._park[0], self._park[1]):
                        self._park_now()   # Windows moved it (monitor layout changed)
                    if not is_cloaked(self.hwnd):
                        set_cloak(self.hwnd, True)
                except Exception as e:
                    self.log({"event": "park_watchdog_error", "error": str(e)[:200]})

    # -------------------------------------------------------------- pre-render
    def _sig(self) -> tuple:
        s = self.get_settings()
        return (getattr(self.store, "rev", None), s.get("theme", "system"), bool(s.get("quick_preview", True)))

    def _payload(self) -> dict:
        s = self.get_settings()
        return {
            "theme": s.get("theme", "system"),
            "preview": bool(s.get("quick_preview", True)),
            "hotkey": TRIGGER_TEXT,
            "items": self.store.quick_items(),
        }

    def prepare(self, force: bool = False) -> bool:
        """Push the (sorted) list into the hidden popup if anything changed. True if pushed."""
        if not self.loaded.is_set():
            return False
        with self._prep_lock:
            sig = self._sig()
            if not force and sig == self._pushed_sig:
                return False
            payload = self._payload()
            self._js(f"window.__qpPrepare && window.__qpPrepare({json.dumps(payload, ensure_ascii=False)})", wait=True)
            self._pushed_sig = sig
            return True

    def schedule_prepare(self) -> None:
        """Library changed (debounced): refresh the hidden popup in the background."""
        if self.visible:
            return
        if self._prep_timer:
            self._prep_timer.cancel()
        self._prep_timer = threading.Timer(0.3, lambda: (not self.visible) and self.prepare())
        self._prep_timer.daemon = True
        self._prep_timer.start()

    # -------------------------------------------------------------- lifecycle
    def start(self) -> dict:
        s = self.get_settings()
        self.stop()
        self._exclude = exclude_set(s)
        self._skip_fullscreen = bool(s.get("quick_skip_fullscreen", True))
        if s.get("quick_enabled", True):
            self.hook = KeyHook(self._on_trigger, self._should_intercept,
                                accept_injected=self.accept_injected)
            self.hook.start()
            self.log({"event": "hook_start", **self.status()})
        self.schedule_prepare()
        return self.status()

    def stop(self) -> None:
        if self.hook:
            self.hook.stop()
            self.hook = None

    def status(self) -> dict:
        s = self.get_settings()
        st = self.hook.status() if self.hook else {"mode": "off", "error": "", "hotkey": ""}
        lat = sorted(self.latencies[-50:])
        st.update({
            "enabled": bool(s.get("quick_enabled", True)),
            "hotkey": TRIGGER_TEXT,
            "follow": s.get("quick_follow", "caret"),
            "elevated": self._self_elevated,
            "uia": caretmod.uia_available() if IS_WIN else False,
            "setting_error": self.last_error,
            "latency_ms": round(lat[len(lat) // 2]) if lat else None,
            "skipped": dict(self.skipped),
            "popup_mode": self.mode,
            "parked": self.parked,
        })
        return st

    # -------------------------------------------------------------- hook side
    def _skip(self, why: str) -> bool:
        self.skipped[why] = self.skipped.get(why, 0) + 1
        return False

    def _should_intercept(self, fg: int) -> bool:
        """Called inside the LL hook — must be fast (all checks are cached / O(1) Win32 calls).

        Keys are never swallowed; False only means "do not open the popup"."""
        if not fg:
            return self._skip("no_window")
        pid, tid = window_pid_tid(fg)
        if pid == self._pid:
            return False  # our own windows (editor, popup search box): "//" is just text
        if not self._self_elevated and process_elevated(pid):
            return self._skip("elevated")   # cannot type into an elevated window (UIPI)
        if self._exclude and process_exe_name(pid) in self._exclude:
            return self._skip("excluded")
        if is_shell_window(fg):
            return self._skip("desktop")
        if gui_thread_busy(tid):
            return self._skip("menu")       # menu open / window being dragged
        if self._skip_fullscreen and is_fullscreen(fg):
            return self._skip("fullscreen")  # games, slideshows, video players
        return True

    def _on_trigger(self, source: str, t_hook: float | None = None) -> None:
        with self._lock:
            if self.visible:
                return
            self._open_locked(source, t_hook or time.perf_counter())

    # -------------------------------------------------------------- open
    def _open_locked(self, source: str, t_hook: float) -> None:
        if not self.loaded.wait(5) or not self._find_hwnd():
            self.log({"event": "open_failed", "reason": "popup not ready"})
            return
        s = self.get_settings()
        # the second "/" is still on its way to the target app: let it land before we take focus
        wait = 0.012 - (time.perf_counter() - t_hook)
        if wait > 0:
            time.sleep(wait)
        t0 = time.perf_counter()
        target = caretmod.capture(s.get("quick_follow", "caret"))
        t_caret = time.perf_counter()
        rect = caretmod.popup_rect(target, POPUP_W, POPUP_H)
        pushed = self.prepare()  # normally a no-op: the list was pre-rendered while hidden
        t_prep = time.perf_counter()
        self.target = target
        self.target_exe = process_exe_name(target.pid)
        self.visible = True
        self._session += 1
        session = self._session
        self._last_rect = rect
        fast = self.mode == "fast" and self.parked
        if fast:
            self._move(rect)
            r = window_rect(self.hwnd)
            if r and (r[0], r[1], r[2] - r[0], r[3] - r[1]) != tuple(rect[:4]):
                self._move(rect)   # a DPI change made WinForms adjust the size: place again
            self._ex_style(remove=WS_EX_NOACTIVATE)
            set_cloak(self.hwnd, False)
        else:
            caretmod.place_window(self.hwnd, rect)
            self.window.show()
            caretmod.place_window(self.hwnd, rect)  # WinForms may move it on Show
        t_shown = time.perf_counter()
        focused = winput.force_foreground(self.hwnd)
        t_end = time.perf_counter()
        ctx = {"exe": self.target_exe}
        self._js(f"window.__qpFocus && window.__qpFocus({json.dumps(ctx)})")
        latency = (t_end - t_hook) * 1000
        self.latencies.append(latency)
        del self.latencies[:-200]
        self.log({"event": "open", "source": source, "fast": fast, "method": target.method,
                  "tried": target.tried, "caret": target.caret, "mouse": target.mouse, "rect": rect,
                  "focused": focused, "latency_ms": round(latency, 1),
                  "caret_ms": round((t_caret - t0) * 1000, 1),
                  "prepare_ms": round((t_prep - t_caret) * 1000, 1), "pushed": pushed,
                  "show_ms": round((t_shown - t_prep) * 1000, 1),
                  "focus_ms": round((t_end - t_shown) * 1000, 1)})
        threading.Thread(target=self._watch, args=(session,), daemon=True).start()

    def _watch(self, session: int) -> None:
        """Cancel when the user clicks outside (popup loses foreground)."""
        seen = False
        start = time.time()
        while True:
            time.sleep(0.04)
            with self._lock:
                if not self.visible or session != self._session:
                    return
                fg = hval(F.GetForegroundWindow())
                if fg == self.hwnd:
                    seen = True
                    continue
                if seen:
                    self._cancel_locked("outside", new_fg=fg)
                    return
                if time.time() - start > 0.6:
                    if winput.force_foreground(self.hwnd):
                        self._js("window.__qpFocus && window.__qpFocus()")
                        seen = True
                        continue
                    # could not get keyboard focus → never leave a dead popup behind
                    self._cancel_locked("nofocus")
                    return

    # -------------------------------------------------------------- close
    def _hide(self) -> None:
        self.visible = False
        self._session += 1
        try:
            if self.mode == "fast" and self.parked:
                self._park_now()
            else:
                self.window.hide()
        except Exception as e:
            self.log({"event": "hide_error", "error": str(e)[:200]})
        # reset the hidden popup for the next open (list, search box, scroll position)
        threading.Thread(target=self._after_hide, name="pb-qp-reset", daemon=True).start()

    def _after_hide(self) -> None:
        time.sleep(0.12)
        if not self.visible:
            if not self.prepare():
                self._js("window.__qpReset && window.__qpReset()")

    def _ensure_not_focused(self) -> None:
        """After re-focusing the target the (cloaked) popup must not keep the keyboard."""
        if self.mode == "fast" and self.parked and hval(F.GetForegroundWindow()) == self.hwnd:
            self._unpark_fallback("kept_focus")

    def _refocus(self, t: caretmod.Target | None) -> bool:
        if not t or not t.hwnd or not F.IsWindow(t.hwnd):
            return False
        return winput.force_foreground(t.hwnd, t.focus or None)

    def target_in_front(self, t: caretmod.Target | None) -> bool:
        """The original window (or one of its own children/popups) is the foreground window."""
        if not IS_WIN or not t or not t.hwnd:
            return False
        fg = hval(F.GetForegroundWindow())
        if not fg or fg == self.hwnd:
            return False
        if fg == t.hwnd or root_window(fg) == root_window(t.hwnd):
            return True
        pid, _ = window_pid_tid(fg)
        return bool(t.pid and pid == t.pid)

    def cancel(self, reason: str = "esc") -> None:
        with self._lock:
            self._cancel_locked(reason)

    def _cancel_locked(self, reason: str, new_fg: int = 0) -> None:
        if not self.visible:
            return
        t = self.target
        self._hide()
        other = new_fg if (new_fg and t and new_fg != t.hwnd and new_fg != self.hwnd) else 0
        if other:
            # the user clicked into another window: leave focus there
            self.log({"event": "cancel", "reason": reason, "refocus": False})
            return
        ok = self._refocus(t)  # the "//" stays as typed; nothing is sent
        self._ensure_not_focused()
        self.log({"event": "cancel", "reason": reason, "refocus": ok})

    def commit(self, prompt_id: str, values: dict) -> dict:
        with self._lock:
            if not self.visible:
                return {"ok": False, "error": "浮框已关闭"}
            p = self.store.get(prompt_id)
            if not p:
                return {"ok": False, "error": "提示词不存在"}
            from prompt_syntax import analyze
            res = analyze(p["body"], values or {})
            text = res["rendered"]
            t = self.target
            self._hide()
        self.store.touch_used(prompt_id, values or {})
        try:
            if self.history and self.get_settings().get("history_enabled", True):
                self.history.add(prompt_id, p.get("name") or "", values or {}, text or "")
        except Exception:
            pass

        def work():
            ok = self._refocus(t)
            self._ensure_not_focused()
            time.sleep(0.05)
            if not self.target_in_front(t):
                # focus could not be returned: do not send keys into some other window;
                # keep the text on the clipboard so the user can paste it manually
                winput.set_text(text)
                self.notify("未能回到原输入框，内容已复制到剪贴板，按 Ctrl+V 粘贴")
                self._record({"event": "commit", "prompt": p["name"], "refocus": ok, "ok": False,
                              "fallback": "clipboard", "chars": len(text)})
                return
            v = textcheck.verify_trigger(t.focus or 0)
            ime = ime_state(t.focus or t.hwnd, t.tid)
            action = textcheck.decide(v["status"], ime["lang"], ime["open"])
            r = winput.paste_text(text, backspaces=len(TRIGGER_TEXT) if action == "delete" else 0)
            self._record({"event": "commit", "prompt": p["name"], "refocus": ok, **r,
                          "verify": v["status"], "verify_method": v["method"],
                          "before": v["text"], "ime": ime, "action": action, "chars": len(text)})
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "missing": res["missing"]}

    def _record(self, ev: dict) -> None:
        self.commits.append(ev)
        del self.commits[:-50]
        self.log(ev)

    # -------------------------------------------------------------- popup actions
    def exclude_current(self) -> dict:
        exe = self.target_exe
        if not exe or not self.save_settings:
            return {"ok": False, "error": "无法识别当前程序"}
        cur = self.get_settings().get("quick_exclude") or ""
        new = normalize_exclude(f"{cur}, {exe}" if cur else exe)
        self.save_settings({"quick_exclude": new})
        self._exclude = exclude_set({"quick_exclude": new})
        self.cancel("exclude")
        self.notify(f"已在 {exe} 中停用 // 唤醒（可在设置 → 排除的程序中恢复）")
        return {"ok": True, "exe": exe}

    def open_main(self) -> dict:
        self.cancel("open_main")
        self.show_main()
        return {"ok": True}


class PopupApi:
    """js_api for the popup window (keep attributes private: pywebview exposes public ones)."""
    def __init__(self, qp: QuickPick):
        self._qp = qp

    def qp_get(self, prompt_id: str) -> dict | None:
        p = self._qp.store.get(prompt_id)
        if not p:
            return None
        from prompt_syntax import variables_of
        vars_ = variables_of(p["body"])
        names = {v["name"] for v in vars_}
        last = {k: v for k, v in (p.get("last_values") or {}).items() if k in names}
        return {"id": p["id"], "name": p["name"], "variables": vars_, "last_values": last,
                "needs_form": any(v["required"] for v in vars_)}

    def qp_commit(self, prompt_id: str, values: dict) -> dict:
        return self._qp.commit(prompt_id, values or {})

    def qp_cancel(self, reason: str = "esc") -> dict:
        threading.Thread(target=self._qp.cancel, args=(reason or "esc",), daemon=True).start()
        return {"ok": True}

    def qp_exclude_current(self) -> dict:
        return self._qp.exclude_current()

    def qp_open_main(self) -> dict:
        threading.Thread(target=self._qp.open_main, daemon=True).start()
        return {"ok": True}
