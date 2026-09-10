"""JARVIS - overlay de voz Qt/PySide6.

Roda em processo separado para não misturar o event-loop Qt com o Tkinter.
O overlay é per-pixel alpha, click-through e não recebe foco.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path
from jarvis_identity import env as jarvis_env
from typing import Optional, Tuple

try:
    from text_sanitizer import sanitize_text
except Exception:
    def sanitize_text(text, *, limit=260, preserve_newlines=False):
        value = unicodedata.normalize("NFC", str(text or "")).replace("\ufffd", "")
        value = "".join(ch for ch in value if not unicodedata.category(ch).startswith("C"))
        value = " ".join(value.split()).strip()
        return value[:limit] if limit and len(value) > limit else value

VOICE_ORB_OPACITY = max(0.60, min(float(jarvis_env("VOICE_ORB_OPACITY", "0.90")), 1.0))

OVERLAY_FULL_WIDTH = 380
OVERLAY_FULL_HEIGHT = 360
OVERLAY_COMPACT_SIZE = 96
OVERLAY_COMPACT_RADIUS = 20.0
OVERLAY_EDGE_MARGIN = 18


def clamp_overlay_position(x, y, width, height, left, top, right, bottom, margin=OVERLAY_EDGE_MARGIN):
    """Mantem o overlay 100% dentro da area util (right/bottom exclusivos)."""
    width = max(1, int(width)); height = max(1, int(height))
    left = int(left); top = int(top); right = int(right); bottom = int(bottom)
    margin = max(0, int(margin))
    min_x = left + margin
    min_y = top + margin
    max_x = max(min_x, right - width - margin)
    max_y = max(min_y, bottom - height - margin)
    return max(min_x, min(int(x), max_x)), max(min_y, min(int(y), max_y))


def corner_overlay_position(width, height, left, top, right, bottom, margin=OVERLAY_EDGE_MARGIN):
    """Canto inferior direito da area util, sem encostar na barra de tarefas."""
    return clamp_overlay_position(
        int(right) - int(width) - int(margin),
        int(bottom) - int(height) - int(margin),
        width, height, left, top, right, bottom, margin,
    )


class QtVoiceOverlayController:
    """Controlador usado pelo gui.py. Comunicação: JSON por stdin."""

    def __init__(self, project_dir: str, logger=None):
        self.project_dir = Path(project_dir)
        self.logger = logger
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stderr_handle = None
        self.available = importlib.util.find_spec("PySide6") is not None
        self._visible = False
        self._last_position: Optional[Tuple[int, int]] = None
        self._last_state = "REPOUSO"
        self._last_caption = ""
        self._last_caption_speaker = "assistant"
        self._last_level = 0.0
        self._last_audio_metrics = {}
        self._last_orb_style = "core"
        self._last_compact = True
        self._last_opacity = VOICE_ORB_OPACITY
        self._conversation_lock = False
        self.position_path = self.project_dir / "data" / "overlay_position.json"
        self._move_mode = False

    def _log(self, level: str, message: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "OVERLAY")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    def is_alive(self) -> bool:
        return bool(
            self.process
            and self.process.poll() is None
        )

    def start(self) -> bool:
        if not self.available:
            self._log("warning", "PySide6 não instalado; usando overlay Tk fallback.")
            return False
        if self.is_alive():
            return True

        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            log_dir = self.project_dir / "data"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "voice_overlay_qt.log"
            try:
                if self._stderr_handle:
                    self._stderr_handle.close()
            except Exception:
                pass
            self._stderr_handle = open(log_path, "a", encoding="utf-8")

            if getattr(sys, "frozen", False):
                # In a PyInstaller build sys.executable is JARVIS.exe. Passing
                # this module path as if it were a Python script would relaunch
                # the full JARVIS UI recursively. main.py owns this explicit
                # helper switch and dispatches directly to _run_child().
                child_command = [sys.executable, "--voice-overlay-child"]
            else:
                child_command = [sys.executable, str(Path(__file__).resolve()), "--child"]

            self.process = subprocess.Popen(
                child_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr_handle,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=flags,
                cwd=str(self.project_dir),
            )
            self._log("info", "Overlay Qt V4 iniciado.")
            return True
        except Exception as exc:
            self.process = None
            self._log("warning", f"Falha ao iniciar overlay Qt: {exc}")
            return False

    def _raw_send(self, payload: dict):
        with self._lock:
            process = self.process
            if not process or process.poll() is not None or not process.stdin:
                return False
            try:
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
                return True
            except Exception:
                return False

    def _restore_visible_state(self):
        if not self._visible or not self.is_alive():
            return False
        # 13.10.3: não restaura posição arrastada antiga; o overlay volta ao canto.
        self._raw_send({"cmd": "conversation_lock", "value": self._conversation_lock})
        self._raw_send({"cmd": "state", "value": self._last_state})
        self._raw_send({"cmd": "level", "value": self._last_level})
        self._raw_send({"cmd": "audio_metrics", "value": self._last_audio_metrics})
        self._raw_send({"cmd": "orb_style", "value": self._last_orb_style})
        self._raw_send({"cmd": "compact", "value": self._last_compact})
        self._raw_send({"cmd": "opacity", "value": self._last_opacity})
        self._raw_send({"cmd": "caption", "value": self._last_caption, "speaker": self._last_caption_speaker})
        payload = {"cmd": "show"}
        if self._last_position:
            payload["x"], payload["y"] = self._last_position
        return self._raw_send(payload)

    def _recover_if_visible(self):
        if not self._visible:
            return self.is_alive()
        if self.is_alive():
            return True
        self._log("warning", "Overlay Qt caiu; reiniciando automaticamente.")
        if not self.start():
            return False
        return self._restore_visible_state()

    def show(self, position: Optional[Tuple[int, int]] = None):
        self._visible = True
        if position:
            self._last_position = (int(position[0]), int(position[1]))
        if not self.is_alive() and not self.start():
            return False
        return self._restore_visible_state()

    def hide(self):
        self._visible = False
        if self.is_alive():
            self._raw_send({"cmd": "hide"})

    def set_state(self, state: str):
        requested = str(state or "REPOUSO").upper()
        if self._conversation_lock and requested not in {"ERRO", "SEM_MICROFONE", "RECONECTANDO"}:
            requested = "OUVINDO"
        self._last_state = requested
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "state", "value": self._last_state}) if self.is_alive() else False

    def set_conversation_lock(self, enabled: bool):
        """Trava o overlay do Modo Conversa: mini, verde e sem pulsar tamanho."""
        self._conversation_lock = bool(enabled)
        if self._conversation_lock:
            self._last_state = "OUVINDO"
            self._last_compact = True
        if self._visible and not self._recover_if_visible():
            return False
        if not self.is_alive():
            return False
        ok = self._raw_send({"cmd": "conversation_lock", "value": self._conversation_lock})
        if self._conversation_lock:
            self._raw_send({"cmd": "compact", "value": True})
            self._raw_send({"cmd": "state", "value": "OUVINDO"})
        return ok

    def set_level(self, level: float):
        self._last_level = max(0.0, min(float(level), 1.0))
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "level", "value": self._last_level}) if self.is_alive() else False

    def set_audio_metrics(self, metrics: dict):
        self._last_audio_metrics = dict(metrics or {})
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "audio_metrics", "value": self._last_audio_metrics}) if self.is_alive() else False

    def set_caption(self, text: str, speaker: str = "assistant"):
        self._last_caption = sanitize_text(text, limit=520)
        self._last_caption_speaker = "user" if str(speaker).lower() == "user" else "assistant"
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({
            "cmd": "caption",
            "value": self._last_caption,
            "speaker": self._last_caption_speaker,
        }) if self.is_alive() else False

    def set_user_caption(self, text: str):
        return self.set_caption(text, speaker="user")

    def get_saved_position(self):
        try:
            if self.position_path.exists():
                data = json.loads(self.position_path.read_text(encoding="utf-8"))
                return int(data.get("x")), int(data.get("y"))
        except Exception:
            pass
        return None

    def set_move_mode(self, enabled: bool = True):
        self._move_mode = bool(enabled)
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "move_mode", "value": self._move_mode}) if self.is_alive() else False


    def set_orb_style(self, style: str):
        value = str(style or "core").strip().lower()
        if value not in {"crystal", "core", "rings", "pulse", "minimal"}:
            value = "core"
        self._last_orb_style = value
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "orb_style", "value": value}) if self.is_alive() else False

    def set_compact(self, enabled: bool):
        self._last_compact = True if self._conversation_lock else bool(enabled)
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "compact", "value": self._last_compact}) if self.is_alive() else False

    def set_opacity(self, value: float):
        try:
            self._last_opacity = max(0.35, min(float(value), 1.0))
        except Exception:
            self._last_opacity = VOICE_ORB_OPACITY
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "opacity", "value": self._last_opacity}) if self.is_alive() else False

    def set_position(self, x: int, y: int):
        self._last_position = (int(x), int(y))
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "position", "x": int(x), "y": int(y)}) if self.is_alive() else False

    def stop(self):
        self._visible = False
        self._raw_send({"cmd": "quit"})
        process = self.process
        self.process = None
        if process:
            try:
                process.wait(timeout=1.5)
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass
        try:
            if self._stderr_handle:
                self._stderr_handle.close()
        except Exception:
            pass
        self._stderr_handle = None


def _run_child():
    from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QThread, QTimer, Signal
    from PySide6.QtGui import (
        QColor,
        QFont,
        QFontMetrics,
        QPainter,
        QPainterPath,
        QPen,
        QRadialGradient,
    )
    from PySide6.QtWidgets import QApplication, QWidget

    class Bridge(QObject):
        command = Signal(dict)

    class Overlay(QWidget):
        WIDTH = OVERLAY_FULL_WIDTH
        HEIGHT = OVERLAY_FULL_HEIGHT
        COMPACT_SIZE = OVERLAY_COMPACT_SIZE
        EDGE_MARGIN = OVERLAY_EDGE_MARGIN

        def __init__(self):
            super().__init__()
            flags = (
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
                | Qt.WindowDoesNotAcceptFocus
            )
            self.setWindowFlags(flags)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setWindowOpacity(VOICE_ORB_OPACITY)
            self.setFocusPolicy(Qt.NoFocus)
            self.resize(self.COMPACT_SIZE, self.COMPACT_SIZE)

            self.state = "REPOUSO"
            self.level = 0.0
            self.smooth_level = 0.0
            self.audio_metrics = {}
            self.orb_style = "core"
            self.compact = True
            self.conversation_lock = False
            self._normal_position = None
            self.caption = ""
            self.caption_target = ""
            self.caption_visible = ""
            self.caption_speaker = "assistant"
            self._caption_progress = 0.0
            self.phase = 0.0
            self.target_x = None
            self.target_y = None
            self.move_mode = False
            self.drag_offset = None
            self.position_path = Path(__file__).resolve().parent / "data" / "overlay_position.json"

            self.timer = QTimer(self)
            self.timer.timeout.connect(self._tick)
            self.timer.start(16)  # ~60 FPS

        def _screen_for_point(self, x=None, y=None):
            try:
                if x is None or y is None:
                    point = self.frameGeometry().center()
                else:
                    point = QPoint(int(x), int(y))
                return QApplication.screenAt(point) or QApplication.primaryScreen()
            except Exception:
                return QApplication.primaryScreen()

        def _work_rect(self, screen=None):
            screen = screen or self._screen_for_point()
            try:
                geo = screen.availableGeometry()
                return int(geo.x()), int(geo.y()), int(geo.x() + geo.width()), int(geo.y() + geo.height())
            except Exception:
                return 0, 0, max(self.width(), 1), max(self.height(), 1)

        def _move_clamped(self, x, y, screen=None):
            screen = screen or self._screen_for_point(int(x) + self.width() // 2, int(y) + self.height() // 2)
            left, top, right, bottom = self._work_rect(screen)
            nx, ny = clamp_overlay_position(
                x, y, self.width(), self.height(), left, top, right, bottom, self.EDGE_MARGIN
            )
            self.move(int(nx), int(ny))
            return int(nx), int(ny)

        def _anchor_bottom_right(self, screen=None):
            screen = screen or self._screen_for_point()
            left, top, right, bottom = self._work_rect(screen)
            x, y = corner_overlay_position(
                self.width(), self.height(), left, top, right, bottom, self.EDGE_MARGIN
            )
            self.move(int(x), int(y))
            return int(x), int(y)

        def _tick(self):
            self.phase += 0.055
            attack = 0.42 if self.level > self.smooth_level else 0.16
            self.smooth_level += (self.level - self.smooth_level) * attack

            # A legenda já chega sincronizada por WordBoundary do TTS.
            # Não recomeçamos animação por palavra, evitando flicker/atraso.
            if self.caption_visible != self.caption_target:
                self.caption_visible = self.caption_target
            self.update()

        def command(self, payload: dict):
            cmd = payload.get("cmd")
            if cmd == "show":
                if "x" in payload and "y" in payload:
                    tx, ty = int(payload["x"]), int(payload["y"])
                    screen = self._screen_for_point(tx + self.width() // 2, ty + self.height() // 2)
                else:
                    screen = self._screen_for_point()
                self._anchor_bottom_right(screen)
                self.show()
                self.raise_()
            elif cmd == "hide":
                self.hide()
            elif cmd == "state":
                requested = str(payload.get("value") or "REPOUSO").upper()
                if self.conversation_lock and requested not in {"ERRO", "SEM_MICROFONE", "RECONECTANDO"}:
                    requested = "OUVINDO"
                self.state = requested
                self.update()
            elif cmd == "conversation_lock":
                self.conversation_lock = bool(payload.get("value", False))
                if self.conversation_lock:
                    self.state = "OUVINDO"
                    if not self.compact:
                        self.compact = True
                        self.resize(self.COMPACT_SIZE, self.COMPACT_SIZE)
                    self.caption_visible = ""
                    self._anchor_bottom_right(self._screen_for_point())
                self.update()
            elif cmd == "level":
                try:
                    self.level = max(0.0, min(float(payload.get("value", 0.0)), 1.0))
                except Exception:
                    self.level = 0.0
            elif cmd == "audio_metrics":
                value = payload.get("value") or {}
                self.audio_metrics = dict(value) if isinstance(value, dict) else {}
                self.update()
            elif cmd == "orb_style":
                value = str(payload.get("value") or "core").strip().lower()
                self.orb_style = value if value in {"crystal", "core", "rings", "pulse", "minimal"} else "core"
                self.update()
            elif cmd == "compact":
                requested = True if self.conversation_lock else bool(payload.get("value", False))
                if requested != self.compact:
                    # Memoriza o MONITOR atual, mas nao restaura coordenada antiga:
                    # tanto pequena quanto grande ficam ancoradas no canto e 100%
                    # dentro de availableGeometry (barra de tarefas respeitada).
                    screen = self._screen_for_point()
                    if requested:
                        self._normal_position = (int(self.x()), int(self.y()))
                        self.compact = True
                        self.resize(self.COMPACT_SIZE, self.COMPACT_SIZE)
                        self._anchor_bottom_right(screen)
                        self.caption_visible = ""
                    else:
                        self.compact = False
                        self.resize(self.WIDTH, self.HEIGHT)
                        self._anchor_bottom_right(screen)
                        self._normal_position = None
                else:
                    # Mesmo sem troca de modo, reafirma o canto. Isso corrige
                    # posição manual antiga e mudanças de resolução/taskbar.
                    screen = self._screen_for_point()
                    if not self.move_mode:
                        self._anchor_bottom_right(screen)
                self.update()
            elif cmd == "opacity":
                try:
                    value = max(0.35, min(float(payload.get("value", VOICE_ORB_OPACITY)), 1.0))
                except Exception:
                    value = VOICE_ORB_OPACITY
                self.setWindowOpacity(value)
                self.update()
            elif cmd == "caption":
                incoming = sanitize_text(payload.get("value") or "", limit=520)
                self.caption_speaker = "user" if str(payload.get("speaker") or "assistant").lower() == "user" else "assistant"
                self.caption = incoming
                self.caption_target = incoming
                if not incoming:
                    self.caption_visible = ""
                self.update()
            elif cmd == "position":
                self._move_clamped(int(payload.get("x", self.x())), int(payload.get("y", self.y())))
            elif cmd == "move_mode":
                self.move_mode = bool(payload.get("value", True))
                self.show()
                self.raise_()
                self.update()
            elif cmd == "quit":
                QApplication.instance().quit()

        def mousePressEvent(self, event):
            # V6: a esfera pode ser arrastada diretamente, sem ativar modo especial.
            if event.button() == Qt.LeftButton:
                self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self.move_mode = True
                self.update()
                event.accept()
                return
            event.ignore()

        def mouseMoveEvent(self, event):
            if self.drag_offset is not None and (event.buttons() & Qt.LeftButton):
                wanted = event.globalPosition().toPoint() - self.drag_offset
                screen = QApplication.screenAt(event.globalPosition().toPoint()) or self._screen_for_point()
                self._move_clamped(wanted.x(), wanted.y(), screen)
                event.accept()
                return
            event.ignore()

        def mouseReleaseEvent(self, event):
            if event.button() == Qt.LeftButton and self.drag_offset is not None:
                self.drag_offset = None
                try:
                    self.position_path.parent.mkdir(parents=True, exist_ok=True)
                    self.position_path.write_text(
                        json.dumps({"x": int(self.x()), "y": int(self.y())}), encoding="utf-8"
                    )
                except Exception:
                    pass
                self.move_mode = False
                self.update()
                event.accept()
                return
            event.ignore()

        def _wrapped_lines(self, text: str, font: QFont, max_width: int, max_lines: int = 3):
            clean = " ".join(str(text or "").split())
            if not clean:
                return []
            metrics = QFontMetrics(font)
            words = clean.split()
            lines = []
            current = ""
            for word in words:
                trial = f"{current} {word}".strip()
                if metrics.horizontalAdvance(trial) <= max_width:
                    current = trial
                    continue
                if current:
                    lines.append(current)
                current = word
                if len(lines) >= max_lines:
                    break
            if current and len(lines) < max_lines:
                lines.append(current)
            rendered = " ".join(lines)
            if len(rendered) < len(clean) and lines:
                last = lines[-1]
                while last and metrics.horizontalAdvance(last + "...") > max_width:
                    last = last[:-1].rstrip()
                lines[-1] = last + "..."
            return lines[:max_lines]

        def _draw_outlined_text(self, painter: QPainter, text: str, x: float, baseline: float, font: QFont, speaker: str = "assistant"):
            path = QPainterPath()
            path.addText(QPointF(x, baseline), font, text)
            painter.setPen(QPen(QColor(0, 0, 0, 235), 4.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(QColor(0, 0, 0, 0))
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            if speaker == "user":
                painter.setBrush(QColor(116, 255, 196, 255))
            else:
                painter.setBrush(QColor(255, 216, 62, 255))
            painter.drawPath(path)

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)

            state = "OUVINDO" if self.conversation_lock else self.state.upper()
            listening = state in ("OUVINDO", "ESCUTANDO")
            waiting = state == "ESPERANDO_RESPOSTA"
            understanding = state == "ENTENDENDO"
            thinking = state in ("PENSANDO", "PROCESSANDO")
            speaking = state == "FALANDO"
            executing = state == "EXECUTANDO"
            reconnecting = state in ("RECONECTANDO", "PREPARANDO")
            error = state in ("ERRO", "SEM_MICROFONE")

            # V6: mais margem superior para o glow nunca ser cortado.
            cx = self.width() / 2.0
            base_cy = (self.height() / 2.0) if self.compact else 126.0
            float_y = 0.0 if self.conversation_lock else math.sin(self.phase * 0.75) * (2.6 if state == "REPOUSO" else 1.5)
            jitter = math.sin(self.phase * 15.0) * 1.3 if error else 0.0
            cy = base_cy + float_y

            pulse = 1.0
            if speaking:
                pulse += 0.04 * (0.5 + 0.5 * math.sin(self.phase * 4.0))
            if (listening or waiting) and not self.conversation_lock:
                pulse += 0.10 * self.smooth_level
            radius = (OVERLAY_COMPACT_RADIUS if self.compact else 58.0) * pulse

            # Cor dominante por estado.
            if listening:
                main = (25, 224, 126); bright = (118, 255, 188); dark = (3, 78, 48)
            elif waiting:
                main = (245, 190, 45); bright = (255, 235, 132); dark = (105, 61, 4)
            elif understanding:
                main = (30, 207, 235); bright = (154, 247, 255); dark = (4, 73, 94)
            elif thinking:
                main = (142, 84, 255); bright = (218, 190, 255); dark = (46, 18, 105)
            elif executing:
                main = (255, 145, 45); bright = (255, 218, 142); dark = (116, 48, 3)
            elif error:
                main = (244, 58, 76); bright = (255, 164, 173); dark = (104, 10, 24)
            elif reconnecting:
                main = (255, 168, 48); bright = (255, 225, 153); dark = (111, 60, 5)
            elif speaking:
                main = (37, 152, 255); bright = (156, 228, 255); dark = (5, 48, 118)
            else:
                main = (26, 137, 255); bright = (151, 222, 255); dark = (5, 43, 105)

            style = self.orb_style
            # Glow controlado dentro do canvas. Cada estilo muda material/energia,
            # mas preserva exatamente a mesma linguagem de estados.
            glow_scale = 0.46 if self.compact else 1.0
            glow_spec = {
                "crystal": ((20, 25), (13, 38), (7, 55)),
                "core": ((24, 18), (14, 34), (6, 62)),
                "rings": ((18, 14), (10, 25), (4, 40)),
                "pulse": ((24, 18), (14, 32), (8, 50)),
                "minimal": ((12, 16), (6, 28)),
            }.get(style, ((20, 25), (13, 38), (7, 55)))
            for extra, alpha in glow_spec:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(*main, alpha))
                extra = extra * glow_scale
                painter.drawEllipse(QPointF(cx + jitter, cy), radius + extra, radius + extra)

            # Ondas de microfone somente quando está realmente esperando voz.
            if (listening or waiting) and not self.conversation_lock:
                for i in range(3):
                    rr = radius + 10 + i * 9 + self.smooth_level * (10 + i * 3)
                    alpha = int(75 + self.smooth_level * 145 - i * 20)
                    painter.setPen(QPen(QColor(*bright, max(35, min(alpha, 230))), 2.0))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(QPointF(cx + jitter, cy), rr, rr)
            elif speaking:
                for i in range(2):
                    rr = radius + 11 + i * 12 + abs(math.sin(self.phase * 2.7 + i)) * 7
                    painter.setPen(QPen(QColor(*bright, 95 - i * 25), 1.8))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(QPointF(cx + jitter, cy), rr, rr)

            if executing or thinking or understanding:
                rect = QRectF(cx - radius - 14, cy - radius - 14, (radius + 14) * 2, (radius + 14) * 2)
                painter.setPen(QPen(QColor(*bright, 205), 2.4))
                painter.setBrush(Qt.NoBrush)
                rot = (self.phase * (105.0 if executing else 68.0)) % 360.0
                span = 45 if executing else 70
                for offset in (0, 120, 240):
                    painter.drawArc(rect, int((rot + offset) * 16), int(span * 16))

            # Material selecionavel da esfera.
            if style == "rings":
                # Centro discreto + anéis holográficos, lembrando HUD/reator.
                core_r = radius * 0.55
                grad = QRadialGradient(QPointF(cx - core_r * 0.22 + jitter, cy - core_r * 0.22), core_r * 1.20)
                grad.setColorAt(0.0, QColor(*bright, 235))
                grad.setColorAt(0.40, QColor(*main, 190))
                grad.setColorAt(1.0, QColor(*dark, 210))
                painter.setPen(QPen(QColor(*bright, 150), 1.3))
                painter.setBrush(grad)
                painter.drawEllipse(QPointF(cx + jitter, cy), core_r, core_r)
                painter.setBrush(Qt.NoBrush)
                for i, extra in enumerate((2.0, 12.0, 23.0)):
                    rr = radius + extra
                    rect = QRectF(cx - rr + jitter, cy - rr, rr * 2, rr * 2)
                    alpha = 190 - i * 42
                    painter.setPen(QPen(QColor(*bright, alpha), 1.5 if i == 0 else 1.1))
                    rot = (self.phase * (72 + i * 21) + i * 83) % 360
                    painter.drawArc(rect, int(rot * 16), int((92 - i * 12) * 16))
                    painter.drawArc(rect, int((rot + 180) * 16), int((54 + i * 8) * 16))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(*bright, 220))
                for i in range(3):
                    a = self.phase * (1.2 + i * 0.18) + i * 2.1
                    rr = radius + 16 + i * 5
                    painter.drawEllipse(QPointF(cx + jitter + math.cos(a) * rr, cy + math.sin(a) * rr), 2.2, 2.2)

            elif style == "core":
                # Reator compacto: borda escura, núcleo branco/azul e arcos internos.
                grad = QRadialGradient(QPointF(cx + jitter, cy), radius * 1.12)
                grad.setColorAt(0.0, QColor(248, 253, 255, 255))
                grad.setColorAt(0.12, QColor(*bright, 255))
                grad.setColorAt(0.30, QColor(*main, 245))
                grad.setColorAt(0.64, QColor(*dark, 245))
                grad.setColorAt(1.0, QColor(2, 10, 22, 250))
                painter.setPen(QPen(QColor(*bright, 205), 1.8))
                painter.setBrush(grad)
                painter.drawEllipse(QPointF(cx + jitter, cy), radius, radius)
                painter.setBrush(Qt.NoBrush)
                for i in range(3):
                    rr = radius * (0.42 + i * 0.17)
                    rect = QRectF(cx - rr + jitter, cy - rr, rr * 2, rr * 2)
                    painter.setPen(QPen(QColor(*bright, 205 - i * 45), 1.5))
                    rot = (self.phase * (95 - i * 14) + i * 97) % 360
                    painter.drawArc(rect, int(rot * 16), int((115 - i * 15) * 16))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(250, 254, 255, 205))
                painter.drawEllipse(QPointF(cx + jitter, cy), 8.0 + self.smooth_level * 3.0, 8.0 + self.smooth_level * 3.0)

            elif style == "pulse":
                # Pulso orgânico: respiração visual contínua e pouca geometria HUD.
                grad = QRadialGradient(QPointF(cx - radius * 0.18 + jitter, cy - radius * 0.22), radius * 1.30)
                grad.setColorAt(0.0, QColor(245, 253, 255, 245))
                grad.setColorAt(0.20, QColor(*bright, 235))
                grad.setColorAt(0.62, QColor(*main, 205))
                grad.setColorAt(1.0, QColor(*dark, 215))
                painter.setPen(QPen(QColor(*bright, 145), 1.4))
                painter.setBrush(grad)
                painter.drawEllipse(QPointF(cx + jitter, cy), radius * 0.94, radius * 0.94)
                painter.setBrush(Qt.NoBrush)
                breathe = 5.0 + abs(math.sin(self.phase * 1.25)) * 8.0 + self.smooth_level * 8.0
                for i in range(2):
                    rr = radius + breathe + i * 10.0
                    painter.setPen(QPen(QColor(*bright, 105 - i * 35), 1.5 - i * 0.25))
                    painter.drawEllipse(QPointF(cx + jitter, cy), rr, rr)

            elif style == "minimal":
                # Uma presença limpa: volume suave, um único contorno e pulso.
                grad = QRadialGradient(QPointF(cx - radius * 0.22 + jitter, cy - radius * 0.26), radius * 1.22)
                grad.setColorAt(0.0, QColor(*bright, 235))
                grad.setColorAt(0.35, QColor(*main, 220))
                grad.setColorAt(1.0, QColor(*dark, 235))
                painter.setPen(QPen(QColor(*bright, 175), 1.4))
                painter.setBrush(grad)
                painter.drawEllipse(QPointF(cx + jitter, cy), radius * 0.88, radius * 0.88)
                painter.setBrush(Qt.NoBrush)
                rr = radius + 4 + (self.smooth_level * 9 if listening else abs(math.sin(self.phase * 1.4)) * 2)
                painter.setPen(QPen(QColor(*bright, 145), 1.35))
                painter.drawEllipse(QPointF(cx + jitter, cy), rr, rr)

            else:
                # Cristal: esfera 3D original, refinada.
                grad = QRadialGradient(QPointF(cx - radius * 0.34 + jitter, cy - radius * 0.38), radius * 1.30)
                grad.setColorAt(0.0, QColor(244, 252, 255, 255))
                grad.setColorAt(0.10, QColor(*bright, 255))
                grad.setColorAt(0.30, QColor(*main, 255))
                mid = tuple(max(0, int(c * 0.72)) for c in main)
                grad.setColorAt(0.66, QColor(*mid, 255))
                grad.setColorAt(1.0, QColor(*dark, 255))
                painter.setPen(QPen(QColor(*bright, 190), 1.6))
                painter.setBrush(grad)
                painter.drawEllipse(QPointF(cx + jitter, cy), radius, radius)
                rim = QRectF(cx - radius + jitter, cy - radius, radius * 2, radius * 2)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(*bright, 155), 1.9))
                painter.drawArc(rim, int(205 * 16), int(118 * 16))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(246, 253, 255, 105))
                painter.drawEllipse(QRectF(cx - radius * 0.55 + jitter, cy - radius * 0.55, radius * 0.57, radius * 0.28))

            if self.compact:
                return

            if thinking:
                painter.setBrush(QColor(*bright, 230))
                painter.setPen(Qt.NoPen)
                for i in range(7):
                    a = self.phase * 1.8 + i * (math.tau / 7)
                    rr = 25 + (i % 3) * 7
                    painter.drawEllipse(QPointF(cx + jitter + math.cos(a) * rr, cy + math.sin(a) * rr * 0.56), 2.4, 2.4)

            state_labels = {
                "REPOUSO": "OCIOSO",
                "AGUARDANDO": "AGUARDANDO",
                "OUVINDO": "OUVINDO",
                "ESCUTANDO": "OUVINDO",
                "ESPERANDO_RESPOSTA": "ESPERANDO RESPOSTA",
                "ENTENDENDO": "ENTENDENDO",
                "PENSANDO": "PENSANDO",
                "PROCESSANDO": "PENSANDO",
                "FALANDO": "FALANDO",
                "EXECUTANDO": "EXECUTANDO",
                "RECONECTANDO": "RECONECTANDO",
                "PREPARANDO": "AGUARDANDO",
                "ERRO": "ERRO",
                "SEM_MICROFONE": "SEM MICROFONE",
            }
            state_text = "MOVER" if self.move_mode else state_labels.get(state, state)
            state_font = QFont("Segoe UI", 10)
            state_font.setWeight(QFont.Bold)
            metrics = QFontMetrics(state_font)
            state_w = metrics.horizontalAdvance(state_text)
            state_x = max(8.0, (self.WIDTH - state_w) / 2.0)
            state_baseline = 208.0
            path = QPainterPath()
            path.addText(QPointF(state_x, state_baseline), state_font, state_text)
            painter.setPen(QPen(QColor(0, 0, 0, 230), 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(*bright, 255))
            painter.drawPath(path)

            # Telemetria de microfone abaixo da esfera.
            metrics_data = self.audio_metrics or {}
            voice_pct = int(metrics_data.get("voice", 0) or 0)
            noise_pct = int(metrics_data.get("noise", 0) or 0)
            gate_pct = int(metrics_data.get("gate", 0) or 0)
            quality = str(metrics_data.get("quality") or "").strip()
            capturing = bool(metrics_data.get("capturing", False))
            if capturing:
                metric_text = f"VOZ {voice_pct}%  •  RUÍDO {noise_pct}%  •  GATE {gate_pct}%"
            else:
                metric_text = f"RUÍDO {noise_pct}%  •  GATE {gate_pct}%"
            metric_font = QFont("Segoe UI", 8)
            metric_font.setWeight(QFont.DemiBold)
            mm = QFontMetrics(metric_font)
            mw = mm.horizontalAdvance(metric_text)
            mx = max(5.0, (self.WIDTH - mw) / 2.0)
            my = 226.0
            if noise_pct >= 34:
                metric_color = QColor(255, 94, 94, 245)
            elif noise_pct >= 22:
                metric_color = QColor(255, 205, 74, 245)
            else:
                metric_color = QColor(138, 236, 190, 245)
            metric_path = QPainterPath()
            metric_path.addText(QPointF(mx, my), metric_font, metric_text)
            painter.setPen(QPen(QColor(0, 0, 0, 225), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(metric_path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(metric_color)
            painter.drawPath(metric_path)

            if quality and noise_pct >= 22:
                qfont = QFont("Segoe UI", 7)
                qm = QFontMetrics(qfont)
                qw = qm.horizontalAdvance(quality)
                qx = max(5.0, (self.WIDTH - qw) / 2.0)
                qp = QPainterPath()
                qp.addText(QPointF(qx, 240.0), qfont, quality)
                painter.setPen(QPen(QColor(0, 0, 0, 220), 2.0))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(qp)
                painter.setPen(Qt.NoPen)
                painter.setBrush(metric_color)
                painter.drawPath(qp)

            # Legenda V7: mais texto, fonte adaptativa e painel translúcido.
            # WordBoundary fornece uma janela rolante durante a fala; quando nao
            # houver timings, ainda mostramos ate 5 linhas sem cortar a janela.
            if self.caption_visible:
                text_len = len(self.caption_visible)
                font_size = 12 if text_len <= 120 else (11 if text_len <= 240 else 10)
                font = QFont("Segoe UI", font_size)
                font.setWeight(QFont.Bold)
                max_width = max(180, self.width() - 28)
                lines = self._wrapped_lines(self.caption_visible, font, max_width - 18, 5)
                metrics = QFontMetrics(font)
                line_h = metrics.height() + 2
                y = 246.0
                panel_h = max(28.0, len(lines) * line_h + 14.0)
                panel = QRectF(10.0, y - 7.0, self.width() - 20.0, panel_h)
                painter.setPen(QPen(QColor(0, 0, 0, 80), 1.0))
                painter.setBrush(QColor(0, 0, 0, 128))
                painter.drawRoundedRect(panel, 10.0, 10.0)
                for line in lines:
                    w = metrics.horizontalAdvance(line)
                    x = max(14.0, (self.width() - w) / 2.0)
                    baseline = y + metrics.ascent()
                    self._draw_outlined_text(painter, line, x, baseline, font, self.caption_speaker)
                    y += line_h

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    overlay = Overlay()
    bridge = Bridge()
    bridge.command.connect(overlay.command)

    def read_commands():
        for line in sys.stdin:
            try:
                payload = json.loads(line)
                bridge.command.emit(payload)
                if payload.get("cmd") == "quit":
                    break
            except Exception:
                continue

    thread = threading.Thread(target=read_commands, daemon=True)
    thread.start()
    sys.exit(app.exec())


if __name__ == "__main__" and ("--child" in sys.argv or "--voice-overlay-child" in sys.argv):
    _run_child()
