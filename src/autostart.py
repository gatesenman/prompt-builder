"""Windows Run-key autostart helper."""
from __future__ import annotations
import os, sys
from pathlib import Path

RUN_VALUE = "PromptBuilder"

def _exe_path() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --tray'
    # Dev: launch via python run.py
    root = Path(__file__).resolve().parent.parent
    return f'"{sys.executable}" "{root / "run.py"}" --tray'

def is_autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            try:
                winreg.QueryValueEx(k, RUN_VALUE)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False

def set_autostart(enable: bool) -> dict:
    if sys.platform != "win32":
        return {"ok": False, "error": "仅 Windows 支持开机自启"}
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        ) as k:
            if enable:
                exe = _exe_path()
                # frozen path may already be quoted via spaces — wrap if needed
                if not exe.startswith('"') and " " in exe:
                    exe = f'"{exe}"'
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, exe)
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return {"ok": True, "enabled": bool(enable)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
