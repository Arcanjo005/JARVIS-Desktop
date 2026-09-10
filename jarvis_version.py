"""Canonical public version identity for JARVIS Desktop."""
from jarvis_identity import PUBLIC_NAME, WAKE_NAME, LEGACY_NAME

VERSION = "1.1.0"
BUILD = "2026.09.10-hotbase.1"
CHANNEL = "stable"
INTERNAL_NAME = "JARVIS"


def display_version() -> str:
    return VERSION


__all__ = [
    "VERSION", "BUILD", "CHANNEL", "PUBLIC_NAME", "INTERNAL_NAME",
    "WAKE_NAME", "LEGACY_NAME", "display_version",
]
