"""Reference-first PySide6 shell for the JARVIS desktop rebuild.

This is a clean UI implementation: it does not subclass, wrap or hide the old
CustomTkinter interface.  Runtime integration is delegated to ``JarvisQtBridge``
so visual work can evolve independently from the assistant/backend.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from jarvis_qt_bridge import JarvisQtBridge


APP_BG = "#020810"
PANEL_BG = "rgba(3, 13, 22, 232)"
GLASS_BG = "rgba(7, 24, 38, 220)"
BORDER = "#173c55"
BORDER_BRIGHT = "#2b6d92"
CYAN = "#32c6ff"
CYAN_SOFT = "#7ce0ff"
TEXT = "#eef9ff"
MUTED = "#86a7ba"


class SceneCanvas(QWidget):
    """Controlled cinematic scene and lightweight hologram renderer."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._phase = 0.0
        self._background = QPixmap()
        self._load_background()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(42)

    def _asset_roots(self):
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            yield Path(bundle)
        yield Path(__file__).resolve().parent

    def _load_background(self) -> None:
        # Deliberately do not fall back to jarvis_reference_scene_1440p.jpg:
        # the 1.3.12 binary currently contains the rejected red scene.  The Qt
        # rebuild uses a separately approved plate when it is present.
        for root in self._asset_roots():
            for rel in (
                Path("assets") / "jarvis_qt_reference_plate.jpg",
                Path("data") / "jarvis_qt_reference_plate.jpg",
            ):
                path = root / rel
                if path.is_file():
                    pixmap = QPixmap(str(path))
                    if not pixmap.isNull():
                        self._background = pixmap
                        return

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self._phase = (self._phase + 0.018) % (math.tau)
        self.update()

    @staticmethod
    def _cover_rect(source_w: int, source_h: int, target: QRectF) -> QRectF:
        if source_w <= 0 or source_h <= 0:
            return QRectF()
        scale = max(target.width() / source_w, target.height() / source_h)
        w = target.width() / scale
        h = target.height() / scale
        x = (source_w - w) / 2.0
        y = (source_h - h) / 2.0
        return QRectF(x, y, w, h)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        target = QRectF(self.rect())

        if not self._background.isNull():
            source = self._cover_rect(self._background.width(), self._background.height(), target)
            painter.drawPixmap(target, self._background, source)
            veil = QLinearGradient(0, 0, 0, self.height())
            veil.setColorAt(0.0, QColor(0, 6, 12, 55))
            veil.setColorAt(1.0, QColor(0, 7, 14, 115))
            painter.fillRect(target, veil)
        else:
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0.0, QColor("#03101b"))
            gradient.setColorAt(0.55, QColor("#06192a"))
            gradient.setColorAt(1.0, QColor("#01060c"))
            painter.fillRect(target, gradient)
            self._paint_office_hint(painter)

        self._paint_hologram(painter)

    def _paint_office_hint(self, painter: QPainter) -> None:
        """Neutral fallback; never recreates the rejected red/city plate."""
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        horizon = self.height() * 0.52
        for i in range(16):
            x = (i / 15.0) * self.width()
            height = self.height() * (0.08 + 0.15 * ((i * 37) % 11) / 10.0)
            painter.fillRect(QRectF(x, horizon - height, self.width() / 25.0, height), QColor(18, 51, 72, 55))
        painter.fillRect(QRectF(0, self.height() * 0.72, self.width(), self.height() * 0.28), QColor(2, 10, 17, 170))
        painter.restore()

    def _paint_hologram(self, painter: QPainter) -> None:
        w, h = self.width(), self.height()
        radius = max(82.0, min(178.0, min(w, h) * 0.23))
        cx = w * 0.52
        cy = h * 0.47

        painter.save()
        glow = QRadialGradient(cx, cy, radius * 1.55)
        glow.setColorAt(0.0, QColor(55, 196, 255, 82))
        glow.setColorAt(0.42, QColor(24, 147, 222, 36))
        glow.setColorAt(1.0, QColor(4, 28, 50, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(cx - radius * 1.55, cy - radius * 1.55, radius * 3.1, radius * 3.1))

        sphere = QRadialGradient(cx - radius * 0.28, cy - radius * 0.38, radius * 1.35)
        sphere.setColorAt(0.0, QColor(76, 211, 255, 112))
        sphere.setColorAt(0.40, QColor(18, 117, 177, 92))
        sphere.setColorAt(1.0, QColor(2, 27, 45, 175))
        painter.setBrush(sphere)
        painter.setPen(QPen(QColor(69, 195, 246, 180), 1.35))
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        grid_pen = QPen(QColor(78, 192, 231, 110), 0.9)
        painter.setPen(grid_pen)
        for factor in (-0.66, -0.33, 0.0, 0.33, 0.66):
            y = cy + radius * factor
            half = radius * math.sqrt(max(0.0, 1.0 - factor * factor))
            painter.drawEllipse(QRectF(cx - half, y - radius * 0.13, half * 2, radius * 0.26))
        for factor in (-0.62, -0.30, 0.0, 0.30, 0.62):
            x = cx + radius * factor
            half = radius * math.sqrt(max(0.0, 1.0 - factor * factor))
            painter.drawEllipse(QRectF(x - radius * 0.15, cy - half, radius * 0.30, half * 2))

        arc_pen = QPen(QColor(72, 211, 255, 215), 2.0)
        painter.setPen(arc_pen)
        for idx, tilt in enumerate((-18.0, 28.0)):
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(tilt + math.sin(self._phase + idx) * 2.2)
            painter.drawArc(QRectF(-radius * 1.22, -radius * 0.54, radius * 2.44, radius * 1.08), 12 * 16, 255 * 16)
            painter.restore()
        painter.restore()


class MessageBubble(QFrame):
    def __init__(self, sender: str, text: str, is_user: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("userBubble" if is_user else "jarvisBubble")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 11)
        layout.setSpacing(4)
        name = QLabel("VOCÊ" if is_user else "JARVIS")
        name.setObjectName("bubbleSender")
        body = QLabel(text)
        body.setObjectName("bubbleText")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(name)
        layout.addWidget(body)


class Composer(QFrame):
    submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("composer")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(7)

        self.plus = QPushButton("+")
        self.plus.setObjectName("roundButton")
        self.editor = QTextEdit()
        self.editor.setObjectName("composerEditor")
        self.editor.setPlaceholderText("Mensagem para o JARVIS...")
        self.editor.setAcceptRichText(False)
        self.editor.setFixedHeight(52)
        self.mic = QPushButton("●")
        self.mic.setObjectName("micButton")
        self.send = QPushButton("➤")
        self.send.setObjectName("sendButton")
        for button in (self.plus, self.mic, self.send):
            button.setFixedSize(46, 46)

        layout.addWidget(self.plus)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.mic)
        layout.addWidget(self.send)
        self.send.clicked.connect(self._submit)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._submit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _submit(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            return
        self.editor.clear()
        self.submitted.emit(text)


class JarvisGUI(QMainWindow):
    """New main-window contract; compatible constructor with the current app."""

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
        self._conversation_ids: list[int] = []

        self.setWindowTitle("JARVIS // Desktop Intelligence")
        self.resize(1440, 900)
        self.setMinimumSize(1040, 680)
        self.setObjectName("jarvisWindow")
        self._build_ui()
        self._connect_bridge()
        self.bridge.refresh_conversations()
        self.bridge.load_active_conversation()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = self._build_sidebar()
        outer.addWidget(self.sidebar)

        main = QFrame()
        main.setObjectName("mainSurface")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scene = SceneCanvas()
        main_layout.addWidget(self.scene, 5)

        self.transcript_frame = QFrame()
        self.transcript_frame.setObjectName("transcriptFrame")
        transcript_layout = QVBoxLayout(self.transcript_frame)
        transcript_layout.setContentsMargins(18, 12, 18, 10)
        transcript_layout.setSpacing(8)

        self.transcript = QScrollArea()
        self.transcript.setObjectName("transcript")
        self.transcript.setWidgetResizable(True)
        self.transcript.setFrameShape(QFrame.Shape.NoFrame)
        self.message_host = QWidget()
        self.message_layout = QVBoxLayout(self.message_host)
        self.message_layout.setContentsMargins(2, 2, 2, 2)
        self.message_layout.setSpacing(8)
        self.message_layout.addStretch(1)
        self.transcript.setWidget(self.message_host)
        transcript_layout.addWidget(self.transcript, 1)

        self.composer = Composer()
        transcript_layout.addWidget(self.composer)
        transcript_layout.addWidget(self._build_mode_bar())
        main_layout.addWidget(self.transcript_frame, 4)
        outer.addWidget(main, 1)

        self.setStyleSheet(self._stylesheet())

    def _build_sidebar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(292)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(10)

        brand = QHBoxLayout()
        mark = QLabel("◇")
        mark.setObjectName("brandMark")
        mark.setFixedSize(52, 52)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("JARVIS")
        title.setObjectName("brandTitle")
        brand.addWidget(mark)
        brand.addWidget(title)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(10)

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
        settings = QPushButton("⚙")
        help_button = QPushButton("?")
        for button in (settings, help_button):
            button.setObjectName("footerButton")
            button.setFixedSize(42, 38)
        footer.addWidget(settings)
        footer.addWidget(help_button)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.new_button.clicked.connect(self.bridge.new_conversation)
        self.search.textChanged.connect(self._filter_history)
        self.history.itemActivated.connect(self._history_activated)
        self.history.itemClicked.connect(self._history_activated)
        return panel

    def _build_mode_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("modeBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(14)
        for text, checked in (
            ("JARVIS fala", True),
            ("Legenda na tela", True),
            ("Modo Rápido", False),
            ("Modo Detalhado", False),
            ("Enter para enviar", True),
        ):
            check = QCheckBox(text)
            check.setChecked(checked)
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
        bubble = MessageBubble(row.get("sender", "JARVIS"), row.get("message", ""), is_user)
        alignment = Qt.AlignmentFlag.AlignRight if is_user else Qt.AlignmentFlag.AlignLeft
        bubble.setMaximumWidth(760)
        self.message_layout.insertWidget(self.message_layout.count() - 1, bubble, 0, alignment)
        QTimer.singleShot(0, self._scroll_to_bottom)
        return bubble

    def _scroll_to_bottom(self) -> None:
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_conversations(self, rows: list) -> None:
        selected = self.bridge.active_conversation_id
        self.history.blockSignals(True)
        self.history.clear()
        self._conversation_ids = []
        for row in rows:
            conversation_id = int(row.get("id"))
            item = QListWidgetItem(str(row.get("title") or "Nova conversa"))
            item.setData(Qt.ItemDataRole.UserRole, conversation_id)
            self.history.addItem(item)
            self._conversation_ids.append(conversation_id)
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
        self._stream_bubble = self._append_row({"sender": "JARVIS", "message": "", "is_user": False})

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
        QLabel#brandMark {{ border: 1px solid {CYAN}; border-radius: 25px; color: {CYAN_SOFT}; font: 22px 'Segoe UI'; }}
        QLabel#brandTitle {{ color: {TEXT}; font: 700 26px 'Segoe UI'; }}
        QPushButton {{ color: {TEXT}; background: #071725; border: 1px solid {BORDER}; border-radius: 10px; font: 12px 'Segoe UI'; }}
        QPushButton:hover {{ background: #0b2942; border-color: {BORDER_BRIGHT}; }}
        QPushButton#primarySideButton {{ text-align: left; padding-left: 15px; }}
        QLineEdit#search {{ color: {TEXT}; background: #06131e; border: 1px solid {BORDER}; border-radius: 10px; padding: 0 12px; }}
        QLabel#sectionTitle {{ color: {MUTED}; font: 600 11px 'Segoe UI'; padding-top: 8px; }}
        QListWidget#history {{ background: transparent; border: 0; outline: 0; color: #cbe5f2; font: 12px 'Segoe UI'; }}
        QListWidget#history::item {{ min-height: 36px; border-radius: 8px; padding: 0 8px; }}
        QListWidget#history::item:selected {{ background: #0d2a42; color: white; }}
        QFrame#transcriptFrame {{ background: rgba(2, 10, 17, 248); border-top: 1px solid #102c40; }}
        QScrollArea#transcript {{ background: transparent; }}
        QScrollArea#transcript > QWidget > QWidget {{ background: transparent; }}
        QFrame#userBubble {{ background: rgba(13, 48, 72, 235); border: 1px solid #286181; border-radius: 13px; }}
        QFrame#jarvisBubble {{ background: rgba(5, 23, 36, 235); border: 1px solid #153b55; border-radius: 13px; }}
        QLabel#bubbleSender {{ color: {CYAN_SOFT}; font: 700 10px 'Segoe UI'; }}
        QLabel#bubbleText {{ color: {TEXT}; font: 14px 'Segoe UI'; }}
        QFrame#composer {{ background: {GLASS_BG}; border: 1px solid #31536d; border-radius: 18px; }}
        QTextEdit#composerEditor {{ color: {TEXT}; background: transparent; border: 0; padding: 8px 5px; font: 14px 'Segoe UI'; }}
        QPushButton#roundButton, QPushButton#micButton, QPushButton#sendButton {{ border-radius: 22px; font: 20px 'Segoe UI'; }}
        QPushButton#micButton {{ background: #062c52; border-color: #168fe5; color: {CYAN_SOFT}; }}
        QPushButton#sendButton {{ background: #0a3152; border-color: #2d8fc5; color: white; }}
        QFrame#modeBar {{ background: transparent; }}
        QCheckBox {{ color: {MUTED}; spacing: 6px; font: 11px 'Segoe UI'; }}
        QCheckBox::indicator {{ width: 24px; height: 13px; border-radius: 6px; border: 1px solid #31536d; background: #091622; }}
        QCheckBox::indicator:checked {{ background: #148ac7; border-color: {CYAN}; }}
        """


__all__ = ["JarvisGUI", "SceneCanvas", "MessageBubble"]
