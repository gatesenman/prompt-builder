"""Admin mode (2.6): start PromptBuilder elevated through a scheduled task.

Windows blocks keyboard hooks / input injection from a normal process into windows that run
as administrator (UIPI). Running PromptBuilder itself elevated fixes that, but a UAC prompt on
every start would be unbearable. The standard solution:

  * once (one UAC prompt) an elevated helper registers the task
    "\\PromptBuilder\\ElevatedStart" — RunLevel HighestAvailable, interactive token of the
    current user, optional logon trigger (= autostart), no time limit, normal priority;
  * afterwards a normal launch (Start menu, shortcut, autostart) just runs that task
    (`schtasks /Run`) — Windows starts the elevated instance without asking again;
  * turning the option off deletes the task (from the elevated instance: no prompt).

The launcher passes its intent ("show" the window or stay in the "tray") through a small
file, because one task cannot take per-launch arguments.
"""
from __future__ import annotations
import ctypes, json, os, subprocess, sys, tempfile, time
from ctypes import wintypes
from pathlib import Path
from xml.sax.saxutils import escape

TASK_FOLDER = "PromptBuilder"
TASK_NAME = TASK_FOLDER + "\\ElevatedStart"
FROM_TASK_ARG = "--from-task"
REGISTER_ARG = "--pb-register-task"
UNREGISTER_ARG = "--pb-unregister-task"
CREATE_NO_WINDOW = 0x08000000
IS_WIN = sys.platform == "win32"


def supported() -> bool:
    return IS_WIN


# ------------------------------------------------------------ helpers
def _run(args: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW if IS_WIN else 0)
        out = (p.stdout or b"") + (p.stderr or b"")
        for enc in ("utf-8", "mbcs" if IS_WIN else "latin-1"):
            try:
                return p.returncode, out.decode(enc).strip()
            except Exception:
                continue
        return p.returncode, out.decode("latin-1", "replace").strip()
    except Exception as e:
        return -1, str(e)


def _schtasks(*args: str, timeout: float = 20) -> tuple[int, str]:
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "schtasks.exe")
    return _run([exe, *args], timeout)


def app_command() -> tuple[str, str, str]:
    """(command, arguments, working dir) that start this app from the task."""
    if getattr(sys, "frozen", False):
        exe = str(Path(sys.executable).resolve())
        return exe, FROM_TASK_ARG, str(Path(exe).parent)
    root = Path(__file__).resolve().parent.parent
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else py), f'"{root / "run.py"}" {FROM_TASK_ARG}', str(root)


def _user_id() -> str:
    dom, user = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    return f"{dom}\\{user}" if dom else user


def task_xml(autostart: bool, user: str | None = None, command: tuple | None = None) -> str:
    cmd, args, wd = command or app_command()
    user = escape(user or _user_id())
    trigger = (f"<LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger>"
               if autostart else "")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>提示词 Builder：以管理员身份启动（可在管理员窗口中输入 // 唤醒）。由 提示词 Builder 设置创建，关闭该选项即自动删除。</Description>
  </RegistrationInfo>
  <Triggers>{trigger}</Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>4</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(cmd)}</Command>
      <Arguments>{escape(args)}</Arguments>
      <WorkingDirectory>{escape(wd)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


# ------------------------------------------------------------ task operations
def task_exists() -> bool:
    if not IS_WIN:
        return False
    code, _ = _schtasks("/Query", "/TN", TASK_NAME, timeout=10)
    return code == 0


def register(autostart: bool) -> dict:
    """Create/replace the task. Needs an elevated process (helper or elevated app)."""
    if not IS_WIN:
        return {"ok": False, "error": "仅 Windows 支持"}
    fd, path = tempfile.mkstemp(prefix="pb-task-", suffix=".xml")
    os.close(fd)
    try:
        Path(path).write_text(task_xml(autostart), encoding="utf-16")
        code, out = _schtasks("/Create", "/TN", TASK_NAME, "/XML", path, "/F")
        return {"ok": code == 0, "error": "" if code == 0 else (out or f"schtasks 返回 {code}")}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def unregister() -> dict:
    if not IS_WIN:
        return {"ok": True}
    if not task_exists():
        return {"ok": True}
    code, out = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    return {"ok": code == 0, "error": "" if code == 0 else (out or f"schtasks 返回 {code}")}


def run_task() -> bool:
    code, _ = _schtasks("/Run", "/TN", TASK_NAME, timeout=10)
    return code == 0


# ------------------------------------------------------------ one-time UAC helper
class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def run_elevated_helper(arg: str, extra: str = "", timeout_s: float = 120) -> dict:
    """Start this app elevated with a helper argument (one UAC prompt) and wait for it."""
    if not IS_WIN:
        return {"ok": False, "error": "仅 Windows 支持"}
    cmd, base_args, wd = app_command()
    params = base_args.replace(FROM_TASK_ARG, "").strip()
    params = f"{params} {arg} {extra}".strip()
    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    sei.fMask = 0x00000040 | 0x00000100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    sei.lpVerb, sei.lpFile, sei.lpParameters, sei.lpDirectory = "runas", cmd, params, wd
    sei.nShow = 0
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.get_last_error()
        if err == 1223:  # ERROR_CANCELLED: the user declined the UAC prompt
            return {"ok": False, "cancelled": True, "error": "已取消（未授予管理员权限）"}
        return {"ok": False, "error": f"无法以管理员身份启动（错误 {err}）"}
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        if not sei.hProcess:
            return {"ok": False, "error": "管理员进程未启动"}
        k32.WaitForSingleObject(sei.hProcess, int(timeout_s * 1000))
        code = wintypes.DWORD(1)
        k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
        return {"ok": code.value == 0, "error": "" if code.value == 0 else f"计划任务创建失败（{code.value}）"}
    finally:
        if sei.hProcess:
            k32.CloseHandle(sei.hProcess)


def helper_main(argv: list[str]) -> int:
    """Entry of the elevated helper process (no window)."""
    if UNREGISTER_ARG in argv:
        return 0 if unregister().get("ok") else 2
    return 0 if register("--autostart" in argv).get("ok") else 2


# ------------------------------------------------------------ launch intent
def _intent_path() -> Path:
    from paths import data_dir
    return data_dir() / "launch-intent.json"


def write_intent(action: str) -> None:
    try:
        _intent_path().write_text(json.dumps({"action": action, "t": time.time()}), encoding="utf-8")
    except Exception:
        pass


def take_intent(max_age_s: float = 60) -> str:
    """'show' | 'tray' | '' (none or stale). The file is consumed."""
    p = _intent_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    finally:
        try:
            p.unlink()
        except OSError:
            pass
    if not isinstance(data, dict) or time.time() - float(data.get("t") or 0) > max_age_s:
        return ""
    return str(data.get("action") or "")


def restart_unelevated() -> bool:
    """From an elevated instance: start a normal (non-elevated) instance ~2 s later through
    Explorer (which runs with the user's normal token), so this instance can exit first."""
    if not IS_WIN:
        return False
    cmd, args, _ = app_command()
    target = cmd if getattr(sys, "frozen", False) else cmd  # dev: python run.py is not supported
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", f'ping -n 3 127.0.0.1 >nul & start "" explorer.exe "{target}"'],
            creationflags=CREATE_NO_WINDOW, close_fds=True)
        return True
    except Exception:
        return False
