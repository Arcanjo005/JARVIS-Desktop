"""Current compatibility bootstrap for JARVIS Desktop.

The old 1.2.3 release layer still contains useful non-blocking boot, router,
actions and core compatibility fixes. It also contains two obsolete monkey
patches that must never win over the current source tree:

- the 1.2.1 full-window/sidebar renderer;
- the older VoiceEngine microphone detector.

This adapter disables only those obsolete overrides and keeps the remaining
compatibility layer active until the legacy bootstrap can be retired entirely.
"""
from __future__ import annotations

import jarvis_release_123_bootstrap as _legacy


def _skip_legacy_gui_patch() -> None:
    """Modern gui.py/gui_conversation_shell.py own all visual layout."""
    try:
        _legacy._PATCHED.add("gui")
    except Exception:
        pass


def _skip_legacy_voice_patch() -> None:
    """Modern voice_engine.py owns device probing, resampling and recovery."""
    try:
        _legacy._PATCHED.add("voice")
    except Exception:
        pass


def install() -> None:
    # _apply_loaded_patches() resolves these names from the legacy module at
    # call time, so replacing them before install() also affects later imports.
    _legacy._patch_gui = _skip_legacy_gui_patch
    _legacy._patch_voice_engine = _skip_legacy_voice_patch
    _legacy.install()


__all__ = ["install"]
