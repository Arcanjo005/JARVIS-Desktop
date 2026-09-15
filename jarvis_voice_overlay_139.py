"""JARVIS 1.3.9 voice overlay compatibility layer.

Keeps the proven Qt renderer from voice_overlay_qt.py but changes positioning so
movement is constrained by the *visible sphere*, not by the transparent subtitle
canvas. This removes the apparent invisible wall users hit while dragging the
orb in conversation mode.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import voice_overlay_qt as _legacy

OVERLAY_FULL_WIDTH = _legacy.OVERLAY_FULL_WIDTH
OVERLAY_FULL_HEIGHT = _legacy.OVERLAY_FULL_HEIGHT
OVERLAY_COMPACT_SIZE = _legacy.OVERLAY_COMPACT_SIZE
ORB_RADIUS = _legacy.ORB_RADIUS

_VISIBLE_MARGIN = 8
_VISIBLE_RADIUS = max(36, int(round(ORB_RADIUS + 14)))
_CHILD_ENV_FLAG = "JARVIS_OVERLAY_139"


def _visible_orb_geometry(width: int, height: int):
    width = max(1, int(width))
    height = max(1, int(height))
    if width > OVERLAY_COMPACT_SIZE or height > OVERLAY_COMPACT_SIZE:
        return width // 2, 38, _VISIBLE_RADIUS
    return width // 2, height // 2, _VISIBLE_RADIUS


def clamp_overlay_position(x, y, width, height, left, top, right, bottom, margin=0):
    """Clamp only the visible orb, allowing transparent canvas to cross edges."""
    x = int(x); y = int(y)
    left = int(left); top = int(top); right = int(right); bottom = int(bottom)
    cx, cy, radius = _visible_orb_geometry(width, height)
    safe = max(_VISIBLE_MARGIN, int(margin or 0))
    min_x = left + safe + radius - cx
    max_x = right - safe - radius - cx
    min_y = top + safe + radius - cy
    max_y = bottom - safe - radius - cy
    if max_x < min_x:
        max_x = min_x
    if max_y < min_y:
        max_y = min_y
    return max(min_x, min(x, max_x)), max(min_y, min(y, max_y))


def corner_overlay_position(width, height, left, top, right, bottom, margin=0):
    """Put the visible orb in the lower-right corner, independent of canvas size."""
    cx, cy, radius = _visible_orb_geometry(width, height)
    safe = max(_VISIBLE_MARGIN, int(margin or 0))
    x = int(right) - safe - radius - cx
    y = int(bottom) - safe - radius - cy
    return clamp_overlay_position(x, y, width, height, left, top, right, bottom, safe)


class QtVoiceOverlayController(_legacy.QtVoiceOverlayController):
    """Legacy controller with a tagged child so the frozen EXE uses this layer."""

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
            child_env = os.environ.copy()
            child_env[_CHILD_ENV_FLAG] = "1"
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
                env=child_env,
            )
            self._log("info", "Overlay 3D 1.3.9 iniciado com movimento pela esfera visivel.")
            return True
        except Exception as exc:
            self.process = None
            self._log("warning", f"Falha ao iniciar overlay 3D 1.3.9: {exc}")
            return False


def _run_child():
    # The legacy child resolves these globals dynamically inside its Overlay
    # methods, so replacing them before construction changes only positioning;
    # rendering, subtitles, state animation and IPC stay untouched.
    _legacy.clamp_overlay_position = clamp_overlay_position
    _legacy.corner_overlay_position = corner_overlay_position
    _legacy.OVERLAY_EDGE_MARGIN = 0
    return _legacy._run_child()


if __name__ == "__main__" and "--child" in sys.argv:
    raise SystemExit(_run_child())


__all__ = [
    "QtVoiceOverlayController",
    "OVERLAY_FULL_WIDTH",
    "OVERLAY_FULL_HEIGHT",
    "clamp_overlay_position",
    "corner_overlay_position",
    "_run_child",
]
