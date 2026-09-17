#!/usr/bin/env python3
"""Strict headless smoke for the single-source approved Qt desktop UI."""
from __future__ import annotations

import os
import sys
from pathlib import Path
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["JARVIS_QT_DISABLE_AUTO_VOICE"] = "1"
os.environ["JARVIS_QT_DISABLE_AUTO_UPDATE"] = "1"

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from gui import FORBIDDEN_VISUAL_MODULES, JarvisGUI, REQUIRED_UI_ASSETS, required_asset_paths

class Logger:
    def info(self,*args,**kwargs): pass
    def system(self,*args,**kwargs): pass
    def warning(self,*args,**kwargs): pass
    def error(self,*args,**kwargs): pass

class Core:
    def process_message_stream(self,message,history,memories,system_commands_info="",on_chunk=None,**kwargs):
        del history,memories,system_commands_info,kwargs
        answer=f"Resposta Qt para: {message}"
        if callable(on_chunk): on_chunk("Resposta Qt "); on_chunk(f"para: {message}")
        return answer

def wait(ms=100):
    loop=QEventLoop(); QTimer.singleShot(ms,loop.quit); loop.exec()
def check(value,message):
    if not value: raise AssertionError(message)

def main():
    root=Path(__file__).resolve().parent
    source=(root/"gui.py").read_text(encoding="utf-8"); upper=source.upper()
    check("JARVIS DESKTOP INTELLIGENCE" not in upper,"forbidden old title remains in gui.py")
    check("from gui_qt_" not in source,"gui.py imports a legacy Qt visual module")
    check("from gui_reference" not in source,"gui.py imports a legacy reference visual module")
    check("_paint_hologram" not in source,"old painter sphere fallback remains")
    check("QRadialGradient" not in source,"old radial painter sphere remains")
    check("↻" not in source,"old update glyph remains")
    paths=required_asset_paths(); check(set(paths)==set(REQUIRED_UI_ASSETS),"approved asset manifest mismatch")
    for name,path in paths.items(): check(path.is_file(),f"approved UI asset missing: {name}"); check(path.stat().st_size>=128,f"approved UI asset invalid: {name}")
    forbidden=[name for name in FORBIDDEN_VISUAL_MODULES if name in sys.modules]; check(not forbidden,f"legacy visual module loaded: {forbidden}")
    app=QApplication.instance() or QApplication([]); evidence=root/"validation"; evidence.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jarvis-qt-smoke-") as td:
        os.environ["JARVIS_APP_DIR"]=td; window=JarvisGUI(Logger(),object(),Core()); window.resize(1280,780); window.show(); wait(180)
        check(window.windowTitle().startswith("JARVIS Desktop "),"window title is not the Qt shell")
        check(window.sidebar.width()==310,"approved sidebar width changed")
        check("rgba(2,10,17,198)" in window.styleSheet(),"sidebar is not the approved translucent style")
        check(window.status.text()=="ONLINE","ONLINE neon status is missing")
        check("#55ff9a" in window.status.styleSheet().lower(),"ONLINE status is not green neon")
        check(window.scene.isVisible(),"approved scene is not visible")
        check(window.scene.bg.pixmap() is not None and not window.scene.bg.pixmap().isNull(),"workspace background did not load")
        check(window.scene.orb.pixmap() is not None and not window.scene.orb.pixmap().isNull(),"approved sphere did not load")
        check(window.chat_frame.isVisible(),"floating chat is missing"); check(window.chat_frame.minimumHeight()>=250,"chat height regressed")
        check(window.composer.isVisible(),"composer is missing"); check(window.composer.height()==66,"composer height changed")
        check(window.composer.plus.text()=="+","approved plus control changed"); check(window.composer.mic.text()=="●","approved mic control changed"); check(window.composer.send.text()=="➤","approved send control changed"); check(window.update_button.text()=="↑","approved neon update control changed")
        check(window.history.count()>=1,"history has no conversation row"); check(window.history.findChildren(QPushButton,"historyMenu"),"history row has no three-dot menu")
        all_text=" ".join(label.text() for label in window.findChildren(QLabel)).upper(); check("DESKTOP INTELLIGENCE" not in all_text,"forbidden old subtitle is visible")
        window.composer.submit.emit("teste funcional"); deadline=time.monotonic()+2.5
        while time.monotonic()<deadline:
            app.processEvents(); rows=window.bridge.memory.load_messages(window.bridge.active_conversation_id)
            if len(rows)>=2: break
            time.sleep(.01)
        rows=window.bridge.memory.load_messages(window.bridge.active_conversation_id)
        check(any(r.get("is_user") and r.get("message")=="teste funcional" for r in rows),"user message did not persist")
        check(any(r.get("is_jarvis") and "Resposta Qt para" in r.get("message","") for r in rows),"Qt response did not persist")
        forbidden=[name for name in FORBIDDEN_VISUAL_MODULES if name in sys.modules]; check(not forbidden,f"legacy visual module loaded after startup: {forbidden}")
        shot=window.grab(); check(not shot.isNull(),"Qt screenshot failed"); check(shot.save(str(evidence/"qt-single-source.png")),"could not save Qt evidence")
        old_id=window.bridge.active_conversation_id; window.bridge.new_conversation(); app.processEvents(); check(window.bridge.active_conversation_id!=old_id,"new conversation did not change session"); check(window.chat_frame.isVisible(),"new conversation hid chat"); check(window.composer.isVisible(),"new conversation hid composer")
        window.close(); app.processEvents()
    print("JARVIS QT SINGLE-SOURCE UI SMOKE: PASS")

if __name__=="__main__": main()
