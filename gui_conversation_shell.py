"""Cinematic conversation-first shell for JARVIS Desktop.

The shell replaces the legacy dashboard with the approved three-column visual:
conversation history on the left, a realistic animated JARVIS core + chat in the
center, and update/system controls on the right. The real voice engine remains
separate from the visual renderer so animation cannot stall wake/STT/TTS.
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
    import numpy as np
except Exception:
    np = None

try:
    import psutil
except Exception:
    psutil = None

from gui import JarvisGUI as BaseJarvisGUI
from jarvis_version import VERSION as JARVIS_VERSION, BUILD as JARVIS_BUILD, PUBLIC_NAME


class JarvisGUI(BaseJarvisGUI):
    """High-legibility, cinematic JARVIS desktop shell."""

    BG = "#020812"
    PANEL = "#06111D"
    PANEL_2 = "#091826"
    PANEL_3 = "#0D2030"
    BORDER = "#12354D"
    BORDER_STRONG = "#216F98"
    BLUE = "#33C7FF"
    BLUE_SOFT = "#A2E5FF"
    TEXT = "#F2F8FC"
    MUTED = "#89A5B8"
    MUTED_2 = "#5F7B8E"
    YELLOW = "#FFD84A"
    GREEN = "#45E6B0"
    PURPLE = "#AB8BFF"
    ORANGE = "#FFB45F"

    def _cinematic_pref_path(self) -> Path:
        return Path(self.project_dir) / "data" / "ui_layout.json"

    def _load_cinematic_prefs(self):
        data = {}
        try:
            path = self._cinematic_pref_path()
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        self._chat_tts_enabled = bool(data.get("chat_tts_enabled", True))
        self._cinematic_captions_enabled = bool(data.get("cinematic_captions", True))

    def _save_cinematic_prefs(self):
        try:
            path = self._cinematic_pref_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    data = {}
            data["chat_tts_enabled"] = bool(getattr(self, "_chat_tts_enabled", True))
            data["cinematic_captions"] = bool(getattr(self, "_cinematic_captions_enabled", True))
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _create_main_layout(self):
        self._load_cinematic_prefs()
        self._chat_text_turn_should_speak = False
        self._pending_chat_speech = ""
        self._pending_chat_speech_attempt = 0
        self._conversation_voice_labels = {}
        self._cinematic_orb_state = "REPOUSO"
        self._cinematic_orb_frame = 0
        self._cinematic_orb_cache = {}
        self._cinematic_orb_job = None
        self._cinematic_metrics_job = None

        root_shell = ctk.CTkFrame(self.root, fg_color=self.BG, corner_radius=0)
        root_shell.pack(fill="both", expand=True)
        root_shell.grid_rowconfigure(0, weight=1)
        root_shell.grid_columnconfigure(0, weight=0, minsize=244)
        root_shell.grid_columnconfigure(1, weight=1, minsize=650)
        root_shell.grid_columnconfigure(2, weight=0, minsize=252)
        self.content_frame = root_shell

        left = ctk.CTkFrame(
            root_shell, width=232, fg_color="#040D17", corner_radius=20,
            border_width=1, border_color="#102E43",
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
        left.grid_propagate(False)
        self.side_panel = left
        self.sidebar_splitter = None
        self._create_system_monitor(left)

        center = ctk.CTkFrame(root_shell, fg_color=self.BG, corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew", padx=5, pady=10)
        self._create_chat_area(center)

        right = ctk.CTkFrame(root_shell, width=240, fg_color="transparent", corner_radius=0)
        right.grid(row=0, column=2, sticky="nsew", padx=(7, 14), pady=14)
        right.grid_propagate(False)
        self._create_right_rail(right)

        self.root.after(90, self._animate_cinematic_orb)
        self.root.after(250, self._start_cinematic_metrics_loop)

    def _create_system_monitor(self, parent):
        side = ctk.CTkFrame(parent, fg_color="transparent")
        side.pack(fill="both", expand=True, padx=13, pady=15)

        ctk.CTkLabel(
            side, text="J A R V I S", anchor="w", text_color="#EEF8FF",
            font=ctk.CTkFont(family="Bahnschrift", size=24, weight="bold"),
        ).pack(fill="x")
        ctk.CTkLabel(
            side, text="ASSISTENTE PESSOAL", anchor="w", text_color="#6294B1",
            font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
        ).pack(fill="x", pady=(1, 11))

        status = ctk.CTkFrame(side, fg_color="transparent")
        status.pack(fill="x", pady=(0, 13))
        self.status_dot = ctk.CTkLabel(status, text="●", width=14, text_color=self.GREEN, font=ctk.CTkFont(size=10))
        self.status_dot.pack(side="left")
        self.status_label = ctk.CTkLabel(
            status, text="ONLINE", text_color="#A7C0D0",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
        )
        self.status_label.pack(side="left", padx=(2, 0))
        self.activity_label = ctk.CTkLabel(
            status, text="Pronto", anchor="e", text_color="#658295",
            font=ctk.CTkFont(family="Segoe UI", size=10),
        )
        self.activity_label.pack(side="right", fill="x", expand=True)

        heading = ctk.CTkFrame(side, fg_color="transparent")
        heading.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            heading, text="CONVERSAS", text_color="#C2D7E5",
            font=ctk.CTkFont(family="Bahnschrift", size=12, weight="bold"),
        ).pack(side="left")
        self._conversation_search_button = ctk.CTkButton(
            heading, text="", image=self._get_ui_icon("search", 17, "#B1D0E2"),
            width=34, height=32, corner_radius=10, fg_color="transparent", hover_color="#102B40",
            command=lambda: self._open_conversation_search_popover(self._conversation_search_button),
        )
        self._conversation_search_button.pack(side="right")

        self._new_chat_button = ctk.CTkButton(
            side, text="NOVA CONVERSA", image=self._get_ui_icon("new_chat", 17, "#E8F7FF"),
            height=43, corner_radius=13, fg_color="#0A2234", border_width=1,
            border_color="#1B5879", hover_color="#123A55", text_color="#EAF8FF",
            font=ctk.CTkFont(family="Bahnschrift", size=11, weight="bold"),
            command=self._new_conversation,
        )
        self._new_chat_button.pack(fill="x", pady=(0, 10))

        ctk.CTkFrame(side, height=1, fg_color="#123148").pack(fill="x", pady=(0, 8))
        self.conversation_list_frame = ctk.CTkScrollableFrame(
            side, fg_color="transparent", corner_radius=0, border_width=0,
            scrollbar_button_color="#153248", scrollbar_button_hover_color="#285875",
        )
        self.conversation_list_frame.pack(fill="both", expand=True)

        footer = ctk.CTkFrame(side, fg_color="transparent")
        footer.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(
            footer, text=f"v{JARVIS_VERSION}", text_color="#4A6A7F",
            font=ctk.CTkFont(family="Consolas", size=9),
        ).pack(side="left")
        ctk.CTkLabel(
            footer, text="CONVERSATION CORE", text_color="#3D6076",
            font=ctk.CTkFont(family="Consolas", size=8, weight="bold"),
        ).pack(side="right")

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
        wrapper = ctk.CTkFrame(parent, fg_color=self.BG)
        wrapper.pack(fill="both", expand=True, padx=5, pady=(2, 7))

        top = ctk.CTkFrame(wrapper, fg_color="transparent", height=38)
        top.pack(fill="x", padx=10, pady=(0, 3))
        top.pack_propagate(False)
        self.current_conversation_label = ctk.CTkLabel(
            top, text="Nova conversa", anchor="w", text_color="#B6CCDA",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        )
        self.current_conversation_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            top, text="", image=self._get_ui_icon("copy", 16, "#C4DCEB"),
            width=36, height=32, corner_radius=10, fg_color="#091A28", border_width=1,
            border_color="#17425C", hover_color="#102C40", command=self._copy_everything,
        ).pack(side="right")

        hero = ctk.CTkFrame(wrapper, fg_color="transparent", height=250)
        hero.pack(fill="x", padx=4, pady=(0, 5))
        hero.pack_propagate(False)
        self._cinematic_orb_label = ctk.CTkLabel(hero, text="", width=192, height=192, fg_color="transparent")
        self._cinematic_orb_label.pack(pady=(0, 0))

        subtitle_shell = ctk.CTkFrame(
            hero, fg_color="#03080D", corner_radius=10, border_width=1, border_color="#182F3E",
        )
        subtitle_shell.pack(padx=44, pady=(0, 0))
        self._cinematic_subtitle_label = ctk.CTkLabel(
            subtitle_shell, text=f"{PUBLIC_NAME}: Pronto quando você estiver.",
            text_color=self.YELLOW, font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            wraplength=670, justify="center",
        )
        self._cinematic_subtitle_label.pack(padx=18, pady=8)

        self._cinematic_wave_label = ctk.CTkLabel(
            hero, text="·  ·  ▁  ▂  ▄  ▆  █  ▆  ▄  ▂  ▁  ·  ·",
            text_color="#2B93C3", font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
        )
        self._cinematic_wave_label.pack(pady=(2, 0))

        self.agent_hud = ctk.CTkFrame(
            wrapper, fg_color="#091A28", corner_radius=13, border_width=1, border_color="#1C5B7C",
        )
        hud_top = ctk.CTkFrame(self.agent_hud, fg_color="transparent")
        hud_top.pack(fill="x", padx=12, pady=(8, 2))
        self.agent_hud_title = ctk.CTkLabel(
            hud_top, text=f"{PUBLIC_NAME} // AGENT", text_color="#78D8FF",
            font=ctk.CTkFont(family="Bahnschrift", size=11, weight="bold"),
        )
        self.agent_hud_title.pack(side="left")
        self.agent_stop_button = ctk.CTkButton(
            hud_top, text="■ PARAR", width=74, height=25, corner_radius=8,
            fg_color="#351B24", hover_color="#512633", text_color="#FF9DAC",
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold"), command=self._stop_agent_goal,
        )
        self.agent_stop_button.pack(side="right")
        self.agent_hud_step = ctk.CTkLabel(
            self.agent_hud, text="", anchor="w", justify="left", wraplength=760,
            text_color="#D7E8F2", font=ctk.CTkFont(family="Segoe UI", size=11),
        )
        self.agent_hud_step.pack(fill="x", padx=12, pady=(0, 6))
        self.agent_hud_progress = ctk.CTkProgressBar(
            self.agent_hud, height=4, corner_radius=2, fg_color="#162638", progress_color=self.BLUE,
        )
        self.agent_hud_progress.pack(fill="x", padx=12, pady=(0, 9))
        self.agent_hud_progress.set(0.0)
        self.agent_hud.pack_forget()

        chat_shell = ctk.CTkFrame(
            wrapper, fg_color="#050F18", corner_radius=20, border_width=1, border_color="#185574",
        )
        chat_shell.pack(fill="both", expand=True, padx=12, pady=(1, 7))
        self.chat_scroll = ctk.CTkScrollableFrame(
            chat_shell, fg_color="#050F18", corner_radius=17, border_width=0,
            scrollbar_button_color="#18384F", scrollbar_button_hover_color="#2D627E",
        )
        self.chat_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        self.chat_display = None
        self._install_chat_mousewheel()

        state_row = ctk.CTkFrame(wrapper, fg_color="transparent", height=30)
        state_row.pack(fill="x", padx=30, pady=(0, 4))
        state_row.pack_propagate(False)
        state_box = ctk.CTkFrame(state_row, fg_color="transparent")
        state_box.pack(anchor="center")
        for key, label in (("OUVINDO", "OUVINDO"), ("PENSANDO", "PENSANDO"), ("EXECUTANDO", "EXECUTANDO"), ("FALANDO", "FALANDO")):
            widget = ctk.CTkLabel(
                state_box, text=label, text_color="#5C7688",
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            )
            widget.pack(side="left", padx=8)
            self._conversation_voice_labels[key] = widget
            if key != "FALANDO":
                ctk.CTkLabel(state_box, text="•", text_color="#318FBC", font=ctk.CTkFont(size=9)).pack(side="left")

        self.input_shell = ctk.CTkFrame(
            wrapper, fg_color="#071725", corner_radius=26, border_width=1, border_color="#22729A",
        )
        self.input_shell.pack(fill="x", padx=17, pady=(0, 7))
        self.quick_menu_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("dots", 19, "#B6D1E1"),
            width=42, height=42, corner_radius=14, fg_color="#0E293C", border_width=1,
            border_color="#1D506D", hover_color="#173B55",
            command=lambda: self._show_quick_actions_menu(self.quick_menu_button),
        )
        self.quick_menu_button.pack(side="left", padx=(8, 3), pady=7)
        self.text_input = ctk.CTkTextbox(
            self.input_shell, height=self.COMPOSER_MIN_HEIGHT, wrap="word", activate_scrollbars=False,
            font=ctk.CTkFont(family="Segoe UI", size=15), text_color=self.TEXT,
            fg_color="transparent", border_width=0, corner_radius=0,
        )
        self.text_input.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=7)
        self.text_input.bind("<FocusIn>", self._composer_focus_in, add="+")
        self.text_input.bind("<FocusOut>", self._composer_focus_out, add="+")
        self.text_input.bind("<Return>", self._on_composer_return, add="+")
        self.text_input.bind("<KeyRelease>", self._resize_composer, add="+")
        self._composer_set_placeholder()
        self.voice_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("voice", 19, "#D5F1FF"),
            width=42, height=42, corner_radius=14, fg_color="#0C344C", border_width=1,
            border_color="#206E96", hover_color="#16506E", command=self._toggle_voice_visual_mode,
        )
        self.voice_button.pack(side="left", padx=4, pady=7)
        self.send_button = ctk.CTkButton(
            self.input_shell, text="", image=self._get_ui_icon("send", 19, "#02131D"),
            width=44, height=44, corner_radius=14, fg_color="#3AC9FF", hover_color="#71DAFF",
            command=self.send_message,
        )
        self.send_button.pack(side="left", padx=(4, 8), pady=6)

        ctk.CTkLabel(
            wrapper, text="JARVIS  |  INTELIGÊNCIA QUE TRABALHA POR VOCÊ", text_color="#32647E",
            font=ctk.CTkFont(family="Consolas", size=9),
        ).pack(pady=(0, 1))

    def _create_right_rail(self, parent):
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 9))
        self.update_button = ctk.CTkButton(
            actions, text="ATUALIZAR", height=39, corner_radius=13, fg_color=self.BLUE,
            hover_color="#73DBFF", text_color="#02131D",
            font=ctk.CTkFont(family="Bahnschrift", size=11, weight="bold"), command=self._update_now,
        )
        self.update_button.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.api_button = ctk.CTkButton(
            actions, text="API", width=48, height=39, corner_radius=13, fg_color="#081A29",
            hover_color="#123048", border_width=1, border_color="#19516F", text_color="#A9E4FF",
            font=ctk.CTkFont(family="Bahnschrift", size=10, weight="bold"), command=self._open_api_settings,
        )
        self.api_button.pack(side="right")

        clock = ctk.CTkFrame(parent, fg_color="#05111C", corner_radius=16, border_width=1, border_color="#12374E")
        clock.pack(fill="x", pady=(0, 9))
        self.clock_label = ctk.CTkLabel(
            clock, text="--:--", text_color="#C6E6F8",
            font=ctk.CTkFont(family="Consolas", size=30, weight="bold"),
        )
        self.clock_label.pack(pady=(11, 0))
        self._cinematic_date_label = ctk.CTkLabel(
            clock, text="--", text_color="#7E9DB0", font=ctk.CTkFont(family="Segoe UI", size=10),
        )
        self._cinematic_date_label.pack(pady=(0, 11))

        pulse = ctk.CTkFrame(parent, fg_color="#05111C", corner_radius=16, border_width=1, border_color="#12374E")
        pulse.pack(fill="x", pady=(0, 9))
        ctk.CTkLabel(
            pulse, text="SYSTEM PULSE", anchor="w", text_color="#83BDD9",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
        ).pack(fill="x", padx=14, pady=(11, 6))
        self._metric_cpu = self._metric_row(pulse, "CPU", "--")
        self._metric_ram = self._metric_row(pulse, "RAM", "--")
        self._metric_disk = self._metric_row(pulse, "DISCO", "--")
        self._metric_network = self._metric_row(pulse, "REDE", "Online", last=True)

        note = ctk.CTkFrame(parent, fg_color="#071725", corner_radius=15, border_width=1, border_color="#143C54")
        note.pack(fill="x", pady=(0, 9))
        ctk.CTkLabel(note, text="✦", width=30, text_color=self.YELLOW, font=ctk.CTkFont(size=18)).pack(side="left", padx=(11, 4), pady=12)
        ctk.CTkLabel(
            note, text="Estou aqui para\nsimplificar o seu dia.", justify="left", anchor="w",
            text_color="#A4BFCE", font=ctk.CTkFont(family="Segoe UI", size=11),
        ).pack(side="left", fill="x", expand=True, padx=(2, 8), pady=10)

        controls = ctk.CTkFrame(parent, fg_color="#05111C", corner_radius=16, border_width=1, border_color="#12374E")
        controls.pack(side="bottom", fill="x", pady=(9, 0))
        ctk.CTkLabel(
            controls, text="CONVERSAÇÃO", anchor="w", text_color="#82ABC2",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
        ).pack(fill="x", padx=13, pady=(11, 5))
        self._continuous_var = ctk.BooleanVar(value=str(self.interaction_mode or "").lower() == "conversa")
        self._continuous_switch = ctk.CTkSwitch(
            controls, text="Modo contínuo", variable=self._continuous_var, progress_color="#29BFFF",
            button_color="#C5EEFF", button_hover_color="#FFFFFF", text_color="#B3CEDD",
            font=ctk.CTkFont(family="Segoe UI", size=11), command=self._toggle_continuous,
        )
        self._continuous_switch.pack(fill="x", padx=13, pady=6)
        self._captions_var = ctk.BooleanVar(value=self._cinematic_captions_enabled)
        self._captions_switch = ctk.CTkSwitch(
            controls, text="Legendas", variable=self._captions_var, progress_color="#29BFFF",
            button_color="#C5EEFF", button_hover_color="#FFFFFF", text_color="#B3CEDD",
            font=ctk.CTkFont(family="Segoe UI", size=11), command=self._toggle_captions,
        )
        self._captions_switch.pack(fill="x", padx=13, pady=6)
        self._chat_tts_var = ctk.BooleanVar(value=self._chat_tts_enabled)
        self._chat_tts_switch = ctk.CTkSwitch(
            controls, text="JARVIS fala", variable=self._chat_tts_var, progress_color="#29BFFF",
            button_color="#C5EEFF", button_hover_color="#FFFFFF", text_color="#B3CEDD",
            font=ctk.CTkFont(family="Segoe UI", size=11), command=self._toggle_chat_tts,
        )
        self._chat_tts_switch.pack(fill="x", padx=13, pady=(6, 13))

    def _metric_row(self, parent, name, value, last=False):
        row = ctk.CTkFrame(parent, fg_color="transparent", height=30)
        row.pack(fill="x", padx=13, pady=(1, 8 if last else 3))
        ctk.CTkLabel(row, text=name, width=80, anchor="w", text_color="#83ABC1", font=ctk.CTkFont(family="Segoe UI", size=11)).pack(side="left")
        label = ctk.CTkLabel(row, text=value, anchor="e", text_color="#BCD5E4", font=ctk.CTkFont(family="Consolas", size=11, weight="bold"))
        label.pack(side="right", fill="x", expand=True)
        return label

    def _orb_palette(self, state):
        state = str(state or "REPOUSO").upper()
        if state in {"OUVINDO", "ESCUTANDO", "ESPERANDO_RESPOSTA"}:
            return (18, 211, 172), (173, 255, 237), (2, 73, 70)
        if state in {"PENSANDO", "PROCESSANDO", "ENTENDENDO"}:
            return (142, 99, 255), (229, 216, 255), (43, 22, 108)
        if state == "EXECUTANDO":
            return (255, 157, 70), (255, 231, 190), (112, 50, 6)
        if state == "FALANDO":
            return (42, 169, 255), (191, 237, 255), (4, 58, 132)
        if state in {"RECONECTANDO", "SEM_MICROFONE"}:
            return (226, 171, 67), (255, 236, 183), (102, 63, 8)
        return (37, 132, 255), (184, 232, 255), (4, 37, 103)

    def _build_orb_frame(self, state, phase, size=192):
        main, bright, dark = self._orb_palette(state)
        S = size * 3
        c = (S - 1) / 2.0
        radius = S * 0.255

        canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for mul, alpha in ((1.75, 18), (1.48, 30), (1.25, 48)):
            rr = radius * mul
            gd.ellipse((c-rr, c-rr, c+rr, c+rr), fill=main + (alpha,))
        glow = glow.filter(ImageFilter.GaussianBlur(int(S * 0.028)))
        canvas = Image.alpha_composite(canvas, glow)

        if np is not None:
            y, x = np.mgrid[0:S, 0:S].astype(np.float32)
            nx = (x - c) / radius
            ny = (y - c) / radius
            r2 = nx*nx + ny*ny
            mask = r2 <= 1.0
            nz = np.sqrt(np.clip(1.0-r2, 0.0, 1.0))
            p = float(phase)
            lx1, ly1, lz1 = -0.46, -0.58, 0.67
            lx2 = 0.52 * math.cos(p*0.45)
            ly2 = 0.35 * math.sin(p*0.38)
            lz2 = 0.78
            dot1 = np.clip(nx*lx1 + ny*ly1 + nz*lz1, 0.0, 1.0)
            dot2 = np.clip(nx*lx2 + ny*ly2 + nz*lz2, 0.0, 1.0)
            fresnel = np.clip(1.0-nz, 0.0, 1.0) ** 2.5
            spec1 = dot1 ** 28
            spec2 = dot2 ** 18
            angle = np.arctan2(ny, nx)
            swirl = (np.sin(angle*3.0 + p*2.0 + nz*7.0 + np.sqrt(np.clip(r2,0,1))*11.0) + 1.0) * 0.5
            caustic = (np.sin((nx*math.cos(p)+ny*math.sin(p))*15.0 + nz*9.0) + 1.0) * 0.5
            core = np.exp(-r2*3.0)
            light = 0.20 + dot1*0.54 + dot2*0.20 + core*0.28 + swirl*0.07 + caustic*0.05

            arr = np.zeros((S, S, 4), dtype=np.uint8)
            main_a = np.array(main, dtype=np.float32)
            dark_a = np.array(dark, dtype=np.float32)
            bright_a = np.array(bright, dtype=np.float32)
            base_mix = np.clip((light-0.16)/0.98, 0.0, 1.0)[...,None]
            rgb = dark_a + (main_a-dark_a) * base_mix
            rgb += bright_a * (spec1[...,None]*0.70 + spec2[...,None]*0.30)
            rgb += bright_a * fresnel[...,None]*0.16
            absorption = np.clip((nx+ny+0.35)*0.10, -0.08, 0.12)[...,None]
            rgb *= (1.0-absorption)
            rgb = np.clip(rgb, 0, 255)
            arr[...,:3] = rgb.astype(np.uint8)
            edge = np.clip((1.0-r2)*18.0, 0.0, 1.0)
            arr[...,3] = (edge*255).astype(np.uint8)
            arr[~mask,3] = 0
            sphere = Image.fromarray(arr, "RGBA")
        else:
            sphere = Image.new("RGBA", (S, S), (0,0,0,0))
            sd = ImageDraw.Draw(sphere)
            for rr in range(int(radius), 0, -2):
                t = 1.0 - rr/max(radius,1.0)
                rgb = tuple(int(dark[i] + (main[i]-dark[i])*(t**0.65)) for i in range(3))
                sd.ellipse((c-rr,c-rr,c+rr,c+rr), fill=rgb+(255,))

        canvas = Image.alpha_composite(canvas, sphere)
        highlight = Image.new("RGBA", (S,S), (0,0,0,0))
        hd = ImageDraw.Draw(highlight)
        hx, hy = c-radius*0.36, c-radius*0.40
        hr = radius*0.31
        hd.ellipse((hx-hr,hy-hr,hx+hr,hy+hr), fill=(255,255,255,140))
        bx = c + math.cos(phase*0.72)*radius*0.18
        by = c + math.sin(phase*0.58)*radius*0.12
        br = radius*0.22
        hd.ellipse((bx-br,by-br,bx+br,by+br), fill=bright+(64,))
        highlight = highlight.filter(ImageFilter.GaussianBlur(int(S*0.021)))
        canvas = Image.alpha_composite(canvas, highlight)

        ring_layer = Image.new("RGBA", (S,S), (0,0,0,0))
        rd = ImageDraw.Draw(ring_layer)
        a = math.degrees(phase)
        rr1 = radius*1.27
        rr2 = radius*1.50
        width = max(4, int(S*0.0055))
        rd.arc((c-rr1,c-rr1,c+rr1,c+rr1), a+15, a+148, fill=bright+(195,), width=width)
        rd.arc((c-rr1,c-rr1,c+rr1,c+rr1), a+202, a+302, fill=main+(112,), width=max(2,width-1))
        rd.arc((c-rr2,c-rr2,c+rr2,c+rr2), -a*0.58+42, -a*0.58+112, fill=main+(78,), width=max(2,width-2))
        rd.arc((c-rr2,c-rr2,c+rr2,c+rr2), -a*0.58+216, -a*0.58+264, fill=bright+(88,), width=max(2,width-2))
        ring_glow = ring_layer.filter(ImageFilter.GaussianBlur(int(S*0.010)))
        canvas = Image.alpha_composite(canvas, ring_glow)
        canvas = Image.alpha_composite(canvas, ring_layer)

        particle = Image.new("RGBA", (S,S), (0,0,0,0))
        pd = ImageDraw.Draw(particle)
        orbit = radius*1.42
        px = c + math.cos(phase*1.15)*orbit
        py = c + math.sin(phase*1.15)*orbit*0.52
        pr = max(5, int(S*0.009))
        pd.ellipse((px-pr*2,py-pr*2,px+pr*2,py+pr*2), fill=bright+(46,))
        particle = particle.filter(ImageFilter.GaussianBlur(pr))
        canvas = Image.alpha_composite(canvas, particle)
        pd = ImageDraw.Draw(canvas)
        pd.ellipse((px-pr/2,py-pr/2,px+pr/2,py+pr/2), fill=bright+(245,))

        reduced = canvas.resize((size*2,size*2), Image.Resampling.LANCZOS)
        return ctk.CTkImage(light_image=reduced, dark_image=reduced, size=(size,size))

    def _orb_frames(self, state):
        key = str(state or "REPOUSO").upper()
        cached = self._cinematic_orb_cache.get(key)
        if cached:
            return cached
        frames = [self._build_orb_frame(key, i/16.0*math.tau) for i in range(16)]
        self._cinematic_orb_cache[key] = frames
        return frames

    def _animate_cinematic_orb(self):
        self._cinematic_orb_job = None
        try:
            label = getattr(self, "_cinematic_orb_label", None)
            if not label or not label.winfo_exists():
                return
            frames = self._orb_frames(self._cinematic_orb_state)
            index = int(self._cinematic_orb_frame) % len(frames)
            label.configure(image=frames[index])
            self._cinematic_orb_frame = (index+1) % len(frames)
            self._cinematic_orb_job = self.root.after(72, self._animate_cinematic_orb)
        except Exception:
            try:
                self._cinematic_orb_job = self.root.after(180, self._animate_cinematic_orb)
            except Exception:
                pass

    def _set_cinematic_orb_state(self, state, detail=""):
        state = str(state or "REPOUSO").upper()
        aliases = {
            "AGUARDANDO":"REPOUSO", "PREPARANDO":"REPOUSO", "ACORDOU":"OUVINDO",
            "ESCUTANDO":"OUVINDO", "ESPERANDO_RESPOSTA":"OUVINDO",
            "ENTENDENDO":"PENSANDO", "PROCESSANDO":"PENSANDO", "SEM_MICROFONE":"RECONECTANDO",
        }
        state = aliases.get(state, state)
        self._cinematic_orb_state = state
        palette = {"OUVINDO":self.GREEN,"PENSANDO":self.PURPLE,"EXECUTANDO":self.ORANGE,"FALANDO":self.BLUE}
        for key, widget in getattr(self, "_conversation_voice_labels", {}).items():
            try:
                widget.configure(text_color=palette[key] if key == state else "#5C7688")
            except Exception:
                pass
        try:
            if self._cinematic_wave_label:
                pattern = "▁  ▃  ▆  █  ▅  ▂  ▄  ▇  ▄  ▂  ▁" if state == "FALANDO" else ("·  ▁  ▃  ▆  ▃  ▁  ·  ▁  ▄  ▂  ·" if state == "OUVINDO" else "·  ·  ▁  ▂  ▄  ▆  █  ▆  ▄  ▂  ▁  ·  ·")
                self._cinematic_wave_label.configure(text=pattern, text_color=palette.get(state,"#2B93C3"))
        except Exception:
            pass

    def _start_clock_updater(self):
        def tick():
            try:
                now = datetime.now()
                if self.clock_label:
                    self.clock_label.configure(text=now.strftime("%H:%M"))
                if getattr(self,"_cinematic_date_label",None):
                    days=["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"]
                    months=["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
                    self._cinematic_date_label.configure(text=f"{days[now.weekday()]}, {now.day:02d} de {months[now.month-1]} de {now.year}")
                self.root.after(1000,tick)
            except Exception:
                pass
        self.root.after(150,tick)

    def _start_cinematic_metrics_loop(self):
        if self._cinematic_metrics_job:
            return
        def tick():
            self._cinematic_metrics_job=None
            try:
                if psutil:
                    cpu=int(round(psutil.cpu_percent(interval=None)))
                    ram=int(round(psutil.virtual_memory().percent))
                    try: disk=int(round(psutil.disk_usage(self.project_dir).percent))
                    except Exception:
                        usage=shutil.disk_usage(self.project_dir); disk=int(round(usage.used/max(1,usage.total)*100))
                    online=any(info.isup for name,info in psutil.net_if_stats().items() if not str(name).lower().startswith(("loopback","lo")))
                    self._metric_cpu.configure(text=f"{cpu}%")
                    self._metric_ram.configure(text=f"{ram}%")
                    self._metric_disk.configure(text=f"{disk}%")
                    self._metric_network.configure(text="Online" if online else "Offline", text_color=self.GREEN if online else "#E5AA42")
                self._cinematic_metrics_job=self.root.after(1700,tick)
            except Exception:
                try:self._cinematic_metrics_job=self.root.after(3000,tick)
                except Exception:pass
        tick()

    def _toggle_continuous(self):
        enabled=bool(self._continuous_var.get())
        self.interaction_mode="conversa" if enabled else "auto"
        try:
            if self.voice_engine:self.voice_engine.set_conversation_mode(enabled)
        except Exception:pass
        try:self._sync_conversation_overlay_lock(enabled)
        except Exception:pass
        try:self._save_quick_preferences()
        except Exception:pass

    def _toggle_captions(self):
        self._cinematic_captions_enabled=bool(self._captions_var.get())
        self._save_cinematic_prefs()
        if not self._cinematic_captions_enabled:
            try:self._cinematic_subtitle_label.configure(text="")
            except Exception:pass
        else:
            try:self._cinematic_subtitle_label.configure(text=f"{PUBLIC_NAME}: Pronto quando você estiver.")
            except Exception:pass

    def _toggle_chat_tts(self):
        self._chat_tts_enabled=bool(self._chat_tts_var.get())
        self._save_cinematic_prefs()
        if not self._chat_tts_enabled:
            self._pending_chat_speech=""
            self._chat_text_turn_should_speak=False
            try:
                if self.voice_engine:self.voice_engine.stop_speaking(clear_queue=True)
            except Exception:pass

    def _set_voice_overlay_text(self,text):
        result=super()._set_voice_overlay_text(text)
        if not self._cinematic_captions_enabled:return result
        clean=" ".join(str(text or "").split()).strip()
        if clean:
            try:
                prefix="" if clean.lower().startswith(("jarvis:","você:","voce:")) else f"{PUBLIC_NAME}: "
                self._cinematic_subtitle_label.configure(text=(prefix+clean)[:380])
            except Exception:pass
        return result

    def _apply_voice_engine_state(self,state,detail):
        result=super()._apply_voice_engine_state(state,detail)
        self._set_cinematic_orb_state(state,detail)
        return result

    def _update_status(self,text,color=None):
        result=super()._update_status(text,color)
        key=str(text or "").upper()
        if any(t in key for t in ("PROCESS","PENS","GERANDO","PESQUIS")):self._set_cinematic_orb_state("PENSANDO")
        elif "EXEC" in key:self._set_cinematic_orb_state("EXECUTANDO")
        elif "OUV" in key:self._set_cinematic_orb_state("OUVINDO")
        elif "FAL" in key:self._set_cinematic_orb_state("FALANDO")
        elif any(t in key for t in ("ONLINE","PRONTO","CONVERSA COPIADA")):self._set_cinematic_orb_state("REPOUSO")
        return result

    def _create_chat_bubble(self,*args,**kwargs):
        widget=super()._create_chat_bubble(*args,**kwargs)
        try:
            if isinstance(widget,ctk.CTkTextbox):
                widget.configure(font=ctk.CTkFont(family="Segoe UI",size=15))
            elif isinstance(widget,ctk.CTkLabel):
                widget.configure(font=ctk.CTkFont(family="Segoe UI",size=14))
        except Exception:pass
        return widget

    def send_message(self,event=None):
        try:has_text=bool(self._composer_text().replace("\x00","").strip())
        except Exception:has_text=False
        if has_text:
            self._chat_text_turn_should_speak=bool(self._chat_tts_enabled)
            self._set_cinematic_orb_state("PENSANDO")
        return super().send_message(event=event)

    def _queue_chat_speech(self,text,attempt=0):
        clean=" ".join(str(text or "").split()).strip()
        if not clean or not self._chat_tts_enabled:
            self._pending_chat_speech="";self._chat_text_turn_should_speak=False;return
        engine=getattr(self,"voice_engine",None)
        if engine is None:
            if attempt<24 and getattr(self,"root",None):
                self._pending_chat_speech=clean
                self.root.after(250,lambda:self._queue_chat_speech(clean,attempt+1))
            return
        try:
            spoken=self._voice_spoken_summary(clean)
            engine.speak(spoken,wait=False,fast=True)
            self._pending_chat_speech=""
            self._chat_text_turn_should_speak=False
            self._set_cinematic_orb_state("FALANDO")
        except Exception as exc:
            if attempt<4 and getattr(self,"root",None):
                self.root.after(350,lambda:self._queue_chat_speech(clean,attempt+1))
            else:
                self._chat_text_turn_should_speak=False
                try:self.logger.warning(f"TTS da conversa indisponível após retry: {exc}","VOICE")
                except Exception:pass

    def _speak_chat_response(self,text):
        if not self._chat_text_turn_should_speak:return
        if getattr(self,"_voice_command_active",False):return
        self._queue_chat_speech(text,0)

    def add_message(self,sender,message,is_user=False,is_jarvis=False,is_system=False,speak=False):
        result=super().add_message(sender,message,is_user=is_user,is_jarvis=is_jarvis,is_system=is_system,speak=speak)
        if is_jarvis and not is_system:
            if self._cinematic_captions_enabled:
                try:
                    preview=" ".join(str(message or "").split()).strip()
                    if preview:self._cinematic_subtitle_label.configure(text=f"{PUBLIC_NAME}: {preview[:320]}")
                except Exception:pass
            if not speak:self._speak_chat_response(message)
        return result

    def _finish_streaming_response(self,full_response,token=0):
        pending=bool(self._chat_text_turn_should_speak)
        result=super()._finish_streaming_response(full_response,token=token)
        if pending and self._chat_text_turn_should_speak:self._speak_chat_response(full_response)
        return result

    def _scroll_chat_top(self):
        try:
            canvas=getattr(self.chat_scroll,"_parent_canvas",None)
            if canvas is not None:canvas.yview_moveto(0.0)
        except Exception:pass

    def _new_conversation(self):
        super()._new_conversation()
        for delay in (10,60,160):
            try:self.root.after(delay,self._scroll_chat_top)
            except Exception:pass

    def _copy_everything(self):
        cid=int(self.active_conversation_id)
        title=self.memory_store.get_conversation_title(cid)
        messages=self.memory_store.load_messages(cid,limit=5000)
        lines=["=== RELATÓRIO DE CONVERSA - JARVIS ===",f"Versão: {JARVIS_VERSION}",f"Build: {JARVIS_BUILD}",f"Conversa: {title}",f"ID da conversa: {cid}",f"Exportado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",f"Mensagens: {len(messages)}",""]
        for item in messages:
            sender=str(item.get("sender") or ("Você" if item.get("is_user") else PUBLIC_NAME)).strip()
            stamp=str(item.get("timestamp") or "").strip();msg=str(item.get("message") or "").strip()
            if not msg:continue
            lines.extend(((f"[{stamp}] {sender}:" if stamp else f"{sender}:"),msg,""))
        report="\n".join(lines).rstrip()+"\n"
        self.root.clipboard_clear();self.root.clipboard_append(report);self.root.update_idletasks()
        self._update_status("CONVERSA COPIADA",self.UI_SUCCESS)
        self.root.after(1800,lambda:self._update_status("ONLINE",self.UI_SUCCESS))

    def _collect_diagnostic_text(self):
        report=super()._collect_diagnostic_text()
        controller=getattr(self,"qt_voice_overlay",None)
        try:qt_alive=bool(controller and controller.is_alive())
        except Exception:qt_alive=False
        lines=["","=== INTERFACE CINEMATOGRÁFICA ===","Layout: JARVIS cinematic realistic",f"TTS no chat: {'ATIVO' if self._chat_tts_enabled else 'DESATIVADO'}",f"Legendas: {'ATIVAS' if self._cinematic_captions_enabled else 'DESATIVADAS'}",f"Esfera central: {self._cinematic_orb_state}",f"Overlay Qt vivo: {'SIM' if qt_alive else 'NÃO'}"]
        try:
            if self.voice_engine:
                vs=self.voice_engine.status() or {}
                lines.extend(["","=== VOZ / WAKE ===",f"Microfone: {'SIM' if vs.get('microphone_available') else 'NÃO'}",f"Entrada: {vs.get('input_device') or vs.get('input_device_name') or '-'}",f"Host: {vs.get('input_hostapi') or '-'}",f"Captura: {vs.get('capture_mode') or '-'}",f"TTS provider: {vs.get('tts_provider') or '-'}",f"Último erro: {vs.get('last_error') or '-'}"])
        except Exception:pass
        return report+"\n"+"\n".join(lines)
