#!/usr/bin/env python3
"""Prepare deterministic JARVIS build metadata without changing the UI route."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
ROOT_STR = str(ROOT)
if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)

REQUIRED_UI_ASSETS = (
    "workspace_bg.jpg",
    "sphere_3d.webp",
)


def replace_assignment(text: str, name: str, value: str) -> str:
    pattern = rf'(?m)^{re.escape(name)}\s*=\s*["\'][^"\']*["\']\s*$'
    replacement = f'{name} = {json.dumps(value)}'
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not find {name} in jarvis_version.py")
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
    content = f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v},
    prodvers={v},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'JARVIS Desktop'),
        StringStruct('FileDescription', 'JARVIS Desktop AI Assistant'),
        StringStruct('FileVersion', '{dotted}'),
        StringStruct('InternalName', 'JARVIS'),
        StringStruct('LegalCopyright', 'JARVIS Desktop'),
        StringStruct('OriginalFilename', 'JARVIS.exe'),
        StringStruct('ProductName', 'JARVIS Desktop'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''
    (ROOT / "build" / "version_info.txt").write_text(content, encoding="utf-8")


def validate_single_source_ui():
    main_path = ROOT / "main.py"
    gui_path = ROOT / "gui.py"
    if not main_path.is_file() or not gui_path.is_file():
        raise RuntimeError("main.py/gui.py missing")
    main = main_path.read_text(encoding="utf-8")
    gui = gui_path.read_text(encoding="utf-8")
    if "from gui import JarvisGUI" not in main:
        raise RuntimeError("main.py is not using the single-source gui.py")
    forbidden = (
        "from gui_qt_",
        "from gui_reference",
        "JARVIS DESKTOP INTELLIGENCE",
        "_paint_hologram",
        "QRadialGradient",
    )
    hits = [token for token in forbidden if token in gui]
    if hits:
        raise RuntimeError("Legacy visual path detected in gui.py: " + ", ".join(hits))


def validate_approved_assets():
    assets = ROOT / "assets"
    missing = [name for name in REQUIRED_UI_ASSETS if not (assets / name).is_file()]
    if missing:
        raise RuntimeError("Approved UI assets missing: " + ", ".join(missing))
    invalid = [name for name in REQUIRED_UI_ASSETS if (assets / name).stat().st_size < 128]
    if invalid:
        raise RuntimeError("Approved UI assets invalid: " + ", ".join(invalid))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-number", default="1")
    parser.add_argument("--channel", default="stable", choices=("stable", "beta", "dev"))
    parser.add_argument("--build-id", default="")
    args = parser.parse_args()

    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version.strip()):
        raise SystemExit("version must use X.Y.Z")
    version = str(Version(args.version))
    repository = args.repository.strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SystemExit("repository must use OWNER/REPO")

    validate_single_source_ui()
    validate_approved_assets()

    version_file = ROOT / "jarvis_version.py"
    text = version_file.read_text(encoding="utf-8")
    text = replace_assignment(text, "VERSION", version)
    if args.build_id.strip():
        build_id = args.build_id.strip()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y.%m.%d")
        build_id = f"{stamp}-desktop.{args.run_number}"
    text = replace_assignment(text, "BUILD", build_id)
    text = replace_assignment(text, "CHANNEL", args.channel)
    version_file.write_text(text, encoding="utf-8")

    config_path = ROOT / "update_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["repository"] = repository
    config["enabled"] = True
    config["hot_updates_enabled"] = True
    config["hot_update_asset_prefix"] = str(config.get("hot_update_asset_prefix") or "JARVIS_HotUpdate_")
    config["runtime_api"] = 1
    config["bootstrap_version"] = version
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_version_resource(version)
    (ROOT / "RELEASE_VERSION.txt").write_text(version + "\n", encoding="utf-8")
    print(f"JARVIS Desktop {version} / {build_id} / {args.channel} prepared for {repository}")


if __name__ == "__main__":
    main()
