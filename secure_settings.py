"""Secure per-user settings for JARVIS Desktop.

Gemini credentials are stored outside the install directory and protected with
Windows DPAPI.  The decrypted value only lives in the current process memory.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Optional

APP_DIR_NAME = "JARVIS"
SECRET_FILENAME = "secrets.json"
_SECRET_DESCRIPTION = "JARVIS Desktop credentials"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _local_appdata() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    if os.name == "nt":
        return Path.home() / "AppData" / "Local"
    return Path.home() / ".local" / "share"


def settings_dir() -> Path:
    path = _local_appdata() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def secret_path() -> Path:
    return settings_dir() / SECRET_FILENAME


def _blob_from_bytes(data: bytes):
    if not data:
        return _DATA_BLOB(0, None), None
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _bytes_from_blob(blob: _DATA_BLOB) -> bytes:
    if not blob.cbData or not blob.pbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        # Development/test fallback only. Production Windows builds always use DPAPI.
        return b"DEV0" + base64.b64encode(data)
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, source_buffer = _blob_from_bytes(data)
    target = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        _SECRET_DESCRIPTION,
        None,
        None,
        None,
        0,
        ctypes.byref(target),
    )
    _ = source_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        return _bytes_from_blob(target)
    finally:
        if target.pbData:
            kernel32.LocalFree(target.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if data.startswith(b"DEV0"):
        return base64.b64decode(data[4:])
    if os.name != "nt":
        raise RuntimeError("Credencial DPAPI só pode ser aberta pelo usuário Windows que a salvou.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, source_buffer = _blob_from_bytes(data)
    target = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(target),
    )
    _ = source_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        return _bytes_from_blob(target)
    finally:
        if target.pbData:
            kernel32.LocalFree(target.pbData)


def normalize_api_key(value: object) -> str:
    key = str(value or "").strip().strip('"\'')
    if not key or key.lower() in {"sua_api_key_aqui", "sua_chave_api_aqui", "coloque_sua_chave_gemini_aqui"}:
        return ""
    return key


def key_looks_plausible(value: object) -> bool:
    key = normalize_api_key(value)
    if len(key) < 20 or len(key) > 512:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_\-.]+", key))


def save_gemini_api_key(value: object) -> str:
    key = normalize_api_key(value)
    if not key_looks_plausible(key):
        raise ValueError("A chave Gemini parece incompleta ou inválida.")
    payload = json.dumps({"version": 1, "gemini_api_key": key}, ensure_ascii=False).encode("utf-8")
    protected = _dpapi_protect(payload)
    envelope = {
        "version": 1,
        "protection": "windows-dpapi" if os.name == "nt" else "development-fallback",
        "payload": base64.b64encode(protected).decode("ascii"),
    }
    path = secret_path()
    fd, temp_name = tempfile.mkstemp(prefix="jarvis-secret-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        try:
            os.chmod(temp_name, 0o600)
        except Exception:
            pass
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except Exception:
            pass
    os.environ["GEMINI_API_KEY"] = key
    return key


def load_gemini_api_key() -> str:
    path = secret_path()
    if not path.exists():
        return ""
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        protected = base64.b64decode(str(envelope.get("payload") or ""), validate=True)
        payload = json.loads(_dpapi_unprotect(protected).decode("utf-8"))
        return normalize_api_key(payload.get("gemini_api_key"))
    except Exception:
        return ""


def delete_gemini_api_key() -> None:
    try:
        secret_path().unlink(missing_ok=True)
    except TypeError:  # Python < 3.8 compatibility guard
        path = secret_path()
        if path.exists():
            path.unlink()
    os.environ.pop("GEMINI_API_KEY", None)


def bootstrap_secrets_to_env() -> str:
    """Load the protected key into this process without changing global Windows env."""
    key = load_gemini_api_key()
    if key:
        os.environ["GEMINI_API_KEY"] = key
    return key


def migrate_legacy_env(project_dir: object) -> bool:
    """Move GEMINI_API_KEY from legacy .env into DPAPI storage.

    Other .env settings are preserved. The Gemini line is removed only after the
    protected write succeeds.
    """
    if load_gemini_api_key():
        return False
    env_path = Path(project_dir) / ".env"
    if not env_path.exists():
        return False
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False
    key = ""
    kept = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped.startswith("GEMINI_API_KEY="):
            key = normalize_api_key(stripped.split("=", 1)[1])
            continue
        kept.append(line)
    if not key_looks_plausible(key):
        return False
    save_gemini_api_key(key)
    try:
        content = "\n".join(kept).rstrip() + ("\n" if kept else "")
        fd, temp_name = tempfile.mkstemp(prefix="jarvis-env-", suffix=".tmp", dir=str(env_path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp_name, env_path)
    except Exception:
        # The migration is already safe: the protected copy exists. We leave the
        # legacy file untouched if cleanup cannot be completed.
        pass
    return True


__all__ = [
    "bootstrap_secrets_to_env",
    "delete_gemini_api_key",
    "key_looks_plausible",
    "load_gemini_api_key",
    "migrate_legacy_env",
    "normalize_api_key",
    "save_gemini_api_key",
    "secret_path",
    "settings_dir",
]
