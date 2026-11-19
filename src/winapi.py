"""Thin ctypes layer over Win32 used by the quick-pick popup.

All functions are no-ops / return None on non-Windows so the rest of the app
(and the unit tests on Linux) keep working.
"""
from __future__ import annotations
import ctypes, os, sys, time
from ctypes import wintypes

IS_WIN = sys.platform == "win32"

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HRESULT_T = ctypes.c_long

# marker placed in dwExtraInfo of every event we inject, so our own hook ignores it
PB_MARK = 0x50420024

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LSHIFT, VK_RSHIFT = 0xA0, 0xA1
VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA2, 0xA3, 0xA4, 0xA5
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_RETURN, VK_ESCAPE = 0x0D, 0x1B

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4

SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
HWND_TOPMOST = -1
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x80, 0x40000, 0x08000000
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
MONITOR_DEFAULTTONEAREST = 2


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", RECT)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


HOOKPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32 = kernel32 = shcore = advapi32 = oleacc = ole32 = None


def _bind(dll, name, restype, *argtypes):
    try:
        f = getattr(dll, name)
    except AttributeError:
        return None
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


class _F:  # namespace of bound functions
    pass


F = _F()

if IS_WIN:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:
        shcore = None
    try:
        oleacc = ctypes.WinDLL("oleacc")
        ole32 = ctypes.WinDLL("ole32")
    except OSError:
        oleacc = ole32 = None
    H, B, U, D, I = wintypes.HWND, wintypes.BOOL, wintypes.UINT, wintypes.DWORD, ctypes.c_int
    VP = ctypes.c_void_p
    F.GetForegroundWindow = _bind(user32, "GetForegroundWindow", H)
    F.SetForegroundWindow = _bind(user32, "SetForegroundWindow", B, H)
    F.BringWindowToTop = _bind(user32, "BringWindowToTop", B, H)
    F.SetFocus = _bind(user32, "SetFocus", H, H)
    F.IsWindow = _bind(user32, "IsWindow", B, H)
    F.IsWindowVisible = _bind(user32, "IsWindowVisible", B, H)
    F.IsIconic = _bind(user32, "IsIconic", B, H)
    F.ShowWindow = _bind(user32, "ShowWindow", B, H, I)
    F.GetWindowThreadProcessId = _bind(user32, "GetWindowThreadProcessId", D, H, ctypes.POINTER(D))
    F.AttachThreadInput = _bind(user32, "AttachThreadInput", B, D, D, B)
    F.GetCurrentThreadId = _bind(kernel32, "GetCurrentThreadId", D)
    F.GetCurrentProcessId = _bind(kernel32, "GetCurrentProcessId", D)
    F.GetGUIThreadInfo = _bind(user32, "GetGUIThreadInfo", B, D, ctypes.POINTER(GUITHREADINFO))
    F.ClientToScreen = _bind(user32, "ClientToScreen", B, H, ctypes.POINTER(POINT))
    F.GetWindowRect = _bind(user32, "GetWindowRect", B, H, ctypes.POINTER(RECT))
    F.GetCursorPos = _bind(user32, "GetCursorPos", B, ctypes.POINTER(POINT))
    F.GetPhysicalCursorPos = _bind(user32, "GetPhysicalCursorPos", B, ctypes.POINTER(POINT))
    F.MonitorFromPoint = _bind(user32, "MonitorFromPoint", VP, POINT, D)
    F.GetMonitorInfoW = _bind(user32, "GetMonitorInfoW", B, VP, ctypes.POINTER(MONITORINFO))
    F.SetWindowPos = _bind(user32, "SetWindowPos", B, H, H, I, I, I, I, U)
    F.GetWindowLongPtrW = _bind(user32, "GetWindowLongPtrW", ctypes.c_ssize_t, H, I)
    F.SetWindowLongPtrW = _bind(user32, "SetWindowLongPtrW", ctypes.c_ssize_t, H, I, ctypes.c_ssize_t)
    F.FindWindowW = _bind(user32, "FindWindowW", H, wintypes.LPCWSTR, wintypes.LPCWSTR)
    F.SendInput = _bind(user32, "SendInput", U, U, ctypes.POINTER(INPUT), I)
    F.MapVirtualKeyW = _bind(user32, "MapVirtualKeyW", U, U, U)
    F.GetAsyncKeyState = _bind(user32, "GetAsyncKeyState", ctypes.c_short, I)
    F.GetKeyboardLayout = _bind(user32, "GetKeyboardLayout", VP, D)
    F.GetLastInputInfo = _bind(user32, "GetLastInputInfo", B, ctypes.POINTER(LASTINPUTINFO))
    F.GetTickCount = _bind(kernel32, "GetTickCount", D)
    F.SetThreadDpiAwarenessContext = _bind(user32, "SetThreadDpiAwarenessContext", VP, VP)
    F.GetWindowDpiAwarenessContext = _bind(user32, "GetWindowDpiAwarenessContext", VP, H)
    F.LogicalToPhysicalPointForPerMonitorDPI = _bind(
        user32, "LogicalToPhysicalPointForPerMonitorDPI", B, H, ctypes.POINTER(POINT))
    F.GetDpiForMonitor = _bind(shcore, "GetDpiForMonitor", HRESULT_T, VP, I,
                               ctypes.POINTER(U), ctypes.POINTER(U)) if shcore else None
    F.OpenProcess = _bind(kernel32, "OpenProcess", wintypes.HANDLE, D, B, D)
    F.CloseHandle = _bind(kernel32, "CloseHandle", B, wintypes.HANDLE)
    F.OpenProcessToken = _bind(advapi32, "OpenProcessToken", B, wintypes.HANDLE, D,
                               ctypes.POINTER(wintypes.HANDLE))
    F.GetTokenInformation = _bind(advapi32, "GetTokenInformation", B, wintypes.HANDLE, I,
                                  VP, D, ctypes.POINTER(D))
    F.GetCurrentProcess = _bind(kernel32, "GetCurrentProcess", wintypes.HANDLE)
    F.SetWindowsHookExW = _bind(user32, "SetWindowsHookExW", wintypes.HHOOK, I, HOOKPROC,
                                wintypes.HINSTANCE, D)
    F.UnhookWindowsHookEx = _bind(user32, "UnhookWindowsHookEx", B, wintypes.HHOOK)
    F.CallNextHookEx = _bind(user32, "CallNextHookEx", LRESULT, wintypes.HHOOK, I,
                             wintypes.WPARAM, wintypes.LPARAM)
    F.GetModuleHandleW = _bind(kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
    F.GetMessageW = _bind(user32, "GetMessageW", B, ctypes.POINTER(wintypes.MSG), H, U, U)
    F.PeekMessageW = _bind(user32, "PeekMessageW", B, ctypes.POINTER(wintypes.MSG), H, U, U, U)
    F.PostThreadMessageW = _bind(user32, "PostThreadMessageW", B, D, U, wintypes.WPARAM, wintypes.LPARAM)
    F.DwmSetWindowAttribute = None
    try:
        dwm = ctypes.WinDLL("dwmapi")
        F.DwmSetWindowAttribute = _bind(dwm, "DwmSetWindowAttribute", HRESULT_T, H, D, VP, D)
    except OSError:
        pass
    # clipboard
    F.OpenClipboard = _bind(user32, "OpenClipboard", B, H)
    F.CloseClipboard = _bind(user32, "CloseClipboard", B)
    F.EmptyClipboard = _bind(user32, "EmptyClipboard", B)
    F.EnumClipboardFormats = _bind(user32, "EnumClipboardFormats", U, U)
    F.GetClipboardData = _bind(user32, "GetClipboardData", wintypes.HANDLE, U)
    F.SetClipboardData = _bind(user32, "SetClipboardData", wintypes.HANDLE, U, wintypes.HANDLE)
    F.GetClipboardSequenceNumber = _bind(user32, "GetClipboardSequenceNumber", D)
    F.RegisterClipboardFormatW = _bind(user32, "RegisterClipboardFormatW", U, wintypes.LPCWSTR)
    F.GlobalAlloc = _bind(kernel32, "GlobalAlloc", wintypes.HGLOBAL, U, ctypes.c_size_t)
    F.GlobalLock = _bind(kernel32, "GlobalLock", VP, wintypes.HGLOBAL)
    F.GlobalUnlock = _bind(kernel32, "GlobalUnlock", B, wintypes.HGLOBAL)
    F.GlobalSize = _bind(kernel32, "GlobalSize", ctypes.c_size_t, wintypes.HGLOBAL)
    F.GlobalFree = _bind(kernel32, "GlobalFree", wintypes.HGLOBAL, wintypes.HGLOBAL)
    F.CreateWindowExW = _bind(user32, "CreateWindowExW", H, D, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              D, I, I, I, I, H, wintypes.HMENU, wintypes.HINSTANCE, VP)
    F.DestroyWindow = _bind(user32, "DestroyWindow", B, H)
    F.QueryFullProcessImageNameW = _bind(kernel32, "QueryFullProcessImageNameW", B, wintypes.HANDLE, D,
                                         wintypes.LPWSTR, ctypes.POINTER(D))
    F.MonitorFromWindow = _bind(user32, "MonitorFromWindow", VP, H, D)
    F.GetAncestor = _bind(user32, "GetAncestor", H, H, U)
    F.GetClassNameW = _bind(user32, "GetClassNameW", I, H, wintypes.LPWSTR, I)
    F.GetShellWindow = _bind(user32, "GetShellWindow", H)
    F.IsZoomed = _bind(user32, "IsZoomed", B, H)
    # 2.6: popup parking (DWM cloak), text verification, IME state, elevation, instance objects
    F.DwmGetWindowAttribute = None
    try:
        F.DwmGetWindowAttribute = _bind(dwm, "DwmGetWindowAttribute", HRESULT_T, H, D, VP, D)
    except NameError:
        pass
    F.GetSystemMetrics = _bind(user32, "GetSystemMetrics", I, I)
    F.MonitorFromRect = _bind(user32, "MonitorFromRect", VP, ctypes.POINTER(RECT), D)
    F.SendMessageTimeoutW = _bind(user32, "SendMessageTimeoutW", LRESULT, H, U, wintypes.WPARAM,
                                  wintypes.LPARAM, U, U, ctypes.POINTER(ULONG_PTR))
    F.GetWindowTextLengthW = _bind(user32, "GetWindowTextLengthW", I, H)
    try:
        imm32 = ctypes.WinDLL("imm32")
        F.ImmGetDefaultIMEWnd = _bind(imm32, "ImmGetDefaultIMEWnd", H, H)
    except OSError:
        F.ImmGetDefaultIMEWnd = None
    F.ConvertStringSecurityDescriptorToSecurityDescriptorW = _bind(
        advapi32, "ConvertStringSecurityDescriptorToSecurityDescriptorW", B, wintypes.LPCWSTR, D,
        ctypes.POINTER(VP), ctypes.POINTER(D))
    F.LocalFree = _bind(kernel32, "LocalFree", VP, VP)
    F.CreateMutexW = _bind(kernel32, "CreateMutexW", wintypes.HANDLE, VP, B, wintypes.LPCWSTR)
    F.OpenMutexW = _bind(kernel32, "OpenMutexW", wintypes.HANDLE, D, B, wintypes.LPCWSTR)
    F.CreateEventW = _bind(kernel32, "CreateEventW", wintypes.HANDLE, VP, B, B, wintypes.LPCWSTR)
    F.OpenEventW = _bind(kernel32, "OpenEventW", wintypes.HANDLE, D, B, wintypes.LPCWSTR)
    F.SetEvent = _bind(kernel32, "SetEvent", B, wintypes.HANDLE)
    F.WaitForSingleObject = _bind(kernel32, "WaitForSingleObject", D, wintypes.HANDLE, D)
    F.WaitForMultipleObjects = _bind(kernel32, "WaitForMultipleObjects", D, D,
                                     ctypes.POINTER(wintypes.HANDLE), B, D)
    F.ReleaseMutex = _bind(kernel32, "ReleaseMutex", B, wintypes.HANDLE)
    F.GetExitCodeProcess = _bind(kernel32, "GetExitCodeProcess", B, wintypes.HANDLE, ctypes.POINTER(D))


# ---------------------------------------------------------------- helpers
def hval(h) -> int:
    """Normalize HWND/handle to int (0 for NULL)."""
    if h is None:
        return 0
    if isinstance(h, int):
        return h
    return int(getattr(h, "value", 0) or 0)


class per_monitor_dpi:
    """Context manager: make the current thread per-monitor-v2 DPI aware (physical px)."""
    def __enter__(self):
        self.old = None
        if IS_WIN and F.SetThreadDpiAwarenessContext:
            self.old = F.SetThreadDpiAwarenessContext(
                ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
        return self

    def __exit__(self, *exc):
        if IS_WIN and self.old and F.SetThreadDpiAwarenessContext:
            F.SetThreadDpiAwarenessContext(ctypes.c_void_p(self.old))
        return False


def window_pid_tid(hwnd) -> tuple[int, int]:
    if not IS_WIN or not hwnd:
        return 0, 0
    pid = wintypes.DWORD(0)
    tid = F.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value), int(tid)


def key_down(vk: int) -> bool:
    return bool(IS_WIN and (F.GetAsyncKeyState(vk) & 0x8000))


def window_rect(hwnd) -> tuple[int, int, int, int] | None:
    r = RECT()
    if IS_WIN and hwnd and F.GetWindowRect(hwnd, ctypes.byref(r)):
        return r.left, r.top, r.right, r.bottom
    return None


_elev_cache: dict[int, tuple[float, bool]] = {}


def _token_elevated(hproc) -> bool | None:
    tok = wintypes.HANDLE()
    if not F.OpenProcessToken(hproc, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
        return None
    try:
        val = wintypes.DWORD(0)
        ret = wintypes.DWORD(0)
        if F.GetTokenInformation(tok, 20, ctypes.byref(val), 4, ctypes.byref(ret)):  # TokenElevation
            return bool(val.value)
        return None
    finally:
        F.CloseHandle(tok)


def self_elevated() -> bool:
    if not IS_WIN:
        return False
    r = _token_elevated(F.GetCurrentProcess())
    return bool(r)


def process_elevated(pid: int) -> bool:
    """True if pid runs elevated (or we cannot even open it, e.g. protected/admin)."""
    if not IS_WIN or not pid:
        return False
    now = time.time()
    hit = _elev_cache.get(pid)
    if hit and now - hit[0] < 30:
        return hit[1]
    h = F.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        res = ctypes.get_last_error() == 5  # access denied → treat as elevated
    else:
        try:
            res = bool(_token_elevated(h))
        finally:
            F.CloseHandle(h)
    _elev_cache[pid] = (now, res)
    return res


# ------------------------------------------------- cheap checks used inside the LL hook
_exe_cache: dict[int, tuple[float, str]] = {}


def process_exe_name(pid: int) -> str:
    """Lower-case exe file name of pid ('' if unknown). Cached 60 s (pids are reused)."""
    if not IS_WIN or not pid:
        return ""
    now = time.time()
    hit = _exe_cache.get(pid)
    if hit and now - hit[0] < 60:
        return hit[1]
    name = ""
    h = F.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if F.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
        finally:
            F.CloseHandle(h)
    if len(_exe_cache) > 512:
        _exe_cache.clear()
    _exe_cache[pid] = (now, name)
    return name


def class_name(hwnd) -> str:
    if not IS_WIN or not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    n = F.GetClassNameW(hwnd, buf, 256)
    return buf.value[:n] if n > 0 else ""


def root_window(hwnd) -> int:
    if not IS_WIN or not hwnd:
        return 0
    return hval(F.GetAncestor(hwnd, 2)) or hval(hwnd)  # GA_ROOT


GUI_INMOVESIZE, GUI_INMENUMODE, GUI_POPUPMENUMODE, GUI_SYSTEMMENUMODE = 0x2, 0x4, 0x10, 0x8


def gui_thread_busy(tid: int) -> bool:
    """True while the thread is in a menu loop or moving/sizing a window."""
    if not IS_WIN or not tid:
        return False
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not F.GetGUIThreadInfo(tid, ctypes.byref(gti)):
        return False
    return bool(gti.flags & (GUI_INMOVESIZE | GUI_INMENUMODE | GUI_POPUPMENUMODE | GUI_SYSTEMMENUMODE))


_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def is_shell_window(hwnd) -> bool:
    """Desktop / taskbar: no text box there, so '?' should simply pass through."""
    return class_name(hwnd) in _SHELL_CLASSES


def is_fullscreen(hwnd) -> bool:
    """Borderless window covering its whole monitor (games, slideshows, video players)."""
    if not IS_WIN or not hwnd or is_shell_window(hwnd):
        return False
    if F.IsZoomed(hwnd):  # maximized (incl. auto-hide taskbar) is a normal window
        return False
    style = F.GetWindowLongPtrW(hwnd, -16)  # GWL_STYLE
    if (style & 0x00C00000) == 0x00C00000:  # WS_CAPTION → regular framed window
        return False
    with per_monitor_dpi():
        r = window_rect(hwnd)
        mon = F.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not mon or not F.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return False
    m = mi.rcMonitor
    return bool(r and r[0] <= m.left and r[1] <= m.top and r[2] >= m.right and r[3] >= m.bottom)


# ------------------------------------------------- 2.6: DWM cloak (pre-rendered popup)
DWMWA_CLOAK, DWMWA_CLOAKED = 13, 14


def set_cloak(hwnd, on: bool) -> bool:
    """Hide/show a window at the DWM level. The window stays 'visible' for Win32 and keeps
    rendering, so un-cloaking shows the already drawn content in a single frame."""
    if not IS_WIN or not hwnd or not F.DwmSetWindowAttribute:
        return False
    v = ctypes.c_int(1 if on else 0)
    return F.DwmSetWindowAttribute(hwnd, DWMWA_CLOAK, ctypes.byref(v), 4) == 0


def is_cloaked(hwnd) -> bool:
    if not IS_WIN or not hwnd or not F.DwmGetWindowAttribute:
        return False
    v = ctypes.c_int(0)
    if F.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), 4) != 0:
        return False
    return bool(v.value)


def send_message_timeout(hwnd, msg: int, wparam: int = 0, lparam=0, timeout_ms: int = 80) -> int | None:
    """SendMessageTimeout with SMTO_ABORTIFHUNG; None on timeout / failure."""
    if not IS_WIN or not hwnd:
        return None
    res = ULONG_PTR(0)
    ok = F.SendMessageTimeoutW(hwnd, msg, wparam, lparam, 0x0002, timeout_ms, ctypes.byref(res))
    return int(res.value) if ok else None


def ime_state(hwnd, tid: int) -> dict:
    """Input-method state of another thread: primary language of its keyboard layout and
    whether the IME is switched on (IMC_GETOPENSTATUS via the default IME window)."""
    out = {"lang": 0, "open": None}
    if not IS_WIN or not hwnd:
        return out
    try:
        hkl = F.GetKeyboardLayout(tid) or 0
        out["lang"] = int(hkl if isinstance(hkl, int) else getattr(hkl, "value", 0) or 0) & 0x3FF
        ime = F.ImmGetDefaultIMEWnd(hwnd) if F.ImmGetDefaultIMEWnd else None
        if ime:
            r = send_message_timeout(ime, 0x0283, 0x0005, 0, 60)  # WM_IME_CONTROL, IMC_GETOPENSTATUS
            if r is not None:
                out["open"] = bool(r)
    except Exception:
        pass
    return out


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


# everyone in the session (also a non-elevated instance when the running one is elevated)
# may open/signal our instance objects; medium integrity label so "no write up" does not apply
_SHARED_SDDL = "D:(A;;GA;;;WD)(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NW;;;ME)"


def shared_security_attributes():
    """SECURITY_ATTRIBUTES (kept alive by the caller) or None when unavailable."""
    if not IS_WIN or not F.ConvertStringSecurityDescriptorToSecurityDescriptorW:
        return None
    psd = ctypes.c_void_p()
    if not F.ConvertStringSecurityDescriptorToSecurityDescriptorW(_SHARED_SDDL, 1, ctypes.byref(psd), None):
        return None
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = psd
    sa.bInheritHandle = False
    return sa
