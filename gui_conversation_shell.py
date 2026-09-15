"""Stable release entry point for the responsive cinematic interface.

The shell adds a single lifecycle owner around the proven responsive UI while
keeping a narrow compatibility fix for CTk/Tk callbacks that may invoke bound
handlers without an event object during teardown/tests.
"""
import customtkinter as ctk

from gui_reference_exact_v3 import (
    JarvisGUI as ResponsiveJarvisGUI,
    MessageText,
    PUBLIC_NAME,
)
from jarvis_voice_lifecycle_136 import VoiceLifecycle136Mixin


class JarvisGUI(VoiceLifecycle136Mixin, ResponsiveJarvisGUI):
    """Responsive UI plus the safe voice/overlay lifecycle."""

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
        # CTk/Tk can invoke this command without an event object in synthetic
        # dispatch/teardown paths. Keep Ctrl+C behavior but make event optional.
        text.bind("<Control-c>", lambda event=None: self._copy_text_selection(text))
        if not suppress_autoscroll and not self._restoring_history:
            self._schedule_chat_scroll(force=is_user, delay=100)
        return text


__all__ = ["JarvisGUI"]
