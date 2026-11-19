"""Keyboard injection, clipboard snapshot/restore and focus switching (Windows)."""
from __future__ import annotations
import ctypes, time
from ctypes import wintypes

from winapi import (F, INPUT, INPUT_KEYBOARD, IS_WIN, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE,
                    PB_MARK, VK_CONTROL, VK_LWIN, VK_MENU, VK_RWIN, VK_SHIFT, key_down,
                    window_pid_tid, hval)

# ------------------------------------------------------------------ input
def _key(vk: int = 0, up: bool = False, scan: int = 0, unicode: bool = False) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    ki = inp.u.ki
    if unicode:
        ki.wVk = 0
        ki.wScan = scan
        ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    else:
        ki.wVk = vk
        ki.wScan = F.MapVirtualKeyW(vk, 0) if F.MapVirtualKeyW else 0
        ext = 0x1 if vk in (0x2D, 0x2E, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0xA3, 0xA5) else 0
        ki.dwFlags = ext | (KEYEVENTF_KEYUP if up else 0)
    ki.time = 0
    ki.dwExtraInfo = PB_MARK
    return inp


def send(inputs: list[INPUT]) -> int:
    if not IS_WIN or not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    return int(F.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)))


def type_unicode(text: str) -> int:
    seq: list[INPUT] = []
    data = (text or "").encode("utf-16-le")
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i + 2], "little")
        seq += [_key(scan=unit, unicode=True), _key(scan=unit, unicode=True, up=True)]
    return send(seq)


MOD_VK = {"shift": VK_SHIFT, "ctrl": VK_CONTROL, "alt": VK_MENU, "win": VK_LWIN}


def release_modifiers() -> None:
    """Lift modifiers that are still physically down so our Ctrl+V is not Ctrl+Shift+V etc."""
    seq = []
    for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN):
        if key_down(vk):
            seq.append(_key(vk, up=True))
    send(seq)


def send_backspaces(n: int) -> int:
    """Delete the "//" trigger the user typed (tagged PB_MARK, so our hook ignores it)."""
    seq: list[INPUT] = []
    for _ in range(max(0, n)):
        seq += [_key(0x08), _key(0x08, up=True)]
    return send(seq)


def send_ctrl_v() -> int:
    return send([_key(VK_CONTROL), _key(0x56), _key(0x56, up=True), _key(VK_CONTROL, up=True)])


# --------------------------------------------------------------- clipboard
CF_UNICODETEXT = 13
_SKIP_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}  # GDI handles / owner-display
_MAX_SNAPSHOT = 64 * 1024 * 1024
GMEM_MOVEABLE = 0x0002


class _Clip:
    """Open the clipboard with a private message-only owner window (retries if busy)."""
    def __init__(self, tries: int = 25):
        self.tries = tries
        self.hwnd = None
        self.ok = False

    def __enter__(self):
        if not IS_WIN:
            return self
        self.hwnd = F.CreateWindowExW(0, "STATIC", "pb-clip", 0, 0, 0, 0, 0,
                                      ctypes.c_void_p(-3), None, None, None)  # HWND_MESSAGE
        for _ in range(self.tries):
            if F.OpenClipboard(self.hwnd):
                self.ok = True
                break
            time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        if IS_WIN:
            if self.ok:
                F.CloseClipboard()
            if self.hwnd:
                F.DestroyWindow(self.hwnd)
        return False


def _global_bytes(h) -> bytes | None:
    if not h:
        return None
    size = F.GlobalSize(h)
    if not size:
        return None
    p = F.GlobalLock(h)
    if not p:
        return None
    try:
        return ctypes.string_at(p, size)
    finally:
        F.GlobalUnlock(h)


def _put(fmt: int, data: bytes) -> bool:
    h = F.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
    if not h:
        return False
    p = F.GlobalLock(h)
    if not p:
        F.GlobalFree(h)
        return False
    ctypes.memmove(p, data, len(data))
    F.GlobalUnlock(h)
    if not F.SetClipboardData(fmt, h):
        F.GlobalFree(h)
        return False
    return True  # system owns h now


def snapshot() -> list[tuple[int, bytes]] | None:
    """Copy every memory-based clipboard format. None = clipboard could not be opened."""
    if not IS_WIN:
        return None
    out: list[tuple[int, bytes]] = []
    total = 0
    with _Clip() as c:
        if not c.ok:
            return None
        fmt = 0
        while True:
            fmt = F.EnumClipboardFormats(fmt)
            if not fmt:
                break
            if fmt in _SKIP_FORMATS or 0x300 <= fmt <= 0x3FF:
                continue
            try:
                data = _global_bytes(F.GetClipboardData(fmt))
            except OSError:
                data = None
            if data is None:
                continue
            total += len(data)
            if total > _MAX_SNAPSHOT:
                out = [(f, d) for f, d in out if f == CF_UNICODETEXT]
                break
            out.append((fmt, data))
    return out


def restore(snap: list[tuple[int, bytes]] | None) -> bool:
    if not IS_WIN or snap is None:
        return False
    with _Clip() as c:
        if not c.ok:
            return False
        F.EmptyClipboard()
        for fmt, data in snap:
            _put(fmt, data)
    return True


def _private_formats() -> list[tuple[int, bytes]]:
    """Ask Windows clipboard history / cloud sync to skip our temporary text."""
    out = []
    for name, val in (("ExcludeClipboardContentFromMonitorProcessing", b"\x00\x00\x00\x00"),
                      ("CanIncludeInClipboardHistory", b"\x00\x00\x00\x00"),
                      ("CanUploadToCloudClipboard", b"\x00\x00\x00\x00")):
        fmt = F.RegisterClipboardFormatW(name)
        if fmt:
            out.append((fmt, val))
    return out


def set_text(text: str, transient: bool = False) -> bool:
    if not IS_WIN:
        return False
    data = (text or "").encode("utf-16-le") + b"\x00\x00"
    with _Clip() as c:
        if not c.ok:
            return False
        F.EmptyClipboard()
        ok = _put(CF_UNICODETEXT, data)
        if transient:
            for fmt, val in _private_formats():
                _put(fmt, val)
    return ok


def get_text() -> str:
    if not IS_WIN:
        return ""
    with _Clip() as c:
        if not c.ok:
            return ""
        data = _global_bytes(F.GetClipboardData(CF_UNICODETEXT))
    if not data:
        return ""
    return data.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]


def seq_no() -> int:
    return int(F.GetClipboardSequenceNumber()) if IS_WIN else 0


# ------------------------------------------------------------------ focus
def _attach(a: int, b: int) -> bool:
    return bool(a and b and a != b and F.AttachThreadInput(a, b, True))


def _detach(a: int, b: int) -> None:
    if a and b and a != b:
        F.AttachThreadInput(a, b, False)


def wait_foreground(hwnd, timeout: float = 0.6) -> bool:
    end = time.time() + timeout
    target = hval(hwnd)
    while time.time() < end:
        if hval(F.GetForegroundWindow()) == target:
            return True
        time.sleep(0.015)
    return hval(F.GetForegroundWindow()) == target


def force_foreground(hwnd, focus_hwnd=None) -> bool:
    """Bring hwnd to the foreground (and optionally focus a child) despite the foreground lock."""
    if not IS_WIN or not hwnd or not F.IsWindow(hwnd):
        return False
    cur = int(F.GetCurrentThreadId())
    fg = F.GetForegroundWindow()
    _, fg_tid = window_pid_tid(fg)
    _, tgt_tid = window_pid_tid(hwnd)
    a1 = _attach(cur, fg_tid)
    a2 = _attach(cur, tgt_tid) if tgt_tid != fg_tid else False
    try:
        if F.IsIconic(hwnd):
            F.ShowWindow(hwnd, 9)  # SW_RESTORE
        F.BringWindowToTop(hwnd)
        F.SetForegroundWindow(hwnd)
        if focus_hwnd and F.IsWindow(focus_hwnd):
            F.SetFocus(focus_hwnd)
    finally:
        if a1:
            _detach(cur, fg_tid)
        if a2:
            _detach(cur, tgt_tid)
    if wait_foreground(hwnd, 0.25):
        return True
    # Last resort: an ALT tap lifts the foreground lock. Never while Shift is held
    # (Alt+Shift is the default input-language switch).
    if not key_down(VK_SHIFT):
        send([_key(VK_MENU)])
        F.SetForegroundWindow(hwnd)
        send([_key(VK_MENU, up=True)])
        if focus_hwnd and F.IsWindow(focus_hwnd):
            a = _attach(cur, tgt_tid)
            F.SetFocus(focus_hwnd)
            if a:
                _detach(cur, tgt_tid)
    return wait_foreground(hwnd, 0.35)


def paste_text(text: str, restore_after: float = 0.45, backspaces: int = 0) -> dict:
    """(Backspace × n, then) Ctrl+V `text` into the focused control, then restore the clipboard."""
    if not IS_WIN:
        return {"ok": False, "error": "仅 Windows"}
    snap = snapshot()
    if not set_text(text, transient=True):
        return {"ok": False, "error": "无法写入剪贴板（被其他程序占用）"}
    mine = seq_no()
    release_modifiers()
    if backspaces:
        send_backspaces(backspaces)
        time.sleep(0.03)
    send_ctrl_v()
    time.sleep(restore_after)
    restored = False
    if snap is not None:
        # only restore if nobody else changed the clipboard in the meantime
        if seq_no() == mine:
            restored = restore(snap)
    return {"ok": True, "restored": restored, "had_snapshot": snap is not None}
