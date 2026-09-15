"""Deterministic tests for the 1.3.6 voice/overlay lifecycle.

No microphone, speaker, Tk display or PySide process is required. These tests
exercise the transition contract with fakes and also guard the release shell
against reintroducing the old lazy-toggle race.
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path

from jarvis_voice_lifecycle_136 import VoiceLifecycle136Mixin

ROOT = Path(__file__).resolve().parent
CHECKS = 0


def check(value, message):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(message)


class FakeRoot:
    def __init__(self):
        self.withdrawn = False
        self.after_calls = []
    def state(self):
        return "withdrawn" if self.withdrawn else "normal"
    def winfo_exists(self):
        return True
    def withdraw(self):
        self.withdrawn = True
    def deiconify(self):
        self.withdrawn = False
    def after(self, delay, callback):
        self.after_calls.append((delay, callback))
        return len(self.after_calls)
    def after_cancel(self, job):
        return None


class FakeOverlay:
    def __init__(self, alive=True, show_ok=True):
        self.alive = alive
        self.show_ok = show_ok
        self.visible = False
    def is_alive(self):
        return self.alive
    def set_caption(self, value):
        return True
    def set_state(self, value):
        return True
    def show(self, position=None):
        self.visible = bool(self.show_ok)
        return self.show_ok
    def hide(self):
        self.visible = False


class FakeEngine:
    def __init__(self, started=True):
        self._started = started
        self.spoken = []
    def start(self):
        self._started = True
    def speak(self, text, **kwargs):
        self.spoken.append(text)


class Base:
    def __init__(self):
        self.root = FakeRoot()
        self._main_thread_id = threading.get_ident()
        self.voice_engine = None
        self.qt_voice_overlay = None
        self.voice_visual_mode = False
        self.voice_overlay = None
        self.voice_orb_canvas = None
        self.voice_overlay_text_label = None
        self.voice_overlay_state_label = None
        self.voice_orb_animation_job = None
        self._voice_orb_photo = None
        self._voice_visual_state = "REPOUSO"
        self._ui_disposed = False
        self._ui_jobs = {}
        self._chat_tts_enabled = True
        self.voice_enabled = False
        self.voice_button = None
        self.messages = []
        super().__init__()
    def _later(self, name, delay, callback):
        self.root.after(delay, callback)
    def _post_ui_event(self, event, callback):
        if event == "ui_call":
            callback()
    def _setup_voice(self):
        self.voice_engine = FakeEngine(True)
        self.voice_enabled = True
    def _setup_qt_voice_overlay(self):
        self.qt_voice_overlay = FakeOverlay(True, True)
    def _qt_overlay_position(self):
        return (10, 20)
    def _set_voice_overlay_text(self, text):
        self.messages.append(text)
    def _close_voice_overlay(self):
        self.voice_visual_mode = False
        if self.qt_voice_overlay:
            self.qt_voice_overlay.hide()
        self.root.deiconify()
    def _voice_visual_click(self):
        return "base-click"
    def _deliver_text_speech(self, text):
        if self.voice_engine:
            self.voice_engine.speak(text)
        return "delivered"
    def _speak(self, text):
        if self.voice_engine:
            self.voice_engine.speak(text)
            return True
        return False


class Harness(VoiceLifecycle136Mixin, Base):
    def _v136_start_worker(self, target):
        target()


def drain_after(obj):
    pending = list(obj.root.after_calls)
    obj.root.after_calls.clear()
    for _, callback in pending:
        callback()


# 1) Shell composition must put the lifecycle before the responsive GUI.
shell = (ROOT / "gui_conversation_shell.py").read_text(encoding="utf-8")
check("VoiceLifecycle136Mixin, ResponsiveJarvisGUI" in shell, "release shell nao ativa lifecycle 1.3.6")

# 2) Source must never call the old Tk fallback from the lifecycle.
source = (ROOT / "jarvis_voice_lifecycle_136.py").read_text(encoding="utf-8")
check("_open_voice_overlay_tk(" not in source, "lifecycle reintroduziu esfera Tk antiga")
ast.parse(source)
check(True, "lifecycle tem sintaxe Python invalida")

# 3) First voice toggle starts engine + Qt, but does not hide chat immediately.
app = Harness()
# Ignore scheduled prewarm so this remains a first-click test.
app.root.after_calls.clear()
app._toggle_voice_visual_mode()
check(app.voice_engine is not None and app.voice_engine._started, "primeiro clique nao iniciou VoiceEngine")
check(app.qt_voice_overlay is not None and app.qt_voice_overlay.is_alive(), "primeiro clique nao iniciou Qt")
check(app.voice_visual_mode, "modo visual nao ficou ativo depois de Qt pronto")
check(not app.root.withdrawn, "chat foi escondido antes do settle do overlay")
drain_after(app)
check(app.root.withdrawn, "chat nao foi escondido depois do overlay pronto")

# 4) Qt failure must leave the chat visible and must not create Tk fallback.
app = Harness(); app.root.after_calls.clear()
app.voice_engine = FakeEngine(True)
app.qt_voice_overlay = FakeOverlay(False, False)
def fail_qt():
    app.qt_voice_overlay = FakeOverlay(False, False)
app._setup_qt_voice_overlay = fail_qt
app._toggle_voice_visual_mode()
check(not app.root.withdrawn, "falha Qt escondeu o chat")
check(not app.voice_visual_mode, "falha Qt deixou modo visual marcado como ativo")
check(app.voice_overlay is None, "falha Qt criou esfera Tk antiga")

# 5) TTS can initialize without a microphone/overlay dependency.
app = Harness(); app.root.after_calls.clear()
app._deliver_text_speech("resposta digitada")
check(app.voice_engine is not None, "TTS digitado nao inicializou VoiceEngine")
check("resposta digitada" in app.voice_engine.spoken, "resposta digitada nao chegou ao TTS")

# 6) Runtime request that does not require overlay succeeds even if Qt fails.
app = Harness(); app.root.after_calls.clear()
def fail_qt_2():
    app.qt_voice_overlay = FakeOverlay(False, False)
app._setup_qt_voice_overlay = fail_qt_2
ready = []
app._v136_ensure_voice_runtime(reason="tts-test", require_overlay=False, on_ready=lambda: ready.append(True))
check(app.voice_engine is not None, "engine nao iniciou no caminho sem overlay")
check(ready == [True], "TTS ficou indevidamente dependente do overlay")

print(f"JARVIS VOICE LIFECYCLE SELFTEST: PASS ({CHECKS} verificacoes)")
