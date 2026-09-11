"""Current compatibility bootstrap for JARVIS Desktop.

Keeps the proven non-blocking/router/core fixes from the old release layer while
preventing obsolete GUI and audio monkey patches from overriding modern source.

The voice overlay is a separate smooth 3D Qt process. If Qt is unavailable, the
Tk/PIL fallback is deliberately throttled and yields to UI backlog so a visual
animation can never monopolize the main Tk event loop again.
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

    def conversation_visual_lock_active(self) -> bool:
        # Conversation mode changes size/captions only. The VoiceEngine remains
        # authoritative for listening/thinking/speaking states.
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
        """Emergency renderer that cannot saturate Tk's main loop.

        1.2.10 rendered a full PIL frame and created a new Tk PhotoImage roughly
        every 33 ms in the same thread that handles chat/clicks. That could be
        smooth initially and later starve the event loop under accumulated UI
        load. Qt is now the primary renderer; this path is only a bounded
        fallback.
        """
        self.voice_orb_animation_job = None
        if not getattr(self, "voice_visual_mode", False):
            return
        root = getattr(self, "root", None)
        canvas = getattr(self, "voice_orb_canvas", None)
        if root is None or canvas is None:
            return

        # If the isolated Qt renderer is alive, Tk must do zero animation work.
        controller = getattr(self, "qt_voice_overlay", None)
        try:
            if controller is not None and controller.is_alive():
                return
        except Exception:
            pass

        try:
            if not canvas.winfo_exists():
                return
        except Exception:
            return

        # Audio captions, history restoration and streaming responses have
        # priority over an emergency visual animation.
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
            # Preserve movement while reducing main-thread pressure from ~30 FPS
            # to ~14 FPS during interaction and ~7 FPS while idle.
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

            delay = 70 if active else 140
            self.voice_orb_animation_job = root.after(delay, self._animate_voice_orb)
        except Exception as exc:
            self.voice_orb_animation_job = None
            try:
                self.logger.warning(f"Fallback visual 3D pausado: {exc}", "GUI")
            except Exception:
                pass

    cls._conversation_visual_lock_active = conversation_visual_lock_active
    cls._sync_conversation_overlay_lock = sync_conversation_overlay_lock
    cls._settle_voice_idle = settle_voice_idle
    cls._animate_voice_orb = safe_tk_orb_animation
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
