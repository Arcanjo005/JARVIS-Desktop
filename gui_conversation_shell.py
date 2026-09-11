"""Conversation-first UI shell for JARVIS Desktop.

Keeps the main GUI implementation intact while replacing the left sidebar with
conversation history only and making the header copy action export the complete
active conversation as a shareable diagnostic report.
"""
from __future__ import annotations

from datetime import datetime

import customtkinter as ctk

from gui import JarvisGUI as BaseJarvisGUI
from jarvis_version import VERSION as JARVIS_VERSION, BUILD as JARVIS_BUILD, PUBLIC_NAME


class JarvisGUI(BaseJarvisGUI):
    """JARVIS GUI with a ChatGPT-like conversation sidebar."""

    def _create_system_monitor(self, parent):
        """Left column is dedicated to conversation navigation only."""
        side = ctk.CTkFrame(parent, fg_color="transparent")
        side.pack(fill="both", expand=True, padx=9, pady=10)

        head = ctk.CTkFrame(side, fg_color="transparent")
        head.pack(fill="x", padx=3, pady=(2, 10))
        ctk.CTkLabel(
            head,
            text="CONVERSAS",
            text_color=self.UI_TEXT,
            font=ctk.CTkFont(family="Bahnschrift", size=12, weight="bold"),
        ).pack(side="left")

        self._conversation_search_button = ctk.CTkButton(
            head,
            text="",
            image=self._get_ui_icon("search", 16, "#B8C6D7"),
            width=34,
            height=32,
            corner_radius=10,
            fg_color="transparent",
            hover_color=self.UI_SURFACE_3,
            text_color="#B8C6D7",
            command=lambda: self._open_conversation_search_popover(self._conversation_search_button),
        )
        self._conversation_search_button.pack(side="right", padx=(3, 0))

        self._new_chat_button = ctk.CTkButton(
            side,
            text="NOVA CONVERSA",
            image=self._get_ui_icon("new_chat", 16, "#D7E8F8"),
            height=38,
            corner_radius=11,
            fg_color=self.UI_SURFACE_2,
            border_width=1,
            border_color=self.UI_BORDER_STRONG,
            hover_color=self.UI_SURFACE_3,
            text_color="#D7E8F8",
            compound="left",
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold"),
            command=self._new_conversation,
        )
        self._new_chat_button.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            side,
            text="HISTÓRICO",
            anchor="w",
            text_color=self.UI_MUTED_2,
            font=ctk.CTkFont(family="Consolas", size=7, weight="bold"),
        ).pack(fill="x", padx=3, pady=(2, 4))

        self.conversation_list_frame = ctk.CTkScrollableFrame(
            side,
            fg_color="transparent",
            corner_radius=0,
            border_width=0,
            scrollbar_button_color="#172638",
            scrollbar_button_hover_color="#24435E",
        )
        self.conversation_list_frame.pack(fill="both", expand=True, pady=(0, 8))

        footer = ctk.CTkLabel(
            side,
            text=f"{PUBLIC_NAME} {JARVIS_VERSION}",
            text_color="#435165",
            font=ctk.CTkFont(family="Consolas", size=7),
        )
        footer.pack(anchor="w", padx=3, pady=(3, 0))

        # Metrics/log widgets intentionally stay out of the sidebar. They remain
        # accessible through the three-dot controls/diagnostics.
        self.cpu_gauge = None
        self.ram_gauge = None
        self.network_gauge = None
        self.active_app_label = None
        self.media_value_label = None
        self.context_app_label = None
        self.context_site_label = None
        self.context_goal_label = None
        self.context_download_label = None
        self.system_log_frame = None
        self.system_log_text = None
        self.monitor_visible = False

        self.root.after(80, self._refresh_conversation_list)

    def _create_chat_area(self, parent):
        super()._create_chat_area(parent)
        # The base layout already places the copy action at the upper-right.
        # Make its purpose explicit without duplicating another control.
        try:
            for widget in parent.winfo_children():
                for child in self._walk_widgets(widget):
                    try:
                        if isinstance(child, ctk.CTkButton) and str(child.cget("text") or "") == "COPIAR":
                            child.configure(text="COPIAR CONVERSA", width=126)
                            return
                    except Exception:
                        continue
        except Exception:
            pass

    @staticmethod
    def _walk_widgets(widget):
        yield widget
        try:
            for child in widget.winfo_children():
                yield from JarvisGUI._walk_widgets(child)
        except Exception:
            return

    def _copy_everything(self):
        """Copy the complete active conversation as a paste-ready report."""
        conversation_id = int(self.active_conversation_id)
        title = self.memory_store.get_conversation_title(conversation_id)
        messages = self.memory_store.load_messages(conversation_id, limit=5000)

        lines = [
            "=== RELATÓRIO DE CONVERSA - JARVIS ===",
            f"Versão: {JARVIS_VERSION}",
            f"Build: {JARVIS_BUILD}",
            f"Conversa: {title}",
            f"ID da conversa: {conversation_id}",
            f"Exportado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Mensagens: {len(messages)}",
            "",
        ]

        for item in messages:
            sender = str(item.get("sender") or ("Você" if item.get("is_user") else PUBLIC_NAME)).strip()
            timestamp = str(item.get("timestamp") or "").strip()
            message = str(item.get("message") or "").strip()
            if not message:
                continue
            prefix = f"[{timestamp}] {sender}:" if timestamp else f"{sender}:"
            lines.extend((prefix, message, ""))

        if len(messages) >= 5000:
            lines.extend((
                "[AVISO] Esta conversa atingiu o limite de 5000 mensagens do exportador.",
                "",
            ))

        report = "\n".join(lines).rstrip() + "\n"
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(report)
            self.root.update_idletasks()
            self._update_status("CONVERSA COPIADA", self.UI_SUCCESS)
            self.root.after(1800, lambda: self._update_status("ONLINE", self.UI_SUCCESS))
        except Exception as exc:
            try:
                self.logger.error(exc, "Erro ao copiar conversa completa", "GUI")
            except Exception:
                pass
            raise
