"""Current compatibility bootstrap for JARVIS Desktop.

Keeps the proven non-blocking/router/core fixes from the old release layer while
preventing obsolete GUI and audio monkey patches from overriding modern source.
It also normalizes the voice-orb state contract: conversation mode is a voice
policy, not a permanent visual OUVINDO lock.
"""
from __future__ import annotations

import sys

import jarvis_release_123_bootstrap as _legacy


def _patch_current_gui() -> None:
    mod = sys.modules.get("gui")
    cls = getattr(mod, "JarvisGUI", None) if mod is not None else None
    if cls is None or "gui" in _legacy._PATCHED:
        return

    def conversation_visual_lock_active(self) -> bool:
        # The actual VoiceEngine state is the visual source of truth. Keeping a
        # permanent conversation lock made the orb green/OUVINDO while idle.
        return False

    def sync_conversation_overlay_lock(self, enabled=None):
        if self.qt_voice_overlay:
            try:
                self.qt_voice_overlay.set_conversation_lock(False)
            except Exception:
                pass
        return False

    def settle_voice_idle(self):
        if self._pending_confirmation or self._voice_followup_after_tts:
            return
        capturing = False
        busy = False
        try:
            if self.voice_engine:
                busy = bool(self.voice_engine.speaking or getattr(self.voice_engine, "_assistant_busy", None) and self.voice_engine._assistant_busy.is_set())
                capturing = bool(
                    getattr(self.voice_engine, "_mic_capture_active", None)
                    and self.voice_engine._mic_capture_active.is_set()
                )
        except Exception:
            pass
        if busy:
            return
        if capturing:
            self._voice_visual_state = "OUVINDO"
            self._voice_engine_state = "OUVINDO"
            try:
                if self.qt_voice_overlay:
                    self.qt_voice_overlay.set_conversation_lock(False)
                    self.qt_voice_overlay.set_state("OUVINDO")
                    self.qt_voice_overlay.set_compact(False)
            except Exception:
                pass
            return
        self._voice_visual_state = "REPOUSO"
        self._voice_engine_state = "AGUARDANDO"
        try:
            if self.qt_voice_overlay:
                self.qt_voice_overlay.set_conversation_lock(False)
                self.qt_voice_overlay.set_state("REPOUSO")
                self.qt_voice_overlay.set_compact(True)
        except Exception:
            pass

    cls._conversation_visual_lock_active = conversation_visual_lock_active
    cls._sync_conversation_overlay_lock = sync_conversation_overlay_lock
    cls._settle_voice_idle = settle_voice_idle
    _legacy._PATCHED.add("gui")


def _keep_modern_voice_engine() -> None:
    mod = sys.modules.get("voice_engine")
    cls = getattr(mod, "VoiceEngine", None) if mod is not None else None
    if cls is None or "voice" in _legacy._PATCHED:
        return
    # No method replacement here. Modern voice_engine.py already has real
    # RawInputStream probing, host-API scoring, 44.1/48 kHz resampling, VAD,
    # telemetry and recovery. Marking the key blocks the obsolete detector.
    _legacy._PATCHED.add("voice")


def install() -> None:
    # The legacy import hook resolves these functions dynamically after each
    # module import. This lets us retain its other compatibility patches while
    # replacing only the two obsolete families.
    _legacy._patch_gui = _patch_current_gui
    _legacy._patch_voice_engine = _keep_modern_voice_engine
    _legacy.install()


__all__ = ["install"]
