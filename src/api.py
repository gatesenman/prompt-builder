"""JavaScript bridge for the main window — PromptBuilder 2.12.8 (role system prompt · lint · diff · cases)."""
from __future__ import annotations
import json, os, re, shutil, zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from paths import backups_dir, data_dir, history_path, prompts_path, revisions_path, settings_path
from prompt_syntax import analyze, sample_values, variables_of
from prompts_store import PromptStore
from settings_store import load_settings, save_settings

APP_VERSION = "2.12.8"

# Starter templates the user can dismiss (Markdown + variables only — not a wizard).
STARTERS = [
    {
        "id": "starter-rewrite",
        "name": "润色改写",
        "body": (
            "请将以下内容润色为{{风格|专业、简洁}}的中文，保留原意，不要扩写：\n\n"
            "{{原文:多行}}\n\n"
            "额外要求：{{要求|}}\n"
        ),
        "tags": ["写作"],
    },
    {
        "id": "starter-translate",
        "name": "中英互译",
        "body": (
            "请将以下内容翻译为{{目标语言|英文}}，语气{{语气|自然、准确}}：\n\n"
            "{{原文:多行}}\n"
        ),
        "tags": ["翻译"],
    },
    {
        "id": "starter-summary",
        "name": "摘要总结",
        "body": (
            "请用{{字数|200}}字以内总结以下内容，列出{{要点数:数字|3}}个要点：\n\n"
            "{{内容:多行}}\n"
        ),
        "tags": ["总结"],
    },
    {
        "id": "starter-code-explain",
        "name": "代码讲解",
        "body": (
            "请讲解以下{{语言|Python}}代码的作用、关键逻辑与潜在风险：\n\n"
            "```{{语言|Python}}\n{{代码:多行}}\n```\n\n"
            "受众：{{受众|有经验的开发者}}\n"
        ),
        "tags": ["开发"],
    },
    {
        "id": "starter-meeting",
        "name": "会议纪要",
        "body": (
            "根据以下会议记录整理纪要：\n\n{{记录:多行}}\n\n"
            "输出结构：\n1. 议题\n2. 决议\n3. 待办（负责人 / 截止）\n"
            "语气：{{语气|简洁、客观}}\n"
        ),
        "tags": ["工作"],
    },
]


def _dialog_path(result) -> str | None:
    if not result:
        return None
    return result if isinstance(result, str) else result[0]


def _log_path() -> str:
    try:
        import applog
        return applog.path()
    except Exception:
        return ""


def _safe_filename(name: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "prompt").strip(" .")
    return (s or "prompt")[:80]


def _diff_lines(a: str, b: str) -> list[dict]:
    """Simple line diff for the version compare UI (no external dep)."""
    import difflib
    a_lines = (a or "").splitlines()
    b_lines = (b or "").splitlines()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a_lines, b_lines).get_opcodes():
        if tag == "equal":
            for line in a_lines[i1:i2]:
                out.append({"op": "eq", "text": line})
        elif tag == "delete":
            for line in a_lines[i1:i2]:
                out.append({"op": "del", "text": line})
        elif tag == "insert":
            for line in b_lines[j1:j2]:
                out.append({"op": "ins", "text": line})
        elif tag == "replace":
            for line in a_lines[i1:i2]:
                out.append({"op": "del", "text": line})
            for line in b_lines[j1:j2]:
                out.append({"op": "ins", "text": line})
    return out


class Api:
    def __init__(self, store: PromptStore,
                 on_hide: Callable[[], None] | None = None,
                 on_quit: Callable[[], None] | None = None,
                 on_settings_changed: Callable[[dict], dict] | None = None,
                 get_quick_status: Callable[[], dict] | None = None,
                 revisions=None, history=None):
        self._store = store
        self._revisions = revisions
        self._history = history
        self._on_hide = on_hide
        self._on_quit = on_quit
        self._on_settings_changed = on_settings_changed
        self._get_quick_status = get_quick_status
        self._window = None
        self._restart: Callable[[bool], dict] | None = None

    def set_restart(self, fn: Callable[[bool], dict]) -> None:
        self._restart = fn

    def set_window(self, window) -> None:
        self._window = window

    def _record_fill(self, prompt_id: str, values: dict | None, result: str) -> None:
        if not self._history:
            return
        if not load_settings().get("history_enabled", True):
            return
        p = self._store.get(prompt_id) if prompt_id else None
        if not p:
            return
        try:
            self._history.add(prompt_id, p.get("name") or "", values or {}, result or "")
        except Exception:
            pass

    def _auto_revision(self, prompt_id: str, before: dict | None, after: dict | None) -> None:
        if not self._revisions or not after:
            return
        try:
            if before and before.get("body") == after.get("body") and before.get("name") == after.get("name"):
                return
            self._revisions.add(prompt_id, after.get("name") or "", after.get("body") or "",
                                source="auto", skip_unchanged=True)
        except Exception:
            pass

    # ------------------------------------------------------------ bootstrap
    def get_bootstrap(self) -> dict[str, Any]:
        from settings_store import ONBOARDING_VERSION
        settings = self.get_settings()
        sort = settings.get("library_sort") or "recent"
        return {
            "onboarding": int(settings.get("onboarding") or 0) < ONBOARDING_VERSION,
            "version": APP_VERSION,
            "settings": settings,
            "prompts": self._store.list(sort=sort),
            "tree": self._store.tree(""),
            "tags": self._store.all_tags(),
            "starters": [] if settings.get("starters_dismissed") else list(STARTERS),
            "stats": self._store.local_stats(),
            "quick": self.quick_status(),
            "migration": self._store.migration,
            "recovered": self._store.recovered,
            "data_dir": str(data_dir()),
            "log_path": _log_path(),
        }

    # ------------------------------------------------------------ prompts
    def list_prompts(self, query: str = "", sort: str = "", tag: str = "",
                     favorites_only: bool = False, archived_only: bool = False) -> list:
        s = sort or load_settings().get("library_sort") or "recent"
        return self._store.list(query or "", archived_only=bool(archived_only),
                                tag=tag or None, favorites_only=bool(favorites_only), sort=s)

    def get_prompt(self, prompt_id: str) -> dict | None:
        return self._store.get(prompt_id)

    def create_prompt(self, name: str = "", body: str | None = None,
                      role_id: str = "", category_id: str = "",
                      keywords=None, summary: str = "") -> dict:
        kwargs = {}
        if role_id:
            kwargs["role_id"] = role_id
        if category_id:
            kwargs["category_id"] = category_id
        if keywords is not None:
            kwargs["keywords"] = keywords
        if summary:
            kwargs["summary"] = summary
        if body is not None:
            return self._store.create(name or "", body, **kwargs)
        return self._store.create(name or "", **kwargs)

    def create_from_starter(self, starter_id: str) -> dict:
        st = next((x for x in STARTERS if x["id"] == starter_id), None)
        if not st:
            return {"ok": False, "error": "模板不存在"}
        p = self._store.create(st["name"], st["body"])
        if st.get("tags"):
            p = self._store.set_tags(p["id"], st["tags"]) or p
        return {"ok": True, "prompt": p}

    def dismiss_starters(self) -> dict:
        save_settings({"starters_dismissed": True})
        return {"ok": True, "settings": self.get_settings()}

    def save_prompt(self, prompt_id: str, patch: dict) -> dict:
        before = self._store.get(prompt_id)
        allowed = {k: v for k, v in (patch or {}).items()
                   if k in ("name", "body", "tags", "keywords", "summary", "favorite", "pinned",
                            "category_id", "role_id", "order", "last_ai_run")}
        p = self._store.update(prompt_id, allowed)
        if p and ("body" in allowed or "name" in allowed):
            self._auto_revision(prompt_id, before, p)
        return {"ok": bool(p), "prompt": p}

    def duplicate_prompt(self, prompt_id: str) -> dict:
        p = self._store.duplicate(prompt_id)
        return {"ok": bool(p), "prompt": p}

    def rename_prompt(self, prompt_id: str, name: str) -> dict:
        return self.save_prompt(prompt_id, {"name": name})

    def delete_prompt(self, prompt_id: str) -> dict:
        """Permanent delete; returns the removed prompt so the UI can offer "撤销"."""
        taken = self._store.take(prompt_id)
        if taken and self._revisions:
            try:
                self._revisions.purge_prompt(prompt_id)
            except Exception:
                pass
        return {"ok": bool(taken), **(taken or {})}

    def restore_prompt(self, prompt: dict, index: int = 0) -> dict:
        p = self._store.restore(prompt, index)
        return {"ok": bool(p), "prompt": p}

    def save_test_values(self, prompt_id: str, values: dict) -> dict:
        p = self._store.update(prompt_id, {"test_values": values or {}})
        return {"ok": bool(p), "count": len((p or {}).get("test_values") or {})}

    def list_cases(self, prompt_id: str) -> dict:
        p = self._store.get(prompt_id)
        if not p:
            return {"ok": False, "cases": [], "error": "提示词不存在"}
        return {"ok": True, "cases": list(p.get("cases") or [])}

    def save_case(self, prompt_id: str, case: dict | None = None) -> dict:
        """Create or update one case. Pass id to update; omit for new."""
        import uuid
        p = self._store.get(prompt_id)
        if not p:
            return {"ok": False, "error": "提示词不存在"}
        if p.get("builtin") or p.get("system"):
            return {"ok": False, "error": "内置提示词请先复制后编辑"}
        cases = list(p.get("cases") or [])
        case = case if isinstance(case, dict) else {}
        cid = str(case.get("id") or "").strip()
        name = (str(case.get("name") or "用例").strip() or "用例")[:60]
        values = case.get("values") if isinstance(case.get("values"), dict) else {}
        values = {str(k): str(v if v is not None else "") for k, v in values.items()}
        expect = str(case.get("expect") or "")[:8000]
        notes = str(case.get("notes") or "")[:500]
        last_run = case.get("last_run") if isinstance(case.get("last_run"), dict) else {}
        if cid:
            found = False
            for i, c in enumerate(cases):
                if c.get("id") == cid:
                    prev = dict(c)
                    prev.update({"name": name, "values": values, "expect": expect, "notes": notes})
                    if last_run:
                        prev["last_run"] = last_run
                    cases[i] = prev
                    found = True
                    break
            if not found:
                cases.append({"id": cid, "name": name, "values": values, "expect": expect,
                              "notes": notes, "last_run": last_run or {}})
        else:
            if len(cases) >= 10:
                return {"ok": False, "error": "每个提示词最多 10 个用例"}
            cid = f"case-{uuid.uuid4().hex[:10]}"
            cases.append({"id": cid, "name": name, "values": values, "expect": expect,
                          "notes": notes, "last_run": {}})
        updated = self._store.update(prompt_id, {"cases": cases})
        saved = next((c for c in (updated.get("cases") or []) if c.get("id") == cid), None)
        return {"ok": bool(updated), "case": saved, "cases": (updated or {}).get("cases") or []}

    def delete_case(self, prompt_id: str, case_id: str) -> dict:
        p = self._store.get(prompt_id)
        if not p:
            return {"ok": False, "error": "提示词不存在"}
        if p.get("builtin") or p.get("system"):
            return {"ok": False, "error": "内置提示词请先复制后编辑"}
        cases = [c for c in (p.get("cases") or []) if c.get("id") != case_id]
        updated = self._store.update(prompt_id, {"cases": cases})
        return {"ok": bool(updated), "cases": (updated or {}).get("cases") or []}

    def run_case(self, prompt_id: str, case_id: str, apply_role_system: bool | None = None) -> dict:
        """Render case values; if AI configured, call once and soft-match expect."""
        from datetime import datetime
        p = self._store.get(prompt_id)
        if not p:
            return {"ok": False, "error": "提示词不存在"}
        case = next((c for c in (p.get("cases") or []) if c.get("id") == case_id), None)
        if not case:
            return {"ok": False, "error": "用例不存在"}
        values = case.get("values") or {}
        rr = self.render_prompt(p.get("body") or "", values, prompt_id=prompt_id,
                                apply_role_system=apply_role_system)
        final = rr.get("final") or ""
        expect = (case.get("expect") or "").strip()
        # dry-run always available
        soft = None
        if expect:
            soft = expect in final or final in expect or expect.lower() in final.lower()
        # try AI if configured
        ai_out = ""
        ai_err = ""
        used_ai = False
        try:
            targets = self._resolve_targets([])
            if targets and (targets[0].get("api_key") or "").strip():
                used_ai = True
                sp = rr.get("system_prompt") or ""
                # When role system already prepended into final, send as user content;
                # also pass role system separately if present for cleaner chat.
                from ai_service import run_parallel_test
                rows = run_parallel_test(
                    [targets[0]],
                    rendered="" if sp else final,
                    system=sp,
                    user=rr.get("rendered") if sp else "",
                )
                row = (rows or [{}])[0]
                if row.get("ok"):
                    ai_out = row.get("text") or ""
                else:
                    ai_err = row.get("error") or "AI 调用失败"
                if expect and ai_out:
                    soft = expect in ai_out or expect.lower() in ai_out.lower()
        except Exception as e:
            ai_err = str(e)
            used_ai = used_ai or False
        match = "pass" if soft is True else ("fail" if soft is False else "n/a")
        last_run = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "output": (ai_out or final)[:8000],
            "ok": bool(soft) if soft is not None else (bool(ai_out) if used_ai else True),
            "match": match,
            "error": ai_err[:500],
        }
        # persist last_run on case
        cases = list(p.get("cases") or [])
        for i, c in enumerate(cases):
            if c.get("id") == case_id:
                c = dict(c)
                c["last_run"] = last_run
                cases[i] = c
                break
        if not (p.get("builtin") or p.get("system")):
            self._store.update(prompt_id, {"cases": cases})
        return {
            "ok": True, "used_ai": used_ai, "rendered": rr.get("rendered"),
            "final": final, "output": ai_out or final, "expect": expect,
            "match": match, "soft_match": soft, "error": ai_err,
            "applied_role_system": rr.get("applied"), "last_run": last_run,
            "dry_run": not used_ai,
        }

    # ------------------------------------------------------------ organize
    def set_favorite(self, prompt_id: str, on: bool) -> dict:
        p = self._store.set_flags(prompt_id, favorite=bool(on))
        return {"ok": bool(p), "prompt": p}

    def set_pinned(self, prompt_id: str, on: bool) -> dict:
        p = self._store.set_flags(prompt_id, pinned=bool(on))
        return {"ok": bool(p), "prompt": p}

    def set_tags(self, prompt_id: str, tags) -> dict:
        p = self._store.set_tags(prompt_id, tags)
        return {"ok": bool(p), "prompt": p, "tags": self._store.all_tags()}

    def set_keywords(self, prompt_id: str, keywords) -> dict:
        p = self._store.set_keywords(prompt_id, keywords)
        return {"ok": bool(p), "prompt": p}

    def list_tags(self) -> list:
        return self._store.all_tags()

    # ------------------------------------------------------------ tree (2.8)
    def get_tree(self, query: str = "") -> dict:
        return self._store.tree(query or "")

    def list_roles(self) -> list:
        return self._store.roles()

    def list_categories(self, role_id: str = "") -> list:
        return self._store.categories(role_id or None)

    def create_role(self, name: str = "", icon: str = "folder", description: str = "") -> dict:
        r = self._store.create_role(name or "", icon or "folder", description or "")
        return {"ok": True, "role": r}

    def rename_role(self, role_id: str, name: str) -> dict:
        r = self._store.rename_role(role_id, name)
        return {"ok": bool(r), "role": r, "error": None if r else "无法重命名（内置角色请「复制后编辑」提示词）"}

    def update_role(self, role_id: str, patch: dict | None = None) -> dict:
        r = self._store.update_role(role_id, patch or {})
        return {"ok": bool(r), "role": r, "error": None if r else "角色不存在"}

    def get_role_system_prompt(self, role_id: str) -> dict:
        r = self._store.get_role(role_id)
        if not r:
            return {"ok": False, "system_prompt": "", "error": "角色不存在"}
        return {"ok": True, "role_id": r["id"], "name": r.get("name") or "",
                "system_prompt": r.get("system_prompt") or "", "builtin": bool(r.get("builtin"))}

    def set_role_system_prompt(self, role_id: str, text: str = "") -> dict:
        r = self._store.set_role_system_prompt(role_id, text or "")
        return {"ok": bool(r), "role": r, "error": None if r else "角色不存在"}

    def delete_role(self, role_id: str) -> dict:
        return self._store.delete_role(role_id)

    def reorder_roles(self, role_ids: list) -> dict:
        return self._store.reorder_roles(list(role_ids or []))

    def create_category(self, role_id: str, name: str = "") -> dict:
        c = self._store.create_category(role_id, name or "")
        return {"ok": bool(c), "category": c}

    def rename_category(self, category_id: str, name: str) -> dict:
        c = self._store.rename_category(category_id, name)
        return {"ok": bool(c), "category": c, "error": None if c else "无法重命名内置分类"}

    def delete_category(self, category_id: str) -> dict:
        return self._store.delete_category(category_id)

    def reorder_categories(self, role_id: str, category_ids: list) -> dict:
        return self._store.reorder_categories(role_id, list(category_ids or []))

    def move_prompt(self, prompt_id: str, category_id: str) -> dict:
        p = self._store.move_prompt(prompt_id, category_id)
        return {"ok": bool(p), "prompt": p}

    def move_prompt_to_role(self, prompt_id: str, role_id: str) -> dict:
        """Move user prompt into a role group. Builtins: refuse with Chinese error."""
        p0 = self._store.get(prompt_id)
        if p0 and (p0.get("builtin") or p0.get("system")):
            return {"ok": False, "prompt": None, "error": "内置提示词请先复制后编辑"}
        p = self._store.move_prompt_to_role(prompt_id, role_id)
        if not p:
            return {"ok": False, "prompt": None, "error": "无法移动到该角色"}
        return {"ok": True, "prompt": p}

    def breadcrumb(self, prompt_id: str) -> dict:
        return self._store.breadcrumb(prompt_id)

    def copy_builtin(self, prompt_id: str) -> dict:
        p = self._store.copy_builtin(prompt_id)
        return {"ok": bool(p), "prompt": p}

    def archive_prompt(self, prompt_id: str) -> dict:
        p = self._store.archive(prompt_id)
        return {"ok": bool(p), "prompt": p}

    def unarchive_prompt(self, prompt_id: str) -> dict:
        p = self._store.unarchive(prompt_id)
        return {"ok": bool(p), "prompt": p}

    def batch_archive(self, ids: list) -> dict:
        return self._store.batch_archive(list(ids or []))

    def batch_delete(self, ids: list) -> dict:
        r = self._store.batch_delete(list(ids or []))
        if self._revisions:
            for t in r.get("taken") or []:
                try:
                    self._revisions.purge_prompt((t.get("prompt") or {}).get("id") or "")
                except Exception:
                    pass
        return r

    def restore_many(self, taken: list) -> dict:
        n = self._store.restore_many(list(taken or []))
        return {"ok": n > 0, "count": n}

    def export_selected(self, ids: list) -> dict:
        ids = set(str(x) for x in (ids or []))
        payload = self._store.export_payload()
        payload["prompts"] = [p for p in payload["prompts"] if p["id"] in ids]
        if not payload["prompts"]:
            return {"ok": False, "error": "未选择提示词"}
        path = self._save_dialog("promptbuilder_selected.json", ("JSON (*.json)",))
        if not path:
            return {"ok": False, "cancelled": True}
        from atomic_io import write_json_atomic
        write_json_atomic(Path(path), payload, backup=False)
        return {"ok": True, "count": len(payload["prompts"]), "path": path}

    # ------------------------------------------------------------ versions
    def list_revisions(self, prompt_id: str) -> list:
        if not self._revisions:
            return []
        return self._revisions.list(prompt_id)

    def save_revision(self, prompt_id: str, note: str = "") -> dict:
        p = self._store.get(prompt_id)
        if not p or not self._revisions:
            return {"ok": False, "error": "无法保存版本"}
        rev = self._revisions.add(prompt_id, p.get("name") or "", p.get("body") or "",
                                  note=note or "", source="manual", skip_unchanged=False)
        return {"ok": bool(rev), "revision": rev}

    def restore_revision(self, prompt_id: str, rev_id: str) -> dict:
        if not self._revisions:
            return {"ok": False, "error": "无版本历史"}
        rev = self._revisions.get(prompt_id, rev_id)
        if not rev:
            return {"ok": False, "error": "版本不存在"}
        before = self._store.get(prompt_id)
        # snapshot current before restoring
        if before and self._revisions:
            self._revisions.add(prompt_id, before.get("name") or "", before.get("body") or "",
                                note="还原前自动保存", source="auto", skip_unchanged=True)
        p = self._store.update(prompt_id, {"name": rev["name"], "body": rev["body"]})
        return {"ok": bool(p), "prompt": p, "revision": rev}

    def compare_revisions(self, prompt_id: str, rev_a: str, rev_b: str) -> dict:
        """Compare two revisions, or a revision vs current (rev_b == 'current')."""
        if not self._revisions:
            return {"ok": False, "error": "无版本历史"}
        a = self._revisions.get(prompt_id, rev_a)
        if rev_b == "current":
            cur = self._store.get(prompt_id)
            if not cur:
                return {"ok": False, "error": "提示词不存在"}
            b = {"id": "current", "name": cur["name"], "body": cur["body"], "saved_at": cur.get("updated_at")}
        else:
            b = self._revisions.get(prompt_id, rev_b)
        if not a or not b:
            return {"ok": False, "error": "版本不存在"}
        name_a = a.get("name") or ""
        name_b = b.get("name") or ""
        body_a = a.get("body") or ""
        body_b = b.get("body") or ""
        # Combined name+body text for unified view; separate name_diff for UI header
        combined_a = f"# {name_a}\n\n{body_a}"
        combined_b = f"# {name_b}\n\n{body_b}"
        return {
            "ok": True, "a": a, "b": b,
            "diff": _diff_lines(body_a, body_b),
            "name_diff": _diff_lines(name_a, name_b),
            "combined_diff": _diff_lines(combined_a, combined_b),
            "name_changed": name_a != name_b,
        }

    def delete_revision(self, prompt_id: str, rev_id: str) -> dict:
        if not self._revisions:
            return {"ok": False}
        return {"ok": self._revisions.delete(prompt_id, rev_id)}

    # ------------------------------------------------------------ fill history
    def list_history(self, prompt_id: str = "", limit: int = 50) -> list:
        if not self._history:
            return []
        return self._history.list(prompt_id=prompt_id or None, limit=int(limit or 50))

    def get_history(self, hid: str) -> dict | None:
        if not self._history:
            return None
        return self._history.get(hid)

    def clear_history(self, prompt_id: str = "") -> dict:
        if not self._history:
            return {"ok": False, "count": 0}
        n = self._history.clear(prompt_id=prompt_id or None)
        return {"ok": True, "count": n}

    def delete_history(self, hid: str) -> dict:
        if not self._history:
            return {"ok": False}
        return {"ok": self._history.delete(hid)}

    def rerun_history(self, hid: str) -> dict:
        """Return prompt + values so the UI can re-open the form / insert again."""
        h = self.get_history(hid)
        if not h:
            return {"ok": False, "error": "记录不存在"}
        p = self._store.get(h["prompt_id"])
        return {"ok": True, "history": h, "prompt": p,
                "prompt_missing": p is None}

    # ------------------------------------------------------------ observe / maintain
    def get_stats(self) -> dict:
        return self._store.local_stats()

    def health_check(self) -> dict:
        return self._store.health_check()

    def backup_data(self) -> dict:
        """Zip the whole data folder (prompts, settings, revisions, history, backups)."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self._save_dialog(f"PromptBuilder-backup-{stamp}.zip", ("ZIP (*.zip)",))
        if not path:
            return {"ok": False, "cancelled": True}
        root = data_dir()
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for fp in root.rglob("*"):
                    if not fp.is_file():
                        continue
                    # skip nested backup zips the user may have saved inside data_dir
                    if fp.suffix.lower() == ".zip" and "backup" in fp.name.lower():
                        continue
                    zf.write(fp, arcname=str(fp.relative_to(root)))
            return {"ok": True, "path": path, "bytes": Path(path).stat().st_size}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def restore_data_backup(self) -> dict:
        """Restore from a zip previously made by backup_data. Does NOT wipe unknown files."""
        path = self._open_dialog(("ZIP (*.zip)",))
        if not path:
            return {"ok": False, "cancelled": True}
        root = data_dir()
        try:
            # safety snapshot of current library first
            from atomic_io import snapshot
            try:
                snapshot(prompts_path(), backups_dir(), keep=10, min_interval_s=0)
            except Exception:
                pass
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                # only allow known data files — never extract arbitrary paths
                allowed = {"prompts.json", "settings.json", "revisions.json", "fill_history.json",
                           "prompts.json.bak", "settings.json.bak", "revisions.json.bak",
                           "fill_history.json.bak"}
                extracted = []
                for name in names:
                    # normalize + reject path traversal
                    norm = name.replace("\\", "/").lstrip("/")
                    if ".." in norm.split("/"):
                        continue
                    base = norm.split("/")[-1]
                    if base not in allowed and not (
                        norm.startswith("backups/") and base.endswith(".json")
                    ):
                        continue
                    target = root / Path(norm)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted.append(norm)
            # reload in-memory stores
            self._store.load()
            if self._revisions:
                self._revisions.load()
            if self._history:
                self._history.load()
            return {"ok": True, "extracted": extracted, "count": len(extracted),
                    "restart_hint": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------ debug
    def analyze(self, body: str, values: dict | None = None) -> dict:
        return analyze(body or "", values or {})

    def sample_values(self, body: str) -> dict:
        return sample_values(variables_of(body or ""))

    def _role_system_prompt_for(self, prompt_id: str = "", role_id: str = "") -> str:
        rid = (role_id or "").strip()
        if not rid and prompt_id:
            p = self._store.get(prompt_id)
            if p:
                rid = p.get("role_id") or ""
        if not rid:
            return ""
        r = self._store.get_role(rid)
        return (r.get("system_prompt") or "").strip() if r else ""

    def render_prompt(self, body: str = "", values: dict | None = None,
                      prompt_id: str = "", role_id: str = "",
                      apply_role_system: bool | None = None) -> dict:
        """Render body with values; optionally prepend role system_prompt."""
        from prompt_syntax import render as _render
        rendered = _render(body or "", values or {})
        settings = self.get_settings()
        use = settings.get("apply_role_system_prompt", True) if apply_role_system is None else bool(apply_role_system)
        sp = self._role_system_prompt_for(prompt_id, role_id) if use else ""
        final = rendered
        applied = False
        if sp:
            sep = "\n\n---\n\n"
            final = sp + sep + rendered
            applied = True
        return {"ok": True, "rendered": rendered, "final": final, "system_prompt": sp,
                "applied": applied, "separator": "---"}

    def copy_text(self, text: str, prompt_id: str = "", values: dict | None = None) -> dict:
        try:
            import winput
            ok = winput.set_text(text or "")
            if ok and prompt_id:
                self._store.touch_used(prompt_id, values or {})
                self._record_fill(prompt_id, values or {}, text or "")
            return {"ok": ok}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------ import / export
    def _save_dialog(self, filename: str, types: tuple) -> str | None:
        import webview
        if not self._window:
            return None
        return _dialog_path(self._window.create_file_dialog(
            webview.SAVE_DIALOG, directory="", save_filename=filename, file_types=types))

    def _open_dialog(self, types: tuple, multiple: bool = False):
        import webview
        if not self._window:
            return None
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=multiple, file_types=types)
        if not res:
            return None
        return list(res) if multiple else _dialog_path(res)

    def export_library(self) -> dict:
        path = self._save_dialog("promptbuilder_prompts.json", ("JSON (*.json)",))
        if not path:
            return {"ok": False, "cancelled": True}
        payload = self._store.export_payload()
        from atomic_io import write_json_atomic
        write_json_atomic(Path(path), payload, backup=False)
        return {"ok": True, "count": len(payload["prompts"]), "path": path}

    def import_library(self) -> dict:
        path = self._open_dialog(("JSON (*.json)",))
        if not path:
            return {"ok": False, "cancelled": True}
        try:
            if Path(path).stat().st_size > 20 * 1024 * 1024:
                return {"ok": False, "error": "文件过大（超过 20 MB）"}
            raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except Exception as e:
            return {"ok": False, "error": f"读取失败：{e}"}
        return self._store.import_payload(raw)

    def export_markdown(self, prompt_id: str) -> dict:
        p = self._store.get(prompt_id)
        if not p:
            return {"ok": False, "error": "提示词不存在"}
        path = self._save_dialog(_safe_filename(p["name"]) + ".md", ("Markdown (*.md)", "All files (*.*)"))
        if not path:
            return {"ok": False, "cancelled": True}
        Path(path).write_text(p["body"], encoding="utf-8")
        return {"ok": True, "path": path}

    def import_markdown(self) -> dict:
        paths = self._open_dialog(("Markdown (*.md;*.markdown;*.txt)", "All files (*.*)"), multiple=True)
        if not paths:
            return {"ok": False, "cancelled": True}
        created, errors = [], []
        for pth in paths:
            try:
                created.append(self._store.import_markdown(pth)["id"])
            except Exception as e:
                errors.append(f"{Path(pth).name}: {e}")
        return {"ok": bool(created), "count": len(created), "ids": created, "errors": errors}

    # ------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        s = load_settings()
        s["autostart"] = self._autostart_on()
        # never send raw encrypted blobs to UI list views — use list_ai_profiles
        if "ai_profiles" in s:
            s["ai_profiles"] = self._public_ai_profiles(s.get("ai_profiles") or [])
        return s

    def set_settings(self, patch: dict) -> dict:
        # AI profiles go through save_ai_profile / delete_ai_profile — never via set_settings
        patch = {k: v for k, v in dict(patch or {}).items()
                 if k not in ("admin_mode", "ai_profiles", "ai_default_profile")}  # see set_admin_mode / AI APIs
        err = ""
        if "autostart" in patch:
            try:
                err = self._apply_autostart(bool(patch["autostart"]))
            except Exception as e:
                err = str(e)
        cur = save_settings(patch)
        quick = None
        if self._on_settings_changed and any(k in patch for k in ("quick_enabled",
                                                                 "quick_exclude", "quick_skip_fullscreen",
                                                                 "quick_preview", "theme", "quick_follow")):
            quick = self._on_settings_changed(cur)
        return {"ok": not err, "error": err, "settings": self.get_settings(),
                "quick": quick or self.quick_status()}

    def _apply_autostart(self, on: bool) -> str:
        from autostart import set_autostart
        from winapi import self_elevated
        if load_settings().get("admin_mode") and self_elevated():
            import elevation
            if elevation.task_exists():
                r = elevation.register(on)
                set_autostart(False)
                return "" if r.get("ok") else (r.get("error") or "开机自启设置失败")
        r = set_autostart(on)
        return "" if r.get("ok") else (r.get("error") or "开机自启设置失败")

    def _autostart_on(self) -> bool:
        try:
            from autostart import is_autostart_enabled
            if is_autostart_enabled():
                return True
        except Exception:
            pass
        s = load_settings()
        return bool(s.get("admin_mode") and s.get("autostart"))

    # ------------------------------------------------------------ admin mode
    def admin_status(self) -> dict:
        import elevation
        from winapi import self_elevated
        s = load_settings()
        return {"supported": elevation.supported(), "enabled": bool(s.get("admin_mode")),
                "elevated": self_elevated(), "task": elevation.task_exists()}

    def set_admin_mode(self, on: bool) -> dict:
        import elevation
        from autostart import set_autostart
        from winapi import self_elevated
        on = bool(on)
        autostart = self._autostart_on()
        elevated = self_elevated()
        if on:
            r = elevation.register(autostart) if elevated else \
                elevation.run_elevated_helper(elevation.REGISTER_ARG, "--autostart" if autostart else "")
            if not r.get("ok"):
                return {**r, "status": self.admin_status()}
            if autostart:
                set_autostart(False)
            save_settings({"admin_mode": True, "autostart": autostart})
            return {"ok": True, "restart": not elevated, "status": self.admin_status()}
        r = elevation.unregister() if elevated else (
            elevation.run_elevated_helper(elevation.UNREGISTER_ARG) if elevation.task_exists() else {"ok": True})
        if not r.get("ok"):
            return {**r, "status": self.admin_status()}
        save_settings({"admin_mode": False, "autostart": autostart})
        if autostart:
            set_autostart(True)
        return {"ok": True, "restart": elevated, "status": self.admin_status()}

    def restart_app(self, elevated: bool) -> dict:
        if not self._restart:
            return {"ok": False, "error": "不支持"}
        return self._restart(bool(elevated))

    # ------------------------------------------------------------ misc
    def complete_onboarding(self) -> dict:
        from settings_store import ONBOARDING_VERSION
        save_settings({"onboarding": ONBOARDING_VERSION})
        return {"ok": True}

    def open_data_dir(self) -> dict:
        try:
            os.startfile(str(data_dir()))  # type: ignore[attr-defined]
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def quick_status(self) -> dict:
        if self._get_quick_status:
            try:
                return self._get_quick_status()
            except Exception as e:
                return {"mode": "error", "error": str(e)}
        return {"mode": "off"}


    # ------------------------------------------------------------ AI workshop (2.11)
    def _public_ai_profiles(self, profiles: list | None = None) -> list:
        from ai_crypto import decrypt_secret, mask_secret
        out = []
        for p in profiles if profiles is not None else (load_settings().get("ai_profiles") or []):
            key = decrypt_secret(p.get("api_key_enc") or "")
            out.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "preset": p.get("preset"),
                "kind": p.get("kind"),
                "base_url": p.get("base_url"),
                "default_model": p.get("default_model"),
                "models": list(p.get("models") or []),
                "has_key": bool(key),
                "api_key_masked": mask_secret(key),
            })
        return out

    def list_ai_presets(self) -> list:
        from ai_providers import list_presets
        return list_presets()

    def list_ai_models(self, spec: dict | None = None) -> dict:
        """Fetch models for a profile or ad-hoc {kind, base_url, api_key, preset, profile_id}."""
        from ai_crypto import decrypt_secret
        from ai_providers import list_models, preset_models
        spec = dict(spec or {})
        kind = str(spec.get("kind") or "openai")
        base_url = str(spec.get("base_url") or "")
        api_key = str(spec.get("api_key") or "")
        preset = str(spec.get("preset") or "")
        pid = str(spec.get("profile_id") or "").strip()
        if pid:
            s = load_settings()
            prof = next((p for p in (s.get("ai_profiles") or []) if p.get("id") == pid), None)
            if prof:
                kind = kind or prof.get("kind") or "openai"
                if not base_url:
                    base_url = prof.get("base_url") or ""
                if not api_key:
                    api_key = decrypt_secret(prof.get("api_key_enc") or "")
                if not preset:
                    preset = prof.get("preset") or ""
                if not kind:
                    kind = prof.get("kind") or "openai"
                # prefer stored kind from profile when caller left default
                if spec.get("kind") in (None, "", "openai") and prof.get("kind"):
                    kind = prof.get("kind") or kind
        # if key empty but profile has key, already filled above
        r = list_models(kind=kind, base_url=base_url, api_key=api_key, preset=preset)
        if (not r.get("models")) and preset:
            r = {"ok": True, "models": preset_models(preset), "source": "preset",
                 "error": r.get("error") or ""}
        return r

    def list_ai_profiles(self) -> dict:
        s = load_settings()
        return {
            "ok": True,
            "profiles": self._public_ai_profiles(),
            "default_profile": s.get("ai_default_profile") or "",
        }

    def save_ai_profile(self, profile: dict) -> dict:
        """Create or update a provider profile. Pass api_key to set/replace; omit/empty to keep."""
        import uuid
        from ai_crypto import encrypt_secret
        profile = dict(profile or {})
        s = load_settings()
        profiles = list(s.get("ai_profiles") or [])
        pid = str(profile.get("id") or "").strip()
        is_new = not pid
        if is_new:
            pid = "aip-" + uuid.uuid4().hex[:10]
        existing = next((p for p in profiles if p.get("id") == pid), None)
        api_key = profile.get("api_key")
        if api_key is None or api_key == "":
            enc = (existing or {}).get("api_key_enc") or ""
        else:
            enc = encrypt_secret(str(api_key).strip())
        models = profile.get("models")
        if not isinstance(models, list):
            models = (existing or {}).get("models") or []
        models = [str(m).strip() for m in models if str(m).strip()][:40]
        row = {
            "id": pid,
            "name": str(profile.get("name") or (existing or {}).get("name") or "未命名")[:80],
            "preset": str(profile.get("preset") or (existing or {}).get("preset") or "custom")[:40],
            "kind": str(profile.get("kind") or (existing or {}).get("kind") or "openai")[:20],
            "base_url": str(profile.get("base_url") if profile.get("base_url") is not None else (existing or {}).get("base_url") or "")[:300],
            "api_key_enc": enc,
            "default_model": str(profile.get("default_model") or (existing or {}).get("default_model") or (models[0] if models else ""))[:120],
            "models": models,
        }
        if existing:
            profiles = [row if p.get("id") == pid else p for p in profiles]
        else:
            profiles.append(row)
        patch = {"ai_profiles": profiles}
        if profile.get("make_default") or not s.get("ai_default_profile"):
            patch["ai_default_profile"] = pid
        save_settings(patch)
        return {"ok": True, "profile": self._public_ai_profiles([row])[0],
                "profiles": self._public_ai_profiles()}

    def delete_ai_profile(self, profile_id: str) -> dict:
        s = load_settings()
        profiles = [p for p in (s.get("ai_profiles") or []) if p.get("id") != profile_id]
        patch = {"ai_profiles": profiles}
        if s.get("ai_default_profile") == profile_id:
            patch["ai_default_profile"] = profiles[0]["id"] if profiles else ""
        save_settings(patch)
        return {"ok": True, "profiles": self._public_ai_profiles()}

    def set_ai_default_profile(self, profile_id: str) -> dict:
        s = load_settings()
        ids = {p.get("id") for p in (s.get("ai_profiles") or [])}
        if profile_id and profile_id not in ids:
            return {"ok": False, "error": "配置不存在"}
        save_settings({"ai_default_profile": profile_id or ""})
        return {"ok": True, "default_profile": profile_id or ""}

    def _resolve_targets(self, spec) -> list:
        """spec: profile_id+model | list of {profile_id, model} | {targets: [...]}"""
        from ai_crypto import decrypt_secret
        from ai_service import resolve_target_from_profile
        s = load_settings()
        profiles = {p["id"]: p for p in (s.get("ai_profiles") or [])}
        items = []
        if isinstance(spec, dict) and "targets" in spec:
            items = list(spec.get("targets") or [])
        elif isinstance(spec, list):
            items = spec
        elif isinstance(spec, dict):
            items = [spec]
        else:
            items = []
        out = []
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            pid = it.get("profile_id") or it.get("id") or s.get("ai_default_profile")
            prof = profiles.get(pid)
            if not prof:
                continue
            key = decrypt_secret(prof.get("api_key_enc") or "")
            model = it.get("model") or prof.get("default_model") or ""
            t = resolve_target_from_profile(prof, key, model)
            t["id"] = f"{pid}:{model}:{i}"
            t["label"] = f"{prof.get('name') or pid} · {model}"
            out.append(t)
        return out

    def ai_generate(self, goal: str, audience: str = "", extra: str = "",
                    profile_id: str = "", model: str = "") -> dict:
        from ai_service import run_generate
        targets = self._resolve_targets({"profile_id": profile_id, "model": model})
        if not targets:
            return {"ok": False, "error": "请先在设置中配置至少一个 AI 模型，并填入 API Key"}
        if not (goal or "").strip():
            return {"ok": False, "error": "请填写目标描述"}
        r = run_generate(targets[0], goal, audience, extra)
        return {"ok": r.get("ok"), "text": r.get("text") or "", "error": r.get("error") or "",
                "latency_ms": r.get("latency_ms"), "model": targets[0].get("model"),
                "label": targets[0].get("label")}

    def ai_rewrite(self, body: str, instruction: str = "",
                   profile_id: str = "", model: str = "") -> dict:
        from ai_service import run_rewrite
        targets = self._resolve_targets({"profile_id": profile_id, "model": model})
        if not targets:
            return {"ok": False, "error": "请先配置 AI 模型与 API Key"}
        if not (body or "").strip():
            return {"ok": False, "error": "正文为空"}
        r = run_rewrite(targets[0], body, instruction)
        return {"ok": r.get("ok"), "text": r.get("text") or "", "error": r.get("error") or "",
                "latency_ms": r.get("latency_ms"), "model": targets[0].get("model"),
                "original": body}

    def ai_review(self, body: str, profile_id: str = "", model: str = "") -> dict:
        from ai_service import run_review
        targets = self._resolve_targets({"profile_id": profile_id, "model": model})
        if not targets:
            return {"ok": False, "error": "请先配置 AI 模型与 API Key"}
        if not (body or "").strip():
            return {"ok": False, "error": "正文为空"}
        r = run_review(targets[0], body)
        return {"ok": r.get("ok"), "text": r.get("text") or "", "error": r.get("error") or "",
                "latency_ms": r.get("latency_ms"), "model": targets[0].get("model")}

    def ai_parallel_test(self, rendered: str = "", targets: list | None = None,
                         system: str = "", user: str = "") -> dict:
        from ai_service import run_parallel_test
        ts = self._resolve_targets(targets or [])
        if not ts:
            return {"ok": False, "error": "请至少选择一个模型"}
        if not ((rendered or user or "").strip()):
            return {"ok": False, "error": "测试内容为空 — 请先在表单填好变量并预览"}
        rows = run_parallel_test(ts, rendered=rendered, system=system, user=user)
        return {"ok": True, "results": rows}

    def ai_fill_form(self, variables: list | None = None, user_text: str = "",
                     profile_id: str = "", model: str = "") -> dict:
        """Fill variable form from natural language (// quick form + optional main UI)."""
        from ai_service import run_fill_form
        targets = self._resolve_targets({"profile_id": profile_id, "model": model})
        if not targets or not (targets[0].get("api_key") or "").strip():
            return {"ok": False, "values": {}, "error": "请先在设置 → AI 模型中配置 API Key",
                    "need_settings": True}
        r = run_fill_form(targets[0], variables or [], user_text)
        r["need_settings"] = False
        if "label" not in r:
            r["label"] = targets[0].get("label")
        if "model" not in r:
            r["model"] = targets[0].get("model")
        return r

    def ai_judge(self, rendered: str, results: list, profile_id: str = "", model: str = "") -> dict:

        """Optional AI judge: score each parallel-test output 1–5 with short rationale."""
        from ai_service import run_judge
        targets = self._resolve_targets({"profile_id": profile_id, "model": model})
        if not targets:
            return {"ok": False, "error": "请配置用于打分的评判模型与 API Key"}
        if not results:
            return {"ok": False, "error": "没有可打分的结果"}
        r = run_judge(targets[0], rendered or "", results or [])
        return {"ok": r.get("ok"), "scores": r.get("scores") or [], "text": r.get("text") or "",
                "error": r.get("error") or "", "latency_ms": r.get("latency_ms"),
                "model": targets[0].get("model")}

    def save_ai_run(self, prompt_id: str, run: dict) -> dict:
        """Persist last multi-model test run on the prompt (local)."""
        if not isinstance(run, dict):
            return {"ok": False, "error": "无效的试跑数据"}
        # cap payload
        results = []
        for row in (run.get("results") or [])[:12]:
            if not isinstance(row, dict):
                continue
            results.append({
                "id": str(row.get("id") or "")[:80],
                "label": str(row.get("label") or "")[:80],
                "model": str(row.get("model") or "")[:80],
                "ok": bool(row.get("ok")),
                "text": str(row.get("text") or "")[:8000],
                "error": str(row.get("error") or "")[:500],
                "latency_ms": int(row.get("latency_ms") or 0),
                "user_score": int(row.get("user_score") or 0),
                "ai_score": int(row.get("ai_score") or 0),
                "ai_note": str(row.get("ai_note") or "")[:400],
            })
        payload = {
            "at": run.get("at") or "",
            "rendered_preview": str(run.get("rendered_preview") or "")[:400],
            "results": results,
            "sort": str(run.get("sort") or "score"),
        }
        p = self._store.update(prompt_id, {"last_ai_run": payload})
        return {"ok": bool(p), "prompt": p}

    # ------------------------------------------------------------ window
    def hide_window(self) -> dict:
        if self._on_hide:
            self._on_hide()
        return {"ok": True}

    def quit_app(self) -> dict:
        if self._on_quit:
            self._on_quit()
        return {"ok": True}
