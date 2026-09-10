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
_RESTART_AFTER_PID_SWITCH = "--restart-after-pid"
_RUNTIME_SELFTEST_SWITCH = "--runtime-selftest"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _pop_switch_value(name: str) -> str:
    try:
        index = sys.argv.index(name)
    except ValueError:
        return ""
    value = ""
    if index + 1 < len(sys.argv):
        value = str(sys.argv[index + 1] or "").strip()
        del sys.argv[index:index + 2]
    else:
        del sys.argv[index:index + 1]
    return value


def _wait_for_restart_parent() -> None:
    """Helper-process mode: wait for the old JARVIS PID before normal boot."""
    raw_pid = _pop_switch_value(_RESTART_AFTER_PID_SWITCH)
    if not raw_pid:
        return
    try:
        pid = int(raw_pid)
    except Exception:
        return
    if pid <= 0 or pid == os.getpid():
        return
    if os.name == "nt":
        try:
            SYNCHRONIZE = 0x00100000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
            open_process.restype = ctypes.c_void_p
            wait_for_single = kernel32.WaitForSingleObject
            wait_for_single.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            wait_for_single.restype = ctypes.c_uint32
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_bool
            handle = open_process(SYNCHRONIZE, False, pid)
            if handle:
                try:
                    wait_for_single(handle, 20000)
                finally:
                    close_handle(handle)
                return
        except Exception:
            pass
    try:
        import time
        time.sleep(1.2)
    except Exception:
        pass


def _activate_runtime(base: Path, *, track_boot: bool):
    """Load a validated AppData hot runtime before importing JARVIS modules."""
    os.environ["JARVIS_APP_DIR"] = str(base)
    try:
        from hot_update_runtime import activate_hot_runtime
        return activate_hot_runtime(base, track_boot=track_boot)
    except Exception as exc:
        _write_critical_error(f"Hot runtime ignorado: {exc}")
        return None



def _run_runtime_selftest(base: Path) -> None:
    """Frozen-build smoke test used by CI before publishing an installer.

    This does not open the microphone or any GUI. It verifies that the modules
    and native assets required by voice, tray and overlay survived PyInstaller.
    The optional argument after --runtime-selftest is a JSON report path.
    """
    report_path = _pop_switch_value(_RUNTIME_SELFTEST_SWITCH)
    if report_path:
        target = Path(report_path)
        if not target.is_absolute():
            target = (base / target).resolve()
    else:
        target = base / "runtime_selftest.json"

    checks = {}
    failures = []

    def _report_value(value):
        # Import probes return module objects. They prove that the import worked,
        # but module objects are not JSON serializable. Keep structured/string
        # diagnostics when they are JSON-safe; otherwise store a simple True.
        if value is None:
            return True
        try:
            __import__("json").dumps(value, ensure_ascii=False)
        except (TypeError, ValueError, OverflowError):
            return True
        return value

    def probe(name, func):
        try:
            value = func()
            checks[name] = _report_value(value)
        except Exception as exc:
            checks[name] = False
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    _prepare_process_environment(base)
    os.environ["JARVIS_APP_DIR"] = str(base)

    probe("customtkinter", lambda: __import__("customtkinter"))
    probe("sounddevice", lambda: __import__("sounddevice"))
    probe("vosk", lambda: __import__("vosk"))
    probe("webrtcvad", lambda: __import__("webrtcvad"))
    probe("_webrtcvad", lambda: __import__("_webrtcvad"))
    probe("pystray", lambda: __import__("pystray"))
    probe("pystray_win32", lambda: __import__("pystray._win32", fromlist=["*"]))
    probe("pyside6", lambda: __import__("PySide6"))
    probe("voice_engine", lambda: __import__("voice_engine"))
    probe("desktop_integration", lambda: __import__("desktop_integration"))
    probe("overlay", lambda: __import__("voice_overlay_qt"))
    probe("send2trash", lambda: __import__("send2trash"))

    # CI pode preparar um hot runtime sintético e pedir que o EXE prove que
    # módulos externos em %LOCALAPPDATA% realmente têm precedência sobre o
    # PYZ embutido. Sem esta prova, um build poderia publicar um atualizador
    # "rápido" que baixa arquivos corretamente, mas continua executando a
    # cópia congelada antiga.
    expected_hot = str(os.environ.get("JARVIS_EXPECT_HOT_VERSION") or "").strip()
    if expected_hot:
        activation_box = {"value": None}

        def activate_hot_for_probe():
            activation = _activate_runtime(base, track_boot=False)
            activation_box["value"] = activation
            if activation is None or str(getattr(activation, "version", "")) != expected_hot:
                raise RuntimeError(f"hot runtime esperado {expected_hot} não foi ativado")
            return str(getattr(activation, "path", ""))

        def prove_hot_import_precedence():
            activation = activation_box.get("value")
            if activation is None:
                raise RuntimeError("hot runtime não foi ativado")
            import importlib
            sys.modules.pop("jarvis_version", None)
            module = importlib.import_module("jarvis_version")
            actual = str(getattr(module, "VERSION", ""))
            origin = Path(str(getattr(module, "__file__", "") or "")).resolve()
            runtime_path = Path(str(getattr(activation, "path", ""))).resolve()
            if actual != expected_hot:
                raise RuntimeError(f"import usou versão {actual or 'desconhecida'}, esperada {expected_hot}")
            try:
                origin.relative_to(runtime_path)
            except Exception as exc:
                raise RuntimeError(f"jarvis_version veio do bundle, não do hot runtime: {origin}") from exc
            return {"version": actual, "origin": str(origin)}

        probe("hot_runtime_activation", activate_hot_for_probe)
        probe("hot_runtime_import_precedence", prove_hot_import_precedence)

    model = base / "data" / "voice_models" / "vosk-model-small-pt-0.3"
    required_model_files = [
        model / "final.mdl",
        model / "Gr.fst",
        model / "HCLr.fst",
        model / "phones.txt",
        model / "mfcc.conf",
    ]
    missing = [str(path.relative_to(base)) for path in required_model_files if not path.is_file()]
    checks["wake_model_assets"] = not missing
    if missing:
        failures.append("wake_model_assets ausentes: " + ", ".join(missing))

    payload = {
        "ok": not failures,
        "frozen": bool(getattr(sys, "frozen", False)),
        "app_dir": str(base),
        "checks": checks,
        "failures": failures,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        _write_critical_error(f"Runtime selftest não conseguiu gravar relatório: {exc}")
        raise SystemExit(4)

    if failures:
        _write_critical_error("Runtime selftest falhou: " + " | ".join(failures))
        raise SystemExit(3)
    raise SystemExit(0)

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

    # PyInstaller --windowed pode entregar stdout/stderr como None. Algumas
    # bibliotecas de áudio/GUI ainda escrevem nesses objetos durante import;
    # manter handles para os.devnull evita falhas que só aparecem no .exe.
    if getattr(sys, "frozen", False):
        try:
            if sys.stdout is None:
                sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
            if sys.stderr is None:
                sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
        except Exception:
            pass

    # O Desktop alvo é Windows. Fixar o backend evita que o pystray tente
    # autodetectar backends não empacotados quando executado pelo PyInstaller.
    if os.name == "nt":
        os.environ.setdefault("PYSTRAY_BACKEND", "win32")


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
    _prepare_process_environment(base)
    os.environ["JARVIS_APP_DIR"] = str(base)

    if _RUNTIME_SELFTEST_SWITCH in sys.argv:
        _run_runtime_selftest(base)
        return

    # Hot-update restart helper waits before the single-instance mutex so the
    # old process has time to release it. The switch is removed afterwards.
    _wait_for_restart_parent()

    # PyInstaller helper processes are dispatched without participating in the
    # main-window boot-health counter. They still use the active hot runtime.
    if _OVERLAY_CHILD_SWITCH in sys.argv:
        _activate_runtime(base, track_boot=False)
        _run_overlay_child(base)
        return

    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass

    helper_mode = _CONFIGURE_API_SWITCH in sys.argv or _ENSURE_API_SWITCH in sys.argv
    if helper_mode:
        _activate_runtime(base, track_boot=False)
    else:
        if not _acquire_main_instance():
            return
        _activate_runtime(base, track_boot=True)

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
        try:
            from hot_update_runtime import mark_hot_runtime_healthy
            mark_hot_runtime_healthy()
        except Exception:
            pass
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
