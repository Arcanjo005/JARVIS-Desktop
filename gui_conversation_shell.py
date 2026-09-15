"""Stable release entry point for the responsive cinematic interface.

The 1.3.6 shell adds a single lifecycle owner around the proven responsive UI;
all presentation remains in gui_reference_exact_v3.JarvisGUI.
"""
from gui_reference_exact_v3 import JarvisGUI as ResponsiveJarvisGUI
from jarvis_voice_lifecycle_136 import VoiceLifecycle136Mixin


class JarvisGUI(VoiceLifecycle136Mixin, ResponsiveJarvisGUI):
    """Responsive UI plus the safe 1.3.6 voice/overlay lifecycle."""


__all__ = ["JarvisGUI"]
