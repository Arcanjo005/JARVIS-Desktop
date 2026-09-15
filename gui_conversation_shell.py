"""Stable JARVIS release shell matching the approved cinematic reference."""
from __future__ import annotations

import re
import threading
import time
import tkinter as tk

import customtkinter as ctk
from PIL import ImageTk

from gui_reference_exact_v3 import (
    JarvisGUI as ResponsiveJarvisGUI,
    MessageText,
    PUBLIC_NAME,
)
from jarvis_antonio_tts import AntonioNeuralTTS
from jarvis_reference_scene_139 import render_reference_scene
from jarvis_voice_lifecycle_136 import VoiceLifecycle136Mixin


class JarvisGUI(VoiceLifecycle136Mixin, ResponsiveJarvisGUI):
    """Responsive UI, safe boot, fast chat and the approved 1.3.9 visual shell."""

    def __init__(self, *args, **kwargs):
        self._antonio_tts = None
        self._pre_action_ack_until = 0.0
        self._pre_action_ack_text = ""
        self._jarvis_detail_mode = False
        super().__init__(*args, **kwargs)
        self._install_fast_chat_path()

    def _create_main_layout(self):
        super()._create_main_layout()

        try:
            old_header = self.update_button.master
            old_header.grid_remove()
        except Exception:
            old_header = None

        try:
            self.side_panel.configure(width=282, corner_radius=0, fg_color="#020b14", border_width=0)
        except Exception:
            pass

        try:
            old_history_head = self._conversation_search_button.master
            old_history_head.pack_forget()
        except Exception:
            pass

        try:
            brand = ctk.CTkFrame(self.side_panel, fg_color="transparent", height=78)
            brand.pack(fill="x", padx=16, pady=(14, 10), before=self._new_chat_button)
            brand.pack_propagate(False)
            self.history_button = self._button(brand, "◈", self._toggle_history, 48)
            self.history_button.configure(
                height=48,
                corner_radius=24,
                font=ctk.CTkFont(size=25, weight="bold"),
                fg_color="#061a2c",
                hover_color="#0b2a46",
                border_color="#168ee8",
                text_color="#6bd5ff",
            )
            self.history_button.pack(side="left", pady=10)
            ctk.CTkLabel(
                brand,
                text="JARVIS",
                text_color="#f5fbff",
                font=ctk.CTkFont(family="Segoe UI", size=27, weight="bold"),
            ).pack(side="left", padx=(12, 0), pady=12)
        except Exception:
            pass

        try:
            self._new_chat_button.configure(
                text="＋      Nova conversa",
                height=44,
                anchor="w",
                fg_color="#071726",
                hover_color="#0c2740",
                border_color="#1d4868",
            )
            self._new_chat_button.pack_configure(padx=17, pady=(0, 10))
        except Exception:
            pass

        try:
            self.reference_search_entry = ctk.CTkEntry(
                self.side_panel,
                placeholder_text="⌕  Buscar conversas...",
                height=40,
                corner_radius=11,
                fg_color="#061522",
                border_color="#173d55",
                text_color="#d9edf8",
                placeholder_text_color="#7f9bad",
            )
            self.reference_search_entry.pack(fill="x", padx=17, pady=(0, 10), after=self._new_chat_button)
            self.reference_search_entry.bind(
                "<Button-1>",
                lambda event=None: self.root.after(1, lambda: self._open_conversation_search_popover(self.reference_search_entry)),
                add="+",
            )
            self.reference_search_entry.bind(
                "<Return>",
                lambda event=None: self._open_conversation_search_popover(self.reference_search_entry),
                add="+",
            )
        except Exception:
            self.reference_search_entry = None

        try:
            self.copy_conversation_button = self._button(self.side_panel, "Copiar conversa", self._copy_conversation, width=110)
            self.copy_conversation_button.configure(
                height=34,
                fg_color="#061522",
                hover_color="#0c2740",
                text_color="#a9c5d6",
            )
            anchor = self.reference_search_entry or self._new_chat_button
            self.copy_conversation_button.pack(fill="x", padx=17, pady=(0, 8), after=anchor)
            self.root.bind("<Control-Shift-C>", lambda event=None: self._copy_conversation(), add="+")
        except Exception:
            self.copy_conversation_button = None

        try:
            self.conversation_list_frame.configure(fg_color="transparent", scrollbar_button_color="#123650")
        except Exception:
            pass

        try:
            self.status_label.pack_forget()
        except Exception:
            pass
        try:
            sidebar_tools = ctk.CTkFrame(self.side_panel, fg_color="transparent", height=58)
            sidebar_tools.pack(side="bottom", fill="x", padx=17, pady=(8, 12))
            self._button(sidebar_tools, "⚙", lambda: self._show_quick_actions_menu(self.history_button), 42).pack(side="left")
            self._button(sidebar_tools, "?", self._show_functions, 42).pack(side="left", padx=(10, 0))
        except Exception:
            pass

        try:
            self._states.grid_remove()
            self._wave.grid_remove()
            self._hint.grid_remove()
        except Exception:
            pass
        try:
            self._center.grid_rowconfigure(0, weight=5, minsize=280)
            self._center.grid_rowconfigure(3, weight=1, minsize=74)
            self._hero.configure(height=520, bg="#020810")
            self._caption.configure(
                fg_color="#04101a",
                text_color="#ffe45f",
                corner_radius=9,
                height=34,
                font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            )
            chat_panel = self.chat_scroll.master
            chat_panel.configure(fg_color="transparent", border_width=0, corner_radius=0)
            self.chat_scroll.configure(fg_color="transparent", corner_radius=0)
        except Exception:
            pass

        try:
            reference_update = self._button(self.root, "↻", self._update_now, 46)
            reference_update.configure(
                height=46,
                corner_radius=23,
                font=ctk.CTkFont(size=24),
                fg_color="#071522",
                hover_color="#0b2d48",
                border_color="#1d5276",
            )
            self.update_button = reference_update
            self._position_reference_update()
            self.root.after_idle(self._position_reference_update)
        except Exception:
            pass

        try:
            self.input_shell.configure(fg_color="#061321", corner_radius=18, border_width=1, border_color="#244d68")
            self.quick_menu_button.configure(
                text="＋", width=48, height=48, corner_radius=24,
                fg_color="#0a1d31", hover_color="#12395d",
            )
            self.voice_button.configure(
                text="●", width=48, height=48, corner_radius=24,
                fg_color="#0a2b4a", hover_color="#124c7d",
                font=ctk.CTkFont(size=18),
            )
            self.send_button.configure(
                text="➤", width=48, height=48, corner_radius=24,
                fg_color="#09243b", hover_color="#124c7d",
                font=ctk.CTkFont(size=19),
            )
        except Exception:
            pass

        self._install_reference_switches()
        self._sidebar_history_button = self.history_button
        self._compact_history_button = self._button(self._center, "◈", self._toggle_history, 48)
        self._compact_history_button.configure(height=48, corner_radius=24)
        self._place_history()
        self.root.bind("<F1>", lambda event=None: self._show_functions(), add="+")

    def _position_reference_update(self):
        """Pin updater to physical root bounds regardless of CTk DPI scaling."""
        button = getattr(self, "update_button", None)
        if button is None:
            return
        try:
            scale = float(button._get_widget_scaling() or 1.0)
        except Exception:
            scale = 1.0
        try:
            root_w = max(1, int(self.root.winfo_width()))
            margin_px = 12
            top_px = 12
            # CTk scales absolute place coordinates by widget_scaling. Convert
            # physical root pixels back to logical coordinates before place().
            logical_x = max(1.0, (root_w - margin_px) / max(0.01, scale))
            logical_y = max(1.0, top_px / max(0.01, scale))
            button.place(x=logical_x, y=logical_y, anchor="ne")
            button.lift()
        except Exception:
            pass

    def _install_reference_switches(self):
        try:
            self.reference_switch_bar = ctk.CTkFrame(
                self._center,
                fg_color="#05111d",
                corner_radius=14,
                border_width=1,
                border_color="#173b55",
                height=46,
            )
            self.reference_switch_bar.grid(row=7, column=0, sticky="ew", pady=(5, 0))

            self._chat_tts_var = tk.BooleanVar(value=bool(getattr(self, "_chat_tts_enabled", True)))
            self._captions_var = tk.BooleanVar(value=bool(getattr(self, "_captions_enabled", True)))
            self._reference_fast_var = tk.BooleanVar(value=True)
            self._reference_detail_var = tk.BooleanVar(value=False)

            def make_switch(text, variable, command):
                return ctk.CTkSwitch(
                    self.reference_switch_bar,
                    text=text,
                    variable=variable,
                    command=command,
                    progress_color="#159cff",
                    button_color="#dff7ff",
                    button_hover_color="#ffffff",
                    fg_color="#243850",
                    text_color="#e8f5fc",
                    font=ctk.CTkFont(size=11),
                    height=28,
                )

            self._reference_speech_switch = make_switch("JARVIS fala", self._chat_tts_var, self._toggle_text_speech)
            self._reference_caption_switch = make_switch("Legenda na tela", self._captions_var, self._toggle_captions)
            self._reference_fast_switch = make_switch("Modo Rápido", self._reference_fast_var, self._toggle_reference_fast)
            self._reference_detail_switch = make_switch("Modo Detalhado", self._reference_detail_var, self._toggle_reference_detail)
            self._reference_enter_label = ctk.CTkLabel(
                self.reference_switch_bar,
                text="Enter para enviar",
                text_color="#8399aa",
                font=ctk.CTkFont(size=10),
            )
            self._layout_reference_switches(1200)
        except Exception:
            self.reference_switch_bar = None

    def _layout_reference_switches(self, logical_w):
        bar = getattr(self, "reference_switch_bar", None)
        switches = (
            getattr(self, "_reference_speech_switch", None),
            getattr(self, "_reference_caption_switch", None),
            getattr(self, "_reference_fast_switch", None),
            getattr(self, "_reference_detail_switch", None),
        )
        if bar is None or any(sw is None for sw in switches):
            return
        for sw in switches:
            try:
                sw.grid_forget()
            except Exception:
                pass
        label = getattr(self, "_reference_enter_label", None)
        if label is not None:
            try:
                label.grid_forget()
            except Exception:
                pass
        for column in range(5):
            try:
                bar.grid_columnconfigure(column, weight=0, minsize=0)
            except Exception:
                pass

        if logical_w >= 850:
            bar.configure(height=46)
            for idx, sw in enumerate(switches):
                sw.configure(font=ctk.CTkFont(size=11))
                sw.grid(row=0, column=idx, padx=(14 if idx == 0 else 8, 8), pady=8, sticky="w")
            bar.grid_columnconfigure(4, weight=1)
            if label is not None:
                label.grid(row=0, column=4, padx=(8, 14), sticky="e")
            return

        bar.configure(height=78)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_columnconfigure(1, weight=1)
        compact_font = ctk.CTkFont(size=10 if logical_w < 560 else 11)
        positions = ((0, 0), (0, 1), (1, 0), (1, 1))
        for sw, (row, column) in zip(switches, positions):
            sw.configure(font=compact_font)
            sw.grid(row=row, column=column, padx=(10, 6), pady=(5, 3), sticky="w")

    def _toggle_reference_fast(self):
        enabled = bool(self._reference_fast_var.get())
        if enabled:
            self._reference_detail_var.set(False)
            self._jarvis_detail_mode = False
        elif not bool(self._reference_detail_var.get()):
            self._reference_fast_var.set(True)
        try:
            setattr(self.core, "jarvis_detail_mode", bool(self._jarvis_detail_mode))
        except Exception:
            pass

    def _toggle_reference_detail(self):
        enabled = bool(self._reference_detail_var.get())
        self._jarvis_detail_mode = enabled
        if enabled:
            self._reference_fast_var.set(False)
        elif not bool(self._reference_fast_var.get()):
            self._reference_fast_var.set(True)
        try:
            setattr(self.core, "jarvis_detail_mode", bool(self._jarvis_detail_mode))
        except Exception:
            pass

    def _relayout(self):
        scale = self._center._get_widget_scaling()
        logical_w = self.root.winfo_width() / scale
        logical_h = self.root.winfo_height() / scale
        wide = logical_w >= 980
        if wide != self._wide_layout:
            self._wide_layout = wide
            self._drawer_open = False
            self._place_history()

        self._layout_reference_switches(logical_w)
        self._position_reference_update()

        if logical_h < 430:
            self._hero.grid_remove()
        else:
            self._hero.grid()
            hero_height = max(210, min(620, logical_h * 0.58))
            self._hero.configure(height=round(hero_height * scale))

        for widget in (self._states, self._wave, self._hint):
            try:
                widget.grid_remove()
            except Exception:
                pass
        self._center.grid_rowconfigure(0, weight=0 if logical_h < 430 else 5,
                                       minsize=round((58 if logical_h < 430 else 210) * scale))
        self._center.grid_rowconfigure(3, weight=1, minsize=round(110 * scale))
        width = max(180, self._center.winfo_width() / scale - 44)
        self._caption.configure(wraplength=width)
        self._refresh_caption()
        self.agent_hud_step.configure(wraplength=max(140, width - 30))
        self._resize_composer()
        self._position_reference_update()

    def _place_history(self):
        self.side_panel.grid_remove()
        self.side_panel.place_forget()
        if hasattr(self, "_compact_history_button"):
            if self._wide_layout or self._drawer_open:
                self._compact_history_button.place_forget()
                self.history_button = self._sidebar_history_button
            else:
                self._compact_history_button.place(relx=0.025, rely=0.025, anchor="nw")
                self.history_button = self._compact_history_button
        if self._wide_layout:
            self.side_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        elif self._drawer_open:
            self.side_panel.place(x=0, y=0, relheight=1)
            self.side_panel.lift()
        try:
            self.history_button.configure(text="×" if self._drawer_open else "◈")
        except Exception:
            pass

    def _resize_scene(self):
        w, h = self._hero.winfo_width(), self._hero.winfo_height()
        if w < 2 or h < 2 or (w, h) == self._scene_size:
            return
        self._scene_size = w, h
        self._hero_photo = ImageTk.PhotoImage(render_reference_scene(w, h), master=self.root)
        self._hero.itemconfigure(self._scene_item, image=self._hero_photo)
        self._hero.coords(self._orb_item, w / 2, h / 2)

    def _on_hero_size(self, event):
        self._hero.coords(self._orb_item, event.width / 2, event.height / 2)
        self._hero.coords(self._render_error_item, event.width / 2, event.height / 2)
        self._later("scene", 160, self._resize_scene)

    def _visual_tick(self):
        super()._visual_tick()
        try:
            self._hero.coords(self._orb_item, self._hero.winfo_width() / 2, self._hero.winfo_height() / 2)
            self._position_reference_update()
        except Exception:
            pass

    def _v136_schedule_prewarm(self):
        try:
            self._v136_log("info", "Boot seguro: microfone/STT sob demanda; Antonio usa caminho leve.")
        except Exception:
            pass

    def _start_deferred_runtime(self):
        starter = getattr(self, "_v123_start_worker", None)
        core_target = getattr(getattr(self, "core", None), "prewarm", None)
        desktop_target = getattr(self, "_setup_desktop_integration", None)

        def run_worker(name, target):
            if not callable(target):
                return
            if callable(starter):
                starter(name, target)
            else:
                threading.Thread(target=target, name=name, daemon=True).start()

        def warm_short_tts():
            try:
                self._get_antonio_tts().prefetch("Certo, pesquisando.")
            except Exception:
                pass

        try:
            self.root.after(180, lambda: run_worker("JARVIS-BOOT-DESKTOP-SAFE", desktop_target))
            self.root.after(650, lambda: run_worker("JARVIS-BOOT-AI-SAFE", core_target))
            self.root.after(1800, lambda: run_worker("JARVIS-TTS-PREFETCH", warm_short_tts))
        except Exception:
            run_worker("JARVIS-BOOT-DESKTOP-SAFE", desktop_target)
            run_worker("JARVIS-BOOT-AI-SAFE", core_target)

    @staticmethod
    def _fast_standalone_question(message: str) -> bool:
        text = " ".join(str(message or "").split()).strip()
        if not text or len(text) > 180:
            return False
        key = text.lower()
        words = re.findall(r"[\wÀ-ÿ]+", key)
        if not 2 <= len(words) <= 22:
            return False
        if re.search(
            r"\b(?:ele|ela|eles|elas|isso|isto|esse|essa|este|esta|aquele|aquela|tambem|também|depois|anterior|mesmo|mesma|continua|continue|explica melhor|como assim|e se|e quando|e onde|sobre isso|lembra|lembr[a-z]*)\b",
            key,
        ):
            return False
        if re.match(r"^(?:e|mas|entao|então|ai|aí|certo|beleza|sim|nao|não)\b", key):
            return False
        if re.search(
            r"\b(?:abre|abra|abrir|fecha|feche|fechar|minimiza|maximiza|move|mova|pesquisa|pesquise|pesquisar|procura|buscar|busca|clica|clique|pausa|continua|toque|toca|volume|arquivo|pasta|monitor|tela)\b",
            key,
        ):
            return False
        return bool(
            text.endswith("?")
            or re.match(r"^(?:o que|oq|qual|quais|quem|quanto|quantos|quanta|quantas|como|por que|porque|onde|quando|me diga|me explica|explique|define|defina)\b", key)
        )

    def _install_fast_chat_path(self):
        core = getattr(self, "core", None)
        original = getattr(core, "process_message_stream", None)
        if not callable(original) or bool(getattr(core, "_jarvis_139_fast_path", False)):
            return

        def fast_stream(message, conversation_history, memories, system_commands_info="", on_chunk=None, speaker_name="", source="text"):
            if (
                str(source or "text").lower() == "text"
                and not bool(getattr(self, "_jarvis_detail_mode", False))
                and self._fast_standalone_question(message)
            ):
                conversation_history = list(conversation_history or [])[-2:]
                memories = []
                system_commands_info = ""
            return original(
                message,
                conversation_history,
                memories,
                system_commands_info,
                on_chunk=on_chunk,
                speaker_name=speaker_name,
                source=source,
            )

        core.process_message_stream = fast_stream
        core._jarvis_139_fast_path = True

    def _get_antonio_tts(self):
        engine = self._antonio_tts
        if engine is not None:
            return engine
        engine = AntonioNeuralTTS(
            project_dir=self.project_dir,
            logger=getattr(self, "logger", None),
            on_start=getattr(self, "_on_voice_tts_start", None),
            on_end=getattr(self, "_on_voice_tts_end", None),
        )
        self._antonio_tts = engine
        return engine

    def _speak(self, text: str):
        clean = str(text or "").strip()
        if not clean:
            return None
        if hasattr(self, "_chat_tts_enabled") and not bool(getattr(self, "_chat_tts_enabled", True)):
            return None
        voice_engine = getattr(self, "voice_engine", None)
        if voice_engine is not None and bool(getattr(voice_engine, "_started", False)):
            return super()._speak(clean)
        try:
            self._get_antonio_tts().speak(clean, interrupt=True)
            return True
        except Exception as exc:
            try:
                self._v136_log("warning", f"Antonio Neural leve indisponivel: {exc}")
            except Exception:
                pass
            return None

    def _speak_action_ack(self, text: str):
        clean = str(text or "").strip()
        if not clean or not bool(getattr(self, "_chat_tts_enabled", True)):
            return None
        try:
            voice_engine = getattr(self, "voice_engine", None)
            if voice_engine is not None and bool(getattr(voice_engine, "_started", False)):
                return voice_engine.speak(clean, wait=False, fast=True)
            return self._get_antonio_tts().speak(clean, interrupt=True)
        except Exception:
            return None

    def _execute_v8_command_result(self, command: str):
        value = str(command or "")
        if value.startswith("v8:browser_search:"):
            self._pre_action_ack_text = "Certo, pesquisando."
            self._pre_action_ack_until = time.monotonic() + 3.0
            threading.Thread(
                target=self._speak_action_ack,
                args=(self._pre_action_ack_text,),
                name="JARVIS-ACTION-ACK",
                daemon=True,
            ).start()
        return super()._execute_v8_command_result(command)

    def _deliver_text_speech(self, text):
        ticket = getattr(self, "_text_speech_token", None)
        self._text_speech_token = None
        if not ticket or not text or bool(getattr(self, "_restoring_history", False)) or not bool(getattr(self, "_chat_tts_enabled", False)):
            return None
        self._speech_delivery = ticket
        if self._speech_delivery != ticket or ticket[1] != self.active_conversation_id or not self._work_is_current(ticket[0]):
            return None
        spoken = self._voice_spoken_summary(text)
        if not spoken:
            self._speech_delivery = None
            return None
        if time.monotonic() <= float(getattr(self, "_pre_action_ack_until", 0.0) or 0.0):
            key = " ".join(str(spoken).lower().split())
            duplicate_ack = len(key) <= 130 and ("pesquis" in key or "buscand" in key) and any(marker in key for marker in ("certo", "ok", "abrindo", "vou ", "opera", "navegador"))
            if duplicate_ack:
                self._speech_delivery = None
                self._pre_action_ack_until = 0.0
                self._pre_action_ack_text = ""
                return None
        voice_engine = getattr(self, "voice_engine", None)
        use_voice_engine = bool(voice_engine is not None and (not hasattr(voice_engine, "_started") or bool(getattr(voice_engine, "_started", False))))
        self._speech_delivery = None
        try:
            if use_voice_engine:
                return voice_engine.speak(spoken, wait=False, fast=True)
            return self._get_antonio_tts().speak(spoken, interrupt=True)
        except Exception:
            return None

    def _setup_qt_voice_overlay(self):
        existing = getattr(self, "qt_voice_overlay", None)
        if existing is not None:
            try:
                if existing.is_alive():
                    self._qt_overlay_active = True
                    return True
            except Exception:
                pass
        try:
            from jarvis_voice_overlay_139 import QtVoiceOverlayController
            controller = QtVoiceOverlayController(self.project_dir, logger=self.logger)
            if not controller.start():
                raise RuntimeError("processo Qt nao iniciou")
            self.qt_voice_overlay = controller
            self._qt_overlay_active = True
            try:
                controller.set_orb_style(getattr(self, "voice_orb_style", "default"))
                controller.set_conversation_lock(str(getattr(self, "interaction_mode", "") or "").lower() == "conversa")
            except Exception:
                pass
            try:
                self._post_ui_event("runtime_ready", "overlay")
            except Exception:
                pass
            return True
        except Exception as exc:
            self.qt_voice_overlay = None
            self._qt_overlay_active = False
            try:
                self.logger.warning(f"Overlay Qt 1.3.9 indisponivel: {exc}", "OVERLAY")
            except Exception:
                pass
            return False

    def _qt_overlay_position(self):
        width = 420
        orb_cx, orb_cy, visible_radius, margin = width // 2, 38, 42, 18
        left = top = 0
        try:
            if self.window_manager:
                monitor = self.window_manager.get_active_monitor()
                right = int(monitor["right"]); bottom = int(monitor["bottom"])
                left = int(monitor.get("left", 0)); top = int(monitor.get("top", 0))
            else:
                right = int(self.root.winfo_screenwidth()); bottom = int(self.root.winfo_screenheight())
        except Exception:
            right = int(self.root.winfo_screenwidth()); bottom = int(self.root.winfo_screenheight())
        x = right - margin - visible_radius - orb_cx
        y = bottom - margin - visible_radius - orb_cy
        return max(left - orb_cx + visible_radius, x), max(top - orb_cy + visible_radius, y)

    def _create_chat_bubble(self, sender, message, is_user=False, is_jarvis=False,
                            is_system=False, timestamp=None, suppress_autoscroll=False):
        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=4)
        bubble = ctk.CTkFrame(
            row,
            fg_color="#0a1d2c" if is_user else "#061522",
            corner_radius=11,
            border_width=1,
            border_color="#1d5878" if is_user else "#12354a",
        )
        bubble.pack(fill="x", padx=(34, 2) if is_user else (2, 22))
        meta = ctk.CTkFrame(bubble, fg_color="transparent")
        meta.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(
            meta,
            text=("VOCÊ" if is_user else PUBLIC_NAME if is_jarvis else str(sender)),
            height=18,
            text_color=self.UI_ACCENT,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            meta,
            text=self._format_message_time(timestamp),
            height=18,
            text_color=self.UI_MUTED,
            font=ctk.CTkFont(size=9),
        ).pack(side="right")
        text = MessageText(
            bubble,
            str(message or ""),
            fg_color="transparent",
            border_width=0,
            text_color="#adbecb" if is_system else self.UI_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=14),
        )
        text.pack(fill="x", expand=True, padx=8, pady=(0, 5))
        self._bind_chat_mousewheel_tree(row)
        text.bind("<Control-c>", lambda event=None: self._copy_text_selection(text))
        if not suppress_autoscroll and not self._restoring_history:
            self._schedule_chat_scroll(force=is_user, delay=100)
        return text


__all__ = ["JarvisGUI"]
