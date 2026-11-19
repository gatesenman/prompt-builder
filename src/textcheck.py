"""Verify the text in front of the caret before deleting the "//" trigger (2.6).

Why: with an input method composing, or in editors that react to "/", the two characters
in front of the caret are not always the "//" the user typed. Blind Backspaces could then
delete the user's own text. Before deleting we try to read what is really there:

  1. classic Edit / RichEdit controls (also WinForms text boxes): WM_GETTEXT + EM_GETSEL
  2. UI Automation TextPattern(2): caret range moved back by two characters
     (Word, browsers, WPF/UWP, Windows 11 Notepad, most modern apps)

Outcome → action
  match     the two chars are slashes ("//", "、、", "／／", "・・" from IMEs)  → delete them
  mismatch  readable but different (composition was cancelled, caret moved,
            editor rewrote the text)                                       → delete nothing
  unknown   app exposes no text (Tk, games, some Electron apps)            → delete, except
            when a Japanese/Korean IME is on (punctuation may still sit in an
            uncommitted composition), then delete nothing
Deleting nothing is always safe: at worst the "//" stays visible.
"""
from __future__ import annotations
import ctypes, re

from winapi import IS_WIN, class_name, send_message_timeout

TRIGGER_CHARS = frozenset("/、／・･")
RISKY_IME_LANGS = frozenset({0x11, 0x12})  # LANG_JAPANESE, LANG_KOREAN
_EDIT_CLASS = re.compile(r"(^|\.)edit($|\.)|richedit", re.I)
WM_GETTEXT, WM_GETTEXTLENGTH, EM_GETSEL = 0x000D, 0x000E, 0x00B0


def classify(before: str | None) -> str:
    """'match' | 'mismatch' | 'unknown' for the text read in front of the caret."""
    if before is None or "\ufffc" in before:   # embedded objects: offsets unreliable
        return "unknown"
    tail = before[-2:]
    if len(tail) == 2 and all(c in TRIGGER_CHARS for c in tail):
        return "match"
    return "mismatch"


def decide(status: str, ime_lang: int = 0, ime_open: bool | None = None) -> str:
    """'delete' (Backspace × 2) or 'keep' (leave the trigger text, insert after it)."""
    if status == "match":
        return "delete"
    if status == "mismatch":
        return "keep"
    if ime_open and ime_lang in RISKY_IME_LANGS:
        return "keep"
    return "delete"


# ------------------------------------------------------------ 1. Edit / RichEdit
def is_edit_class(cls: str) -> bool:
    return bool(cls and _EDIT_CLASS.search(cls))


def read_edit_before(hwnd: int, rich: bool, n: int = 2) -> str | None:
    """Up to n characters in front of a collapsed selection of an Edit/RichEdit control."""
    if not IS_WIN or not hwnd:
        return None
    length = send_message_timeout(hwnd, WM_GETTEXTLENGTH, 0, 0, 80)
    if length is None or length > 2_000_000:
        return None
    sel = send_message_timeout(hwnd, EM_GETSEL, 0, 0, 80)
    if sel is None or sel == 0xFFFFFFFF or length >= 0xFFFF:
        return None  # packed 16-bit positions only (cross-process safe without shared memory)
    start, end = sel & 0xFFFF, (sel >> 16) & 0xFFFF
    if start != end:
        return None  # a selection is active: not the plain "//" situation
    buf = ctypes.create_unicode_buffer(length + 2)
    got = send_message_timeout(hwnd, WM_GETTEXT, length + 2, ctypes.addressof(buf), 120)
    if got is None:
        return None
    text = buf.value
    if rich:  # RichEdit selection offsets count a paragraph break as one character
        text = text.replace("\r\n", "\r")
    if start > len(text):
        return None
    return text[max(0, start - n):start]


# ------------------------------------------------------------ 2. UI Automation
def _uia_before(uia, U, out: dict) -> None:
    el = uia.GetFocusedElement()
    if not el:
        return
    rng = None
    try:
        p2 = el.GetCurrentPattern(10024)  # TextPattern2
        if p2:
            res = p2.QueryInterface(U.IUIAutomationTextPattern2).GetCaretRange()
            rng = res[1] if isinstance(res, tuple) else res
    except Exception:
        rng = None
    if rng is None:
        p1 = el.GetCurrentPattern(10014)  # TextPattern
        if not p1:
            return
        sel = p1.QueryInterface(U.IUIAutomationTextPattern).GetSelection()
        if not sel or sel.Length < 1:
            return
        rng = sel.GetElement(0)
    if rng.CompareEndpoints(0, rng, 1) != 0:  # Start vs End: not collapsed
        out["selection"] = True
        return
    r = rng.Clone()
    moved = r.MoveEndpointByUnit(0, 0, -2)  # Start, TextUnit_Character, back 2
    out["moved"] = int(moved)
    out["text"] = r.GetText(16) or ""


def read_uia_before(timeout: float = 0.18) -> str | None:
    import caret
    out = caret.uia_run(_uia_before, timeout)
    if "text" not in out:
        return None
    text, moved = out["text"], out.get("moved", 0)
    if not text and moved:     # provider moved but returns no text: not trustworthy
        return None
    return text


# ------------------------------------------------------------ combined
def verify_trigger(focus_hwnd: int, timeout: float = 0.18) -> dict:
    """Read the two characters in front of the caret of the (re-focused) target.

    Plain Edit controls are read directly (exact and instant). RichEdit variants (Windows 11
    Notepad, WordPad, WinForms RichTextBox) have native UI Automation support, which is
    tried first because their message offsets differ between versions."""
    cls = class_name(focus_hwnd) if focus_hwnd else ""
    edit = bool(focus_hwnd and is_edit_class(cls))
    rich = "richedit" in cls.lower()

    def via_edit():
        t = read_edit_before(focus_hwnd, rich)
        return None if t is None else {"status": classify(t), "method": "edit", "text": t, "class": cls}

    def via_uia():
        try:
            t = read_uia_before(timeout)
        except Exception:
            t = None
        return None if t is None else {"status": classify(t), "method": "uia", "text": t, "class": cls}

    order = (via_uia, via_edit) if rich else ((via_edit, via_uia) if edit else (via_uia,))
    for fn in order:
        r = fn()
        if r is not None:
            return r
    return {"status": "unknown", "method": "", "text": None, "class": cls}
