"""Conversation-first UI shell for JARVIS Desktop.

The left rail contains only conversation history, like ChatGPT. The main chat
surface follows the approved cinematic concept while keeping the updater visible
in the native JARVIS header. Typed conversations can also be spoken through the
same VoiceEngine/TTS used by voice mode.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

import customtkinter as ctk

from gui import JarvisGUI as BaseJarvisGUI
from jarvis_version import VERSION as JARVIS_VERSION, BUILD as JARVIS_BUILD, PUBLIC_NAME


class JarvisGUI(BaseJarvisGUI):
    """JARVIS GUI with ChatGPT-like history and cinematic conversation surface."""

    CHAT_SURFACE = "#07101A"
    CHAT_SURFACE_2 = "#0A1623"
    CHAT_BORDER = "#163A55"
    CHAT_ACCENT = "#31BFFF"
    CHAT_YELLOW = "#FFD840"

    def _load_chat_tts_preference(self) -> bool:
        try:
            path = Path(self.project_dir) / "data" / "ui_layout.json"
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8")) or {}
                value = payload.get("chat_tts_enabled")
                if value is not None:
                    return bool(value)
        except Exception:
            pass
        # The approved conversation design speaks replies by default.
        return True

    def _save_chat_tts_preference(self) -> None:
        try:
            path = Path(self.project_dir) / "data" / "ui_layout.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {}
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    payload = {}
            payload["chat_tts_enabled"] = bool(getattr(self, "_chat_tts_enabled", True))
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _create_system_monitor(self, parent):
        """Left column contains conversations only; no telemetry duplication."""
        side = ctk.CTkFrame(parent, fg_color="transparent")
        side.pack(fill="both", expand=True, padx=10, pady=11)

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=3, pady=(1, 10))
        ctk.CTkLabel(
            brand, text="CONVERSAS", text_color="#EAF6FF",
            font=ctk.CTkFont(family="Bahnschrift", size=13, weight="bold"),
        ).pack(side="left")

        self._conversation_search_button = ctk.CTkButton(
            brand, text="", image=self._get_ui_icon("search", 16, "#A9C7DE"),
            width=34, height=32, corner_radius=10, fg_color="transparent",
            hover_color="#10263A", text_color="#A9C7DE",
            command=lambda: self._open_conversation_search_popover(self._conversation_search_button),
        )
        self._conversation_search_button.pack(side="right", padx=(4, 0))

        self._new_chat_button = ctk.CTkButton(
            side, text="NOVA CONVERSA", image=self._get_ui_icon("new_chat", 16, "#DDF2FF"),
            height=40, corner_radius=12, fg_color="#0E2233",
            border_width=1, border_color="#1A4B6A",
            hover_color="#15344E", text_color="#DDF2FF", compound="left",
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold"),
            command=self._new_conversation,
        )
        self._new_chat_button.pack(fill="x", pady=(0, 10))

        ctk.CTkFrame(side, height=1, fg_color="#122C40").pack(fill="x", pady=(0, 8))

        self.conversation_list_frame = ctk.CTkScrollableFrame(
            side, fg_color="transparent", corner_radius=0, border_width=0,
            scrollbar_button_color="#142A3D", scrollbar_button_hover_color="#23506F",
        )
        self.conversation_list_frame.pack(fill="both", expand=True, pady=(0, 8))

        footer = ctk.CTkFrame(side, fg_color="transparent")
        footer.pack(fill="x", padx=2, pady=(5, 0))
        ctk.CTkLabel(
            footer, text=f"{PUBLIC_NAME} {JARVIS_VERSION}", text_color="#49677D",
            font=ctk.CTkFont(family="Consolas", size=7),
        ).pack(side="left")
        ctk.CTkLabel(
            footer, text="● ONLINE", text_color="#35DFA2",
            font=ctk.CTkFont(family="Consolas", size=7, weight="bold"),
        ).pack(side="right")

        # These continue to exist logically, but not as permanent sidebar widgets.
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
        self.root.after(70, self._refresh_conversation_list)

    def _create_chat_area(self, parent):
        """Approved cinematic chat: conversation first, voice-aware, no extra orb."""
        self._chat_tts_enabled = self._load_chat_tts_preference()
        self._chat_text_turn_should_speak = False
        self._conversation_voice_labels = {}

        wrapper = ctk.CTkFrame(parent, fg_color=self.UI_BG)
        wrapper.pack(fill="both", expand=True, padx=(12, 7), pady=(7, 8))

        # Top identity row. The global header above still owns the always-visible
        # ATUALIZAR button, API control and application status.
        top = ctk.CTkFrame(wrapper, fg_color="transparent", height=54)
        top.pack(fill="x", padx=9, pady=(0, 8))

        title_box = ctk.CTkFrame(top, fg_color="transparent")
        title_box.pack(side="left", fill="y")
        ctk.CTkLabel(
            title_box, text="CONVERSA ATIVA", text_color="#5BCBFF",
            font=ctk.CTkFont(family="Consolas", size=7, weight="bold"),
        ).pack(anchor="w", pady=(2, 0))
        self.current_conversation_label = ctk.CTkLabel(
            title_box, text="Nova conversa", text_color="#F4F9FD",
            font=ctk.CTkFont(family="Bahnschrift", size=18, weight="bold"),
        )
        self.current_conversation_label.pack(anchor="w", pady=(1, 0))

        tools = ctk.CTkFrame(top, fg_color="transparent")
        tools.pack(side="right", pady=5)

        self._chat_tts_button = ctk.CTkButton(
            tools,
            text="FALA  ON" if self._chat_tts_enabled else "FALA  OFF",
            width=82, height=31, corner_radius=10,
            fg_color="#0E2B26" if self._chat_tts_enabled else "#151D27",
            hover_color="#174138" if self._chat_tts_enabled else "#202D3B",
            border_width=1,
            border_color="#27745D" if self._chat_tts_enabled else "#2A3A49",
            text_color="#7CF0BF" if self._chat_tts_enabled else "#8798A8",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
            command=self._toggle_chat_tts,
        )
        self._chat_tts_button.pack(side="left", padx=3)

        ctk.CTkButton(
            tools, text="COPIAR CONVERSA", image=self._get_ui_icon("copy", 14, "#C2D8E8"),
            width=132, height=31, corner_radius=10, fg_color="#0D1B29",
            border_width=1, border_color="#1B425C", hover_color="#132A3D",
            text_color="#C9DCE9", compound="left",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
            command=self._copy_everything,
        ).pack(side="left", padx=(3, 0))

        # Voice/status strip inspired by the selected Model B. It has no sphere,
        # so it cannot compete with the separate high-resolution Qt voice orb.
        voice_strip = ctk.CTkFrame(
            wrapper, fg_color="#081622", corner_radius=14,
            border_width=1, border_color="#123851", height=46,
        )
        voice_strip.pack(fill="x", padx=10, pady=(0, 8))
        voice_strip.pack_propagate(False)

        ctk.CTkLabel(
            voice_strip, text="JARVIS  //  VOZ", width=96,
            text_color="#7ED9FF", font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
        ).pack(side="left", padx=(12, 6))

        for key, label in (
            ("OUVINDO", "OUVINDO"),
            ("PENSANDO", "PENSANDO"),
            ("EXECUTANDO", "EXECUTANDO"),
            ("FALANDO", "FALANDO"),
        ):
            widget = ctk.CTkLabel(
                voice_strip, text=f"•  {label}", text_color="#52697C",
                font=ctk.CTkFont(family="Consolas", size=8, weight="bold"),
            )
            widget.pack(side="left", padx=8)
            self._conversation_voice_labels[key] = widget

        self._conversation_voice_detail = ctk.CTkLabel(
            voice_strip, text="Pronto para conversar", anchor="e",
            text_color="#71889A", font=ctk.CTkFont(family="Segoe UI", size=8),
        )
        self._conversation_voice_detail.pack(side="right", fill="x", expand=True, padx=(8, 13))

        # Agent HUD remains available when the autonomous planner is actually active.
        self.agent_hud = ctk.CTkFrame(
            wrapper, fg_color="#091A28", corner_radius=13,
            border_width=1, border_color="#1C5578",
        )
        hud_top = ctk.CTkFrame(self.agent_hud, fg_color="transparent")
        hud_top.pack(fill="x", padx=12, pady=(8, 1))
        self.agent_hud_title = ctk.CTkLabel(
            hud_top, text=f"{PUBLIC_NAME} // AGENT", text_color="#71D4FF",
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold"),
        )
        self.agent_hud_title.pack(side="left")
        self.agent_stop_button = ctk.CTkButton(
            hud_top, text="■ PARAR", width=70, height=23, corner_radius=8,
            fg_color="#351B24", hover_color="#512633", text_color="#FF9DAC",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
            command=self._stop_agent_goal,
        )
        self.agent_stop_button.pack(side="right")
        self.agent_hud_step = ctk.CTkLabel(
            self.agent_hud, text="", anchor="w", justify="left", wraplength=760,
            text_color="#D4E4EF", font=ctk.CTkFont(family="Segoe UI", size=10),
        )
        self.agent_hud_step.pack(fill="x", padx=12, pady=(0, 5))
        self.agent_hud_progress = ctk.CTkProgressBar(
            self.agent_hud, height=4, corner_radius=2,
            fg_color="#162638", progress_color="#32BCFF",
        )
        self.agent_hud_progress.pack(fill="x", padx=12, pady=(0, 8))
        self.agent_hud_progress.set(0.0)
        self.agent_hud.pack_forget()

        # Conversation viewport.
        chat_shell = ctk.CTkFrame(
            wrapper, fg_color=self.CHAT_SURFACE, corner_radius=18,
            border_width=1, border_color="#102B3E",
        )
        chat_shell.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        self.chat_scroll = ctk.CTkScrollableFrame(
            chat_shell, fg_color=self.CHAT_SURFACE, corner_radius=15,
            border_width=0, scrollbar_button_color="#173146",
            scrollbar_button_hover_color="#28536E",
        )
        self.chat_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        self.chat_display = None
        self._install_chat_mousewheel()

        # Floating composer matching the approved concept.
        self.input_shell = ctk.CTkFrame(
            wrapper, fg_color="#0A1724", corner_radius=24,
            border_width=1, border_color="#1D5B7E",
        )
        self.input_shell.pack(fill="x", padx=18, pady=(0, 6))

        self.quick_menu_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("dots", 18, "#A9C6D9"),
            width=40, height=40, corner_radius=14, fg_color="#10263A",
            border_width=1, border_color="#1E415A", hover_color="#183650",
            command=lambda: self._show_quick_actions_menu(self.quick_menu_button),
        )
        self.quick_menu_button.pack(side="left", padx=(8, 3), pady=7)

        self.text_input = ctk.CTkTextbox(
            self.input_shell, height=self.COMPOSER_MIN_HEIGHT, wrap="word", activate_scrollbars=False,
            font=ctk.CTkFont(family="Segoe UI", size=13), text_color="#F1F7FB",
            fg_color="transparent", border_width=0, corner_radius=0,
        )
        self.text_input.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=7)
        self.text_input.bind("<FocusIn>", self._composer_focus_in, add="+")
        self.text_input.bind("<FocusOut>", self._composer_focus_out, add="+")
        self.text_input.bind("<Return>", self._on_composer_return, add="+")
        self.text_input.bind("<KeyRelease>", self._resize_composer, add="+")
        self._composer_set_placeholder()

        self.voice_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("voice", 18, "#D3F1FF"),
            width=40, height=40, corner_radius=14, fg_color="#0D3047",
            border_width=1, border_color="#1D6286", hover_color="#154762",
            command=self._toggle_voice_visual_mode,
        )
        self.voice_button.pack(side="left", padx=4, pady=7)

        self.send_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("send", 18, "#02121B"),
            width=42, height=42, corner_radius=14, fg_color="#35C3FF",
            hover_color="#67D2FF", text_color="#02121B", command=self.send_message,
        )
        self.send_button.pack(side="left", padx=(4, 8), pady=6)

        ctk.CTkLabel(
            wrapper, text="JARVIS  |  INTELIGÊNCIA QUE TRABALHA POR VOCÊ",
            text_color="#315C76", font=ctk.CTkFont(family="Consolas", size=7),
        ).pack(pady=(1, 0))

    def _toggle_chat_tts(self):
        self._chat_tts_enabled = not bool(getattr(self, "_chat_tts_enabled", True))
        self._save_chat_tts_preference()
        try:
            self._chat_tts_button.configure(
                text="FALA  ON" if self._chat_tts_enabled else "FALA  OFF",
                fg_color="#0E2B26" if self._chat_tts_enabled else "#151D27",
                hover_color="#174138" if self._chat_tts_enabled else "#202D3B",
                border_color="#27745D" if self._chat_tts_enabled else "#2A3A49",
                text_color="#7CF0BF" if self._chat_tts_enabled else "#8798A8",
            )
        except Exception:
            pass
        if not self._chat_tts_enabled:
            try:
                if self.voice_engine:
                    self.voice_engine.stop_speaking(clear_queue=True)
            except Exception:
                pass

    def _update_conversation_voice_strip(self, state: str, detail: str = ""):
        state = str(state or "REPOUSO").upper()
        visual = "PENSANDO" if state in {"ENTENDENDO", "PROCESSANDO", "PENSANDO"} else state
        palette = {
            "OUVINDO": "#48E8B6",
            "PENSANDO": "#A98CFF",
            "EXECUTANDO": "#FFBC66",
            "FALANDO": "#5CCBFF",
        }
        for key, widget in getattr(self, "_conversation_voice_labels", {}).items():
            try:
                widget.configure(text_color=palette[key] if key == visual else "#52697C")
            except Exception:
                pass
        try:
            if state in {"REPOUSO", "AGUARDANDO"}:
                message = "Pronto para conversar"
            elif state == "SEM_MICROFONE":
                message = "Reconectando microfone"
            elif state == "RECONECTANDO":
                message = "Reconectando áudio"
            else:
                message = str(detail or visual.title()).strip()[:86]
            self._conversation_voice_detail.configure(text=message)
        except Exception:
            pass

    def _apply_voice_engine_state(self, state, detail):
        result = super()._apply_voice_engine_state(state, detail)
        self._update_conversation_voice_strip(state, detail)
        return result

    def send_message(self, event=None):
        # A text turn may speak exactly one resulting assistant response. Voice
        # turns keep using the existing progressive/interruptible TTS route.
        try:
            has_text = bool(self._composer_text().replace("\x00", "").strip())
        except Exception:
            has_text = False
        if has_text:
            self._chat_text_turn_should_speak = bool(getattr(self, "_chat_tts_enabled", True))
        return super().send_message(event=event)

    def _speak_chat_response(self, text: str) -> None:
        if not bool(getattr(self, "_chat_text_turn_should_speak", False)):
            return
        self._chat_text_turn_should_speak = False
        if not bool(getattr(self, "_chat_tts_enabled", True)):
            return
        if getattr(self, "_voice_command_active", False):
            return
        clean = " ".join(str(text or "").split()).strip()
        if not clean or not self.voice_engine:
            return
        try:
            spoken = self._voice_spoken_summary(clean)
            self.voice_engine.speak(spoken, wait=False, fast=True)
        except Exception as exc:
            try:
                self.logger.warning(f"TTS da conversa indisponível: {exc}", "VOICE")
            except Exception:
                pass

    def add_message(self, sender: str, message: str, is_user: bool = False, is_jarvis: bool = False, is_system: bool = False, speak: bool = False):
        result = super().add_message(
            sender, message, is_user=is_user, is_jarvis=is_jarvis,
            is_system=is_system, speak=speak,
        )
        if is_jarvis and not is_system and not speak:
            self._speak_chat_response(message)
        return result

    def _finish_streaming_response(self, full_response: str, token: int = 0):
        pending_before = bool(getattr(self, "_chat_text_turn_should_speak", False))
        result = super()._finish_streaming_response(full_response, token=token)
        # Some streaming paths do not pass through add_message at completion.
        # Speak only if the text-turn flag survived the base renderer.
        if pending_before and bool(getattr(self, "_chat_text_turn_should_speak", False)):
            self._speak_chat_response(full_response)
        return result

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
        report = super()._collect_diagnostic_text()
        controller = getattr(self, "qt_voice_overlay", None)
        qt_alive = False
        try:
            qt_alive = bool(controller and controller.is_alive())
        except Exception:
            qt_alive = False
        backend = "Qt/PySide6" if qt_alive else "Tk fallback/nenhum"
        visual = str(getattr(self, "_voice_visual_state", "REPOUSO") or "REPOUSO")
        compact = getattr(controller, "_last_compact", None) if controller else None
        state = str(getattr(controller, "_last_state", visual) or visual) if controller else visual
        lines = [
            "",
            "=== ESFERA / OVERLAY DETALHADO ===",
            f"Backend efetivo: {backend}",
            f"Processo Qt vivo: {'SIM' if qt_alive else 'NÃO'}",
            f"Estado enviado: {state}",
            f"Estado visual GUI: {'OCIOSO' if visual == 'REPOUSO' else visual}",
            f"Compacta: {'SIM' if compact is True else ('NÃO' if compact is False else '?')}",
            f"TTS no chat: {'ATIVO' if bool(getattr(self, '_chat_tts_enabled', True)) else 'DESATIVADO'}",
            "Contrato: uma única esfera Qt; conversa usa legenda cinematográfica e não cria segunda esfera.",
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
