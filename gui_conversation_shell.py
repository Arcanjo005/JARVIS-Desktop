"""Stable release entry point for the responsive cinematic interface.

The shell keeps boot conservative on Windows machines: the GUI becomes usable
first and heavy/background services stay on demand. Normal chat speech uses a
lightweight Antonio Neural-only path, while microphone/wake mode keeps the full
VoiceEngine. Desktop tray/hotkey remain available because they are the recovery
path when visual voice mode hides the main chat.
"""
from __future__ import annotations

import re
import threading
import time

import customtkinter as ctk

from gui_reference_exact_v3 import (
    JarvisGUI as ResponsiveJarvisGUI,
    MessageText,
    PUBLIC_NAME,
)
from jarvis_antonio_tts import AntonioNeuralTTS
from jarvis_voice_lifecycle_136 import VoiceLifecycle136Mixin


class JarvisGUI(VoiceLifecycle136Mixin, ResponsiveJarvisGUI):
    """Responsive UI with conservative safe boot and fast interaction paths."""

    def __init__(self, *args, **kwargs):
        self._antonio_tts = None
        self._pre_action_ack_until = 0.0
        self._pre_action_ack_text = ""
        super().__init__(*args, **kwargs)
        self._install_fast_chat_path()

    # ------------------------------------------------------------------
    # Approved compact interface
    # ------------------------------------------------------------------
    def _create_main_layout(self):
        super()._create_main_layout()

        try:
            self.history_button.configure(text="☰", width=44)
        except Exception:
            pass
        try:
            self.update_button.configure(text="↻", width=44)
        except Exception:
            pass
        try:
            header = self.update_button.master
            for child in header.winfo_children():
                if child is self.history_button or child is self.update_button:
                    continue
                try:
                    if isinstance(child, ctk.CTkLabel) and "J A R V I S" in str(child.cget("text")):
                        child.grid_remove()
                except Exception:
                    pass
            title_slot = getattr(self.current_conversation_label, "master", None)
            if title_slot is not None:
                try:
                    title_slot.grid_remove()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            self._states.grid_remove()
        except Exception:
            pass
        try:
            self._wave.grid_remove()
        except Exception:
            pass
        try:
            self._hero.configure(height=310)
        except Exception:
            pass
        try:
            self._hint.configure(text="+ controles   •   F1 ajuda")
        except Exception:
            pass

        try:
            self.copy_conversation_button = self._button(
                self.side_panel,
                "Copiar conversa",
                self._copy_conversation,
                width=110,
            )
            # Do not use CTkScrollableFrame as a pack(before/after) anchor.
            # CTkScrollableFrame delegates geometry to a private parent frame;
            # using the public wrapper as an anchor leaves stale pack metadata
            # and crashes CustomTkinter when DPI scaling changes.
            self.copy_conversation_button.pack(
                fill="x",
                padx=12,
                pady=(0, 8),
                after=self._new_chat_button,
            )
            self.root.bind(
                "<Control-Shift-C>",
                lambda event=None: self._copy_conversation(),
                add="+",
            )
        except Exception:
            self.copy_conversation_button = None

    # ------------------------------------------------------------------
    # Conservative boot: essential lightweight recovery services only
    # ------------------------------------------------------------------
    def _v136_schedule_prewarm(self):
        """Do not auto-start microphone/STT/wake during boot."""
        try:
            self._v136_log(
                "info",
                "Boot seguro: microfone/STT permanecem sob demanda; TTS Antonio usa caminho leve.",
            )
        except Exception:
            pass

    def _start_deferred_runtime(self):
        """Keep tray/hotkey alive while expensive services remain on demand."""
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

        def start_desktop():
            run_worker("JARVIS-BOOT-DESKTOP-SAFE", desktop_target)

        def start_core():
            run_worker("JARVIS-BOOT-AI-SAFE", core_target)

        def warm_short_tts():
            try:
                self._get_antonio_tts().prefetch("Certo, pesquisando.")
            except Exception:
                pass

        try:
            self.root.after(180, start_desktop)
            self.root.after(650, start_core)
            self.root.after(1800, lambda: run_worker("JARVIS-TTS-PREFETCH", warm_short_tts))
        except Exception:
            start_desktop()
            start_core()

        try:
            logger = getattr(self, "logger", None)
            fn = getattr(logger, "info", None)
            if callable(fn):
                try:
                    fn(
                        "Boot seguro: bandeja/hotkey e IA leves ativos; microfone/STT, updater e modulos pesados sob demanda.",
                        "BOOT",
                    )
                except TypeError:
                    fn("Boot seguro: bandeja e IA leves ativos; servicos pesados sob demanda.")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Short standalone chat fast path
    # ------------------------------------------------------------------
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
            r"\b(?:ele|ela|eles|elas|isso|isto|esse|essa|este|esta|aquele|aquela|"
            r"tambem|também|depois|anterior|mesmo|mesma|continua|continue|explica melhor|"
            r"como assim|e se|e quando|e onde|sobre isso|lembra|lembr[a-z]*)\b",
            key,
        ):
            return False
        if re.match(r"^(?:e|mas|entao|então|ai|aí|certo|beleza|sim|nao|não)\b", key):
            return False
        if re.search(
            r"\b(?:abre|abra|abrir|fecha|feche|fechar|minimiza|maximiza|move|mova|"
            r"pesquisa|pesquise|pesquisar|procura|buscar|busca|clica|clique|pausa|"
            r"continua|toque|toca|volume|arquivo|pasta|monitor|tela)\b",
            key,
        ):
            return False
        return bool(
            text.endswith("?")
            or re.match(
                r"^(?:o que|oq|qual|quais|quem|quanto|quantos|quanta|quantas|como|"
                r"por que|porque|onde|quando|me diga|me explica|explique|define|defina)\b",
                key,
            )
        )

    def _install_fast_chat_path(self):
        core = getattr(self, "core", None)
        original = getattr(core, "process_message_stream", None)
        if not callable(original) or bool(getattr(core, "_jarvis_139_fast_path", False)):
            return

        def fast_stream(
            message,
            conversation_history,
            memories,
            system_commands_info="",
            on_chunk=None,
            speaker_name="",
            source="text",
        ):
            if str(source or "text").lower() == "text" and self._fast_standalone_question(message):
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

    # ------------------------------------------------------------------
    # Antonio Neural-only TTS
    # ------------------------------------------------------------------
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
        """Speak chat replies with Antonio without starting STT/microphone."""
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
        """Acknowledge searches in parallel; never hold the browser action."""
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
        """Preserve turn guards and suppress duplicated post-action acknowledgements."""
        ticket = getattr(self, "_text_speech_token", None)
        self._text_speech_token = None
        if (
            not ticket
            or not text
            or bool(getattr(self, "_restoring_history", False))
            or not bool(getattr(self, "_chat_tts_enabled", False))
        ):
            return None

        self._speech_delivery = ticket
        if (
            self._speech_delivery != ticket
            or ticket[1] != self.active_conversation_id
            or not self._work_is_current(ticket[0])
        ):
            return None

        spoken = self._voice_spoken_summary(text)
        if not spoken:
            self._speech_delivery = None
            return None

        if time.monotonic() <= float(getattr(self, "_pre_action_ack_until", 0.0) or 0.0):
            key = " ".join(str(spoken).lower().split())
            duplicate_ack = (
                len(key) <= 130
                and ("pesquis" in key or "buscand" in key)
                and any(marker in key for marker in ("certo", "ok", "abrindo", "vou ", "opera", "navegador"))
            )
            if duplicate_ack:
                self._speech_delivery = None
                self._pre_action_ack_until = 0.0
                self._pre_action_ack_text = ""
                return None

        voice_engine = getattr(self, "voice_engine", None)
        use_voice_engine = bool(
            voice_engine is not None
            and (
                not hasattr(voice_engine, "_started")
                or bool(getattr(voice_engine, "_started", False))
            )
        )

        self._speech_delivery = None
        try:
            if use_voice_engine:
                return voice_engine.speak(spoken, wait=False, fast=True)
            return self._get_antonio_tts().speak(spoken, interrupt=True)
        except Exception as exc:
            try:
                self._v136_log("warning", f"Typed response TTS: {exc}")
            except Exception:
                pass
            return None

    # ------------------------------------------------------------------
    # Voice overlay 1.3.9: free-moving visible orb, no transparent barrier
    # ------------------------------------------------------------------
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
        """Anchor the visible sphere, not the transparent subtitle canvas."""
        width = 420
        orb_cx = width // 2
        orb_cy = 38
        visible_radius = 42
        margin = 18
        left = top = 0
        try:
            if self.window_manager:
                monitor = self.window_manager.get_active_monitor()
                right = int(monitor["right"])
                bottom = int(monitor["bottom"])
                left = int(monitor.get("left", 0))
                top = int(monitor.get("top", 0))
            else:
                right = int(self.root.winfo_screenwidth())
                bottom = int(self.root.winfo_screenheight())
        except Exception:
            right = int(self.root.winfo_screenwidth())
            bottom = int(self.root.winfo_screenheight())
        x = right - margin - visible_radius - orb_cx
        y = bottom - margin - visible_radius - orb_cy
        return max(left - orb_cx + visible_radius, x), max(top - orb_cy + visible_radius, y)

    # ------------------------------------------------------------------
    # Chat bubbles
    # ------------------------------------------------------------------
    def _create_chat_bubble(self, sender, message, is_user=False, is_jarvis=False,
                            is_system=False, timestamp=None, suppress_autoscroll=False):
        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=5)
        bubble = ctk.CTkFrame(
            row,
            fg_color="#10283b" if is_user else "#081a29",
            corner_radius=12,
            border_width=1,
            border_color="#244d65" if is_user else "#12334b",
        )
        bubble.pack(fill="x", padx=(32, 2) if is_user else (2, 20))
        meta = ctk.CTkFrame(bubble, fg_color="transparent")
        meta.pack(fill="x", padx=12, pady=(7, 0))
        ctk.CTkLabel(
            meta,
            text=("VOCÊ" if is_user else PUBLIC_NAME if is_jarvis else str(sender)),
            height=20,
            text_color=self.UI_ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            meta,
            text=self._format_message_time(timestamp),
            height=20,
            text_color=self.UI_MUTED,
            font=ctk.CTkFont(size=10),
        ).pack(side="right")
        text = MessageText(
            bubble,
            str(message or ""),
            fg_color="transparent",
            border_width=0,
            text_color="#adbecb" if is_system else self.UI_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=15),
        )
        text.pack(fill="x", expand=True, padx=8, pady=(0, 6))
        self._bind_chat_mousewheel_tree(row)
        text.bind("<Control-c>", lambda event=None: self._copy_text_selection(text))
        if not suppress_autoscroll and not self._restoring_history:
            self._schedule_chat_scroll(force=is_user, delay=100)
        return text


__all__ = ["JarvisGUI"]
