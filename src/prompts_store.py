"""Prompt library: Role › Category › Prompt tree + lifecycle metadata.

File: <data>/prompts.json
  {"format": "promptbuilder-prompts", "version": 5,
   "roles": [...], "categories": [...], "prompts": [...]}

Prompt fields: id / name / body / role_id / category_id / order / builtin / system /
tags / keywords / summary / favorite / pinned / archived / archived_at /
test_values / last_values / use_count / created_at / updated_at / last_used_at.

Built-in developer suite is merged from data/builtins.json (add-missing by id; refresh fields; prune obsolete builtins).
User prompts migrate into 我的提示 › 未分类. 2.x templates.json migration kept.
"""
from __future__ import annotations
import json, re, shutil, threading, uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_io import read_json_safe, snapshot, write_json_atomic
from paths import backups_dir, data_dir, examples_path, legacy_dir, prompts_path
from library_model import (
    DEFAULT_CAT_ID, DEFAULT_ROLE_ID, VERSION as TREE_VERSION,
    _clean_category, _clean_role, default_user_category, default_user_role,
    ensure_defaults, load_builtins, sort_categories, sort_roles, tree_payload,
    _new_cat_id, _new_role_id,
)
from prompt_syntax import normalize_newlines, preview_line, variables_of

FORMAT = "promptbuilder-prompts"
VERSION = 6  # 2.10 flat Role › Prompt; categories storage-only
# 2.x heuristic: these names used a multi-line box; migration makes it explicit (:多行)
_V2_MULTILINE = {"代码", "原文", "需求", "背景", "方案", "关键信息", "问题", "约束",
                 "内容", "描述", "正文", "输入", "文本"}
_V2_VAR = re.compile(r"\{\{\s*([^}|]+?)(?:\s*\|\s*([^}]*?))?\s*\}\}")
_LEGACY_FILES = ("templates.json", "last_values.json", "history.json", "favorites.json",
                 "snippets.json", "stats.json", "workspaces.json")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    write_json_atomic(path, data, backup=True)


MAX_IMPORT_BYTES = 20 * 1024 * 1024


def _str_map(d: Any) -> dict:
    if not isinstance(d, dict):
        return {}
    return {str(k): normalize_newlines(str(v)) for k, v in d.items() if v is not None}


def convert_v2_body(body: str) -> str:
    """Rewrite a 2.x template body to 2.4 syntax without changing its rendered output."""
    def repl(m: re.Match) -> str:
        name = (m.group(1) or "").strip()
        default = m.group(2)
        if ":" in name or "：" in name:
            safe = name.replace(":", "-").replace("：", "-")  # ':' now starts a control type
        elif name in _V2_MULTILINE:
            safe = f"{name}:多行"
        else:
            safe = name
        return "{{" + safe + ("" if default is None else "|" + default.strip()) + "}}"
    return _V2_VAR.sub(repl, body or "")


def _int(v: Any) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def _new_id() -> str:
    return f"p-{uuid.uuid4().hex[:10]}"


def _norm_keywords(raw) -> list[str]:
    """Search aliases; allow slightly longer than tags; cap 16."""
    if isinstance(raw, str):
        raw = [t.strip() for t in re.split(r"[,，;；|/\\]", raw) if t.strip()]
    if not isinstance(raw, list):
        return []
    seen, out = set(), []
    for t in raw:
        s = str(t or "").strip()[:32]
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 16:
            break
    return out


def _norm_tags(raw) -> list[str]:
    if isinstance(raw, str):
        raw = [t.strip() for t in re.split(r"[,，;；|/\\]", raw) if t.strip()]
    if not isinstance(raw, list):
        return []
    seen, out = set(), []
    for t in raw:
        s = str(t or "").strip()[:48]
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 12:
            break
    return out



CASES_CAP = 10


def _clean_cases(raw) -> list[dict]:
    """Per-prompt golden cases (2.12.8). Cap CASES_CAP."""
    if not isinstance(raw, list):
        return []
    out = []
    for it in raw[:CASES_CAP]:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("id") or "").strip()
        if not cid:
            import uuid
            cid = f"case-{uuid.uuid4().hex[:10]}"
        name = (str(it.get("name") or "用例").strip() or "用例")[:60]
        vals = it.get("values") if isinstance(it.get("values"), dict) else {}
        values = {str(k)[:80]: str(v if v is not None else "")[:4000] for k, v in vals.items()}
        expect = str(it.get("expect") or "")[:8000]
        notes = str(it.get("notes") or "")[:500]
        last_run = it.get("last_run") if isinstance(it.get("last_run"), dict) else {}
        lr = {}
        if last_run:
            lr = {
                "at": str(last_run.get("at") or "")[:40],
                "output": str(last_run.get("output") or "")[:8000],
                "ok": bool(last_run.get("ok")),
                "match": str(last_run.get("match") or "")[:40],
                "error": str(last_run.get("error") or "")[:500],
            }
        out.append({"id": cid, "name": name, "values": values, "expect": expect, "notes": notes, "last_run": lr})
    return out


def _clean_prompt(item: dict) -> dict:
    now = _now()
    # Prefer top-level tags/favorite/pinned; fall back to legacy 2.x metadata once.
    legacy = item.get("legacy") if isinstance(item.get("legacy"), dict) else {}
    tags = item.get("tags")
    if tags in (None, [], ""):
        tags = legacy.get("tags")
    favorite = item.get("favorite")
    if favorite is None:
        favorite = legacy.get("favorite")
    pinned = item.get("pinned")
    if pinned is None:
        pinned = legacy.get("pinned")
    archived = bool(item.get("archived"))
    role_id = str(item.get("role_id") or DEFAULT_ROLE_ID).strip() or DEFAULT_ROLE_ID
    category_id = str(item.get("category_id") or DEFAULT_CAT_ID).strip() or DEFAULT_CAT_ID
    out = {
        "id": str(item.get("id") or _new_id()),
        "name": (str(item.get("name") or "未命名提示词").strip() or "未命名提示词")[:120],
        "body": normalize_newlines(str(item.get("body") or "")),
        "role_id": role_id,
        "category_id": category_id,
        "order": _int(item.get("order")),
        "builtin": bool(item.get("builtin")),
        "system": bool(item.get("system") or item.get("builtin")),
        "tags": _norm_tags(tags),
        "keywords": _norm_keywords(item.get("keywords")),
        "summary": (str(item.get("summary") or "").strip())[:120],
        "favorite": bool(favorite),
        "pinned": bool(pinned),
        "archived": archived,
        "archived_at": (item.get("archived_at") or now) if archived else "",
        "test_values": _str_map(item.get("test_values")),
        "last_values": _str_map(item.get("last_values")),
        "use_count": _int(item.get("use_count")),
        "created_at": item.get("created_at") or now,
        "updated_at": item.get("updated_at") or now,
        "last_used_at": item.get("last_used_at") or "",
        "last_ai_run": item.get("last_ai_run") if isinstance(item.get("last_ai_run"), dict) else {},
        "cases": _clean_cases(item.get("cases")),
    }
    if legacy:
        out["legacy"] = legacy  # preserved 2.x metadata, not shown in UI
    return out


def prompts_from_v2(templates: list, last_values: dict | None = None,
                    keep_builtin_unused: bool = False) -> list[dict]:
    """Convert 2.x templates. Pure built-ins the user never used are skipped."""
    last_values = last_values or {}
    out = []
    ordered = sorted(
        [t for t in templates if isinstance(t, dict)],
        key=lambda t: (0 if t.get("pinned") else 1, 0 if t.get("favorite") else 1,
                       int(t.get("sort_order") or 0), str(t.get("name") or "")),
    )
    for t in ordered:
        tid = str(t.get("id") or "")
        used = bool(last_values.get(tid)) or bool(t.get("favorite")) or bool(t.get("pinned"))
        if t.get("builtin") and not used and not keep_builtin_unused:
            continue
        legacy = {k: t.get(k) for k in ("category", "folder", "tags", "description",
                                        "version_note", "favorite", "pinned", "builtin")
                  if t.get(k) not in (None, "", [], False)}
        legacy["source_id"] = tid
        out.append(_clean_prompt({
            "id": tid if tid and not t.get("builtin") else _new_id(),
            "name": t.get("name"),
            "body": convert_v2_body(t.get("template") or t.get("body") or ""),
            "test_values": last_values.get(tid) or {},
            "created_at": t.get("created_at"),
            "updated_at": t.get("updated_at"),
            "tags": t.get("tags") or [],
            "favorite": bool(t.get("favorite")),
            "pinned": bool(t.get("pinned")),
            "legacy": legacy,
        }))
    return out


def load_examples() -> list[dict]:
    raw = _read_json(examples_path(), [])
    return [_clean_prompt(x) for x in raw if isinstance(x, dict)]


class PromptStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._prompts: list[dict] = []
        self._roles: list[dict] = []
        self._categories: list[dict] = []
        self.migration: dict = {}
        self.recovered: str = ""   # "" | "bak" | "snapshot:<file>" | "default" (data could not be read)
        self.listeners: list = []  # called (no args) after every successful save
        self.rev = 0               # bumped on every save (cheap "did anything change?" check)
        self.load()

    # --- persistence -------------------------------------------------
    def load(self) -> None:
        with self._lock:
            path = prompts_path()
            roles_raw, cats_raw = [], []
            if path.exists():
                raw, source = read_json_safe(path, None, backups_dir())
                if source != "main":
                    self.recovered = source
                if raw is None:
                    raw = {"prompts": []}
                if isinstance(raw, dict):
                    roles_raw = list(raw.get("roles") or [])
                    cats_raw = list(raw.get("categories") or [])
                    items = raw.get("prompts")
                else:
                    items = raw
                seen: set[str] = set()
                self._prompts = []
                for x in (items or []):
                    if not isinstance(x, dict):
                        continue
                    c = _clean_prompt(x)
                    if c["id"] in seen:
                        c["id"] = _new_id()
                    seen.add(c["id"])
                    self._prompts.append(c)
                self._roles = []
                for i, r in enumerate(roles_raw):
                    cr = _clean_role(r, fallback_order=i * 10)
                    if cr and cr["id"] not in {x["id"] for x in self._roles}:
                        self._roles.append(cr)
                self._categories = []
                for i, c in enumerate(cats_raw):
                    cc = _clean_category(c, fallback_order=i * 10)
                    if cc and cc["id"] not in {x["id"] for x in self._categories}:
                        self._categories.append(cc)
                if self.recovered:
                    pass  # save after tree normalize
                else:
                    try:
                        snapshot(path, backups_dir())
                    except Exception:
                        pass
            else:
                self._prompts = self._migrate_or_seed()
                self._roles, self._categories = [], []
            self._roles, self._categories = ensure_defaults(self._roles, self._categories)
            self._normalize_prompt_placement()
            self._merge_builtins()
            self._normalize_prompt_placement()
            self._flatten_categories_to_tags_once()
            self._seed_examples_once()
            # always persist current schema after load/migrate
            self.save()

    def _migrate_or_seed(self) -> list[dict]:
        d = data_dir()
        old = d / "templates.json"
        if not old.exists():
            self.migration = {"migrated": False}
            return []
        raw = _read_json(old, None)
        if raw is None:
            # unreadable 2.x file: do not migrate and do not move anything — the user's
            # files stay exactly where they are
            self.migration = {"migrated": False, "error": "templates.json 无法读取，已原样保留"}
            return []
        templates = raw if isinstance(raw, list) else list((raw or {}).get("templates") or [])
        last_values = _read_json(d / "last_values.json", {})
        prompts = prompts_from_v2(templates, last_values if isinstance(last_values, dict) else {})
        # move legacy files aside (kept, not deleted)
        # write the new library first; only then move legacy files aside
        _write_json(prompts_path(), {"format": FORMAT, "version": VERSION, "prompts": prompts})
        moved = []
        ld = legacy_dir()
        ld.mkdir(parents=True, exist_ok=True)
        for name in _LEGACY_FILES:
            src = d / name
            if src.exists():
                try:
                    shutil.move(str(src), str(ld / name))
                    moved.append(name)
                except Exception:
                    pass
        self.migration = {
            "migrated": True,
            "from_templates": len(templates),
            "imported": len(prompts),
            "skipped_unused_builtins": len([t for t in templates if isinstance(t, dict) and t.get("builtin")])
                                       - len([p for p in prompts if (p.get("legacy") or {}).get("builtin")]),
            "legacy_dir": str(ld),
            "moved": moved,
        }
        return prompts

    def _flatten_categories_to_tags_once(self) -> None:
        """2.10 migration: fold former category names into tags (user prompts)."""
        from settings_store import load_settings, save_settings
        s = load_settings()
        if s.get("flat_v210"):
            return
        cat_names = {c["id"]: c.get("name") or "" for c in self._categories}
        skip = {"未分类", "默认", ""}
        for p in self._prompts:
            if p.get("builtin"):
                continue
            cname = cat_names.get(p.get("category_id") or "", "")
            if cname in skip:
                continue
            tags = list(p.get("tags") or [])
            if cname not in tags:
                tags.insert(0, cname)
                p["tags"] = tags[:12]
        save_settings({"flat_v210": True})

    def _seed_examples_once(self) -> None:
        from settings_store import load_settings, save_settings
        s = load_settings()
        if s.get("examples_seeded"):
            return
        have = {p["id"] for p in self._prompts}
        for ex in load_examples():
            if ex["id"] not in have:
                self._prompts.append(ex)
        self.save()
        save_settings({"examples_seeded": True})

    def _storage_cat_id(self, role_id: str) -> str:
        """Return (creating if needed) a hidden storage category under role for schema compat."""
        for c in self._categories:
            if c.get("role_id") == role_id:
                return c["id"]
        # prefer deterministic id for builtins
        rid_short = role_id[5:] if role_id.startswith("role-") else role_id
        cid = DEFAULT_CAT_ID if role_id == DEFAULT_ROLE_ID else f"cat-{rid_short}-default"
        if any(c["id"] == cid for c in self._categories):
            # id exists but under other role — mint new
            from library_model import _new_cat_id
            cid = _new_cat_id()
        cat = _clean_category({
            "id": cid,
            "role_id": role_id,
            "name": "未分类" if role_id == DEFAULT_ROLE_ID else "默认",
            "order": 0,
            "builtin": role_id != DEFAULT_ROLE_ID,
            "system": True,
        })
        # _clean_category may regenerate id — force ours if helper allows
        cat["id"] = cid
        cat["role_id"] = role_id
        self._categories.append(cat)
        return cid

    def _normalize_prompt_placement(self) -> None:
        """Role is primary (2.10). Category kept only as storage pointer under that role."""
        role_ids = {r["id"] for r in self._roles}
        cat_by_id = {c["id"]: c for c in self._categories}
        for p in self._prompts:
            rid = p.get("role_id") or ""
            if rid not in role_ids:
                cat = cat_by_id.get(p.get("category_id") or "")
                if cat and cat.get("role_id") in role_ids:
                    rid = cat["role_id"]
                else:
                    rid = DEFAULT_ROLE_ID
                p["role_id"] = rid
            cid = p.get("category_id") or ""
            cat = cat_by_id.get(cid)
            if not cat or cat.get("role_id") != p["role_id"]:
                p["category_id"] = self._storage_cat_id(p["role_id"])
                cat_by_id = {c["id"]: c for c in self._categories}

    def _merge_builtins(self) -> None:
        """Add missing builtins; refresh name/keywords/summary/body/tags; prune obsolete builtins."""
        from settings_store import load_settings, save_settings
        bun = load_builtins()
        have_r = {r["id"] for r in self._roles}
        have_c = {c["id"] for c in self._categories}
        by_p = {p["id"]: i for i, p in enumerate(self._prompts)}
        hidden = set(load_settings().get("hidden_builtins") or [])
        added = 0
        refreshed = 0
        for r in bun["roles"]:
            if r["id"] not in have_r:
                self._roles.append(r)
                have_r.add(r["id"])
                added += 1
        for c in bun["categories"]:
            if c["id"] not in have_c and c["role_id"] in have_r:
                self._categories.append(c)
                have_c.add(c["id"])
                added += 1
        for raw in bun["prompts"]:
            if not isinstance(raw, dict):
                continue
            pid = str(raw.get("id") or "")
            if not pid or pid in hidden:
                continue
            if pid in by_p:
                # 2.11.1+: keep builtins in sync with seed (titles/keywords/summary/body)
                i = by_p[pid]
                cur = self._prompts[i]
                if not cur.get("builtin"):
                    continue
                seed = _clean_prompt({**raw, "builtin": True, "system": True,
                                      "id": pid,
                                      "role_id": raw.get("role_id") or cur.get("role_id"),
                                      "category_id": cur.get("category_id"),
                                      "favorite": cur.get("favorite"),
                                      "pinned": cur.get("pinned"),
                                      "use_count": cur.get("use_count"),
                                      "last_used_at": cur.get("last_used_at"),
                                      "test_values": cur.get("test_values"),
                                      "last_values": cur.get("last_values"),
                                      "cases": cur.get("cases"),
                                      "created_at": cur.get("created_at"),
                                      "archived": cur.get("archived"),
                                      "archived_at": cur.get("archived_at")})
                # preserve placement
                seed["category_id"] = cur.get("category_id") or seed.get("category_id")
                seed["role_id"] = cur.get("role_id") or seed.get("role_id")
                seed["order"] = cur.get("order") if cur.get("order") is not None else seed.get("order")
                if (cur.get("name") != seed.get("name")
                        or cur.get("body") != seed.get("body")
                        or list(cur.get("keywords") or []) != list(seed.get("keywords") or [])
                        or (cur.get("summary") or "") != (seed.get("summary") or "")
                        or list(cur.get("tags") or []) != list(seed.get("tags") or [])):
                    self._prompts[i] = seed
                    refreshed += 1
                continue
            item = _clean_prompt({**raw, "builtin": True, "system": True})
            if item.get("role_id") not in have_r:
                continue
            cid = item.get("category_id") or ""
            if cid not in have_c or next((c for c in self._categories if c["id"] == cid), {}).get("role_id") != item["role_id"]:
                cid = self._storage_cat_id(item["role_id"])
                have_c.add(cid)
            item["category_id"] = cid
            self._prompts.append(item)
            by_p[pid] = len(self._prompts) - 1
            added += 1
        # 2.12.1: drop builtins no longer in seed (e.g. 2.9.0 step-split siblings).
        # User-custom prompts (builtin=False) are never removed.
        seed_ids = {str(p.get("id") or "") for p in bun["prompts"] if isinstance(p, dict) and p.get("id")}
        kept: list[dict] = []
        pruned = 0
        for p in self._prompts:
            if p.get("builtin") and str(p.get("id") or "") not in seed_ids:
                pruned += 1
                continue
            kept.append(p)
        if pruned:
            self._prompts = kept
            by_p = {p["id"]: i for i, p in enumerate(self._prompts)}

        if added or refreshed or pruned:
            save_settings({"builtins_seeded": True})
            # load() always persists after merge

    def save(self) -> None:
        with self._lock:
            _write_json(prompts_path(), {
                "format": FORMAT, "version": VERSION, "updated_at": _now(),
                "roles": self._roles, "categories": self._categories,
                "prompts": self._prompts,
            })
            self.rev += 1
        for fn in list(getattr(self, "listeners", [])):
            try:
                fn()
            except Exception:
                pass

    # --- queries -----------------------------------------------------
    def _summary(self, p: dict) -> dict:
        vars_ = variables_of(p["body"])
        return {
            "id": p["id"], "name": p["name"], "updated_at": p["updated_at"],
            "last_used_at": p.get("last_used_at") or "",
            "created_at": p.get("created_at") or "",
            "use_count": int(p.get("use_count") or 0),
            "var_count": len(vars_),
            "required_count": sum(1 for v in vars_ if v["required"]),
            "preview": (str(p.get("summary") or "").strip() or preview_line(p["body"])),
            "tags": list(p.get("tags") or []),
            "keywords": list(p.get("keywords") or []),
            "summary": str(p.get("summary") or ""),
            "favorite": bool(p.get("favorite")),
            "pinned": bool(p.get("pinned")),
            "archived": bool(p.get("archived")),
            "archived_at": p.get("archived_at") or "",
            "role_id": p.get("role_id") or DEFAULT_ROLE_ID,
            "category_id": p.get("category_id") or DEFAULT_CAT_ID,
            "order": int(p.get("order") or 0),
            "builtin": bool(p.get("builtin")),
            "system": bool(p.get("system") or p.get("builtin")),
        }

    def list(self, query: str = "", *, include_archived: bool = False,
             archived_only: bool = False, tag: str | None = None,
             favorites_only: bool = False, sort: str = "recent") -> list[dict]:
        """Public library rows.

        sort: recent | used | name | updated | created
        Multi-word query: every term must match name, body, tags, keywords, or summary (AND).
        """
        with self._lock:
            items = list(self._prompts)
        if archived_only:
            items = [p for p in items if p.get("archived")]
        elif not include_archived:
            items = [p for p in items if not p.get("archived")]
        if favorites_only:
            items = [p for p in items if p.get("favorite")]
        if tag:
            tl = tag.strip().casefold()
            items = [p for p in items if any(t.casefold() == tl for t in (p.get("tags") or []))]
        terms = [t for t in (query or "").strip().casefold().split() if t]
        if terms:
            with self._lock:
                role_names = {r["id"]: r["name"] for r in self._roles}
                cat_names = {c["id"]: c["name"] for c in self._categories}
            def matches(p):
                blob = (
                    f"{p.get('name') or ''} {p.get('body') or ''} "
                    f"{' '.join(p.get('tags') or [])} "
                    f"{' '.join(p.get('keywords') or [])} "
                    f"{p.get('summary') or ''} "
                    f"{role_names.get(p.get('role_id') or '', '')} "
                    f"{cat_names.get(p.get('category_id') or '', '')}"
                ).casefold()
                return all(t in blob for t in terms)
            items = [p for p in items if matches(p)]
            # name hits float first within the chosen sort
            items.sort(key=lambda p: (0 if any(t in (p.get("name") or "").casefold() for t in terms) else 1))
        items = self._sort_items(items, sort)
        return [self._summary(p) for p in items]

    @staticmethod
    def _sort_items(items: list[dict], sort: str) -> list[dict]:
        sort = (sort or "recent").lower()

        def k_recent(p):
            used = p.get("last_used_at") or ""
            upd = p.get("updated_at") or ""
            return (1 if p.get("pinned") else 0, 1 if used else 0, used or upd, upd)

        def k_used(p):
            return (1 if p.get("pinned") else 0, int(p.get("use_count") or 0),
                    p.get("last_used_at") or "", p.get("updated_at") or "")

        def k_name(p):
            return (0 if p.get("pinned") else 1, (p.get("name") or "").casefold())

        def k_updated(p):
            return (1 if p.get("pinned") else 0, p.get("updated_at") or "")

        def k_created(p):
            return (1 if p.get("pinned") else 0, p.get("created_at") or "")

        reverse = sort != "name"
        key = {"used": k_used, "name": k_name, "updated": k_updated,
               "created": k_created}.get(sort, k_recent)
        # stable: apply secondary sort after any query name-boost already applied
        items.sort(key=key, reverse=reverse)
        return items

    def quick_items(self, recent: int = 3) -> list[dict]:
        """Popup order: pinned → favorites → recent uses → most-used → library order.
        Archived prompts are excluded from the popup.
        """
        with self._lock:
            items = [(i, p) for i, p in enumerate(self._prompts) if not p.get("archived")]
        pinned = [ip for ip in items if ip[1].get("pinned")]
        pinned_ids = {p["id"] for _, p in pinned}
        fav = [ip for ip in items if ip[1].get("favorite") and ip[1]["id"] not in pinned_ids]
        fav_ids = {p["id"] for _, p in fav} | pinned_ids
        used = sorted([ip for ip in items if ip[1].get("last_used_at") and ip[1]["id"] not in fav_ids],
                      key=lambda ip: ip[1]["last_used_at"], reverse=True)[:recent]
        used_ids = {p["id"] for _, p in used} | fav_ids
        rest = [ip for ip in items if ip[1]["id"] not in used_ids]
        rest.sort(key=lambda ip: (-int(ip[1].get("use_count") or 0), ip[0]))
        with self._lock:
            role_by_id = {r["id"]: r for r in self._roles}
            cat_by_id = {c["id"]: c for c in self._categories}
        out = []
        for _, p in pinned + fav + used + rest:
            s = self._summary(p)
            s["recent"] = bool(p.get("last_used_at")) and p["id"] in {x["id"] for _, x in used}
            s["use_count"] = int(p.get("use_count") or 0)
            s["section"] = ("pinned" if p.get("pinned") else
                            "favorite" if p.get("favorite") else
                            "recent" if s["recent"] else "library")
            rid = s.get("role_id") or ""
            cid = s.get("category_id") or ""
            role = role_by_id.get(rid) or {}
            cat = cat_by_id.get(cid) or {}
            s["role_name"] = role.get("name") or ""
            s["category_name"] = cat.get("name") or ""
            s["role_order"] = int(role.get("order") if role.get("order") is not None else 9999)
            s["category_order"] = int(cat.get("order") if cat.get("order") is not None else 9999)
            out.append(s)
        return out

    def get(self, pid: str) -> dict | None:
        with self._lock:
            for p in self._prompts:
                if p["id"] == pid:
                    return deepcopy(p)
        return None

    # --- mutations ---------------------------------------------------
    def _unique_name(self, base: str) -> str:
        names = {p["name"] for p in self._prompts}
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    def create(self, name: str = "", body: str | None = None,
               role_id: str | None = None, category_id: str | None = None,
               keywords=None, summary: str = "") -> dict:
        with self._lock:
            rid = role_id or DEFAULT_ROLE_ID
            if not any(r["id"] == rid for r in self._roles):
                rid = DEFAULT_ROLE_ID
            cid = category_id or ""
            cat = next((c for c in self._categories if c["id"] == cid and c.get("role_id") == rid), None)
            if not cat:
                cid = self._storage_cat_id(rid)
            else:
                cid = cat["id"]
            item = _clean_prompt({
                "name": self._unique_name((name or "新提示词").strip() or "新提示词"),
                "body": body if body is not None else "请根据以下内容完成任务：\n\n{{内容:多行}}\n\n要求：{{要求|简洁、准确}}\n",
                "role_id": rid, "category_id": cid, "builtin": False, "system": False,
                "keywords": keywords or [],
                "summary": summary or "",
            })
            self._prompts.insert(0, item)
            self.save()
            return deepcopy(item)

    def update(self, pid: str, patch: dict) -> dict | None:
        with self._lock:
            for i, p in enumerate(self._prompts):
                if p["id"] != pid:
                    continue
                p = deepcopy(p)
                content_touch = ("name" in patch or "body" in patch)
                # Built-in content is copy-on-write: editing name/body clones to a user prompt.
                if p.get("builtin") and content_touch and not patch.get("_force_builtin"):
                    clone = _clean_prompt({
                        "name": self._unique_name((str(patch.get("name") or p["name"])).strip() or p["name"]),
                        "body": normalize_newlines(str(patch["body"])) if "body" in patch else p["body"],
                        "role_id": p.get("role_id"), "category_id": p.get("category_id"),
                        "tags": patch.get("tags") if "tags" in patch else p.get("tags"),
                        "keywords": patch.get("keywords") if "keywords" in patch else p.get("keywords"),
                        "summary": patch.get("summary") if "summary" in patch else p.get("summary"),
                        "favorite": p.get("favorite"), "pinned": False,
                        "test_values": p.get("test_values") or {},
                        "cases": p.get("cases") or [],
                        "builtin": False, "system": False,
                    })
                    self._prompts.insert(i + 1, clone)
                    self.save()
                    clone["_copied_from_builtin"] = True
                    return deepcopy(clone)
                if "name" in patch:
                    p["name"] = (str(patch["name"] or "").strip() or p["name"])[:120]
                if "body" in patch:
                    p["body"] = normalize_newlines(str(patch["body"] or ""))
                if "test_values" in patch:
                    p["test_values"] = {k: v for k, v in _str_map(patch["test_values"]).items()
                                        if v.strip() != ""}
                if "tags" in patch:
                    p["tags"] = _norm_tags(patch.get("tags"))
                if "keywords" in patch:
                    p["keywords"] = _norm_keywords(patch.get("keywords"))
                if "summary" in patch:
                    p["summary"] = (str(patch.get("summary") or "").strip())[:120]
                if "last_ai_run" in patch:
                    raw = patch.get("last_ai_run")
                    p["last_ai_run"] = raw if isinstance(raw, dict) else {}
                if "cases" in patch:
                    p["cases"] = _clean_cases(patch.get("cases"))
                if "favorite" in patch:
                    p["favorite"] = bool(patch.get("favorite"))
                if "pinned" in patch:
                    p["pinned"] = bool(patch.get("pinned"))
                if "order" in patch:
                    p["order"] = _int(patch.get("order"))
                if "category_id" in patch or "role_id" in patch:
                    cid = str(patch.get("category_id") or p.get("category_id") or DEFAULT_CAT_ID)
                    cat = next((c for c in self._categories if c["id"] == cid), None)
                    if cat:
                        p["category_id"] = cat["id"]
                        p["role_id"] = cat["role_id"]
                    else:
                        p["category_id"] = DEFAULT_CAT_ID
                        p["role_id"] = DEFAULT_ROLE_ID
                p["updated_at"] = _now()
                self._prompts[i] = p
                self.save()
                return deepcopy(p)
        return None

    def touch_used(self, pid: str, values: dict | None = None) -> None:
        """Record a use (quick-pick insert / copy): recency, count and last-used values."""
        with self._lock:
            for p in self._prompts:
                if p["id"] == pid:
                    p["last_used_at"] = _now()
                    p["use_count"] = int(p.get("use_count") or 0) + 1
                    if values is not None:
                        names = {v["name"] for v in variables_of(p["body"])}
                        p["last_values"] = {k: v for k, v in _str_map(values).items()
                                            if k in names and v.strip() != ""}
                    self.save()
                    return

    def duplicate(self, pid: str) -> dict | None:
        with self._lock:
            for i, p in enumerate(self._prompts):
                if p["id"] != pid:
                    continue
                item = _clean_prompt({
                    "name": self._unique_name(f"{p['name']} 副本"),
                    "body": p["body"],
                    "test_values": p.get("test_values") or {},
                    "tags": list(p.get("tags") or []),
                    "keywords": list(p.get("keywords") or []),
                    "summary": p.get("summary") or "",
                    "favorite": bool(p.get("favorite")),
                    "role_id": p.get("role_id"), "category_id": p.get("category_id"),
                    "builtin": False, "system": False,
                })
                self._prompts.insert(i + 1, item)
                self.save()
                return deepcopy(item)
        return None

    def delete(self, pid: str) -> bool:
        return self.take(pid) is not None

    def take(self, pid: str) -> dict | None:
        """Delete and return {"prompt": ..., "index": ...} so the UI can offer "撤销".
        Built-in prompts are hidden (not removed from disk seed) via settings.hidden_builtins.
        """
        with self._lock:
            for i, p in enumerate(self._prompts):
                if p["id"] != pid:
                    continue
                if p.get("builtin"):
                    from settings_store import load_settings, save_settings
                    s = load_settings()
                    hidden = list(s.get("hidden_builtins") or [])
                    if pid not in hidden:
                        hidden.append(pid)
                        save_settings({"hidden_builtins": hidden})
                    del self._prompts[i]
                    self.save()
                    return {"prompt": deepcopy(p), "index": i, "hidden_builtin": True}
                del self._prompts[i]
                self.save()
                return {"prompt": deepcopy(p), "index": i}
            return None

    def restore(self, prompt: dict, index: int = 0) -> dict | None:
        """Undo a delete: put the prompt back at its old position (same id if still free)."""
        if not isinstance(prompt, dict):
            return None
        with self._lock:
            item = _clean_prompt(prompt)
            if any(p["id"] == item["id"] for p in self._prompts):
                item["id"] = _new_id()
            # if this was a hidden builtin, un-hide it
            if item.get("builtin"):
                from settings_store import load_settings, save_settings
                st = load_settings()
                hidden = [x for x in (st.get("hidden_builtins") or []) if x != item["id"]]
                if len(hidden) != len(st.get("hidden_builtins") or []):
                    save_settings({"hidden_builtins": hidden})
            idx = max(0, min(int(index or 0), len(self._prompts)))
            self._prompts.insert(idx, item)
            self.save()
            return deepcopy(item)

    # --- organize / maintain (2.7 lifecycle) -------------------------
    def set_flags(self, pid: str, *, favorite: bool | None = None,
                  pinned: bool | None = None) -> dict | None:
        patch = {}
        if favorite is not None:
            patch["favorite"] = favorite
        if pinned is not None:
            patch["pinned"] = pinned
        return self.update(pid, patch) if patch else self.get(pid)

    def set_tags(self, pid: str, tags) -> dict | None:
        return self.update(pid, {"tags": tags})

    def set_keywords(self, pid: str, keywords) -> dict | None:
        return self.update(pid, {"keywords": keywords})

    def all_tags(self) -> list[str]:
        with self._lock:
            items = [p for p in self._prompts if not p.get("archived")]
        counts: dict[str, int] = {}
        order: list[str] = []
        for p in items:
            for t in p.get("tags") or []:
                if t not in counts:
                    order.append(t)
                counts[t] = counts.get(t, 0) + 1
        order.sort(key=lambda t: (-counts[t], t.casefold()))
        return order

    def archive(self, pid: str) -> dict | None:
        with self._lock:
            for i, p in enumerate(self._prompts):
                if p["id"] != pid:
                    continue
                p = deepcopy(p)
                p["archived"] = True
                p["archived_at"] = _now()
                p["pinned"] = False  # archived items leave the popup
                p["updated_at"] = _now()
                self._prompts[i] = p
                self.save()
                return deepcopy(p)
        return None

    def unarchive(self, pid: str) -> dict | None:
        with self._lock:
            for i, p in enumerate(self._prompts):
                if p["id"] != pid:
                    continue
                p = deepcopy(p)
                p["archived"] = False
                p["archived_at"] = ""
                p["updated_at"] = _now()
                self._prompts[i] = p
                self.save()
                return deepcopy(p)
        return None

    def batch_archive(self, ids: list[str]) -> dict:
        ok = 0
        for pid in ids or []:
            if self.archive(str(pid)):
                ok += 1
        return {"ok": True, "count": ok}

    def batch_delete(self, ids: list[str]) -> dict:
        """Permanent delete. Returns taken items so the UI can offer a single undo."""
        taken = []
        for pid in ids or []:
            t = self.take(str(pid))
            if t:
                taken.append(t)
        return {"ok": True, "count": len(taken), "taken": taken}

    def restore_many(self, taken: list) -> int:
        n = 0
        for t in taken or []:
            if not isinstance(t, dict):
                continue
            if self.restore(t.get("prompt"), t.get("index") or 0):
                n += 1
        return n

    def health_check(self) -> dict:
        """Lightweight diagnostics for broken / empty / unused prompts."""
        with self._lock:
            items = list(self._prompts)
        empty, unused, archived, broken = [], [], [], []
        for p in items:
            if p.get("archived"):
                archived.append(p["id"])
            body = (p.get("body") or "").strip()
            if not body:
                empty.append({"id": p["id"], "name": p["name"], "reason": "empty_body"})
            elif not (p.get("use_count") or 0) and not (p.get("last_used_at") or ""):
                unused.append({"id": p["id"], "name": p["name"]})
            # broken: variable syntax that analyze would flag — keep light, just unmatched braces
            if body.count("{{") != body.count("}}"):
                broken.append({"id": p["id"], "name": p["name"], "reason": "unbalanced_braces"})
        return {
            "total": len(items),
            "active": len(items) - len(archived),
            "archived": len(archived),
            "empty": empty,
            "unused": unused[:50],
            "broken": broken,
            "favorites": sum(1 for p in items if p.get("favorite") and not p.get("archived")),
            "tagged": sum(1 for p in items if (p.get("tags") or []) and not p.get("archived")),
        }

    def local_stats(self) -> dict:
        """Observe: uses this week, top prompts, empty unused hint. Local only."""
        from datetime import timedelta
        with self._lock:
            items = [p for p in self._prompts if not p.get("archived")]
        now = datetime.now(timezone.utc).astimezone()
        week_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")
        uses_week = 0
        # We only store cumulative use_count + last_used_at; approximate "this week"
        # as prompts whose last_used_at is within 7 days (count 1 each) plus a
        # weighted hint from use_count for recently used ones.
        recent = []
        for p in items:
            lu = p.get("last_used_at") or ""
            if lu and lu >= week_ago:
                uses_week += max(1, min(int(p.get("use_count") or 1), 20))
                recent.append(p)
        top = sorted(items, key=lambda p: (int(p.get("use_count") or 0),
                                           p.get("last_used_at") or ""), reverse=True)[:8]
        unused = [p for p in items if not (p.get("use_count") or 0)
                  and not (p.get("last_used_at") or "") and (p.get("body") or "").strip()]
        empty = [p for p in items if not (p.get("body") or "").strip()]
        return {
            "total": len(items),
            "uses_this_week_est": uses_week,
            "active_this_week": len(recent),
            "top_prompts": [{"id": p["id"], "name": p["name"],
                             "use_count": int(p.get("use_count") or 0),
                             "last_used_at": p.get("last_used_at") or ""} for p in top
                            if int(p.get("use_count") or 0) > 0],
            "unused_count": len(unused),
            "empty_count": len(empty),
            "unused_hint": [{"id": p["id"], "name": p["name"]} for p in unused[:8]],
        }

    # --- import / export --------------------------------------------
    def export_payload(self) -> dict:
        with self._lock:
            return {"format": FORMAT, "version": VERSION, "exported_at": _now(),
                    "roles": deepcopy(self._roles),
                    "categories": deepcopy(self._categories),
                    "prompts": deepcopy(self._prompts)}

    def import_payload(self, raw: Any) -> dict:
        """Merge import. Accepts 2.4 library, 2.x template export, 2.x full backup, or a list."""
        incoming: list[dict] = []
        kind = "unknown"
        if isinstance(raw, dict) and isinstance(raw.get("prompts"), list):
            incoming = [_clean_prompt(x) for x in raw["prompts"] if isinstance(x, dict)]
            kind = "2.4"
        elif isinstance(raw, dict) and isinstance(raw.get("templates"), list):
            lv = raw.get("last_values") if isinstance(raw.get("last_values"), dict) else {}
            incoming = prompts_from_v2(raw["templates"], lv, keep_builtin_unused=True)
            kind = "2.x"
        elif isinstance(raw, dict) and isinstance(raw.get("body"), str):
            incoming = [_clean_prompt(raw)]
            kind = "2.4"
        elif isinstance(raw, list):
            if raw and isinstance(raw[0], dict) and "template" in raw[0]:
                incoming = prompts_from_v2(raw, {}, keep_builtin_unused=True)
                kind = "2.x"
            else:
                incoming = [_clean_prompt(x) for x in raw if isinstance(x, dict)]
                kind = "2.4"
        else:
            return {"ok": False, "error": "无法识别的文件格式"}
        added = replaced = 0
        try:  # safety net: always keep a snapshot of the library before merging
            snapshot(prompts_path(), backups_dir(), keep=10, min_interval_s=0)
        except Exception:
            pass
        with self._lock:
            # merge roles / categories if the payload carries a v5 tree
            if isinstance(raw, dict):
                for r in raw.get("roles") or []:
                    cr = _clean_role(r)
                    if not cr:
                        continue
                    existing = next((x for x in self._roles if x["id"] == cr["id"]), None)
                    if existing:
                        if not existing.get("system"):
                            existing.update({k: cr[k] for k in ("name", "icon", "description", "order")})
                    else:
                        self._roles.append(cr)
                for c in raw.get("categories") or []:
                    cc = _clean_category(c)
                    if not cc:
                        continue
                    existing = next((x for x in self._categories if x["id"] == cc["id"]), None)
                    if existing:
                        if not existing.get("system"):
                            existing.update({k: cc[k] for k in ("name", "role_id", "order")})
                    else:
                        self._categories.append(cc)
                self._roles, self._categories = ensure_defaults(self._roles, self._categories)
            idx = {p["id"]: i for i, p in enumerate(self._prompts)}
            for item in incoming:
                if item["id"] in idx:
                    self._prompts[idx[item["id"]]] = item
                    replaced += 1
                else:
                    idx[item["id"]] = len(self._prompts)
                    self._prompts.append(item)
                    added += 1
            self._normalize_prompt_placement()
            self.save()
        return {"ok": True, "kind": kind, "added": added, "replaced": replaced}

    def import_markdown(self, path: str) -> dict:
        p = Path(path)
        if p.stat().st_size > MAX_IMPORT_BYTES:
            raise ValueError("文件过大（超过 20 MB）")
        data = p.read_bytes()
        for enc in ("utf-8-sig", "utf-16", "gb18030"):
            try:
                body = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("无法识别文件编码（请另存为 UTF-8）")
        if "\x00" in body:
            raise ValueError("不是文本文件")
        return self.create(name=p.stem, body=normalize_newlines(body))

    # --- Role › Category tree (2.8) ----------------------------------
    def tree(self, query: str = "", *, include_archived: bool = False) -> dict:
        """Full navigation payload for the sidebar."""
        summaries = self.list(query=query, include_archived=include_archived, sort="name")
        # list() already filters; re-attach order/placement from live prompts for sorting
        with self._lock:
            by_id = {p["id"]: p for p in self._prompts}
            roles = deepcopy(self._roles)
            cats = deepcopy(self._categories)
        for s in summaries:
            live = by_id.get(s["id"])
            if live:
                s["order"] = int(live.get("order") or 0)
                s["role_id"] = live.get("role_id") or DEFAULT_ROLE_ID
                s["category_id"] = live.get("category_id") or DEFAULT_CAT_ID
        from settings_store import load_settings
        hidden = set(load_settings().get("hidden_builtins") or [])
        return tree_payload(roles, cats, summaries, hidden_builtins=hidden)

    def roles(self) -> list[dict]:
        with self._lock:
            return deepcopy(sort_roles(self._roles))

    def categories(self, role_id: str | None = None) -> list[dict]:
        with self._lock:
            cats = list(self._categories)
        if role_id:
            cats = [c for c in cats if c["role_id"] == role_id]
        return deepcopy(sort_categories(cats))

    def create_role(self, name: str = "", icon: str = "folder", description: str = "") -> dict:
        with self._lock:
            orders = [int(r.get("order") or 0) for r in self._roles] or [0]
            item = _clean_role({
                "name": (name or "新角色").strip() or "新角色",
                "icon": icon or "folder",
                "description": description or "",
                "order": max(orders) + 10,
                "builtin": False, "system": False,
            })
            self._roles.append(item)
            # auto-create an empty default category under the new role
            cat = _clean_category({
                "role_id": item["id"], "name": "未分类",
                "order": 0, "builtin": False, "system": False,
            })
            self._categories.append(cat)
            self.save()
            return deepcopy(item)

    def rename_role(self, role_id: str, name: str) -> dict | None:
        with self._lock:
            for r in self._roles:
                if r["id"] != role_id:
                    continue
                if r.get("builtin"):
                    return None  # developer suite roles stay fixed
                r["name"] = (str(name or "").strip() or r["name"])[:40]
                self.save()
                return deepcopy(r)
        return None

    def update_role(self, role_id: str, patch: dict | None = None) -> dict | None:
        """Update writable role fields. system_prompt is writable for all roles (incl. builtins)."""
        patch = patch or {}
        with self._lock:
            for r in self._roles:
                if r["id"] != role_id:
                    continue
                if "name" in patch and not r.get("builtin"):
                    r["name"] = (str(patch.get("name") or "").strip() or r["name"])[:40]
                if "description" in patch and not r.get("builtin"):
                    r["description"] = (str(patch.get("description") or "").strip())[:200]
                if "icon" in patch and not r.get("builtin"):
                    r["icon"] = (str(patch.get("icon") or "folder").strip() or "folder")[:32]
                if "system_prompt" in patch or "persona" in patch:
                    sp = patch.get("system_prompt")
                    if sp is None:
                        sp = patch.get("persona")
                    r["system_prompt"] = str(sp if sp is not None else "")[:8000]
                self.save()
                return deepcopy(r)
        return None

    def set_role_system_prompt(self, role_id: str, text: str) -> dict | None:
        return self.update_role(role_id, {"system_prompt": text or ""})

    def get_role(self, role_id: str) -> dict | None:
        with self._lock:
            for r in self._roles:
                if r["id"] == role_id:
                    return deepcopy(r)
        return None

    def delete_role(self, role_id: str, *, move_to: str | None = None) -> dict:
        """Delete a user role. System/builtin roles cannot be removed.
        Prompts+categories move to move_to (default: 我的提示/未分类).
        """
        with self._lock:
            role = next((r for r in self._roles if r["id"] == role_id), None)
            if not role:
                return {"ok": False, "error": "角色不存在"}
            if role.get("system") or role.get("builtin"):
                return {"ok": False, "error": "系统/内置角色不可删除"}
            target_role = move_to or DEFAULT_ROLE_ID
            if not any(r["id"] == target_role for r in self._roles):
                target_role = DEFAULT_ROLE_ID
            # move categories' prompts to default uncategorized, drop categories
            moved = 0
            for p in self._prompts:
                if p.get("role_id") == role_id:
                    p["role_id"] = DEFAULT_ROLE_ID
                    p["category_id"] = DEFAULT_CAT_ID
                    moved += 1
            self._categories = [c for c in self._categories if c["role_id"] != role_id]
            self._roles = [r for r in self._roles if r["id"] != role_id]
            self.save()
            return {"ok": True, "moved": moved}

    def reorder_roles(self, role_ids: list[str]) -> dict:
        with self._lock:
            by_id = {r["id"]: r for r in self._roles}
            for i, rid in enumerate(role_ids or []):
                if rid in by_id:
                    by_id[rid]["order"] = (i + 1) * 10
            self.save()
            return {"ok": True}

    def create_category(self, role_id: str, name: str = "") -> dict | None:
        with self._lock:
            if not any(r["id"] == role_id for r in self._roles):
                return None
            role = next(r for r in self._roles if r["id"] == role_id)
            if role.get("builtin") and role_id != DEFAULT_ROLE_ID:
                # allow user categories under builtin roles? Yes — useful for personalizing
                pass
            orders = [int(c.get("order") or 0) for c in self._categories if c["role_id"] == role_id] or [0]
            item = _clean_category({
                "role_id": role_id,
                "name": (name or "新分类").strip() or "新分类",
                "order": max(orders) + 10,
                "builtin": False, "system": False,
            })
            self._categories.append(item)
            self.save()
            return deepcopy(item)

    def rename_category(self, cat_id: str, name: str) -> dict | None:
        with self._lock:
            for c in self._categories:
                if c["id"] != cat_id:
                    continue
                if c.get("builtin"):
                    return None  # built-in categories: use 复制后编辑 on prompts instead
                c["name"] = (str(name or "").strip() or c["name"])[:40]
                self.save()
                return deepcopy(c)
        return None

    def delete_category(self, cat_id: str) -> dict:
        with self._lock:
            cat = next((c for c in self._categories if c["id"] == cat_id), None)
            if not cat:
                return {"ok": False, "error": "分类不存在"}
            if cat.get("system") or cat.get("builtin") or cat_id == DEFAULT_CAT_ID:
                return {"ok": False, "error": "系统/内置分类不可删除"}
            moved = 0
            for p in self._prompts:
                if p.get("category_id") == cat_id:
                    p["category_id"] = DEFAULT_CAT_ID
                    p["role_id"] = DEFAULT_ROLE_ID
                    moved += 1
            self._categories = [c for c in self._categories if c["id"] != cat_id]
            self.save()
            return {"ok": True, "moved": moved}

    def reorder_categories(self, role_id: str, cat_ids: list[str]) -> dict:
        with self._lock:
            by_id = {c["id"]: c for c in self._categories if c["role_id"] == role_id}
            for i, cid in enumerate(cat_ids or []):
                if cid in by_id:
                    by_id[cid]["order"] = (i + 1) * 10
            self.save()
            return {"ok": True}

    def move_prompt(self, pid: str, category_id: str) -> dict | None:
        return self.update(pid, {"category_id": category_id})

    def move_prompt_to_role(self, pid: str, role_id: str) -> dict | None:
        """Move a user prompt into a role (sets role_id + that role's storage category).
        Built-in / system prompts cannot be moved — copy first."""
        role_id = str(role_id or "").strip()
        if not role_id:
            return None
        with self._lock:
            p = next((x for x in self._prompts if x["id"] == pid), None)
            if not p:
                return None
            if p.get("builtin") or p.get("system"):
                return None
            if not any(r["id"] == role_id for r in self._roles):
                return None
            if p.get("role_id") == role_id:
                return deepcopy(p)
            cid = self._storage_cat_id(role_id)
            p["category_id"] = cid
            p["role_id"] = role_id
            p["updated_at"] = _now()
            self.save()
            return deepcopy(p)

    def breadcrumb(self, pid: str) -> dict:
        p = self.get(pid)
        if not p:
            return {"role": None, "category": None}
        with self._lock:
            role = next((r for r in self._roles if r["id"] == p.get("role_id")), None)
            cat = next((c for c in self._categories if c["id"] == p.get("category_id")), None)
        return {
            "role": deepcopy(role) if role else None,
            # 2.10: category no longer user-facing; keep field for compat but UI ignores it
            "category": None,
        }

    def copy_builtin(self, pid: str) -> dict | None:
        """Explicit「复制后编辑」 for a builtin prompt."""
        with self._lock:
            for i, p in enumerate(self._prompts):
                if p["id"] != pid:
                    continue
                item = _clean_prompt({
                    "name": self._unique_name(f"{p['name']}（可编辑）"),
                    "body": p["body"],
                    "test_values": p.get("test_values") or {},
                    "tags": list(p.get("tags") or []),
                    "keywords": list(p.get("keywords") or []),
                    "summary": p.get("summary") or "",
                    "role_id": p.get("role_id"), "category_id": p.get("category_id"),
                    "builtin": False, "system": False,
                })
                self._prompts.insert(i + 1, item)
                self.save()
                return deepcopy(item)
        return None
