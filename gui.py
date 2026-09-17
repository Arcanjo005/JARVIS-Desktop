from __future__ import annotations
import os, subprocess, sys, threading, webbrowser
from pathlib import Path
from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication,QFileDialog,QFrame,QGraphicsDropShadowEffect,QGraphicsOpacityEffect,QHBoxLayout,QInputDialog,QLabel,QLineEdit,QListWidget,QListWidgetItem,QMainWindow,QMenu,QMessageBox,QPushButton,QScrollArea,QStackedLayout,QTextEdit,QVBoxLayout,QWidget)
from github_updater import GitHubReleaseUpdater
from jarvis_qt_bridge import JarvisQtBridge
from jarvis_version import BUILD,CHANNEL,VERSION

REQUIRED_UI_ASSETS=("workspace_bg.jpg","sphere_3d.png","update_neon_arrow.png","jarvis_logo.png","plus.png","mic.png","send.png")
FORBIDDEN_VISUAL_MODULES=("gui_qt_dev","gui_qt_integrated","gui_qt_reference","gui_qt_reference_v2","gui_reference_exact","gui_reference_exact_v2","gui_reference_exact_v3","gui_reference_final_1311","gui_reference_final_1312","gui_reference_release_1312","jarvis_reference_orb","jarvis_reference_scene_139","jarvis_visual_runtime","voice_overlay_qt","jarvis_voice_overlay_139")

def _root(): return Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
def asset_path(name):
    roots=([Path(sys._MEIPASS)/"assets"] if getattr(sys,"_MEIPASS",None) else [])+[_root()/"assets"]
    for root in roots:
        p=root/name
        if p.is_file(): return p
    raise FileNotFoundError(f"Approved UI asset missing: assets/{name}")
def required_asset_paths(): return {x:asset_path(x) for x in REQUIRED_UI_ASSETS}
def validate_approved_assets():
    paths=required_asset_paths(); bad=[n for n,p in paths.items() if p.stat().st_size<128]
    if bad: raise RuntimeError("Invalid approved UI assets: "+", ".join(bad))
    return paths
def _pix(name):
    p=QPixmap(str(asset_path(name)))
    if p.isNull(): raise RuntimeError(f"Approved UI asset cannot be decoded: assets/{name}")
    return p

class Scene(QWidget):
    def __init__(self):
        super().__init__(); self.bg_src=_pix("workspace_bg.jpg"); self.orb_src=_pix("sphere_3d.png"); self.bg=QLabel(self); self.orb=QLabel(self)
        self.bg.setObjectName("workspaceBackground"); self.orb.setObjectName("approvedSphere")
    def resizeEvent(self,e):
        super().resizeEvent(e)
        if self.width()<4:return
        self.bg.setGeometry(self.rect()); s=self.bg_src.scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation); self.bg.setPixmap(s.copy(max(0,(s.width()-self.width())//2),max(0,(s.height()-self.height())//2),self.width(),self.height()))
        d=int(max(230,min(500,min(self.width(),self.height())*.46))); self.orb.setGeometry((self.width()-d)//2,max(48,int(self.height()*.39-d/2)),d,d); self.orb.setPixmap(self.orb_src.scaled(d,d,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)); self.orb.raise_()

class Ring(QWidget):
    def __init__(self): super().__init__(); self.value=0; self.setFixedSize(44,44)
    def setValue(self,v): self.value=max(0,min(100,int(v))); self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setPen(QPen(QColor("#30e1ff"),3)); p.drawArc(QRectF(4,4,36,36),90*16,-int(360*16*self.value/100)); p.setPen(QColor("#dffbff")); p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,f"{self.value}%")

class Composer(QFrame):
    submit=Signal(str); manual_voice=Signal()
    def __init__(self):
        super().__init__(); self.setObjectName("composer"); self.setFixedHeight(66); row=QHBoxLayout(self); row.setContentsMargins(8,7,8,7)
        self.plus,self.mic,self.send=QPushButton(),QPushButton(),QPushButton(); self.editor=QTextEdit(); self.editor.setObjectName("composerEditor"); self.editor.setPlaceholderText("Mensagem para o JARVIS..."); self.editor.setAcceptRichText(False)
        for b,n in ((self.plus,"plus.png"),(self.mic,"mic.png"),(self.send,"send.png")): b.setIcon(QIcon(str(asset_path(n)))); b.setIconSize(QSize(27,27)); b.setFixedSize(46,46); b.setObjectName("composerIconButton")
        row.addWidget(self.plus); row.addWidget(self.editor,1); row.addWidget(self.mic); row.addWidget(self.send); self.send.clicked.connect(self._send); self.mic.clicked.connect(self.manual_voice.emit); self.editor.installEventFilter(self)
    def eventFilter(self,o,e):
        if o is self.editor and e.type()==QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and not e.modifiers()&Qt.KeyboardModifier.ShiftModifier: self._send(); return True
        return super().eventFilter(o,e)
    def _send(self):
        t=self.editor.toPlainText().strip()
        if t:self.editor.clear();self.submit.emit(t)

class HistoryRow(QWidget):
    selected=Signal(int)
    def __init__(self,owner,row):
        super().__init__(); self.owner=owner; self.cid=int(row["id"]); self.setObjectName("historyRow"); box=QHBoxLayout(self); box.setContentsMargins(8,4,4,4); title=QPushButton(str(row.get("title") or "Nova conversa")); title.setObjectName("historyTitle"); more=QPushButton("⋮"); more.setObjectName("historyMenu"); more.setFixedWidth(30); title.clicked.connect(lambda:self.selected.emit(self.cid)); more.clicked.connect(self.menu); box.addWidget(title,1); box.addWidget(more)
    def menu(self):
        m=QMenu(self); r=m.addAction("Renomear"); d=m.addAction("Apagar"); c=m.addAction("Copiar tudo"); a=m.exec(self.mapToGlobal(QPoint(self.width()-34,self.height())))
        if a is r:self.owner.rename_conversation(self.cid)
        elif a is d:self.owner.delete_conversation(self.cid)
        elif a is c:self.owner.copy_conversation(self.cid)

class JarvisGUI(QMainWindow):
    voice_state=Signal(str,str); voice_command=Signal(str); voice_caption=Signal(str); voice_live=Signal(str); voice_end=Signal(); update_ready=Signal(object); update_progress=Signal(int); update_error=Signal(str); update_done=Signal(str)
    def __init__(self,logger,actions,core):
        validate_approved_assets(); self.app=QApplication.instance() or QApplication(sys.argv); super().__init__(); self.logger=logger; self.actions=actions; self.core=core; self.project_dir=str(_root()); self.voice_engine=None; self._stream=""; self._bubble=None; self._update=None; self._pulse=False; self.bridge=JarvisQtBridge(core,logger,self)
        self.setObjectName("jarvisWindow"); self.setWindowTitle(f"JARVIS Desktop {VERSION}"); self.resize(1380,850); self.setMinimumSize(1050,680); self._build(); self.setStyleSheet(self._css()); self._wire(); self.bridge.refresh_conversations(); self.bridge.load_active_conversation()
        if os.getenv("JARVIS_QT_DISABLE_AUTO_VOICE")!="1":QTimer.singleShot(2400,self._start_voice)
        if os.getenv("JARVIS_QT_DISABLE_AUTO_UPDATE")!="1":QTimer.singleShot(6000,self.check_update)
    def _build(self):
        root=QWidget(); self.setCentralWidget(root); stack=QStackedLayout(root); stack.setStackingMode(QStackedLayout.StackingMode.StackAll); self.scene=Scene(); stack.addWidget(self.scene); overlay=QWidget(); stack.addWidget(overlay); main=QHBoxLayout(overlay); main.setContentsMargins(0,0,0,0)
        self.sidebar=QFrame(); self.sidebar.setObjectName("sidebar"); self.sidebar.setFixedWidth(310); side=QVBoxLayout(self.sidebar); brand=QHBoxLayout(); logo=QLabel(); logo.setPixmap(_pix("jarvis_logo.png").scaled(42,42,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)); brand.addWidget(logo); brand.addWidget(QLabel("JARVIS")); brand.addStretch(); side.addLayout(brand); new=QPushButton("+  Nova conversa"); new.clicked.connect(self.bridge.new_conversation); side.addWidget(new); self.search=QLineEdit(); self.search.setPlaceholderText("Buscar conversas..."); side.addWidget(self.search); self.history=QListWidget(); self.history.setObjectName("history"); side.addWidget(self.history,1); side.addWidget(QLabel(f"v{VERSION} • {CHANNEL} • {BUILD}")); main.addWidget(self.sidebar)
        stage=QWidget(); main.addWidget(stage,1); col=QVBoxLayout(stage); col.setContentsMargins(24,16,24,18); top=QHBoxLayout(); top.addStretch(); self.status=QLabel("ONLINE"); self.status.setObjectName("status"); top.addWidget(self.status); self.update_button=QPushButton(); self.update_button.setObjectName("updateButton"); self.update_button.setIcon(QIcon(str(asset_path("update_neon_arrow.png")))); self.update_button.setIconSize(QSize(24,24)); self.update_button.setFixedSize(44,44); top.addWidget(self.update_button); self.ring=Ring(); self.ring.hide(); top.addWidget(self.ring); col.addLayout(top); col.addStretch(2)
        self.caption=QLabel(); self.caption.setObjectName("caption"); self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter); self.caption.setWordWrap(True); shadow=QGraphicsDropShadowEffect(self.caption); shadow.setBlurRadius(7); shadow.setOffset(0,2); shadow.setColor(QColor(0,0,0,245)); self.caption.setGraphicsEffect(shadow); self.caption.hide(); col.addWidget(self.caption)
        self.chat_frame=QFrame(); self.chat_frame.setObjectName("chatFrame"); self.chat_frame.setMinimumHeight(250); self.chat_frame.setMaximumHeight(390); chat=QVBoxLayout(self.chat_frame); self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.messages=QWidget(); self.msg=QVBoxLayout(self.messages); self.msg.addStretch(); self.scroll.setWidget(self.messages); chat.addWidget(self.scroll); col.addWidget(self.chat_frame); self.composer=Composer(); col.addWidget(self.composer)
    def _wire(self):
        b=self.bridge; b.conversations_changed.connect(self._history); b.conversation_loaded.connect(self._loaded); b.user_message_saved.connect(lambda r:self._add(r.get("message",""),True)); b.response_started.connect(self._start_response); b.response_chunk.connect(self._chunk); b.response_finished.connect(self._finish); b.response_failed.connect(lambda g,t:self._fail(t)); b.busy_changed.connect(lambda x:self._status("PENSANDO" if x else "ONLINE")); self.composer.submit.connect(b.send_message); self.composer.manual_voice.connect(self._manual_voice); self.composer.plus.clicked.connect(self._plus); self.search.textChanged.connect(self._filter); self.update_button.clicked.connect(self._update_click)
        self.voice_state.connect(lambda s,d:self._status(s)); self.voice_command.connect(b.send_message); self.voice_caption.connect(self._caption); self.voice_live.connect(lambda t:self._caption("VOCÊ: "+t)); self.voice_end.connect(lambda:self._status("ONLINE")); self.update_ready.connect(self._ready); self.update_progress.connect(self.ring.setValue); self.update_error.connect(self._update_fail); self.update_done.connect(self._update_finish); self.pulse=QTimer(self); self.pulse.timeout.connect(self._pulse_step)
    def _status(self,s):
        s={"AGUARDANDO":"ONLINE","PREPARANDO":"PENSANDO","PROCESSANDO":"PENSANDO","SEM_MICROFONE":"SEM MICROFONE"}.get(str(s or "ONLINE").upper(),str(s or "ONLINE").upper()); color="#55ff9a" if s=="ONLINE" else ("#ff6e75" if s in ("ERRO","SEM MICROFONE") else "#61dfff"); self.status.setText(s); self.status.setStyleSheet(f"color:{color};background:transparent;border:none;font-weight:900")
    def _add(self,text,user=False):
        frame=QFrame(); frame.setObjectName("userBubble" if user else "jarvisBubble"); box=QVBoxLayout(frame); who=QLabel("VOCÊ" if user else "JARVIS"); body=QLabel(str(text)); body.setWordWrap(True); body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); box.addWidget(who); box.addWidget(body); self.msg.insertWidget(self.msg.count()-1,frame); QTimer.singleShot(0,lambda:self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())); return body
    def _clear(self):
        while self.msg.count()>1:
            w=self.msg.takeAt(0).widget()
            if w:w.deleteLater()
    def _loaded(self,cid,title,rows):
        self._clear()
        for r in rows:self._add(r.get("message",""),bool(r.get("is_user")))
    def _start_response(self,g):self._stream="";self._bubble=self._add("",False);self._status("PENSANDO")
    def _chunk(self,g,t):self._stream+=str(t or "");self._bubble.setText(self._stream) if self._bubble else None;self._caption(self._stream)
    def _finish(self,g,t):
        if self._bubble:self._bubble.setText(str(t));self._bubble=None
        self._stream="";self._caption(t);self._speak(t);self._status("FALANDO" if self.voice_engine else "ONLINE")
    def _fail(self,t):
        if self._bubble:self._bubble.setText(t);self._bubble=None
        self._status("ERRO")
    def _caption(self,t):
        t=" ".join(str(t or "").split())[-190:]; self.caption.setText(t); self.caption.setVisible(bool(t))
        if t:QTimer.singleShot(6500,self.caption.hide)
    def _history(self,rows):
        self._rows=list(rows or []);self.history.clear()
        for r in self._rows:
            item=QListWidgetItem();item.setSizeHint(QSize(0,64));w=HistoryRow(self,r);w.selected.connect(self.bridge.load_conversation);self.history.addItem(item);self.history.setItemWidget(item,w)
        self._filter(self.search.text())
    def _filter(self,t):
        t=str(t or "").casefold()
        for i,r in enumerate(getattr(self,"_rows",[])):self.history.item(i).setHidden(bool(t and t not in str(r.get("title","")).casefold()))
    def rename_conversation(self,cid):
        title,ok=QInputDialog.getText(self,"Renomear","Novo nome:",text=self.bridge.memory.get_conversation_title(cid))
        if ok and self.bridge.memory.rename_conversation(cid,title):self.bridge.refresh_conversations()
    def delete_conversation(self,cid):
        if QMessageBox.question(self,"Apagar","Apagar esta conversa?")==QMessageBox.StandardButton.Yes:self.bridge.memory.delete_conversation(cid);self.bridge.new_conversation() if cid==self.bridge.active_conversation_id else self.bridge.refresh_conversations()
    def copy_conversation(self,cid):QApplication.clipboard().setText("\n\n".join(f"{r.get('sender','')}: {r.get('message','')}" for r in self.bridge.memory.load_messages(cid,5000)))
    def _plus(self):
        m=QMenu(self)
        for section in ("Arquivos","Imagens","Áudio","Tarefas","Ferramentas","Ações rápidas"):
            sm=m.addMenu(section);sm.addAction("Abrir").triggered.connect(lambda checked=False,s=section:self._plus_action(s))
        m.exec(self.composer.plus.mapToGlobal(QPoint(0,self.composer.plus.height())))
    def _plus_action(self,s):
        if s in ("Arquivos","Imagens","Áudio"):
            p,_=QFileDialog.getOpenFileName(self,"Anexar ao JARVIS");self.composer.editor.setPlainText((self.composer.editor.toPlainText()+f"\n[Arquivo anexado: {p}]").strip()) if p else None
        elif s=="Tarefas":self.composer.editor.setPlainText("Crie um lembrete: "+self.composer.editor.toPlainText())
        elif s=="Ferramentas" and os.name=="nt":subprocess.Popen(["cmd.exe"])
        else:self.composer.editor.setPlainText("Resuma, traduza ou explique: "+self.composer.editor.toPlainText())
    def _start_voice(self):
        try:
            from voice_engine import VoiceEngine
            self.voice_engine=VoiceEngine(project_dir=self.project_dir,logger=self.logger,on_state=lambda s,d:self.voice_state.emit(s,d),on_command=lambda t:self.voice_command.emit(t),on_caption=lambda t:self.voice_caption.emit(t),on_live_transcript=lambda t:self.voice_live.emit(t),on_tts_start=lambda t:self.voice_state.emit("FALANDO",t),on_tts_end=lambda:self.voice_end.emit());self.voice_engine.start()
        except Exception as e:
            self.voice_engine=None
            try:self.logger.warning(f"Voz Qt indisponível: {e}","VOICE")
            except Exception:pass
    def _manual_voice(self):
        if not self.voice_engine:self._start_voice()
        if self.voice_engine:self.voice_engine.trigger_manual();self._status("OUVINDO")
    def _speak(self,t):
        try:self.voice_engine.speak(t) if self.voice_engine else None
        except Exception:self._status("ONLINE")
    def _updater(self):return GitHubReleaseUpdater(app_dir=self.project_dir,current_version=VERSION,current_build=BUILD,channel=CHANNEL,logger=self.logger)
    def check_update(self):
        def work():
            try:
                info=self._updater().check()
                if info:self.update_ready.emit(info)
            except Exception as e:self.update_error.emit(str(e))
        threading.Thread(target=work,daemon=True,name="JARVIS-QT-UPDATE-CHECK").start()
    def _ready(self,info):self._update=info;self.pulse.start(620);self.update_button.setToolTip("Atualização disponível")
    def _pulse_step(self):
        fx=self.update_button.graphicsEffect()
        if not isinstance(fx,QGraphicsOpacityEffect):fx=QGraphicsOpacityEffect(self.update_button);self.update_button.setGraphicsEffect(fx)
        self._pulse=not self._pulse;fx.setOpacity(.45 if self._pulse else 1)
    def _update_click(self):
        if not self._update:self.check_update();return
        self.pulse.stop();self.update_button.hide();self.ring.show();self.ring.setValue(0)
        def work():
            try:self.update_done.emit(str(self._updater().download(self._update,progress=lambda d,t:self.update_progress.emit(int(d*100/max(1,t))))))
            except Exception as e:self.update_error.emit(str(e))
        threading.Thread(target=work,daemon=True,name="JARVIS-QT-UPDATER").start()
    def _update_fail(self,t):self.ring.hide();self.update_button.show();self.update_button.setToolTip("Falha: "+str(t)[:100]);self._status("ONLINE")
    def _update_finish(self,p):
        self.ring.setValue(100);QMessageBox.information(self,"JARVIS","Atualização baixada. O instalador será aberto.")
        try:os.startfile(p)
        except Exception:pass
    def closeEvent(self,e):
        try:self.voice_engine.stop() if self.voice_engine else None
        except Exception:pass
        self.bridge.close();super().closeEvent(e)
    def run(self):self.show();return self.app.exec()
    @staticmethod
    def _css():return """QMainWindow#jarvisWindow,QWidget{color:#edf8ff;background:transparent}QMainWindow#jarvisWindow{background:#02070d}QFrame#sidebar{background:rgba(2,10,17,198);border-right:1px solid rgba(73,126,151,110)}QPushButton,QLineEdit{background:rgba(7,23,37,145);border:1px solid rgba(72,117,138,100);border-radius:11px;color:#edf8ff;padding:8px}QPushButton:hover{border-color:#61dfff}QListWidget#history{background:transparent;border:none}QWidget#historyRow{background:rgba(7,20,30,105);border-radius:11px}QPushButton#historyTitle,QPushButton#historyMenu{background:transparent;border:none;text-align:left}QPushButton#historyMenu{font-size:20px}QPushButton#updateButton{border:1px solid rgba(75,217,255,125);border-radius:22px;padding:0}QLabel#caption{color:#ffd84c;background:rgba(0,0,0,55);padding:8px;font-size:16px;font-weight:800}QFrame#chatFrame{background:rgba(3,10,15,105);border:1px solid rgba(93,156,181,55);border-radius:17px}QFrame#userBubble{background:rgba(14,30,39,180);border-radius:12px}QFrame#jarvisBubble{background:rgba(4,12,18,145);border-radius:12px}QFrame#composer{background:rgba(8,17,23,180);border:1px solid rgba(92,193,228,110);border-radius:25px}QTextEdit#composerEditor{background:transparent;border:none;color:#edf8ff;padding:7px}QPushButton#composerIconButton{background:transparent;border:none;border-radius:22px;padding:0}QMenu{background:#07121b;color:#eaf8ff;border:1px solid #28556a;padding:5px}QMenu::item{padding:7px 20px}QMenu::item:selected{background:#164a60}"""

__all__=["JarvisGUI","REQUIRED_UI_ASSETS","FORBIDDEN_VISUAL_MODULES","asset_path","required_asset_paths","validate_approved_assets"]
