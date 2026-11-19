"""Fallback Setup.exe when Inno Setup is unavailable.
Still presents welcome / path / shortcuts / uninstall / autostart — not a bare unzip.
Prefer installer/PromptBuilder.iss via ISCC when present.
"""
from __future__ import annotations
import ctypes, os, shutil, sys, zipfile, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

APP_NAME = "提示词 Builder"
APP_NAME_EN = "PromptBuilder"
APP_VERSION = "2.12.8"
EXE_NAME = "PromptBuilder.exe"

def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)

def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / APP_NAME_EN

def create_shortcut(link_path: Path, target: Path, work_dir: Path) -> None:
    import subprocess
    ps = f'''
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{str(link_path).replace('"','`"')}")
$sc.TargetPath = "{str(target).replace('"','`"')}"
$sc.WorkingDirectory = "{str(work_dir).replace('"','`"')}"
$sc.Description = "{APP_NAME}"
$sc.Save()
'''
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   check=False, capture_output=True)

def register_uninstall(app_path: Path) -> None:
    import winreg
    uninst = app_path / "Uninstall.bat"
    uninst.write_text(
        f'''@echo off
chcp 65001 >nul
echo 正在卸载 {APP_NAME}...
taskkill /IM {EXE_NAME} /F >nul 2>&1
set "APP={app_path}"
powershell -NoProfile -Command "Remove-Item -LiteralPath $env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME} -Recurse -Force -ErrorAction SilentlyContinue"
powershell -NoProfile -Command "Remove-Item -LiteralPath ([Environment]::GetFolderPath('Desktop') + '\\{APP_NAME}.lnk') -Force -ErrorAction SilentlyContinue"
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v PromptBuilder /f >nul 2>&1
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PromptBuilder" /f >nul 2>&1
cd /d "%TEMP%"
rmdir /s /q "%APP%"
echo 卸载完成。
pause
''',
        encoding="utf-8",
    )
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PromptBuilder"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, f"{APP_NAME} {APP_VERSION}")
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "Allen49 Thompson")
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, str(app_path))
        winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, str(app_path / EXE_NAME))
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, f'"{uninst}"')
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)

def set_autostart(exe: Path, enable: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, "PromptBuilder", 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(k, "PromptBuilder")
            except FileNotFoundError:
                pass

def signal_app_quit(timeout_s: float = 6.0) -> None:
    """Ask a running PromptBuilder to save and exit (works for an elevated instance too)."""
    try:
        import ctypes, time
        k = ctypes.windll.kernel32
        k.OpenEventW.restype = k.OpenMutexW.restype = ctypes.c_void_p
        h = k.OpenEventW(0x0002, False, "Local\\PromptBuilder.Quit")
        if not h:
            return
        k.SetEvent(ctypes.c_void_p(h)); k.CloseHandle(ctypes.c_void_p(h))
        end = time.time() + timeout_s
        while time.time() < end:
            m = k.OpenMutexW(0x00100000, False, "Local\\PromptBuilder.SingleInstance")
            if not m:
                return
            k.CloseHandle(ctypes.c_void_p(m)); time.sleep(0.15)
    except Exception:
        pass


def do_install(dest: Path, desktop: bool, autostart: bool) -> Path:
    payload = resource_path("payload", "app.zip")
    if not payload.exists():
        raise FileNotFoundError(f"安装包损坏：找不到应用数据\n{payload}")
    signal_app_quit()
    os.system(f'taskkill /IM {EXE_NAME} /F >nul 2>&1')
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload, "r") as zf:
        zf.extractall(dest)
    exe = dest / EXE_NAME
    if not exe.exists():
        nested = dest / "PromptBuilder" / EXE_NAME
        if nested.exists():
            nested_dir = dest / "PromptBuilder"
            for item in nested_dir.iterdir():
                shutil.move(str(item), str(dest / item.name))
            shutil.rmtree(nested_dir, ignore_errors=True)
            exe = dest / EXE_NAME
    if not exe.exists():
        raise FileNotFoundError("安装失败：未找到 PromptBuilder.exe")
    register_uninstall(dest)
    set_autostart(exe, autostart)
    programs = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs" / APP_NAME
    programs.mkdir(parents=True, exist_ok=True)
    create_shortcut(programs / f"{APP_NAME}.lnk", exe, dest)
    create_shortcut(programs / f"卸载 {APP_NAME}.lnk", dest / "Uninstall.bat", dest)
    if desktop:
        desk = Path.home() / "Desktop"
        if not desk.exists():
            desk = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        create_shortcut(desk / f"{APP_NAME}.lnk", exe, dest)
    (dest / "VERSION.txt").write_text(APP_VERSION + "\n", encoding="utf-8")
    return exe

class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION} 安装向导")
        self.geometry("560x400")
        self.resizable(False, False)
        self.dest = tk.StringVar(value=str(default_install_dir()))
        self.desktop = tk.BooleanVar(value=False)
        self.autostart = tk.BooleanVar(value=False)
        self.step = 0
        self._build()
        self._show(0)

    def _build(self):
        self.container = ttk.Frame(self, padding=20)
        self.container.pack(fill="both", expand=True)
        self.frames = []
        # 0 welcome
        f0 = ttk.Frame(self.container)
        ttk.Label(f0, text=f"欢迎安装 {APP_NAME}", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(f0, text=f"版本 {APP_VERSION} · WebUI 桌面版\n\n本向导将安装提示词 Builder，并写入开始菜单与卸载项。",
                  justify="left").pack(anchor="w", pady=12)
        self.frames.append(f0)
        # 1 path
        f1 = ttk.Frame(self.container)
        ttk.Label(f1, text="选择安装位置", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(f1, text="建议安装到 Local\\Programs（无需管理员权限）").pack(anchor="w", pady=8)
        row = ttk.Frame(f1); row.pack(fill="x", pady=8)
        ttk.Entry(row, textvariable=self.dest).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self._browse).pack(side="left", padx=6)
        self.frames.append(f1)
        # 2 components
        f2 = ttk.Frame(self.container)
        ttk.Label(f2, text="附加组件", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Checkbutton(f2, text="创建桌面快捷方式", variable=self.desktop).pack(anchor="w", pady=8)
        ttk.Checkbutton(f2, text="开机自动启动（托盘）", variable=self.autostart).pack(anchor="w", pady=4)
        ttk.Label(f2, text="将写入开始菜单、注册表卸载项，并生成 Uninstall.bat").pack(anchor="w", pady=16)
        self.frames.append(f2)
        # 3 finish placeholder
        f3 = ttk.Frame(self.container)
        self.finish_label = ttk.Label(f3, text="准备安装…", font=("Segoe UI", 12))
        self.finish_label.pack(anchor="w", pady=12)
        self.frames.append(f3)

        nav = ttk.Frame(self); nav.pack(fill="x", padx=20, pady=12)
        self.btn_back = ttk.Button(nav, text="上一步", command=self._back)
        self.btn_next = ttk.Button(nav, text="下一步", command=self._next)
        self.btn_cancel = ttk.Button(nav, text="取消", command=self.destroy)
        self.btn_cancel.pack(side="right")
        self.btn_next.pack(side="right", padx=6)
        self.btn_back.pack(side="right")

    def _browse(self):
        p = filedialog.askdirectory(initialdir=self.dest.get())
        if p:
            self.dest.set(p)

    def _show(self, i: int):
        for f in self.frames:
            f.pack_forget()
        self.step = i
        self.frames[i].pack(fill="both", expand=True)
        self.btn_back.configure(state=("normal" if i > 0 and i < 3 else "disabled"))
        if i == 2:
            self.btn_next.configure(text="安装")
        elif i == 3:
            self.btn_next.configure(text="完成")
            self.btn_back.configure(state="disabled")
            self.btn_cancel.configure(state="disabled")
        else:
            self.btn_next.configure(text="下一步")

    def _back(self):
        if self.step > 0:
            self._show(self.step - 1)

    def _next(self):
        if self.step < 2:
            self._show(self.step + 1)
            return
        if self.step == 2:
            try:
                exe = do_install(Path(self.dest.get()), self.desktop.get(), self.autostart.get())
                self._installed_exe = exe
                self.finish_label.configure(
                    text=f"安装完成！\n\n位置：{self.dest.get()}\n\n可从开始菜单打开「{APP_NAME}」。"
                )
                self._show(3)
            except Exception as e:
                messagebox.showerror(APP_NAME, str(e))
            return
        # finish
        if messagebox.askyesno(APP_NAME, "是否立即运行？"):
            try:
                os.startfile(str(self._installed_exe))
            except Exception:
                pass
        self.destroy()

def main() -> int:
    if sys.platform != "win32":
        print("仅支持 Windows")
        return 1
    # Prefer silent if --silent
    if "--silent" in sys.argv:
        try:
            do_install(default_install_dir(), False, False)
            return 0
        except Exception as e:
            print(e)
            return 1
    app = Wizard()
    app.mainloop()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
