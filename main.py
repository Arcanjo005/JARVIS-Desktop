#!/usr/bin/env python3
"""JARVIS Desktop entry point.

The desktop build bootstraps per-user secrets before importing the AI stack so
an installed JARVIS does not depend on Python, Git or a plaintext API key file.
"""
from __future__ import annotations

import ctypes
import os
import sys
from datetime import datetime
from pathlib import Path

_MAIN_MUTEX_HANDLE = None
_MAIN_MUTEX_NAME = r"Local\JARVISDesktop.MainInstance"
_OVERLAY_CHILD_SWITCH = "--voice-overlay-child"
_CONFIGURE_API_SWITCH = "--configure-api"
_ENSURE_API_SWITCH = "--ensure-api"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _write_critical_error(message: object) -> None:
    base = _app_dir()
    try:
        from secure_settings import settings_dir
        error_dir = settings_dir() / "logs"
    except Exception:
        error_dir = base / "logs"
    try:
        error_dir.mkdir(parents=True, exist_ok=True)
        path = error_dir / "ERRO_CRITICO.txt"
        with path.open("a", encoding="utf-8") as handle:
            handle.write("JARVIS DESKTOP - ERRO CRITICO\n")
            handle.write("=" * 50 + "\n")
            handle.write(f"Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            handle.write(f"Sistema: {sys.platform}\n")
            handle.write(f"Aplicativo: {base}\n")
            handle.write(f"Erro: {message}\n\n")
    except Exception:
        pass


def _prepare_process_environment(base: Path) -> None:
    os.chdir(base)
    base_text = str(base)
    if base_text not in sys.path:
        sys.path.insert(0, base_text)


def _run_overlay_child(base: Path) -> None:
    """Run the Qt overlay inside the bundled executable without opening the GUI."""
    _prepare_process_environment(base)
    try:
        from voice_overlay_qt import _run_child
        _run_child()
    except SystemExit:
        raise
    except Exception as exc:
        _write_critical_error(f"Overlay Qt filho: {exc}")
        raise SystemExit(2)


def _acquire_main_instance() -> bool:
    """Keep one main JARVIS window per Windows user/session.

    Helper modes such as --configure-api and --voice-overlay-child bypass this
    function and therefore remain available while the main UI is running.
    """
    global _MAIN_MUTEX_HANDLE
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        create_mutex.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_bool

        ctypes.set_last_error(0)
        handle = create_mutex(None, False, _MAIN_MUTEX_NAME)
        if not handle:
            # Never make JARVIS unusable because the defensive mutex itself failed.
            return True
        error = ctypes.get_last_error()
        if error == 183:  # ERROR_ALREADY_EXISTS
            close_handle(handle)
            return False
        _MAIN_MUTEX_HANDLE = handle
        return True
    except Exception as exc:
        _write_critical_error(f"Trava de instancia unica indisponivel: {exc}")
        return True


def _bootstrap_configuration(base: Path) -> None:
    _prepare_process_environment(base)
    from secure_settings import bootstrap_secrets_to_env, migrate_legacy_env

    # Existing Build 16 installations can carry GEMINI_API_KEY in .env. On the
    # first Desktop launch it is moved into Windows DPAPI storage.
    try:
        migrate_legacy_env(base)
    except Exception:
        pass
    key = bootstrap_secrets_to_env()

    configure_only = _CONFIGURE_API_SWITCH in sys.argv
    ensure_only = _ENSURE_API_SWITCH in sys.argv
    skip_first_run = "--no-first-run" in sys.argv

    if configure_only:
        try:
            from first_run_setup import show_api_key_dialog
            show_api_key_dialog(first_run=False)
        except Exception as exc:
            _write_critical_error(f"Falha ao abrir configuracao Gemini: {exc}")
        bootstrap_secrets_to_env()
        raise SystemExit(0)

    if (not key) and (ensure_only or not skip_first_run):
        try:
            from first_run_setup import show_api_key_dialog
            # Normal first launch may be skipped. The installer's explicit
            # configuration mode uses --configure-api and has no skip button.
            show_api_key_dialog(first_run=not ensure_only)
        except Exception as exc:
            _write_critical_error(f"Falha ao abrir configuracao Gemini: {exc}")
        bootstrap_secrets_to_env()

    if ensure_only:
        raise SystemExit(0)


def main() -> None:
    base = _app_dir()

    # PyInstaller subprocesses must be dispatched before the single-instance
    # guard; otherwise a helper can accidentally become another JARVIS window.
    if _OVERLAY_CHILD_SWITCH in sys.argv:
        _run_overlay_child(base)
        return

    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass

    helper_mode = _CONFIGURE_API_SWITCH in sys.argv or _ENSURE_API_SWITCH in sys.argv
    if not helper_mode and not _acquire_main_instance():
        # A main window is already alive. Exit quietly instead of creating a
        # second UI (or a cascade if a helper process is misrouted).
        return

    try:
        _bootstrap_configuration(base)
    except SystemExit:
        raise
    except Exception as exc:
        _write_critical_error(f"Bootstrap: {exc}")

    try:
        import customtkinter as ctk
        from actions import SystemActions
        from core import JarvisCore
        from gui import JarvisGUI
        from logger import JarvisLogger
    except Exception as exc:
        _write_critical_error(f"Importacao: {exc}")
        if not getattr(sys, "frozen", False):
            print(f"Erro ao importar modulos: {exc}")
        raise SystemExit(1)

    try:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        logger = JarvisLogger()
        actions = SystemActions(logger)
        core = JarvisCore(logger)
        app = JarvisGUI(logger, actions, core)
        app.run()
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:
        _write_critical_error(f"Inicializacao: {exc}")
        try:
            print(f"Erro fatal na inicializacao: {exc}")
        except Exception:
            pass
        raise SystemExit(1)


if __name__ == "__main__":
    main()
