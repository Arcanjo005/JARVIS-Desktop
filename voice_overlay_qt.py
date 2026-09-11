"""JARVIS voice orb - single small 3D Qt/PySide6 overlay.

The orb keeps the exact small idle footprint in every state. Conversation mode
only expands the transparent caption canvas below it; the sphere itself never
switches to a larger competing variant. Captions use a cinema-style yellow fill
with a strong black outline for readability on any desktop background.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Optional, Tuple

from jarvis_identity import env as jarvis_env

try:
    from text_sanitizer import sanitize_text
except Exception:
    def sanitize_text(text, *, limit=260, preserve_newlines=False):
        value = unicodedata.normalize("NFC", str(text or "")).replace("\ufffd", "")
        value = "".join(ch for ch in value if not unicodedata.category(ch).startswith("C"))
        value = " ".join(value.split()).strip()
        return value[:limit] if limit and len(value) > limit else value


VOICE_ORB_OPACITY = max(0.76, min(float(jarvis_env("VOICE_ORB_OPACITY", "0.98")), 1.0))
OVERLAY_FULL_WIDTH = 420
OVERLAY_FULL_HEIGHT = 160
OVERLAY_COMPACT_SIZE = 88
OVERLAY_EDGE_MARGIN = 18
ORB_RADIUS = 24.0


def clamp_overlay_position(x, y, width, height, left, top, right, bottom, margin=OVERLAY_EDGE_MARGIN):
    width = max(1, int(width)); height = max(1, int(height))
    left = int(left); top = int(top); right = int(right); bottom = int(bottom)
    margin = max(0, int(margin))
    min_x = left + margin; min_y = top + margin
    max_x = max(min_x, right - width - margin)
    max_y = max(min_y, bottom - height - margin)
    return max(min_x, min(int(x), max_x)), max(min_y, min(int(y), max_y))


def corner_overlay_position(width, height, left, top, right, bottom, margin=OVERLAY_EDGE_MARGIN):
    return clamp_overlay_position(
        int(right) - int(width) - int(margin),
        int(bottom) - int(height) - int(margin),
        width, height, left, top, right, bottom, margin,
    )


class QtVoiceOverlayController:
    """Controller used by gui.py. Communication is newline-delimited JSON."""

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
        self._last_caption_at = 0.0
        self._last_level = 0.0
        self._last_audio_metrics = {}
        self._last_compact = True
        self._last_opacity = VOICE_ORB_OPACITY
        self._conversation_lock = False
        self._move_mode = False
        self.position_path = self.project_dir / "data" / "overlay_position.json"

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
        return bool(self.process and self.process.poll() is None)

    def start(self) -> bool:
        if not self.available:
            self._log("warning", "PySide6 indisponivel; overlay 3D Qt nao iniciado.")
            return False
        if self.is_alive():
            return True
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
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
            self._log("info", "Overlay 3D compacto iniciado.")
            return True
        except Exception as exc:
            self.process = None
            self._log("warning", f"Falha ao iniciar overlay 3D: {exc}")
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
        self._raw_send({"cmd": "conversation_lock", "value": self._conversation_lock})
        self._raw_send({"cmd": "state", "value": self._last_state})
        self._raw_send({"cmd": "level", "value": self._last_level})
        self._raw_send({"cmd": "audio_metrics", "value": self._last_audio_metrics})
        self._raw_send({"cmd": "compact", "value": True})
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
        self._log("warning", "Overlay 3D caiu; reiniciando.")
        return self.start() and self._restore_visible_state()

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
        self._last_state = str(state or "REPOUSO").upper()
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "state", "value": self._last_state}) if self.is_alive() else False

    def set_conversation_lock(self, enabled: bool):
        # API compatibility: this flag controls caption layout only. It never
        # changes orb size and never forces OUVINDO.
        self._conversation_lock = bool(enabled)
        self._last_compact = True
        if self._visible and not self._recover_if_visible():
            return False
        if not self.is_alive():
            return False
        ok = self._raw_send({"cmd": "conversation_lock", "value": self._conversation_lock})
        self._raw_send({"cmd": "compact", "value": True})
        return ok

    def set_level(self, level: float):
        try:
            self._last_level = max(0.0, min(float(level), 1.0))
        except Exception:
            self._last_level = 0.0
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "level", "value": self._last_level}) if self.is_alive() else False

    def set_audio_metrics(self, metrics: dict):
        self._last_audio_metrics = dict(metrics or {})
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "audio_metrics", "value": self._last_audio_metrics}) if self.is_alive() else False

    def set_caption(self, text: str, speaker: str = "assistant"):
        incoming = sanitize_text(text, limit=360)
        speaker_key = "user" if str(speaker).lower() == "user" else "assistant"

        # gui.py clears captions on ENTENDENDO/PENSANDO transitions. Preserve
        # the user's latest transcript briefly so conversation mode can show
        # what JARVIS actually understood until the assistant starts replying.
        if not incoming:
            keep_user_caption = (
                self._last_caption
                and self._last_caption_speaker == "user"
                and self._last_state in {"ENTENDENDO", "PENSANDO", "PROCESSANDO"}
                and (time.monotonic() - self._last_caption_at) < 3.0
            )
            if keep_user_caption:
                return True

        self._last_caption = incoming
        self._last_caption_speaker = speaker_key
        self._last_caption_at = time.monotonic() if incoming else 0.0
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "caption", "value": self._last_caption, "speaker": self._last_caption_speaker}) if self.is_alive() else False

    def set_user_caption(self, text: str):
        return self.set_caption(text, speaker="user")

    def set_orb_style(self, style: str):
        return True

    def set_compact(self, enabled: bool):
        # One orb size only. Outside conversation the window stays compact;
        # conversation mode expands only the transparent subtitle canvas.
        self._last_compact = True
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "compact", "value": True}) if self.is_alive() else False

    def set_opacity(self, value: float):
        try:
            self._last_opacity = max(0.60, min(float(value), 1.0))
        except Exception:
            self._last_opacity = VOICE_ORB_OPACITY
        if self._visible and not self._recover_if_visible():
            return False
        return self._raw_send({"cmd": "opacity", "value": self._last_opacity}) if self.is_alive() else False

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
    from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QRadialGradient
    from PySide6.QtWidgets import QApplication, QWidget

    class Bridge(QObject):
        command = Signal(dict)

    class Overlay(QWidget):
        WIDTH = OVERLAY_FULL_WIDTH
        HEIGHT = OVERLAY_FULL_HEIGHT
        COMPACT_SIZE = OVERLAY_COMPACT_SIZE
        EDGE_MARGIN = OVERLAY_EDGE_MARGIN

        STATE_COLORS = {
            "REPOUSO": ((37, 126, 255), (176, 229, 255), (5, 34, 95)),
            "AGUARDANDO": ((37, 126, 255), (176, 229, 255), (5, 34, 95)),
            "PREPARANDO": ((50, 135, 255), (184, 232, 255), (6, 39, 102)),
            "OUVINDO": ((14, 207, 175), (166, 255, 236), (2, 72, 69)),
            "ESCUTANDO": ((14, 207, 175), (166, 255, 236), (2, 72, 69)),
            "ESPERANDO_RESPOSTA": ((14, 207, 175), (166, 255, 236), (2, 72, 69)),
            "ENTENDENDO": ((72, 187, 255), (194, 242, 255), (7, 62, 110)),
            "PENSANDO": ((133, 89, 255), (229, 210, 255), (42, 18, 108)),
            "PROCESSANDO": ((133, 89, 255), (229, 210, 255), (42, 18, 108)),
            "EXECUTANDO": ((255, 157, 69), (255, 232, 186), (111, 49, 5)),
            "FALANDO": ((33, 160, 255), (190, 239, 255), (4, 54, 128)),
            "RECONECTANDO": ((238, 173, 61), (255, 236, 184), (104, 61, 6)),
            "SEM_MICROFONE": ((238, 173, 61), (255, 236, 184), (104, 61, 6)),
            "ERRO": ((241, 82, 100), (255, 198, 205), (105, 13, 29)),
        }

        def __init__(self):
            super().__init__()
            flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
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
            self.compact = True
            self.conversation_mode = False
            self.caption = ""
            self.caption_speaker = "assistant"
            self.phase = 0.0
            self.move_mode = False
            self.drag_offset = None
            self._error_since = 0.0
            self.position_path = Path(os.environ.get("JARVIS_APP_DIR") or Path(__file__).resolve().parent) / "data" / "overlay_position.json"
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._tick)
            self.timer.start(16)

        def _screen_for_point(self, x=None, y=None):
            try:
                point = self.frameGeometry().center() if x is None or y is None else QPoint(int(x), int(y))
                return QApplication.screenAt(point) or QApplication.primaryScreen()
            except Exception:
                return QApplication.primaryScreen()

        def _work_rect(self, screen=None):
            screen = screen or self._screen_for_point()
            try:
                geo = screen.availableGeometry()
                return int(geo.x()), int(geo.y()), int(geo.x()+geo.width()), int(geo.y()+geo.height())
            except Exception:
                return 0, 0, max(self.width(), 1), max(self.height(), 1)

        def _move_clamped(self, x, y, screen=None):
            screen = screen or self._screen_for_point(int(x)+self.width()//2, int(y)+self.height()//2)
            left, top, right, bottom = self._work_rect(screen)
            nx, ny = clamp_overlay_position(x, y, self.width(), self.height(), left, top, right, bottom, self.EDGE_MARGIN)
            self.move(int(nx), int(ny))
            return int(nx), int(ny)

        def _anchor_bottom_right(self, screen=None):
            screen = screen or self._screen_for_point()
            left, top, right, bottom = self._work_rect(screen)
            x, y = corner_overlay_position(self.width(), self.height(), left, top, right, bottom, self.EDGE_MARGIN)
            self.move(int(x), int(y))

        def _apply_window_mode(self):
            # The sphere is always the same size. Conversation mode changes only
            # the transparent area available for subtitles.
            w, h = (self.WIDTH, self.HEIGHT) if self.conversation_mode else (self.COMPACT_SIZE, self.COMPACT_SIZE)
            if self.width() != w or self.height() != h:
                screen = self._screen_for_point()
                self.resize(w, h)
                self._anchor_bottom_right(screen)
            elif not self.move_mode:
                self._anchor_bottom_right(self._screen_for_point())

        def _tick(self):
            self.phase = (self.phase + 0.045) % (math.pi * 400.0)
            attack = 0.46 if self.level > self.smooth_level else 0.14
            self.smooth_level += (self.level - self.smooth_level) * attack
            if self.state == "ERRO" and self._error_since and time.monotonic() - self._error_since > 2.5:
                self.state = "RECONECTANDO"
            self.update()

        def command(self, payload: dict):
            cmd = payload.get("cmd")
            if cmd == "show":
                self._apply_window_mode(); self.show(); self.raise_()
            elif cmd == "hide":
                self.hide()
            elif cmd == "state":
                requested = str(payload.get("value") or "REPOUSO").upper()
                self.state = requested
                self._error_since = time.monotonic() if requested == "ERRO" else 0.0
                self.update()
            elif cmd == "conversation_lock":
                self.conversation_mode = bool(payload.get("value", False))
                self.compact = True
                self._apply_window_mode(); self.update()
            elif cmd == "level":
                try: self.level = max(0.0, min(float(payload.get("value", 0.0)), 1.0))
                except Exception: self.level = 0.0
            elif cmd == "audio_metrics":
                value = payload.get("value") or {}; self.audio_metrics = dict(value) if isinstance(value, dict) else {}
            elif cmd == "orb_style":
                pass
            elif cmd == "compact":
                self.compact = True
                self._apply_window_mode(); self.update()
            elif cmd == "opacity":
                try: self.setWindowOpacity(max(0.60, min(float(payload.get("value", VOICE_ORB_OPACITY)), 1.0)))
                except Exception: pass
            elif cmd == "caption":
                self.caption = sanitize_text(payload.get("value") or "", limit=360)
                self.caption_speaker = "user" if str(payload.get("speaker") or "assistant").lower() == "user" else "assistant"
                self.update()
            elif cmd == "position":
                self._move_clamped(int(payload.get("x", self.x())), int(payload.get("y", self.y())))
            elif cmd == "move_mode":
                self.move_mode = bool(payload.get("value", True)); self.show(); self.raise_(); self.update()
            elif cmd == "quit":
                QApplication.instance().quit()

        def mousePressEvent(self, event):
            if event.button() == Qt.LeftButton:
                self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self.move_mode = True; event.accept(); return
            event.ignore()

        def mouseMoveEvent(self, event):
            if self.drag_offset is not None and (event.buttons() & Qt.LeftButton):
                wanted = event.globalPosition().toPoint() - self.drag_offset
                self._move_clamped(wanted.x(), wanted.y(), QApplication.screenAt(event.globalPosition().toPoint()) or self._screen_for_point())
                event.accept(); return
            event.ignore()

        def mouseReleaseEvent(self, event):
            if event.button() == Qt.LeftButton and self.drag_offset is not None:
                self.drag_offset = None; self.move_mode = False
                try:
                    self.position_path.parent.mkdir(parents=True, exist_ok=True)
                    self.position_path.write_text(json.dumps({"x": int(self.x()), "y": int(self.y())}), encoding="utf-8")
                except Exception:
                    pass
                event.accept(); return
            event.ignore()

        def _state_palette(self):
            return self.STATE_COLORS.get(self.state, self.STATE_COLORS["REPOUSO"])

        def _draw_orb(self, painter, cx, cy):
            main, bright, dark = self._state_palette()
            r = ORB_RADIUS
            listening = self.state in {"OUVINDO", "ESCUTANDO", "ESPERANDO_RESPOSTA"}
            speaking = self.state == "FALANDO"

            # No size pulse: the requested identity is always the same small orb.
            # Reactivity only changes light/glow intensity.
            reactive = min(1.0, self.smooth_level) if listening else (0.45 + 0.25*math.sin(self.phase*3.0) if speaking else 0.20)
            glow_scale = 1.0 + 0.30 * reactive
            for extra, alpha in ((14, int(12*glow_scale)), (8, int(24*glow_scale)), (4, int(42*glow_scale))):
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(*main, max(6, min(alpha, 72))))
                painter.drawEllipse(QPointF(cx, cy), r + extra, r + extra)

            sphere = QPainterPath(); sphere.addEllipse(QPointF(cx, cy), r, r)
            painter.save(); painter.setClipPath(sphere)

            grad = QRadialGradient(QPointF(cx-r*0.34, cy-r*0.38), r*1.34)
            grad.setColorAt(0.00, QColor(255,255,255,255))
            grad.setColorAt(0.08, QColor(*bright,253))
            grad.setColorAt(0.30, QColor(*main,250))
            mid = tuple(max(0, int(v*0.62)) for v in main)
            grad.setColorAt(0.68, QColor(*mid,250))
            grad.setColorAt(1.00, QColor(*dark,255))
            painter.setPen(Qt.NoPen); painter.setBrush(grad); painter.drawPath(sphere)

            # Thin internal arcs rotate inside the sphere, giving depth without
            # recreating the old concentric-reactor look.
            angle = (self.phase * 18.0) % 360.0
            painter.translate(cx, cy); painter.rotate(angle)
            painter.setPen(QPen(QColor(*bright, 50), 1.0, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(QRectF(-r*0.76, -r*0.24, r*1.52, r*0.48), int(205*16), int(128*16))
            painter.drawArc(QRectF(-r*0.58, -r*0.38, r*1.16, r*0.76), int(24*16), int(112*16))
            painter.rotate(-angle)

            sweep_x = math.cos(self.phase*0.82) * r*0.18
            sweep_y = math.sin(self.phase*0.67) * r*0.10
            caustic = QRadialGradient(QPointF(sweep_x-r*0.14, sweep_y-r*0.11), r*0.72)
            caustic.setColorAt(0.0, QColor(255,255,255,58))
            caustic.setColorAt(0.35, QColor(*bright,34))
            caustic.setColorAt(1.0, QColor(*main,0))
            painter.setPen(Qt.NoPen); painter.setBrush(caustic)
            painter.drawEllipse(QPointF(0,0), r*0.92, r*0.92)
            painter.restore()

            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(*bright, 136), 1.0))
            painter.drawEllipse(QPointF(cx, cy), r-0.5, r-0.5)
            hi = QRadialGradient(QPointF(cx-r*0.38, cy-r*0.42), r*0.42)
            hi.setColorAt(0.0, QColor(255,255,255,184)); hi.setColorAt(1.0, QColor(255,255,255,0))
            painter.setPen(Qt.NoPen); painter.setBrush(hi)
            painter.drawEllipse(QPointF(cx-r*0.28, cy-r*0.31), r*0.42, r*0.34)

            a = self.phase * 1.05
            ox = cx + math.cos(a) * r*0.82
            oy = cy + math.sin(a) * r*0.40
            painter.setBrush(QColor(*bright, 225)); painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(ox, oy), 1.5, 1.5)

        def _wrapped_lines(self, text, font, max_width, max_lines=3):
            clean = " ".join(str(text or "").split())
            if not clean: return []
            metrics = QFontMetrics(font); words = clean.split(); lines=[]; current=""
            for word in words:
                trial = f"{current} {word}".strip()
                if metrics.horizontalAdvance(trial) <= max_width:
                    current = trial; continue
                if current: lines.append(current)
                current = word
                if len(lines) >= max_lines: break
            if current and len(lines) < max_lines: lines.append(current)
            if " ".join(lines) != clean and lines:
                last = lines[-1]
                while last and metrics.horizontalAdvance(last + "...") > max_width:
                    last = last[:-1].rstrip()
                lines[-1] = last + "..."
            return lines[:max_lines]

        def _draw_cinema_subtitle(self, painter, text, speaker, center_x, start_y):
            prefix = "VOCÊ: " if speaker == "user" else "JARVIS: "
            full = prefix + text
            font = QFont("Segoe UI", 11)
            font.setBold(True)
            lines = self._wrapped_lines(full, font, self.width()-40, max_lines=3)
            metrics = QFontMetrics(font)
            y = float(start_y)
            for line in lines:
                width = metrics.horizontalAdvance(line)
                baseline = y + metrics.ascent()
                path = QPainterPath()
                path.addText(QPointF(center_x-width/2.0, baseline), font, line)

                # Classic cinema subtitle: high-contrast black outline/shadow
                # around a warm yellow glyph, rendered as vector paths.
                painter.setBrush(QColor(0,0,0,0))
                painter.setPen(QPen(QColor(0,0,0,245), 4.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawPath(path)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 216, 64, 255))
                painter.drawPath(path)
                y += metrics.height() + 3

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

            if not self.conversation_mode:
                self._draw_orb(painter, self.width()/2.0, self.height()/2.0)
                return

            cx = self.width()/2.0
            self._draw_orb(painter, cx, 38.0)
            if self.caption:
                self._draw_cinema_subtitle(painter, self.caption, self.caption_speaker, cx, 80.0)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    overlay = Overlay()
    bridge = Bridge()
    bridge.command.connect(overlay.command)

    def reader():
        for line in sys.stdin:
            try:
                payload = json.loads(line)
            except Exception:
                continue
            bridge.command.emit(payload)

    threading.Thread(target=reader, name="JARVIS-OVERLAY-COMMANDS", daemon=True).start()
    return app.exec()


if __name__ == "__main__":
    if "--child" in sys.argv:
        raise SystemExit(_run_child())
