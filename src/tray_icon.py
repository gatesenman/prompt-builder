"""System tray icon: open the main window, pause the "//" trigger, quit; notifications."""
from __future__ import annotations
import threading
from typing import Callable
from paths import icon_path

TOOLTIP = "提示词 Builder · 输入 // 唤醒浮框"


class TrayApp:
    def __init__(self, on_show: Callable[[], None], on_quit: Callable[[], None],
                 is_enabled: Callable[[], bool] | None = None,
                 on_toggle: Callable[[bool], None] | None = None,
                 admin: bool = False):
        self.on_show = on_show
        self.on_quit = on_quit
        self.is_enabled = is_enabled or (lambda: True)
        self.on_toggle = on_toggle
        self.admin = admin
        self._icon = None

    def start(self) -> None:
        def run():
            try:
                import pystray
                from PIL import Image
                path = icon_path()
                image = Image.open(path) if path.exists() else Image.new("RGB", (64, 64), (37, 99, 235))
                items = [pystray.MenuItem("打开提示词 Builder", lambda: self.on_show(), default=True)]
                if self.on_toggle:
                    items.append(pystray.MenuItem(
                        "暂停 // 唤醒", lambda: self.on_toggle(not self.is_enabled()),
                        checked=lambda _item: not self.is_enabled()))
                items += [pystray.Menu.SEPARATOR, pystray.MenuItem("退出", lambda: self._quit())]
                tip = TOOLTIP + ("（管理员）" if self.admin else "")
                self._icon = pystray.Icon("PromptBuilder", image, tip, pystray.Menu(*items))
                self._icon.run()
            except Exception as e:
                print(f"tray failed: {e}")
        threading.Thread(target=run, name="pb-tray", daemon=True).start()

    def refresh(self) -> None:
        try:
            if self._icon:
                self._icon.update_menu()
        except Exception:
            pass

    def notify(self, msg: str, title: str = "提示词 Builder") -> None:
        try:
            if self._icon:
                self._icon.notify(msg, title)
        except Exception:
            pass

    def _quit(self):
        self.stop()
        self.on_quit()

    def stop(self):
        try:
            if self._icon:
                self._icon.stop()
        except Exception:
            pass
