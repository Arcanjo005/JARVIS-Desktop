"""Scrollable controls view; delegates actions to the existing JARVIS controller."""
from __future__ import annotations

import customtkinter as ctk
from jarvis_display import place_popup


class QuickControlsPanel(ctk.CTkToplevel):
    def __init__(self, owner, anchor):
        super().__init__(owner.root)
        self.owner = owner
        self._availability_job = None
        self._last_ready = None
        self.title("Controles do JARVIS")
        self.configure(fg_color=owner.UI_BG)
        self.transient(owner.root)
        place_popup(self, anchor, 440, 630)
        self.protocol("WM_DELETE_WINDOW", owner._close_quick_control_panel)
        self.bind("<Escape>", lambda e: owner._close_quick_control_panel())
        self.feedback = ctk.CTkLabel(self, text="Controles de voz e do assistente", height=34,
                                    wraplength=380, text_color=owner.UI_MUTED)
        self.feedback.pack(fill="x", padx=12, pady=(6, 0))
        body = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        owner._populate_quick_panel_extras(body)
        rate, mic, mode, autonomy, presence = owner._quick_control_values()
        self.buttons = {}
        self.audio_buttons = []

        def section(title, value=""):
            box = ctk.CTkFrame(body, fg_color=owner.UI_SURFACE_2, corner_radius=12)
            box.pack(fill="x", padx=5, pady=5)
            header = ctk.CTkFrame(box, fg_color="transparent")
            header.pack(fill="x", padx=12, pady=6)
            ctk.CTkLabel(header, text=title, text_color=owner.UI_TEXT,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            label = ctk.CTkLabel(header, text=value, text_color=owner.UI_ACCENT,
                                 font=ctk.CTkFont(size=11))
            label.pack(side="right")
            return box, label

        def choices(box, entries, audio=False):
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=(0, 8))
            for i, (name, callback) in enumerate(entries):
                row.grid_columnconfigure(i, weight=1)
                button = owner._button(row, name, callback, 70)
                button.grid(row=0, column=i, sticky="ew", padx=3)
                self.buttons[name] = button
                if audio:
                    self.audio_buttons.append(button)

        box, owner._quick_panel_mode_value = section("MODO", mode.upper())
        choices(box, [(label, lambda key=key: owner._apply_interaction_mode_ui(key))
                      for label, key in (("Auto", "auto"), ("Conversa", "conversa"), ("Comando", "comando"))])
        box, owner._quick_panel_autonomy_value = section("AUTONOMIA", f"{autonomy}%")
        slider = ctk.CTkSlider(box, from_=20, to=100, number_of_steps=4,
                               command=owner._apply_autonomy_percent_ui)
        slider.pack(fill="x", padx=14, pady=(2, 12)); slider.set(autonomy)
        box, owner._quick_panel_presence_value = section("PRESENCA", f"{presence}%")
        slider = ctk.CTkSlider(box, from_=20, to=100, number_of_steps=4,
                               command=owner._apply_presence_percent_ui)
        slider.pack(fill="x", padx=14, pady=(2, 12)); slider.set(presence)
        box, owner._quick_panel_voice_value = section("VELOCIDADE DA VOZ", rate)
        choices(box, [(label, lambda value=value, name=label: owner._apply_voice_rate_ui(value, name))
                      for label, value in (("Devagar", "+4%"), ("Normal", "+10%"), ("Rapida", "+14%"))], audio=True)
        box, owner._quick_panel_mic_value = section("MICROFONE", f"{mic:.2f}x")
        choices(box, [(label, lambda value=value, name=label: owner._apply_mic_sensitivity_ui(value, name))
                      for label, value in (("Padrao", 1.0), ("Sensivel", 1.18), ("Muito", 1.28))], audio=True)
        box, _ = section("FERRAMENTAS")
        entries = (("Contexto atual", owner._show_operational_context), ("Rotinas", owner._show_workflows),
                   ("Esfera flutuante", lambda: owner._show_orb_style_menu(anchor)),
                   ("Memorias", owner._open_memory_manager), ("Paleta", owner._open_command_palette),
                   ("Diagnostico", owner._open_diagnostic_panel), ("Logs", owner._toggle_monitor))
        for label, callback in entries:
            button = owner._button(box, label, lambda cb=callback: owner._quick_action(cb))
            button.pack(fill="x", padx=10, pady=3)
            self.buttons[label] = button
        ctk.CTkLabel(body, text="Acoes de alto impacto continuam exigindo autorizacao.",
                     text_color=owner.UI_MUTED, wraplength=370).pack(fill="x", padx=12, pady=12)
        self._refresh_availability()
        self.after_idle(self.focus_force)

    def _voice_ready(self):
        checker = getattr(self.owner, "_v136_engine_ready", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return self.owner.voice_engine is not None

    def _refresh_availability(self):
        self._availability_job = None
        ready = self._voice_ready()
        if ready != self._last_ready:
            self._last_ready = ready
            for button in self.audio_buttons:
                button.configure(state="normal" if ready else "disabled")
            self.feedback.configure(text="Voz disponivel. Ajuste os controles abaixo." if ready else
                                     "Voz ainda nao disponivel; ajustes de audio ficam desativados.")
        self._availability_job = self.after(500, self._refresh_availability)

    def destroy(self):
        if self._availability_job is not None:
            self.after_cancel(self._availability_job)
            self._availability_job = None
        super().destroy()
