"""Current compatibility bootstrap for JARVIS Desktop.

Keeps the proven non-blocking/router/core fixes from the old release layer while
preventing obsolete GUI and audio monkey patches from overriding modern source.

The voice overlay is a separate smooth 3D Qt process. If Qt is unavailable, the
Tk/PIL fallback is deliberately throttled and yields to UI backlog so a visual
animation can never monopolize the main Tk event loop again. When Qt is alive,
any stale Tk fallback window is explicitly closed so only one orb can exist.

Shutdown policy:
- closing the main window terminates JARVIS instead of hiding an invisible
  instance in the tray;
- this prevents the next shortcut launch from finding the old mutex and doing
  nothing, which looked like a frozen application after the first successful run.
"""
from __future__ import annotations

import sys

import jarvis_release_123_bootstrap as _legacy


def _patch_current_gui() -> None:
    mod = sys.modules.get("gui")
    cls = getattr(mod, "JarvisGUI", None) if mod is not None else None
    if cls is None or "gui" in _legacy._PATCHED:
        return

    original_render_orb_frame = getattr(cls, "_render_orb_frame", None)
    original_setup_qt = getattr(cls, "_setup_qt_voice_overlay", None)
    original_on_closing = getattr(cls, "_on_closing", None)

    def conversation_visual_lock_active(self) -> bool:
        return False

    def sync_conversation_overlay_lock(self, enabled=None):
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

    def close_stale_tk_overlay(self):
        overlay = getattr(self, "voice_overlay", None)
        if overlay is not None:
            try:
                if overlay.winfo_exists():
                    overlay.destroy()
            except Exception:
                pass
        self.voice_overlay = None
        self.voice_orb_canvas = None
        self.voice_overlay_text_label = None
        self.voice_overlay_state_label = None
        job = getattr(self, "voice_orb_animation_job", None)
        if job is not None and getattr(self, "root", None):
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self.voice_orb_animation_job = None
        self._voice_orb_photo = None

    def setup_qt_voice_overlay(self):
        result = original_setup_qt(self) if callable(original_setup_qt) else None
        controller = getattr(self, "qt_voice_overlay", None)
        try:
            if controller is not None and controller.is_alive():
                close_stale_tk_overlay(self)
        except Exception:
            pass
        return result

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
                active = self._sync_conversation_overlay_lock()
                if not capturing and not active:
                    controller.set_compact(True)
        except Exception:
            pass

    def safe_tk_orb_animation(self):
        self.voice_orb_animation_job = None
        if not getattr(self, "voice_visual_mode", False):
            return
        root = getattr(self, "root", None)
        canvas = getattr(self, "voice_orb_canvas", None)
        if root is None or canvas is None:
            return

        controller = getattr(self, "qt_voice_overlay", None)
        try:
            if controller is not None and controller.is_alive():
                close_stale_tk_overlay(self)
                return
        except Exception:
            pass

        try:
            if not canvas.winfo_exists():
                return
        except Exception:
            return

        backlog = 0
        try:
            q = getattr(self, "_ui_event_queue", None)
            backlog = int(q.qsize()) if q is not None else 0
        except Exception:
            backlog = 0
        if backlog >= 32 or bool(getattr(self, "_history_restore_active", False)):
            try:
                self.voice_orb_animation_job = root.after(180, self._animate_voice_orb)
            except Exception:
                self.voice_orb_animation_job = None
            return

        state = str(getattr(self, "_voice_visual_state", "REPOUSO") or "REPOUSO").upper()
        active = state in {
            "OUVINDO", "ESCUTANDO", "ESPERANDO_RESPOSTA", "ENTENDENDO",
            "PENSANDO", "PROCESSANDO", "EXECUTANDO", "FALANDO", "ERRO",
        }
        try:
            self.voice_orb_phase += 0.085 if active else 0.035
            if not callable(original_render_orb_frame):
                return
            frame = original_render_orb_frame(self)
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(frame)
            self._voice_orb_photo = photo

            item_id = getattr(self, "_safe_orb_canvas_item", None)
            valid_item = False
            if item_id is not None:
                try:
                    valid_item = bool(canvas.type(item_id))
                except Exception:
                    valid_item = False
            if valid_item:
                canvas.itemconfigure(item_id, image=photo)
            else:
                try:
                    canvas.delete("all")
                except Exception:
                    pass
                self._safe_orb_canvas_item = canvas.create_image(0, 0, image=photo, anchor="nw")

            self.voice_orb_animation_job = root.after(70 if active else 140, self._animate_voice_orb)
        except Exception as exc:
            self.voice_orb_animation_job = None
            try:
                self.logger.warning(f"Fallback visual 3D pausado: {exc}", "GUI")
            except Exception:
                pass

    def hard_close_main_window(self):
        """Close the application instead of leaving a hidden tray instance."""
        try:
            self._exit_requested = True
        except Exception:
            pass
        if callable(original_on_closing):
            return original_on_closing(self)
        try:
            controller = getattr(self, "qt_voice_overlay", None)
            if controller:
                controller.stop()
        except Exception:
            pass
        try:
            if getattr(self, "voice_engine", None):
                self.voice_engine.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    cls._conversation_visual_lock_active = conversation_visual_lock_active
    cls._sync_conversation_overlay_lock = sync_conversation_overlay_lock
    cls._setup_qt_voice_overlay = setup_qt_voice_overlay
    cls._settle_voice_idle = settle_voice_idle
    cls._animate_voice_orb = safe_tk_orb_animation
    cls._on_closing = hard_close_main_window
    _legacy._PATCHED.add("gui")


def _keep_modern_voice_engine() -> None:
    mod = sys.modules.get("voice_engine")
    cls = getattr(mod, "VoiceEngine", None) if mod is not None else None
    if cls is None or "voice" in _legacy._PATCHED:
        return
    try:
        from jarvis_audio_reliability_patch import install as _install_audio_reliability
        _install_audio_reliability(cls)
    except Exception:
        pass
    _legacy._PATCHED.add("voice")


def install() -> None:
    _legacy._patch_gui = _patch_current_gui
    _legacy._patch_voice_engine = _keep_modern_voice_engine
    _legacy.install()


__all__ = ["install"]
