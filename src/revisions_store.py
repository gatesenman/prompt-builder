"""Per-prompt content revision history (local only).

File: <data>/revisions.json
  {"format": "promptbuilder-revisions", "version": 1,
   "items": {"<prompt-id>": [{"id", "saved_at", "name", "body", "note", "source"}]}}

Soft limit: MAX_REVISIONS newest kept per prompt. Snapshots are taken on content save
(source="auto", skipped if body unchanged) or via explicit "保存版本" (source="manual").
"""
from __future__ import annotations
import threading, uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from atomic_io import read_json_safe, write_json_atomic
from paths import revisions_path
from prompt_syntax import normalize_newlines

FORMAT = "promptbuilder-revisions"
VERSION = 1
MAX_REVISIONS = 20


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _new_id() -> str:
    return f"r-{uuid.uuid4().hex[:10]}"


def _clean_rev(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    body = normalize_newlines(str(item.get("body") or ""))
    name = (str(item.get("name") or "").strip() or "未命名")[:120]
    return {
        "id": str(item.get("id") or _new_id()),
        "saved_at": item.get("saved_at") or _now(),
        "name": name,
        "body": body,
        "note": (str(item.get("note") or "").strip())[:200],
        "source": "manual" if item.get("source") == "manual" else "auto",
    }


class RevisionsStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, list[dict]] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
            raw, _ = read_json_safe(revisions_path(), {"items": {}})
            items = (raw or {}).get("items") if isinstance(raw, dict) else {}
            out: dict[str, list[dict]] = {}
            if isinstance(items, dict):
                for pid, revs in items.items():
                    if not isinstance(revs, list):
                        continue
                    cleaned = [r for r in (_clean_rev(x) for x in revs) if r]
                    cleaned.sort(key=lambda r: r["saved_at"], reverse=True)
                    out[str(pid)] = cleaned[:MAX_REVISIONS]
            self._items = out

    def _save(self) -> None:
        write_json_atomic(revisions_path(), {
            "format": FORMAT, "version": VERSION, "updated_at": _now(),
            "items": self._items,
        }, backup=True)

    def list(self, prompt_id: str) -> list[dict]:
        with self._lock:
            return deepcopy(self._items.get(prompt_id) or [])

    def get(self, prompt_id: str, rev_id: str) -> dict | None:
        with self._lock:
            for r in self._items.get(prompt_id) or []:
                if r["id"] == rev_id:
                    return deepcopy(r)
        return None

    def add(self, prompt_id: str, name: str, body: str, *, note: str = "",
            source: str = "auto", skip_unchanged: bool = True) -> dict | None:
        """Append a snapshot. Returns None if skipped (identical to newest)."""
        body = normalize_newlines(body or "")
        name = (name or "").strip() or "未命名"
        with self._lock:
            revs = self._items.setdefault(prompt_id, [])
            if skip_unchanged and revs and revs[0]["body"] == body and revs[0]["name"] == name:
                return None
            rev = _clean_rev({
                "id": _new_id(), "saved_at": _now(), "name": name, "body": body,
                "note": note, "source": source,
            })
            assert rev is not None
            revs.insert(0, rev)
            del revs[MAX_REVISIONS:]
            self._save()
            return deepcopy(rev)

    def delete(self, prompt_id: str, rev_id: str) -> bool:
        with self._lock:
            revs = self._items.get(prompt_id) or []
            kept = [r for r in revs if r["id"] != rev_id]
            if len(kept) == len(revs):
                return False
            if kept:
                self._items[prompt_id] = kept
            else:
                self._items.pop(prompt_id, None)
            self._save()
            return True

    def purge_prompt(self, prompt_id: str) -> None:
        with self._lock:
            if prompt_id in self._items:
                del self._items[prompt_id]
                self._save()

    def rename_prompt(self, prompt_id: str, name: str) -> None:
        """Keep revision names in sync when the prompt is renamed without body change."""
        # no-op on purpose: revisions are historical snapshots
        return

    def stats(self) -> dict:
        with self._lock:
            return {"prompts": len(self._items),
                    "revisions": sum(len(v) for v in self._items.values())}
