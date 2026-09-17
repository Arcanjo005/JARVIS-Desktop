"""Minimal neon composer controls for the Qt rebuild.

The icons are rendered directly into QIcon pixmaps, so the visual never sits in
an overlay widget above the QPushButton.  The full button remains the clickable
hit target.  This module also installs the real Enter/Shift+Enter behavior on
the QTextEdit child, where keyboard events actually arrive.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


CYAN = QColor(76, 224, 255)
CYAN_HOT = QColor(218, 252, 255)


def _stroke_icon(painter: QPainter, kind: str, alpha: int, width: float, scale: float = 1.0) -> None:
    painter.save()
    painter.translate(32.0, 32.0)
    painter.scale(scale, scale)
    painter.translate(-32.0, -32.0)
    color = QColor(CYAN)
    color.setAlpha(alpha)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

    if kind == "plus":
        painter.drawLine(QPointF(32, 17), QPointF(32, 47))
        painter.drawLine(QPointF(17, 32), QPointF(47, 32))
    elif kind == "mic":
        painter.drawRoundedRect(QRectF(25, 13, 14, 27), 7, 7)
        path = QPainterPath()
        path.moveTo(19, 31)
        path.cubicTo(19, 43, 25, 48, 32, 48)
        path.cubicTo(39, 48, 45, 43, 45, 31)
        painter.drawPath(path)
        painter.drawLine(QPointF(32, 48), QPointF(32, 54))
        painter.drawLine(QPointF(25, 54), QPointF(39, 54))
    elif kind == "send":
        path = QPainterPath()
        path.moveTo(13, 21)
        path.lineTo(50, 14)
        path.lineTo(40, 50)
        path.lineTo(29, 35)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(29, 35), QPointF(50, 14))
    painter.restore()


def neon_icon(kind: str) -> QIcon:
    """Return a transparent 64x64 cyan-neon icon without any button border."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # A few translucent strokes create the approved soft neon look while
    # remaining lightweight enough for old integrated GPUs.
    _stroke_icon(painter, kind, 25, 12.0)
    _stroke_icon(painter, kind, 55, 8.0)
    _stroke_icon(painter, kind, 145, 4.5)

    hot = QColor(CYAN_HOT)
    painter.setPen(QPen(hot, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == "plus":
        painter.drawLine(QPointF(32, 17), QPointF(32, 47))
        painter.drawLine(QPointF(17, 32), QPointF(47, 32))
    elif kind == "mic":
        painter.drawRoundedRect(QRectF(25, 13, 14, 27), 7, 7)
        path = QPainterPath()
        path.moveTo(19, 31)
        path.cubicTo(19, 43, 25, 48, 32, 48)
        path.cubicTo(39, 48, 45, 43, 45, 31)
        painter.drawPath(path)
        painter.drawLine(QPointF(32, 48), QPointF(32, 54))
        painter.drawLine(QPointF(25, 54), QPointF(39, 54))
    elif kind == "send":
        path = QPainterPath()
        path.moveTo(13, 21)
        path.lineTo(50, 14)
        path.lineTo(40, 50)
        path.lineTo(29, 35)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(29, 35), QPointF(50, 14))
    painter.end()
    return QIcon(pixmap)


class ComposerPolish(QObject):
    """Keeps icons clickable and fixes Enter handling on the actual editor."""

    def __init__(self, composer):
        super().__init__(composer)
        self.composer = composer
        self.editor = composer.editor
        self.editor.installEventFilter(self)
        self._configure_button(composer.plus, "plus", "Mais opções", "Abrir mais opções")
        self._configure_button(composer.mic, "mic", "Microfone", "Usar entrada de voz")
        self._configure_button(composer.send, "send", "Enviar", "Enviar mensagem")

    @staticmethod
    def _configure_button(button, kind: str, accessible: str, tooltip: str) -> None:
        button.setText("")
        button.setIcon(neon_icon(kind))
        button.setIconSize(QSize(34, 34))
        button.setFixedSize(46, 46)
        button.setToolTip(tooltip)
        button.setAccessibleName(accessible)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 23px; padding: 0; }"
            "QPushButton:hover { background: rgba(34, 190, 255, 28); }"
            "QPushButton:pressed { background: rgba(34, 190, 255, 52); }"
            "QPushButton:disabled { background: transparent; }"
        )

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if watched is self.editor and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False
                self.composer._submit()
                return True
        return super().eventFilter(watched, event)


def install_composer_polish(composer) -> ComposerPolish:
    return ComposerPolish(composer)


__all__ = ["ComposerPolish", "install_composer_polish", "neon_icon"]
