"""Current compatibility bootstrap for JARVIS Desktop.

Keeps the proven non-blocking/router/core fixes from the old release layer while
preventing obsolete GUI and audio monkey patches from overriding modern source.

The voice overlay is now a single smooth 3D Qt identity. Conversation mode only
changes presentation size/captions; VoiceEngine remains the source of truth for
OUVINDO/ENTENDENDO/PENSANDO/FALANDO states.
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
        # Important: returning False here prevents legacy gui.py from replacing
        # every real VoiceEngine state with OUVINDO just because conversation
        # mode is enabled.
        return False

    def sync_conversation_overlay_lock(self, enabled=None):
        # The new overlay still needs to know conversation mode so it can grow
        # from the tiny idle orb and show captions. This is intentionally
        # independent from the legacy visual lock above.
        active = False
        try:
            active = bool(self.voice_engine and self.voice_engine.conversation_mode)
        except Exception:
            pass
        if not active:
            active = str(getattr(self, "interaction_mode", "") or "").lower() == "conversa"
        controller = getattr(self, "qt_voice_overlay", None)
        if controller:
            try:
                controller.set_conversation_lock(active)
            except Exception:
                pass
        return active

    def settle_voice_idle(self):
        if getattr(self, "_pending_confirmation", None) or getattr(self, "_voice_followup_after_tts", False):
            return
        capturing = False
        busy = False
        try:
            if self.voice_engine:
                busy = bool(
                    self.voice_engine.speaking
                    or (
                        getattr(self.voice_engine, "_assistant_busy", None)
                        and self.voice_engine._assistant_busy.is_set()
                    )
                )
                capturing = bool(
                    getattr(self.voice_engine, "_mic_capture_active", None)
                    and self.voice_engine._mic_capture_active.is_set()
                )
        except Exception:
            pass
        if busy:
            return
        state = "OUVINDO" if capturing else "REPOUSO"
        self._voice_visual_state = state
        self._voice_engine_state = "OUVINDO" if capturing else "AGUARDANDO"
        try:
            controller = getattr(self, "qt_voice_overlay", None)
            if controller:
                controller.set_state(state)
                self._sync_conversation_overlay_lock()
                if not capturing and not self._sync_conversation_overlay_lock():
                    controller.set_compact(True)
        except Exception:
            pass

    # Keep all modern gui.py rendering/controller methods. Only neutralize the
    # obsolete state lock and keep modern VoiceEngine untouched.
    cls._conversation_visual_lock_active = conversation_visual_lock_active
    cls._sync_conversation_overlay_lock = sync_conversation_overlay_lock
    cls._settle_voice_idle = settle_voice_idle
    _legacy._PATCHED.add("gui")


def _keep_modern_voice_engine() -> None:
    mod = sys.modules.get("voice_engine")
    cls = getattr(mod, "VoiceEngine", None) if mod is not None else None
    if cls is None or "voice" in _legacy._PATCHED:
        return
    _legacy._PATCHED.add("voice")


def install() -> None:
    _legacy._patch_gui = _patch_current_gui
    _legacy._patch_voice_engine = _keep_modern_voice_engine
    _legacy.install()


__all__ = ["install"]
