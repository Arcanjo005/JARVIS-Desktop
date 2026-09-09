#!/usr/bin/env python3
"""Prepare deterministic Desktop build metadata before PyInstaller runs."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def replace_assignment(text: str, name: str, value: str) -> str:
    pattern = rf'(?m)^{re.escape(name)}\s*=\s*["\'][^"\']*["\']\s*$'
    replacement = f'{name} = {json.dumps(value)}'
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"Não encontrei {name} em jarvis_version.py")
    return updated


def parse_numeric_version(version: str):
    parsed = Version(version)
    release = list(parsed.release[:4])
    while len(release) < 4:
        release.append(0)
    return tuple(int(x) for x in release)


def write_version_resource(version: str):
    v = parse_numeric_version(version)
    dotted = ".".join(str(x) for x in v)
    content = f'''# UTF-8\nVSVersionInfo(\n  ffi=FixedFileInfo(\n    filevers={v},\n    prodvers={v},\n    mask=0x3f,\n    flags=0x0,\n    OS=0x40004,\n    fileType=0x1,\n    subtype=0x0,\n    date=(0, 0)\n  ),\n  kids=[\n    StringFileInfo([\n      StringTable('040904B0', [\n        StringStruct('CompanyName', 'JARVIS Desktop'),\n        StringStruct('FileDescription', 'JARVIS Desktop AI Assistant'),\n        StringStruct('FileVersion', '{dotted}'),\n        StringStruct('InternalName', 'JARVIS'),\n        StringStruct('LegalCopyright', 'JARVIS Desktop'),\n        StringStruct('OriginalFilename', 'JARVIS.exe'),\n        StringStruct('ProductName', 'JARVIS Desktop'),\n        StringStruct('ProductVersion', '{version}')\n      ])\n    ]),\n    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n  ]\n)\n'''
    (ROOT / "build" / "version_info.txt").write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-number", default="1")
    args = parser.parse_args()

    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version.strip()):
        raise SystemExit("version deve usar X.Y.Z, por exemplo 1.0.1")
    version = str(Version(args.version))
    repository = args.repository.strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SystemExit("repository deve estar no formato OWNER/REPO")

    version_file = ROOT / "jarvis_version.py"
    text = version_file.read_text(encoding="utf-8")
    text = replace_assignment(text, "VERSION", version)
    stamp = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    text = replace_assignment(text, "BUILD", f"{stamp}-desktop.{args.run_number}")
    text = replace_assignment(text, "CHANNEL", "stable")
    version_file.write_text(text, encoding="utf-8")

    config_path = ROOT / "update_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["repository"] = repository
    config["enabled"] = True
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_version_resource(version)
    (ROOT / "RELEASE_VERSION.txt").write_text(version + "\n", encoding="utf-8")
    print(f"JARVIS Desktop {version} preparado para {repository}")


if __name__ == "__main__":
    main()
