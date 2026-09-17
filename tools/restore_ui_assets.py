#!/usr/bin/env python3
"""Reconstruct only the approved visual assets used by the single-source Qt UI."""
from __future__ import annotations

import base64
import runpy
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "ui_assets"
ASSETS = ROOT / "assets"


def restore_background() -> Path:
    ns = runpy.run_path(str(SOURCES / "background_renderer.py"))
    render = ns.get("render_reference_scene")
    if not callable(render):
        raise RuntimeError("approved background renderer missing")
    image = render(2560, 1440).convert("RGB")
    if image.size != (2560, 1440):
        raise RuntimeError(f"approved background size changed: {image.size}")
    target = ASSETS / "workspace_bg.jpg"
    image.save(target, "JPEG", quality=95, optimize=True, progressive=True)
    return target


def restore_sphere() -> Path:
    ns = runpy.run_path(str(SOURCES / "sphere_source.py"))
    encoded = next(
        (value for key, value in ns.items() if key.endswith("WEBP_B64") and isinstance(value, str)),
        None,
    )
    if not encoded:
        raise RuntimeError("approved sphere payload missing")
    payload = base64.b64decode(encoded, validate=True)
    target = ASSETS / "sphere_3d.webp"
    target.write_bytes(payload)
    with Image.open(target) as image:
        image.verify()
    with Image.open(target) as image:
        if image.width < 256 or image.height < 256:
            raise RuntimeError(f"approved sphere is unexpectedly small: {image.size}")
    return target


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    for old in (
        "sphere_3d.png",
        "update_neon_arrow.png",
        "jarvis_logo.png",
        "plus.png",
        "mic.png",
        "send.png",
    ):
        (ASSETS / old).unlink(missing_ok=True)
    bg = restore_background()
    sphere = restore_sphere()
    print(f"APPROVED UI ASSETS RESTORED: {bg.relative_to(ROOT)}, {sphere.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
