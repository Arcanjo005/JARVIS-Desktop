"""Stable release entry point for the responsive cinematic interface.

The shell keeps boot conservative on Windows machines: the GUI becomes usable
first and heavy/background services stay on demand. This avoids the burst of
AI/learning/advanced/app-index/updater/voice work that can starve Tk and make
Windows report JARVIS as Not Responding.
"""
import customtkinter as ctk

from gui_reference_exact_v3 import (
    JarvisGUI as ResponsiveJarvisGUI,
    MessageText,
    PUBLIC_NAME,
)
from jarvis_voice_lifecycle_136 import VoiceLifecycle136Mixin


class JarvisGUI(VoiceLifecycle136Mixin, ResponsiveJarvisGUI):
    """Responsive UI with conservative safe-boot lifecycle."""

    def _v136_schedule_prewarm(self):
        """Do not auto-start microphone/voice during boot.

        Voice still initializes on the first explicit voice/TTS request. Keeping
        it lazy prevents Vosk/audio driver work from overlapping the GUI and
        other Windows services on lower-core systems.
        """
        try:
            self._v136_log("info", "Boot seguro: voz permanece sob demanda.")
        except Exception:
            pass

    def _start_deferred_runtime(self):
        """Safe boot: prewarm only the conversational core automatically.

        The legacy release layer scheduled learning, advanced Windows modules,
        desktop integration, app-index rebuild and updater within the first nine
        seconds. Together with voice this could saturate a 4-core CPU and leave
        Tk without message-pump time. Those subsystems remain available through
        their normal on-demand paths; automatic app-index rebuild is deliberately
        skipped because it is maintenance, not a boot requirement.
        """
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
                        "Boot seguro ativo: indice de apps, voz, updater e modulos pesados ficam sob demanda.",
                        "BOOT",
                    )
                except TypeError:
                    fn("Boot seguro ativo; servicos pesados ficam sob demanda.")
        except Exception:
            pass

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
