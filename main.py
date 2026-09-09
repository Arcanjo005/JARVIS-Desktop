#!/usr/bin/env python3
"""JARVIS Desktop entry point.

The desktop build bootstraps per-user secrets before importing the AI stack so
an installed JARVIS does not depend on Python, Git or a plaintext API key file.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


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


def _bootstrap_configuration(base: Path) -> None:
    os.chdir(base)
    sys.path.insert(0, str(base))
    from secure_settings import bootstrap_secrets_to_env, migrate_legacy_env

    # Existing Build 16 installations can carry GEMINI_API_KEY in .env. On the
    # first Desktop launch it is moved into Windows DPAPI storage.
    try:
        migrate_legacy_env(base)
    except Exception:
        pass
    key = bootstrap_secrets_to_env()

    configure_only = "--configure-api" in sys.argv
    skip_first_run = "--no-first-run" in sys.argv
    if configure_only or (not key and not skip_first_run):
        try:
            from first_run_setup import show_api_key_dialog
            show_api_key_dialog(first_run=not configure_only)
        except Exception as exc:
            _write_critical_error(f"Falha ao abrir configuracao Gemini: {exc}")
        bootstrap_secrets_to_env()
    if configure_only:
        raise SystemExit(0)


def main() -> None:
    base = _app_dir()
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
