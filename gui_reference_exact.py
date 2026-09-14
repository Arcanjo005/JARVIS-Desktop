"""Pixel-anchored JARVIS shell based on the exact user-approved reference.

Reference canvas: 1536 x 960 (Windows taskbar excluded).
The layout preserves those proportions and uses the exact approved orb crop.
Functional widgets are placed on top of the same geometry instead of redesigning
or reinterpreting the reference.
"""
from __future__ import annotations

from datetime import datetime
import math
import customtkinter as ctk

from gui_conversation_shell import JarvisGUI as CinematicJarvisGUI
from jarvis_reference_orb import load_orb_image
from jarvis_version import PUBLIC_NAME, VERSION as JARVIS_VERSION


class JarvisGUI(CinematicJarvisGUI):
    REF_W = 1536
    REF_H = 960

    REF_BG = "#010712"
    REF_PANEL = "#020A13"
    REF_PANEL_2 = "#03101C"
    REF_BORDER = "#073455"
    REF_BORDER_BRIGHT = "#0878B9"
    REF_BLUE = "#29B9FF"
    REF_TEXT = "#E5F2FC"
    REF_MUTED = "#8BB4CF"
    REF_YELLOW = "#FFE500"
    REF_GREEN = "#26E7A2"

    def _create_main_layout(self):
        # The reference itself is 1536x960. Keep the same aspect/proportions and
        # let place(rel*) scale cleanly on smaller monitors.
        self._load_cinematic_prefs()
        self._chat_text_turn_should_speak = False
        self._pending_chat_speech = ""
        self._pending_chat_speech_attempt = 0
        self._conversation_voice_labels = {}
        self._cinematic_orb_state = "REPOUSO"
        self._cinematic_metrics_job = None
        self._reference_clock_job = None

        try:
            self.root.minsize(1180, 738)
        except Exception:
            pass

        stage = ctk.CTkFrame(self.root, fg_color=self.REF_BG, corner_radius=0)
        stage.pack(fill="both", expand=True)
        self.content_frame = stage
        self.side_panel = None
        self.sidebar_splitter = None

        self._create_reference_sidebar(stage)
        self._create_reference_center(stage)
        self._create_reference_right(stage)

        self.root.after(120, self._reference_tick)
        self.root.after(300, self._start_cinematic_metrics_loop)
        self.root.after(90, self._refresh_conversation_list)

    # ------------------------------------------------------------------
    # LEFT — exact geometry from reference. Content remains conversation-first.
    # ------------------------------------------------------------------
    def _create_reference_sidebar(self, parent):
        logo = ctk.CTkLabel(
            parent, text="J A R V I S", anchor="w",
            text_color="#B7DAF5",
            font=ctk.CTkFont(family="Bahnschrift", size=27, weight="bold"),
        )
        logo.place(relx=0.024, rely=0.034, relwidth=0.14, relheight=0.04)
        ctk.CTkLabel(
            parent, text="S E M P R E   A O   S E U   L A D O", anchor="w",
            text_color="#76AACA", font=ctk.CTkFont(family="Consolas", size=10),
        ).place(relx=0.024, rely=0.075, relwidth=0.15, relheight=0.025)

        panel = ctk.CTkFrame(
            parent, fg_color="#020B15", corner_radius=18,
            border_width=1, border_color="#07304C",
        )
        panel.place(relx=24/self.REF_W, rely=124/self.REF_H,
                    relwidth=234/self.REF_W, relheight=755/self.REF_H)
        self.side_panel = panel

        selected = ctk.CTkFrame(panel, fg_color="#03182A", corner_radius=10)
        selected.place(relx=0.0, rely=0.018, relwidth=0.93, relheight=0.068)
        ctk.CTkFrame(selected, fg_color="#00AFFF", width=3, corner_radius=2).pack(side="left", fill="y")
        ctk.CTkLabel(
            selected, text="▢   Conversar", anchor="w", text_color="#8BD6FF",
            font=ctk.CTkFont(family="Segoe UI", size=14),
        ).pack(side="left", fill="both", expand=True, padx=(19, 6))

        # Search + new conversation keep the requested conversation-only
        # behavior while occupying the same visual rhythm as the reference menu.
        self._conversation_search_button = ctk.CTkButton(
            panel, text="⌕   Buscar conversas", anchor="w",
            height=40, corner_radius=8, fg_color="transparent", hover_color="#061A2A",
            text_color="#8EC9ED", font=ctk.CTkFont(family="Segoe UI", size=13),
            command=lambda: self._open_conversation_search_popover(self._conversation_search_button),
        )
        self._conversation_search_button.place(relx=0.075, rely=0.105, relwidth=0.83, relheight=0.054)

        self._new_chat_button = ctk.CTkButton(
            panel, text="＋   Nova conversa", anchor="w",
            height=40, corner_radius=8, fg_color="transparent", hover_color="#061A2A",
            text_color="#8EC9ED", font=ctk.CTkFont(family="Segoe UI", size=13),
            command=self._new_conversation,
        )
        self._new_chat_button.place(relx=0.075, rely=0.163, relwidth=0.83, relheight=0.054)

        ctk.CTkLabel(
            panel, text="CONVERSAS", anchor="w", text_color="#527E99",
            font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
        ).place(relx=0.09, rely=0.235, relwidth=0.7, relheight=0.03)

        self.conversation_list_frame = ctk.CTkScrollableFrame(
            panel, fg_color="transparent", corner_radius=0, border_width=0,
            scrollbar_button_color="#0A2940", scrollbar_button_hover_color="#145077",
        )
        self.conversation_list_frame.place(relx=0.055, rely=0.27, relwidth=0.89, relheight=0.48)

        ctk.CTkFrame(panel, fg_color="#0A2B43", height=1).place(
            relx=0.09, rely=0.77, relwidth=0.82, relheight=0.0015
        )
        ctk.CTkButton(
            panel, text="⚙   Configurações", anchor="w", fg_color="transparent",
            hover_color="#061A2A", text_color="#8EC9ED", corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=13), command=self._open_api_settings,
        ).place(relx=0.075, rely=0.79, relwidth=0.83, relheight=0.056)

        status_box = ctk.CTkFrame(
            panel, fg_color="#020D18", corner_radius=12,
            border_width=1, border_color="#073455",
        )
        status_box.place(relx=0.06, rely=0.86, relwidth=0.87, relheight=0.095)
        self.status_dot = ctk.CTkLabel(status_box, text="●", width=18, text_color=self.REF_GREEN,
                                       font=ctk.CTkFont(size=10))
        self.status_dot.place(relx=0.07, rely=0.13, relwidth=0.1, relheight=0.34)
        self.status_label = ctk.CTkLabel(status_box, text="Online", anchor="w", text_color="#59DBD6",
                                         font=ctk.CTkFont(family="Segoe UI", size=10))
        self.status_label.place(relx=0.20, rely=0.13, relwidth=0.64, relheight=0.34)
        ctk.CTkLabel(status_box, text="☁  Gemini 3.5 Flash", anchor="w", text_color="#5EC8FF",
                     font=ctk.CTkFont(family="Segoe UI", size=9)).place(
            relx=0.08, rely=0.52, relwidth=0.83, relheight=0.3
        )
        self.activity_label = ctk.CTkLabel(
            panel, text="“Mais que um assistente,\num verdadeiro aliado.”", justify="left", anchor="w",
            text_color="#78A4BF", font=ctk.CTkFont(family="Segoe UI", size=10),
        )
        self.activity_label.place(relx=0.09, rely=0.96, relwidth=0.84, relheight=0.07, anchor="nw")

        # Compatibility references expected by inherited monitor code.
        self.cpu_gauge = self.ram_gauge = self.network_gauge = None
        self.system_log_frame = self.system_log_text = None
        self.monitor_visible = False

    # ------------------------------------------------------------------
    # CENTER — positions measured from the approved screenshot.
    # ------------------------------------------------------------------
    def _create_reference_center(self, parent):
        orb_pil = load_orb_image()
        self._reference_orb_image = ctk.CTkImage(
            light_image=orb_pil, dark_image=orb_pil, size=(310, 260)
        )
        self._cinematic_orb_label = ctk.CTkLabel(
            parent, text="", image=self._reference_orb_image, fg_color="transparent"
        )
        self._cinematic_orb_label.place(relx=0.498, rely=0.316, anchor="center")

        subtitle = ctk.CTkFrame(
            parent, fg_color="#02070D", corner_radius=14,
            border_width=1, border_color="#073455",
        )
        subtitle.place(relx=500/self.REF_W, rely=435/self.REF_H,
                       relwidth=534/self.REF_W, relheight=51/self.REF_H)
        self._cinematic_subtitle_label = ctk.CTkLabel(
            subtitle, text=f"{PUBLIC_NAME}: Pronto quando você estiver.",
            text_color=self.REF_YELLOW,
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            anchor="center", justify="center",
        )
        self._cinematic_subtitle_label.pack(fill="both", expand=True, padx=14, pady=5)

        card = ctk.CTkFrame(
            parent, fg_color="#010B17", corner_radius=18,
            border_width=1, border_color="#0879B8",
        )
        card.place(relx=396/self.REF_W, rely=511/self.REF_H,
                   relwidth=743/self.REF_W, relheight=190/self.REF_H)

        self.chat_scroll = ctk.CTkScrollableFrame(
            card, fg_color="transparent", corner_radius=15, border_width=0,
            scrollbar_button_color="#0B3550", scrollbar_button_hover_color="#12618E",
        )
        self.chat_scroll.pack(fill="both", expand=True, padx=8, pady=8)
        self.chat_display = None
        self._install_chat_mousewheel()

        state_row = ctk.CTkFrame(parent, fg_color="transparent")
        state_row.place(relx=470/self.REF_W, rely=712/self.REF_H,
                        relwidth=620/self.REF_W, relheight=45/self.REF_H)
        state_box = ctk.CTkFrame(state_row, fg_color="transparent")
        state_box.pack(expand=True)
        for idx, (key, label) in enumerate((
            ("OUVINDO", "OUVINDO"), ("PENSANDO", "PENSANDO"),
            ("EXECUTANDO", "EXECUTANDO"), ("FALANDO", "FALANDO")
        )):
            widget = ctk.CTkLabel(
                state_box, text=label, text_color="#6A879C",
                font=ctk.CTkFont(family="Consolas", size=11),
            )
            widget.pack(side="left", padx=10)
            self._conversation_voice_labels[key] = widget
            if idx < 3:
                ctk.CTkLabel(state_box, text="•", text_color="#52C8FF",
                             font=ctk.CTkFont(size=10)).pack(side="left", padx=2)

        self.input_shell = ctk.CTkFrame(
            parent, fg_color="#010A15", corner_radius=27,
            border_width=1, border_color="#0788C8",
        )
        self.input_shell.place(relx=373/self.REF_W, rely=812/self.REF_H,
                               relwidth=789/self.REF_W, relheight=71/self.REF_H)

        self.voice_button = ctk.CTkButton(
            self.input_shell, text="◉", width=46, height=48, corner_radius=20,
            fg_color="transparent", hover_color="#032038", text_color="#38C7FF",
            font=ctk.CTkFont(size=23), command=self._toggle_voice_visual_mode,
        )
        self.voice_button.pack(side="left", padx=(12, 5), pady=10)

        self.text_input = ctk.CTkTextbox(
            self.input_shell, height=self.COMPOSER_MIN_HEIGHT, wrap="word", activate_scrollbars=False,
            font=ctk.CTkFont(family="Segoe UI", size=15), text_color="#E4F2FB",
            fg_color="transparent", border_width=0, corner_radius=0,
        )
        self.text_input.pack(side="left", fill="both", expand=True, padx=(6, 8), pady=9)
        self.text_input.bind("<FocusIn>", self._composer_focus_in, add="+")
        self.text_input.bind("<FocusOut>", self._composer_focus_out, add="+")
        self.text_input.bind("<Return>", self._on_composer_return, add="+")
        self.text_input.bind("<KeyRelease>", self._resize_composer, add="+")
        self._composer_placeholder_text = "Fale com o JARVIS..."
        self._composer_set_placeholder()

        ctk.CTkLabel(
            self.input_shell, text="⌨", width=34, text_color="#79B5D6",
            font=ctk.CTkFont(size=17),
        ).pack(side="left", padx=2)
        self.send_button = ctk.CTkButton(
            self.input_shell, text="➤", width=50, height=50, corner_radius=25,
            fg_color="#031728", hover_color="#06304C", text_color="#22BFFF",
            border_width=0, font=ctk.CTkFont(size=25), command=self.send_message,
        )
        self.send_button.pack(side="right", padx=(3, 12), pady=9)

        ctk.CTkLabel(
            parent, text="J A R V I S   |   I N T E L I G Ê N C I A   Q U E   T R A B A L H A   P O R   V O C Ê",
            text_color="#27698E", font=ctk.CTkFont(family="Consolas", size=8),
        ).place(relx=0.5, rely=0.966, anchor="center")

        # Agent HUD stays hidden unless used; it is placed over the chat card,
        # not given a new permanent visual block absent from the reference.
        self.agent_hud = ctk.CTkFrame(parent, fg_color="#041424", corner_radius=12,
                                      border_width=1, border_color="#0879B8")
        self.agent_hud_title = ctk.CTkLabel(self.agent_hud, text=f"{PUBLIC_NAME} // AGENT",
                                            text_color="#77D9FF", font=ctk.CTkFont(size=10, weight="bold"))
        self.agent_hud_title.pack(anchor="w", padx=10, pady=(7, 2))
        self.agent_hud_step = ctk.CTkLabel(self.agent_hud, text="", text_color="#D8EAF5",
                                           font=ctk.CTkFont(size=10), anchor="w")
        self.agent_hud_step.pack(fill="x", padx=10, pady=(0, 4))
        self.agent_hud_progress = ctk.CTkProgressBar(self.agent_hud, height=3, progress_color=self.REF_BLUE)
        self.agent_hud_progress.pack(fill="x", padx=10, pady=(0, 7))
        self.agent_stop_button = ctk.CTkButton(self.agent_hud, text="PARAR", command=self._stop_agent_goal)

    # ------------------------------------------------------------------
    # RIGHT — same cards/spacing as approved reference. UPDATE is preserved.
    # ------------------------------------------------------------------
    def _create_reference_right(self, parent):
        clock_card = ctk.CTkFrame(
            parent, fg_color="#010914", corner_radius=17,
            border_width=1, border_color="#06304C",
        )
        clock_card.place(relx=1275/self.REF_W, rely=21/self.REF_H,
                         relwidth=237/self.REF_W, relheight=93/self.REF_H)
        self.clock_label = ctk.CTkLabel(
            clock_card, text="--:--", text_color="#B8D9F4",
            font=ctk.CTkFont(family="Consolas", size=32, weight="bold"),
        )
        self.clock_label.pack(pady=(9, 0))
        self._cinematic_date_label = ctk.CTkLabel(
            clock_card, text="--", text_color="#89B7D3",
            font=ctk.CTkFont(family="Segoe UI", size=11),
        )
        self._cinematic_date_label.pack(pady=(0, 7))

        metrics = ctk.CTkFrame(parent, fg_color="#010914", corner_radius=17,
                               border_width=1, border_color="#073755")
        metrics.place(relx=1276/self.REF_W, rely=126/self.REF_H,
                      relwidth=237/self.REF_W, relheight=190/self.REF_H)
        self._metric_cpu = self._reference_metric(metrics, "▣", "CPU", "--", 0.02)
        self._metric_ram = self._reference_metric(metrics, "▤", "RAM", "--", 0.26)
        self._metric_disk = self._reference_metric(metrics, "▱", "DISCO", "--", 0.50)
        self._metric_network = self._reference_metric(metrics, "⌁", "REDE", "Online", 0.74)

        tip = ctk.CTkFrame(parent, fg_color="#020C17", corner_radius=15,
                           border_width=1, border_color="#073755")
        tip.place(relx=1276/self.REF_W, rely=330/self.REF_H,
                  relwidth=237/self.REF_W, relheight=78/self.REF_H)
        ctk.CTkLabel(tip, text="♧", text_color="#F2E6C8", font=ctk.CTkFont(size=25)).pack(side="left", padx=(15, 10))
        ctk.CTkLabel(tip, text="Estou aqui para\nsimplificar o seu dia.", justify="left", anchor="w",
                     text_color="#94BFDC", font=ctk.CTkFont(family="Segoe UI", size=11)).pack(side="left", fill="both", expand=True)

        controls = ctk.CTkFrame(parent, fg_color="#010914", corner_radius=15,
                                border_width=1, border_color="#073755")
        controls.place(relx=1275/self.REF_W, rely=764/self.REF_H,
                       relwidth=238/self.REF_W, relheight=109/self.REF_H)
        self._continuous_var = ctk.BooleanVar(value=str(self.interaction_mode or "").lower() == "conversa")
        self._continuous_switch = ctk.CTkSwitch(
            controls, text="Modo contínuo", variable=self._continuous_var,
            progress_color="#178ED7", button_color="#A7EAFF", button_hover_color="#FFFFFF",
            text_color="#8FC6E5", font=ctk.CTkFont(size=11), command=self._toggle_continuous,
        )
        self._continuous_switch.pack(fill="x", padx=15, pady=(13, 7))
        self._captions_var = ctk.BooleanVar(value=self._cinematic_captions_enabled)
        self._captions_switch = ctk.CTkSwitch(
            controls, text="Legendas", variable=self._captions_var,
            progress_color="#178ED7", button_color="#A7EAFF", button_hover_color="#FFFFFF",
            text_color="#8FC6E5", font=ctk.CTkFont(size=11), command=self._toggle_captions,
        )
        self._captions_switch.pack(fill="x", padx=15, pady=7)

        # The reference has no update card, but the user explicitly required the
        # update button to remain. Keep it visually quiet between tip and controls.
        self.update_button = ctk.CTkButton(
            parent, text="ATUALIZAR", corner_radius=12,
            fg_color="#05243A", hover_color="#083B5B", border_width=1,
            border_color="#0879B8", text_color="#7EDBFF",
            font=ctk.CTkFont(family="Bahnschrift", size=10, weight="bold"),
            command=self._update_now,
        )
        self.update_button.place(relx=1320/self.REF_W, rely=704/self.REF_H,
                                 relwidth=145/self.REF_W, relheight=37/self.REF_H)
        self.api_button = None
        self.source_badge = None

    def _reference_metric(self, parent, icon, name, value, rely):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.place(relx=0.075, rely=rely, relwidth=0.86, relheight=0.22)
        ctk.CTkLabel(row, text=icon, width=30, text_color="#77CFFF",
                     font=ctk.CTkFont(size=18)).pack(side="left")
        ctk.CTkLabel(row, text=name, width=70, anchor="w", text_color="#8FC6E5",
                     font=ctk.CTkFont(family="Segoe UI", size=11)).pack(side="left", padx=(6, 0))
        label = ctk.CTkLabel(row, text=value, anchor="e", text_color="#A9D1EA",
                             font=ctk.CTkFont(family="Consolas", size=11))
        label.pack(side="right", fill="x", expand=True)
        return label

    def _reference_tick(self):
        self._reference_clock_job = None
        try:
            now = datetime.now()
            if self.clock_label:
                self.clock_label.configure(text=now.strftime("%H:%M"))
            if self._cinematic_date_label:
                days = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
                months = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
                self._cinematic_date_label.configure(
                    text=f"{days[now.weekday()]}, {now.day:02d} de {months[now.month-1]} de {now.year}"
                )
            self._reference_clock_job = self.root.after(1000, self._reference_tick)
        except Exception:
            pass

    # Exact approved orb is intentionally static in shape/material. State is
    # communicated by the labels/wave/captions instead of morphing its pixels.
    def _animate_cinematic_orb(self):
        return

    def _orb_frames(self, state):
        return [self._reference_orb_image]

    def _set_cinematic_orb_state(self, state, detail=""):
        state = str(state or "REPOUSO").upper()
        aliases = {
            "AGUARDANDO": "REPOUSO", "PREPARANDO": "REPOUSO", "ACORDOU": "OUVINDO",
            "ESCUTANDO": "OUVINDO", "ESPERANDO_RESPOSTA": "OUVINDO",
            "ENTENDENDO": "PENSANDO", "PROCESSANDO": "PENSANDO", "SEM_MICROFONE": "RECONECTANDO",
        }
        state = aliases.get(state, state)
        self._cinematic_orb_state = state
        palette = {"OUVINDO": "#77B3D1", "PENSANDO": "#19BFFF", "EXECUTANDO": "#A8B8C3", "FALANDO": "#A8B8C3"}
        for key, widget in self._conversation_voice_labels.items():
            try:
                widget.configure(text_color=palette[key] if key == state else "#6A879C")
            except Exception:
                pass

    def _collect_diagnostic_text(self):
        return super()._collect_diagnostic_text() + "\nReference UI: EXACT-1536x960\nReference orb: embedded approved image crop\n"


__all__ = ["JarvisGUI"]
