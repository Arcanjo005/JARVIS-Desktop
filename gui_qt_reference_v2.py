"""Second-pass Qt composition for the JARVIS reference rebuild.

This file owns the new window composition.  It deliberately reuses only the
small Qt components from ``gui_qt_reference`` and the runtime bridge; it does not
inherit the legacy CustomTkinter hierarchy.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui_qt_reference import Composer, MessageBubble, SceneCanvas
from jarvis_qt_bridge import JarvisQtBridge

APP_BG = "#02070d"
PANEL_BG = "rgba(2, 11, 19, 240)"
LOWER_BG = "rgba(1, 8, 14, 246)"
GLASS = "rgba(5, 20, 32, 222)"
BORDER = "#16384f"
BORDER_BRIGHT = "#2a7298"
CYAN = "#36c8ff"
CYAN_SOFT = "#82e2ff"
TEXT = "#edf8ff"
MUTED = "#7899aa"


def _shadow(widget: QWidget, blur: int = 26, alpha: int = 95, y: int = 7) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


class JarvisGUI(QMainWindow):
    """Reference-driven Qt shell with chat permanently reachable."""

    def __init__(self, logger, actions, core):
        self._owned_app = QApplication.instance() is None
        self.app = QApplication.instance() or QApplication(sys.argv)
        super().__init__()
        self.logger = logger
        self.actions = actions
        self.core = core
        self.bridge = JarvisQtBridge(core=core, logger=logger)
        self._stream_generation = 0
        self._stream_text = ""
        self._stream_bubble: MessageBubble | None = None

        self.setObjectName("jarvisWindow")
        self.setWindowTitle("JARVIS // Desktop Intelligence")
        self.resize(1440, 900)
        self.setMinimumSize(1040, 680)
        self._build_ui()
        self._connect_bridge()
        self.bridge.refresh_conversations()
        self.bridge.load_active_conversation()

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

        self.topbar = self._build_topbar()
        main_layout.addWidget(self.topbar)

        self.scene = SceneCanvas()
        main_layout.addWidget(self.scene, 1)

        lower = QFrame()
        lower.setObjectName("lowerSurface")
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(20, 8, 20, 12)
        lower_layout.setSpacing(8)

        self.transcript_frame = QFrame()
        self.transcript_frame.setObjectName("transcriptFrame")
        self.transcript_frame.setMinimumHeight(130)
        self.transcript_frame.setMaximumHeight(245)
        transcript_layout = QVBoxLayout(self.transcript_frame)
        transcript_layout.setContentsMargins(10, 8, 10, 8)

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
        lower_layout.addWidget(self.transcript_frame)

        self.composer = Composer()
        _shadow(self.composer)
        lower_layout.addWidget(self.composer)
        lower_layout.addWidget(self._build_mode_bar())

        main_layout.addWidget(lower)
        shell.addWidget(main, 1)
        self.setStyleSheet(self._stylesheet())

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(50)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 6, 14, 6)
        layout.setSpacing(8)

        title = QLabel("JARVIS")
        title.setObjectName("topTitle")
        subtitle = QLabel("DESKTOP INTELLIGENCE")
        subtitle.setObjectName("topSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)

        self.update_button = QPushButton("↻")
        self.update_button.setObjectName("updateButton")
        self.update_button.setToolTip("Verificar atualização")
        self.update_button.setFixedSize(40, 36)
        layout.addWidget(self.update_button)
        return bar

    def _build_sidebar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(286)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 20, 18, 16)
        layout.setSpacing(10)

        brand = QHBoxLayout()
        mark = QLabel("◇")
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

        self.new_button = QPushButton("＋   Nova conversa")
        self.new_button.setObjectName("primarySideButton")
        self.new_button.setFixedHeight(46)
        layout.addWidget(self.new_button)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("⌕  Buscar conversas...")
        self.search.setFixedHeight(40)
        layout.addWidget(self.search)

        heading = QLabel("HISTÓRICO")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.history = QListWidget()
        self.history.setObjectName("history")
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
        self.history.itemActivated.connect(self._history_activated)
        self.history.itemClicked.connect(self._history_activated)
        return panel

    def _build_mode_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("modeBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(13)
        self.mode_checks: dict[str, QCheckBox] = {}
        for text, checked in (
            ("JARVIS fala", True),
            ("Legenda na tela", True),
            ("Modo Rápido", False),
            ("Modo Detalhado", False),
            ("Enter para enviar", True),
        ):
            check = QCheckBox(text)
            check.setChecked(checked)
            self.mode_checks[text] = check
            layout.addWidget(check)
        layout.addStretch(1)
        return bar

    def _connect_bridge(self) -> None:
        self.composer.submitted.connect(self.bridge.send_message)
        self.bridge.conversations_changed.connect(self._set_conversations)
        self.bridge.conversation_loaded.connect(self._load_conversation)
        self.bridge.user_message_saved.connect(self._append_row)
        self.bridge.response_started.connect(self._response_started)
        self.bridge.response_chunk.connect(self._response_chunk)
        self.bridge.response_finished.connect(self._response_finished)
        self.bridge.response_failed.connect(self._response_failed)
        self.bridge.busy_changed.connect(self._busy_changed)

    def _clear_messages(self) -> None:
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._stream_bubble = None
        self._stream_text = ""

    def _append_row(self, row: dict) -> MessageBubble:
        is_user = bool(row.get("is_user"))
        bubble = MessageBubble(
            row.get("sender", "JARVIS"),
            row.get("message", ""),
            is_user,
        )
        bubble.setMaximumWidth(760)
        alignment = Qt.AlignmentFlag.AlignRight if is_user else Qt.AlignmentFlag.AlignLeft
        self.message_layout.insertWidget(
            self.message_layout.count() - 1,
            bubble,
            0,
            alignment,
        )
        QTimer.singleShot(0, self._scroll_to_bottom)
        return bubble

    def _scroll_to_bottom(self) -> None:
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_conversations(self, rows: list) -> None:
        selected = self.bridge.active_conversation_id
        self.history.blockSignals(True)
        self.history.clear()
        for row in rows:
            conversation_id = int(row.get("id"))
            item = QListWidgetItem(str(row.get("title") or "Nova conversa"))
            item.setData(Qt.ItemDataRole.UserRole, conversation_id)
            self.history.addItem(item)
            if conversation_id == selected:
                self.history.setCurrentItem(item)
        self.history.blockSignals(False)
        self._filter_history(self.search.text())

    def _filter_history(self, text: str) -> None:
        needle = str(text or "").casefold().strip()
        for index in range(self.history.count()):
            item = self.history.item(index)
            item.setHidden(bool(needle and needle not in item.text().casefold()))

    def _history_activated(self, item: QListWidgetItem) -> None:
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if conversation_id is not None:
            self.bridge.load_conversation(int(conversation_id))

    def _load_conversation(self, conversation_id: int, title: str, rows: list) -> None:
        self._clear_messages()
        for row in rows:
            self._append_row(row)
        self.setWindowTitle(f"JARVIS // {title}")

    def _response_started(self, generation: int) -> None:
        self._stream_generation = generation
        self._stream_text = ""
        self._stream_bubble = self._append_row(
            {"sender": "JARVIS", "message": "", "is_user": False}
        )

    def _response_chunk(self, generation: int, text: str) -> None:
        if generation != self._stream_generation or self._stream_bubble is None:
            return
        self._stream_text += str(text or "")
        body = self._stream_bubble.findChild(QLabel, "bubbleText")
        if body is not None:
            body.setText(self._stream_text)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _response_finished(self, generation: int, text: str) -> None:
        if generation != self._stream_generation:
            return
        if self._stream_bubble is not None:
            body = self._stream_bubble.findChild(QLabel, "bubbleText")
            if body is not None:
                body.setText(text)
        self._stream_text = text
        self._stream_bubble = None

    def _response_failed(self, generation: int, text: str) -> None:
        self._response_finished(generation, text)

    def _busy_changed(self, busy: bool) -> None:
        self.composer.send.setEnabled(not busy)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.bridge.close()
        super().closeEvent(event)

    def run(self) -> int:
        self.show()
        return self.app.exec()

    @staticmethod
    def _stylesheet() -> str:
        return f"""
        QMainWindow#jarvisWindow, QWidget#root, QFrame#mainSurface {{ background: {APP_BG}; color: {TEXT}; }}
        QFrame#sidebar {{ background: {PANEL_BG}; border-right: 1px solid {BORDER}; }}
        QFrame#topbar {{ background: rgba(1,7,12,244); border-bottom: 1px solid #102b3d; }}
        QLabel#topTitle {{ color: {TEXT}; font: 700 13px 'Segoe UI'; }}
        QLabel#topSubtitle {{ color: #53798e; font: 9px 'Segoe UI'; letter-spacing: 1px; }}
        QPushButton#updateButton {{ border-radius: 18px; font: 20px 'Segoe UI'; background: #041725; border: 1px solid #1c5574; color: {CYAN_SOFT}; }}
        QLabel#brandMark {{ border: 1px solid {CYAN}; border-radius: 25px; color: {CYAN_SOFT}; font: 22px 'Segoe UI'; }}
        QLabel#brandTitle {{ color: {TEXT}; font: 700 26px 'Segoe UI'; }}
        QPushButton {{ color: {TEXT}; background: #071725; border: 1px solid {BORDER}; border-radius: 10px; font: 12px 'Segoe UI'; }}
        QPushButton:hover {{ background: #0b2942; border-color: {BORDER_BRIGHT}; }}
        QPushButton#primarySideButton {{ text-align: left; padding-left: 15px; }}
        QLineEdit#search {{ color: {TEXT}; background: #06131e; border: 1px solid {BORDER}; border-radius: 10px; padding: 0 12px; }}
        QLabel#sectionTitle {{ color: {MUTED}; font: 600 10px 'Segoe UI'; padding-top: 8px; letter-spacing: 1px; }}
        QListWidget#history {{ background: transparent; border: 0; outline: 0; color: #cbe5f2; font: 12px 'Segoe UI'; }}
        QListWidget#history::item {{ min-height: 36px; border-radius: 8px; padding: 0 8px; }}
        QListWidget#history::item:selected {{ background: #0d2a42; color: white; }}
        QFrame#lowerSurface {{ background: {LOWER_BG}; border-top: 1px solid #0f2a3c; }}
        QFrame#transcriptFrame {{ background: rgba(3,14,23,215); border: 1px solid #14374d; border-radius: 14px; }}
        QScrollArea#transcript, QWidget#messageHost {{ background: transparent; }}
        QScrollArea#transcript > QWidget > QWidget {{ background: transparent; }}
        QFrame#userBubble {{ background: rgba(13,48,72,235); border: 1px solid #286181; border-radius: 13px; }}
        QFrame#jarvisBubble {{ background: rgba(5,23,36,235); border: 1px solid #153b55; border-radius: 13px; }}
        QLabel#bubbleSender {{ color: {CYAN_SOFT}; font: 700 10px 'Segoe UI'; }}
        QLabel#bubbleText {{ color: {TEXT}; font: 14px 'Segoe UI'; }}
        QFrame#composer {{ background: {GLASS}; border: 1px solid #31536d; border-radius: 20px; }}
        QTextEdit#composerEditor {{ color: {TEXT}; background: transparent; border: 0; padding: 7px 5px; font: 14px 'Segoe UI'; }}
        QPushButton#roundButton, QPushButton#micButton, QPushButton#sendButton {{ border-radius: 21px; font: 19px 'Segoe UI'; }}
        QPushButton#micButton {{ background: #062c52; border-color: #168fe5; color: {CYAN_SOFT}; }}
        QPushButton#sendButton {{ background: #0a3152; border-color: #2d8fc5; color: white; }}
        QFrame#modeBar {{ background: transparent; }}
        QCheckBox {{ color: {MUTED}; spacing: 6px; font: 10px 'Segoe UI'; }}
        QCheckBox::indicator {{ width: 22px; height: 12px; border-radius: 6px; border: 1px solid #31536d; background: #091622; }}
        QCheckBox::indicator:checked {{ background: #148ac7; border-color: {CYAN}; }}
        """


__all__ = ["JarvisGUI"]
