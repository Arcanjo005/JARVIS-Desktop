"""Current compatibility bootstrap for JARVIS Desktop.

Keeps the proven non-blocking/router/core fixes from the old release layer while
preventing obsolete GUI and audio monkey patches from overriding modern source.

Voice visual policy:
- the modern PIL/Tk 3D orb in gui.py is the canonical renderer;
- the old concentric Qt/core reactor is retired;
- persisted `core` settings are migrated to `crystal` automatically;
- conversation mode never means permanent OUVINDO.
"""
from __future__ import annotations

import sys

import jarvis_release_123_bootstrap as _legacy


def _normalize_orb_style(value: object) -> str:
    style = str(value or "crystal").strip().lower()
    # `core` is the retired concentric/pixelated reactor. Keep the alias only
    # so old ui_layout.json files cannot resurrect it after an update.
    if style == "core":
        return "crystal"
    if style not in {"crystal", "rings", "pulse", "minimal"}:
        return "crystal"
    return style


def _patch_current_gui() -> None:
    mod = sys.modules.get("gui")
    cls = getattr(mod, "JarvisGUI", None) if mod is not None else None
    if cls is None or "gui" in _legacy._PATCHED:
        return

    original_load_orb_style = getattr(cls, "_load_orb_style", None)
    original_save_orb_style = getattr(cls, "_save_orb_style", None)
    original_set_orb_style = getattr(cls, "_set_orb_style", None)
    original_render_orb_frame = getattr(cls, "_render_orb_frame", None)

    def load_orb_style(self):
        value = "crystal"
        if callable(original_load_orb_style):
            try:
                value = original_load_orb_style(self)
            except Exception:
                value = "crystal"
        return _normalize_orb_style(value)

    def set_orb_style(self, style: str, announce: bool = True):
        value = _normalize_orb_style(style)
        if callable(original_set_orb_style):
            result = original_set_orb_style(self, value, announce=announce)
        else:
            self.voice_orb_style = value
            result = value
        # Persist the migrated choice so a legacy `core` value cannot return.
        try:
            self.voice_orb_style = value
            if callable(original_save_orb_style):
                original_save_orb_style(self)
        except Exception:
            pass
        return result

    def show_orb_style_menu(self, widget=None):
        """Only current visual identities are exposed; legacy Core is gone."""
        anchor = widget or getattr(self, "quick_menu_button", None) or getattr(self, "voice_button", None)
        labels = [
            ("Cristal  -  3D giratório", "crystal"),
            ("Anéis  -  holográfico/HUD", "rings"),
            ("Pulso  -  orgânico e responsivo", "pulse"),
            ("Minimal  -  discreto e limpo", "minimal"),
        ]
        entries = []
        active = _normalize_orb_style(getattr(self, "voice_orb_style", "crystal"))
        for label, style in labels:
            prefix = "● " if style == active else "   "
            entries.append((prefix + label, lambda st=style: self._set_orb_style(st)))
        try:
            return self._popup_dark_menu(anchor, entries, upward=True)
        except Exception:
            return None

    def render_orb_frame(self):
        # Last-resort migration guard for an already-running instance or a
        # manually edited ui_layout.json.
        if str(getattr(self, "voice_orb_style", "")).strip().lower() == "core":
            self.voice_orb_style = "crystal"
        if callable(original_render_orb_frame):
            return original_render_orb_frame(self)
        return None

    def disable_legacy_qt_orb(self, *args, **kwargs):
        """Do not let the later Qt/core renderer replace the approved 3D orb."""
        controller = getattr(self, "qt_voice_overlay", None)
        if controller is not None:
            try:
                controller.stop()
            except Exception:
                pass
        self.qt_voice_overlay = None
        self._qt_overlay_active = False
        return False

    def open_3d_voice_overlay(self):
        """Open the rotating PIL/Tk orb directly; never route through Qt/core."""
        disable_legacy_qt_orb(self)
        self.voice_orb_style = _normalize_orb_style(getattr(self, "voice_orb_style", "crystal"))
        try:
            if callable(original_save_orb_style):
                original_save_orb_style(self)
        except Exception:
            pass
        opener = getattr(self, "_open_voice_overlay_tk", None)
        result = opener() if callable(opener) else None
        try:
            self.root.after(80, self._settle_voice_idle)
        except Exception:
            pass
        return result

    def conversation_visual_lock_active(self) -> bool:
        # The actual VoiceEngine state is the visual source of truth. Keeping a
        # permanent conversation lock made the orb green/OUVINDO while idle.
        return False

    def sync_conversation_overlay_lock(self, enabled=None):
        # Qt/core is retired; keep the method as a compatibility no-op.
        return False

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
        if capturing:
            self._voice_visual_state = "OUVINDO"
            self._voice_engine_state = "OUVINDO"
            return
        self._voice_visual_state = "REPOUSO"
        self._voice_engine_state = "AGUARDANDO"
        try:
            self._set_voice_overlay_text(f"{getattr(mod, 'PUBLIC_NAME', 'JARVIS')} está pronto.")
        except Exception:
            pass

    cls._load_orb_style = load_orb_style
    cls._set_orb_style = set_orb_style
    cls._show_orb_style_menu = show_orb_style_menu
    cls._render_orb_frame = render_orb_frame
    cls._setup_qt_voice_overlay = disable_legacy_qt_orb
    cls._open_voice_overlay = open_3d_voice_overlay
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
