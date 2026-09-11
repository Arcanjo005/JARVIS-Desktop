"""Protected JARVIS hot-runtime bootstrap.

The stable implementation lives in ``hot_update_runtime_core``. This wrapper
prevents an older per-user runtime from overriding a newer full installer and,
critically, determines the bundled version without importing application
modules before the hot runtime has had a chance to win ``sys.path``.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import hot_update_runtime_core as _core

_core.PROTECTED_HOT_PATHS.add("hot_update_runtime_core.py")

HOT_RUNTIME_API = _core.HOT_RUNTIME_API
MANIFEST_NAME = _core.MANIFEST_NAME
ACTIVE_NAME = _core.ACTIVE_NAME
BOOTING_NAME = _core.BOOTING_NAME
MAX_RUNTIME_FILES = _core.MAX_RUNTIME_FILES
MAX_RUNTIME_BYTES = _core.MAX_RUNTIME_BYTES
MAX_FILE_BYTES = _core.MAX_FILE_BYTES
MAX_FAILED_BOOTS = _core.MAX_FAILED_BOOTS
PROTECTED_HOT_PATHS = _core.PROTECTED_HOT_PATHS
RuntimeActivation = _core.RuntimeActivation
runtime_store_dir = _core.runtime_store_dir
validate_runtime_dir = _core.validate_runtime_dir
install_hot_package = _core.install_hot_package
mark_hot_runtime_healthy = _core.mark_hot_runtime_healthy

_VERSION_PARTS_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def _version_key(value: object) -> tuple[int, int, int]:
    match = _VERSION_PARTS_RE.match(str(value or "").strip())
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _bundled_version(app_dir: Path | str | None = None) -> str:
    """Read the installer version without importing ``jarvis_version``.

    ``jarvis_version`` installs compatibility hooks as an import side effect.
    Importing it before the hot runtime is activated contaminates normal boot
    and can make an old bundled GUI win even when a newer runtime exists.
    ``prepare_release.py`` writes the shipped base version to update_config.json,
    so that file is the side-effect-free source of truth here.
    """
    if not getattr(sys, "frozen", False):
        return ""
    try:
        base = Path(app_dir or os.environ.get("JARVIS_APP_DIR") or Path(sys.executable).resolve().parent)
        payload = json.loads((base / "update_config.json").read_text(encoding="utf-8"))
        value = str(payload.get("bootstrap_version") or "").strip()
        return value if _VERSION_PARTS_RE.match(value) else ""
    except Exception:
        return ""


def _clear_hot_environment() -> None:
    os.environ.pop("JARVIS_HOT_RUNTIME_DIR", None)
    os.environ.pop("JARVIS_EFFECTIVE_VERSION", None)


def activate_hot_runtime(app_dir: Path | str, *, track_boot: bool = True):
    """Activate only a hot runtime that is not older than the installed bundle."""
    bundled = _bundled_version(app_dir)
    if bundled:
        root = _core.runtime_store_dir()
        active = _core._read_json(root / _core.ACTIVE_NAME)
        hot_version = str(active.get("version") or "").strip()
        if hot_version and _version_key(hot_version) < _version_key(bundled):
            _core._disable_active(f"runtime {hot_version} anterior ao instalador {bundled}")
            try:
                (root / _core.BOOTING_NAME).unlink(missing_ok=True)
            except Exception:
                pass
            _clear_hot_environment()
            os.environ["JARVIS_BUNDLED_VERSION"] = bundled
            os.environ["JARVIS_EFFECTIVE_VERSION"] = bundled
            return None

    activation = _core.activate_hot_runtime(app_dir, track_boot=track_boot)
    if activation is None and bundled:
        os.environ["JARVIS_BUNDLED_VERSION"] = bundled
        os.environ.setdefault("JARVIS_EFFECTIVE_VERSION", bundled)
    elif activation is not None and bundled:
        os.environ["JARVIS_BUNDLED_VERSION"] = bundled
    return activation
