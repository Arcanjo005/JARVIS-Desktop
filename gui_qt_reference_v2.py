"""Reference-driven PySide6 composition for the JARVIS desktop rebuild.

The working area is one continuous cinematic scene.  Conversation controls live
as translucent overlays above it instead of reserving an opaque lower panel.
"""
from __future__ import annotations

import re
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
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from gui_qt_reference import Composer, MessageBubble, SceneCanvas
from jarvis_qt_bridge import JarvisQtBridge
from jarvis_qt_composer_patch import install_composer_polish

APP_BG = "#02070d"
PANEL_BG = "rgba(2, 10, 17, 226)"
GLASS = "rgba(5, 14, 22, 176)"
GLASS_SOFT = "rgba(3, 10, 16, 112)"
BORDER = "rgba(89, 132, 158, 92)"
BORDER_BRIGHT = "rgba(82, 200, 244, 150)"
CYAN = "#36c8ff"
CYAN_SOFT = "#82e2ff"
TEXT = "#edf8ff"
MUTED = "#8da7b6"


def _shadow(widget: QWidget, blur: int = 28, alpha: int = 105, y: int = 7) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


class RollingCaption(QFrame):
    """Two-line subtitle window that advances instead of accumulating text.

    During streaming it follows the newest page, so a long answer never remains
    stuck on its first lines.  Once the response ends it keeps the last page for
    a few seconds and clears itself.  No extra thread is used.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("captionGlass")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(54)
        self.setMaximumHeight(72)
        self.setMaximumWidth(840)
        self._raw_text = ""
        self._pages: list[str] = []
        self._visible_index = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 8, 22, 9)
        layout.setSpacing(1)
        self.label = QLabel("")
        self.label.setObjectName("captionText")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setMaximumHeight(50)
        layout.addWidget(self.label)

        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self.clear_caption)
        self.hide()

    @staticmethod
    def _paginate(text: str, target_chars: int = 112) -> list[str]:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean:
            return []
        words = clean.split(" ")
        pages: list[str] = []
        current: list[str] = []
        current_len = 0
        for word in words:
            addition = len(word) + (1 if current else 0)
            if current and current_len + addition > target_chars:
                pages.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len += addition
        if current:
            pages.append(" ".join(current))
        return pages

    def set_stream_text(self, text: str) -> None:
        self._clear_timer.stop()
        self._raw_text = str(text or "")
        self._pages = self._paginate(self._raw_text)
        if not self._pages:
            self.clear_caption()
            return
        # Always expose the newest page while chunks arrive.  This is what makes
        # the subtitle actually progress for long streamed answers.
        self._visible_index = len(self._pages) - 1
        self.label.setText(self._pages[self._visible_index])
        self.show()
        self.raise_()

    def finish_text(self, text: str) -> None:
        self.set_stream_text(text)
        if self._pages:
            self._clear_timer.start(6500)

    def clear_caption(self) -> None:
        self._raw_text = ""
        self._pages = []
        self._visible_index = -1
        self.label.clear()
        self.hide()


class JarvisGUI(QMainWindow):
    """Reference-driven Qt shell with the chat floating over the workspace."""

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
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(30, 24, 30, 22)
        overlay_layout.setSpacing(10)

        # The sphere itself is painted by SceneCanvas.  The subtitle sits below
        # its visual center, then the transcript/composer float near the bottom.
        overlay_layout.addStretch(7)
        caption_row = QHBoxLayout()
        caption_row.addStretch(1)
        self.caption = RollingCaption()
        caption_row.addWidget(self.caption, 0)
        caption_row.addStretch(1)
        overlay_layout.addLayout(caption_row)
        overlay_layout.addStretch(2)

        self.transcript_frame = QFrame()
        self.transcript_frame.setObjectName("transcriptFrame")
        self.transcript_frame.setMinimumHeight(96)
        self.transcript_frame.setMaximumHeight(180)
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
        self.message_layout.setSpacing(7)
        self.message_layout.addStretch(1)
        self.transcript.setWidget(self.message_host)
        transcript_layout.addWidget(self.transcript)
        overlay_layout.addWidget(self.transcript_frame)

        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(34, 0, 34, 0)
        self.composer = Composer()
        self.composer.setMinimumWidth(520)
        self.composer.setMaximumWidth(920)
        self._composer_polish = install_composer_polish(self.composer)
        _shadow(self.composer, blur=30, alpha=120, y=8)
        composer_row.addStretch(1)
        composer_row.addWidget(self.composer, 1)
        composer_row.addStretch(1)
        overlay_layout.addLayout(composer_row)

        mode_row = QHBoxLayout()
        mode_row.addStretch(1)
        mode_row.addWidget(self._build_mode_bar())
        mode_row.addStretch(1)
        overlay_layout.addLayout(mode_row)

        stack.addWidget(overlay)
        main_layout.addWidget(stage, 1)
        shell.addWidget(main, 1)
        self.setStyleSheet(self._stylesheet())

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(48)
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
        self.update_button.setFixedSize(40, 34)
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
        layout.setContentsMargins(10, 1, 10, 1)
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
        self.mode_checks["Legenda na tela"].toggled.connect(self._caption_visibility_changed)
        return bar

    def _caption_visibility_changed(self, enabled: bool) -> None:
        if enabled and self._stream_text:
            self.caption.set_stream_text(self._stream_text)
        else:
            self.caption.clear_caption()

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
        self.caption.clear_caption()

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
        self.caption.clear_caption()
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
        if self.mode_checks["Legenda na tela"].isChecked():
            self.caption.set_stream_text(self._stream_text)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _response_finished(self, generation: int, text: str) -> None:
        if generation != self._stream_generation:
            return
        if self._stream_bubble is not None:
            body = self._stream_bubble.findChild(QLabel, "bubbleText")
            if body is not None:
                body.setText(text)
        self._stream_text = str(text or "")
        if self.mode_checks["Legenda na tela"].isChecked():
            self.caption.finish_text(self._stream_text)
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
        QWidget#stage, QWidget#workspaceOverlay {{ background: transparent; }}
        QFrame#sidebar {{ background: {PANEL_BG}; border-right: 1px solid rgba(37,77,101,120); }}
        QFrame#topbar {{ background: rgba(1,7,12,214); border-bottom: 1px solid rgba(36,70,90,78); }}
        QLabel#topTitle {{ color: {TEXT}; font: 700 13px 'Segoe UI'; }}
        QLabel#topSubtitle {{ color: #6e8795; font: 9px 'Segoe UI'; letter-spacing: 1px; }}
        QPushButton#updateButton {{ border-radius: 17px; font: 20px 'Segoe UI'; background: rgba(4,23,37,150); border: 1px solid rgba(53,103,132,110); color: {CYAN_SOFT}; }}
        QLabel#brandMark {{ border: 1px solid rgba(54,200,255,155); border-radius: 25px; color: {CYAN_SOFT}; font: 22px 'Segoe UI'; }}
        QLabel#brandTitle {{ color: {TEXT}; font: 700 26px 'Segoe UI'; }}
        QPushButton {{ color: {TEXT}; background: rgba(7,23,37,150); border: 1px solid rgba(47,82,104,100); border-radius: 10px; font: 12px 'Segoe UI'; }}
        QPushButton:hover {{ background: rgba(11,41,66,175); border-color: rgba(70,145,184,150); }}
        QPushButton#primarySideButton {{ text-align: left; padding-left: 15px; }}
        QLineEdit#search {{ color: {TEXT}; background: rgba(6,19,30,164); border: 1px solid rgba(47,82,104,100); border-radius: 10px; padding: 0 12px; }}
        QLabel#sectionTitle {{ color: {MUTED}; font: 600 10px 'Segoe UI'; padding-top: 8px; letter-spacing: 1px; }}
        QListWidget#history {{ background: transparent; border: 0; outline: 0; color: #cbe5f2; font: 12px 'Segoe UI'; }}
        QListWidget#history::item {{ min-height: 36px; border-radius: 8px; padding: 0 8px; }}
        QListWidget#history::item:selected {{ background: rgba(13,42,66,160); color: white; }}

        QFrame#captionGlass {{ background: {GLASS_SOFT}; border: 1px solid rgba(118,154,175,54); border-radius: 14px; }}
        QLabel#captionText {{ color: #f1f7fb; background: transparent; font: 500 14px 'Segoe UI'; }}

        QFrame#transcriptFrame {{ background: rgba(4,11,17,92); border: none; border-radius: 14px; }}
        QScrollArea#transcript, QWidget#messageHost {{ background: transparent; border: none; }}
        QScrollArea#transcript > QWidget > QWidget {{ background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 6px; margin: 3px 0; }}
        QScrollBar::handle:vertical {{ background: rgba(139,171,188,70); min-height: 22px; border-radius: 3px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

        QFrame#userBubble {{ background: rgba(18,29,37,176); border: 1px solid rgba(131,158,174,58); border-radius: 13px; }}
        QFrame#jarvisBubble {{ background: rgba(9,18,25,166); border: 1px solid rgba(123,151,168,48); border-radius: 13px; }}
        QLabel#bubbleSender {{ color: #a9dff1; font: 700 10px 'Segoe UI'; }}
        QLabel#bubbleText {{ color: {TEXT}; font: 14px 'Segoe UI'; }}

        QFrame#composer {{ background: {GLASS}; border: 1px solid {BORDER}; border-radius: 24px; }}
        QTextEdit#composerEditor {{ color: {TEXT}; background: transparent; border: 0; padding: 7px 5px; font: 14px 'Segoe UI'; selection-background-color: rgba(54,200,255,90); }}
        QFrame#modeBar {{ background: rgba(2,9,15,76); border: 1px solid rgba(86,119,139,34); border-radius: 12px; }}
        QCheckBox {{ color: #8ba1ad; spacing: 6px; font: 10px 'Segoe UI'; }}
        QCheckBox::indicator {{ width: 22px; height: 12px; border-radius: 6px; border: 1px solid rgba(72,104,123,90); background: rgba(9,22,34,160); }}
        QCheckBox::indicator:checked {{ background: rgba(31,137,185,190); border-color: rgba(73,196,241,180); }}
        """


__all__ = ["JarvisGUI", "RollingCaption"]
