"""Stable release entry point for the responsive cinematic interface.

The shell keeps boot conservative on Windows machines: the GUI becomes usable
first and heavy/background services stay on demand. Normal chat speech uses a
lightweight Antonio Neural-only path, while microphone/wake mode keeps the full
VoiceEngine. Both paths therefore preserve the same voice identity without
forcing Vosk/Whisper/PortAudio to start on the first typed conversation.
"""
import customtkinter as ctk

from gui_reference_exact_v3 import (
    JarvisGUI as ResponsiveJarvisGUI,
    MessageText,
    PUBLIC_NAME,
)
from jarvis_antonio_tts import AntonioNeuralTTS
from jarvis_voice_lifecycle_136 import VoiceLifecycle136Mixin


class JarvisGUI(VoiceLifecycle136Mixin, ResponsiveJarvisGUI):
    """Responsive UI with conservative safe-boot lifecycle."""

    def __init__(self, *args, **kwargs):
        self._antonio_tts = None
        super().__init__(*args, **kwargs)

    def _v136_schedule_prewarm(self):
        """Do not auto-start microphone/voice during boot."""
        try:
            self._v136_log("info", "Boot seguro: microfone/STT permanecem sob demanda; TTS Antonio usa caminho leve.")
        except Exception:
            pass

    def _start_deferred_runtime(self):
        """Safe boot: prewarm only the conversational core automatically."""
        starter = getattr(self, "_v123_start_worker", None)
        target = getattr(getattr(self, "core", None), "prewarm", None)

        def start_core():
            if not callable(target):
                return
            if callable(starter):
                starter("JARVIS-BOOT-AI-SAFE", target)
            else:
                import threading
                threading.Thread(target=target, name="JARVIS-BOOT-AI-SAFE", daemon=True).start()

        try:
            self.root.after(1200, start_core)
        except Exception:
            start_core()

        try:
            logger = getattr(self, "logger", None)
            fn = getattr(logger, "info", None)
            if callable(fn):
                try:
                    fn(
                        "Boot seguro ativo: indice de apps, microfone/STT, updater e modulos pesados ficam sob demanda.",
                        "BOOT",
                    )
                except TypeError:
                    fn("Boot seguro ativo; servicos pesados ficam sob demanda.")
        except Exception:
            pass

    def _get_antonio_tts(self):
        engine = self._antonio_tts
        if engine is not None:
            return engine
        engine = AntonioNeuralTTS(
            project_dir=self.project_dir,
            logger=getattr(self, "logger", None),
            on_start=getattr(self, "_on_voice_tts_start", None),
            on_end=getattr(self, "_on_voice_tts_end", None),
        )
        self._antonio_tts = engine
        return engine

    def _speak(self, text: str):
        """Speak every normal chat reply with Antonio Neural without starting STT.

        If the full VoiceEngine is already active because the user intentionally
        entered microphone/wake mode, keep using it; that engine is also locked
        to pt-BR-AntonioNeural. Otherwise use the lightweight serial TTS worker.
        """
        clean = str(text or "").strip()
        if not clean:
            return None
        if hasattr(self, "_chat_tts_enabled") and not bool(getattr(self, "_chat_tts_enabled", True)):
            return None

        voice_engine = getattr(self, "voice_engine", None)
        if voice_engine is not None and bool(getattr(voice_engine, "_started", False)):
            return super()._speak(clean)

        try:
            self._get_antonio_tts().speak(clean, interrupt=True)
            return True
        except Exception as exc:
            try:
                self._v136_log("warning", f"Antonio Neural leve indisponivel: {exc}")
            except Exception:
                pass
            return None

    def _deliver_text_speech(self, text):
        """Typed chat must never start microphone/STT just to synthesize speech."""
        if not bool(getattr(self, "_chat_tts_enabled", False)):
            return None
        return self._speak(text)

    def _create_chat_bubble(self, sender, message, is_user=False, is_jarvis=False,
                            is_system=False, timestamp=None, suppress_autoscroll=False):
        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=5)
        bubble = ctk.CTkFrame(
            row,
            fg_color="#10283b" if is_user else "#081a29",
            corner_radius=12,
            border_width=1,
            border_color="#244d65" if is_user else "#12334b",
        )
        bubble.pack(fill="x", padx=(32, 2) if is_user else (2, 20))
        meta = ctk.CTkFrame(bubble, fg_color="transparent")
        meta.pack(fill="x", padx=12, pady=(7, 0))
        ctk.CTkLabel(
            meta,
            text=("VOCÊ" if is_user else PUBLIC_NAME if is_jarvis else str(sender)),
            height=20,
            text_color=self.UI_ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            meta,
            text=self._format_message_time(timestamp),
            height=20,
            text_color=self.UI_MUTED,
            font=ctk.CTkFont(size=10),
        ).pack(side="right")
        text = MessageText(
            bubble,
            str(message or ""),
            fg_color="transparent",
            border_width=0,
            text_color="#adbecb" if is_system else self.UI_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=15),
        )
        text.pack(fill="x", expand=True, padx=8, pady=(0, 6))
        self._bind_chat_mousewheel_tree(row)
        text.bind("<Control-c>", lambda event=None: self._copy_text_selection(text))
        if not suppress_autoscroll and not self._restoring_history:
            self._schedule_chat_scroll(force=is_user, delay=100)
        return text


__all__ = ["JarvisGUI"]
