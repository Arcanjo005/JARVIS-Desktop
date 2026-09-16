#!/usr/bin/env python3
"""Behavioral UI regression tests: real Tk widgets, SQLite and rendering.

The backend boundary is deterministic: no microphone, API calls, Windows actions,
real updates or user settings are touched. The controller, event queue, history,
composer, dialogs and renderer are real production implementations.
Run on Windows, or under xvfb-run on Linux. Evidence goes to validation/.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageChops, ImageGrab
import customtkinter as ctk

from jarvis_display import WorkArea, clamp_rect, popup_geometry, fit_window
from jarvis_ui_render import OrbRenderer, OrbWorker, RenderRequest, rotation, project, render_scene
from gui_reference_final_1311 import JarvisGUI
from gui_reference_exact_v3 import MessageText

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "validation"


class CaptureLogger:
    def __init__(self):
        self.errors = []
        self.warnings = []
    def info(self, *args): pass
    def system(self, *args): pass
    def debug(self, *args): pass
    def warning(self, *args): self.warnings.append(str(args))
    def error(self, *args): self.errors.append(str(args))
    def get_buffer_logs(self, limit=50): return []


class VoiceFixture:
    def __init__(self):
        self.spoken = []
        self.rate = "+10%"
        self.sensitivity = 1.12
        self.conversation = False
        self._started = True
    def speak(self, text, **kwargs): self.spoken.append(text)
    def stop_speaking(self, **kwargs): pass
    def set_assistant_busy(self, value): pass
    def set_conversation_mode(self, value): self.conversation = value
    def set_tts_rate(self, value): self.rate = value; return value
    def set_microphone_sensitivity(self, value): self.sensitivity = value; return value
    def status(self):
        return {"tts_rate": self.rate, "mic_sensitivity": self.sensitivity,
                "microphone_available": True, "tts_speaking": False}


class TestApplication(JarvisGUI):
    """Only external/background services are replaced, never UI behaviors."""
    def _start_deferred_runtime(self): pass
    def _start_persistent_reminder_watcher(self): pass
    def _start_jarvis_player_watcher(self): pass
    def _v136_schedule_prewarm(self): pass
    def _process_message(self, message, source="text"):
        token = self._begin_work_generation()
        self.requests.append((token, message, source))
        return token


def pump(app, seconds=0.12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.root.update()
        time.sleep(.005)
    app.root.update_idletasks()


def settle_layout(app, timeout=5.0):
    deadline = time.monotonic()+timeout
    previous = None
    stable_since = None
    snapshot = None
    while time.monotonic() < deadline:
        pump(app, .025)
        widgets = (app.root, app.update_button, app.quick_menu_button,
                   app.text_input, app.send_button)
        snapshot = tuple((w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height())
                         for w in widgets)
        pending = set(app._ui_jobs).intersection({"layout", "fit", "reference-layout"})
        now = time.monotonic()
        if snapshot == previous and not pending:
            if stable_since is None: stable_since = now
            elif now-stable_since >= .15: return
        else: stable_since = None
        previous = snapshot
    raise AssertionError(f"Layout did not settle: jobs={list(app._ui_jobs)}, geometry={snapshot}")


def walk(widget):
    yield widget
    for child in widget.winfo_children(): yield from walk(child)


class GeometryTests(unittest.TestCase):
    def test_negative_monitor_origin(self):
        a = WorkArea(-1920, -120, 1920, 1080)
        x, y, w, h = clamp_rect(-2100, -250, 2500, 1600, a)
        self.assertGreaterEqual(x, a.x); self.assertGreaterEqual(y, a.y)
        self.assertLessEqual(x+w, a.x+a.width); self.assertLessEqual(y+h, a.y+a.height)
        self.assertLess(x, 0)

    def test_popup_geometry_stays_inside_work_area(self):
        a = WorkArea(-1920, -120, 1920, 1080)
        x, y, w, h = popup_geometry(-2000, -200, 900, 600, a)
        self.assertGreaterEqual(x, a.x); self.assertGreaterEqual(y, a.y)
        self.assertLessEqual(x+w, a.x+a.width); self.assertLessEqual(y+h, a.y+a.height)


class RendererMathTests(unittest.TestCase):
    def test_rotation_preserves_norm(self):
        points = np.asarray(((1,0,0),(0,1,0),(0,0,1),(1,1,1)), dtype=np.float32)
        for angle in (0, .2, 1.3, 5.1):
            rotated = points @ rotation(angle).T
            self.assertTrue(np.allclose(np.linalg.norm(points,axis=1), np.linalg.norm(rotated,axis=1), atol=1e-5))

    def test_projection_depth_changes(self):
        points=np.asarray(((1,0,0),(0,0,1)),dtype=np.float32)
        a=project(points,0,100,100); b=project(points,math.pi/2,100,100)
        self.assertFalse(np.allclose(a[:,2],b[:,2]))

    def test_orb_is_rgba(self):
        img=OrbRenderer().render(180,.2,"REPOUSO",0)
        self.assertEqual(img.mode,"RGBA"); self.assertEqual(img.size,(180,180))

    def test_scene_is_rgb(self):
        img=render_scene(320,180)
        self.assertEqual(img.mode,"RGB"); self.assertEqual(img.size,(320,180))


class FinalReferenceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        os.environ["JARVIS_APP_DIR"]=cls.temp.name
        os.environ["LOCALAPPDATA"]=cls.temp.name
        cls.app=TestApplication()
        cls.app.requests=[]
        cls.app.voice_engine=VoiceFixture()
        pump(cls.app,.4)

    @classmethod
    def tearDownClass(cls):
        try: cls.app.root.destroy()
        except Exception: pass
        cls.temp.cleanup()

    def assert_inside(self, widget):
        root=self.app.root
        self.assertTrue(widget.winfo_viewable(),str(widget))
        x=widget.winfo_rootx()-root.winfo_rootx(); y=widget.winfo_rooty()-root.winfo_rooty()
        self.assertGreaterEqual(x,-1); self.assertGreaterEqual(y,-1)
        self.assertLessEqual(x+widget.winfo_width(),root.winfo_width()+1)
        self.assertLessEqual(y+widget.winfo_height(),root.winfo_height()+1)

    def test_reference_controls_exist(self):
        self.assertIsNotNone(self.app.reference_switch_bar)
        self.assertIsNotNone(self.app._reference_settings_button)
        self.assertEqual(self.app.copy_conversation_button.cget("text"),"Copiar diagnóstico")

    def test_responsive_sizes_and_live_controls(self):
        for w,h in ((1420,900),(1024,680),(800,600),(620,440),(1280,720)):
            self.app.root.geometry(f"{w}x{h}+20+20")
            settle_layout(self.app)
            for widget in (self.app.quick_menu_button,self.app.text_input,self.app.send_button,self.app.voice_button,self.app.update_button):
                self.assert_inside(widget)
            if self.app._wide_layout:
                self.assert_inside(self.app.history_button)

    def test_hidpi_and_4k_composition(self):
        original_widget=ctk.ScalingTracker.widget_scaling
        original_window=ctk.ScalingTracker.window_scaling
        try:
            for scale in (1.25,1.5,2.0):
                ctk.set_widget_scaling(scale); ctk.set_window_scaling(scale)
                self.app.root.geometry("1000x700+10+10")
                settle_layout(self.app)
                for widget in (self.app.update_button,self.app.quick_menu_button,self.app.text_input,self.app.send_button): self.assert_inside(widget)
            ctk.set_widget_scaling(2.0); ctk.set_window_scaling(1.0)
            self.app.root.geometry("1900x1000+0+0"); settle_layout(self.app)
            for widget in (self.app.update_button,self.app.quick_menu_button,self.app.text_input,self.app.send_button): self.assert_inside(widget)
        finally:
            ctk.set_widget_scaling(original_widget); ctk.set_window_scaling(original_window)

    def test_history_drawer_and_breakpoints(self):
        self.app.root.geometry("700x520+10+10"); settle_layout(self.app)
        self.assertFalse(self.app._wide_layout)
        self.app._toggle_history(); pump(self.app,.15)
        self.assertTrue(self.app.side_panel.winfo_viewable())
        self.app._toggle_history(); pump(self.app,.12)
        self.app.root.geometry("1200x800+10+10"); settle_layout(self.app)
        self.assertTrue(self.app._wide_layout); self.assertTrue(self.app.side_panel.winfo_viewable())

    def test_reference_search_never_searches_literal_isso(self):
        self.app._reference_last_search_topic="RTX 5060"
        command,resolved,raw=self.app._resolve_browser_context("v8:browser_search:Opera|isso no YouTube")
        self.assertIn("youtube.com/results?search_query=RTX+5060",command)
        self.assertEqual(resolved,"RTX 5060")
        self.assertNotIn("search_query=isso",command.lower())

    def test_caption_follows_spoken_chunk(self):
        self.app._captions_enabled=True
        self.app._set_voice_overlay_text("primeiro trecho")
        pump(self.app,.05)
        self.assertIn("primeiro trecho",self.app._caption.cget("text").lower())
        self.app._set_voice_overlay_text("segundo trecho")
        pump(self.app,.05)
        self.assertIn("segundo trecho",self.app._caption.cget("text").lower())
        self.assertNotIn("primeiro trecho",self.app._caption.cget("text").lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
