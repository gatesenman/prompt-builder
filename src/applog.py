"""Logging + crash capture.

Everything goes to <data>/logs/promptbuilder.log (rotating, 3 × 1 MB). Uncaught exceptions
in the main thread, worker threads and asyncio-less callbacks are written there too, and a
hard crash (access violation in native code) is dumped by faulthandler to crash.log.
The windowed (no console) exe has sys.stdout/stderr = None, so print() output is routed to
the log as well.
"""
from __future__ import annotations
import faulthandler, logging, os, sys, threading
from logging.handlers import RotatingFileHandler

log = logging.getLogger("pb")
_state: dict = {"path": "", "crash": None}


class _StreamToLog:
    def __init__(self, level: int):
        self.level = level

    def write(self, s: str) -> int:
        s = (s or "").rstrip()
        if s:
            log.log(self.level, s)
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def setup(version: str) -> str:
    """Idempotent. Returns the log file path ('' if the log dir is not writable)."""
    if _state["path"]:
        return _state["path"]
    try:
        from paths import logs_dir
        d = logs_dir()
        path = str(d / "promptbuilder.log")
        h = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s [%(threadName)s] %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
        _state["path"] = path
        try:
            _state["crash"] = open(d / "crash.log", "a", encoding="utf-8")
            faulthandler.enable(_state["crash"], all_threads=True)
        except Exception:
            pass
    except Exception:
        return ""
    if sys.stdout is None:
        sys.stdout = _StreamToLog(logging.INFO)  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _StreamToLog(logging.ERROR)  # type: ignore[assignment]

    def excepthook(et, ev, tb):
        log.critical("uncaught exception", exc_info=(et, ev, tb))
    sys.excepthook = excepthook

    def thook(args):
        if args.exc_type is SystemExit:
            return
        log.error("uncaught exception in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = thook
    log.info("PromptBuilder %s start pid=%s frozen=%s exe=%s", version, os.getpid(),
             bool(getattr(sys, "frozen", False)), sys.executable)
    return path


def path() -> str:
    return _state["path"]
