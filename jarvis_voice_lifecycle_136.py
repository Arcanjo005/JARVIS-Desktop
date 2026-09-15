"""Voice/overlay lifecycle used by the 1.3.6 responsive release shell.

The 1.2.3 compatibility layer intentionally made voice lazy, but its visual
wrapper opened the voice UI immediately while VoiceEngine/Qt were still being
created.  On real Windows machines that can hide the Tk window before a usable
Qt overlay exists, expose the old Tk fallback for a frame, and leave typed TTS
without any VoiceEngine at all.

This mixin keeps expensive voice startup off the Tk thread while giving the
release shell one owner for these transitions:
- prewarm VoiceEngine after the first UI frames so wake/TTS become available;
- coalesce concurrent/repeated startup requests;
- never hide the chat until the Qt process is alive and accepted ``show``;
- never fall back to the obsolete Tk orb when Qt startup fails;
- keep TTS usable even when no microphone is available.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional


class VoiceLifecycle136Mixin:
    VOICE_PREWARM_DELAY_MS = 2200
    VOICE_OVERLAY_SETTLE_MS = 140

    def __init__(self, *args, **kwargs):
        self._v136_voice_lock = threading.Lock()
        self._v136_voice_state = "idle"
        self._v136_voice_error = ""
        self._v136_voice_waiters = []
        self._v136_voice_open_pending = False
        self._v136_pending_speech = None
        super().__init__(*args, **kwargs)
        self._v136_schedule_prewarm()

    # ------------------------------------------------------------------
    # Thread/UI helpers
    # ------------------------------------------------------------------
    def _v136_log(self, level: str, message: str) -> None:
        try:
            logger = getattr(self, "logger", None)
            fn = getattr(logger, level, None)
            if callable(fn):
                try:
                    fn(message, "VOICE")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    def _v136_post_ui(self, callback: Optional[Callable[[], None]]) -> None:
        if not callable(callback):
            return

        def invoke():
            try:
                callback()
            except Exception as exc:
                self._v136_log("warning", f"Callback de ciclo de voz falhou: {exc}")

        try:
            post = getattr(self, "_post_ui_event", None)
            if callable(post):
                post("ui_call", invoke)
                return
        except Exception:
            pass

        # Direct invocation is safe when the caller already is the Tk thread.
        try:
            if threading.get_ident() == getattr(self, "_main_thread_id", threading.get_ident()):
                invoke()
                return
        except Exception:
            pass

        # Last resort for small test/fallback shells. Production has _post_ui_event.
        try:
            root = getattr(self, "root", None)
            if root is not None:
                root.after(0, invoke)
        except Exception:
            self._v136_log("warning", "Nao foi possivel devolver callback de voz para a UI.")

    def _v136_later(self, name: str, delay_ms: int, callback: Callable[[], None]) -> None:
        later = getattr(self, "_later", None)
        if callable(later):
            later(name, int(delay_ms), callback)
            return
        root = getattr(self, "root", None)
        if root is not None:
            root.after(int(delay_ms), callback)

    def _v136_schedule_prewarm(self) -> None:
        """Start wake/TTS after the UI is visible, not in the boot critical path."""
        try:
            self._v136_later(
                "voice-runtime-prewarm",
                self.VOICE_PREWARM_DELAY_MS,
                lambda: self._v136_ensure_voice_runtime(reason="startup-prewarm"),
            )
        except Exception as exc:
            self._v136_log("warning", f"Prewarm de voz nao foi agendado: {exc}")

    # ------------------------------------------------------------------
    # Runtime ownership
    # ------------------------------------------------------------------
    def _v136_engine_ready(self) -> bool:
        engine = getattr(self, "voice_engine", None)
        if engine is None:
            return False
        try:
            return bool(getattr(engine, "_started", True))
        except Exception:
            return True

    def _v136_overlay_ready(self) -> bool:
        controller = getattr(self, "qt_voice_overlay", None)
        if controller is None:
            return False
        try:
            return bool(controller.is_alive())
        except Exception:
            return False

    def _v136_start_worker(self, target: Callable[[], None]) -> None:
        try:
            inherited = getattr(self, "_v123_start_worker", None)
            if callable(inherited):
                inherited("JARVIS-VOICE-LIFECYCLE-136", target)
                return
        except Exception:
            pass
        threading.Thread(target=target, name="JARVIS-VOICE-LIFECYCLE-136", daemon=True).start()

    def _v136_ensure_voice_runtime(
        self,
        *,
        reason: str = "interaction",
        require_overlay: bool = False,
        on_ready: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Ensure VoiceEngine (and optionally Qt) exactly once per transition.

        Returns True only when the requested resources were already ready.  If
        startup is needed, callbacks are coalesced and dispatched on the UI
        thread when the worker finishes.
        """
        engine_ready = self._v136_engine_ready()
        overlay_ready = self._v136_overlay_ready()
        if engine_ready and (overlay_ready or not require_overlay):
            if callable(on_ready):
                self._v136_post_ui(on_ready)
            return True

        with self._v136_voice_lock:
            # Re-check after taking the lock to close the first-click race.
            engine_ready = self._v136_engine_ready()
            overlay_ready = self._v136_overlay_ready()
            if engine_ready and (overlay_ready or not require_overlay):
                immediate = True
            else:
                immediate = False
                if callable(on_ready) or callable(on_error):
                    self._v136_voice_waiters.append((bool(require_overlay), on_ready, on_error))
                if self._v136_voice_state == "starting":
                    return False
                self._v136_voice_state = "starting"
                self._v136_voice_error = ""

        if immediate:
            if callable(on_ready):
                self._v136_post_ui(on_ready)
            return True

        self._v136_log("info", f"Inicializando voz de forma idempotente ({reason}).")

        def worker():
            engine_error = ""
            overlay_error = ""
            try:
                if not self._v136_engine_ready():
                    engine = getattr(self, "voice_engine", None)
                    if engine is None:
                        setup_voice = getattr(self, "_setup_voice", None)
                        if not callable(setup_voice):
                            raise RuntimeError("_setup_voice indisponivel")
                        setup_voice()
                    else:
                        try:
                            engine.start()
                            self.voice_enabled = True
                        except Exception as exc:
                            raise RuntimeError(f"VoiceEngine nao reiniciou: {exc}") from exc
                if not self._v136_engine_ready():
                    detail = str(getattr(self, "_voice_engine_detail", "") or "").strip()
                    raise RuntimeError(detail or "VoiceEngine nao ficou pronto")
            except Exception as exc:
                engine_error = str(exc) or type(exc).__name__

            if not engine_error and not self._v136_overlay_ready():
                try:
                    setup_qt = getattr(self, "_setup_qt_voice_overlay", None)
                    if callable(setup_qt):
                        setup_qt()
                    if not self._v136_overlay_ready():
                        overlay_error = "overlay Qt 3D nao ficou disponivel"
                except Exception as exc:
                    overlay_error = str(exc) or type(exc).__name__

            with self._v136_voice_lock:
                waiters = list(self._v136_voice_waiters)
                self._v136_voice_waiters.clear()
                self._v136_voice_state = "ready" if not engine_error else "failed"
                self._v136_voice_error = engine_error or overlay_error

            if engine_error:
                self._v136_log("warning", f"Inicializacao de voz falhou: {engine_error}")
            elif overlay_error:
                # TTS/wake remain useful even when the visual process fails.
                self._v136_log("warning", f"Voz pronta; visual 3D indisponivel: {overlay_error}")
            else:
                self._v136_log("info", "VoiceEngine e overlay 3D prontos.")

            engine_ok = self._v136_engine_ready()
            overlay_ok = self._v136_overlay_ready()
            for needs_overlay, ready_cb, error_cb in waiters:
                if engine_ok and (overlay_ok or not needs_overlay):
                    self._v136_post_ui(ready_cb)
                else:
                    detail = engine_error or overlay_error or "recurso de voz indisponivel"
                    if callable(error_cb):
                        self._v136_post_ui(lambda cb=error_cb, msg=detail: cb(msg))

        self._v136_start_worker(worker)
        return False

    # ------------------------------------------------------------------
    # Visual transition: Qt only, chat is never hidden before readiness.
    # ------------------------------------------------------------------
    def _v136_close_stale_tk_orb(self) -> None:
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
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self.voice_orb_animation_job = None
        self._voice_orb_photo = None

    def _v136_visual_error(self, detail: str) -> None:
        self._v136_voice_open_pending = False
        message = "Modo de voz visual indisponivel; o chat continua aberto."
        if detail:
            self._v136_log("warning", f"{message} {detail}")
        try:
            self._set_voice_overlay_text(message)
        except Exception:
            pass
        try:
            caption = getattr(self, "_caption", None)
            if caption is not None:
                caption.configure(text=message)
        except Exception:
            pass

    def _toggle_voice_visual_mode(self):
        if bool(getattr(self, "voice_visual_mode", False)):
            self._v136_voice_open_pending = False
            return super()._close_voice_overlay()

        # A second click during startup cancels the pending visual transition;
        # the background VoiceEngine may still finish and remain useful for wake/TTS.
        if self._v136_voice_open_pending:
            self._v136_voice_open_pending = False
            try:
                self._set_voice_overlay_text("Abertura do modo de voz cancelada.")
            except Exception:
                pass
            return None

        self._v136_voice_open_pending = True
        try:
            self._set_voice_overlay_text("Preparando voz...")
        except Exception:
            pass

        def ready():
            if not self._v136_voice_open_pending:
                return
            self._v136_voice_open_pending = False
            self._open_voice_overlay()

        def failed(detail: str):
            self._v136_visual_error(detail)

        return self._v136_ensure_voice_runtime(
            reason="voice-button",
            require_overlay=True,
            on_ready=ready,
            on_error=failed,
        )

    def _open_voice_overlay(self):
        controller = getattr(self, "qt_voice_overlay", None)
        if controller is None or not self._v136_overlay_ready():
            self._v136_visual_error("overlay Qt nao esta pronto")
            return False

        self._v136_close_stale_tk_orb()
        try:
            current_state = self.root.state()
            self._root_hidden_before_voice = current_state == "withdrawn"
            self._root_state_before_voice = current_state if current_state != "withdrawn" else "normal"
        except Exception:
            self._root_hidden_before_voice = False
            self._root_state_before_voice = "normal"

        try:
            controller.set_caption("")
            controller.set_state(str(getattr(self, "_voice_visual_state", "REPOUSO") or "REPOUSO"))
            shown = controller.show(self._qt_overlay_position())
            if shown is False or not controller.is_alive():
                raise RuntimeError("processo Qt nao aceitou a exibicao")
        except Exception as exc:
            self.voice_visual_mode = False
            self._v136_visual_error(str(exc))
            return False

        # From this point there is exactly one orb owner: the Qt child.
        self.voice_visual_mode = True
        self._qt_overlay_active = True
        try:
            if self.voice_button:
                self.voice_button.configure(fg_color="#215FA8", hover_color="#2E73C7")
        except Exception:
            pass

        def hide_chat_after_settle():
            if not bool(getattr(self, "voice_visual_mode", False)):
                return
            try:
                if not controller.is_alive():
                    raise RuntimeError("overlay Qt encerrou antes do primeiro frame")
                if self.root and self.root.winfo_exists():
                    self.root.withdraw()
            except Exception as exc:
                self.voice_visual_mode = False
                try:
                    controller.hide()
                except Exception:
                    pass
                try:
                    if self.root and self.root.winfo_exists() and not self._root_hidden_before_voice:
                        self.root.deiconify()
                except Exception:
                    pass
                self._v136_visual_error(str(exc))

        self._v136_later("voice-overlay-hide-chat", self.VOICE_OVERLAY_SETTLE_MS, hide_chat_after_settle)
        return True

    def _voice_visual_click(self):
        if self._v136_engine_ready():
            return super()._voice_visual_click()

        try:
            self._set_voice_overlay_text("Preparando microfone...")
        except Exception:
            pass

        def ready():
            if self._v136_engine_ready():
                super(VoiceLifecycle136Mixin, self)._voice_visual_click()

        return self._v136_ensure_voice_runtime(
            reason="orb-click",
            require_overlay=False,
            on_ready=ready,
            on_error=lambda detail: self._v136_visual_error(detail),
        )

    # ------------------------------------------------------------------
    # TTS: text chat starts VoiceEngine instead of waiting six seconds for
    # a lazy runtime that nobody requested.
    # ------------------------------------------------------------------
    def _deliver_text_speech(self, text):
        if bool(getattr(self, "_chat_tts_enabled", False)) and not self._v136_engine_ready():
            self._v136_ensure_voice_runtime(reason="typed-response", require_overlay=False)
        return super()._deliver_text_speech(text)

    def _speak(self, text: str):
        clean = str(text or "").strip()
        if not clean:
            return None
        if self._v136_engine_ready():
            return super()._speak(clean)

        # Keep only the latest deferred non-stream speech. This prevents an old
        # reminder/status line from talking after a newer turn took ownership.
        self._v136_pending_speech = clean

        def ready():
            pending = self._v136_pending_speech
            if pending != clean:
                return
            if hasattr(self, "_chat_tts_enabled") and not bool(getattr(self, "_chat_tts_enabled", True)):
                return
            self._v136_pending_speech = None
            super(VoiceLifecycle136Mixin, self)._speak(clean)

        return self._v136_ensure_voice_runtime(
            reason="deferred-tts",
            require_overlay=False,
            on_ready=ready,
            on_error=lambda detail: self._v136_log("warning", f"TTS adiado indisponivel: {detail}"),
        )


__all__ = ["VoiceLifecycle136Mixin"]
