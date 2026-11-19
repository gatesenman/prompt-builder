"""Recent fill / insert history — local only, privacy-minded.

File: <data>/fill_history.json
  {"format": "promptbuilder-history", "version": 1,
   "items": [{"id", "prompt_id", "prompt_name", "values", "result", "created_at"}]}

MAX_ITEMS newest kept. Result text is capped to keep the file small.
"""
from __future__ import annotations
import threading, uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from atomic_io import read_json_safe, write_json_atomic
from paths import history_path
from prompt_syntax import normalize_newlines

FORMAT = "promptbuilder-history"
VERSION = 1
MAX_ITEMS = 100
MAX_RESULT_CHARS = 8000


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _new_id() -> str:
    return f"h-{uuid.uuid4().hex[:10]}"


def _clean(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    values = item.get("values") if isinstance(item.get("values"), dict) else {}
    clean_vals = {str(k)[:80]: str(v)[:4000] for k, v in values.items()}
    result = normalize_newlines(str(item.get("result") or ""))[:MAX_RESULT_CHARS]
    return {
        "id": str(item.get("id") or _new_id()),
        "prompt_id": str(item.get("prompt_id") or ""),
        "prompt_name": (str(item.get("prompt_name") or "").strip() or "未命名")[:120],
        "values": clean_vals,
        "result": result,
        "created_at": item.get("created_at") or _now(),
    }


class HistoryStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: list[dict] = []
        self.load()

    def load(self) -> None:
        with self._lock:
            raw, _ = read_json_safe(history_path(), {"items": []})
            items = (raw or {}).get("items") if isinstance(raw, dict) else []
            cleaned = [h for h in (_clean(x) for x in (items or [])) if h]
            cleaned.sort(key=lambda h: h["created_at"], reverse=True)
            self._items = cleaned[:MAX_ITEMS]

    def _save(self) -> None:
        write_json_atomic(history_path(), {
            "format": FORMAT, "version": VERSION, "updated_at": _now(),
            "items": self._items,
        }, backup=True)

    def list(self, *, prompt_id: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            items = self._items
            if prompt_id:
                items = [h for h in items if h["prompt_id"] == prompt_id]
            return deepcopy(items[: max(1, min(limit, MAX_ITEMS))])

    def get(self, hid: str) -> dict | None:
        with self._lock:
            for h in self._items:
                if h["id"] == hid:
                    return deepcopy(h)
        return None

    def add(self, prompt_id: str, prompt_name: str, values: dict, result: str) -> dict:
        item = _clean({
            "id": _new_id(), "prompt_id": prompt_id, "prompt_name": prompt_name,
            "values": values or {}, "result": result or "", "created_at": _now(),
        })
        assert item is not None
        with self._lock:
            self._items.insert(0, item)
            del self._items[MAX_ITEMS:]
            self._save()
            return deepcopy(item)

    def clear(self, *, prompt_id: str | None = None) -> int:
        with self._lock:
            if prompt_id:
                before = len(self._items)
                self._items = [h for h in self._items if h["prompt_id"] != prompt_id]
                n = before - len(self._items)
            else:
                n = len(self._items)
                self._items = []
            if n:
                self._save()
            return n

    def delete(self, hid: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [h for h in self._items if h["id"] != hid]
            if len(self._items) == before:
                return False
            self._save()
            return True

    def stats(self) -> dict:
        with self._lock:
            return {"count": len(self._items)}
