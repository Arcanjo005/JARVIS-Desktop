"""Stable hot-runtime bootstrap for JARVIS Desktop.

This module is bundled inside JARVIS.exe and is intentionally small. Normal
application updates are installed under ``%LOCALAPPDATA%/JARVIS/runtime`` and are
loaded before the modules embedded by PyInstaller. This lets interface, dialog,
agent and automation fixes ship without rebuilding the Windows executable.

Security / recovery guarantees:
- hot packages may contain Python source only;
- main.py and this bootstrap can never be replaced by a hot package;
- every file is SHA-256 verified against runtime_manifest.json;
- ZIP path traversal and duplicate entries are rejected;
- activation is atomic;
- two failed boots automatically roll back to the previous runtime (or bundled
  code when no previous runtime exists).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

HOT_RUNTIME_API = 1
MANIFEST_NAME = "runtime_manifest.json"
ACTIVE_NAME = "active.json"
BOOTING_NAME = "booting.json"
MAX_RUNTIME_FILES = 220
MAX_RUNTIME_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_FAILED_BOOTS = 2
PROTECTED_HOT_PATHS = {
    "main.py",
    "hot_update_runtime.py",
}
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:[A-Za-z0-9_.+-]*)?$")
_SHA_RE = re.compile(r"[0-9a-f]{64}$")


@dataclass(frozen=True)
class RuntimeActivation:
    version: str
    path: Path
    runtime_api: int


def _local_appdata() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    if os.name == "nt":
        return Path.home() / "AppData" / "Local"
    return Path.home() / ".local" / "share"


def runtime_store_dir() -> Path:
    path = _local_appdata() / "JARVIS" / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except Exception:
            pass


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _safe_relative(value: object) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or "\x00" in raw:
        raise ValueError("Caminho vazio/absoluto em hot update.")
    pure = PurePosixPath(raw)
    parts = pure.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Caminho inseguro em hot update: {raw}")
    if ":" in parts[0]:
        raise ValueError(f"Caminho de unidade não permitido: {raw}")
    normalized = "/".join(parts)
    if normalized.lower() in PROTECTED_HOT_PATHS:
        raise ValueError(f"Arquivo protegido não pode ser atualizado a quente: {normalized}")
    if not normalized.lower().endswith(".py"):
        raise ValueError(f"Hot update aceita somente código Python .py: {normalized}")
    return normalized


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _validate_manifest_shape(manifest: dict, expected_version: str = "") -> tuple[str, int, list[dict]]:
    if int(manifest.get("format") or 0) != 1:
        raise ValueError("Formato de hot update não suportado.")
    runtime_api = int(manifest.get("runtime_api") or 0)
    if runtime_api != HOT_RUNTIME_API:
        raise ValueError(f"Runtime API incompatível: pacote={runtime_api}, JARVIS={HOT_RUNTIME_API}.")
    version = str(manifest.get("version") or "").strip()
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("Versão inválida no hot update.")
    if expected_version and version != str(expected_version).strip():
        raise ValueError(f"Versão do pacote ({version}) não confere com a release ({expected_version}).")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Hot update sem arquivos.")
    if len(files) > MAX_RUNTIME_FILES:
        raise ValueError("Hot update contém arquivos demais.")
    return version, runtime_api, files


def validate_runtime_dir(path: Path, expected_version: str = "") -> dict:
    path = Path(path).resolve()
    manifest_path = path / MANIFEST_NAME
    manifest = _read_json(manifest_path)
    version, runtime_api, files = _validate_manifest_shape(manifest, expected_version=expected_version)
    total = 0
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Entrada inválida no manifesto do hot update.")
        relative = _safe_relative(item.get("path"))
        key = relative.casefold()
        if key in seen:
            raise ValueError(f"Arquivo duplicado no manifesto: {relative}")
        seen.add(key)
        expected_hash = str(item.get("sha256") or "").strip().lower()
        expected_size = int(item.get("size") or -1)
        if not _SHA_RE.fullmatch(expected_hash) or expected_size < 0 or expected_size > MAX_FILE_BYTES:
            raise ValueError(f"Metadados inválidos para {relative}")
        target = (path / Path(*PurePosixPath(relative).parts)).resolve()
        try:
            target.relative_to(path)
        except ValueError:
            raise ValueError(f"Arquivo escapou da pasta de runtime: {relative}")
        if not target.is_file():
            raise ValueError(f"Arquivo ausente no runtime: {relative}")
        actual_size = target.stat().st_size
        if actual_size != expected_size:
            raise ValueError(f"Tamanho inválido no runtime: {relative}")
        total += actual_size
        if total > MAX_RUNTIME_BYTES:
            raise ValueError("Hot runtime excede o limite de tamanho.")
        if _hash_file(target) != expected_hash:
            raise ValueError(f"SHA-256 inválido no runtime: {relative}")
    return {
        "version": version,
        "runtime_api": runtime_api,
        "files": files,
        "minimum_bootstrap": str(manifest.get("minimum_bootstrap") or "").strip(),
    }


def _write_active(version: str, previous_version: str = "", failures: int = 0) -> None:
    _atomic_json(
        runtime_store_dir() / ACTIVE_NAME,
        {
            "version": version,
            "previous_version": previous_version if previous_version != version else "",
            "runtime_api": HOT_RUNTIME_API,
            "failed_boots": max(0, int(failures)),
            "activated_at": int(time.time()),
        },
    )


def _disable_active(reason: str = "") -> None:
    root = runtime_store_dir()
    active = root / ACTIVE_NAME
    if not active.exists():
        return
    stamp = int(time.time())
    disabled = root / f"active.disabled.{stamp}.json"
    try:
        os.replace(active, disabled)
        if reason:
            payload = _read_json(disabled)
            payload["disabled_reason"] = str(reason)[:400]
            _atomic_json(disabled, payload)
    except Exception:
        try:
            active.unlink(missing_ok=True)
        except Exception:
            pass


def _restore_previous(active_payload: dict, reason: str) -> Optional[RuntimeActivation]:
    root = runtime_store_dir()
    previous = str(active_payload.get("previous_version") or "").strip()
    if previous and _VERSION_RE.fullmatch(previous):
        previous_dir = root / previous
        try:
            meta = validate_runtime_dir(previous_dir, expected_version=previous)
            _write_active(previous, previous_version="", failures=0)
            return RuntimeActivation(previous, previous_dir, int(meta["runtime_api"]))
        except Exception:
            pass
    _disable_active(reason)
    return None


def activate_hot_runtime(app_dir: Path | str, *, track_boot: bool = True) -> Optional[RuntimeActivation]:
    """Activate the validated per-user runtime by prepending it to sys.path."""
    app = Path(app_dir).resolve()
    os.environ["JARVIS_APP_DIR"] = str(app)
    os.environ["JARVIS_HOT_RUNTIME_API"] = str(HOT_RUNTIME_API)
    root = runtime_store_dir()
    active_path = root / ACTIVE_NAME
    active = _read_json(active_path)
    version = str(active.get("version") or "").strip()
    if not version or not _VERSION_RE.fullmatch(version):
        return None

    if track_boot:
        previous_boot = _read_json(root / BOOTING_NAME)
        if str(previous_boot.get("version") or "") == version:
            failures = int(active.get("failed_boots") or 0) + 1
            if failures >= MAX_FAILED_BOOTS:
                fallback = _restore_previous(active, f"rollback após {failures} falhas de boot")
                try:
                    (root / BOOTING_NAME).unlink(missing_ok=True)
                except Exception:
                    pass
                if fallback is None:
                    return None
                active = _read_json(active_path)
                version = fallback.version
            else:
                _write_active(version, str(active.get("previous_version") or ""), failures=failures)
                active = _read_json(active_path)

    runtime_dir = root / version
    try:
        metadata = validate_runtime_dir(runtime_dir, expected_version=version)
    except Exception as exc:
        fallback = _restore_previous(active, f"runtime inválido: {exc}")
        if fallback is None:
            return None
        runtime_dir = fallback.path
        version = fallback.version
        metadata = validate_runtime_dir(runtime_dir, expected_version=version)

    runtime_text = str(runtime_dir)
    # Runtime must win over the PyInstaller archive and the installation folder.
    sys.path[:] = [p for p in sys.path if os.path.normcase(str(p)) != os.path.normcase(runtime_text)]
    sys.path.insert(0, runtime_text)
    os.environ["JARVIS_HOT_RUNTIME_DIR"] = runtime_text
    os.environ["JARVIS_EFFECTIVE_VERSION"] = version

    if track_boot:
        _atomic_json(
            root / BOOTING_NAME,
            {"version": version, "pid": os.getpid(), "started_at": int(time.time())},
        )
    return RuntimeActivation(version, runtime_dir, int(metadata["runtime_api"]))


def mark_hot_runtime_healthy() -> None:
    root = runtime_store_dir()
    booting = _read_json(root / BOOTING_NAME)
    version = str(booting.get("version") or "").strip()
    if not version:
        return
    active = _read_json(root / ACTIVE_NAME)
    if str(active.get("version") or "") == version:
        _write_active(version, str(active.get("previous_version") or ""), failures=0)
    try:
        (root / BOOTING_NAME).unlink(missing_ok=True)
    except Exception:
        pass


def install_hot_package(package_path: Path | str, *, expected_version: str = "") -> RuntimeActivation:
    """Validate, stage and atomically activate a downloaded hot-update ZIP."""
    package = Path(package_path).resolve()
    if not package.is_file():
        raise FileNotFoundError(str(package))
    root = runtime_store_dir()
    staging_parent = Path(tempfile.mkdtemp(prefix="jarvis-hot-stage-", dir=str(root)))
    staging = staging_parent / "runtime"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(package, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_RUNTIME_FILES + 4:
                raise ValueError("Hot update contém entradas demais.")
            names: dict[str, zipfile.ZipInfo] = {}
            uncompressed_total = 0
            for info in infos:
                if info.is_dir():
                    continue
                raw_name = str(info.filename or "").replace("\\", "/")
                if raw_name == MANIFEST_NAME:
                    safe_name = MANIFEST_NAME
                else:
                    safe_name = _safe_relative(raw_name)
                key = safe_name.casefold()
                if key in names:
                    raise ValueError(f"Entrada duplicada no ZIP: {safe_name}")
                if info.file_size < 0 or info.file_size > MAX_FILE_BYTES:
                    raise ValueError(f"Arquivo grande demais no hot update: {safe_name}")
                uncompressed_total += int(info.file_size)
                if uncompressed_total > MAX_RUNTIME_BYTES:
                    raise ValueError("Hot update excede o limite descompactado.")
                names[key] = info

            manifest_info = names.get(MANIFEST_NAME.casefold())
            if manifest_info is None:
                raise ValueError("runtime_manifest.json ausente no hot update.")
            manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
            version, runtime_api, files = _validate_manifest_shape(manifest, expected_version=expected_version)

            manifest_paths: set[str] = set()
            for item in files:
                relative = _safe_relative(item.get("path"))
                manifest_paths.add(relative.casefold())
                info = names.get(relative.casefold())
                if info is None:
                    raise ValueError(f"Arquivo do manifesto ausente no ZIP: {relative}")
                payload = archive.read(info)
                expected_size = int(item.get("size") or -1)
                expected_hash = str(item.get("sha256") or "").strip().lower()
                if len(payload) != expected_size or hashlib.sha256(payload).hexdigest().lower() != expected_hash:
                    raise ValueError(f"Integridade inválida no hot update: {relative}")
                # Syntax gate before activation. Source-only updates cannot brick
                # startup with a malformed Python file without triggering rollback.
                compile(payload.decode("utf-8"), relative, "exec")
                target = staging / Path(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)

            extra = {key for key in names if key != MANIFEST_NAME.casefold()} - manifest_paths
            if extra:
                raise ValueError("Hot update contém arquivos não declarados no manifesto.")
            (staging / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        validate_runtime_dir(staging, expected_version=version)
        final_dir = root / version
        if final_dir.exists():
            # Release versions are immutable. Nunca aceite dois conteúdos
            # diferentes com o mesmo número de versão: isso evita estado
            # ambíguo se uma release for substituída no servidor.
            validate_runtime_dir(final_dir, expected_version=version)
            existing_manifest = _hash_file(final_dir / MANIFEST_NAME)
            staged_manifest = _hash_file(staging / MANIFEST_NAME)
            if existing_manifest != staged_manifest:
                raise ValueError(
                    f"A versão {version} já existe localmente com conteúdo diferente. "
                    "Publique a correção com um novo número de versão."
                )
            shutil.rmtree(staging_parent, ignore_errors=True)
        else:
            os.replace(staging, final_dir)
            shutil.rmtree(staging_parent, ignore_errors=True)

        active = _read_json(root / ACTIVE_NAME)
        previous = str(active.get("version") or "").strip()
        if previous == version:
            previous = str(active.get("previous_version") or "").strip()
        _write_active(version, previous_version=previous, failures=0)
        try:
            (root / BOOTING_NAME).unlink(missing_ok=True)
        except Exception:
            pass
        prune_old_runtimes(keep={version, previous})
        return RuntimeActivation(version, final_dir, runtime_api)
    except Exception:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise


def prune_old_runtimes(*, keep: Optional[set[str]] = None, retain_extra: int = 1) -> None:
    root = runtime_store_dir()
    keep = {str(x) for x in (keep or set()) if x}
    candidates = []
    for child in root.iterdir():
        if child.is_dir() and _VERSION_RE.fullmatch(child.name):
            try:
                candidates.append((child.stat().st_mtime, child))
            except Exception:
                pass
    candidates.sort(reverse=True)
    spared = 0
    for _, child in candidates:
        if child.name in keep:
            continue
        if spared < max(0, int(retain_extra)):
            spared += 1
            continue
        shutil.rmtree(child, ignore_errors=True)


__all__ = [
    "HOT_RUNTIME_API",
    "RuntimeActivation",
    "activate_hot_runtime",
    "install_hot_package",
    "mark_hot_runtime_healthy",
    "prune_old_runtimes",
    "runtime_store_dir",
    "validate_runtime_dir",
]
