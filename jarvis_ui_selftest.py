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
from gui_conversation_shell import JarvisGUI
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
        pending = set(app._ui_jobs).intersection({"layout", "fit"})
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

    def test_rectangles_on_all_monitor_positions(self):
        for area in (WorkArea(0,0,1366,728), WorkArea(3840,200,1280,680), WorkArea(-1920,-1080,1920,1040)):
            for x, y in ((-5000,-5000),(0,0),(9000,9000)):
                rx,ry,w,h=clamp_rect(x,y,2500,1800,area)
                self.assertTrue(area.x <= rx < rx+w <= area.x+area.width)
                self.assertTrue(area.y <= ry < ry+h <= area.y+area.height)

    def test_popup_uses_monitor_and_logical_scale(self):
        anchor = SimpleNamespace(winfo_rootx=lambda:-1800, winfo_rooty=lambda:900)
        panel = SimpleNamespace(_get_window_scaling=lambda:1.5)
        with patch("jarvis_display.monitor_work_area", return_value=WorkArea(-1920,0,1280,680)):
            w,h,x,y=popup_geometry(panel,anchor)
        self.assertLessEqual(h*1.5,640); self.assertLess(x,0); self.assertGreaterEqual(y,0)


class RenderTests(unittest.TestCase):
    def test_rotation_is_orthogonal_and_depth_changes(self):
        r=rotation(.83); np.testing.assert_allclose(r@r.T,np.eye(3),atol=1e-6)
        self.assertAlmostEqual(float(np.linalg.det(r)),1,places=6)
        point=np.asarray([[0,0,1]],dtype=np.float32)
        front=project(point,0,1,0);back=project(point,math.pi,1,0)
        self.assertGreater(front[0,2],0);self.assertLess(back[0,2],0)

    def test_render_has_transparency_and_real_motion(self):
        renderer=OrbRenderer(); first=renderer.render(200,0); second=renderer.render(200,1.5)
        self.assertEqual(first.mode,"RGBA");self.assertEqual(first.size,(200,200));self.assertEqual(first.getpixel((0,0))[3],0)
        self.assertIsNotNone(ImageChops.difference(first,second).getbbox())
        a=np.asarray(first);b=np.asarray(second);self.assertGreater(np.count_nonzero(a[50:150,50:150]!=b[50:150,50:150]),300)

    def test_render_cache_bounded_during_resize(self):
        renderer=OrbRenderer()
        for size in (160,220,350,640,160):
            image=renderer.render(size,.5);self.assertEqual(image.size,(size,size));self.assertLessEqual(renderer._internal,renderer.MAX_RENDER_SIZE)
        self.assertEqual(renderer._key,(160,320))

    def test_scene_4k(self):
        scene=render_scene(3840,2160);self.assertEqual(scene.size,(3840,2160));self.assertEqual(scene.mode,"RGB")

    def test_worker_start_failure_is_reported_without_crashing(self):
        with patch("multiprocessing.context.SpawnProcess.start",side_effect=OSError("blocked")): worker=OrbWorker()
        try:
            self.assertIn("blocked",worker.error);worker.request(RenderRequest(150));self.assertIsNone(worker.take())
        finally: worker.close()

    def test_worker_pause_and_shutdown(self):
        worker=OrbWorker()
        try:
            self.assertIsNone(worker.take());worker.request(RenderRequest(150,"PENSANDO",.4,True))
            end=time.monotonic()+10;image=None
            while image is None and time.monotonic()<end: time.sleep(.03);image=worker.take()
            self.assertIsNotNone(image, f"worker exit={worker.process.exitcode}; error={worker.error}")
            worker.request(RenderRequest(150,visible=False));time.sleep(.2);worker.take();time.sleep(.2)
            self.assertIsNone(worker.take());self.assertIsNone(worker.error)
        finally: worker.close();worker.process.join(3)
        self.assertFalse(worker.process.is_alive())


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="jarvis-ui-test-")
        cls.oldenv={key:os.environ.get(key) for key in ("JARVIS_APP_DIR","LOCALAPPDATA","GEMINI_API_KEY")}
        os.environ["JARVIS_APP_DIR"]=cls.temp.name;os.environ["LOCALAPPDATA"]=cls.temp.name;os.environ.pop("GEMINI_API_KEY",None)
        cls.log=CaptureLogger();cls.app=TestApplication(cls.log,SimpleNamespace(),SimpleNamespace());cls.app.requests=[];cls.callbacks=[]
        cls.app.root.report_callback_exception=lambda *exc: cls.callbacks.append("".join(traceback.format_exception(*exc)));pump(cls.app,.8)

    @classmethod
    def tearDownClass(cls):
        cls.app._close_quick_control_panel()
        controller=getattr(cls.app,"qt_voice_overlay",None)
        if controller is not None:
            try: controller.stop()
            except Exception: pass
            cls.app.qt_voice_overlay=None
        cls.app._orb_worker.close();cls.app.root.destroy();cls.app._orb_worker.process.join(3);cls.app.memory_store.close()
        for key,value in cls.oldenv.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value
        cls.temp.cleanup()
        if cls.callbacks or cls.log.errors: raise AssertionError("Tk/controller errors: " + repr(cls.callbacks+cls.log.errors))
        if cls.app._orb_worker.process.is_alive(): raise AssertionError("Renderer process leaked after window destruction")

    def setUp(self):
        self._started=time.monotonic();a=self.app;a._close_quick_control_panel()
        for name in ("_help_window","_conversation_search_popup"):
            win=getattr(a,name,None)
            if win is not None and win.winfo_exists(): win.destroy()
            setattr(a,name,None)
        a._invalidate_active_work();a._speech_delivery=None;a._text_speech_token=None;a._text_turn_token=None
        a.voice_engine=None;a._voice_command_active=False;a._chat_tts_enabled=True;a._pending_update_info=None;a._update_download_active=False
        a.update_button.configure(text="ATUALIZAR",state="normal");a.is_processing=False
        if ctk.ScalingTracker.widget_scaling != 1: ctk.set_widget_scaling(1)
        if ctk.ScalingTracker.window_scaling != 1: ctk.set_window_scaling(1)
        a.root.deiconify();a.root.geometry("1100x760");a._new_conversation();a.requests.clear();pump(a,.18)

    def tearDown(self):
        print(f" [{time.monotonic()-self._started:.2f}s]", end="", flush=True);self.assertFalse(self.callbacks,repr(self.callbacks));self.assertFalse(self.log.errors,repr(self.log.errors))

    def assert_inside(self, widget):
        root=self.app.root;self.assertTrue(widget.winfo_viewable(),str(widget));x,y=widget.winfo_rootx()-root.winfo_rootx(),widget.winfo_rooty()-root.winfo_rooty()
        self.assertGreaterEqual(x,-1);self.assertGreaterEqual(y,-1);self.assertLessEqual(x+widget.winfo_width(),root.winfo_width()+1);self.assertLessEqual(y+widget.winfo_height(),root.winfo_height()+1)

    def send(self,text="Teste deterministico"):
        a=self.app;a._composer_focus_in();a.text_input.delete("1.0","end");a.text_input.insert("1.0",text);a.send_button.invoke();return a.requests[-1][0]

    def test_responsive_sizes_and_live_controls(self):
        a=self.app
        for width,height in ((1420,900),(1024,680),(800,600),(620,440),(1280,720)):
            a.root.geometry(f"{width}x{height}");settle_layout(a)
            for widget in (a.quick_menu_button,a.text_input,a.send_button,a.voice_button,a.update_button,a.history_button): self.assert_inside(widget)
            self.assertGreater(a.text_input.winfo_width(),180);ox,oy=a._hero.coords(a._orb_item);self.assertAlmostEqual(ox,a._hero.winfo_width()/2,delta=1);self.assertAlmostEqual(oy,a._hero.winfo_height()/2,delta=1);self.assertGreater(a.chat_scroll._parent_canvas.winfo_height(),60)
        self.assertEqual(a.side_panel.winfo_width(),242)

    def test_hidpi_and_4k_composition(self):
        a=self.app
        for scale in (1.25,1.5,2):
            ctk.set_widget_scaling(scale);ctk.set_window_scaling(scale);a.root.geometry("1000x700");settle_layout(a)
            for widget in (a.update_button,a.quick_menu_button,a.text_input,a.send_button): self.assert_inside(widget)
        ctk.set_widget_scaling(2);ctk.set_window_scaling(1);a.root.geometry(f"{min(3800,a.root.winfo_screenwidth()-50)}x{min(2050,a.root.winfo_screenheight()-120)}");settle_layout(a);self.assert_inside(a.update_button)

    def test_history_drawer_and_breakpoints(self):
        a=self.app;a.root.geometry("700x520");pump(a,.25);self.assertFalse(a.side_panel.winfo_viewable())
        for _ in range(3):
            a.history_button.invoke();pump(a,.04);self.assertTrue(a.side_panel.winfo_viewable());self.assert_inside(a.side_panel);a.history_button.invoke();pump(a,.04);self.assertFalse(a.side_panel.winfo_viewable())
        a.root.geometry("1200x800");pump(a,.2);self.assertTrue(a.side_panel.winfo_viewable())

    def test_plus_opens_original_functions_without_losing_glyph(self):
        a=self.app
        for _ in range(3):
            a.quick_menu_button.invoke();pump(a,.12);self.assertTrue(a.quick_panel.winfo_exists());self.assertEqual(a.quick_menu_button.cget("text"),"+");self.assertIn("Conversa",a.quick_panel.buttons);self.assertIn("Logs",a.quick_panel.buttons);a.quick_menu_button.invoke();pump(a,.02);self.assertIsNone(a.quick_panel);self.assertEqual(a.quick_menu_button.cget("text"),"+")

    def test_controls_disable_unavailable_voice_and_enable_when_ready(self):
        a=self.app;a.quick_menu_button.invoke();pump(a,.08);self.assertTrue(all(b.cget("state")=="disabled" for b in a.quick_panel.audio_buttons))
        a.voice_engine=VoiceFixture();pump(a,.6);self.assertTrue(all(b.cget("state")=="normal" for b in a.quick_panel.audio_buttons));a.quick_panel.buttons["Devagar"].invoke();self.assertEqual(a.voice_engine.rate,"+4%");a.quick_panel.buttons["Sens\u00edvel"].invoke();self.assertEqual(a.voice_engine.sensitivity,1.18);a.quick_panel.buttons["Conversa"].invoke();self.assertTrue(a.voice_engine.conversation);self.assertEqual(a.interaction_mode,"conversa")

    def test_help_does_not_execute_examples(self):
        a=self.app;a._show_functions();pump(a,.1);buttons=[w for w in walk(a._help_window) if isinstance(w,ctk.CTkButton)];self.assertGreaterEqual(len(buttons),5);buttons[0].invoke();self.assertEqual(len(a.requests),0);self.assertEqual(a._composer_text(),"Abra a calculadora")

    def test_history_persists_switch_rename_and_search(self):
        a=self.app;first=a.active_conversation_id;a.add_message("Voce","MARCADOR-PERSISTENTE",is_user=True);self.assertTrue(a.memory_store.rename_conversation(first,"Conversa de teste"));a._new_chat_button.invoke();second=a.active_conversation_id;self.assertNotEqual(first,second);a._switch_conversation(first);pump(a,.2);self.assertTrue(any("MARCADOR-PERSISTENTE" in m["message"] for m in a.chat_history));a._conversation_search_button.invoke();pump(a,.08);a.history_search_entry.insert(0,"MARCADOR-PERSISTENTE");a._search_history_ui();pump(a,.05);self.assertIn("Resultados",a.chat_history[-1]["message"]);a._switch_conversation(second);pump(a,.1);self.assertTrue(a.memory_store.delete_conversation(first));self.assertEqual(a.memory_store.load_messages(first),[])

    def test_long_message_reflows_without_truncation(self):
        a=self.app;text=("Mensagem com acentos: a\u00e7\u00e3o, hist\u00f3rico e informa\u00e7\u00e3o. "*80)+"FIM-DA-MENSAGEM";widget=a._create_chat_bubble("JARVIS",text,is_jarvis=True);a.root.geometry("1400x900");pump(a,.4);wide_height=float(widget.cget("height"));a.root.geometry("620x440");pump(a,.5);self.assertGreater(float(widget.cget("height")),wide_height);self.assertEqual(widget.get("1.0","end-1c"),text);native=widget._textbox;native.see("end-1c");a.root.update_idletasks();self.assertIsNotNone(native.dlineinfo("end-1c"));self.assertEqual(widget._textbox.cget("state"),"disabled")

    def test_composer_return_and_shift_return(self):
        a=self.app;a._composer_focus_in();a.text_input.insert("1.0","linha 1\nlinha 2");self.assertIsNone(a._on_composer_return(SimpleNamespace(state=1)));self.assertFalse(a.requests);self.assertEqual(a._on_composer_return(SimpleNamespace(state=0)),"break");self.assertEqual(a.requests[-1][1],"linha 1\nlinha 2")

    def test_empty_composer_never_sends(self):
        a=self.app;a.send_button.invoke();self.assertFalse(a.requests);a._composer_focus_in();a.text_input.insert("1.0"," \n ");a.send_button.invoke();self.assertFalse(a.requests)

    def test_update_pulses_only_for_available_release(self):
        a=self.app;pump(a,.08);self.assertFalse(a._update_pulsing);a._show_update_available(SimpleNamespace(version="9.9.9"));pump(a,.08);self.assertTrue(a._update_pulsing);c=a.update_button.cget("fg_color");pump(a,.15);self.assertNotEqual(c,a.update_button.cget("fg_color"));a._update_download_active=True;a._set_update_progress(20,100);pump(a,.08);self.assertFalse(a._update_pulsing);self.assertIn("20%",a.update_button.cget("text"));a._update_download_active=False;a._pending_update_info=None;a.update_button.configure(state="normal");pump(a,.08);self.assertFalse(a._update_pulsing)

    def test_update_button_reaches_real_check_without_install(self):
        a=self.app;a.update_manager=SimpleNamespace(is_configured=lambda:True,check=lambda:None)
        with patch("gui.messagebox.showinfo") as info: a.update_button.invoke();pump(a,.3);self.assertTrue(info.called)
        self.assertIsNone(a._pending_update_info);self.assertFalse(a._update_pulsing)

    def test_typed_reply_speaks_once(self):
        a=self.app;a.voice_engine=VoiceFixture();self.send();a.add_message("JARVIS","Resposta completa de teste.",is_jarvis=True,speak=True);self.assertEqual(len(a.voice_engine.spoken),1);a._deliver_text_speech("Resposta repetida");self.assertEqual(len(a.voice_engine.spoken),1)

    def test_speech_disabled_suppresses_explicit_typed_speak(self):
        a=self.app;a.voice_engine=VoiceFixture();a._chat_tts_enabled=False;self.send();a.add_message("JARVIS","Nao falar.",is_jarvis=True,speak=True);self.assertEqual(a.voice_engine.spoken,[])

    def test_typed_interrupt_respects_disabled_speech(self):
        a=self.app;a.voice_engine=VoiceFixture();a._voice_command_active=True;a.is_processing=True;a._chat_tts_enabled=False;a.send_button.invoke();self.assertTrue(a._voice_command_active);self.send("Typed input interrupts the voice turn");self.assertFalse(a._voice_command_active);a.add_message("JARVIS","Typed response must remain silent.",is_jarvis=True,speak=True);self.assertEqual(a.voice_engine.spoken,[])

    def test_typed_interrupt_stream_speaks_once(self):
        a=self.app;a.voice_engine=VoiceFixture();a._voice_command_active=True;a.is_processing=True;token=self.send("Typed input owns the new turn");self.assertFalse(a._voice_command_active);a._active_stream_token=token;a.streaming_label=a._create_chat_bubble("JARVIS","",is_jarvis=True);a._append_streaming_chunk("Typed response.");self.assertEqual(a.voice_engine.spoken,[]);a._finish_streaming_response("Typed response.",token);a._finish_streaming_response("Stale response.",token);self.assertEqual(a.voice_engine.spoken,[a._voice_spoken_summary("Typed response.")])

    def test_delayed_speech_cannot_leak_into_new_turn(self):
        a=self.app;self.send("primeiro");a.add_message("JARVIS","Resposta antiga",is_jarvis=True);self.send("segundo");a.voice_engine=VoiceFixture();pump(a,.4);self.assertEqual(a.voice_engine.spoken,[]);a.add_message("JARVIS","Resposta nova",is_jarvis=True);self.assertEqual(a.voice_engine.spoken,[a._voice_spoken_summary("Resposta nova")])

    def test_history_restoration_does_not_speak(self):
        a=self.app;cid=a.active_conversation_id;a.add_message("JARVIS","Registro antigo",is_jarvis=True);a._new_conversation();a.voice_engine=VoiceFixture();a._switch_conversation(cid);pump(a,.2);self.assertEqual(a.voice_engine.spoken,[])

    def test_streaming_completion_speaks_once_and_rejects_old_token(self):
        a=self.app;a.voice_engine=VoiceFixture();token=self.send();a._active_stream_token=token;a.streaming_label=a._create_chat_bubble("JARVIS","",is_jarvis=True);a._append_streaming_chunk("Resposta ");a._append_streaming_chunk("em fluxo.");a._finish_streaming_response("Resposta em fluxo.",token);a._finish_streaming_response("Resposta duplicada.",token);self.assertEqual(a.voice_engine.spoken,[a._voice_spoken_summary("Resposta em fluxo.")])

    def test_background_message_is_queued_to_tk_thread(self):
        a=self.app;count=len(a.chat_history);t=threading.Thread(target=lambda:a.add_message("Sistema","Evento em fila",is_system=True));t.start();t.join(2);self.assertEqual(len(a.chat_history),count);pump(a,.15);self.assertEqual(a.chat_history[-1]["message"],"Evento em fila")

    def test_preferences_preserve_other_fields(self):
        a=self.app;path=Path(a.project_dir)/"data"/"ui_layout.json";data=json.loads(path.read_text()) if path.exists() else {};data["unrelated_test_setting"]="preserved";path.write_text(json.dumps(data),encoding="utf-8");a._chat_tts_enabled=False;a._captions_enabled=False;a._save_visual_preferences();a._load_visual_preferences();self.assertFalse(a._chat_tts_enabled);self.assertFalse(a._captions_enabled);self.assertEqual(json.loads(path.read_text())["unrelated_test_setting"],"preserved");a._chat_tts_enabled=True;a._captions_enabled=True;a._save_visual_preferences()

    def test_long_title_does_not_displace_update(self):
        a=self.app;a.root.geometry("620x440");a.current_conversation_label.configure(text="Titulo muito longo "*80);pump(a,.2);self.assert_inside(a.update_button);self.assert_inside(a.history_button)

    def test_minimized_worker_pauses(self):
        a=self.app;a.root.withdraw();pump(a,.3);a._orb_worker.take();pump(a,.25);self.assertIsNone(a._orb_worker.take());a.root.deiconify();pump(a,.4);self.assertIsNone(a._orb_worker.error)

    def test_old_update_notice_cannot_overwrite_download(self):
        a=self.app
        with patch("gui.messagebox.showinfo"): a._finish_manual_update_check(None)
        a._show_update_available(SimpleNamespace(version="9.9.9"));a._update_download_active=True;a._set_update_progress(37,100);pump(a,1.95);self.assertEqual(a.update_button.cget("text"),"BAIXANDO 37%");self.assertEqual(a.update_button.cget("state"),"disabled")

    def test_corrupt_and_nonobject_preferences_do_not_crash(self):
        a=self.app;path=Path(a.project_dir)/"data"/"ui_layout.json"
        for malformed in ("not-json", "[]", "null"): path.write_text(malformed,encoding="utf-8");a._load_visual_preferences();self.assertTrue(a._chat_tts_enabled)
        a._save_visual_preferences();self.assertIsInstance(json.loads(path.read_text()),dict)

    def test_compact_height_preserves_composer_and_transcript(self):
        a=self.app;a.root.minsize(480,340);a.root.geometry("520x370");pump(a,.16);a._relayout();pump(a,.04)
        for widget in (a.update_button,a.quick_menu_button,a.text_input,a.send_button): self.assert_inside(widget)
        self.assertGreater(a.chat_scroll._parent_canvas.winfo_height(),60)

    def test_z_capture_real_ui_evidence(self):
        a=self.app;a._hero_state="OUVINDO";a.add_message("Voce","Onde encontro as funcoes?",is_user=True);a.add_message("JARVIS","Use o + para abrir os controles ou escreva o que precisa aqui. F1 mostra exemplos.",is_jarvis=True);EVIDENCE.mkdir(exist_ok=True)
        for geometry in ("1420x900","800x600","620x440"):
            a.root.geometry(geometry);pump(a,.45);x,y=a.root.winfo_rootx(),a.root.winfo_rooty();ImageGrab.grab(bbox=(x,y,x+a.root.winfo_width(),y+a.root.winfo_height())).save(EVIDENCE/f"ui-{geometry}.png")
        if a.root.winfo_screenwidth()>=3840 and a.root.winfo_screenheight()>=2160:
            ctk.set_widget_scaling(2);ctk.set_window_scaling(1);a.root.geometry("3840x2160+0+0");pump(a,1.2);self.assertEqual((a.root.winfo_width(),a.root.winfo_height()),(3840,2160));self.assert_inside(a.update_button);ImageGrab.grab(bbox=(0,0,3840,2160)).save(EVIDENCE/"ui-3840x2160.png");ctk.set_widget_scaling(1);a.root.geometry("800x600");pump(a,.5)
        a.quick_menu_button.invoke();pump(a,.2);x,y=a.quick_panel.winfo_rootx(),a.quick_panel.winfo_rooty();ImageGrab.grab(bbox=(x,y,x+a.quick_panel.winfo_width(),y+a.quick_panel.winfo_height())).save(EVIDENCE/"quick-controls.png")


def main():
    EVIDENCE.mkdir(exist_ok=True);started=time.perf_counter();suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]);result=unittest.TextTestRunner(verbosity=2).run(suite)
    files=("gui_reference_exact_v3.py","gui_conversation_shell.py","jarvis_display.py","jarvis_quick_controls.py","jarvis_ui_render.py","jarvis_ui_selftest.py")
    report={"ok":result.wasSuccessful(),"tests":result.testsRun,"seconds":round(time.perf_counter()-started,2),"platform":sys.platform,"python":sys.version,"screen":"runner desktop / virtual display","scope":"Real Tk + SQLite + rendered frames; deterministic backend; no live audio, API or installation","failures":[[str(test),error] for test,error in result.failures+result.errors],"source_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}}
    (EVIDENCE/"ui-test-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support();main()
