#!/usr/bin/env python3
"""JARVIS Desktop entry point for the single-source Qt UI."""
from __future__ import annotations

import ctypes
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

_MAIN_MUTEX_HANDLE = None
_MAIN_MUTEX_NAME = r"Local\JARVISDesktop.MainInstance"
_CONFIGURE_API_SWITCH = "--configure-api"
_ENSURE_API_SWITCH = "--ensure-api"
_RESTART_AFTER_PID_SWITCH = "--restart-after-pid"
_RUNTIME_SELFTEST_SWITCH = "--runtime-selftest"
_STARTUP_PHASE = "module-load"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _diagnostic_log_path() -> Path:
    try:
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        folder = local / "JARVIS" / "logs"
    except Exception:
        folder = _app_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "STARTUP_CRASH.txt"


def _write_startup_diagnostic(message: object, *, exc: BaseException | None = None) -> None:
    try:
        path = _diagnostic_log_path()
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write("\n" + "=" * 72 + "\n")
            handle.write("JARVIS DESKTOP - STARTUP DIAGNOSTIC\n")
            handle.write("=" * 72 + "\n")
            handle.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            handle.write(f"Phase: {_STARTUP_PHASE}\n")
            handle.write(f"PID: {os.getpid()}\n")
            handle.write(f"Frozen: {bool(getattr(sys, 'frozen', False))}\n")
            handle.write(f"Executable: {sys.executable}\n")
            handle.write(f"App dir: {_app_dir()}\n")
            handle.write(f"CWD: {Path.cwd()}\n")
            handle.write(f"argv: {sys.argv!r}\n")
            handle.write(f"Message: {message}\n")
            if exc is not None:
                handle.write(f"Type: {type(exc).__name__}\n")
                handle.write("Traceback:\n")
                handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            handle.write("\n")
    except Exception:
        pass


def _set_phase(name: str) -> None:
    global _STARTUP_PHASE
    _STARTUP_PHASE = str(name)
    try:
        with _diagnostic_log_path().open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PHASE: {_STARTUP_PHASE}\n")
    except Exception:
        pass


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
            handle.write("JARVIS DESKTOP - CRITICAL ERROR\n")
            handle.write("=" * 50 + "\n")
            handle.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            handle.write(f"System: {sys.platform}\n")
            handle.write(f"Application: {base}\n")
            handle.write(f"Error: {message}\n\n")
    except Exception:
        pass


def _prepare_process_environment(base: Path) -> None:
    os.chdir(base)
    base_text = str(base)
    if base_text not in sys.path:
        sys.path.insert(0, base_text)
    if getattr(sys, "frozen", False):
        try:
            if sys.stdout is None:
                sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
            if sys.stderr is None:
                sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
        except Exception:
            pass
    if os.name == "nt":
        os.environ.setdefault("PYSTRAY_BACKEND", "win32")


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
    os.environ["JARVIS_APP_DIR"] = str(base)
    try:
        from hot_update_runtime import activate_hot_runtime
        return activate_hot_runtime2(base, track_boot=track_boot)
    except Exception as exc:
        _write_critical_error(f"Hot runtime ignored: {exc}")
        _write_startup_diagnostic("Hot runtime activation failed; using bundle.", exc=exc)
        return None


def _run_runtime_selftest(base: Path) -> None:
    report_path = _pop_switch_value(_RUNTIME_SELFTEST_SWITCH)
    target = Path(report_path) if report_path else base / "runtime_selftest.json"
    if not target.is_absolute():
        target = (base / target).resolve()

    checks = {}
    failures = []

    def probe(name, func):
        try:
            value = func()
            if value is None:
                checks[name] = True
            elif isinstance(value, (bool, str, int, float, list, dict)):
                checks[name] = value
            else:
                checks[name] = True
        except Exception as exc:
            checks[name] = False
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    _prepare_process_environment(base)
    os.environ["JARVIS_APP_DIR"] = str(base)
    probe("pyside6", lambda: __import__("PySide6"))
    probe("sounddevice", lambda: __import__("sounddevice"))
    probe("vosk", lambda: __import__("vosk"))
    probe("webrtcvad", lambda: __import__("webrtcvad"))
    probe("_webrtcvad", lambda: __import__("_webrtcvad"))
    probe("pystray", lambda: __import__("pystray"))
    probe("pystray_win32", lambda: __import__("pystray._win32", fromlist=["*"]))
    probe("voice_engine", lambda: __import__("voice_engine"))
    probe("desktop_integration", lambda: __import__("desktop_integration"))
    probe("send2trash", lambda: __import__("send2trash"))

    def prove_single_qt_ui():
        import gui
        paths = gui.required_asset_paths()
        forbidden = [name for name in gui.FORBIDDEN_VISUAL_MODULES if name in sys.modules]
        if forbidden:
            raise RuntimeError("Legacy visual modules loaded: " + ", ".join(forbidden))
        return {"module": str(Path(gui.__file__).name), "assets": sorted(paths)}

    probe("single_qt_ui", prove_single_qt_ui)

    model = base / "data" / "voice_models" / "vosk-model-small-pt-0.3"
    required_model_files = [model / "final.mdl", model / "Gr.fst", model / "HCLr.fst", model / "phones.txt", model / "mfcc.conf"]
    missing = [str(path.relative_to(base)) for path in required_model_files if not path.is_file()]
    checks["wake_model_assets"] = not missing
    if missing:
        failures.append("wake_model_assets missing: " + ", ".join(missing))

    expected_hot = str(os.environ.get("JARVIS_EXPECT_HOT_VERSION") or "").strip()
    if expected_hot:
        activation_box = {"value": None}

        def activate_hot_for_probe():
            activation = _activate_runtime(base, track_boot=False)
            activation_box["value"] = activation
            if activation is None or str(getattr(activation, "version", "")) != expected_hot:
                raise RuntimeError(f"Expected hot runtime {expected_hot} was not activated")
            return str(getattr(activation, "path", ""))

        def prove_hot_import_precedence():
            activation = activation_box.get("value")
            if activation is None:
                raise RuntimeError("Hot runtime was not activated")
            import importlib
            sys.modules.pop("jarvis_version", None)
            module = importlib.import_module("jarvis_version")
            actual = str(getattr(module, "VERSION", ""))
            origin = Path(str(getattr(module, "__file__", "") or "")).resolve()
            runtime_path = Path(str(getattr(activation, "path", ""))).resolve()
            if actual != expected_hot:
                raise RuntimeError(f"Version {actual or 'unknown'} != {expected_hot}")
            try:
                origin.relative_to(runtime_path)
            except Exception as exc:
                raise RuntimeError(f"jarvis_version came from bundle: {origin}") from exc
            return {"version": actual, "origin": str(origin)}

        probe("hot_runtime_activation", activate_hot_for_probe)
        probe("hot_runtime_import_precedence", prove_hot_import_precedence)

    payload = {
        "ok": not failures,
        "frozen": bool(getattr(sys, "frozen", False)),
        "app_dir": str(base),
        "checks": checks,
        "failures": failures,
    }
    try:
        import json
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        _write_critical_error(f"Runtime selftest report failed: {exc}")
        raise SystemExit(4)
    if failures:
        _write_critical_error("Runtime selftest failed: " + " | ".join(failures))
        raise SystemExit(3)
    raise SystemExit(0)


def _acquire_main_instance() -> bool:
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
            return True
        error = ctypes.get_last_error()
        if error == 183:
            close_handle(handle)
            _write_startup_diagnostic("Another JARVIS instance already owns the main mutex.")
            return False
        _MAIN_MUTEX_HANDLE = handle
        return True
    except Exception as exc:
        _write_critical_error(f"Single-instance mutex unavailable: {exc}")
        return True


def _bootstrap_configuration(base: Path) -> None:
    _prepare_process_environment(base)
    from secure_settings import bootstrap_secrets_to_env, migrate_legacy_env
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
            _write_critical_error(f"Gemini config dialog failed: {exc}")
            _write_startup_diagnostic("Gemini configuration dialog failed.", exc=exc)
        bootstrap_secrets_to_env()
        raise SystemExit(0)
    if (not key) and (ensure_only or not skip_first_run):
        try:
            from first_run_setup import show_api_key_dialog
            show_api_key_dialog(first_run=not ensure_only)
        except Exception as exc:
            _write_critical_error(f"First-run Gemini dialog failed: {exc}")
            _write_startup_diagnostic("First-run configuration dialog failed.", exc=exc)
        bootstrap_secrets_to_env()
    if ensure_only:
        raise SystemExit(0)


def main() -> None:
    base = _app_dir()
    _set_phase("prepare-environment")
    _prepare_process_environment(base)
    os.environ["JARVIS_APP_DIR"] = str(base)
    if _RUNTIME_SELFTEST_SWITCH in sys.argv:
        _set_phase("runtime-selftest")
        _run_runtime_selftest(base)
        return
    _set_phase("wait-restart-parent")
    _wait_for_restart_parent()
    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass
    helper_mode = _CONFIGURE_API_SWITCH in sys.argv or _ENSURE_API_SWITCH in sys.argv
    if helper_mode:
        _set_phase("helper-activate-runtime")
        _activate_runtime(base, track_boot=False)
    else:
        _set_phase("single-instance")
        if not _acquire_main_instance():
            return
        _set_phase("activate-runtime")
        _activate_runtime(base, track_boot=True)
    try:
        _set_phase("bootstrap-configuration")
        _bootstrap_configuration(base)
    except SystemExit:
        raise
    except Exception as exc:
        _write_critical_error(f"Bootstrap: {exc}")
        _write_startup_diagnostic("Configuration bootstrap failed.", exc=exc)
    try:
        _set_phase("import-actions")
        from actions import SystemActions
        _set_phase("import-core")
        from core import JarvisCore
        _set_phase("import-gui")
        from gui import JarvisGUI
        _set_phase("import-logger")
        from logger import JarvisLogger
    except Exception as exc:
        _write_critical_error(f"Import failure: {exc}")
        _write_startup_diagnostic("Main module import failed.", exc=exc)
        if not getattr(sys, "frozen", False):
            print(f"Import error: {exc}")
        raise SystemExit(1)
    try:
        _set_phase("create-logger")
        logger = JarvisLogger()
        _set_phase("create-actions")
        actions = SystemActions(logger)
        _set_phase("create-core")
        core = JarvisCore(logger)
        _set_phase("create-gui")
        app = JarvisGUI(logger, actions, core)
        _set_phase("schedule-runtime-healthy")
        try:
            from PySide6.QtCore import QTimer
            from hot_update_runtime import mark_hot_runtime_healthy
            QTimer.singleShot(1500, mark_hot_runtime_healthy)
        except Exception as exc:
            _write_startup_diagnostic("Could not schedule hot runtime health mark.", exc=exc)
        _set_phase("app-run")
        app.run()
        _set_phase("app-run-returned")
        _write_startup_diagnostic("app.run() returned normally.")
    except KeyboardInterrupt:
        raise SystemExit(0)
    except SystemExit:
        raise
    except BaseException as exc:
        _write_critical_error(f"Startup: {type(exc).__name__}: {exc}")
        _write_startup_diagnostic("Fatal GUI startup/runtime failure.", exc=exc)
        try:
            print(f"Fatal startup error: {exc}")
        except Exception:
            pass
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        _set_phase("__main__")
        main()
    except SystemExit:
        raise
    except BaseException as exc:
        _write_startup_diagnostic("Unhandled exception escaped main().", exc=exc)
        raise
