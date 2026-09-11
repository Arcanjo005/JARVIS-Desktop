"""Canonical public version identity for JARVIS Desktop."""
from jarvis_identity import PUBLIC_NAME, WAKE_NAME, LEGACY_NAME

VERSION = "1.2.4"
BUILD = "2026.09.11-interface-hotflow.1"
CHANNEL = "stable"
INTERNAL_NAME = "JARVIS"

# Chat Core, non-blocking UI and UX fixes are installed through a small compatibility layer so the
# known-good v1.1.2 startup architecture remains untouched.
try:
    from jarvis_release_123_bootstrap import install as _install_release_layer
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
