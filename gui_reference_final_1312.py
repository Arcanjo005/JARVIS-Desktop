"""JARVIS 1.3.12 reference-first production shell.

The approved 2560x1440 office scene is a real bundled asset.  Tk/CTk still owns
all controls, history, chat, captions and the live orb; nothing is implemented
as a screenshot-shaped click map.  The cinematic home collapses the transcript
only while a conversation is empty, and restores it on the first real turn or
when a saved conversation is opened.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import threading
import time
import unicodedata
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse

import customtkinter as ctk
from PIL import Image, ImageEnhance, ImageOps, ImageTk

from gui_conversation_shell import JarvisGUI as ConversationJarvisGUI
from jarvis_reference_asset import REFERENCE_RELATIVE_PATH, ensure_reference_scene
from jarvis_router import context_status as v8_context_status


_REFERENCE_WORDS = {
    "isso", "isto", "aquilo", "esse", "essa", "este", "esta", "ele", "ela",
    "sobre isso", "por isso",
}


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_youtube_suffix(value: str) -> str:
    clean = " ".join(str(value or "").split()).strip()
    return re.sub(
        r"\s+(?:(?:no|na|do|da|pelo|pela|para o|para a|pro|pra)\s+)?youtube\s*$",
        "",
        clean,
        flags=re.I,
    ).strip()


class JarvisGUI(ConversationJarvisGUI):
    """Functional chat plus the approved cinematic composition."""

    UI_BG = "#01070d"
    UI_SURFACE = "#04101a"
    UI_SURFACE_2 = "#071522"
    UI_SURFACE_3 = "#0b2942"
    UI_BORDER = "#15344a"
    UI_BORDER_STRONG = "#24587a"
    UI_ACCENT = "#28b9ff"
    UI_ACCENT_HOVER = "#74dcff"
    UI_TEXT = "#edf8ff"
    UI_MUTED = "#829cad"

    def __init__(self, *args, **kwargs):
        self._reference_scene_source = None
        self._reference_scene_path = None
        self._reference_scene_failed = False
        self._reference_chat_visible = True
        self._reference_last_search_topic = ""
        self._reference_update_badge = None
        self._reference_settings_button = None
        super().__init__(*args, **kwargs)
        try:
            self.root.after(180, self._sync_reference_chat_mode)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # VISUAL COMPOSITION
    # ------------------------------------------------------------------
    def _create_main_layout(self):
        super()._create_main_layout()

        try:
            self.side_panel.configure(
                width=286,
                fg_color="#020910",
                border_width=1,
                border_color="#10283a",
                corner_radius=0,
            )
        except Exception:
            pass

        try:
            self._new_chat_button.configure(
                height=46,
                corner_radius=10,
                fg_color="#071522",
                hover_color="#0b2942",
                border_width=1,
                border_color="#244a65",
                text="＋      Nova conversa",
            )
            if getattr(self, "reference_search_entry", None) is not None:
                self.reference_search_entry.configure(
                    height=41,
                    corner_radius=10,
                    fg_color="#06131e",
                    border_color="#203f56",
                    placeholder_text="⌕  Buscar conversas...",
                )
        except Exception:
            pass

        # Keep the transcript widget alive.  It may be collapsed only by
        # _set_reference_chat_visible and is always restored for real chat.
        try:
            self._reference_chat_panel = self.chat_scroll.master
            self._reference_chat_panel.configure(
                fg_color="#030c14",
                border_width=1,
                border_color="#132c3e",
                corner_radius=13,
            )
            self.chat_scroll.configure(
                fg_color="#030c14",
                corner_radius=11,
                scrollbar_button_color="#173a50",
            )
        except Exception:
            self._reference_chat_panel = None

        try:
            self._hero.configure(bg="#01070d", highlightthickness=0)
            self._caption.configure(
                fg_color="transparent",
                text_color="#ffe35b",
                corner_radius=0,
                height=42,
                font=ctk.CTkFont(family="Segoe UI", size=19, weight="normal"),
            )
        except Exception:
            pass

        try:
            self.input_shell.configure(
                fg_color="#071522",
                corner_radius=18,
                border_width=1,
                border_color="#31536d",
            )
            self._composer_placeholder_text = "Digite sua mensagem..."
            if getattr(self, "_composer_placeholder_active", False):
                self._composer_set_placeholder()
            self.quick_menu_button.configure(
                text="＋", width=50, height=50, corner_radius=25,
                fg_color="#102238", hover_color="#173a5c",
                border_color="#173b56", font=ctk.CTkFont(size=27),
            )
            self.voice_button.configure(
                text="●", width=50, height=50, corner_radius=25,
                fg_color="#062c52", hover_color="#0c4b80",
                border_color="#168fe5", font=ctk.CTkFont(size=17),
            )
            self.send_button.configure(
                text="➤", width=50, height=50, corner_radius=25,
                fg_color="#0a1e34", hover_color="#123d63",
                border_color="#52708a", font=ctk.CTkFont(size=20),
            )
            self._reference_settings_button = self._button(
                self.input_shell,
                "☷",
                lambda: self._show_quick_actions_menu(self._reference_settings_button),
                50,
            )
            self._reference_settings_button.configure(
                width=50, height=50, corner_radius=25,
                fg_color="#102238", hover_color="#173a5c",
                border_color="#173b56", font=ctk.CTkFont(size=21),
            )
            self._reference_settings_button.grid(row=0, column=4, padx=(3, 8), pady=7)
        except Exception:
            self._reference_settings_button = None

        try:
            if self.reference_switch_bar is not None:
                self.reference_switch_bar.configure(
                    fg_color="#06131f",
                    corner_radius=15,
                    border_width=1,
                    border_color="#294a62",
                )
        except Exception:
            pass

        try:
            self._reference_update_badge = ctk.CTkLabel(
                self.root,
                text="1",
                width=18,
                height=18,
                corner_radius=9,
                fg_color="#ff3048",
                text_color="#ffffff",
                font=ctk.CTkFont(size=10, weight="bold"),
            )
            self._reference_update_badge.place_forget()
        except Exception:
            self._reference_update_badge = None

        self._load_reference_scene()
        try:
            self.root.after_idle(self._relayout)
        except Exception:
            pass

    def _reference_asset_candidates(self):
        roots = []
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            roots.append(Path(bundle))
        try:
            roots.append(Path(self.project_dir))
        except Exception:
            pass
        roots.append(Path(__file__).resolve().parent)
        seen = set()
        for root in roots:
            path = (root / REFERENCE_RELATIVE_PATH).resolve()
            if path not in seen:
                seen.add(path)
                yield root, path

    def _load_reference_scene(self):
        if self._reference_scene_source is not None or self._reference_scene_failed:
            return
        for root, path in self._reference_asset_candidates():
            try:
                if not path.is_file() and not getattr(sys, "frozen", False):
                    path = ensure_reference_scene(root)
                if not path.is_file():
                    continue
                image = Image.open(path).convert("RGB")
                if image.size != (2560, 1440):
                    continue
                self._reference_scene_source = ImageEnhance.Contrast(image).enhance(1.015)
                self._reference_scene_path = str(path)
                try:
                    self._diag("reference_scene", "asset carregado", path=str(path), size=list(image.size))
                except Exception:
                    pass
                return
            except Exception as exc:
                try:
                    self._diag("reference_scene_error", str(exc), path=str(path))
                except Exception:
                    pass
        self._reference_scene_failed = True

    def _resize_scene(self):
        w, h = self._hero.winfo_width(), self._hero.winfo_height()
        if w < 2 or h < 2 or (w, h) == self._scene_size:
            return
        self._scene_size = (w, h)
        self._load_reference_scene()
        source = self._reference_scene_source
        if source is None:
            # Keep a neutral dark surface rather than silently returning to the
            # old procedural visual which caused the repeated-style regression.
            image = Image.new("RGB", (w, h), "#01070d")
        else:
            image = ImageOps.fit(
                source,
                (w, h),
                method=Image.Resampling.LANCZOS,
                centering=(0.50, 0.50),
            )
        self._hero_photo = ImageTk.PhotoImage(image, master=self.root)
        self._hero.itemconfigure(self._scene_item, image=self._hero_photo)
        self._place_reference_orb(w, h)

    def _place_reference_orb(self, width=None, height=None):
        w = int(width or self._hero.winfo_width())
        h = int(height or self._hero.winfo_height())
        x = w * 0.50
        y = h * (0.445 if not self._reference_chat_visible else 0.48)
        try:
            self._hero.coords(self._orb_item, x, y)
            self._hero.coords(self._render_error_item, x, y)
        except Exception:
            pass

    def _on_hero_size(self, event):
        self._place_reference_orb(event.width, event.height)
        self._later("scene", 140, self._resize_scene)

    def _visual_tick(self):
        # Existing worker remains isolated from Tk.  Reposition only after the
        # inherited renderer has consumed its newest frame.
        result = super()._visual_tick()
        self._place_reference_orb()
        self._position_reference_update()
        return result

    def _set_reference_chat_visible(self, visible: bool):
        panel = getattr(self, "_reference_chat_panel", None)
        self._reference_chat_visible = bool(visible)
        if panel is None:
            return
        try:
            if visible:
                panel.grid(row=3, column=0, sticky="nsew", pady=(5, 5))
                panel.lift()
            else:
                panel.grid_remove()
        except Exception:
            return
        self._later("reference-layout", 10, self._relayout)

    def _sync_reference_chat_mode(self):
        has_real_turn = False
        try:
            for row in list(getattr(self, "chat_history", []) or []):
                if bool(row.get("is_user")):
                    has_real_turn = True
                    break
        except Exception:
            pass
        self._set_reference_chat_visible(has_real_turn)

    def _request_chat_visible(self):
        try:
            if threading.get_ident() == getattr(self, "_main_thread_id", None):
                self._set_reference_chat_visible(True)
            else:
                self._post_context_ui_call(lambda: self._set_reference_chat_visible(True))
        except Exception:
            try:
                self.root.after(0, lambda: self._set_reference_chat_visible(True))
            except Exception:
                pass

    def send_message(self, event=None):
        self._set_reference_chat_visible(True)
        return super().send_message(event)

    def add_message(self, sender, message, is_user=False, is_jarvis=False, is_system=False, speak=False):
        if is_user:
            self._request_chat_visible()
        return super().add_message(sender, message, is_user, is_jarvis, is_system, speak)

    def _switch_conversation(self, conversation_id: int):
        result = super()._switch_conversation(conversation_id)
        try:
            self.root.after_idle(lambda: self._set_reference_chat_visible(True))
        except Exception:
            pass
        return result

    def _new_conversation(self):
        result = super()._new_conversation()
        try:
            self.root.after(40, lambda: self._set_reference_chat_visible(False))
        except Exception:
            pass
        return result

    def _relayout(self):
        try:
            scale = max(0.55, float(self._center._get_widget_scaling() or 1.0))
        except Exception:
            scale = 1.0
        logical_w = max(320.0, self.root.winfo_width() / scale)
        logical_h = max(320.0, self.root.winfo_height() / scale)
        wide = logical_w >= 980
        if wide != self._wide_layout:
            self._wide_layout = wide
            self._drawer_open = False
            self._place_history()
        self._layout_reference_switches(logical_w)

        for widget in (getattr(self, "_states", None), getattr(self, "_wave", None), getattr(self, "_hint", None)):
            if widget is not None:
                try:
                    widget.grid_remove()
                except Exception:
                    pass

        if logical_h < 520:
            try:
                self._hero.grid_remove()
            except Exception:
                pass
            self._center.grid_rowconfigure(0, weight=0, minsize=0)
        else:
            try:
                self._hero.grid()
            except Exception:
                pass
            if self._reference_chat_visible:
                hero_logical = max(205.0, min(430.0, (logical_h - 300.0) * 0.48))
                self._center.grid_rowconfigure(3, weight=1, minsize=round(120 * scale))
            else:
                hero_logical = max(340.0, min(760.0, logical_h - 175.0))
                self._center.grid_rowconfigure(3, weight=0, minsize=0)
            hero_px = max(1, round(hero_logical * scale))
            self._hero.configure(height=hero_px)
            self._center.grid_rowconfigure(0, weight=0, minsize=hero_px)

        width = max(180, self._center.winfo_width() / scale - 44)
        try:
            self._caption.configure(wraplength=width)
            self._refresh_caption()
            self.agent_hud_step.configure(wraplength=max(140, width - 30))
        except Exception:
            pass
        self._resize_composer()
        self._position_reference_update()
        self._place_reference_orb()

    def _position_reference_update(self):
        try:
            super()._position_reference_update()
        except Exception:
            pass
        badge = getattr(self, "_reference_update_badge", None)
        if badge is None:
            return
        try:
            if getattr(self, "_pending_update_info", None) is None:
                badge.place_forget()
                return
            bx = self.update_button.winfo_x() + max(27, self.update_button.winfo_width() - 5)
            by = self.update_button.winfo_y() - 4
            badge.place(x=bx, y=by)
            badge.lift()
        except Exception:
            pass

    def _show_update_available(self, info):
        result = super()._show_update_available(info)
        self._position_reference_update()
        return result

    # ------------------------------------------------------------------
    # CAPTIONS
    # ------------------------------------------------------------------
    def _set_voice_overlay_text(self, text):
        result = super()._set_voice_overlay_text(text)
        clean = " ".join(str(text or "").split()).strip()
        if clean.lower().startswith("jarvis:"):
            clean = clean.split(":", 1)[1].strip()
        self._caption_text = clean
        try:
            self._refresh_caption()
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # SEARCH CONTEXT: never send a literal pronoun to the browser
    # ------------------------------------------------------------------
    def _topic_from_history(self) -> str:
        try:
            history = list(getattr(self, "chat_history", []) or [])[-28:]
        except Exception:
            history = []
        for row in reversed(history):
            if not bool(row.get("is_user")):
                continue
            text = " ".join(str(row.get("message") or row.get("content") or "").split()).strip()
            match = re.search(
                r"\b(?:pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar)\s+(.+)$",
                text,
                flags=re.I,
            )
            if not match:
                continue
            subject = _strip_youtube_suffix(match.group(1).strip(" ,.!?"))
            folded = _fold(subject)
            if subject and folded not in _REFERENCE_WORDS and not re.search(r"\b(?:isso|isto|aquilo)\b", folded):
                return subject
        return ""

    def _current_reference_topic(self) -> str:
        if self._reference_last_search_topic:
            return self._reference_last_search_topic
        try:
            status = v8_context_status() or {}
            topic = str(status.get("topic") or "").strip()
            if not topic:
                topic = str(((status.get("entities") or {}).get("topic") or {}).get("value") or "").strip()
            if topic and _fold(topic) not in _REFERENCE_WORDS:
                self._reference_last_search_topic = topic
                return topic
        except Exception:
            pass
        topic = self._topic_from_history()
        if topic:
            self._reference_last_search_topic = topic
        return topic

    def _resolve_browser_context(self, value: str):
        if not str(value).startswith("v8:browser_search:"):
            return value, "", ""
        payload = str(value)[len("v8:browser_search:"):]
        if "|" not in payload:
            return value, "", ""
        browser, query = payload.split("|", 1)
        query = " ".join(query.split()).strip()
        subject = _strip_youtube_suffix(query)
        subject_key = _fold(subject)
        youtube = bool(re.search(r"\byoutube\b", _fold(query)))
        pronoun = subject_key in _REFERENCE_WORDS

        if not pronoun:
            if subject:
                self._reference_last_search_topic = subject
            return value, subject or query, query

        topic = self._current_reference_topic()
        if not topic:
            # The inherited executor treats an unknown v8 command as a normal
            # local failure, so intercept it below and ask for the subject.
            return "v8:clarify_search_topic", "", query
        if youtube:
            url = "https://www.youtube.com/results?search_query=" + quote_plus(topic)
            return f"v8:open_site_in_app:{browser}|{url}", topic, query
        return f"v8:browser_search:{browser}|{topic}", topic, query

    def _repair_reference_url(self, command: str) -> str:
        if not str(command).startswith("v8:open_site_in_app:") or "|" not in str(command):
            return command
        head, url = str(command).split("|", 1)
        try:
            parsed = urlparse(url)
            if "youtube.com" not in parsed.netloc.lower():
                return command
            params = parse_qs(parsed.query)
            values = params.get("search_query") or []
            if not values or _fold(values[0]) not in _REFERENCE_WORDS:
                return command
            topic = self._current_reference_topic()
            if not topic:
                return "v8:clarify_search_topic"
            params["search_query"] = [topic]
            flat = [(key, item) for key, items in params.items() for item in items]
            fixed = urlunparse(parsed._replace(query=urlencode(flat)))
            return head + "|" + fixed
        except Exception:
            return command

    def _execute_v8_command_result(self, command: str):
        raw = str(command or "")
        repaired = self._repair_reference_url(raw)
        if repaired == "v8:clarify_search_topic" or raw == "v8:clarify_search_topic":
            self.add_message(
                "JARVIS",
                "Sobre qual assunto o senhor quer que eu pesquise?",
                is_jarvis=True,
            )
            return {"success": False, "message": "assunto da pesquisa ausente", "clarification": True}
        outcome = super()._execute_v8_command_result(repaired)
        if bool((outcome or {}).get("success")):
            try:
                if repaired.startswith("v8:browser_search:") and "|" in repaired:
                    topic = repaired.split("|", 1)[1].strip()
                    if topic and _fold(topic) not in _REFERENCE_WORDS:
                        self._reference_last_search_topic = topic
                elif "youtube.com" in repaired and "search_query=" in repaired:
                    query = parse_qs(urlparse(repaired.split("|", 1)[1]).query).get("search_query", [""])[0]
                    if query and _fold(query) not in _REFERENCE_WORDS:
                        self._reference_last_search_topic = query
            except Exception:
                pass
        return outcome


__all__ = ["JarvisGUI"]
