"""JARVIS runtime helpers: crash log, diretórios ativos e Windows helpers."""
from __future__ import annotations

# This module is generated from the legacy runtime implementation below to keep
# a canonical JARVIS import path while retaining backwards compatibility.
import os
import sys
import threading
from datetime import datetime
from pathlib import Path


def ensure_runtime_dirs(project_dir=None):
    root = Path(project_dir or os.getcwd())
    for name in ("data", "logs", "screenshots"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _write_crash(exc_type, exc_value, exc_tb, project_dir=None):
    import traceback
    root = ensure_runtime_dirs(project_dir)
    path = root / "logs" / "jarvis_crash.log"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n[{stamp}] UNHANDLED EXCEPTION\n")
        traceback.print_exception(exc_type, exc_value, exc_tb, file=f)


def install_exception_hooks(project_dir=None):
    def sys_hook(exc_type, exc_value, exc_tb):
        _write_crash(exc_type, exc_value, exc_tb, project_dir)
        try:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        except Exception:
            pass

    sys.excepthook = sys_hook

    if hasattr(threading, "excepthook"):
        old_thread_hook = threading.excepthook

        def thread_hook(args):
            _write_crash(args.exc_type, args.exc_value, args.exc_traceback, project_dir)
            try:
                old_thread_hook(args)
            except Exception:
                pass

        threading.excepthook = thread_hook


def foreground_window_title():
    if os.name != "nt":
        return ""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value.strip()
    except Exception:
        return ""
