"""Protect AI API keys at rest. Windows DPAPI when available; else local key file."""
from __future__ import annotations
import base64, os, sys
from pathlib import Path

_PREFIX_DPAPI = "dpapi:"
_PREFIX_LOCAL = "local:"


def _key_path() -> Path:
    from paths import data_dir
    return data_dir() / ".ai_key"


def _local_key() -> bytes:
    p = _key_path()
    if p.exists():
        return p.read_bytes()
    key = os.urandom(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(key)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return key


def _xor(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _dpapi_protect(raw: bytes) -> bytes | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        blob_in = DATA_BLOB(len(raw), ctypes.create_string_buffer(raw, len(raw)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _dpapi_unprotect(enc: bytes) -> bytes | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        blob_in = DATA_BLOB(len(enc), ctypes.create_string_buffer(enc, len(enc)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def encrypt_secret(plain: str) -> str:
    raw = (plain or "").encode("utf-8")
    if not raw:
        return ""
    protected = _dpapi_protect(raw)
    if protected is not None:
        return _PREFIX_DPAPI + base64.b64encode(protected).decode("ascii")
    enc = _xor(raw, _local_key())
    return _PREFIX_LOCAL + base64.b64encode(enc).decode("ascii")


def decrypt_secret(token: str) -> str:
    token = token or ""
    if not token:
        return ""
    try:
        if token.startswith(_PREFIX_DPAPI):
            raw = base64.b64decode(token[len(_PREFIX_DPAPI):].encode("ascii"))
            out = _dpapi_unprotect(raw)
            return (out or b"").decode("utf-8", errors="replace")
        if token.startswith(_PREFIX_LOCAL):
            raw = base64.b64decode(token[len(_PREFIX_LOCAL):].encode("ascii"))
            return _xor(raw, _local_key()).decode("utf-8", errors="replace")
        # legacy plaintext — migrate on next save
        return token
    except Exception:
        return ""


def mask_secret(plain: str) -> str:
    s = plain or ""
    if len(s) <= 8:
        return "••••" if s else ""
    return s[:3] + "••••" + s[-4:]
