"""App paths for source and frozen (PyInstaller 6 onedir) runs."""
from __future__ import annotations
import os, sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)  # type: ignore[attr-defined]
        internal = app_root() / "_internal"
        return internal if internal.exists() else app_root()
    return app_root()


def data_dir() -> Path:
    override = os.environ.get("PROMPTBUILDER_DATA_DIR")
    if override:
        d = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        d = base / "PromptBuilder"
    else:
        d = Path.home() / ".prompt_builder"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _first_existing(*candidates: Path) -> Path:
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def examples_path() -> Path:
    return _first_existing(
        resource_dir() / "data" / "examples.json",
        app_root() / "data" / "examples.json",
    )


def builtins_path() -> Path:
    """Bundled developer role library (roles / categories / prompts)."""
    return _first_existing(
        resource_dir() / "data" / "builtins.json",
        app_root() / "data" / "builtins.json",
    )


def prompts_path() -> Path:
    return data_dir() / "prompts.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def legacy_dir() -> Path:
    """Where 2.x data files are moved after migration (kept, never deleted)."""
    return data_dir() / "legacy-2.x"


def backups_dir() -> Path:
    """Rolling snapshots of prompts.json (see atomic_io.snapshot)."""
    return data_dir() / "backups"


def revisions_path() -> Path:
    """Per-prompt content snapshots (see revisions_store)."""
    return data_dir() / "revisions.json"


def history_path() -> Path:
    """Recent fill / insert history (local only)."""
    return data_dir() / "fill_history.json"


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def web_dir() -> Path:
    return _first_existing(resource_dir() / "web", app_root() / "web")


def icon_path() -> Path:
    return _first_existing(resource_dir() / "assets" / "icon.png", app_root() / "assets" / "icon.png")


# ------------------------------------------------------------ WebUI pages
# Every page a window can load. Keep in sync with AppController.run (enforced by tests).
PAGES = {"main": "index.html", "quick": "quick.html"}


class PageMissing(FileNotFoundError):
    """A WebUI page is not where the frozen bundle should have it."""


def page_path(page: str) -> Path:
    """Absolute path of a WebUI page, resolved from the bundle (sys._MEIPASS / exe dir),
    never from the current working directory."""
    name = PAGES[page]
    p = (web_dir() / name).resolve()
    if not p.is_file():
        raise PageMissing(f"界面文件缺失：{p}")
    return p


def page_url(page: str) -> str:
    """file:// URL for a page. Deliberately no query string or fragment: WebView2 on Windows
    percent-encodes '?' and '#' in file URLs (pythonnet → Uri → Source), so 'index.html?x=y'
    becomes a request for a file literally named 'index.html%3Fx=y' (the 2.6.0 blank-window
    bug). Pass state through the js_api / localStorage instead."""
    url = page_path(page).as_uri()
    if "?" in url or "#" in url:  # a '#' or '?' in the install path itself
        raise PageMissing(f"安装路径含有 ? 或 #，WebView2 无法加载：{url}")
    return url


def all_web_refs() -> dict:
    """{page: [missing relative asset paths]} for css/js referenced by each page."""
    import re
    out = {}
    for page, name in PAGES.items():
        p = web_dir() / name
        if not p.is_file():
            out[page] = [name]
            continue
        html = p.read_text(encoding="utf-8")
        refs = re.findall(r'<(?:link|script)\b[^>]*?(?:href|src)="([^"#?:]+)"', html)
        out[page] = [r for r in refs if not (p.parent / r).is_file()]
    return out
