"""Stable JARVIS release shell matching the approved cinematic reference."""
from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import platform
import re
import sys
import threading
import time
import tkinter as tk
import unicodedata
from urllib.parse import quote_plus

import customtkinter as ctk
from PIL import ImageTk

import jarvis_router as _jarvis_router
from jarvis_router import context_status as v8_context_status, remember_topic as v8_remember_topic
from gui_reference_exact_v3 import (
    JarvisGUI as ResponsiveJarvisGUI,
    MessageText,
    PUBLIC_NAME,
)
from jarvis_antonio_tts import AntonioNeuralTTS
from jarvis_reference_scene_139 import render_reference_scene
from jarvis_voice_lifecycle_136 import VoiceLifecycle136Mixin


def _fold_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Guard conservador para planos pessoais. "Eu quero montar uma bancada" e
# "vou criar um espaço no quarto" sao conversa; "crie uma pasta" continua
# sendo comando. O router importou classify_speech_act como global, por isso a
# correcao e instalada no namespace que realmente toma a decisao.
_original_router_classify = getattr(_jarvis_router, "classify_speech_act", None)
if callable(_original_router_classify) and not getattr(_jarvis_router, "_jarvis_personal_plan_guard", False):
    def _jarvis_personal_plan_classify(text: str):
        key = _fold_text(text)
        personal_plan = re.match(
            r"^(?:eu\s+)?(?:quero|vou|pretendo|planejo|penso\s+em|estou\s+pensando\s+em|to\s+pensando\s+em)\s+"
            r"(?:montar|criar|fazer|construir|produzir|organizar)\b",
            key,
        )
        digital_object = re.search(
            r"\b(?:pasta|arquivo|regra|rotina|atalho|screenshot|print|planilha|documento)\b",
            key,
        )
        if personal_plan and not digital_object:
            return "assertion"
        return _original_router_classify(text)

    _jarvis_router.classify_speech_act = _jarvis_personal_plan_classify
    _jarvis_router._jarvis_personal_plan_guard = True


class JarvisGUI(VoiceLifecycle136Mixin, ResponsiveJarvisGUI):
    """Responsive UI, safe boot, fast chat and the approved cinematic shell."""

    def __init__(self, *args, **kwargs):
        # Precisa existir antes do super: o construtor base ja pode registrar
        # mensagens e estados que sao uteis no relatorio de diagnostico.
        self._diagnostic_events = deque(maxlen=360)
        self._diagnostic_lock = threading.Lock()
        self._last_user_request = ""
        self._last_failed_request = ""
        self._antonio_tts = None
        self._pre_action_ack_until = 0.0
        self._pre_action_ack_text = ""
        self._jarvis_detail_mode = False
        super().__init__(*args, **kwargs)
        self._install_fast_chat_path()
        self._diag("boot", "shell cinematico carregado")

    def _diag(self, event: str, detail: str = "", **data) -> None:
        try:
            row = {
                "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "event": str(event or "event"),
                "detail": str(detail or "")[:1200],
            }
            if data:
                row["data"] = data
            with self._diagnostic_lock:
                self._diagnostic_events.append(row)
        except Exception:
            pass

    def add_message(self, sender: str, message: str, is_user: bool = False, is_jarvis: bool = False, is_system: bool = False, speak: bool = False):
        text = str(message or "")
        try:
            self._diag(
                "message",
                text,
                sender=str(sender or ""),
                user=bool(is_user),
                jarvis=bool(is_jarvis),
                system=bool(is_system),
            )
            if is_user:
                retry_key = _fold_text(text)
                if retry_key not in {"tenta de novo", "tenta novamente", "tenta outra vez", "repete", "repete a pergunta"}:
                    self._last_user_request = text.strip()
            elif is_jarvis:
                key = _fold_text(text)
                if any(marker in key for marker in (
                    "nao respondeu a tempo",
                    "demorou mais que o esperado",
                    "nao consegui concluir a resposta neste turno",
                    "pode enviar novamente",
                    "pode mandar de novo",
                )):
                    self._last_failed_request = str(getattr(self, "_last_user_request", "") or "").strip()
                    self._diag("remote_timeout", text, retry_target=self._last_failed_request[:500])
        except Exception:
            pass
        return super().add_message(sender, message, is_user=is_user, is_jarvis=is_jarvis, is_system=is_system, speak=speak)

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
            self.history_button.configure(height=48, corner_radius=24, font=ctk.CTkFont(size=25, weight="bold"), fg_color="#061a2c", hover_color="#0b2a46", border_color="#168ee8", text_color="#6bd5ff")
            self.history_button.pack(side="left", pady=10)
            ctk.CTkLabel(brand, text="JARVIS", text_color="#f5fbff", font=ctk.CTkFont(family="Segoe UI", size=27, weight="bold")).pack(side="left", padx=(12, 0), pady=12)
        except Exception:
            pass

        try:
            self._new_chat_button.configure(text="＋      Nova conversa", height=44, anchor="w", fg_color="#071726", hover_color="#0c2740", border_color="#1d4868")
            self._new_chat_button.pack_configure(padx=17, pady=(0, 10))
        except Exception:
            pass

        try:
            self.reference_search_entry = ctk.CTkEntry(self.side_panel, placeholder_text="⌕  Buscar conversas...", height=40, corner_radius=11, fg_color="#061522", border_color="#173d55", text_color="#d9edf8", placeholder_text_color="#7f9bad")
            self.reference_search_entry.pack(fill="x", padx=17, pady=(0, 10), after=self._new_chat_button)
            self.reference_search_entry.bind("<Button-1>", lambda event=None: self.root.after(1, lambda: self._open_conversation_search_popover(self.reference_search_entry)), add="+")
            self.reference_search_entry.bind("<Return>", lambda event=None: self._open_conversation_search_popover(self.reference_search_entry), add="+")
        except Exception:
            self.reference_search_entry = None

        try:
            self.copy_conversation_button = self._button(self.side_panel, "Copiar diagnóstico", self._copy_full_diagnostic, width=110)
            self.copy_conversation_button.configure(height=34, fg_color="#061522", hover_color="#0c2740", text_color="#a9c5d6")
            anchor = self.reference_search_entry or self._new_chat_button
            self.copy_conversation_button.pack(fill="x", padx=17, pady=(0, 8), after=anchor)
            self.root.bind("<Control-Shift-C>", lambda event=None: self._copy_full_diagnostic(), add="+")
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
            self._states.grid_remove(); self._wave.grid_remove(); self._hint.grid_remove()
        except Exception:
            pass
        try:
            self._center.grid_rowconfigure(0, weight=5, minsize=280)
            self._center.grid_rowconfigure(3, weight=1, minsize=74)
            self._hero.configure(height=520, bg="#020810")
            self._caption.configure(fg_color="#04101a", text_color="#ffe45f", corner_radius=9, height=34, font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"))
            chat_panel = self.chat_scroll.master
            chat_panel.configure(fg_color="transparent", border_width=0, corner_radius=0)
            self.chat_scroll.configure(fg_color="transparent", corner_radius=0)
        except Exception:
            pass

        try:
            reference_update = self._button(self.root, "↻", self._update_now, 46)
            reference_update.configure(height=46, corner_radius=23, font=ctk.CTkFont(size=24), fg_color="#071522", hover_color="#0b2d48", border_color="#1d5276")
            self.update_button = reference_update
            self._position_reference_update()
            self.root.after_idle(self._position_reference_update)
        except Exception:
            pass

        try:
            self.input_shell.configure(fg_color="#061321", corner_radius=18, border_width=1, border_color="#244d68")
            self.quick_menu_button.configure(text="＋", width=48, height=48, corner_radius=24, fg_color="#0a1d31", hover_color="#12395d")
            self.voice_button.configure(text="●", width=48, height=48, corner_radius=24, fg_color="#0a2b4a", hover_color="#124c7d", font=ctk.CTkFont(size=18))
            self.send_button.configure(text="➤", width=48, height=48, corner_radius=24, fg_color="#09243b", hover_color="#124c7d", font=ctk.CTkFont(size=19))
        except Exception:
            pass

        self._install_reference_switches()
        self._sidebar_history_button = self.history_button
        self._compact_history_button = self._button(self._center, "◈", self._toggle_history, 48)
        self._compact_history_button.configure(height=48, corner_radius=24)
        self._place_history()
        self.root.bind("<F1>", lambda event=None: self._show_functions(), add="+")

    def _copy_full_diagnostic(self):
        """Copy conversation plus runtime evidence needed to reproduce failures."""
        self._diag("diagnostic_copy", "usuario solicitou diagnostico completo")
        try:
            from jarvis_version import JARVIS_VERSION
        except Exception:
            JARVIS_VERSION = "?"

        try:
            root_geometry = self.root.geometry()
        except Exception:
            root_geometry = "?"
        try:
            widget_scale = float(self._center._get_widget_scaling())
        except Exception:
            widget_scale = 1.0
        try:
            window_scale = float(self._center._get_window_scaling())
        except Exception:
            window_scale = 1.0

        core = getattr(self, "core", None)
        try:
            api_status = core.get_api_status() if core is not None else "indisponível"
        except Exception as exc:
            api_status = f"erro: {exc}"
        core_health = {
            "available": bool(getattr(core, "is_available", lambda: False)()) if core is not None else False,
            "last_remote_success_at": str(getattr(core, "last_remote_success_at", "")),
            "last_remote_error_at": str(getattr(core, "last_remote_error_at", "")),
            "last_remote_error": str(getattr(core, "last_remote_error", ""))[:1000],
            "api_status": str(api_status),
        }

        antonio = getattr(self, "_antonio_tts", None)
        voice = getattr(self, "voice_engine", None)
        runtime = {
            "version": str(JARVIS_VERSION),
            "timestamp_local": datetime.now().astimezone().isoformat(timespec="seconds"),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "geometry": root_geometry,
            "widget_scale": widget_scale,
            "window_scale": window_scale,
            "interaction_mode": str(getattr(self, "interaction_mode", "")),
            "captions_enabled": bool(getattr(self, "_captions_enabled", False)),
            "chat_tts_enabled": bool(getattr(self, "_chat_tts_enabled", False)),
            "antonio_speaking": bool(getattr(antonio, "speaking", False)) if antonio is not None else False,
            "voice_engine_started": bool(getattr(voice, "_started", False)) if voice is not None else False,
            "window_manager_loaded": bool(getattr(self, "window_manager", None)),
            "optional_import_errors": dict(getattr(self, "_advanced_import_errors", {}) or {}),
            "core": core_health,
        }

        try:
            context = v8_context_status()
        except Exception as exc:
            context = {"error": str(exc)}
        try:
            with self._diagnostic_lock:
                events = list(self._diagnostic_events)
        except Exception:
            events = []
        try:
            logs = list(self.logger.get_buffer_logs(100))
        except Exception:
            logs = []
        try:
            conversation = self._conversation_as_text()
        except Exception as exc:
            conversation = f"<falha ao exportar conversa: {exc}>"

        report = "\n".join((
            "=== JARVIS - DIAGNÓSTICO COMPLETO ===",
            json.dumps(runtime, ensure_ascii=False, indent=2, default=str),
            "",
            "=== CONTEXTO / REFERÊNCIAS ===",
            json.dumps(context, ensure_ascii=False, indent=2, default=str),
            "",
            "=== LINHA DO TEMPO DA SESSÃO ===",
            json.dumps(events, ensure_ascii=False, indent=2, default=str),
            "",
            "=== LOGS RECENTES ===",
            "\n".join(str(row) for row in logs) or "<sem logs no buffer>",
            "",
            "=== CONVERSA COMPLETA ===",
            conversation,
        ))
        self._copy_to_clipboard(report)
        return report

    def _position_reference_update(self):
        """Pin updater in physical Tk pixels, bypassing CTk place scaling."""
        button = getattr(self, "update_button", None)
        if button is None:
            return
        try:
            root_w_px = max(1, int(self.root.winfo_width()))
            button_w_px = max(1, int(button.winfo_width()))
            if button_w_px <= 1:
                try:
                    scale = float(button._get_widget_scaling() or 1.0)
                except Exception:
                    scale = 1.0
                button_w_px = max(1, round(46 * scale))
            margin_px = 12
            top_px = 12
            left_px = max(0, root_w_px - margin_px - button_w_px)
            button.tk.call(
                "place", "configure", button._w,
                "-x", int(left_px),
                "-y", int(top_px),
                "-anchor", "nw",
            )
            button.lift()
        except Exception:
            pass

    def _install_reference_switches(self):
        try:
            self.reference_switch_bar = ctk.CTkFrame(self._center, fg_color="#05111d", corner_radius=14, border_width=1, border_color="#173b55", height=46)
            self.reference_switch_bar.grid(row=7, column=0, sticky="ew", pady=(5, 0))
            self._chat_tts_var = tk.BooleanVar(value=bool(getattr(self, "_chat_tts_enabled", True)))
            self._captions_var = tk.BooleanVar(value=bool(getattr(self, "_captions_enabled", True)))
            self._reference_fast_var = tk.BooleanVar(value=False)
            self._reference_detail_var = tk.BooleanVar(value=False)
            def make_switch(text, variable, command):
                return ctk.CTkSwitch(self.reference_switch_bar, text=text, variable=variable, command=command, progress_color="#159cff", button_color="#dff7ff", button_hover_color="#ffffff", fg_color="#243850", text_color="#e8f5fc", font=ctk.CTkFont(size=11), height=28)
            self._reference_speech_switch = make_switch("JARVIS fala", self._chat_tts_var, self._toggle_text_speech)
            self._reference_caption_switch = make_switch("Legenda na tela", self._captions_var, self._toggle_captions)
            self._reference_fast_switch = make_switch("Modo Rápido", self._reference_fast_var, self._toggle_reference_fast)
            self._reference_detail_switch = make_switch("Modo Detalhado", self._reference_detail_var, self._toggle_reference_detail)
            self._reference_enter_label = ctk.CTkLabel(self.reference_switch_bar, text="Enter para enviar", text_color="#8399aa", font=ctk.CTkFont(size=10))
            self._layout_reference_switches(1200)
        except Exception:
            self.reference_switch_bar = None

    def _layout_reference_switches(self, logical_w):
        bar = getattr(self, "reference_switch_bar", None)
        switches = (getattr(self, "_reference_speech_switch", None), getattr(self, "_reference_caption_switch", None), getattr(self, "_reference_fast_switch", None), getattr(self, "_reference_detail_switch", None))
        if bar is None or any(sw is None for sw in switches): return
        for sw in switches:
            try: sw.grid_forget()
            except Exception: pass
        label = getattr(self, "_reference_enter_label", None)
        if label is not None:
            try: label.grid_forget()
            except Exception: pass
        for column in range(5):
            try: bar.grid_columnconfigure(column, weight=0, minsize=0)
            except Exception: pass
        if logical_w >= 850:
            bar.configure(height=46)
            for idx, sw in enumerate(switches):
                sw.configure(font=ctk.CTkFont(size=11)); sw.grid(row=0, column=idx, padx=(14 if idx == 0 else 8, 8), pady=8, sticky="w")
            bar.grid_columnconfigure(4, weight=1)
            if label is not None: label.grid(row=0, column=4, padx=(8, 14), sticky="e")
            return
        bar.configure(height=78); bar.grid_columnconfigure(0, weight=1); bar.grid_columnconfigure(1, weight=1)
        compact_font = ctk.CTkFont(size=10 if logical_w < 560 else 11)
        for sw, (row, column) in zip(switches, ((0,0),(0,1),(1,0),(1,1))):
            sw.configure(font=compact_font); sw.grid(row=row, column=column, padx=(10,6), pady=(5,3), sticky="w")

    def _toggle_reference_fast(self):
        enabled = bool(self._reference_fast_var.get())
        if enabled:
            self._reference_detail_var.set(False); self._jarvis_detail_mode = False
        try: setattr(self.core, "jarvis_detail_mode", bool(self._jarvis_detail_mode))
        except Exception: pass

    def _toggle_reference_detail(self):
        enabled = bool(self._reference_detail_var.get()); self._jarvis_detail_mode = enabled
        if enabled: self._reference_fast_var.set(False)
        try: setattr(self.core, "jarvis_detail_mode", bool(self._jarvis_detail_mode))
        except Exception: pass

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

        hide_hero = logical_h < 560
        if hide_hero:
            self._hero.grid_remove()
            self._center.grid_rowconfigure(0, weight=0, minsize=0)
        else:
            self._hero.grid()
            reserve_logical = 300 if logical_w < 850 else 270
            hero_height = max(150, min(560, (logical_h - reserve_logical) * 0.72))
            hero_px = max(1, round(hero_height * scale))
            self._hero.configure(height=hero_px)
            self._center.grid_rowconfigure(0, weight=0, minsize=hero_px)

        for widget in (self._states, self._wave, self._hint):
            try:
                widget.grid_remove()
            except Exception:
                pass

        chat_min = 70 if logical_h < 700 else 90
        self._center.grid_rowconfigure(3, weight=1, minsize=round(chat_min * scale))
        width = max(180, self._center.winfo_width() / scale - 44)
        self._caption.configure(wraplength=width)
        self._refresh_caption()
        self.agent_hud_step.configure(wraplength=max(140, width - 30))
        self._resize_composer()
        self._position_reference_update()

    def _place_history(self):
        self.side_panel.grid_remove(); self.side_panel.place_forget()
        if hasattr(self, "_compact_history_button"):
            if self._wide_layout or self._drawer_open:
                self._compact_history_button.place_forget(); self.history_button = self._sidebar_history_button
            else:
                self._compact_history_button.place(relx=0.025, rely=0.025, anchor="nw"); self.history_button = self._compact_history_button
        if self._wide_layout: self.side_panel.grid(row=0, column=0, sticky="nsew", padx=(0,1))
        elif self._drawer_open: self.side_panel.place(x=0, y=0, relheight=1); self.side_panel.lift()
        try: self.history_button.configure(text="×" if self._drawer_open else "◈")
        except Exception: pass

    def _resize_scene(self):
        w,h=self._hero.winfo_width(),self._hero.winfo_height()
        if w<2 or h<2 or (w,h)==self._scene_size:return
        self._scene_size=w,h; self._hero_photo=ImageTk.PhotoImage(render_reference_scene(w,h),master=self.root); self._hero.itemconfigure(self._scene_item,image=self._hero_photo); self._hero.coords(self._orb_item,w/2,h/2)

    def _on_hero_size(self,event):
        self._hero.coords(self._orb_item,event.width/2,event.height/2); self._hero.coords(self._render_error_item,event.width/2,event.height/2); self._later("scene",160,self._resize_scene)

    def _visual_tick(self):
        super()._visual_tick()
        try: self._hero.coords(self._orb_item,self._hero.winfo_width()/2,self._hero.winfo_height()/2); self._position_reference_update()
        except Exception: pass

    def _v136_schedule_prewarm(self):
        try:self._v136_log("info","Boot seguro: microfone/STT sob demanda; Antonio usa caminho leve.")
        except Exception:pass

    def _start_deferred_runtime(self):
        starter=getattr(self,"_v123_start_worker",None);core_target=getattr(getattr(self,"core",None),"prewarm",None);desktop_target=getattr(self,"_setup_desktop_integration",None)
        def run_worker(name,target):
            if not callable(target):return
            if callable(starter):starter(name,target)
            else:threading.Thread(target=target,name=name,daemon=True).start()
        def warm_short_tts():
            try:self._get_antonio_tts().prefetch("Certo, pesquisando.")
            except Exception:pass
        try:
            self.root.after(180,lambda:run_worker("JARVIS-BOOT-DESKTOP-SAFE",desktop_target));self.root.after(650,lambda:run_worker("JARVIS-BOOT-AI-SAFE",core_target));self.root.after(1800,lambda:run_worker("JARVIS-TTS-PREFETCH",warm_short_tts))
        except Exception:
            run_worker("JARVIS-BOOT-DESKTOP-SAFE",desktop_target);run_worker("JARVIS-BOOT-AI-SAFE",core_target)

    @staticmethod
    def _fast_standalone_question(message:str)->bool:
        text=" ".join(str(message or "").split()).strip()
        if not text or len(text)>180:return False
        key=text.lower();words=re.findall(r"[\wÀ-ÿ]+",key)
        if not 2<=len(words)<=22:return False
        if re.search(r"\b(?:ele|ela|eles|elas|isso|isto|esse|essa|este|esta|aquele|aquela|tambem|também|depois|anterior|mesmo|mesma|continua|continue|explica melhor|como assim|e se|e quando|e onde|sobre isso|lembra|lembr[a-z]*)\b",key):return False
        if re.match(r"^(?:e|mas|entao|então|ai|aí|certo|beleza|sim|nao|não)\b",key):return False
        if re.search(r"\b(?:abre|abra|abrir|fecha|feche|fechar|minimiza|maximiza|move|mova|pesquisa|pesquise|pesquisar|procura|buscar|busca|clica|clique|pausa|continua|toque|toca|volume|arquivo|pasta|monitor|tela)\b",key):return False
        return bool(text.endswith("?") or re.match(r"^(?:o que|oq|qual|quais|quem|quanto|quantos|quanta|quantas|como|por que|porque|onde|quando|me diga|me explica|explique|define|defina)\b",key))

    @staticmethod
    def _local_social_reply(message: str) -> str:
        key = _fold_text(message)
        hour = datetime.now().hour
        greeting = "Bom dia" if 5 <= hour < 12 else "Boa tarde" if 12 <= hour < 18 else "Boa noite"
        if key in {"oi", "ola", "opa", "eai", "e ai", "oi jarvis", "ola jarvis", "opa jarvis", "eai jarvis", "e ai jarvis"}:
            return f"{greeting}, senhor. Em que posso ser útil?"
        if key in {"pode me ajudar", "pode me ajudar por favor", "me ajuda", "me ajuda por favor", "consegue me ajudar"}:
            return "Claro, senhor. Com o que precisa de ajuda?"
        return ""

    def _install_fast_chat_path(self):
        core=getattr(self,"core",None);original=getattr(core,"process_message_stream",None)
        if not callable(original) or bool(getattr(core,"_jarvis_139_fast_path",False)):return
        def fast_stream(message,conversation_history,memories,system_commands_info="",on_chunk=None,_remote_retry=False,speaker_name="",source="text"):
            raw_message=str(message or "")
            retry_key=_fold_text(raw_message)
            if retry_key in {"tenta de novo","tenta novamente","tenta outra vez","repete","repete a pergunta"} and str(getattr(self,"_last_failed_request","") or "").strip():
                raw_message=self._last_failed_request
                self._diag("retry_resolved", message, resolved=raw_message[:600])

            local=self._local_social_reply(raw_message)
            if local and not _remote_retry:
                self._diag("local_social", raw_message, response=local)
                if callable(on_chunk):
                    try:on_chunk(local)
                    except Exception:pass
                return local

            if str(source or "text").lower()=="text" and not bool(getattr(self,"_jarvis_detail_mode",False)) and self._fast_standalone_question(raw_message):
                conversation_history=list(conversation_history or [])[-2:];memories=[];system_commands_info=""

            now=datetime.now().astimezone()
            local_clock=f"horario_local={now:%Y-%m-%d %H:%M:%S}; periodo={'manha' if 5 <= now.hour < 12 else 'tarde' if 12 <= now.hour < 18 else 'noite'}"
            info=str(system_commands_info or "").strip()
            if info.startswith("CTX:"):
                system_commands_info=f"{info} | {local_clock}"
            elif info:
                system_commands_info=f"CTX: {info} | {local_clock}"
            else:
                system_commands_info=f"CTX: {local_clock}"

            return original(raw_message,conversation_history,memories,system_commands_info,on_chunk=on_chunk,_remote_retry=_remote_retry,speaker_name=speaker_name,source=source)
        core.process_message_stream=fast_stream;core._jarvis_139_fast_path=True

    def _on_antonio_tts_chunk(self, chunk: str):
        clean=" ".join(str(chunk or "").split()).strip()
        if not clean:return
        self._diag("tts_chunk", clean)
        try:self._post_ui_call(self._set_voice_overlay_text, clean)
        except Exception:pass

    def _get_antonio_tts(self):
        engine=self._antonio_tts
        if engine is not None:return engine
        engine=AntonioNeuralTTS(project_dir=self.project_dir,logger=getattr(self,"logger",None),on_start=getattr(self,"_on_voice_tts_start",None),on_chunk=self._on_antonio_tts_chunk,on_end=getattr(self,"_on_voice_tts_end",None));self._antonio_tts=engine;return engine

    def _speak(self,text:str):
        clean=str(text or "").strip()
        if not clean:return None
        if hasattr(self,"_chat_tts_enabled") and not bool(getattr(self,"_chat_tts_enabled",True)):return None
        voice_engine=getattr(self,"voice_engine",None)
        if voice_engine is not None and bool(getattr(voice_engine,"_started",False)):return super()._speak(clean)
        try:self._get_antonio_tts().speak(clean,interrupt=True);return True
        except Exception as exc:
            try:self._v136_log("warning",f"Antonio Neural leve indisponivel: {exc}")
            except Exception:pass
            return None

    def _speak_action_ack(self,text:str):
        clean=str(text or "").strip()
        if not clean or not bool(getattr(self,"_chat_tts_enabled",True)):return None
        try:
            voice_engine=getattr(self,"voice_engine",None)
            if voice_engine is not None and bool(getattr(voice_engine,"_started",False)):return voice_engine.speak(clean,wait=False,fast=True)
            return self._get_antonio_tts().speak(clean,interrupt=True)
        except Exception:return None

    def _resolve_browser_context(self, value: str):
        if not value.startswith("v8:browser_search:"):
            return value, "", ""
        payload=value[len("v8:browser_search:"):]
        if "|" not in payload:
            return value, "", ""
        browser,query=payload.split("|",1)
        query=" ".join(query.split()).strip()
        key=_fold_text(query)
        youtube=bool(re.search(r"\byoutube\b",key))
        subject=re.sub(r"\s+(?:no|na|do|da)?\s*youtube\b.*$","",key).strip() if youtube else key
        pronoun=subject in {"isso","isto","aquilo","esse","essa","este","esta"}
        topic=""
        if pronoun:
            try:topic=str((v8_context_status() or {}).get("topic") or "").strip()
            except Exception:topic=""
        resolved=topic if pronoun and topic else query
        if youtube and resolved:
            # Se veio "isso no YouTube", nao mande "isso" para o buscador.
            # Abra diretamente a busca do YouTube com o topico resolvido.
            resolved_subject=topic if pronoun and topic else re.sub(r"\s+(?:no|na|do|da)?\s*youtube\b.*$","",query,flags=re.I).strip()
            if resolved_subject:
                url=f"https://www.youtube.com/results?search_query={quote_plus(resolved_subject)}"
                return f"v8:open_site_in_app:{browser}|{url}", resolved_subject, query
        if pronoun and topic:
            return f"v8:browser_search:{browser}|{topic}", topic, query
        return value, query, query

    def _execute_v8_command_result(self,command:str):
        original_value=str(command or "")
        value=original_value

        # O controlador de janelas e lazy. Um comando real deve carrega-lo sob
        # demanda em vez de responder que o recurso "nao carregou".
        if re.match(r"^(?:minimize|minimiza|minimizar|maximize|maximiza|maximizar|expande|expanda|expandir|restaure|restaura|restaurar)\b",value,re.I):
            try:
                if not getattr(self,"window_manager",None):
                    self._ensure_window_manager()
            except Exception as exc:
                self._diag("window_manager_load_error",str(exc))

        value,resolved_query,raw_query=self._resolve_browser_context(value)
        if value != original_value:
            self._diag("context_resolution",raw_query,resolved=resolved_query,command=value)

        is_search=original_value.startswith("v8:browser_search:")
        if is_search:
            self._pre_action_ack_text="Certo, pesquisando.";self._pre_action_ack_until=time.monotonic()+3.0
            threading.Thread(target=self._speak_action_ack,args=(self._pre_action_ack_text,),name="JARVIS-ACTION-ACK",daemon=True).start()

        started=time.perf_counter()
        outcome=super()._execute_v8_command_result(value)
        elapsed_ms=round((time.perf_counter()-started)*1000.0,1)
        try:
            self._diag("local_command",original_value,executed=value,duration_ms=elapsed_ms,outcome=dict(outcome or {}))
        except Exception:
            pass

        if is_search and bool((outcome or {}).get("success")) and resolved_query:
            try:v8_remember_topic(resolved_query)
            except Exception:pass
        return outcome

    def _deliver_text_speech(self,text):
        ticket=getattr(self,"_text_speech_token",None);self._text_speech_token=None
        if not ticket or not text or bool(getattr(self,"_restoring_history",False)) or not bool(getattr(self,"_chat_tts_enabled",False)):return None
        self._speech_delivery=ticket
        if self._speech_delivery!=ticket or ticket[1]!=self.active_conversation_id or not self._work_is_current(ticket[0]):return None
        spoken=self._voice_spoken_summary(text)
        if not spoken:self._speech_delivery=None;return None
        if time.monotonic()<=float(getattr(self,"_pre_action_ack_until",0.0) or 0.0):
            key=" ".join(str(spoken).lower().split());duplicate_ack=len(key)<=130 and ("pesquis" in key or "buscand" in key) and any(marker in key for marker in ("certo","ok","abrindo","vou ","opera","navegador"))
            if duplicate_ack:self._speech_delivery=None;self._pre_action_ack_until=0.0;self._pre_action_ack_text="";return None
        voice_engine=getattr(self,"voice_engine",None);use_voice_engine=bool(voice_engine is not None and (not hasattr(voice_engine,"_started") or bool(getattr(voice_engine,"_started",False))))
        self._speech_delivery=None
        try:
            if use_voice_engine:return voice_engine.speak(spoken,wait=False,fast=True)
            return self._get_antonio_tts().speak(spoken,interrupt=True)
        except Exception:return None

    def _setup_qt_voice_overlay(self):
        existing=getattr(self,"qt_voice_overlay",None)
        if existing is not None:
            try:
                if existing.is_alive():self._qt_overlay_active=True;return True
            except Exception:pass
        try:
            from jarvis_voice_overlay_139 import QtVoiceOverlayController
            controller=QtVoiceOverlayController(self.project_dir,logger=self.logger)
            if not controller.start():raise RuntimeError("processo Qt nao iniciou")
            self.qt_voice_overlay=controller;self._qt_overlay_active=True
            try:controller.set_orb_style(getattr(self,"voice_orb_style","default"));controller.set_conversation_lock(str(getattr(self,"interaction_mode","") or "").lower()=="conversa")
            except Exception:pass
            try:self._post_ui_event("runtime_ready","overlay")
            except Exception:pass
            return True
        except Exception as exc:
            self.qt_voice_overlay=None;self._qt_overlay_active=False
            try:self.logger.warning(f"Overlay Qt 1.3.9 indisponivel: {exc}","OVERLAY")
            except Exception:pass
            return False

    def _qt_overlay_position(self):
        width=420;orb_cx,orb_cy,visible_radius,margin=width//2,38,42,18;left=top=0
        try:
            if self.window_manager:
                monitor=self.window_manager.get_active_monitor();right=int(monitor["right"]);bottom=int(monitor["bottom"]);left=int(monitor.get("left",0));top=int(monitor.get("top",0))
            else:right=int(self.root.winfo_screenwidth());bottom=int(self.root.winfo_screenheight())
        except Exception:right=int(self.root.winfo_screenwidth());bottom=int(self.root.winfo_screenheight())
        x=right-margin-visible_radius-orb_cx;y=bottom-margin-visible_radius-orb_cy
        return max(left-orb_cx+visible_radius,x),max(top-orb_cy+visible_radius,y)

    def _create_chat_bubble(self,sender,message,is_user=False,is_jarvis=False,is_system=False,timestamp=None,suppress_autoscroll=False):
        row=ctk.CTkFrame(self.chat_scroll,fg_color="transparent");row.pack(fill="x",padx=6,pady=4)
        bubble=ctk.CTkFrame(row,fg_color="#0a1d2c" if is_user else "#061522",corner_radius=11,border_width=1,border_color="#1d5878" if is_user else "#12354a");bubble.pack(fill="x",padx=(34,2) if is_user else (2,22))
        meta=ctk.CTkFrame(bubble,fg_color="transparent");meta.pack(fill="x",padx=12,pady=(6,0))
        ctk.CTkLabel(meta,text=("VOCÊ" if is_user else PUBLIC_NAME if is_jarvis else str(sender)),height=18,text_color=self.UI_ACCENT,font=ctk.CTkFont(size=10,weight="bold")).pack(side="left")
        ctk.CTkLabel(meta,text=self._format_message_time(timestamp),height=18,text_color=self.UI_MUTED,font=ctk.CTkFont(size=9)).pack(side="right")
        text=MessageText(bubble,str(message or ""),fg_color="transparent",border_width=0,text_color="#adbecb" if is_system else self.UI_TEXT,font=ctk.CTkFont(family="Segoe UI",size=14));text.pack(fill="x",expand=True,padx=8,pady=(0,5));self._bind_chat_mousewheel_tree(row);text.bind("<Control-c>",lambda event=None:self._copy_text_selection(text))
        if not suppress_autoscroll and not self._restoring_history:self._schedule_chat_scroll(force=is_user,delay=100)
        return text


__all__=["JarvisGUI"]
