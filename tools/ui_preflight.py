#!/usr/bin/env python3
"""Release gate for source, imports, assets, metadata and workflow structure."""
from __future__ import annotations
import argparse
import ast
import compileall
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--version",required=True)
    args=parser.parse_args()
    checks=[]
    def check(value,label):
        if not value: raise AssertionError(label)
        checks.append(label)
    check(compileall.compile_dir(str(ROOT),quiet=1,
          rx=re.compile(r"[\\/](?:\.git|validation|__pycache__)[\\/]")),"All Python syntax")
    from packaging.version import Version
    from packaging.requirements import Requirement
    for line in (ROOT/"requirements.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            Requirement(line)
    checks.append("Dependency requirement syntax")
    from jarvis_version import VERSION, BUILD, CHANNEL
    check(str(Version(args.version))==VERSION,"Prepared release version matches request")
    check(CHANNEL=="stable" and "desktop." in BUILD,"Canonical build identity")
    import gui_conversation_shell
    import gui_reference_exact_v3
    import gui
    check(gui_conversation_shell.JarvisGUI is gui_reference_exact_v3.JarvisGUI,"Stable shell export")
    check(gui_reference_exact_v3.JarvisGUI.__bases__==(gui.JarvisGUI,),"Single controller inheritance")
    from jarvis_ui_render import OrbRenderer
    image=OrbRenderer().render(100,.5)
    check(image.size==(100,100) and image.mode=="RGBA","Procedural 3D renderer imports and renders")
    from PIL import Image
    for name in ("jarvis.ico","installer/jarvis_small.png","installer/jarvis_wizard.png"):
        with Image.open(ROOT/name) as asset:
            asset.verify()
        checks.append("Decoded asset: "+name)
    from jarvis_reference_orb import load_orb_image
    legacy=load_orb_image()
    legacy.load()
    check(legacy.width>0 and legacy.height>0,"Retained legacy orb asset decodes")
    for path in sorted(ROOT.glob("*.json")):
        json.loads(path.read_text(encoding="utf-8-sig"))
    checks.append("Root JSON metadata syntax")
    entry=(ROOT/"main.py").read_text(encoding="utf-8")
    ast.parse(entry)
    check("from gui_conversation_shell import JarvisGUI" in entry,"Canonical prepared entry point")
    check(entry.index("multiprocessing.freeze_support()") < entry.index("app = JarvisGUI("),
          "Frozen worker dispatch precedes GUI construction")
    # Parse YAML rather than treating a substring check as full validation.
    import yaml
    for path in sorted((ROOT/".github"/"workflows").glob("*.yml")):
        data=yaml.load(path.read_text(encoding="utf-8"),Loader=yaml.BaseLoader)
        check(isinstance(data,dict) and "jobs" in data and "on" in data,"Workflow parses: "+path.name)
    if sys.platform=="win32":
        import voice_engine, sounddevice, vosk, webrtcvad, _webrtcvad
        import pystray._win32, send2trash
        checks.append("Windows production voice/tray imports")
    result={"ok":True,"version":VERSION,"build":BUILD,"checks":checks,
            "note":"Live microphone, neural TTS and physical monitor transitions require device acceptance testing."}
    out=ROOT/"validation";out.mkdir(exist_ok=True)
    (out/"preflight-report.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print(f"JARVIS UI PREFLIGHT: PASS ({len(checks)} checks)")


if __name__=="__main__":
    main()
