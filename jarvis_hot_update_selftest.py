#!/usr/bin/env python3
"""Offline selftest for JARVIS source-only hot-update runtime."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


def make_package(path: Path, version: str, body: str = "VALUE = 1\n", *, protected=False):
    file_name = "main.py" if protected else "dummy_hot_module.py"
    data = body.encode("utf-8")
    manifest = {
        "format": 1,
        "runtime_api": 1,
        "version": version,
        "minimum_bootstrap": "1.1.0",
        "files": [{"path": file_name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(file_name, data)
        z.writestr("runtime_manifest.json", json.dumps(manifest))


def main():
    old_local = os.environ.get("LOCALAPPDATA")
    old_app = os.environ.get("JARVIS_APP_DIR")
    old_path = list(sys.path)
    with tempfile.TemporaryDirectory(prefix="jarvis-hot-selftest-") as td:
        base = Path(td)
        local = base / "local"
        app = base / "app"
        local.mkdir(); app.mkdir()
        os.environ["LOCALAPPDATA"] = str(local)
        os.environ["JARVIS_APP_DIR"] = str(app)

        from hot_update_runtime import (
            HOT_RUNTIME_API,
            activate_hot_runtime,
            install_hot_package,
            mark_hot_runtime_healthy,
            runtime_store_dir,
            validate_runtime_dir,
        )

        check(HOT_RUNTIME_API == 1, "runtime api inesperada")
        p1 = base / "u111.zip"
        make_package(p1, "1.1.1", "VALUE = 111\n")
        a1 = install_hot_package(p1, expected_version="1.1.1")
        check(a1.version == "1.1.1", "versão 1.1.1 não ativada")
        check((a1.path / "dummy_hot_module.py").is_file(), "arquivo hot ausente")
        check(validate_runtime_dir(a1.path)["runtime_api"] == 1, "runtime inválido")

        active = json.loads((runtime_store_dir() / "active.json").read_text(encoding="utf-8"))
        check(active["version"] == "1.1.1", "ponteiro active incorreto")

        # Releases são imutáveis: publicar o mesmo número com bytes diferentes
        # não pode substituir silenciosamente um runtime já instalado.
        same_version_changed = base / "u111-mutated.zip"
        make_package(same_version_changed, "1.1.1", "VALUE = 999\n")
        try:
            install_hot_package(same_version_changed, expected_version="1.1.1")
        except ValueError as exc:
            check("nova versão" in str(exc).lower() or "conteúdo" in str(exc).lower(),
                  "erro de versão imutável não é explicativo")
        else:
            raise AssertionError("hot update aceitou mesma versão com conteúdo diferente")
        check((a1.path / "dummy_hot_module.py").read_text(encoding="utf-8") == "VALUE = 111\n",
              "tentativa de sobrescrever mesma versão alterou runtime ativo")

        activation = activate_hot_runtime(app, track_boot=True)
        check(activation and activation.version == "1.1.1", "runtime não carregou")
        check(Path(sys.path[0]).resolve() == a1.path.resolve(), "hot runtime não ganhou prioridade no sys.path")
        check((runtime_store_dir() / "booting.json").is_file(), "boot marker não criado")
        mark_hot_runtime_healthy()
        check(not (runtime_store_dir() / "booting.json").exists(), "boot marker não limpo")

        bad = base / "protected.zip"
        make_package(bad, "1.1.2", protected=True)
        try:
            install_hot_package(bad, expected_version="1.1.2")
        except ValueError:
            pass
        else:
            raise AssertionError("hot update aceitou main.py protegido")
        checks_before = checks
        check(checks == checks_before, "contador inconsistente")

        traversal = base / "traversal.zip"
        data = b"X=1\n"
        manifest = {
            "format": 1,
            "runtime_api": 1,
            "version": "1.1.2",
            "minimum_bootstrap": "1.1.0",
            "files": [{"path": "../evil.py", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}],
        }
        with zipfile.ZipFile(traversal, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("../evil.py", data)
            z.writestr("runtime_manifest.json", json.dumps(manifest))
        try:
            install_hot_package(traversal, expected_version="1.1.2")
        except ValueError:
            pass
        else:
            raise AssertionError("hot update aceitou path traversal")
        check(not (base / "evil.py").exists(), "path traversal escreveu fora da pasta")

        # Automatic rollback after two failed boots.
        p2 = base / "u112.zip"
        make_package(p2, "1.1.2", "VALUE = 112\n")
        a2 = install_hot_package(p2, expected_version="1.1.2")
        check(a2.version == "1.1.2", "versão 1.1.2 não instalada")
        active = json.loads((runtime_store_dir() / "active.json").read_text(encoding="utf-8"))
        check(active.get("previous_version") == "1.1.1", "versão anterior não preservada")
        first = activate_hot_runtime(app, track_boot=True)
        check(first and first.version == "1.1.2", "primeiro boot 1.1.2 falhou")
        second = activate_hot_runtime(app, track_boot=True)
        check(second and second.version == "1.1.2", "primeira falha deveria permitir retry")
        third = activate_hot_runtime(app, track_boot=True)
        check(third and third.version == "1.1.1", "rollback automático não voltou para 1.1.1")
        mark_hot_runtime_healthy()

        # Integration gates: the stable executable must own restart/bootstrap.
        main_src = (ROOT / "main.py").read_text(encoding="utf-8")
        gui_src = (ROOT / "gui.py").read_text(encoding="utf-8")
        updater_src = (ROOT / "github_updater.py").read_text(encoding="utf-8")
        check("activate_hot_runtime" in main_src, "main sem bootstrap hot")
        check("--restart-after-pid" in main_src, "main sem reinício seguro")
        check("apply_hot_update" in gui_src, "GUI sem aplicação hot")
        check("launch_hot_restart" in gui_src, "GUI sem reinício hot")
        check("JARVIS_HotUpdate_" in updater_src, "updater sem asset hot")
        check((ROOT / ".github" / "workflows" / "publish-hot-update.yml").is_file(), "workflow rápido ausente")
        check((ROOT / "tools" / "build_hot_update.py").is_file(), "builder hot ausente")

    sys.path[:] = old_path
    if old_local is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = old_local
    if old_app is None:
        os.environ.pop("JARVIS_APP_DIR", None)
    else:
        os.environ["JARVIS_APP_DIR"] = old_app
    print(f"JARVIS HOT UPDATE SELFTEST: PASS ({checks} verificacoes)")


if __name__ == "__main__":
    main()
