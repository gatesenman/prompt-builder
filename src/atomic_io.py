"""Crash-safe JSON persistence shared by the prompt library and settings.

write_json_atomic():
  1. serialise first (a serialisation error never touches the file on disk)
  2. write <name>.<pid>.<tid>.tmp, flush + fsync
  3. keep the previous good file as <name>.bak (copy, so the main file is never missing)
  4. os.replace(tmp, path) — atomic on NTFS; retried because antivirus / indexers may
     briefly lock the target on Windows
read_json_safe():
  main file → .bak → newest snapshot in backups/; a corrupt main file is preserved as
  <name>.corrupt-<timestamp>.json before anything else happens.
"""
from __future__ import annotations
import json, os, shutil, threading, time
from datetime import datetime
from pathlib import Path
from typing import Any

_lock = threading.RLock()


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return  # directories cannot be fsynced on Windows; NTFS journals the rename
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def write_json_atomic(path: Path, data: Any, backup: bool = True, indent: int | None = 2) -> None:
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=False, indent=indent)
    json.loads(payload)  # paranoia: never write something we cannot read back
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if backup and path.exists():
            try:
                if _readable_json(path):
                    shutil.copy2(path, path.with_name(path.name + ".bak"))
            except OSError:
                pass
        last: Exception | None = None
        for attempt in range(12):
            try:
                os.replace(tmp, path)
                last = None
                break
            except PermissionError as e:  # file briefly locked (AV / indexer / sync client)
                last = e
                time.sleep(0.05 * (attempt + 1))
        if last is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise last
        _fsync_dir(path.parent)


def _readable_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8-sig"))
        return True
    except Exception:
        return False


def snapshot(path: Path, folder: Path, keep: int = 10, min_interval_s: int = 6 * 3600) -> Path | None:
    """Rolling dated copies (at most one per `min_interval_s`, newest `keep` kept)."""
    path, folder = Path(path), Path(folder)
    if not path.exists() or not _readable_json(path):
        return None
    with _lock:
        folder.mkdir(parents=True, exist_ok=True)
        snaps = sorted(folder.glob(path.stem + "-*.json"))
        if snaps and time.time() - snaps[-1].stat().st_mtime < min_interval_s:
            return None
        dst = folder / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}.json"
        shutil.copy2(path, dst)
        snaps.append(dst)
        for old in snaps[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
        return dst


def read_json_safe(path: Path, default: Any = None, backups_dir: Path | None = None) -> tuple[Any, str]:
    """Return (data, source) where source is 'main' | 'bak' | 'snapshot:<name>' | 'missing' | 'default'."""
    path = Path(path)
    if not path.exists():
        return default, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), "main"
    except Exception:
        pass
    # corrupt: preserve it, then fall back
    try:
        shutil.copy2(path, path.with_name(f"{path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}.json"))
    except OSError:
        pass
    candidates: list[tuple[Path, str]] = [(path.with_name(path.name + ".bak"), "bak")]
    if backups_dir and Path(backups_dir).exists():
        for p in sorted(Path(backups_dir).glob(path.stem + "-*.json"), reverse=True):
            candidates.append((p, "snapshot:" + p.name))
    for cand, label in candidates:
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8-sig")), label
            except Exception:
                continue
    return default, "default"
