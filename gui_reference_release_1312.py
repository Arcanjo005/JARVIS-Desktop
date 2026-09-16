"""Production entry shell for JARVIS Desktop 1.3.12."""
from __future__ import annotations

from gui_reference_final_1312 import JarvisGUI as ReferenceJarvisGUI
from jarvis_natural_tts_1312 import NaturalSpeechTTS1312


class JarvisGUI(ReferenceJarvisGUI):
    """Approved reference UI using the natural continuous speech engine."""

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


__all__ = ["JarvisGUI"]
