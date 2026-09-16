"""Production entry shell for JARVIS Desktop 1.3.12."""
from __future__ import annotations

from pathlib import Path
import sys

from gui_reference_final_1312 import JarvisGUI as ReferenceJarvisGUI
from jarvis_natural_tts_1312 import NaturalSpeechTTS1312


class JarvisGUI(ReferenceJarvisGUI):
    """Approved reference UI using the natural continuous speech engine."""

    def _create_main_layout(self):
        """Build the approved shell and keep the real transcript host reachable.

        The final-reference layer applies cosmetic CTk options after the base
        layout exists.  Some CustomTkinter versions reject one of those cosmetic
        options and the defensive block used to clear ``_reference_chat_panel``
        even though the real chat host had already been created.  Release code
        must never let a styling error disable chat visibility transitions.
        """
        super()._create_main_layout()
        if getattr(self, "_reference_chat_panel", None) is None:
            self._reference_chat_panel = getattr(getattr(self, "chat_scroll", None), "master", None)

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