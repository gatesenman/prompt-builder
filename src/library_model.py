"""Role › Prompt tree helpers (library schema v6; categories kept for storage/migration only)."""
from __future__ import annotations
import json, uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from paths import builtins_path

FORMAT_LIBRARY = "promptbuilder-prompts"
VERSION = 6

DEFAULT_ROLE_ID = "role-mine"
DEFAULT_CAT_ID = "cat-mine-uncat"


def _new_role_id() -> str:
    return f"role-{uuid.uuid4().hex[:10]}"


def _new_cat_id() -> str:
    return f"cat-{uuid.uuid4().hex[:10]}"


def default_user_role() -> dict:
    return {
        "id": DEFAULT_ROLE_ID,
        "name": "我的提示",
        "icon": "folder",
        "description": "你创建与导入的提示词",
        "builtin": False,
        "system": True,  # cannot delete; can rename
        "order": 0,
        "system_prompt": "",
    }


def default_user_category() -> dict:
    return {
        "id": DEFAULT_CAT_ID,
        "role_id": DEFAULT_ROLE_ID,
        "name": "未分类",
        "builtin": False,
        "system": True,
        "order": 0,
    }


def _clean_role(item: dict, *, fallback_order: int = 0) -> dict | None:
    if not isinstance(item, dict):
        return None
    name = (str(item.get("name") or "").strip() or "未命名角色")[:40]
    # system_prompt / persona: role-level system message (2.12.8); migrate missing → ""
    sp = item.get("system_prompt")
    if sp is None:
        sp = item.get("persona")
    system_prompt = str(sp if sp is not None else "")[:8000]
    return {
        "id": str(item.get("id") or _new_role_id()),
        "name": name,
        "icon": (str(item.get("icon") or "folder").strip() or "folder")[:32],
        "description": (str(item.get("description") or "").strip())[:200],
        "builtin": bool(item.get("builtin")),
        "system": bool(item.get("system") or item.get("builtin")),
        "order": int(item.get("order") if item.get("order") is not None else fallback_order),
        "system_prompt": system_prompt,
    }


def _clean_category(item: dict, *, fallback_order: int = 0) -> dict | None:
    if not isinstance(item, dict):
        return None
    rid = str(item.get("role_id") or "").strip()
    if not rid:
        return None
    name = (str(item.get("name") or "").strip() or "未命名分类")[:40]
    return {
        "id": str(item.get("id") or _new_cat_id()),
        "role_id": rid,
        "name": name,
        "builtin": bool(item.get("builtin")),
        "system": bool(item.get("system") or item.get("builtin")),
        "order": int(item.get("order") if item.get("order") is not None else fallback_order),
    }


def load_builtins() -> dict:
    """Load bundled developer suite. Returns {roles, categories, prompts}."""
    path = builtins_path()
    empty = {"roles": [], "categories": [], "prompts": []}
    try:
        if not path.is_file():
            return empty
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return empty
    if not isinstance(raw, dict):
        return empty
    roles, cats, prompts = [], [], []
    for i, r in enumerate(raw.get("roles") or []):
        c = _clean_role(r, fallback_order=(i + 1) * 10)
        if c:
            c["builtin"] = True
            c["system"] = True
            roles.append(c)
    for i, c in enumerate(raw.get("categories") or []):
        cc = _clean_category(c, fallback_order=(i + 1) * 10)
        if cc:
            cc["builtin"] = True
            cc["system"] = True
            cats.append(cc)
    for p in raw.get("prompts") or []:
        if isinstance(p, dict):
            prompts.append(p)  # cleaned later by store._clean_prompt
    return {"roles": roles, "categories": cats, "prompts": prompts}


def ensure_defaults(roles: list[dict], categories: list[dict]) -> tuple[list[dict], list[dict]]:
    """Guarantee 我的提示 › 未分类 exist."""
    roles = list(roles)
    categories = list(categories)
    if not any(r["id"] == DEFAULT_ROLE_ID for r in roles):
        roles.insert(0, default_user_role())
    else:
        # keep system flag on default role
        for r in roles:
            if r["id"] == DEFAULT_ROLE_ID:
                r["system"] = True
                break
    if not any(c["id"] == DEFAULT_CAT_ID for c in categories):
        categories.insert(0, default_user_category())
    else:
        for c in categories:
            if c["id"] == DEFAULT_CAT_ID:
                c["system"] = True
                c["role_id"] = DEFAULT_ROLE_ID
                break
    return roles, categories


def sort_roles(roles: list[dict]) -> list[dict]:
    return sorted(roles, key=lambda r: (int(r.get("order") or 0), (r.get("name") or "").casefold()))


def sort_categories(cats: list[dict]) -> list[dict]:
    return sorted(cats, key=lambda c: (int(c.get("order") or 0), (c.get("name") or "").casefold()))


def tree_payload(roles: list[dict], categories: list[dict], prompt_summaries: list[dict],
                 *, hidden_builtins: set[str] | None = None) -> dict:
    """Build UI tree: roles with prompts directly (flat). Categories ignored for nesting."""
    hidden = hidden_builtins or set()
    roles = sort_roles(roles)
    by_role: dict[str, list] = {r["id"]: [] for r in roles}
    for p in prompt_summaries:
        if p.get("id") in hidden:
            continue
        if p.get("archived"):
            continue
        rid = p.get("role_id") or DEFAULT_ROLE_ID
        if rid not in by_role:
            rid = DEFAULT_ROLE_ID
        by_role.setdefault(rid, []).append(p)

    out_roles = []
    for r in roles:
        items = by_role.get(r["id"], [])
        items = sorted(items, key=lambda p: (
            0 if p.get("pinned") else 1,
            0 if p.get("favorite") else 1,
            int(p.get("order") or 0),
            (p.get("name") or "").casefold(),
        ))
        out_roles.append({
            **{k: r.get(k, False if k in ("builtin", "system") else (0 if k == "order" else "")) for k in ("id", "name", "icon", "description", "builtin", "system", "order", "system_prompt")},
            "count": len(items),
            "prompts": items,
            "categories": [],  # 2.10 flat IA — kept empty for older UI guards
            "has_system_prompt": bool((r.get("system_prompt") or "").strip()),
        })
    return {"roles": out_roles, "flat": True}
