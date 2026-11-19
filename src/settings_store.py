"""Minimal settings: theme, quick-pick ("//" trigger) options, autostart, admin mode.

Obsolete 2.x keys (triggers, density, language, animations, ...) are pruned on load.
"""
from __future__ import annotations
import json
from atomic_io import read_json_safe, write_json_atomic
from paths import settings_path

ONBOARDING_VERSION = 1           # bump to show the first-run guide again after big changes

DEFAULTS = {
    "theme": "system",            # system | dark | light
    "quick_enabled": True,        # type "//" in any input box → quick-pick popup
    "quick_follow": "caret",      # caret (fallback mouse) | mouse
    "quick_preview": True,        # show one-line preview in popup list
    "quick_skip_fullscreen": True,  # never open the popup in fullscreen apps (games, slideshows)
    "quick_exclude": "",          # comma separated exe names where the popup never opens
    "autostart": False,
    "admin_mode": False,          # start elevated through a scheduled task (see elevation.py)
    "onboarding": 0,              # last first-run guide version the user finished/skipped
    "settings_rev": 0,            # one-time upgrades of stored values (see _upgrade)
    "examples_seeded": False,
    "library_sort": "recent",     # recent | used | name | updated | created
    "starters_dismissed": False,  # user closed the starter-templates strip
    "history_enabled": True,      # record fill/insert history locally
    "builtins_seeded": False,     # developer suite was merged at least once
    "hidden_builtins": [],        # builtin prompt ids the user removed (not re-seeded)
    "ai_profiles": [],           # [{id,name,preset,kind,base_url,api_key_enc,default_model,models}]
    "ai_default_profile": "",    # profile id used by AI workshop
    "apply_role_system_prompt": True,  # prepend role system_prompt when copy/AI/preview
}
SETTINGS_REV = 1


def _normalize(data: dict) -> dict:
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in data:
            out[k] = data[k]
    if out["theme"] not in ("system", "dark", "light"):
        out["theme"] = "system"
    if out["quick_follow"] not in ("caret", "mouse"):
        out["quick_follow"] = "caret"
    for b in ("quick_enabled", "quick_preview", "quick_skip_fullscreen", "autostart", "admin_mode",
              "examples_seeded", "starters_dismissed", "history_enabled", "apply_role_system_prompt"):
        out[b] = bool(out[b])
    if out.get("library_sort") not in ("recent", "used", "name", "updated", "created"):
        out["library_sort"] = "recent"
    for n in ("onboarding", "settings_rev"):
        try:
            out[n] = max(0, int(out[n]))
        except (TypeError, ValueError):
            out[n] = 0
    out["quick_exclude"] = normalize_exclude(out.get("quick_exclude"))
    hb = out.get("hidden_builtins") or []
    if not isinstance(hb, list):
        hb = []
    out["hidden_builtins"] = [str(x) for x in hb if str(x).strip()][:500]
    out["builtins_seeded"] = bool(out.get("builtins_seeded"))
    profiles = out.get("ai_profiles") or []
    if not isinstance(profiles, list):
        profiles = []
    clean = []
    for raw in profiles[:30]:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("id") or "").strip()[:64]
        if not pid:
            continue
        clean.append({
            "id": pid,
            "name": str(raw.get("name") or raw.get("preset") or "未命名")[:80],
            "preset": str(raw.get("preset") or "custom")[:40],
            "kind": str(raw.get("kind") or "openai")[:20],
            "base_url": str(raw.get("base_url") or "")[:300],
            "api_key_enc": str(raw.get("api_key_enc") or "")[:4000],
            "default_model": str(raw.get("default_model") or "")[:120],
            "models": [str(m)[:120] for m in (raw.get("models") or []) if str(m).strip()][:40],
        })
    out["ai_profiles"] = clean
    ad = str(out.get("ai_default_profile") or "")
    if ad and ad not in {x["id"] for x in clean}:
        ad = clean[0]["id"] if clean else ""
    out["ai_default_profile"] = ad
    return out


def normalize_exclude(v) -> str:
    """'Code.exe; mstsc ,  game.EXE' -> 'code.exe, mstsc.exe, game.exe'"""
    if isinstance(v, (list, tuple)):
        v = ",".join(map(str, v))
    parts = []
    for p in str(v or "").replace("；", ",").replace(";", ",").replace("，", ",").replace("\n", ",").split(","):
        p = p.strip().strip('"').lower()
        if not p:
            continue
        p = p.replace("/", "\\").rsplit("\\", 1)[-1]
        if not p.endswith(".exe"):
            p += ".exe"
        if p not in parts:
            parts.append(p)
    return ", ".join(parts[:50])


def exclude_set(settings: dict) -> frozenset:
    return frozenset(x.strip() for x in str(settings.get("quick_exclude") or "").split(",") if x.strip())


_cache: dict = {"mtime": None, "data": None}


def _write(data: dict) -> None:
    write_json_atomic(settings_path(), data, backup=True)
    _cache["mtime"], _cache["data"] = None, None


def load_settings() -> dict:
    """Cached by file mtime: the quick-pick hot path calls this on every open."""
    p = settings_path()
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        mtime = None
    if mtime is not None and _cache["mtime"] == mtime and _cache["data"] is not None:
        return dict(_cache["data"])
    raw, _src = read_json_safe(p, {})
    if not isinstance(raw, dict):
        raw = {}
    out = _normalize(raw)
    upgraded = _upgrade(raw, out)
    if upgraded or (raw and set(raw.keys()) != set(out.keys())):
        try:
            _write(out)  # prune obsolete keys from older versions
        except Exception:
            pass
    try:
        _cache["mtime"], _cache["data"] = p.stat().st_mtime_ns, dict(out)
    except OSError:
        pass
    return out


def _upgrade(raw: dict, out: dict) -> bool:
    """One-time value upgrades. 2.6: the 2.5 default theme was a hard-coded "dark" — switch
    it to "system" once (users can still pick dark/light; the choice is kept afterwards)."""
    if not raw or int(out.get("settings_rev") or 0) >= SETTINGS_REV:
        if not raw:
            out["settings_rev"] = SETTINGS_REV
        return False
    if raw.get("theme") in (None, "dark"):
        out["theme"] = "system"
    out["settings_rev"] = SETTINGS_REV
    return True


def save_settings(patch: dict) -> dict:
    cur = load_settings()
    cur.update({k: v for k, v in (patch or {}).items() if k in DEFAULTS})
    cur = _normalize(cur)
    _write(cur)
    return cur
