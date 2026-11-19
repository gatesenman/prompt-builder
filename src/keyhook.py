"""Global "//" trigger for the quick-pick popup.

WH_KEYBOARD_LL low-level hook on a dedicated thread with its own message loop.
  * NOTHING is swallowed: every key (including both "/") reaches the app unchanged, so a
    single "/" or "?" always types normally;
  * the popup triggers when "/" is pressed twice in a row — no other key in between, within
    DOUBLE_MS, same foreground window — see SlashDetector (pure logic, unit tested);
  * no trigger after ":" (https://), on a held / auto-repeating "/", with Ctrl/Alt/Win held,
    or for Shift+/ ("?");
  * main-keyboard "/" (VK_OEM_2) and numpad divide (VK_DIVIDE) both count;
  * injected events tagged PB_MARK (our own Backspace / Ctrl+V) are ignored;
  * the callback only updates a few fields and queues work — it never blocks, so Windows
    will not drop the hook for exceeding LowLevelHooksTimeout;
  * a watchdog reinstalls the hook if it stops receiving events while the user types.
"""
from __future__ import annotations
import ctypes, queue, threading, time
from ctypes import wintypes
from typing import Callable

from winapi import (F, HOOKPROC, IS_WIN, KBDLLHOOKSTRUCT, LASTINPUTINFO, PB_MARK, VK_CONTROL,
                    VK_LWIN, VK_MENU, VK_RWIN, VK_SHIFT, hval, key_down)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_QUIT, WM_APP = 0x0012, 0x8000
MSG_REINSTALL = WM_APP + 1
LLKHF_INJECTED = 0x10

VK_OEM_2, VK_DIVIDE, VK_OEM_1 = 0xBF, 0x6F, 0xBA     # "/"  numpad "/"  ";:" key
SLASH_VKS = (VK_OEM_2, VK_DIVIDE)
MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14, 0x90, 0x91}
DOUBLE_MS = 500
TRIGGER_TEXT = "//"


class SlashDetector:
    """Pure state machine (no Win32), fed with key events from the hook.

    feed() returns True exactly on the second "/" of a qualifying "//"."""
    def __init__(self, window_ms: int = DOUBLE_MS):
        self.window = window_ms / 1000.0
        self.reset()

    def reset(self) -> None:
        self.first_t: float | None = None   # time of a pending first "/"
        self.first_fg = 0
        self.after_colon = False            # last non-modifier key was ":"
        self.url_run = False                # inside a "://…" slash run (file:///)
        self.down: set[int] = set()         # slash keys physically down (auto-repeat filter)
        self.last_slash_t: float | None = None
        self.last_slash_fg = 0

    def feed(self, vk: int, is_down: bool, t: float, shift: bool = False, ctrl: bool = False,
             alt: bool = False, win: bool = False, fg: int = 0) -> bool:
        if vk in MODIFIER_VKS:
            return False                    # modifiers never break or form a sequence
        if not is_down:
            self.down.discard(vk)
            return False
        if vk in SLASH_VKS:
            repeat = vk in self.down
            self.down.add(vk)
            plain = not ctrl and not alt and not win and (vk == VK_DIVIDE or not shift)
            if repeat or not plain:
                # auto-repeat ("////…" by holding the key), "?" or a shortcut: never a trigger
                self.first_t = None
                self.after_colon = False
                return False
            if self.first_t is not None and t - self.first_t <= self.window and fg == self.first_fg:
                self.first_t = None
                self.after_colon = False
                return True
            # this "/" becomes the first of a possible pair, unless it directly follows ":"
            # (https://, file:///): the whole slash run after a colon is ignored.  The run
            # ends after a pause longer than the window or in another window.
            if self.url_run and (self.last_slash_t is None or t - self.last_slash_t > self.window
                                 or fg != self.last_slash_fg):
                self.url_run = False
            self.last_slash_t, self.last_slash_fg = t, fg
            if self.after_colon:
                self.url_run = True
            self.first_t = None if self.url_run else t
            self.first_fg = fg
            self.after_colon = False
            return False
        # any other key in between cancels the pair
        self.first_t = None
        self.url_run = False
        self.after_colon = (vk == VK_OEM_1 and shift)
        return False


class KeyHook:
    def __init__(self, on_trigger: Callable[[str, float], None],
                 should_trigger: Callable[[int], bool], accept_injected: bool = False,
                 window_ms: int = DOUBLE_MS):
        self.on_trigger = on_trigger
        self.should_trigger = should_trigger
        self.accept_injected = accept_injected
        self.det = SlashDetector(window_ms)
        self.mode = "off"          # hook | off | error
        self.error = ""
        self.reinstalls = 0
        self.display = TRIGGER_TEXT
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._hhook = None
        self._proc = HOOKPROC(self._callback) if IS_WIN else None  # keep reference alive
        self._last_cb = time.time()
        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._stop = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> dict:
        if not IS_WIN:
            self.mode, self.error = "error", "仅支持 Windows"
            return self.status()
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="pb-keyhook", daemon=True)
        self._thread.start()
        threading.Thread(target=self._dispatch, name="pb-keyhook-dispatch", daemon=True).start()
        threading.Thread(target=self._watchdog, name="pb-keyhook-watchdog", daemon=True).start()
        self._ready.wait(3)
        return self.status()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)
        if IS_WIN and self._tid:
            F.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(2)
        self.mode = "off"

    def status(self) -> dict:
        return {"mode": self.mode, "error": self.error, "hotkey": self.display,
                "reinstalls": self.reinstalls}

    # ------------------------------------------------------------ thread
    def _install_hook(self) -> bool:
        hmod = F.GetModuleHandleW(None)
        self._hhook = F.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, hmod, 0)
        if not self._hhook:
            self.error = f"SetWindowsHookEx 失败（错误码 {ctypes.get_last_error()}），可能被安全软件拦截"
            return False
        self._last_cb = time.time()
        return True

    def _uninstall_hook(self) -> None:
        if self._hhook:
            F.UnhookWindowsHookEx(self._hhook)
            self._hhook = None

    def _run(self) -> None:
        self._tid = int(F.GetCurrentThreadId())
        msg = wintypes.MSG()
        F.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create the message queue
        self.mode = "hook" if self._install_hook() else "error"
        self._ready.set()
        if self.mode == "error":
            return
        while not self._stop.is_set():
            r = F.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            if msg.message == MSG_REINSTALL and self.mode == "hook":
                self._uninstall_hook()
                if self._install_hook():
                    self.reinstalls += 1
                else:
                    self.mode = "error"
        self._uninstall_hook()

    def _callback(self, ncode, wparam, lparam):
        try:
            if ncode == 0:
                self._last_cb = time.time()
                kb = KBDLLHOOKSTRUCT.from_address(lparam)
                if kb.dwExtraInfo != PB_MARK and (self.accept_injected or not (kb.flags & LLKHF_INJECTED)):
                    is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    vk = int(kb.vkCode)
                    if vk in SLASH_VKS and is_down:
                        fg = hval(F.GetForegroundWindow())
                        if self.det.feed(vk, True, time.perf_counter(), key_down(VK_SHIFT),
                                         key_down(VK_CONTROL), key_down(VK_MENU),
                                         key_down(VK_LWIN) or key_down(VK_RWIN), fg) \
                                and self.should_trigger(fg):
                            self._q.put(time.perf_counter())
                    else:
                        self.det.feed(vk, is_down, time.perf_counter(),
                                      shift=key_down(VK_SHIFT) if is_down and vk == VK_OEM_1 else False)
        except Exception:
            pass
        return F.CallNextHookEx(None, ncode, wparam, lparam)  # never swallow anything

    def _dispatch(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is None:
                break
            try:
                self.on_trigger("hook", item)
            except Exception as e:  # never let the dispatcher die
                import logging
                logging.getLogger("pb").exception("quick-pick trigger error: %s", e)

    def _watchdog(self) -> None:
        """Windows silently removes LL hooks that time out; reinstall if we go deaf."""
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        while not self._stop.wait(10):
            if self.mode != "hook" or not self._tid:
                continue
            if not F.GetLastInputInfo(ctypes.byref(info)):
                continue
            idle_ms = (int(F.GetTickCount()) - int(info.dwTime)) & 0xFFFFFFFF
            silent = time.time() - self._last_cb
            if idle_ms < 5000 and silent > 90:
                F.PostThreadMessageW(self._tid, MSG_REINSTALL, 0, 0)
