"""Canonical public version identity for JARVIS Desktop."""
from jarvis_identity import PUBLIC_NAME, WAKE_NAME, LEGACY_NAME

VERSION = "1.2.13"
BUILD = "2026.09.11-restart-recovery.1"
CHANNEL = "stable"
INTERNAL_NAME = "JARVIS"

try:
    from jarvis_release_current_bootstrap import install as _install_release_layer
    _install_release_layer()
except Exception:
    pass


def display_version() -> str:
    return VERSION


__all__ = [
    "VERSION", "BUILD", "CHANNEL", "PUBLIC_NAME", "INTERNAL_NAME",
    "WAKE_NAME", "LEGACY_NAME", "display_version",
]
