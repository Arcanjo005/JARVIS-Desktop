"""Protected JARVIS hot-runtime bootstrap.

The stable implementation lives in ``hot_update_runtime_core``.  This protected
wrapper adds one important compatibility rule: a hot runtime from an older
JARVIS release must never override a newer full installer.  That prevents stale
GUI/runtime Python files in %LOCALAPPDATA% from winning over the freshly
installed executable.

The core keeps the immutable-release errors for "conteúdo diferente" and
"novo número de versão" used by the distribution regression guards.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import hot_update_runtime_core as _core

# Re-export the public bootstrap API expected by the application and selftests.
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


def _bundled_version() -> str:
    """Return the version embedded in the full installer, before hot sys.path."""
    if not getattr(sys, "frozen", False):
        return ""
    try:
        from jarvis_version import VERSION
        return str(VERSION or "").strip()
    except Exception:
        return ""


def _clear_hot_environment() -> None:
    os.environ.pop("JARVIS_HOT_RUNTIME_DIR", None)
    os.environ.pop("JARVIS_EFFECTIVE_VERSION", None)


def activate_hot_runtime(app_dir: Path | str, *, track_boot: bool = True):
    """Activate only a hot runtime that is not older than the installed bundle."""
    bundled = _bundled_version()
    if bundled:
        root = _core.runtime_store_dir()
        active = _core._read_json(root / _core.ACTIVE_NAME)
        hot_version = str(active.get("version") or "").strip()
        if hot_version and _version_key(hot_version) < _version_key(bundled):
            _core._disable_active(
                f"runtime {hot_version} anterior ao instalador {bundled}"
            )
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
