"""Locate the text caret of the foreground app (physical screen pixels) and place the popup.

Order (stop at the first plausible result):
  1. GetGUIThreadInfo → rcCaret of the focused thread (classic Win32 / WinForms / many editors),
     converted from the window's own DPI space with LogicalToPhysicalPointForPerMonitorDPI.
  2. MSAA: AccessibleObjectFromWindow(OBJID_CARET) → IAccessible::accLocation
     (Chrome / Edge / Electron / Office expose the caret this way).
  3. UI Automation (comtypes, optional): focused element TextPattern selection / TextPattern2
     caret range → GetBoundingRectangles (WPF, UWP, Windows Terminal, ...). Runs with a timeout.
  4. Mouse pointer.
Every result must fall inside the foreground window rectangle, otherwise it is discarded.
"""
from __future__ import annotations
import ctypes, queue, threading, time
from ctypes import wintypes
from dataclasses import dataclass, field

from winapi import (F, GUITHREADINFO, IS_WIN, MONITOR_DEFAULTTONEAREST, MONITORINFO, POINT, RECT,
                    hval, oleacc, ole32, per_monitor_dpi, window_pid_tid, window_rect)


@dataclass
class Target:
    hwnd: int = 0            # top-level foreground window
    focus: int = 0           # focused child (if same-thread info available)
    pid: int = 0
    tid: int = 0
    caret: tuple | None = None   # (left, top, right, bottom) physical px
    method: str = "mouse"
    mouse: tuple = (0, 0)
    tried: list = field(default_factory=list)


# ------------------------------------------------------------ 1. GUI thread
def _to_physical(hwnd, x: int, y: int) -> tuple[int, int]:
    pt = POINT(x, y)
    ctx = F.GetWindowDpiAwarenessContext(hwnd) if F.GetWindowDpiAwarenessContext else None
    old = F.SetThreadDpiAwarenessContext(ctx) if (ctx and F.SetThreadDpiAwarenessContext) else None
    try:
        F.ClientToScreen(hwnd, ctypes.byref(pt))
    finally:
        if old:
            F.SetThreadDpiAwarenessContext(old)
    if F.LogicalToPhysicalPointForPerMonitorDPI:
        F.LogicalToPhysicalPointForPerMonitorDPI(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def _caret_gui(tid: int, t: Target) -> tuple | None:
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not F.GetGUIThreadInfo(tid, ctypes.byref(gti)):
        return None
    t.focus = hval(gti.hwndFocus)
    hc = gti.hwndCaret
    if not hc:
        return None
    rc = gti.rcCaret
    if rc.bottom - rc.top <= 0 or (rc.left == 0 and rc.top == 0 and rc.right <= 1):
        return None
    x1, y1 = _to_physical(hc, rc.left, rc.top)
    x2, y2 = _to_physical(hc, rc.right, rc.bottom)
    return (x1, y1, max(x2, x1 + 1), y2)


# ------------------------------------------------------------ 2. MSAA caret
class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]


class _VARIANT(ctypes.Structure):  # x64 layout, 24 bytes
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("lVal", ctypes.c_long), ("pad", ctypes.c_long),
                ("pad2", ctypes.c_void_p)]


_IID_IAccessible = _GUID(0x618736E0, 0x3C3D, 0x11CF, (ctypes.c_ubyte * 8)(0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71))
_OBJID_CARET = 0xFFFFFFF8


def _caret_msaa(hwnd) -> tuple | None:
    if not oleacc or not hwnd:
        return None
    ole32.CoInitializeEx(None, 2)  # STA; harmless if already initialized
    ptr = ctypes.c_void_p()
    fn = oleacc.AccessibleObjectFromWindow
    fn.restype = ctypes.c_long
    fn.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    if fn(hwnd, _OBJID_CARET, ctypes.byref(_IID_IAccessible), ctypes.byref(ptr)) != 0 or not ptr.value:
        return None
    vtbl = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    try:
        LP = ctypes.POINTER(ctypes.c_long)
        acc_location = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, LP, LP, LP, LP, _VARIANT)(vtbl[22])
        x, y, w, h = ctypes.c_long(), ctypes.c_long(), ctypes.c_long(), ctypes.c_long()
        var = _VARIANT()
        var.vt = 3  # VT_I4, CHILDID_SELF = 0
        hr = acc_location(ptr, ctypes.byref(x), ctypes.byref(y), ctypes.byref(w), ctypes.byref(h), var)
        if hr != 0 or (x.value == 0 and y.value == 0 and w.value == 0 and h.value == 0) or h.value <= 0:
            return None
        return (x.value, y.value, x.value + max(1, w.value), y.value + h.value)
    finally:
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        release(ptr)


# ------------------------------------------------------------ 3. UI Automation
_uia_state = {"ok": None, "err": ""}


def uia_available() -> bool:
    if _uia_state["ok"] is None:
        try:
            import comtypes.client  # noqa: F401
            try:  # pre-generated at build time (frozen app) …
                from comtypes.gen import UIAutomationClient  # noqa: F401
            except ImportError:  # … or generate on first use (source run)
                comtypes.client.GetModule("UIAutomationCore.dll")
                from comtypes.gen import UIAutomationClient  # noqa: F401
            _uia_state["ok"] = True
        except Exception as e:
            _uia_state["ok"], _uia_state["err"] = False, str(e)
    return bool(_uia_state["ok"])


def _uia_query(uia, U, out: dict) -> None:
    with per_monitor_dpi():
        el = uia.GetFocusedElement()
        if not el:
            return
        rng = None
        try:
            p2 = el.GetCurrentPattern(10024)  # TextPattern2
            if p2:
                tp2 = p2.QueryInterface(U.IUIAutomationTextPattern2)
                res = tp2.GetCaretRange()
                rng = res[1] if isinstance(res, tuple) else res
        except Exception:
            rng = None
        if rng is None:
            p1 = el.GetCurrentPattern(10014)  # TextPattern
            if not p1:
                return
            tp = p1.QueryInterface(U.IUIAutomationTextPattern)
            sel = tp.GetSelection()
            if not sel or sel.Length < 1:
                return
            rng = sel.GetElement(0)
        rects = list(rng.GetBoundingRectangles() or [])
        if not rects:
            rng.ExpandToEnclosingUnit(0)  # TextUnit_Character
            rects = list(rng.GetBoundingRectangles() or [])
        if len(rects) >= 4:
            x, y, w, h = rects[-4:]
            if h > 0:
                out["rect"] = (int(x), int(y), int(x + max(1, w)), int(y + h))


class _UiaWorker:
    """One long-lived MTA thread that owns the IUIAutomation object.

    Creating CUIAutomation costs tens of ms; doing it once (pre-warmed at startup) keeps
    the "//" → popup path fast. Requests carry a deadline: if the popup already gave up
    on UIA (timeout), the stale request is skipped instead of piling up."""
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._th: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        with self._lock:
            if self._th is None or not self._th.is_alive():
                self._th = threading.Thread(target=self._run, name="pb-uia", daemon=True)
                self._th.start()

    def _run(self) -> None:
        uia = U = None
        try:
            import comtypes, comtypes.client
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            from comtypes.gen import UIAutomationClient as U  # noqa: N811
            uia = comtypes.client.CreateObject(U.CUIAutomation._reg_clsid_, interface=U.IUIAutomation)
        except Exception as e:
            _uia_state["err"] = str(e)
        while True:
            item = self._q.get()
            if item is None:
                return
            fn, out, ev, deadline = item
            try:
                if uia is not None and time.perf_counter() < deadline:
                    fn(uia, U, out)
            except Exception as e:
                out["err"] = str(e)
            finally:
                ev.set()

    def prewarm(self) -> None:
        if uia_available():
            self._ensure()

    def run(self, fn, timeout: float) -> dict:
        """Run fn(uia, U, out) on the worker; returns `out` (possibly empty on timeout)."""
        if not uia_available():
            return {}
        self._ensure()
        out: dict = {}
        ev = threading.Event()
        self._q.put((fn, out, ev, time.perf_counter() + timeout))
        if not ev.wait(timeout):
            out = dict(out)
            out["timeout"] = True
        return out

    def query(self, timeout: float) -> tuple | None:
        return self.run(_uia_query, timeout).get("rect")


_uia_worker = _UiaWorker()


def prewarm() -> None:
    """Called once after startup (off the hot path)."""
    try:
        _uia_worker.prewarm()
    except Exception:
        pass


def _caret_uia(timeout: float = 0.22) -> tuple | None:
    return _uia_worker.query(timeout)


def uia_run(fn, timeout: float) -> dict:
    """Public entry for other modules (text verification) to use the warm UIA thread."""
    try:
        return _uia_worker.run(fn, timeout)
    except Exception as e:  # pragma: no cover
        return {"err": str(e)}


# ------------------------------------------------------------ capture
def _inside(rect, win) -> bool:
    if not rect or not win:
        return False
    x, y = rect[0], rect[3]
    l, t, r, b = win
    return (l - 4) <= x <= (r + 4) and (t - 4) <= y <= (b + 4)


def capture(prefer: str = "caret", use_uia: bool = True) -> Target:
    t = Target()
    if not IS_WIN:
        return t
    with per_monitor_dpi():
        fg = F.GetForegroundWindow()
        t.hwnd = hval(fg)
        t.pid, t.tid = window_pid_tid(fg)
        pt = POINT()
        (F.GetPhysicalCursorPos or F.GetCursorPos)(ctypes.byref(pt))
        t.mouse = (pt.x, pt.y)
        caret = None
        # always read GUI thread info (it also tells us the focused child for re-focus)
        try:
            caret = _caret_gui(t.tid, t)
        except Exception:
            caret = None
        t.tried.append("gui")
        if prefer != "caret":
            t.caret, t.method = None, "mouse"
            return t
        win = window_rect(fg)
        if caret and _inside(caret, win):
            t.method = "gui"
        else:
            caret = None
            try:
                caret = _caret_msaa(t.focus or t.hwnd)
            except Exception:
                caret = None
            t.tried.append("msaa")
            if caret and _inside(caret, win):
                t.method = "msaa"
            else:
                caret = None
                if use_uia:
                    caret = _caret_uia()
                    t.tried.append("uia")
                    if caret and _inside(caret, win):
                        t.method = "uia"
                    else:
                        caret = None
        t.caret = caret
        if not caret:
            t.method = "mouse"
    return t


def popup_rect(t: Target, width: int, height: int, gap: int = 6) -> tuple[int, int, int, int, float]:
    """(x, y, w, h, scale) in physical px, clamped to the monitor work area."""
    if not IS_WIN:
        return (100, 100, width, height, 1.0)
    with per_monitor_dpi():
        if t.caret:
            ax, ay_top, ay_bottom = t.caret[0], t.caret[1], t.caret[3]
            dx = 0
        else:
            ax, ay_top, ay_bottom = t.mouse[0], t.mouse[1], t.mouse[1] + 18
            dx = 12
        mon = F.MonitorFromPoint(POINT(ax, ay_bottom), MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        F.GetMonitorInfoW(mon, ctypes.byref(mi))
        work = mi.rcWork
        scale = 1.0
        if F.GetDpiForMonitor:
            dx_dpi, dy_dpi = wintypes.UINT(96), wintypes.UINT(96)
            if F.GetDpiForMonitor(mon, 0, ctypes.byref(dx_dpi), ctypes.byref(dy_dpi)) == 0:
                scale = dx_dpi.value / 96.0
        w, h = int(width * scale), int(height * scale)
        g = int(gap * scale)
        x = ax + int(dx * scale)
        y = ay_bottom + g
        if y + h > work.bottom:               # not enough room below → flip above the caret
            y = ay_top - g - h
        y = max(work.top, min(y, work.bottom - h))
        x = max(work.left, min(x, work.right - w))
        return (x, y, w, h, scale)


def place_window(hwnd, rect) -> bool:
    """SetWindowPos with physical coordinates (thread temporarily per-monitor aware)."""
    if not IS_WIN or not hwnd:
        return False
    from winapi import HWND_TOPMOST, SWP_NOACTIVATE
    x, y, w, h = rect[:4]
    with per_monitor_dpi():
        return bool(F.SetWindowPos(hwnd, ctypes.c_void_p(HWND_TOPMOST), x, y, w, h, SWP_NOACTIVATE))
