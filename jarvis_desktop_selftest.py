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
check("desktop." in BUILD, BUILD)
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

# The clean source package must not contain a real .env.
check(not (root / ".env").exists(), "pacote Desktop contém .env")

print(f"JARVIS DESKTOP SELFTEST: PASS ({checks} verificacoes)")
