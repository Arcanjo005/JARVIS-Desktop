"""Protected JARVIS hot-runtime bootstrap.

A full installer owns the desktop UI. Hot updates may patch backend Python,
but cannot replace ``main.py`` or the single-source ``gui.py`` shell.
"""
from __future__ import annotations
import json,os,re,sys
from pathlib import Path
import hot_update_runtime_core as _core
_core.PROTECTED_HOT_PATHS.update({"hot_update_runtime_core.py","gui.py"})
HOT_RUNTIME_API=_core.HOT_RUNTIME_API
MANIFEST_NAME=_core.MANIFEST_NAME
ACTIVE_NAME=_core.ACTIVE_NAME
BOOTING_NAME=_core.BOOTING_NAME
MAX_RUNTIME_FILES=_core.MAX_RUNTIME_FILES
MAX_RUNTIME_BYTES=_core.MAX_RUNTIME_BYTES
MAX_FILE_BYTES=_core.MAX_FILE_BYTES
MAX_FAILED_BOOTS=_core.MAX_FAILED_BOOTS
PROTECTED_HOT_PATHS=_core.PROTECTED_HOT_PATHS
RuntimeActivation=_core.RuntimeActivation
runtime_store_dir=_core.runtime_store_dir
validate_runtime_dir=_core.validate_runtime_dir
install_hot_package=_core.install_hot_package
mark_hot_runtime_healthy=_core.mark_hot_runtime_healthy
_VERSION_PARTS_RE=re.compile(r"^(\d+)\.(\d+)\.(\d+)")
def _version_key(value):
    m=_VERSION_PARTS_RE.match(str(value or "").strip()); return tuple(int(x) for x in m.groups()) if m else (0,0,0)
def _bundled_version(app_dir=None):
    if not getattr(sys,"frozen",False): return ""
    try:
        base=Path(app_dir or os.environ.get("JARVIS_APP_DIR") or Path(sys.executable).resolve().parent); value=str(json.loads((base/"update_config.json").read_text(encoding="utf-8")).get("bootstrap_version") or "").strip(); return value if _VERSION_PARTS_RE.match(value) else ""
    except Exception:return ""
def _clear_hot_environment():
    os.environ.pop("JARVIS_HOT_RUNTIME_DIR",None); os.environ.pop("JARVIS_EFFECTIVE_VERSION",None)
def activate_hot_runtime(app_dir,*,track_boot=True):
    bundled=_bundled_version(app_dir)
    if bundled:
        root=_core.runtime_store_dir(); active=_core._read_json(root/_core.ACTIVE_NAME); hot=str(active.get("version") or "").strip()
        if hot and _version_key(hot)<=_version_key(bundled):
            _core._disable_active(f"runtime {hot} substituido pelo instalador completo {bundled}")
            try:(root/_core.BOOTING_NAME).unlink(missing_ok=True)
            except Exception:pass
            _clear_hot_environment(); os.environ["JARVIS_BUNDLED_VERSION"]=bundled; os.environ["JARVIS_EFFECTIVE_VERSION"]=bundled; return None
    activation=_core.activate_hot_runtime(app_dir,track_boot=track_boot)
    if bundled:
        os.environ["JARVIS_BUNDLED_VERSION"]=bundled
        if activation is None: os.environ.setdefault("JARVIS_EFFECTIVE_VERSION",bundled)
    return activation
