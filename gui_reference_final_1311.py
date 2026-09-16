"""Final reference composition for JARVIS Desktop.

This shell does not paint a screenshot over the application.  The photographic
room is a static scene plate; the orb, caption, history, update control,
composer, switches and commands remain live widgets/runtime layers.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
import sys
import time
import unicodedata
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse

import customtkinter as ctk
from PIL import Image, ImageEnhance, ImageFilter, ImageTk

from gui_conversation_shell import JarvisGUI as ConversationJarvisGUI
from jarvis_reference_scene_139 import render_reference_scene
from jarvis_router import context_status as v8_context_status, remember_topic as v8_remember_topic
from jarvis_ui_render import RenderRequest


REFERENCE_ASSET = Path("assets") / "jarvis_reference_scene_1440p.jpg"
_REFERENCE_WORDS = {"isso", "isto", "aquilo", "esse", "essa", "este", "esta", "ele", "ela"}


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_youtube_suffix(value: str) -> str:
    clean = " ".join(str(value or "").split()).strip()
    return re.sub(r"\s+(?:no|na|do|da|pelo|para o|pro)\s+youtube\s*$", "", clean, flags=re.I).strip()


class JarvisGUI(ConversationJarvisGUI):
    """Reference-first UI while preserving the production controller."""

    def __init__(self, *args, **kwargs):
        self._reference_scene_source = None
        self._reference_scene_failed = False
        self._reference_last_search_topic = ""
        self._reference_update_badge = None
        self._reference_settings_button = None
        super().__init__(*args, **kwargs)

    # ------------------------------------------------------------------
    # REFERENCE UI
    # ------------------------------------------------------------------
    def _create_main_layout(self):
        super()._create_main_layout()

        # The approved reference has no persistent transcript below the hero.
        # Messages remain stored and selectable from history; only the visual
        # transcript surface is removed from the cinematic home composition.
        try:
            self.chat_scroll.master.grid_remove()
        except Exception:
            pass
        try:
            self.agent_hud.master.grid_remove()
        except Exception:
            pass

        try:
            self.side_panel.configure(
                width=284,
                fg_color="#020a12",
                border_width=1,
                border_color="#102a3d",
                corner_radius=0,
            )
        except Exception:
            pass

        # Refine the existing brand/history control without replacing its
        # callback identity.  Keeping the same widget also keeps drawer tests and
        # keyboard behavior stable.
        try:
            self._sidebar_history_button.configure(
                text="△",
                width=54,
                height=54,
                corner_radius=27,
                fg_color="#031525",
                hover_color="#082b46",
                border_width=2,
                border_color="#24aaf2",
                text_color="#7bddff",
                font=ctk.CTkFont(family="Segoe UI Symbol", size=27, weight="bold"),
            )
            brand = self._sidebar_history_button.master
            brand.configure(height=82)
            for child in brand.winfo_children():
                if child is not self._sidebar_history_button and isinstance(child, ctk.CTkLabel):
                    child.configure(
                        text="JARVIS",
                        font=ctk.CTkFont(family="Segoe UI", size=30, weight="bold"),
                        text_color="#f2f8fd",
                    )
        except Exception:
            pass

        try:
            self._new_chat_button.configure(
                height=44,
                corner_radius=9,
                border_width=1,
                border_color="#21445e",
                fg_color="#071522",
                hover_color="#0b2942",
                text="＋        Nova conversa",
                font=ctk.CTkFont(size=13),
            )
            if self.reference_search_entry is not None:
                self.reference_search_entry.configure(
                    height=40,
                    corner_radius=9,
                    fg_color="#06131f",
                    border_color="#21445e",
                    placeholder_text="⌕  Buscar conversas...",
                    font=ctk.CTkFont(size=12),
                )
            if self.copy_conversation_button is not None:
                self.copy_conversation_button.configure(
                    height=28,
                    corner_radius=8,
                    fg_color="#030d16",
                    hover_color="#092238",
                    border_color="#15334a",
                    text_color="#7895a8",
                    font=ctk.CTkFont(size=10),
                )
        except Exception:
            pass

        # Hero owns the entire center.  Real controls are placed over it, just as
        # in the approved composition.
        try:
            for row in range(8):
                self._center.grid_rowconfigure(row, weight=0, minsize=0)
            self._center.grid_rowconfigure(0, weight=1, minsize=1)
            self._hero.grid_remove()
            self._hero.grid(row=0, column=0, sticky="nsew")
            self._hero.configure(bg="#01070d", highlightthickness=0)
        except Exception:
            pass

        for widget in (
            getattr(self, "_caption", None),
            getattr(self, "input_shell", None),
            getattr(self, "reference_switch_bar", None),
            getattr(self, "_states", None),
            getattr(self, "_wave", None),
            getattr(self, "_hint", None),
        ):
            if widget is not None:
                try:
                    widget.grid_remove()
                except Exception:
                    pass

        try:
            self._caption.configure(
                fg_color="transparent",
                text_color="#ffd72c",
                corner_radius=0,
                height=48,
                font=ctk.CTkFont(family="Segoe UI", size=25, weight="normal"),
            )
        except Exception:
            pass

        # Input row: glass-like panel, large rounded actions and the missing
        # settings/sliders control from the reference.
        try:
            self.input_shell.configure(
                fg_color="#071522",
                corner_radius=15,
                border_width=1,
                border_color="#31536d",
                height=76,
            )
            self._composer_placeholder_text = "Digite sua mensagem..."
            if getattr(self, "_composer_placeholder_active", False):
                self._composer_set_placeholder()
            self.quick_menu_button.configure(
                text="＋", width=50, height=50, corner_radius=25,
                fg_color="#102238", hover_color="#173a5c",
                border_color="#173b56", font=ctk.CTkFont(size=28),
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
                self.input_shell, "☷",
                lambda: self._show_quick_actions_menu(self._reference_settings_button),
                50,
            )
            self._reference_settings_button.configure(
                width=50, height=50, corner_radius=25,
                fg_color="#102238", hover_color="#173a5c",
                border_color="#173b56", font=ctk.CTkFont(size=22),
            )
            self._reference_settings_button.grid(row=0, column=4, padx=(3, 8), pady=10)
        except Exception:
            self._reference_settings_button = None

        try:
            self.reference_switch_bar.configure(
                fg_color="#071522",
                corner_radius=15,
                border_width=1,
                border_color="#31536d",
                height=58,
            )
        except Exception:
            pass

        # Small update badge.  It is shown only when the updater confirms a
        # newer version; the circular update button remains the actual control.
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
        self._later("reference-layout", 1, self._relayout)

    def _reference_asset_candidates(self):
        roots = []
        try:
            roots.append(Path(self.project_dir))
        except Exception:
            pass
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            roots.append(Path(bundle))
        roots.append(Path(__file__).resolve().parent)
        seen = set()
        for root in roots:
            path = (root / REFERENCE_ASSET).resolve()
            if path not in seen:
                seen.add(path)
                yield path

    def _load_reference_scene(self):
        if self._reference_scene_source is not None or self._reference_scene_failed:
            return
        for path in self._reference_asset_candidates():
            try:
                if not path.is_file():
                    continue
                image = Image.open(path).convert("RGB")
                # Very small enhancement only compensates for resize/monitor gamma;
                # it does not redraw or invent the approved room.
                image = ImageEnhance.Contrast(image).enhance(1.02)
                self._reference_scene_source = image
                return
            except Exception:
                continue
        self._reference_scene_failed = True

    def _resize_scene(self):
        w, h = self._hero.winfo_width(), self._hero.winfo_height()
        if w < 2 or h < 2 or (w, h) == self._scene_size:
            return
        self._scene_size = w, h
        self._load_reference_scene()
        try:
            source = self._reference_scene_source
            if source is None:
                image = render_reference_scene(w, h)
            else:
                # The scene plate is deliberately stretched to the exact hero
                # viewport because it was extracted from this composition.  A
                # crop would remove the right wall or city at tall aspect ratios.
                image = source.resize((w, h), Image.Resampling.LANCZOS)
            self._hero_photo = ImageTk.PhotoImage(image, master=self.root)
            self._hero.itemconfigure(self._scene_item, image=self._hero_photo)
            self._place_reference_orb(w, h)
        except Exception as exc:
            try:
                self.logger.warning(f"Reference scene unavailable: {exc}", "UI-REFERENCE")
            except Exception:
                pass
            image = render_reference_scene(w, h)
            self._hero_photo = ImageTk.PhotoImage(image, master=self.root)
            self._hero.itemconfigure(self._scene_item, image=self._hero_photo)

    def _place_reference_orb(self, w=None, h=None):
        w = int(w or self._hero.winfo_width())
        h = int(h or self._hero.winfo_height())
        self._hero.coords(self._orb_item, w * 0.50, h * 0.435)
        self._hero.coords(self._render_error_item, w * 0.50, h * 0.435)

    def _on_hero_size(self, event):
        self._place_reference_orb(event.width, event.height)
        self._later("scene", 120, self._resize_scene)
        self._later("reference-layout", 15, self._layout_reference_overlays)

    def _relayout(self):
        scale = max(0.5, float(self._center._get_widget_scaling() or 1.0))
        logical_w = self.root.winfo_width() / scale
        wide = logical_w >= 980
        if wide != self._wide_layout:
            self._wide_layout = wide
            self._drawer_open = False
            self._place_history()
        self._layout_reference_switches(logical_w)
        self._position_reference_update()
        self._layout_reference_overlays()
        self._resize_composer()

    def _layout_reference_overlays(self):
        try:
            w = max(1, self._center.winfo_width())
            h = max(1, self._center.winfo_height())
            scale = max(0.65, float(self._center._get_widget_scaling() or 1.0))

            if w < 720:
                composer_w = max(250, w - round(20 * scale))
            else:
                composer_w = max(540, min(round(w * 0.79), w - round(42 * scale)))

            compact = h < round(560 * scale)
            input_h = round((62 if compact else 72) * scale)
            switch_h = round((68 if w / scale < 850 else 54) * scale)
            bottom = round((16 if compact else 58) * scale)
            x = max(0, (w - composer_w) // 2)
            y = max(4, h - bottom - input_h - switch_h)

            self.input_shell.place(x=x, y=y, width=composer_w, height=input_h)
            self.reference_switch_bar.place(
                x=x, y=max(0, y + input_h - 1), width=composer_w, height=switch_h
            )

            if compact:
                self._caption.place_forget()
            else:
                caption_h = round(48 * scale)
                caption_y = max(4, y - round(66 * scale))
                self._caption.place(
                    x=x,
                    y=caption_y,
                    width=composer_w,
                    height=caption_h,
                )
                self._caption.configure(wraplength=max(180, composer_w - round(30 * scale)))

            self.input_shell.lift()
            self.reference_switch_bar.lift()
            if not compact:
                self._caption.lift()
            if self._reference_settings_button is not None:
                self._reference_settings_button.lift()
            self._position_reference_update()
        except Exception:
            pass

    def _visual_tick(self):
        visible = bool(self.root.winfo_viewable())
        orb_visible = visible and bool(self._hero.winfo_viewable())
        w = max(1, self._hero.winfo_width())
        h = max(1, self._hero.winfo_height())
        # Orb is deliberately dominant like the approved reference.  The worker
        # clamps at 640, which is also safe on the user's 4-core CPU.
        size = min(640, max(160, int(min(w * 0.62, h * 0.66))))
        state = self._hero_state
        level = max(0, min(1, float(getattr(self, "voice_mic_level", 0) or 0)))
        self._place_reference_orb(w, h)
        self._orb_worker.request(RenderRequest(size, state, level, orb_visible))
        frame = self._orb_worker.take()
        if visible and frame is not None and frame[0] == size:
            self._orb_photo = ImageTk.PhotoImage(frame[1], master=self.root)
            self._hero.itemconfigure(self._orb_item, image=self._orb_photo)
        if self._orb_worker.error and not getattr(self, "_render_error_reported", False):
            self._render_error_reported = True
            try:
                self.logger.warning(self._orb_worker.error, "UI-RENDER")
            except Exception:
                pass

        now = time.monotonic()
        self._update_pulsing = bool(
            getattr(self, "_pending_update_info", None) is not None
            and not getattr(self, "_update_download_active", False)
            and self.update_button.cget("state") != "disabled"
        )
        if self._update_pulsing:
            phase = 0.5 + 0.5 * math.sin(now * 3.0)
            color = "#%02x%02x%02x" % (
                6 + int(7 * phase), 24 + int(34 * phase), 40 + int(48 * phase)
            )
            if color != self._update_color:
                self.update_button.configure(fg_color=color)
                self._update_color = color
        self._later("tick", 45 if visible else 200, self._visual_tick)

    def _position_reference_update(self):
        super()._position_reference_update()
        badge = getattr(self, "_reference_update_badge", None)
        if badge is None:
            return
        try:
            if getattr(self, "_pending_update_info", None) is None:
                badge.place_forget()
                return
            bx = self.update_button.winfo_x() + max(28, self.update_button.winfo_width() - 5)
            by = self.update_button.winfo_y() - 4
            badge.place(x=bx, y=by)
            badge.lift()
        except Exception:
            pass

    def _show_update_available(self, info):
        result = super()._show_update_available(info)
        self._position_reference_update()
        return result

    def _finish_manual_update_check(self, info, error=""):
        result = super()._finish_manual_update_check(info, error)
        self._position_reference_update()
        return result

    # ------------------------------------------------------------------
    # CAPTIONS
    # ------------------------------------------------------------------
    def _set_voice_overlay_text(self, text):
        # Keep the real voice overlay in sync, but the cinematic caption itself
        # mirrors only the currently spoken phrase (no static "JARVIS:" prefix).
        result = super(ConversationJarvisGUI, self)._set_voice_overlay_text(text)
        clean = " ".join(str(text or "").split()).strip()
        if clean.lower().startswith("jarvis:"):
            clean = clean.split(":", 1)[1].strip()
        self._caption_text = clean
        self._refresh_caption()
        return result

    def _refresh_caption(self):
        if not bool(getattr(self, "_captions_enabled", True)):
            try:
                self._caption.configure(text="")
            except Exception:
                pass
            return
        text = " ".join(str(getattr(self, "_caption_text", "") or "").split()).strip()
        # TTS now sends a rolling phrase already sized for the screen; do not
        # truncate it to the beginning of the response again.
        if len(text) > 150:
            text = text[-150:].lstrip(" ,.;:-")
        try:
            self._caption.configure(text=text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # REFERENCE RESOLUTION FOR SEARCH / "ISSO"
    # ------------------------------------------------------------------
    def _remember_reference_search(self, query: str):
        subject = _strip_youtube_suffix(query)
        key = _fold(subject)
        if not subject or key in _REFERENCE_WORDS:
            return
        self._reference_last_search_topic = subject
        try:
            v8_remember_topic(subject)
        except Exception:
            pass

    def _topic_from_history(self) -> str:
        for item in reversed(list(getattr(self, "chat_history", []) or [])[-20:]):
            if not item.get("is_user"):
                continue
            text = " ".join(str(item.get("message") or item.get("content") or "").split()).strip()
            match = re.search(
                r"\b(?:pesquisa|pesquise|pesquisar|procura|procure|buscar|busca)\s+(.+)$",
                text,
                flags=re.I,
            )
            if not match:
                continue
            subject = _strip_youtube_suffix(match.group(1).strip(" ,.!?"))
            if subject and _fold(subject) not in _REFERENCE_WORDS and "isso" not in _fold(subject).split():
                return subject
        return ""

    def _current_reference_topic(self) -> str:
        if self._reference_last_search_topic:
            return self._reference_last_search_topic
        try:
            status = v8_context_status() or {}
            topic = str(status.get("topic") or status.get("current_topic") or "").strip()
            if topic:
                self._reference_last_search_topic = topic
                return topic
        except Exception:
            pass
        topic = self._topic_from_history()
        if topic:
            self._reference_last_search_topic = topic
        return topic

    def _resolve_browser_context(self, value: str):
        if not value.startswith("v8:browser_search:"):
            return value, "", ""
        payload = value[len("v8:browser_search:"):]
        if "|" not in payload:
            return value, "", ""
        browser, query = payload.split("|", 1)
        query = " ".join(query.split()).strip()
        subject = _strip_youtube_suffix(query)
        key = _fold(subject)
        youtube = "youtube" in _fold(query).split()
        is_reference = key in _REFERENCE_WORDS or key in {"sobre isso", "por isso"}

        if not is_reference:
            self._remember_reference_search(subject or query)
            return value, subject or query, query

        topic = self._current_reference_topic()
        if not topic:
            # Do not literally search "isso".  Let the conversational route ask
            # for clarification if the context has genuinely expired.
            return "v8:clarify_search_topic", "", query

        if youtube:
            url = "https://www.youtube.com/results?search_query=" + quote_plus(topic)
            return f"v8:open_site_in_app:{browser}|{url}", topic, query
        return f"v8:browser_search:{browser}|{topic}", topic, query

    def _repair_reference_url(self, command: str) -> str:
        if not command.startswith("v8:open_site_in_app:") or "|" not in command:
            return command
        head, url = command.split("|", 1)
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
                return command
            params["search_query"] = [topic]
            flat = []
            for key, items in params.items():
                for item in items:
                    flat.append((key, item))
            fixed = urlunparse(parsed._replace(query=urlencode(flat)))
            return head + "|" + fixed
        except Exception:
            return command

    def _execute_v8_command_result(self, command: str):
        raw = str(command or "")
        if raw.startswith("v8:browser_search:") and "|" in raw:
            try:
                query = raw.split("|", 1)[1]
                subject = _strip_youtube_suffix(query)
                if _fold(subject) not in _REFERENCE_WORDS:
                    self._remember_reference_search(subject)
            except Exception:
                pass
        repaired = self._repair_reference_url(raw)
        outcome = super()._execute_v8_command_result(repaired)
        try:
            if raw.startswith("v8:clarify_search_topic"):
                self.add_message("JARVIS", "Sobre qual assunto o senhor quer que eu pesquise?", is_jarvis=True)
        except Exception:
            pass
        return outcome


__all__ = ["JarvisGUI"]
