"""Cinematic conversation shell for JARVIS Desktop.

This module intentionally owns the complete visual layout instead of decorating
legacy panels. It mirrors the approved concept: conversation-only history on the
left, cinematic JARVIS core + chat in the center, and clock/system/update cards
on the right. Voice mode keeps using the isolated Qt orb process.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import math
import shutil
import time

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter, ImageColor

try:
    import psutil
except Exception:
    psutil = None

from gui import JarvisGUI as BaseJarvisGUI
from jarvis_version import VERSION as JARVIS_VERSION, BUILD as JARVIS_BUILD, PUBLIC_NAME


class JarvisGUI(BaseJarvisGUI):
    """Full cinematic JARVIS conversation UI."""

    CIN_BG = "#030912"
    CIN_PANEL = "#07111D"
    CIN_PANEL_2 = "#0A1725"
    CIN_PANEL_3 = "#0D1D2C"
    CIN_BORDER = "#12344B"
    CIN_BORDER_STRONG = "#1E658D"
    CIN_BLUE = "#32BFFF"
    CIN_BLUE_SOFT = "#86DBFF"
    CIN_TEXT = "#EDF7FF"
    CIN_MUTED = "#71889B"
    CIN_YELLOW = "#FFD84B"
    CIN_GREEN = "#34E3A4"
    CIN_PURPLE = "#A785FF"
    CIN_ORANGE = "#FFB05C"

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------
    def _ui_pref_path(self) -> Path:
        return Path(self.project_dir) / "data" / "ui_layout.json"

    def _load_chat_tts_preference(self) -> bool:
        try:
            path = self._ui_pref_path()
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8")) or {}
                if payload.get("chat_tts_enabled") is not None:
                    return bool(payload.get("chat_tts_enabled"))
        except Exception:
            pass
        return True

    def _load_caption_preference(self) -> bool:
        try:
            path = self._ui_pref_path()
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8")) or {}
                if payload.get("cinematic_captions") is not None:
                    return bool(payload.get("cinematic_captions"))
        except Exception:
            pass
        return True

    def _save_cinematic_preferences(self) -> None:
        try:
            path = self._ui_pref_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {}
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    payload = {}
            payload["chat_tts_enabled"] = bool(getattr(self, "_chat_tts_enabled", True))
            payload["cinematic_captions"] = bool(getattr(self, "_cinematic_captions_enabled", True))
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Full layout - no legacy header/pulse/sidebar survives here.
    # ------------------------------------------------------------------
    def _create_main_layout(self):
        self._chat_tts_enabled = self._load_chat_tts_preference()
        self._cinematic_captions_enabled = self._load_caption_preference()
        self._chat_text_turn_should_speak = False
        self._conversation_voice_labels = {}
        self._cinematic_orb_state = "REPOUSO"
        self._cinematic_orb_frame_index = 0
        self._cinematic_orb_frame_cache = {}
        self._cinematic_orb_job = None
        self._cinematic_metrics_job = None

        root_shell = ctk.CTkFrame(self.root, fg_color=self.CIN_BG, corner_radius=0)
        root_shell.pack(fill="both", expand=True)
        root_shell.grid_rowconfigure(0, weight=1)
        root_shell.grid_columnconfigure(0, weight=0, minsize=236)
        root_shell.grid_columnconfigure(1, weight=1, minsize=620)
        root_shell.grid_columnconfigure(2, weight=0, minsize=236)
        self.content_frame = root_shell

        left = ctk.CTkFrame(
            root_shell, width=224, fg_color="#050D17", corner_radius=18,
            border_width=1, border_color="#102A3E",
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
        left.grid_propagate(False)
        self.side_panel = left
        self.sidebar_splitter = None
        self._create_system_monitor(left)

        center = ctk.CTkFrame(root_shell, fg_color=self.CIN_BG, corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew", padx=5, pady=10)
        self._create_chat_area(center)

        right = ctk.CTkFrame(
            root_shell, width=224, fg_color="transparent", corner_radius=0,
        )
        right.grid(row=0, column=2, sticky="nsew", padx=(7, 14), pady=14)
        right.grid_propagate(False)
        self._create_cinematic_right_rail(right)

        self.root.after(80, self._animate_cinematic_orb)
        self.root.after(250, self._start_cinematic_metrics_loop)

    # ------------------------------------------------------------------
    # Left rail: brand + conversation history only.
    # ------------------------------------------------------------------
    def _create_system_monitor(self, parent):
        side = ctk.CTkFrame(parent, fg_color="transparent")
        side.pack(fill="both", expand=True, padx=12, pady=14)

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", pady=(2, 14))
        ctk.CTkLabel(
            brand, text="J A R V I S", anchor="w",
            text_color="#E7F5FF",
            font=ctk.CTkFont(family="Bahnschrift", size=22, weight="bold"),
        ).pack(fill="x")
        ctk.CTkLabel(
            brand, text="S E M P R E   A O   S E U   L A D O", anchor="w",
            text_color="#5F9ABB",
            font=ctk.CTkFont(family="Consolas", size=6, weight="bold"),
        ).pack(fill="x", pady=(1, 0))

        status_row = ctk.CTkFrame(side, fg_color="transparent")
        status_row.pack(fill="x", pady=(0, 12))
        self.status_dot = ctk.CTkLabel(
            status_row, text="●", width=13, text_color=self.CIN_GREEN,
            font=ctk.CTkFont(size=9),
        )
        self.status_dot.pack(side="left")
        self.status_label = ctk.CTkLabel(
            status_row, text="ONLINE", anchor="w", text_color="#8EA8BA",
            font=ctk.CTkFont(family="Consolas", size=8, weight="bold"),
        )
        self.status_label.pack(side="left", padx=(2, 0))
        self.activity_label = ctk.CTkLabel(
            status_row, text="Pronto", anchor="e", text_color="#4F6C80",
            font=ctk.CTkFont(family="Segoe UI", size=8),
        )
        self.activity_label.pack(side="right", fill="x", expand=True)

        title_row = ctk.CTkFrame(side, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            title_row, text="CONVERSAS", text_color="#B7CEE0",
            font=ctk.CTkFont(family="Bahnschrift", size=10, weight="bold"),
        ).pack(side="left")
        self._conversation_search_button = ctk.CTkButton(
            title_row, text="", image=self._get_ui_icon("search", 16, "#A7C8DC"),
            width=32, height=30, corner_radius=10, fg_color="transparent",
            hover_color="#10283B",
            command=lambda: self._open_conversation_search_popover(self._conversation_search_button),
        )
        self._conversation_search_button.pack(side="right")

        self._new_chat_button = ctk.CTkButton(
            side, text="NOVA CONVERSA", image=self._get_ui_icon("new_chat", 16, "#E5F5FF"),
            height=40, corner_radius=12, fg_color="#0C2132",
            border_width=1, border_color="#1A506F", hover_color="#12344D",
            text_color="#E5F5FF", compound="left",
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold"),
            command=self._new_conversation,
        )
        self._new_chat_button.pack(fill="x", pady=(0, 10))

        ctk.CTkFrame(side, height=1, fg_color="#102A3D").pack(fill="x", pady=(0, 7))

        self.conversation_list_frame = ctk.CTkScrollableFrame(
            side, fg_color="transparent", corner_radius=0, border_width=0,
            scrollbar_button_color="#122B3F", scrollbar_button_hover_color="#22506D",
        )
        self.conversation_list_frame.pack(fill="both", expand=True)

        footer = ctk.CTkFrame(side, fg_color="transparent")
        footer.pack(fill="x", pady=(9, 0))
        ctk.CTkLabel(
            footer, text=f"v{JARVIS_VERSION}", text_color="#42647A",
            font=ctk.CTkFont(family="Consolas", size=7),
        ).pack(side="left")
        ctk.CTkLabel(
            footer, text="CONVERSATION CORE", text_color="#35536A",
            font=ctk.CTkFont(family="Consolas", size=6, weight="bold"),
        ).pack(side="right")

        # Legacy monitor widgets deliberately do not exist in this design.
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

    # ------------------------------------------------------------------
    # Center: cinematic orb + subtitle + real chat + composer.
    # ------------------------------------------------------------------
    def _create_chat_area(self, parent):
        wrapper = ctk.CTkFrame(parent, fg_color=self.CIN_BG)
        wrapper.pack(fill="both", expand=True, padx=6, pady=(4, 7))

        top = ctk.CTkFrame(wrapper, fg_color="transparent", height=34)
        top.pack(fill="x", padx=8, pady=(0, 2))
        self.current_conversation_label = ctk.CTkLabel(
            top, text="Nova conversa", anchor="w", text_color="#9AB5C8",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        )
        self.current_conversation_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            top, text="", image=self._get_ui_icon("copy", 15, "#B8D1E1"),
            width=34, height=30, corner_radius=10, fg_color="#0A1825",
            border_width=1, border_color="#14364B", hover_color="#10263A",
            command=self._copy_everything,
        ).pack(side="right")

        hero = ctk.CTkFrame(wrapper, fg_color="transparent", height=228)
        hero.pack(fill="x", padx=6, pady=(0, 3))
        hero.pack_propagate(False)

        self._cinematic_orb_label = ctk.CTkLabel(
            hero, text="", width=150, height=150, fg_color="transparent",
        )
        self._cinematic_orb_label.pack(pady=(2, 0))

        subtitle_shell = ctk.CTkFrame(
            hero, fg_color="#050A10", corner_radius=9,
            border_width=1, border_color="#152C3C",
        )
        subtitle_shell.pack(pady=(1, 0), padx=42)
        self._cinematic_subtitle_label = ctk.CTkLabel(
            subtitle_shell,
            text=f"{PUBLIC_NAME}: Pronto quando você estiver.",
            text_color=self.CIN_YELLOW,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            wraplength=650, justify="center",
        )
        self._cinematic_subtitle_label.pack(padx=16, pady=7)

        self._cinematic_wave_label = ctk.CTkLabel(
            hero, text="·  ·  ▁  ▂  ▄  ▆  █  ▆  ▄  ▂  ▁  ·  ·",
            text_color="#238BC0",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
        )
        self._cinematic_wave_label.pack(pady=(3, 0))

        # Agent HUD only appears while the agent is actually doing multi-step work.
        self.agent_hud = ctk.CTkFrame(
            wrapper, fg_color="#091926", corner_radius=12,
            border_width=1, border_color="#1B5576",
        )
        hud_top = ctk.CTkFrame(self.agent_hud, fg_color="transparent")
        hud_top.pack(fill="x", padx=11, pady=(7, 1))
        self.agent_hud_title = ctk.CTkLabel(
            hud_top, text=f"{PUBLIC_NAME} // AGENT", text_color="#74D5FF",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
        )
        self.agent_hud_title.pack(side="left")
        self.agent_stop_button = ctk.CTkButton(
            hud_top, text="■ PARAR", width=68, height=22, corner_radius=8,
            fg_color="#351B24", hover_color="#512633", text_color="#FF9DAC",
            font=ctk.CTkFont(family="Bahnschrift", size=7, weight="bold"),
            command=self._stop_agent_goal,
        )
        self.agent_stop_button.pack(side="right")
        self.agent_hud_step = ctk.CTkLabel(
            self.agent_hud, text="", anchor="w", justify="left", wraplength=700,
            text_color="#D5E5EF", font=ctk.CTkFont(family="Segoe UI", size=9),
        )
        self.agent_hud_step.pack(fill="x", padx=11, pady=(0, 5))
        self.agent_hud_progress = ctk.CTkProgressBar(
            self.agent_hud, height=3, corner_radius=2,
            fg_color="#162638", progress_color=self.CIN_BLUE,
        )
        self.agent_hud_progress.pack(fill="x", padx=11, pady=(0, 7))
        self.agent_hud_progress.set(0.0)
        self.agent_hud.pack_forget()

        chat_shell = ctk.CTkFrame(
            wrapper, fg_color="#06101A", corner_radius=18,
            border_width=1, border_color="#174A67",
        )
        chat_shell.pack(fill="both", expand=True, padx=13, pady=(2, 6))

        self.chat_scroll = ctk.CTkScrollableFrame(
            chat_shell, fg_color="#06101A", corner_radius=16,
            border_width=0, scrollbar_button_color="#17344A",
            scrollbar_button_hover_color="#2A5D79",
        )
        self.chat_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        self.chat_display = None
        self._install_chat_mousewheel()

        states = ctk.CTkFrame(wrapper, fg_color="transparent", height=26)
        states.pack(fill="x", padx=34, pady=(0, 4))
        states.pack_propagate(False)
        state_box = ctk.CTkFrame(states, fg_color="transparent")
        state_box.pack(anchor="center")
        for key, label in (
            ("OUVINDO", "OUVINDO"),
            ("PENSANDO", "PENSANDO"),
            ("EXECUTANDO", "EXECUTANDO"),
            ("FALANDO", "FALANDO"),
        ):
            widget = ctk.CTkLabel(
                state_box, text=label, text_color="#516B7E",
                font=ctk.CTkFont(family="Consolas", size=8, weight="bold"),
            )
            widget.pack(side="left", padx=8)
            self._conversation_voice_labels[key] = widget
            if key != "FALANDO":
                ctk.CTkLabel(
                    state_box, text="•", text_color="#2C90BF",
                    font=ctk.CTkFont(size=8),
                ).pack(side="left", padx=1)

        self.input_shell = ctk.CTkFrame(
            wrapper, fg_color="#071521", corner_radius=25,
            border_width=1, border_color="#1C6288",
        )
        self.input_shell.pack(fill="x", padx=18, pady=(0, 6))

        self.quick_menu_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("dots", 18, "#A9C7D9"),
            width=40, height=40, corner_radius=14, fg_color="#0D2638",
            border_width=1, border_color="#1A455F", hover_color="#153750",
            command=lambda: self._show_quick_actions_menu(self.quick_menu_button),
        )
        self.quick_menu_button.pack(side="left", padx=(8, 3), pady=7)

        self.text_input = ctk.CTkTextbox(
            self.input_shell, height=self.COMPOSER_MIN_HEIGHT, wrap="word", activate_scrollbars=False,
            font=ctk.CTkFont(family="Segoe UI", size=13), text_color=self.CIN_TEXT,
            fg_color="transparent", border_width=0, corner_radius=0,
        )
        self.text_input.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=7)
        self.text_input.bind("<FocusIn>", self._composer_focus_in, add="+")
        self.text_input.bind("<FocusOut>", self._composer_focus_out, add="+")
        self.text_input.bind("<Return>", self._on_composer_return, add="+")
        self.text_input.bind("<KeyRelease>", self._resize_composer, add="+")
        self._composer_set_placeholder()

        self.voice_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("voice", 18, "#CDEEFF"),
            width=40, height=40, corner_radius=14, fg_color="#0C3047",
            border_width=1, border_color="#1D6388", hover_color="#164762",
            command=self._toggle_voice_visual_mode,
        )
        self.voice_button.pack(side="left", padx=4, pady=7)

        self.send_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("send", 18, "#02121B"),
            width=42, height=42, corner_radius=14, fg_color="#35C5FF",
            hover_color="#67D5FF", command=self.send_message,
        )
        self.send_button.pack(side="left", padx=(4, 8), pady=6)

        ctk.CTkLabel(
            wrapper, text="JARVIS  |  INTELIGÊNCIA QUE TRABALHA POR VOCÊ",
            text_color="#2B5D78", font=ctk.CTkFont(family="Consolas", size=7),
        ).pack(pady=(1, 0))

    # ------------------------------------------------------------------
    # Right rail: updater, clock, system pulse and switches.
    # ------------------------------------------------------------------
    def _create_cinematic_right_rail(self, parent):
        top_actions = ctk.CTkFrame(parent, fg_color="transparent")
        top_actions.pack(fill="x", pady=(0, 9))

        self.update_button = ctk.CTkButton(
            top_actions, text="ATUALIZAR", height=36, corner_radius=12,
            fg_color="#31BFFF", hover_color="#69D3FF", text_color="#02131D",
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold"),
            command=self._update_now,
        )
        self.update_button.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.api_button = ctk.CTkButton(
            top_actions, text="API", width=46, height=36, corner_radius=12,
            fg_color="#091827", hover_color="#112B40",
            border_width=1, border_color="#17425C", text_color="#9DDCFF",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
            command=self._open_api_settings,
        )
        self.api_button.pack(side="right")

        clock_card = ctk.CTkFrame(
            parent, fg_color="#06111C", corner_radius=15,
            border_width=1, border_color="#113147",
        )
        clock_card.pack(fill="x", pady=(0, 9))
        self.clock_label = ctk.CTkLabel(
            clock_card, text="--:--", text_color="#B7D9F1",
            font=ctk.CTkFont(family="Consolas", size=27, weight="bold"),
        )
        self.clock_label.pack(pady=(10, 0))
        self._cinematic_date_label = ctk.CTkLabel(
            clock_card, text="--", text_color="#7191A8",
            font=ctk.CTkFont(family="Segoe UI", size=9),
        )
        self._cinematic_date_label.pack(pady=(0, 10))

        pulse = ctk.CTkFrame(
            parent, fg_color="#06111C", corner_radius=15,
            border_width=1, border_color="#113147",
        )
        pulse.pack(fill="x", pady=(0, 9))
        ctk.CTkLabel(
            pulse, text="SYSTEM PULSE", anchor="w", text_color="#7FB9D9",
            font=ctk.CTkFont(family="Consolas", size=8, weight="bold"),
        ).pack(fill="x", padx=13, pady=(10, 5))

        self._metric_cpu = self._metric_row(pulse, "CPU", "--")
        self._metric_ram = self._metric_row(pulse, "RAM", "--")
        self._metric_disk = self._metric_row(pulse, "DISCO", "--")
        self._metric_network = self._metric_row(pulse, "REDE", "Online", last=True)

        tip = ctk.CTkFrame(
            parent, fg_color="#071522", corner_radius=14,
            border_width=1, border_color="#12364C",
        )
        tip.pack(fill="x", pady=(0, 9))
        ctk.CTkLabel(
            tip, text="✦", width=28, text_color=self.CIN_YELLOW,
            font=ctk.CTkFont(size=17),
        ).pack(side="left", padx=(10, 3), pady=11)
        ctk.CTkLabel(
            tip, text="Estou aqui para\nsimplificar o seu dia.", justify="left", anchor="w",
            text_color="#94B3C8", font=ctk.CTkFont(family="Segoe UI", size=9),
        ).pack(side="left", fill="x", expand=True, padx=(2, 8), pady=9)

        controls = ctk.CTkFrame(
            parent, fg_color="#06111C", corner_radius=15,
            border_width=1, border_color="#113147",
        )
        controls.pack(side="bottom", fill="x", pady=(9, 0))
        ctk.CTkLabel(
            controls, text="CONVERSAÇÃO", anchor="w", text_color="#729DB7",
            font=ctk.CTkFont(family="Consolas", size=7, weight="bold"),
        ).pack(fill="x", padx=12, pady=(10, 4))

        self._continuous_var = ctk.BooleanVar(value=str(self.interaction_mode or "").lower() == "conversa")
        self._continuous_switch = ctk.CTkSwitch(
            controls, text="Modo contínuo", variable=self._continuous_var,
            progress_color="#28B9FF", button_color="#BEEBFF", button_hover_color="#FFFFFF",
            text_color="#A5C4D8", font=ctk.CTkFont(family="Segoe UI", size=9),
            command=self._toggle_continuous_from_right_rail,
        )
        self._continuous_switch.pack(fill="x", padx=12, pady=5)

        self._captions_var = ctk.BooleanVar(value=self._cinematic_captions_enabled)
        self._captions_switch = ctk.CTkSwitch(
            controls, text="Legendas", variable=self._captions_var,
            progress_color="#28B9FF", button_color="#BEEBFF", button_hover_color="#FFFFFF",
            text_color="#A5C4D8", font=ctk.CTkFont(family="Segoe UI", size=9),
            command=self._toggle_captions_from_right_rail,
        )
        self._captions_switch.pack(fill="x", padx=12, pady=5)

        self._chat_tts_var = ctk.BooleanVar(value=self._chat_tts_enabled)
        self._chat_tts_switch = ctk.CTkSwitch(
            controls, text="JARVIS fala", variable=self._chat_tts_var,
            progress_color="#28B9FF", button_color="#BEEBFF", button_hover_color="#FFFFFF",
            text_color="#A5C4D8", font=ctk.CTkFont(family="Segoe UI", size=9),
            command=self._toggle_chat_tts,
        )
        self._chat_tts_switch.pack(fill="x", padx=12, pady=(5, 12))

    def _metric_row(self, parent, name: str, value: str, last: bool = False):
        row = ctk.CTkFrame(parent, fg_color="transparent", height=28)
        row.pack(fill="x", padx=12, pady=(1, 7 if last else 2))
        ctk.CTkLabel(
            row, text=name, width=74, anchor="w", text_color="#76A9C5",
            font=ctk.CTkFont(family="Segoe UI", size=9),
        ).pack(side="left")
        label = ctk.CTkLabel(
            row, text=value, anchor="e", text_color="#A9C8DC",
            font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
        )
        label.pack(side="right", fill="x", expand=True)
        return label

    # ------------------------------------------------------------------
    # Smooth central orb. Frames are supersampled once per state and cached.
    # ------------------------------------------------------------------
    def _orb_palette(self, state: str):
        state = str(state or "REPOUSO").upper()
        if state in {"OUVINDO", "ESCUTANDO", "ESPERANDO_RESPOSTA"}:
            return "#18D7A9", "#A8FFE9", "#045B55"
        if state in {"PENSANDO", "PROCESSANDO", "ENTENDENDO"}:
            return "#8B63FF", "#E1D4FF", "#2C176B"
        if state == "EXECUTANDO":
            return "#FF9D42", "#FFE0B5", "#6D3009"
        if state == "FALANDO":
            return "#2DA8FF", "#BCEBFF", "#063C84"
        if state in {"RECONECTANDO", "SEM_MICROFONE"}:
            return "#E5AA42", "#FFE4A9", "#644008"
        return "#2689FF", "#B8E8FF", "#052B70"

    def _orb_frames(self, state: str):
        key = str(state or "REPOUSO").upper()
        cached = self._cinematic_orb_frame_cache.get(key)
        if cached:
            return cached

        main_hex, bright_hex, dark_hex = self._orb_palette(key)
        main = ImageColor.getrgb(main_hex)
        bright = ImageColor.getrgb(bright_hex)
        dark = ImageColor.getrgb(dark_hex)
        size = 148
        scale = 3
        S = size * scale
        c = S // 2
        r = int(S * 0.285)
        frames = []

        for frame_index in range(12):
            phase = frame_index / 12.0 * math.tau
            canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))

            glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            for mul, alpha in ((1.65, 24), (1.40, 38), (1.18, 58)):
                rr = int(r * mul)
                gd.ellipse((c-rr, c-rr, c+rr, c+rr), fill=main + (alpha,))
            glow = glow.filter(ImageFilter.GaussianBlur(int(S * 0.026)))
            canvas = Image.alpha_composite(canvas, glow)

            sphere = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            sd = ImageDraw.Draw(sphere)
            # Radial body, darker at the edge and bright in the center.
            for rr in range(r, 0, -3):
                t = 1.0 - rr / max(1, r)
                eased = min(1.0, max(0.0, t ** 0.72))
                rgb = tuple(int(dark[i] + (main[i] - dark[i]) * eased) for i in range(3))
                alpha = 255
                sd.ellipse((c-rr, c-rr, c+rr, c+rr), fill=rgb + (alpha,))

            # Internal luminous core.
            core_r = int(r * 0.46)
            core = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            cd = ImageDraw.Draw(core)
            cd.ellipse((c-core_r, c-core_r, c+core_r, c+core_r), fill=bright + (128,))
            core = core.filter(ImageFilter.GaussianBlur(int(S * 0.018)))
            sphere = Image.alpha_composite(sphere, core)

            # Soft glass highlight.
            highlight = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            hd = ImageDraw.Draw(highlight)
            hx = c - int(r * 0.34)
            hy = c - int(r * 0.38)
            hr = int(r * 0.34)
            hd.ellipse((hx-hr, hy-hr, hx+hr, hy+hr), fill=(255, 255, 255, 150))
            highlight = highlight.filter(ImageFilter.GaussianBlur(int(S * 0.022)))
            sphere = Image.alpha_composite(sphere, highlight)
            canvas = Image.alpha_composite(canvas, sphere)

            rings = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            rd = ImageDraw.Draw(rings)
            ring_r = int(r * 1.26)
            ring_r2 = int(r * 1.48)
            width = max(3, int(S * 0.005))
            a = math.degrees(phase)
            rd.arc((c-ring_r, c-ring_r, c+ring_r, c+ring_r), a+16, a+158, fill=bright + (205,), width=width)
            rd.arc((c-ring_r, c-ring_r, c+ring_r, c+ring_r), a+202, a+300, fill=main + (125,), width=width)
            rd.arc((c-ring_r2, c-ring_r2, c+ring_r2, c+ring_r2), -a*0.58+44, -a*0.58+120, fill=main + (92,), width=max(2, width-2))
            rd.arc((c-ring_r2, c-ring_r2, c+ring_r2, c+ring_r2), -a*0.58+202, -a*0.58+252, fill=bright + (75,), width=max(2, width-2))
            canvas = Image.alpha_composite(canvas, rings)

            # Tiny orbit point, same signature as the approved concept.
            pd = ImageDraw.Draw(canvas)
            orbit = r * 1.40
            px = c + math.cos(phase * 1.25) * orbit
            py = c + math.sin(phase * 1.25) * orbit * 0.52
            pr = max(4, int(S * 0.007))
            pd.ellipse((px-pr, py-pr, px+pr, py+pr), fill=bright + (235,))

            reduced = canvas.resize((size*2, size*2), Image.Resampling.LANCZOS)
            frames.append(ctk.CTkImage(light_image=reduced, dark_image=reduced, size=(size, size)))

        self._cinematic_orb_frame_cache[key] = frames
        return frames

    def _animate_cinematic_orb(self):
        self._cinematic_orb_job = None
        try:
            label = getattr(self, "_cinematic_orb_label", None)
            if not label or not label.winfo_exists():
                return
            frames = self._orb_frames(getattr(self, "_cinematic_orb_state", "REPOUSO"))
            index = int(getattr(self, "_cinematic_orb_frame_index", 0)) % len(frames)
            label.configure(image=frames[index])
            self._cinematic_orb_frame_index = (index + 1) % len(frames)
            self._cinematic_orb_job = self.root.after(95, self._animate_cinematic_orb)
        except Exception:
            try:
                self._cinematic_orb_job = self.root.after(220, self._animate_cinematic_orb)
            except Exception:
                self._cinematic_orb_job = None

    def _set_cinematic_orb_state(self, state: str, detail: str = ""):
        state = str(state or "REPOUSO").upper()
        if state in {"AGUARDANDO", "PREPARANDO", "ACORDADO"}:
            state = "REPOUSO"
        elif state in {"ENTENDENDO", "PROCESSANDO"}:
            state = "PENSANDO"
        elif state in {"ESCUTANDO", "ESPERANDO_RESPOSTA"}:
            state = "OUVINDO"
        elif state == "SEM_MICROFONE":
            state = "RECONECTANDO"
        self._cinematic_orb_state = state

        palette = {
            "OUVINDO": self.CIN_GREEN,
            "PENSANDO": self.CIN_PURPLE,
            "EXECUTANDO": self.CIN_ORANGE,
            "FALANDO": self.CIN_BLUE,
        }
        for key, widget in getattr(self, "_conversation_voice_labels", {}).items():
            try:
                widget.configure(text_color=palette[key] if key == state else "#516B7E")
            except Exception:
                pass

        try:
            wave = getattr(self, "_cinematic_wave_label", None)
            if wave:
                wave.configure(
                    text_color=palette.get(state, "#238BC0"),
                    text=(
                        "▁  ▃  ▆  █  ▅  ▂  ▄  ▇  ▄  ▂  ▁" if state == "FALANDO" else
                        "·  ▁  ▃  ▆  ▃  ▁  ·  ▁  ▄  ▂  ·" if state == "OUVINDO" else
                        "·  ·  ▁  ▂  ▄  ▆  █  ▆  ▄  ▂  ▁  ·  ·"
                    ),
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Right rail runtime values.
    # ------------------------------------------------------------------
    def _start_clock_updater(self):
        def tick():
            try:
                now = datetime.now()
                if self.clock_label:
                    self.clock_label.configure(text=now.strftime("%H:%M"))
                if getattr(self, "_cinematic_date_label", None):
                    days = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
                    months = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
                    self._cinematic_date_label.configure(
                        text=f"{days[now.weekday()]}, {now.day:02d} de {months[now.month-1]} de {now.year}"
                    )
                self.root.after(1000, tick)
            except Exception:
                pass
        self.root.after(120, tick)

    def _start_cinematic_metrics_loop(self):
        if getattr(self, "_cinematic_metrics_job", None):
            return

        def tick():
            self._cinematic_metrics_job = None
            try:
                if psutil:
                    cpu = int(round(psutil.cpu_percent(interval=None)))
                    ram = int(round(psutil.virtual_memory().percent))
                    try:
                        disk = int(round(psutil.disk_usage(self.project_dir).percent))
                    except Exception:
                        usage = shutil.disk_usage(self.project_dir)
                        disk = int(round((usage.used / max(1, usage.total)) * 100))
                    online = False
                    try:
                        for name, info in psutil.net_if_stats().items():
                            if info.isup and not str(name).lower().startswith(("loopback", "lo")):
                                online = True
                                break
                    except Exception:
                        online = True
                    self._metric_cpu.configure(text=f"{cpu}%")
                    self._metric_ram.configure(text=f"{ram}%")
                    self._metric_disk.configure(text=f"{disk}%")
                    self._metric_network.configure(
                        text="Online" if online else "Offline",
                        text_color=self.CIN_GREEN if online else "#E5AA42",
                    )
                self._cinematic_metrics_job = self.root.after(1700, tick)
            except Exception:
                try:
                    self._cinematic_metrics_job = self.root.after(3000, tick)
                except Exception:
                    self._cinematic_metrics_job = None

        tick()

    # ------------------------------------------------------------------
    # Switches / visual state / subtitles.
    # ------------------------------------------------------------------
    def _toggle_continuous_from_right_rail(self):
        enabled = bool(self._continuous_var.get())
        self.interaction_mode = "conversa" if enabled else "auto"
        try:
            if self.voice_engine:
                self.voice_engine.set_conversation_mode(enabled)
        except Exception:
            pass
        try:
            if self.operational_context:
                self.operational_context.set_mode(self.interaction_mode)
        except Exception:
            pass
        try:
            self._sync_conversation_overlay_lock(enabled)
        except Exception:
            pass
        try:
            self._save_quick_preferences()
        except Exception:
            pass

    def _toggle_captions_from_right_rail(self):
        self._cinematic_captions_enabled = bool(self._captions_var.get())
        self._save_cinematic_preferences()
        if not self._cinematic_captions_enabled:
            try:
                self._cinematic_subtitle_label.configure(text="")
                if self.qt_voice_overlay:
                    self.qt_voice_overlay.set_caption("")
            except Exception:
                pass
        else:
            try:
                self._cinematic_subtitle_label.configure(text=f"{PUBLIC_NAME}: Pronto quando você estiver.")
            except Exception:
                pass

    def _toggle_chat_tts(self):
        self._chat_tts_enabled = bool(self._chat_tts_var.get())
        self._save_cinematic_preferences()
        if not self._chat_tts_enabled:
            try:
                if self.voice_engine:
                    self.voice_engine.stop_speaking(clear_queue=True)
            except Exception:
                pass

    def _set_input_focus(self, focused: bool):
        try:
            if self.input_shell:
                self.input_shell.configure(
                    border_color="#34C6FF" if focused else "#1C6288",
                    fg_color="#0A1B2A" if focused else "#071521",
                )
        except Exception:
            pass

    def _set_voice_overlay_text(self, text):
        result = super()._set_voice_overlay_text(text)
        if not bool(getattr(self, "_cinematic_captions_enabled", True)):
            return result
        clean = " ".join(str(text or "").split()).strip()
        if clean:
            try:
                prefix = "" if clean.lower().startswith(("jarvis:", "você:", "voce:")) else f"{PUBLIC_NAME}: "
                self._cinematic_subtitle_label.configure(text=(prefix + clean)[:360])
            except Exception:
                pass
        return result

    def _apply_voice_engine_state(self, state, detail):
        result = super()._apply_voice_engine_state(state, detail)
        self._set_cinematic_orb_state(state, detail)
        return result

    def _update_status(self, text, color=None):
        result = super()._update_status(text, color)
        key = str(text or "").upper()
        if any(token in key for token in ("PROCESS", "PENS", "GERANDO", "PESQUIS")):
            self._set_cinematic_orb_state("PENSANDO")
        elif "EXEC" in key:
            self._set_cinematic_orb_state("EXECUTANDO")
        elif "OUV" in key:
            self._set_cinematic_orb_state("OUVINDO")
        elif "FAL" in key:
            self._set_cinematic_orb_state("FALANDO")
        elif any(token in key for token in ("ONLINE", "PRONTO", "CONVERSA COPIADA")):
            self._set_cinematic_orb_state("REPOUSO")
        return result

    def _on_voice_caption(self, text):
        if bool(getattr(self, "_cinematic_captions_enabled", True)):
            return super()._on_voice_caption(text)
        return None

    def _on_voice_live_transcript(self, text):
        if bool(getattr(self, "_cinematic_captions_enabled", True)):
            return super()._on_voice_live_transcript(text)
        return None

    # ------------------------------------------------------------------
    # Typed-chat speech. One text turn -> at most one spoken assistant turn.
    # ------------------------------------------------------------------
    def send_message(self, event=None):
        try:
            has_text = bool(self._composer_text().replace("\x00", "").strip())
        except Exception:
            has_text = False
        if has_text:
            self._chat_text_turn_should_speak = bool(getattr(self, "_chat_tts_enabled", True))
            self._set_cinematic_orb_state("PENSANDO")
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
        if is_jarvis and not is_system:
            if bool(getattr(self, "_cinematic_captions_enabled", True)):
                try:
                    preview = " ".join(str(message or "").split()).strip()
                    if preview:
                        self._cinematic_subtitle_label.configure(text=f"{PUBLIC_NAME}: {preview[:300]}")
                except Exception:
                    pass
            if not speak:
                self._speak_chat_response(message)
        return result

    def _finish_streaming_response(self, full_response: str, token: int = 0):
        pending_before = bool(getattr(self, "_chat_text_turn_should_speak", False))
        result = super()._finish_streaming_response(full_response, token=token)
        if pending_before and bool(getattr(self, "_chat_text_turn_should_speak", False)):
            self._speak_chat_response(full_response)
        return result

    # ------------------------------------------------------------------
    # Conversation utilities.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Diagnostics keep the real audio/orb state visible for support.
    # ------------------------------------------------------------------
    def _collect_diagnostic_text(self):
        report = super()._collect_diagnostic_text()
        controller = getattr(self, "qt_voice_overlay", None)
        qt_alive = False
        try:
            qt_alive = bool(controller and controller.is_alive())
        except Exception:
            qt_alive = False
        visual = str(getattr(self, "_voice_visual_state", "REPOUSO") or "REPOUSO")
        compact = getattr(controller, "_last_compact", None) if controller else None
        state = str(getattr(controller, "_last_state", visual) or visual) if controller else visual
        lines = [
            "",
            "=== INTERFACE CINEMATOGRÁFICA ===",
            "Layout: JARVIS 1.3 conversation-first",
            f"TTS no chat: {'ATIVO' if bool(getattr(self, '_chat_tts_enabled', True)) else 'DESATIVADO'}",
            f"Legendas: {'ATIVAS' if bool(getattr(self, '_cinematic_captions_enabled', True)) else 'DESATIVADAS'}",
            f"Esfera central: {getattr(self, '_cinematic_orb_state', 'REPOUSO')}",
            "",
            "=== ESFERA / OVERLAY DETALHADO ===",
            f"Backend efetivo: {'Qt/PySide6' if qt_alive else 'Tk fallback/nenhum'}",
            f"Processo Qt vivo: {'SIM' if qt_alive else 'NÃO'}",
            f"Estado enviado: {state}",
            f"Estado visual GUI: {'OCIOSO' if visual == 'REPOUSO' else visual}",
            f"Compacta: {'SIM' if compact is True else ('NÃO' if compact is False else '?')}",
        ]
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
