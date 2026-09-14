"""Responsive cinematic shell using real controls and the existing JARVIS runtime.

Single inheritance from gui.JarvisGUI; no v2 overlays, compatibility proxies,
source rewriting, hidden conversation widgets or runtime monkey patches here.
The renderer owns no Tk objects; callbacks, persistence and voice stay in the
existing controller. Only this shell's presentation is replaced.
"""
from __future__ import annotations

import json
import math
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox
from pathlib import Path

import customtkinter as ctk
from PIL import ImageTk

from gui import JarvisGUI as BaseJarvisGUI
from jarvis_display import fit_window, place_popup
from jarvis_quick_controls import QuickControlsPanel
from jarvis_ui_render import OrbWorker, RenderRequest, render_scene
from jarvis_version import PUBLIC_NAME, VERSION


class MessageText(ctk.CTkTextbox):
    """Selectable, wrapping message whose height follows actual Tk display lines."""
    def __init__(self, master, text, **kwargs):
        super().__init__(master, width=1, height=36, wrap="word", activate_scrollbars=False, **kwargs)
        self._measure_job = None
        self._last_width = -1
        self.insert("1.0", text)
        self.configure(state="disabled")
        self.bind("<Configure>", self._on_size, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._request_measure()

    def _on_destroy(self, event):
        if event.widget is self._textbox and self._measure_job is not None:
            self.after_cancel(self._measure_job)
            self._measure_job = None

    def _on_size(self, event):
        if event.width != self._last_width:
            self._last_width = event.width
            self._request_measure()

    def _request_measure(self):
        if self._measure_job is not None:
            self.after_cancel(self._measure_job)
        self._measure_job = self.after(80, self._measure)

    def _measure(self):
        self._measure_job = None
        if not self.winfo_exists() or self._textbox.winfo_width() < 20:
            return
        count = self._textbox.count("1.0", "end-1c", "displaylines")
        lines = (int(count[0]) if count else 0)+1
        font = tkfont.Font(root=self, font=self._textbox.cget("font"))
        scale = self._get_widget_scaling()
        native = self._textbox
        outer_padding = max(0, self.winfo_height()-native.winfo_height())
        inner_padding = 2*sum(native.winfo_pixels(native.cget(option))
                              for option in ("pady", "borderwidth", "highlightthickness"))
        height = max(36, math.ceil((lines*font.metrics("linespace")
                                    + outer_padding + inner_padding + 2)/scale))
        if abs(float(self.cget("height"))-height) > 1:
            self.configure(height=height)

    def _set_scaling(self, *args, **kwargs):
        super()._set_scaling(*args, **kwargs)
        # DPI changes can change font metrics even at the same physical width.
        # Re-measure after CTk has applied the scaled font and corner padding.
        if hasattr(self, "_measure_job"):
            self._request_measure()

    def set_message(self, text):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.insert("1.0", text or "")
        self.configure(state="disabled")
        self._request_measure()


class JarvisGUI(BaseJarvisGUI):
    UI_BG = "#030b14"
    UI_SURFACE = "#081725"
    UI_SURFACE_2 = "#0a1b2c"
    UI_SURFACE_3 = "#103049"
    UI_BORDER = "#173d55"
    UI_BORDER_STRONG = "#226886"
    UI_ACCENT = "#30c2ff"
    UI_ACCENT_HOVER = "#76d9ff"
    UI_TEXT = "#edf6fc"
    UI_MUTED = "#8cacc0"
    QUICK_MENU_GLYPH = "+"
    COMPOSER_MIN_HEIGHT = 38
    COMPOSER_MAX_HEIGHT = 116

    def _later(self, name, delay, callback):
        if self._ui_disposed:
            return
        previous = self._ui_jobs.pop(name, None)
        if previous is not None:
            self.root.after_cancel(previous)
        def run():
            self._ui_jobs.pop(name, None)
            if not self._ui_disposed:
                callback()
        self._ui_jobs[name] = self.root.after(delay, run)

    def _create_main_layout(self):
        self._ui_disposed = False
        self._ui_jobs = {}
        self._hero_photo = self._orb_photo = None
        self._scene_size = None
        self._hero_state = "REPOUSO"
        self._caption_text = "JARVIS: Pronto quando voc\u00ea estiver."
        self._drawer_open = False
        self._wide_layout = None
        self._help_window = None
        self._text_speech_requested = False
        self._text_speech_token = None
        self._text_turn_token = None
        self._speech_delivery = None
        self._update_pulsing = False
        self._update_color = None
        self._state_colors = {}
        self._load_visual_preferences()
        fit_window(self.root, initial=True)
        self._orb_worker = OrbWorker()
        self._composer_placeholder_text = "Converse ou pe\u00e7a uma a\u00e7\u00e3o ao JARVIS..."

        shell = ctk.CTkFrame(self.root, fg_color=self.UI_BG, corner_radius=0)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(shell, fg_color="transparent", height=54)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        header.grid_columnconfigure(2, weight=1)
        self.history_button = self._button(header, "Hist\u00f3rico", self._toggle_history, width=104)
        self.history_button.grid(row=0, column=0, padx=(0, 14))
        ctk.CTkLabel(header, text="J A R V I S", text_color="#c7e8fc",
                     font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=1, sticky="w")
        # The title sits inside a non-propagating slot, so long titles cannot push
        # the update control off-screen.
        title_slot = ctk.CTkFrame(header, height=34, width=1, fg_color="transparent")
        title_slot.grid(row=0, column=2, sticky="ew", padx=16)
        title_slot.grid_propagate(False)
        self.current_conversation_label = ctk.CTkLabel(title_slot, text="Nova conversa", anchor="w",
                                                       text_color=self.UI_MUTED, font=ctk.CTkFont(size=12))
        self.current_conversation_label.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.update_button = self._button(header, "ATUALIZAR", self._update_now, width=158)
        self.update_button.grid(row=0, column=3, sticky="e")

        self.content_frame = ctk.CTkFrame(shell, fg_color="transparent", corner_radius=0)
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 12))
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(1, weight=1)
        self.side_panel = ctk.CTkFrame(self.content_frame, width=242, corner_radius=18,
                                      fg_color="#06131f", border_width=1, border_color=self.UI_BORDER)
        self.side_panel.pack_propagate(False)
        self.side_panel.grid_propagate(False)
        self._build_history()
        self.sidebar_splitter = None
        self._center = ctk.CTkFrame(self.content_frame, fg_color="transparent", corner_radius=0)
        self._center.grid(row=0, column=1, sticky="nsew")
        self._center.grid_columnconfigure(0, weight=1)
        self._center.grid_rowconfigure(3, weight=1)

        self._hero = tk.Canvas(self._center, bg=self.UI_BG, height=260, highlightthickness=0, bd=0)
        self._hero.grid(row=0, column=0, sticky="nsew")
        self._scene_item = self._hero.create_image(0, 0, anchor="nw")
        self._orb_item = self._hero.create_image(0, 0, anchor="center")
        self._render_error_item = self._hero.create_text(0, 0, text="", fill="#d6b872", justify="center")
        self._hero.bind("<Configure>", self._on_hero_size)
        self._caption = ctk.CTkLabel(self._center, text="JARVIS: Pronto quando voc\u00ea estiver.",
                                    height=36, wraplength=700, text_color="#ffe15a",
                                    fg_color="#06111d", corner_radius=10,
                                    font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"))
        self._caption.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        # A real, initially empty host allows the inherited agent HUD to use
        # pack() without mixing geometry managers with the main grid.
        hud_host = ctk.CTkFrame(self._center, height=1, fg_color="transparent")
        hud_host.grid(row=2, column=0, sticky="ew")
        self._build_agent_hud(hud_host)
        chat_panel = ctk.CTkFrame(self._center, corner_radius=16, fg_color="#06131f",
                                 border_width=1, border_color=self.UI_BORDER)
        chat_panel.grid(row=3, column=0, sticky="nsew", pady=4)
        self.chat_scroll = ctk.CTkScrollableFrame(chat_panel, width=1, height=1, fg_color="#06131f",
                                                corner_radius=12, scrollbar_button_color="#20445a")
        self.chat_scroll.pack(fill="both", expand=True, padx=4, pady=4)
        self.chat_display = None
        self._install_chat_mousewheel()
        self._states = ctk.CTkFrame(self._center, fg_color="transparent")
        self._states.grid(row=4, column=0, sticky="ew")
        self._state_labels = {}
        for i, state in enumerate(("OUVINDO", "PENSANDO", "EXECUTANDO", "FALANDO")):
            self._states.grid_columnconfigure(i, weight=1)
            label = ctk.CTkLabel(self._states, text=state, height=24, text_color="#637f91",
                                 font=ctk.CTkFont(size=11))
            label.grid(row=0, column=i, sticky="ew")
            self._state_labels[state] = label
        self._wave = tk.Canvas(self._center, height=22, bg=self.UI_BG, bd=0, highlightthickness=0)
        self._wave.grid(row=5, column=0, sticky="ew")
        self._wave_bars = [self._wave.create_line(0, 0, 0, 0, fill="#229dc9", width=2) for _ in range(52)]
        self._build_composer()
        self._hint = ctk.CTkLabel(self._center, text="Pe\u00e7a uma a\u00e7\u00e3o por texto ou voz.  + Controles",
                                 height=24, text_color=self.UI_MUTED, font=ctk.CTkFont(size=11), cursor="hand2")
        self._hint.grid(row=7, column=0, sticky="ew")
        self._hint.bind("<Button-1>", lambda e: self._show_functions())
        self.root.bind("<F1>", lambda e: self._show_functions(), add="+")

        # Status fields consumed by existing controller methods are real widgets.
        self.status_label = ctk.CTkLabel(self.side_panel, text="Pronto", anchor="w", text_color=self.UI_MUTED)
        self.status_label.pack(side="bottom", fill="x", padx=14, pady=10)
        self.status_dot = self.activity_label = self.clock_label = None
        self.source_badge = self.sidebar_state_button = None
        self.system_log_frame = self.system_log_text = None
        self.monitor_visible = False
        self.root.bind("<Configure>", self._on_root_size, add="+")
        self.root.bind("<Destroy>", self._dispose_visuals, add="+")
        self._later("layout", 1, self._relayout)
        self._later("tick", 30, self._visual_tick)
        self._later("history", 70, self._refresh_conversation_list)
        self._later("update-check", 15*60*1000, self._scheduled_update_check)

    def _button(self, parent, text, command, width=100):
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=36,
                            fg_color=self.UI_SURFACE_2, hover_color=self.UI_SURFACE_3,
                            border_width=1, border_color=self.UI_BORDER_STRONG,
                            text_color=self.UI_TEXT, corner_radius=11,
                            font=ctk.CTkFont(family="Segoe UI", size=12))

    def _build_history(self):
        head = ctk.CTkFrame(self.side_panel, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(12, 8))
        ctk.CTkLabel(head, text="CONVERSAS", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#b8d6e6").pack(side="left")
        self._conversation_search_button = self._button(head, "Buscar", lambda: self._open_conversation_search_popover(self._conversation_search_button), 60)
        self._conversation_search_button.pack(side="right")
        self._new_chat_button = self._button(self.side_panel, "+ Nova conversa", self._new_conversation)
        self._new_chat_button.pack(fill="x", padx=12, pady=(0, 8))
        self.conversation_list_frame = ctk.CTkScrollableFrame(self.side_panel, width=1, height=1,
                                                            fg_color="transparent", scrollbar_button_color="#20445a")
        self.conversation_list_frame.pack(fill="both", expand=True, padx=5, pady=4)

    def _build_agent_hud(self, parent):
        self.agent_hud = ctk.CTkFrame(parent, fg_color=self.UI_SURFACE, corner_radius=12)
        self.agent_hud_title = ctk.CTkLabel(self.agent_hud, text="JARVIS", anchor="w", text_color=self.UI_ACCENT)
        self.agent_hud_title.pack(fill="x", padx=10)
        self.agent_hud_step = ctk.CTkLabel(self.agent_hud, text="", anchor="w", wraplength=550)
        self.agent_hud_step.pack(fill="x", padx=10)
        self.agent_hud_progress = ctk.CTkProgressBar(self.agent_hud, height=3)
        self.agent_hud_progress.pack(fill="x", padx=10, pady=4)
        self.agent_stop_button = self._button(self.agent_hud, "Parar", self._stop_agent_goal, 80)
        self.agent_stop_button.pack(anchor="e", padx=8, pady=4)

    def _build_composer(self):
        self.input_shell = ctk.CTkFrame(self._center, fg_color=self.UI_SURFACE_2, corner_radius=18,
                                      border_width=1, border_color=self.UI_BORDER_STRONG)
        self.input_shell.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        self.input_shell.grid_columnconfigure(1, weight=1)
        self.quick_menu_button = self._button(self.input_shell, "+", lambda: self._show_quick_actions_menu(self.quick_menu_button), 38)
        self.quick_menu_button.configure(font=ctk.CTkFont(size=25))
        self.quick_menu_button.grid(row=0, column=0, padx=(7, 3), pady=7)
        self.text_input = ctk.CTkTextbox(self.input_shell, width=1, height=self.COMPOSER_MIN_HEIGHT,
                                       wrap="word", activate_scrollbars=False, fg_color="transparent",
                                       font=ctk.CTkFont(family="Segoe UI", size=15), border_width=0)
        self.text_input.grid(row=0, column=1, sticky="ew", padx=5, pady=6)
        for event, callback in (("<FocusIn>", self._composer_focus_in), ("<FocusOut>", self._composer_focus_out),
                                ("<Return>", self._on_composer_return), ("<KeyRelease>", self._resize_composer)):
            self.text_input.bind(event, callback, add="+")
        self._composer_set_placeholder()
        self.voice_button = self._button(self.input_shell, "Voz", self._toggle_voice_visual_mode, 48)
        self.voice_button.grid(row=0, column=2, padx=3, pady=7)
        self.send_button = self._button(self.input_shell, "Enviar", self.send_message, 62)
        self.send_button.configure(fg_color="#159bce", hover_color="#39bcec")
        self.send_button.grid(row=0, column=3, padx=(3, 7), pady=7)

    def _on_root_size(self, event):
        if event.widget is self.root and not self._ui_disposed:
            self._later("layout", 80, self._relayout)
            self._later("fit", 250, lambda: fit_window(self.root))

    def _relayout(self):
        scale = self._center._get_widget_scaling()
        logical_w = self.root.winfo_width()/scale
        logical_h = self.root.winfo_height()/scale
        wide = logical_w >= 980
        if wide != self._wide_layout:
            self._wide_layout = wide
            self._drawer_open = False
            self._place_history()
        compact = logical_h < 480
        if logical_h < 410:
            self._hero.grid_remove()
        else:
            self._hero.grid()
            hero_height = max(56, min(320, (logical_h-200)*0.38))
            self._hero.configure(height=round(hero_height*scale))
        for widget in (self._states, self._wave, self._hint):
            widget.grid_remove() if compact else widget.grid()
        self._center.grid_rowconfigure(3, weight=1, minsize=round(65*scale))
        width = max(160, self._center.winfo_width()/scale-36)
        self._caption.configure(wraplength=width)
        self._refresh_caption()
        self.agent_hud_step.configure(wraplength=max(140, width-30))
        self._resize_composer()

    def _place_history(self):
        self.side_panel.grid_remove()
        self.side_panel.place_forget()
        if self._wide_layout:
            self.side_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        elif self._drawer_open:
            self.side_panel.place(x=0, y=0, relheight=1)
            self.side_panel.lift()
        self.history_button.configure(text="Fechar hist." if self._drawer_open else "Hist\u00f3rico")

    def _toggle_history(self):
        if self._wide_layout:
            if self.side_panel.winfo_manager():
                self.side_panel.grid_remove()
            else:
                self._place_history()
        else:
            self._drawer_open = not self._drawer_open
            self._place_history()

    def _on_hero_size(self, event):
        # Position follows layout immediately; expensive background resampling
        # is debounced independently and cannot leave the orb off-center.
        self._hero.coords(self._orb_item, event.width/2, event.height/2)
        self._hero.coords(self._render_error_item, event.width/2, event.height/2)
        self._later("scene", 160, self._resize_scene)

    def _resize_scene(self):
        w, h = self._hero.winfo_width(), self._hero.winfo_height()
        if w < 2 or h < 2 or (w, h) == self._scene_size:
            return
        self._scene_size = w, h
        self._hero_photo = ImageTk.PhotoImage(render_scene(w, h), master=self.root)
        self._hero.itemconfigure(self._scene_item, image=self._hero_photo)
        self._hero.coords(self._orb_item, w/2, h/2)

    def _visual_tick(self):
        visible = bool(self.root.winfo_viewable())
        orb_visible = visible and bool(self._hero.winfo_viewable())
        size = min(640, max(64, min(self._hero.winfo_width(), self._hero.winfo_height())-4))
        state = self._hero_state
        level = max(0, min(1, float(getattr(self, "voice_mic_level", 0) or 0)))
        self._hero.coords(self._orb_item, self._hero.winfo_width()/2, self._hero.winfo_height()/2)
        self._orb_worker.request(RenderRequest(size, state, level, orb_visible))
        frame = self._orb_worker.take()
        if visible and frame is not None and frame[0] == size:
            self._orb_photo = ImageTk.PhotoImage(frame[1], master=self.root)
            self._hero.itemconfigure(self._orb_item, image=self._orb_photo)
        if self._orb_worker.error and not getattr(self, "_render_error_reported", False):
            self._render_error_reported = True
            self.logger.warning(self._orb_worker.error, "UI-RENDER")
            self._hero.itemconfigure(self._render_error_item,
                                      text="Anima\u00e7\u00e3o 3D indispon\u00edvel.\nAbra + > Diagn\u00f3stico.",
                                      font=("Segoe UI", -round(13*self._center._get_widget_scaling())))
        now = time.monotonic()
        if visible:
            w, h = self._wave.winfo_width(), self._wave.winfo_height()
            active = state in {"OUVINDO", "PENSANDO", "FALANDO", "EXECUTANDO"}
            amplitude = (0.2+level*0.8) if state == "OUVINDO" else (0.7 if active else 0.1)
            for i, bar in enumerate(self._wave_bars):
                x = w/2+(i-25.5)*min(5, w/70)
                envelope = math.exp(-((i-25.5)/19)**2)
                a = 1 + h*.38*amplitude*envelope*(.4+.6*abs(math.sin(now*3.4+i*.46)))
                self._wave.coords(bar, x, h/2-a, x, h/2+a)
            self._update_pulsing = bool(self._pending_update_info is not None
                                        and not self._update_download_active
                                        and self.update_button.cget("state") != "disabled")
            amount = (.5+.5*math.sin(now*3)) if self._update_pulsing else 0
            color = "#%02x%02x%02x" % (10+int(9*amount), 27+int(72*amount), 44+int(96*amount))
            if color != self._update_color:
                self.update_button.configure(fg_color=color)
                self._update_color = color
            phase = (.5+.5*math.sin(now*3))
            active_color = "#%02x%02x%02x" % (70+int(50*phase), 170+int(48*phase), 225+int(30*phase))
            for key, label in self._state_labels.items():
                color = active_color if key == state else "#637f91"
                if self._state_colors.get(key) != color:
                    label.configure(text_color=color)
                    self._state_colors[key] = color
        self._later("tick", 45 if visible else 200, self._visual_tick)

    def _show_welcome_message(self):
        self.add_message(PUBLIC_NAME,
                         "Converse comigo ou pe\u00e7a uma a\u00e7\u00e3o. O + abre os controles; "
                         "F1 mostra exemplos. Suas conversas ficam salvas no hist\u00f3rico.",
                         is_jarvis=True)

    def _open_quick_control_panel(self, widget=None):
        self._close_quick_control_panel()
        self.quick_panel = QuickControlsPanel(self, widget or self.quick_menu_button)
        self.quick_panel_is_open = True
        self.quick_menu_button.configure(fg_color=self.UI_SURFACE_3)

    def _close_quick_control_panel(self):
        panel = self.quick_panel
        self.quick_panel = None
        self.quick_panel_is_open = False
        for name in ("voice", "mic", "mode", "autonomy", "presence"):
            setattr(self, f"_quick_panel_{name}_value", None)
        if panel is not None and panel.winfo_exists():
            panel.destroy()
        if getattr(self, "quick_menu_button", None) is not None:
            self.quick_menu_button.configure(text="+", image=None, fg_color=self.UI_SURFACE_2)

    def _quick_feedback(self, text):
        if self.quick_panel is not None and self.quick_panel.winfo_exists():
            self.quick_panel.feedback.configure(text=str(text))
        elif self.status_label is not None:
            self.status_label.configure(text=str(text), wraplength=210)
        self.logger.info(str(text), "UI-CONTROL")

    def _open_conversation_search_popover(self, anchor):
        old = self._conversation_search_popup
        if old is not None and old.winfo_exists():
            old.destroy()
            self._conversation_search_popup = None
            return
        win = ctk.CTkToplevel(self.root)
        self._conversation_search_popup = win
        win.title("Buscar conversas")
        win.transient(self.root)
        win.configure(fg_color=self.UI_BG)
        self.history_search_entry = ctk.CTkEntry(win, placeholder_text="Buscar no hist\u00f3rico...")
        self.history_search_entry.pack(fill="x", padx=12, pady=10)
        self._button(win, "Buscar", self._search_history_ui).pack(fill="x", padx=12, pady=(0, 10))
        place_popup(win, anchor, 360, 120)
        self.history_search_entry.bind("<Return>", lambda e: self._search_history_ui())
        win.bind("<Escape>", lambda e: win.destroy())
        win.after_idle(self.history_search_entry.focus_set)

    def _scheduled_update_check(self):
        if not self._update_download_active:
            threading.Thread(target=self._background_update_check,
                             name="JARVIS-UPDATE-CHECK", daemon=True).start()
        self._later("update-check", 15*60*1000, self._scheduled_update_check)

    def _show_update_available(self, info):
        if self._update_download_active:
            return
        job = self._ui_jobs.pop("update-label", None)
        if job is not None:
            self.root.after_cancel(job)
        return super()._show_update_available(info)

    def _finish_manual_update_check(self, info, error=""):
        # An old "already updated" timer must not overwrite a newer download.
        job = self._ui_jobs.pop("update-label", None)
        if job is not None:
            self.root.after_cancel(job)
        if error or info is not None:
            return super()._finish_manual_update_check(info, error)
        self._update_download_active = False
        self._pending_update_info = None
        self.update_button.configure(text="ATUALIZADO", state="normal")
        def reset_label():
            if (self._pending_update_info is None and not self._update_download_active
                    and self.update_button.cget("text") == "ATUALIZADO"):
                self.update_button.configure(text="ATUALIZAR")
        self._later("update-label", 1800, reset_label)
        messagebox.showinfo("Atualiza\u00e7\u00e3o do JARVIS", f"Voc\u00ea j\u00e1 est\u00e1 na vers\u00e3o mais recente ({VERSION}).", parent=self.root)

    def _collect_diagnostic_text(self):
        base = super()._collect_diagnostic_text()
        worker = self._orb_worker
        alive = bool(worker.process is not None and worker.process.is_alive())
        scale = self._center._get_widget_scaling()
        details = ("", "=== INTERFACE RESPONSIVA / ESFERA 3D ===",
                   f"Viewport: {self.root.winfo_width()}x{self.root.winfo_height()} px; escala {scale:.2f}",
                   f"Renderizador isolado ativo: {alive}",
                   f"Ultimo frame calculado: {worker.render_ms:.1f} ms",
                   f"Erro do renderizador: {worker.error or '-'}",
                   f"Fala no chat: {self._chat_tts_enabled}; legendas: {self._captions_enabled}")
        return base+"\n"+"\n".join(details)

    def _start_clock_updater(self):
        # This shell has no clock, so do not start a redundant timer.
        return None

    def _dispose_visuals(self, event):
        if event.widget is not self.root or self._ui_disposed:
            return
        self._ui_disposed = True
        self._orb_worker.close()
        for job in self._ui_jobs.values():
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._ui_jobs.clear()
        self._speech_delivery = None

    def _load_visual_preferences(self):
        path = Path(self.project_dir)/"data"/"ui_layout.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError) as exc:
            self.logger.warning(f"Visual preferences: {exc}", "UI")
            data = {}
        if not isinstance(data, dict):
            self.logger.warning("Visual preferences must be a JSON object; defaults restored", "UI")
            data = {}
        self._chat_tts_enabled = bool(data.get("chat_tts_enabled", True))
        self._captions_enabled = bool(data.get("cinematic_captions", True))

    def _save_visual_preferences(self):
        # Preserve the existing controller settings and atomically replace this
        # presentation's preferences. A write error is visible, never a Tk crash.
        self._save_quick_preferences()
        path = Path(self.project_dir)/"data"/"ui_layout.json"
        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data.update(chat_tts_enabled=self._chat_tts_enabled, cinematic_captions=self._captions_enabled)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            self.logger.warning(f"Visual preferences were not saved: {exc}", "UI")
            self._quick_feedback("N\u00e3o foi poss\u00edvel salvar as prefer\u00eancias. Verifique a permiss\u00e3o da pasta data.")

    def _populate_quick_panel_extras(self, body):
        box = ctk.CTkFrame(body, fg_color=self.UI_SURFACE_2, corner_radius=12)
        box.pack(fill="x", padx=5, pady=5)
        self._chat_tts_var = tk.BooleanVar(value=self._chat_tts_enabled)
        self._captions_var = tk.BooleanVar(value=self._captions_enabled)
        ctk.CTkSwitch(box, text="JARVIS fala as respostas", variable=self._chat_tts_var,
                     command=self._toggle_text_speech).pack(anchor="w", padx=12, pady=8)
        ctk.CTkSwitch(box, text="Legendas", variable=self._captions_var,
                     command=self._toggle_captions).pack(anchor="w", padx=12, pady=8)
        self._button(box, "O que posso pedir?", self._show_functions).pack(fill="x", padx=10, pady=5)
        self.api_button = self._button(box, "Configurar API", self._open_api_settings)
        self.api_button.pack(fill="x", padx=10, pady=(0, 10))

    def _toggle_text_speech(self):
        self._chat_tts_enabled = bool(self._chat_tts_var.get())
        if not self._chat_tts_enabled:
            self._text_speech_token = self._speech_delivery = None
            if self.voice_engine:
                self.voice_engine.stop_speaking(clear_queue=True)
        self._save_visual_preferences()

    def _toggle_captions(self):
        self._captions_enabled = bool(self._captions_var.get())
        self._refresh_caption()
        self._save_visual_preferences()

    def _show_functions(self):
        if self._help_window is not None and self._help_window.winfo_exists():
            self._help_window.lift()
            return
        self._close_quick_control_panel()
        win = ctk.CTkToplevel(self.root)
        self._help_window = win
        win.title("O que posso pedir ao JARVIS?")
        w, h, _, _ = place_popup(win, self.quick_menu_button, 540, 420)
        win.transient(self.root)
        win.configure(fg_color=self.UI_BG)
        body = ctk.CTkScrollableFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(body, text="Diga o que precisa. O + abre os controles.", wraplength=w-60,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(fill="x", pady=10)
        for text in ("Abra a calculadora", "Pesquise sobre energia solar", "Pause a m\u00fasica",
                     "Mostre o uso de mem\u00f3ria RAM", "Explique este assunto em palavras simples"):
            self._button(body, text, lambda value=text: self._insert_example(value)).pack(fill="x", pady=4)
        ctk.CTkLabel(body, text="Os exemplos preenchem o chat; voc\u00ea decide quando enviar.\n"
                     "Enter envia. Shift+Enter quebra a linha. Ctrl+Espa\u00e7o abre a paleta.",
                     wraplength=w-60, text_color=self.UI_MUTED).pack(fill="x", pady=12)

    def _insert_example(self, text):
        self._composer_focus_in()
        self.text_input.delete("1.0", "end")
        self.text_input.insert("1.0", text)
        self._resize_composer()
        if self._help_window is not None:
            self._help_window.destroy()
            self._help_window = None
        self.text_input.focus_set()

    def _resize_composer(self, event=None):
        if not self.text_input or self._composer_placeholder_active:
            return
        count = self.text_input._textbox.count("1.0", "end-1c", "displaylines")
        lines = min(5, (int(count[0]) if count else 0)+1)
        self.text_input.configure(height=min(self.COMPOSER_MAX_HEIGHT, max(38, lines*21+10)))

    def _create_chat_bubble(self, sender, message, is_user=False, is_jarvis=False,
                            is_system=False, timestamp=None, suppress_autoscroll=False):
        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=5)
        bubble = ctk.CTkFrame(row, fg_color="#10283b" if is_user else "#081a29", corner_radius=12,
                              border_width=1, border_color="#244d65" if is_user else "#12334b")
        bubble.pack(fill="x", padx=(32, 2) if is_user else (2, 20))
        meta = ctk.CTkFrame(bubble, fg_color="transparent")
        meta.pack(fill="x", padx=12, pady=(7, 0))
        ctk.CTkLabel(meta, text=("VOC\u00ca" if is_user else PUBLIC_NAME if is_jarvis else str(sender)),
                     height=20, text_color=self.UI_ACCENT, font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        ctk.CTkLabel(meta, text=self._format_message_time(timestamp), height=20, text_color=self.UI_MUTED,
                     font=ctk.CTkFont(size=10)).pack(side="right")
        text = MessageText(bubble, str(message or ""), fg_color="transparent", border_width=0,
                           text_color="#adbecb" if is_system else self.UI_TEXT,
                           font=ctk.CTkFont(family="Segoe UI", size=15))
        text.pack(fill="x", expand=True, padx=8, pady=(0, 6))
        self._bind_chat_mousewheel_tree(row)
        text.bind("<Control-c>", lambda event: self._copy_text_selection(text))
        if not suppress_autoscroll and not self._restoring_history:
            self._schedule_chat_scroll(force=is_user, delay=100)
        return text

    def _set_message_text(self, widget, text):
        if isinstance(widget, MessageText):
            widget.set_message(text)
        else:
            super()._set_message_text(widget, text)

    def _refresh_caption(self):
        if not self._captions_enabled:
            self._caption.configure(text="")
            return
        text = self._caption_text
        physical_width = max(160, self._center.winfo_width()-50)
        font = tkfont.Font(root=self.root, font=self._caption._label.cget("font"))
        budget = physical_width*1.6
        if font.measure(text) > budget:
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo+hi+1)//2
                if font.measure(text[:mid]+"...") <= budget:
                    lo = mid
                else:
                    hi = mid-1
            text = text[:lo].rstrip()+"..."
        self._caption.configure(text=text)

    def _set_voice_overlay_text(self, text):
        result = super()._set_voice_overlay_text(text)
        clean = " ".join(str(text or "").split())
        self._caption_text = clean if clean.lower().startswith(("jarvis:", "voc\u00ea:", "voce:")) else f"JARVIS: {clean}"
        self._refresh_caption()
        return result

    def _apply_voice_engine_state(self, state, detail):
        result = super()._apply_voice_engine_state(state, detail)
        aliases = {"AGUARDANDO": "REPOUSO", "ESCUTANDO": "OUVINDO", "ACORDOU": "OUVINDO",
                   "ESPERANDO_RESPOSTA": "OUVINDO", "ENTENDENDO": "PENSANDO", "PROCESSANDO": "PENSANDO",
                   "SEM_MICROFONE": "RECONECTANDO", "DESATIVADO": "REPOUSO"}
        self._hero_state = aliases.get(str(state).upper(), str(state).upper())
        return result

    def _update_status(self, text, color=None):
        result = super()._update_status(text, color)
        key = str(text).upper()
        if any(s in key for s in ("PROCESS", "PENS", "GERANDO", "PESQUIS")):
            self._hero_state = "PENSANDO"
        elif "EXEC" in key:
            self._hero_state = "EXECUTANDO"
        elif any(s in key for s in ("ONLINE", "PRONTO")):
            self._hero_state = "REPOUSO"
        return result

    def send_message(self, event=None):
        text = self._composer_text().strip()
        self._text_speech_requested = bool(text and len(text) <= self.COMPOSER_MAX_CHARS)
        try:
            return super().send_message(event)
        finally:
            self._text_speech_requested = False

    def _begin_work_generation(self):
        token = super()._begin_work_generation()
        self._text_turn_token = (token, self.active_conversation_id) if getattr(self, "_text_speech_requested", False) else None
        self._text_speech_token = self._text_turn_token if self._chat_tts_enabled else None
        self._speech_delivery = None
        return token

    def _deliver_text_speech(self, text):
        ticket = self._text_speech_token
        self._text_speech_token = None
        if not ticket or not text or self._restoring_history or not self._chat_tts_enabled:
            return
        self._speech_delivery = ticket
        def attempt(tries=0):
            if (self._speech_delivery != ticket or not self._chat_tts_enabled
                    or ticket[1] != self.active_conversation_id or not self._work_is_current(ticket[0])):
                return
            if self.voice_engine is None:
                if tries < 24:
                    self._later("chat-speech", 250, lambda: attempt(tries+1))
                else:
                    self.logger.warning("Voice engine unavailable for typed response", "VOICE")
                return
            self._speech_delivery = None
            try:
                self.voice_engine.speak(self._voice_spoken_summary(text), wait=False, fast=True)
            except Exception as exc:
                self.logger.warning(f"Typed response TTS: {exc}", "VOICE")
        attempt()

    def add_message(self, sender, message, is_user=False, is_jarvis=False, is_system=False, speak=False):
        if threading.get_ident() != self._main_thread_id:
            return super().add_message(sender, message, is_user, is_jarvis, is_system, speak)
        voice_turn = self._voice_command_active
        typed = bool(self._text_turn_token and not voice_turn
                     and self._text_turn_token[1] == self.active_conversation_id
                     and self._work_is_current(self._text_turn_token[0]))
        result = super().add_message(sender, message, is_user, is_jarvis, is_system, False if typed else speak)
        if is_jarvis and not is_system and typed:
            self._deliver_text_speech(message)
        return result

    def _finish_streaming_response(self, full_response, token=0):
        effective = int(token or self._active_stream_token or 0)
        if effective != self._active_stream_token or not self._work_is_current(effective):
            return
        voice_turn = self._voice_command_active
        result = super()._finish_streaming_response(full_response, token=token)
        if not voice_turn:
            self._deliver_text_speech(full_response)
        return result


__all__ = ["JarvisGUI"]
