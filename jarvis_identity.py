"""Canonical JARVIS identity and configuration compatibility helpers.

Public configuration uses the JARVIS_* prefix. Existing ZERO_* variables are
still read as a legacy fallback so old installations keep working while the
runtime and UI present a single JARVIS identity.
"""
from __future__ import annotations

import os
from typing import Optional

PUBLIC_NAME = "JARVIS"
WAKE_NAME = "jarvis"
LEGACY_NAME = "ZERO"
CANONICAL_PREFIX = "JARVIS_"
LEGACY_PREFIX = "ZERO_"


def _suffix(name: str) -> str:
    key = str(name or "").strip().upper()
    if key.startswith(CANONICAL_PREFIX):
        return key[len(CANONICAL_PREFIX):]
    if key.startswith(LEGACY_PREFIX):
        return key[len(LEGACY_PREFIX):]
    return key


def env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read JARVIS_* first, then the legacy ZERO_* equivalent."""
    suffix = _suffix(name)
    canonical = CANONICAL_PREFIX + suffix
    legacy = LEGACY_PREFIX + suffix
    if canonical in os.environ:
        return os.environ.get(canonical)
    if legacy in os.environ:
        return os.environ.get(legacy)
    return default


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name, "1" if default else "0")
    return str(value or "").strip().lower() in {"1", "true", "on", "yes", "sim"}


def mirror_legacy_environment() -> None:
    """Expose both prefixes inside this process without rewriting the user's .env.

    New code can use JARVIS_* while untouched legacy modules continue to read
    ZERO_*. JARVIS_* always wins when both are present.
    """
    snapshot = dict(os.environ)
    for key, value in snapshot.items():
        if key.startswith(CANONICAL_PREFIX):
            legacy = LEGACY_PREFIX + key[len(CANONICAL_PREFIX):]
            os.environ[legacy] = value
    snapshot = dict(os.environ)
    for key, value in snapshot.items():
        if key.startswith(LEGACY_PREFIX):
            canonical = CANONICAL_PREFIX + key[len(LEGACY_PREFIX):]
            os.environ.setdefault(canonical, value)


__all__ = [
    "PUBLIC_NAME", "WAKE_NAME", "LEGACY_NAME", "CANONICAL_PREFIX",
    "LEGACY_PREFIX", "env", "env_bool", "mirror_legacy_environment",
]
