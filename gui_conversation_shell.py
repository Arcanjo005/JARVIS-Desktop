"""Conversation-first UI shell for JARVIS Desktop.

Keeps the main GUI implementation intact while replacing the left sidebar with
conversation history only, exporting the complete active conversation, and
adding runtime diagnostics for the modern voice orb.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

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
            head, text="CONVERSAS", text_color=self.UI_TEXT,
            font=ctk.CTkFont(family="Bahnschrift", size=12, weight="bold"),
        ).pack(side="left")

        self._conversation_search_button = ctk.CTkButton(
            head, text="", image=self._get_ui_icon("search", 16, "#B8C6D7"),
            width=34, height=32, corner_radius=10, fg_color="transparent",
            hover_color=self.UI_SURFACE_3, text_color="#B8C6D7",
            command=lambda: self._open_conversation_search_popover(self._conversation_search_button),
        )
        self._conversation_search_button.pack(side="right", padx=(3, 0))

        self._new_chat_button = ctk.CTkButton(
            side, text="NOVA CONVERSA", image=self._get_ui_icon("new_chat", 16, "#D7E8F8"),
            height=38, corner_radius=11, fg_color=self.UI_SURFACE_2,
            border_width=1, border_color=self.UI_BORDER_STRONG,
            hover_color=self.UI_SURFACE_3, text_color="#D7E8F8", compound="left",
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold"),
            command=self._new_conversation,
        )
        self._new_chat_button.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            side, text="HISTÓRICO", anchor="w", text_color=self.UI_MUTED_2,
            font=ctk.CTkFont(family="Consolas", size=7, weight="bold"),
        ).pack(fill="x", padx=3, pady=(2, 4))

        self.conversation_list_frame = ctk.CTkScrollableFrame(
            side, fg_color="transparent", corner_radius=0, border_width=0,
            scrollbar_button_color="#172638", scrollbar_button_hover_color="#24435E",
        )
        self.conversation_list_frame.pack(fill="both", expand=True, pady=(0, 8))

        ctk.CTkLabel(
            side, text=f"{PUBLIC_NAME} {JARVIS_VERSION}", text_color="#435165",
            font=ctk.CTkFont(family="Consolas", size=7),
        ).pack(anchor="w", padx=3, pady=(3, 0))

        # Telemetry/actions live in the three-dot panel and diagnostics instead
        # of occupying duplicate permanent entries in the conversation sidebar.
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

    def _scroll_chat_top(self):
        try:
            canvas = getattr(self.chat_scroll, "_parent_canvas", None)
            if canvas is not None:
                canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _new_conversation(self):
        """Create a chat and keep its viewport at the beginning, never at stale Y."""
        super()._new_conversation()
        for delay in (10, 60, 160):
            try:
                self.root.after(delay, self._scroll_chat_top)
            except Exception:
                pass

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
            lines.extend(("[AVISO] Esta conversa atingiu o limite de 5000 mensagens do exportador.", ""))
        report = "\n".join(lines).rstrip() + "\n"
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self.root.update_idletasks()
        self._update_status("CONVERSA COPIADA", self.UI_SUCCESS)
        self.root.after(1800, lambda: self._update_status("ONLINE", self.UI_SUCCESS))

    def _collect_diagnostic_text(self):
        """Extend the full report with the actual orb/backend state in use."""
        report = super()._collect_diagnostic_text()
        controller = getattr(self, "qt_voice_overlay", None)
        qt_alive = False
        try:
            qt_alive = bool(controller and controller.is_alive())
        except Exception:
            qt_alive = False
        backend = "Qt/PySide6" if qt_alive else "Tk fallback/nenhum"
        style = str(getattr(self, "voice_orb_style", "core") or "core")
        visual = str(getattr(self, "_voice_visual_state", "REPOUSO") or "REPOUSO")
        compact = getattr(controller, "_last_compact", None) if controller else None
        state = str(getattr(controller, "_last_state", visual) or visual) if controller else visual
        lines = [
            "",
            "=== ESFERA / OVERLAY DETALHADO ===",
            f"Backend efetivo: {backend}",
            f"Processo Qt vivo: {'SIM' if qt_alive else 'NÃO'}",
            f"Estilo: {style}",
            f"Estado enviado: {state}",
            f"Estado visual GUI: {'OCIOSO' if visual == 'REPOUSO' else visual}",
            f"Compacta: {'SIM' if compact is True else ('NÃO' if compact is False else '?')}",
            "Contrato esperado: OCIOSO/REPOUSO=compacta; OUVINDO/PENSANDO/EXECUTANDO/FALANDO=ativa.",
        ]
        if not qt_alive:
            log_path = Path(self.project_dir) / "data" / "voice_overlay_qt.log"
            try:
                if log_path.is_file():
                    tail = [line.strip() for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()][-3:]
                    if tail:
                        lines.append("Último erro/log Qt: " + " | ".join(tail))
            except Exception:
                pass
        try:
            if self.voice_engine:
                vs = self.voice_engine.status() or {}
                lines.extend([
                    "",
                    "=== ÁUDIO / VOZ EFETIVOS ===",
                    f"Entrada PortAudio: {vs.get('input_device') or vs.get('input_device_name') or '-'}",
                    f"Host API: {vs.get('input_hostapi') or '-'}",
                    f"Captura: {vs.get('capture_mode') or '-'}  {vs.get('capture_sample_rate') or '-'}Hz -> 16000Hz",
                    f"Microfone disponível: {'SIM' if vs.get('microphone_available') else 'NÃO'}",
                    f"VAD: {vs.get('endpoint_vad') or '-'}",
                    f"STT: {vs.get('stt_backend') or '-'}",
                    f"Overflows: {vs.get('audio_driver_overflows', 0)}",
                    f"Último erro de voz: {vs.get('last_error') or '-'}",
                ])
        except Exception:
            pass
        return report + "\n" + "\n".join(lines)
