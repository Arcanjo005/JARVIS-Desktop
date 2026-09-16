"""Production entry shell for JARVIS Desktop 1.3.12."""
from __future__ import annotations

from pathlib import Path
import sys

from gui_reference_final_1312 import JarvisGUI as ReferenceJarvisGUI
from jarvis_natural_tts_1312 import NaturalSpeechTTS1312


class JarvisGUI(ReferenceJarvisGUI):
    """Approved reference UI using the natural continuous speech engine."""

    def _create_main_layout(self):
        """Build the approved shell and guarantee a visible real chat surface."""
        super()._create_main_layout()
        self._reference_chat_panel = getattr(getattr(self, "chat_scroll", None), "master", None)
        self._reference_chat_visible = True
        panel = self._reference_chat_panel
        if panel is not None:
            try:
                panel.grid(row=3, column=0, sticky="nsew", pady=(5, 5))
                panel.lift()
            except Exception:
                pass
        try:
            self._center.grid_rowconfigure(3, weight=1, minsize=140)
        except Exception:
            pass

    def _set_reference_chat_visible(self, visible: bool):
        """The production build never hides the transcript/chat container.

        Older reference-shell logic collapsed the chat on an empty/new
        conversation.  That made the released app look like chat was missing and
        could also leave the composer below the visible area.  Keep the actual
        chat widget mounted at all times; an empty conversation is represented by
        an empty transcript, not by removing the surface.
        """
        self._reference_chat_visible = True
        panel = getattr(self, "_reference_chat_panel", None)
        if panel is None:
            panel = getattr(getattr(self, "chat_scroll", None), "master", None)
            self._reference_chat_panel = panel
        if panel is not None:
            try:
                panel.grid(row=3, column=0, sticky="nsew", pady=(5, 5))
                panel.lift()
            except Exception:
                pass
        try:
            self._center.grid_rowconfigure(3, weight=1, minsize=140)
            self._later("reference-layout", 10, self._relayout)
        except Exception:
            pass

    def _sync_reference_chat_mode(self):
        self._set_reference_chat_visible(True)

    def _new_conversation(self):
        result = super()._new_conversation()
        self._set_reference_chat_visible(True)
        return result

    def _reference_asset_candidates(self):
        """Prefer the staged copy that build_windows already bundles as data/."""
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
            for relative in (
                Path("data") / "jarvis_reference_scene_1440p.jpg",
                Path("assets") / "jarvis_reference_scene_1440p.jpg",
            ):
                path = (root / relative).resolve()
                key = str(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                yield root, path

    def _get_antonio_tts(self):
        engine = getattr(self, "_antonio_tts", None)
        if engine is not None:
            return engine
        engine = NaturalSpeechTTS1312(
            project_dir=self.project_dir,
            logger=getattr(self, "logger", None),
            on_start=getattr(self, "_on_voice_tts_start", None),
            on_chunk=self._on_antonio_tts_chunk,
            on_end=getattr(self, "_on_voice_tts_end", None),
        )
        self._antonio_tts = engine
        return engine

    def _execute_v8_command_result(self, command: str):
        """Resolve a search reference before any browser action can see it."""
        raw = str(command or "")
        if raw.startswith("v8:browser_search:"):
            contextual, _, _ = self._resolve_browser_context(raw)
            raw = contextual
        return super()._execute_v8_command_result(raw)


__all__ = ["JarvisGUI"]