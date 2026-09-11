#!/usr/bin/env python3
"""Desktop 1.0 distribution/security/update regression checks."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

checks = 0

def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)

root = Path(__file__).resolve().parent

# Version identity must be updater-compatible semver.
from jarvis_version import VERSION, BUILD, CHANNEL
from packaging.version import Version
check(str(Version(VERSION)) == VERSION, f"VERSION não é semver: {VERSION}")
check("desktop." in BUILD or "hotbase." in BUILD or "hot." in BUILD, BUILD)
check(CHANNEL == "stable", CHANNEL)

# DPAPI abstraction / migration. On non-Windows the module intentionally uses a dev-only fallback.
old_local = os.environ.get("LOCALAPPDATA")
old_key = os.environ.get("GEMINI_API_KEY")
with tempfile.TemporaryDirectory() as td:
    os.environ["LOCALAPPDATA"] = td
    import secure_settings
    secret = "test-key-" + "A" * 32
    secure_settings.delete_gemini_api_key()
    secure_settings.save_gemini_api_key(secret)
    check(secure_settings.load_gemini_api_key() == secret, "chave segura não reabre")
    raw = secure_settings.secret_path().read_text(encoding="utf-8")
    check(secret not in raw, "chave apareceu em plaintext no arquivo seguro")
    os.environ.pop("GEMINI_API_KEY", None)
    check(secure_settings.bootstrap_secrets_to_env() == secret, "bootstrap falhou")
    check(os.environ.get("GEMINI_API_KEY") == secret, "env de processo não recebeu chave")

    legacy = Path(td) / "legacy"
    legacy.mkdir()
    (legacy / ".env").write_text("OPENWEATHER_API_KEY=keep\nGEMINI_API_KEY=" + secret + "\nJARVIS_TEST=1\n", encoding="utf-8")
    secure_settings.delete_gemini_api_key()
    check(secure_settings.migrate_legacy_env(legacy), "migração .env não ocorreu")
    migrated = (legacy / ".env").read_text(encoding="utf-8")
    check("GEMINI_API_KEY=" not in migrated, "Gemini ficou no .env após migração")
    check("OPENWEATHER_API_KEY=keep" in migrated and "JARVIS_TEST=1" in migrated, "migração apagou outras configs")
    check(secure_settings.load_gemini_api_key() == secret, "migração não salvou chave segura")

if old_local is None:
    os.environ.pop("LOCALAPPDATA", None)
else:
    os.environ["LOCALAPPDATA"] = old_local
if old_key is None:
    os.environ.pop("GEMINI_API_KEY", None)
else:
    os.environ["GEMINI_API_KEY"] = old_key

# Updater configuration/version logic.
from github_updater import GitHubReleaseUpdater
with tempfile.TemporaryDirectory() as td:
    app = Path(td)
    (app / "update_config.json").write_text(json.dumps({
        "enabled": True,
        "repository": "owner/JARVIS-Desktop",
        "installer_asset_prefix": "JARVIS_Setup_",
        "hot_updates_enabled": True,
        "hot_update_asset_prefix": "JARVIS_HotUpdate_",
        "runtime_api": 1,
        "bootstrap_version": "1.1.0",
    }), encoding="utf-8")
    up = GitHubReleaseUpdater(app, current_version="1.0.0")
    check(up.is_configured(), "repo público válido não reconhecido")
    check(up._is_newer("v1.0.1"), "versão nova não reconhecida")
    check(not up._is_newer("v1.0.0"), "mesma versão marcada como nova")
    check(not up._is_newer("v0.9.9"), "downgrade marcado como update")
    check(up._digest_from_asset({"digest": "sha256:" + "a" * 64}) == "a" * 64, "digest GitHub não lido")

# Source-level integration guards.
main_src = (root / "main.py").read_text(encoding="utf-8")
core_src = (root / "core.py").read_text(encoding="utf-8")
web_src = (root / "web_search.py").read_text(encoding="utf-8")
gui_src = (root / "gui.py").read_text(encoding="utf-8")
iss = (root / "build" / "JARVIS.iss").read_text(encoding="utf-8")
workflow = (root / ".github" / "workflows" / "build-release.yml").read_text(encoding="utf-8")
overlay_src = (root / "voice_overlay_qt.py").read_text(encoding="utf-8")
first_run_src = (root / "first_run_setup.py").read_text(encoding="utf-8")
requirements_src = (root / "requirements.txt").read_text(encoding="utf-8")
desktop_src = (root / "desktop_integration.py").read_text(encoding="utf-8")
voice_src = (root / "voice_engine.py").read_text(encoding="utf-8")
build_src = (root / "build" / "build_windows.ps1").read_text(encoding="utf-8")
build_requirements_src = (root / "build" / "requirements-build.txt").read_text(encoding="utf-8")
updater_src = (root / "github_updater.py").read_text(encoding="utf-8")
hot_workflow_src = (root / ".github" / "workflows" / "publish-hot-update.yml").read_text(encoding="utf-8")
hot_runtime_src = (root / "hot_update_runtime.py").read_text(encoding="utf-8")
hot_runtime_core_src = (root / "hot_update_runtime_core.py").read_text(encoding="utf-8")
baseline = json.loads((root / "build" / "hot_runtime_baseline.json").read_text(encoding="utf-8"))

check("activate_hot_runtime" in main_src, "main sem hot runtime")
check("--restart-after-pid" in main_src, "main sem reinicio hot seguro")
check("apply_hot_update" in gui_src and "launch_hot_restart" in gui_src, "GUI sem hot update")
check((root / ".github" / "workflows" / "publish-hot-update.yml").is_file(), "workflow hot update ausente")
check((root / "build" / "hot_runtime_baseline.json").is_file(), "baseline hot ausente")
check("migrate_legacy_env(base)" in main_src, "main não migra .env legado")
check(main_src.index("_bootstrap_configuration(base)") < main_src.index("from core import JarvisCore"), "core importa antes do bootstrap seguro")
check("bootstrap_secrets_to_env" in core_src and "reload_api_key" in core_src, "core sem cofre/reload")
check("bootstrap_secrets_to_env" in web_src and "reload_api_key" in web_src, "web_search sem cofre/reload")
check("GitHubReleaseUpdater" in gui_src, "GUI sem updater")
check("ATUALIZAR {info.version}" in gui_src, "GUI sem botão de versão")
check("_open_api_settings" in gui_src, "GUI sem botão API")
check("SHA-256" in gui_src or "sha256" in (root / "github_updater.py").read_text(encoding="utf-8"), "sem validação de hash")
check("DefaultDirName=C:\\JARVIS" in iss, "instalador não aponta para C:\\JARVIS")
check('Name: "{app}\\data"; Permissions: users-modify' in iss, "data não gravável")
check("GEMINI_API_KEY" not in iss, "instalador embute chave")
check('Type: files; Name: "{app}\\*.py"' in iss, "migração não remove fontes legados")
check('.env' not in "\n".join(line for line in iss.splitlines() if line.strip().startswith("Type:")), "InstallDelete apaga .env")
check("windows-latest" in workflow, "workflow não usa Windows")
check("actions/checkout@v7" in workflow and "actions/setup-python@v7" in workflow, "actions desatualizadas")
check("gh release" in workflow, "workflow não publica release")
check("JARVIS_Setup_${{ inputs.version }}.exe" in workflow, "asset do setup ausente")

# Runtime distribution guards: packaged helper processes may never relaunch
# the full JARVIS UI recursively.
check("--voice-overlay-child" in main_src, "main sem dispatch do overlay empacotado")
check("_acquire_main_instance" in main_src and "CreateMutexW" in main_src, "main sem trava de instancia unica")
check('child_command = [sys.executable, "--voice-overlay-child"]' in overlay_src, "overlay frozen relanca JARVIS incorretamente")
check('str(Path(__file__).resolve()), "--child"' in overlay_src, "overlay de desenvolvimento perdeu modo python")
check('Parameters: "--configure-api"' in iss and 'waituntilterminated skipifsilent' in iss, "instalador nao abre configuracao Gemini antes do app")
check(first_run_src.count('window.attributes("-topmost", True)') >= 1, "dialogo Gemini pode ficar escondido atras do instalador")

# Desktop/voice reliability guards introduced by the 1.1.0 stable baseline.
check("pystray" in requirements_src, "runtime do instalador não inclui pystray")
check("pystray._win32" in build_src and '"--hidden-import", "pystray._win32"' in build_src, "PyInstaller não força backend Win32 do tray")
check("--runtime-selftest" in main_src, "main sem smoke test do executável congelado")
check("PYSTRAY_BACKEND" in main_src and "win32" in main_src, "main não fixa backend Win32 do tray")
check(
    "runtime-selftest.json" in build_src
    and "Start-Process" in build_src
    and "-FilePath $ExePath" in build_src
    and "--runtime-selftest" in build_src,
    "build não executa smoke test no JARVIS.exe final",
)
check('"--collect-all", "sounddevice"' in build_src and '"--collect-all", "vosk"' in build_src, "build não empacota voz nativa explicitamente")
check("_voice_supervisor_loop" in voice_src and "wait_until_ready" in voice_src, "VoiceEngine sem supervisor de recuperação")
check(
    "check_input_settings" in voice_src
    and "RawInputStream" in voice_src
    and "query_devices" in voice_src
    and "default_samplerate" in voice_src,
    "detecção de microfone não possui fallback real",
)
check(
    "self._brand_icon_cache = {}" in gui_src
    and "def _get_brand_icon" in gui_src
    and 'getattr(self, "_brand_icon_cache"' in gui_src,
    "Blue Core pode cair no startup por cache de marca não inicializado",
)
check(
    "resource_delay = 30.0" in voice_src
    and "min(300.0, resource_delay" in voice_src,
    "supervisor de voz ainda pode martelar recurso indisponível",
)
check(
    "threading.get_ident()" in voice_src
    and "urllib.request.urlopen" in voice_src,
    "download Vosk ainda usa temporário global frágil",
)
check("_monitor_voice_runtime" in gui_src, "GUI não confirma que o wake realmente ficou pronto")
check("engine.trigger_manual()" in gui_src, "botão/escuta manual ainda usa reconhecedor legado")
check('can_hide = bool(desktop_status.get("tray_ready"))' in gui_src, "X ainda pode esconder JARVIS sem tray")
check('or desktop_status.get("hotkey_ready")' not in gui_src, "hotkey ainda permite processo invisível sem tray")
check("_tray_started_event" in desktop_src and "icon.run(setup=self._tray_setup)" in desktop_src, "tray não aguarda backend Win32 real")
check("_tray_supervisor_loop" in desktop_src and "_tray_restarts" in desktop_src and "_tray_last_error" in desktop_src, "tray sem supervisor/retry observável")
check("run_detached()" not in desktop_src, "tray ainda usa run_detached depois do Tk mainloop")
check("auto_enable_startup=False" in gui_src, "GUI ainda força inicialização automática do Windows")
check("send2trash" in requirements_src, "runtime do instalador não inclui send2trash")
check(
    '"--hidden-import", "send2trash"' in build_src
    and '"--hidden-import", "send2trash.win"' in build_src
    and '"--hidden-import", "send2trash.win.modern"' in build_src
    and '"--hidden-import", "send2trash.win.legacy"' in build_src,
    "PyInstaller não força Send2Trash no runtime congelado",
)
check("pyinstaller==6.22.2" in build_requirements_src and "pyinstaller-hooks-contrib==2026.7" in build_requirements_src, "toolchain PyInstaller não está travada na base hot validada")
check("_capture_sample_rate" in voice_src and "_resample_to_target" in voice_src and "default_samplerate" in voice_src, "voz não possui fallback 44.1/48 kHz com reamostragem para 16 kHz")
check("PYINSTALLER_RESET_ENVIRONMENT" in updater_src, "reinício hot do EXE não reseta ambiente do bootloader")
check("SetDllDirectoryW(None)" in updater_src, "instalador externo herda diretório de DLL do PyInstaller")
check("sys.stdout is None" in main_src and "sys.stderr is None" in main_src, "main congelado não protege stdout/stderr ausentes")
check("JARVIS_EXPECT_HOT_VERSION" in main_src, "runtime-selftest não prova precedência do código hot")
check("def _report_value(value):" in main_src, "runtime-selftest ainda grava objetos não serializáveis")
check("checks[name] = _report_value(value)" in main_src, "runtime-selftest não normaliza resultado dos imports para JSON")
check("hot-runtime-smoke" in build_src and "JARVIS_EXPECT_HOT_VERSION" in build_src, "build completo não prova Hot Runtime no EXE final")
check("jarvis_hot_update_selftest.py" in hot_workflow_src and "jarvis_desktop_selftest.py" in hot_workflow_src, "workflow rápido publica sem regressão do runtime")
check('"requests>=2.31,<3"' in hot_workflow_src, "workflow rápido não instala requests exigido pelo selftest/updater")
check("build/requirements-build.txt" in (baseline.get("locked_files") or {}), "baseline hot não protege toolchain do build completo")
# The immutable-release rule lives in hot_update_runtime_core.py after the
# protected bootstrap split. Test the implementation that actually owns it,
# instead of requiring compatibility prose in the wrapper.
check(
    "conteúdo diferente" in hot_runtime_core_src
    and "novo número de versão" in hot_runtime_core_src,
    "runtime hot permite reutilizar versão com conteúdo diferente",
)
check("from jarvis_version import VERSION" not in hot_runtime_src, "bootstrap hot importa jarvis_version antes da ativação")

# The clean source package must not contain a real .env.
check(not (root / ".env").exists(), "pacote Desktop contém .env")

print(f"JARVIS DESKTOP SELFTEST: PASS ({checks} verificacoes)")
