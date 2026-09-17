"""Integrated production candidate UI for JARVIS Desktop.

Keeps the existing runtime/bridge/updater while applying the approved dark
cinematic Qt composition used during UI iteration.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from gui_qt_dev import JarvisGUI as DevJarvisGUI
from gui_qt_reference import Composer, SceneCanvas
from gui_qt_reference_v2 import RollingCaption, _shadow
from jarvis_qt_composer_patch import install_composer_polish

TEXT = "#edf8ff"
MUTED = "#8da7b6"
CYAN = "#61dfff"


class JarvisGUI(DevJarvisGUI):
    """Approved V4-style UI wired to the real JARVIS runtime."""

    def __init__(self, logger, actions, core):
        self._history_widgets = {}
        super().__init__(logger, actions, core)
        self.setWindowTitle("JARVIS")
        self.composer.plus.clicked.connect(self._show_plus_menu)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.sidebar = self._build_sidebar()
        shell.addWidget(self.sidebar)

        main = QFrame()
        main.setObjectName("mainSurface")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        stage = QWidget()
        stage.setObjectName("stage")
        stack = QStackedLayout(stage)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self.scene = SceneCanvas()
        stack.addWidget(self.scene)

        overlay = QWidget()
        overlay.setObjectName("workspaceOverlay")
        overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ol = QVBoxLayout(overlay)
        ol.setContentsMargins(24, 8, 24, 18)
        ol.setSpacing(10)

        self.topbar = self._build_topbar()
        ol.addWidget(self.topbar)
        ol.addStretch(6)

        caption_row = QHBoxLayout()
        caption_row.addStretch(1)
        self.caption = RollingCaption()
        caption_row.addWidget(self.caption)
        caption_row.addStretch(1)
        ol.addLayout(caption_row)
        ol.addStretch(1)

        self.transcript_frame = QFrame()
        self.transcript_frame.setObjectName("transcriptFrame")
        self.transcript_frame.setMinimumHeight(250)
        self.transcript_frame.setMaximumHeight(390)
        transcript_layout = QVBoxLayout(self.transcript_frame)
        transcript_layout.setContentsMargins(14, 9, 14, 8)

        self.transcript = QScrollArea()
        self.transcript.setObjectName("transcript")
        self.transcript.setWidgetResizable(True)
        self.transcript.setFrameShape(QFrame.Shape.NoFrame)
        self.message_host = QWidget()
        self.message_host.setObjectName("messageHost")
        self.message_layout = QVBoxLayout(self.message_host)
        self.message_layout.setContentsMargins(2, 2, 2, 2)
        self.message_layout.setSpacing(8)
        self.message_layout.addStretch(1)
        self.transcript.setWidget(self.message_host)
        transcript_layout.addWidget(self.transcript)
        ol.addWidget(self.transcript_frame)

        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(36, 0, 36, 0)
        self.composer = Composer()
        self.composer.setMinimumWidth(540)
        self.composer.setMaximumWidth(980)
        _shadow(self.composer, blur=30, alpha=120, y=8)
        composer_row.addStretch(1)
        composer_row.addWidget(self.composer, 1)
        composer_row.addStretch(1)
        ol.addLayout(composer_row)

        mode_row = QHBoxLayout()
        mode_row.addStretch(1)
        mode_row.addWidget(self._build_mode_bar())
        mode_row.addStretch(1)
        ol.addLayout(mode_row)

        stack.addWidget(overlay)
        stack.setCurrentWidget(overlay)
        overlay.raise_()

        main_layout.addWidget(stage, 1)
        shell.addWidget(main, 1)
        self.setStyleSheet(self._stylesheet_integrated())

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(60)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(12)
        layout.addStretch(1)

        self.status_label = QLabel("ONLINE")
        self.status_label.setObjectName("onlineStatus")
        glow = QGraphicsDropShadowEffect(self.status_label)
        glow.setBlurRadius(18)
        glow.setOffset(0, 0)
        glow.setColor(QColor("#55ff9a"))
        self.status_label.setGraphicsEffect(glow)
        layout.addWidget(self.status_label)

        self.update_button = QPushButton("↑")
        self.update_button.setObjectName("updateButtonIntegrated")
        self.update_button.setFixedSize(44, 44)
        self.update_button.setToolTip("Verificar atualização")
        layout.addWidget(self.update_button)
        return bar

    def _build_sidebar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(310)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 20, 18, 16)
        layout.setSpacing(10)

        brand = QHBoxLayout()
        mark = QLabel("◈")
        mark.setObjectName("brandMark")
        mark.setFixedSize(52, 52)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel("JARVIS")
        name.setObjectName("brandTitle")
        brand.addWidget(mark)
        brand.addWidget(name)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(8)

        self.new_button = QPushButton("＋   NOVA CONVERSA")
        self.new_button.setObjectName("primarySideButton")
        self.new_button.setFixedHeight(56)
        layout.addWidget(self.new_button)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("⌕   PESQUISAR CONVERSA")
        self.search.setFixedHeight(52)
        layout.addWidget(self.search)

        heading = QLabel("HISTÓRICO")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self.history = QListWidget()
        self.history.setObjectName("history")
        self.history.setSpacing(6)
        layout.addWidget(self.history, 1)

        footer = QHBoxLayout()
        self.settings_button = QPushButton("⚙")
        self.help_button = QPushButton("?")
        for button in (self.settings_button, self.help_button):
            button.setObjectName("footerButton")
            button.setFixedSize(42, 38)
        footer.addWidget(self.settings_button)
        footer.addWidget(self.help_button)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.new_button.clicked.connect(self.bridge.new_conversation)
        self.search.textChanged.connect(self._filter_history)
        return panel

    def _set_conversations(self, rows: list) -> None:
        selected = self.bridge.active_conversation_id
        self.history.clear()
        self._history_widgets.clear()
        for row in rows:
            cid = int(row.get("id"))
            title = str(row.get("title") or "Nova conversa")
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cid)
            item.setSizeHint(QSize(0, 60))
            self.history.addItem(item)

            card = QWidget()
            card.setObjectName("historyRow")
            lay = QHBoxLayout(card)
            lay.setContentsMargins(13, 4, 4, 4)
            lay.setSpacing(7)
            label = QLabel(title)
            label.setObjectName("historyRowTitle")
            label.setToolTip(title)
            lay.addWidget(label, 1)
            more = QPushButton("⋮")
            more.setObjectName("historyMenuButton")
            more.setFixedSize(36, 36)
            lay.addWidget(more)

            label.mousePressEvent = lambda event, conversation_id=cid: self.bridge.load_conversation(conversation_id)
            more.clicked.connect(lambda checked=False, conversation_id=cid, title_label=label, button=more: self._history_menu(conversation_id, title_label, button))
            self.history.setItemWidget(item, card)
            item.setSelected(cid == selected)
            self._history_widgets[cid] = (item, card, label)
        self._filter_history(self.search.text())

    def _filter_history(self, text: str) -> None:
        needle = str(text or "").casefold().strip()
        for index in range(self.history.count()):
            item = self.history.item(index)
            card = self.history.itemWidget(item)
            label = card.findChild(QLabel, "historyRowTitle") if card else None
            title = label.text() if label else ""
            item.setHidden(bool(needle and needle not in title.casefold()))

    def _history_menu(self, conversation_id: int, label: QLabel, button: QPushButton) -> None:
        menu = QMenu(self)
        rename_action = menu.addAction("Renomear")
        copy_action = menu.addAction("Copiar tudo")
        menu.addSeparator()
        delete_action = menu.addAction("Apagar")
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if chosen == rename_action:
            value, ok = QInputDialog.getText(self, "Renomear conversa", "Novo nome:", text=label.text())
            if ok and value.strip() and self.bridge.memory.rename_conversation(conversation_id, value.strip()):
                self.bridge.refresh_conversations()
        elif chosen == copy_action:
            rows = self.bridge.memory.load_messages(conversation_id, limit=5000)
            QApplication.clipboard().setText("\n\n".join(f"{r.get('sender','')}: {r.get('message','')}" for r in rows))
        elif chosen == delete_action:
            answer = QMessageBox.question(self, "Apagar conversa", f"Apagar '{label.text()}' permanentemente?")
            if answer == QMessageBox.StandardButton.Yes and self.bridge.memory.delete_conversation(conversation_id):
                self.bridge.active_conversation_id = self.bridge.memory.get_or_create_active_conversation()
                self.bridge.refresh_conversations()
                self.bridge.load_active_conversation()

    def _load_conversation(self, conversation_id: int, title: str, rows: list) -> None:
        super()._load_conversation(conversation_id, title, rows)
        self.setWindowTitle("JARVIS")

    def _set_status(self, text: str, color: str) -> None:
        if not hasattr(self, "status_label"):
            return
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color}; background:transparent; border:none; font:900 13px 'Segoe UI';")
        effect = self.status_label.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setColor(QColor(color))

    def _response_started(self, generation: int) -> None:
        super()._response_started(generation)
        self._set_status("PENSANDO", "#ffd84c")

    def _response_chunk(self, generation: int, text: str) -> None:
        super()._response_chunk(generation, text)
        self._set_status("FALANDO", "#61dfff")

    def _response_finished(self, generation: int, text: str) -> None:
        super()._response_finished(generation, text)
        self._set_status("ONLINE", "#55ff9a")

    def _response_failed(self, generation: int, text: str) -> None:
        super()._response_failed(generation, text)
        self._set_status("ONLINE", "#55ff9a")

    def _show_plus_menu(self) -> None:
        menu = QMenu(self)
        files = menu.addMenu("Arquivos")
        files.addAction("Anexar arquivo").triggered.connect(self._attach_file)
        images = menu.addMenu("Imagens")
        images.addAction("Anexar imagem").triggered.connect(lambda: self._attach_file("Imagens (*.png *.jpg *.jpeg *.webp *.bmp)"))
        images.addAction("Capturar tela inteira").triggered.connect(self._capture_screen)
        audio = menu.addMenu("Áudio")
        audio.addAction("Anexar áudio").triggered.connect(lambda: self._attach_file("Áudio (*.wav *.mp3 *.m4a *.ogg *.flac)"))
        tasks = menu.addMenu("Tarefas")
        tasks.addAction("Criar lembrete").triggered.connect(self._create_reminder)
        tools = menu.addMenu("Ferramentas")
        tools.addAction("Calculadora").triggered.connect(lambda: self._open_tool("calc"))
        tools.addAction("Terminal").triggered.connect(lambda: self._open_tool("terminal"))
        tools.addAction("Navegador").triggered.connect(lambda: self._open_tool("browser"))
        tools.addAction("Bloco de notas").triggered.connect(lambda: self._open_tool("notepad"))
        quick = menu.addMenu("Ações rápidas")
        for text in ("Resumir", "Traduzir", "Explicar", "Analisar imagem", "Extrair informações", "Reescrever"):
            quick.addAction(text).triggered.connect(lambda checked=False, prefix=text: self._insert_quick(prefix))
        menu.exec(self.composer.plus.mapToGlobal(self.composer.plus.rect().topLeft()))

    def _attach_file(self, file_filter: str = "Todos os arquivos (*.*)") -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Anexar ao JARVIS", "", file_filter)
        if path:
            current = self.composer.editor.toPlainText().strip()
            addition = f"[Arquivo anexado: {path}]"
            self.composer.editor.setPlainText((current + "\n" + addition).strip())
            self.composer.editor.setFocus()

    def _capture_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            QMessageBox.warning(self, "Captura de tela", "Nenhuma tela disponível.")
            return
        folder = Path(tempfile.gettempdir()) / "JARVIS"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"captura_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        pix = screen.grabWindow(0)
        if pix.save(str(path)):
            current = self.composer.editor.toPlainText().strip()
            self.composer.editor.setPlainText((current + f"\n[Imagem anexada: {path}]").strip())
        else:
            QMessageBox.warning(self, "Captura de tela", "Não foi possível salvar a captura.")

    def _create_reminder(self) -> None:
        task, ok = QInputDialog.getText(self, "Novo lembrete", "O que devo lembrar?")
        if not ok or not task.strip():
            return
        due, ok = QInputDialog.getText(self, "Novo lembrete", "Quando? (AAAA-MM-DD HH:MM)")
        if not ok or not due.strip():
            return
        try:
            parsed = datetime.strptime(due.strip(), "%Y-%m-%d %H:%M")
            self.bridge.memory.create_reminder(task.strip(), parsed)
            QMessageBox.information(self, "Lembrete", "Lembrete criado.")
        except ValueError:
            QMessageBox.warning(self, "Lembrete", "Use o formato AAAA-MM-DD HH:MM.")

    def _open_tool(self, kind: str) -> None:
        try:
            if kind == "browser":
                webbrowser.open("https://www.google.com")
            elif os.name == "nt" and kind == "calc":
                subprocess.Popen(["calc.exe"])
            elif os.name == "nt" and kind == "terminal":
                subprocess.Popen(["cmd.exe"])
            elif os.name == "nt" and kind == "notepad":
                subprocess.Popen(["notepad.exe"])
            else:
                QMessageBox.information(self, "JARVIS", "Ferramenta disponível no Windows.")
        except Exception as exc:
            QMessageBox.warning(self, "JARVIS", str(exc))

    def _insert_quick(self, prefix: str) -> None:
        current = self.composer.editor.toPlainText().strip()
        self.composer.editor.setPlainText(f"{prefix}: {current}")
        self.composer.editor.setFocus()

    @staticmethod
    def _stylesheet_integrated() -> str:
        return f"""
        QMainWindow, QWidget#root {{ background:#02070d; color:{TEXT}; }}
        QFrame#mainSurface, QWidget#stage, QWidget#workspaceOverlay {{ background:transparent; }}
        QFrame#sidebar {{ background:rgba(2,10,17,198); border-right:1px solid rgba(73,126,151,110); }}
        QFrame#topbar {{ background:rgba(0,0,0,0); border:none; }}
        QLabel#onlineStatus {{ color:#55ff9a; background:transparent; border:none; font:900 13px 'Segoe UI'; }}
        QLabel#brandMark {{ color:#6fe5ff; font:700 27px 'Segoe UI'; background:rgba(8,35,49,135); border:1px solid rgba(85,215,255,120); border-radius:26px; }}
        QLabel#brandTitle {{ color:#effaff; font:800 27px 'Segoe UI'; }}
        QLabel#sectionTitle {{ color:{MUTED}; font:700 11px 'Segoe UI'; letter-spacing:1px; padding-top:8px; }}
        QPushButton {{ background:rgba(7,23,37,140); border:1px solid rgba(56,87,105,100); border-radius:12px; color:{TEXT}; padding:8px 11px; font:600 12px 'Segoe UI'; }}
        QPushButton:hover {{ background:rgba(13,42,61,180); border-color:rgba(91,210,249,170); }}
        QPushButton#primarySideButton {{ text-align:left; padding-left:18px; font:800 13px 'Segoe UI'; color:#dff8ff; background:rgba(7,31,47,165); border:1px solid rgba(71,201,246,120); }}
        QPushButton#updateButtonIntegrated {{ color:#70e7ff; background:rgba(3,15,24,175); border:1px solid rgba(75,217,255,155); border-radius:22px; font:900 24px 'Segoe UI'; padding:0; }}
        QLineEdit#search {{ background:rgba(6,19,30,145); border:1px solid rgba(74,112,132,105); border-radius:12px; padding:0 15px; color:#eaf8ff; font:600 12px 'Segoe UI'; }}
        QListWidget#history {{ background:transparent; border:none; outline:none; }}
        QListWidget#history::item {{ background:transparent; border:none; min-height:60px; }}
        QWidget#historyRow {{ background:rgba(7,20,30,96); border:1px solid rgba(87,119,136,42); border-radius:12px; }}
        QWidget#historyRow:hover {{ background:rgba(12,38,54,165); border:1px solid rgba(78,194,232,90); }}
        QLabel#historyRowTitle {{ color:#eaf8ff; font:700 13px 'Segoe UI'; background:transparent; }}
        QPushButton#historyMenuButton {{ color:#91e7ff; background:transparent; border:none; font:900 22px 'Segoe UI'; padding:0; }}
        QFrame#transcriptFrame {{ background:rgba(3,10,15,105); border:1px solid rgba(93,156,181,55); border-radius:17px; }}
        QScrollArea#transcript, QWidget#messageHost {{ background:transparent; border:none; }}
        QFrame#captionGlass {{ background:rgba(0,0,0,25); border:none; }}
        QLabel#captionText {{ color:#ffd84c; background:transparent; font:800 16px 'Segoe UI'; }}
        QFrame#composer {{ background:rgba(8,17,23,172); border:1px solid rgba(92,193,228,110); border-radius:25px; }}
        QTextEdit#composerEditor {{ background:transparent; border:none; color:{TEXT}; padding:7px 5px; font:14px 'Segoe UI'; }}
        QFrame#modeBar {{ background:rgba(2,11,18,115); border:1px solid rgba(58,96,118,55); border-radius:10px; }}
        QCheckBox {{ color:#92aebd; font:11px 'Segoe UI'; spacing:5px; }}
        QMenu {{ background:rgba(5,14,22,248); color:#eaf8ff; border:1px solid rgba(81,177,213,100); padding:6px; font:600 12px 'Segoe UI'; }}
        QMenu::item {{ padding:8px 24px 8px 12px; border-radius:7px; }}
        QMenu::item:selected {{ background:rgba(35,130,170,125); }}
        """


__all__ = ["JarvisGUI"]
