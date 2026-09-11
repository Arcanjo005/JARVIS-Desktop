"""Canonical public version identity for JARVIS Desktop."""
from jarvis_identity import PUBLIC_NAME, WAKE_NAME, LEGACY_NAME

VERSION = "1.2.10"
BUILD = "2026.09.11-beta-orb-restore.1"
CHANNEL = "stable"
INTERNAL_NAME = "JARVIS"

# Keep the proven compatibility fixes, but route them through the current
# adapter so obsolete 1.2.1 GUI/audio monkey patches can no longer override
# the modern source tree.
try:
    from jarvis_release_current_bootstrap import install as _install_release_layer
    _install_release_layer()
except Exception:
    # Version identity must never become a startup dependency.
    pass


def display_version() -> str:
    return VERSION


__all__ = [
    "VERSION", "BUILD", "CHANNEL", "PUBLIC_NAME", "INTERNAL_NAME",
    "WAKE_NAME", "LEGACY_NAME", "display_version",
]
