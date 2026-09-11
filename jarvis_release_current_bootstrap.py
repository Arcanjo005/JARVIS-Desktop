"""Current compatibility bootstrap for JARVIS Desktop.

Keeps the proven non-blocking/router/core fixes from the old release layer while
preventing obsolete GUI and audio monkey patches from overriding modern source.

Voice visual policy (validated against the user-provided beta ZIP):
- the canonical orb is the PIL/Tk `core` renderer from gui.py;
- this is the volumetric beta orb: per-pixel lighting/specular/rim, body
  rotation/float, orbital particle and state animations;
- the later Qt `core` renderer is a different, flatter concentric reactor and
  must not replace the beta renderer;
- conversation mode never means permanent OUVINDO.
"""
from __future__ import annotations

import sys

import jarvis_release_123_bootstrap as _legacy


BETA_ORB_STYLE = "core"


def _patch_current_gui() -> None:
    mod = sys.modules.get("gui")
    cls = getattr(mod, "JarvisGUI", None) if mod is not None else None
    if cls is None or "gui" in _legacy._PATCHED:
        return

    original_save_orb_style = getattr(cls, "_save_orb_style", None)
    original_render_orb_frame = getattr(cls, "_render_orb_frame", None)

    def load_beta_orb_style(self):
        # The beta archive itself persisted voice_orb_style="core". The visual
        # identity comes from gui.py's PIL renderer, not voice_overlay_qt.py.
        return BETA_ORB_STYLE

    def set_beta_orb_style(self, style: str = BETA_ORB_STYLE, announce: bool = True):
        self.voice_orb_style = BETA_ORB_STYLE
        self._orb_base_pil = None
        self._orb_base_color = None
        self._orb_base_style = None
        try:
            if callable(original_save_orb_style):
                original_save_orb_style(self)
        except Exception:
            pass
        if announce:
            try:
                self.add_message(
                    getattr(mod, "PUBLIC_NAME", "JARVIS"),
                    "Esfera Beta 3D restaurada.",
                    is_jarvis=True,
                )
            except Exception:
                pass
        return BETA_ORB_STYLE

    def show_beta_orb_style(self, widget=None):
        # There is one canonical voice identity now. Keeping alternate renderers
        # exposed made old saved settings resurrect the wrong orb.
        return set_beta_orb_style(self, announce=True)

    def render_beta_orb_frame(self):
        # Hard guard for already-running installs carrying an old ui_layout.json.
        if getattr(self, "voice_orb_style", None) != BETA_ORB_STYLE:
            self.voice_orb_style = BETA_ORB_STYLE
            self._orb_base_pil = None
            self._orb_base_color = None
            self._orb_base_style = None
        if callable(original_render_orb_frame):
            return original_render_orb_frame(self)
        return None

    def disable_qt_orb(self, *args, **kwargs):
        """The Qt reactor is not the beta orb and is intentionally disabled."""
        controller = getattr(self, "qt_voice_overlay", None)
        if controller is not None:
            try:
                controller.stop()
            except Exception:
                pass
        self.qt_voice_overlay = None
        self._qt_overlay_active = False
        return False

    def open_beta_voice_overlay(self):
        """Open exactly the beta PIL/Tk renderer path."""
        disable_qt_orb(self)
        self.voice_orb_style = BETA_ORB_STYLE
        self._orb_base_pil = None
        self._orb_base_color = None
        self._orb_base_style = None
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
        return False

    def sync_conversation_overlay_lock(self, enabled=None):
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

    cls._load_orb_style = load_beta_orb_style
    cls._set_orb_style = set_beta_orb_style
    cls._show_orb_style_menu = show_beta_orb_style
    cls._render_orb_frame = render_beta_orb_frame
    cls._setup_qt_voice_overlay = disable_qt_orb
    cls._open_voice_overlay = open_beta_voice_overlay
    cls._conversation_visual_lock_active = conversation_visual_lock_active
    cls._sync_conversation_overlay_lock = sync_conversation_overlay_lock
    cls._settle_voice_idle = settle_voice_idle
    _legacy._PATCHED.add("gui")


def _keep_modern_voice_engine() -> None:
    mod = sys.modules.get("voice_engine")
    cls = getattr(mod, "VoiceEngine", None) if mod is not None else None
    if cls is None or "voice" in _legacy._PATCHED:
        return
    # Keep the modern audio stack; only the beta visual renderer is restored.
    _legacy._PATCHED.add("voice")


def install() -> None:
    _legacy._patch_gui = _patch_current_gui
    _legacy._patch_voice_engine = _keep_modern_voice_engine
    _legacy.install()


__all__ = ["install"]
