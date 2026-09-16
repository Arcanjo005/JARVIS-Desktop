"""Approved JARVIS reference-scene asset loader.

The binary is stored as small base64 source chunks so GitHub text-only edits can
still reproduce the exact 2560x1440 JPEG during CI/build.  Release builds call
``ensure_reference_scene`` before PyInstaller and then bundle only the JPEG.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

REFERENCE_WIDTH = 2560
REFERENCE_HEIGHT = 1440
REFERENCE_RELATIVE_PATH = Path("assets") / "jarvis_reference_scene_1440p.jpg"

# Exact ordered source.  Legacy .03-.07 chunks are intentionally not used: they
# were truncated during an earlier upload and remain only as harmless history.
REFERENCE_PARTS = (
    "jarvis_reference_scene_1440p.b64.00",
    "jarvis_reference_scene_1440p.b64.01",
    "jarvis_reference_scene_1440p.b64.02",
    "jarvis_reference_scene_1440p.b64.fix06",
    "jarvis_reference_scene_1440p.b64.fix07",
    "jarvis_reference_scene_1440p.b64.fix08a",
    "jarvis_reference_scene_1440p.b64.fix08b",
    "jarvis_reference_scene_1440p.b64.fix09",
    "jarvis_reference_scene_1440p.b64.fix10",
    "jarvis_reference_scene_1440p.b64.fix11",
    "jarvis_reference_scene_1440p.b64.fix12",
    "jarvis_reference_scene_1440p.b64.fix13",
    "jarvis_reference_scene_1440p.b64.fix14",
    "jarvis_reference_scene_1440p.b64.fix15a",
    "jarvis_reference_scene_1440p.b64.fix15b",
    "jarvis_reference_scene_1440p.b64.08",
    "jarvis_reference_scene_1440p.b64.09",
)


def _validate_image(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        size = tuple(image.size)
        fmt = str(image.format or "").upper()
    if size != (REFERENCE_WIDTH, REFERENCE_HEIGHT):
        raise RuntimeError(
            f"reference scene has {size[0]}x{size[1]}, expected "
            f"{REFERENCE_WIDTH}x{REFERENCE_HEIGHT}"
        )
    if fmt not in {"JPEG", "JPG"}:
        raise RuntimeError(f"reference scene is {fmt or 'unknown'}, expected JPEG")
    return size


def ensure_reference_scene(root: str | Path | None = None, *, validate: bool = True) -> Path:
    """Return a usable 2560x1440 JPEG, reconstructing it when necessary."""
    base = Path(root).resolve() if root is not None else Path(__file__).resolve().parent
    target = base / REFERENCE_RELATIVE_PATH
    if target.is_file():
        try:
            if not validate:
                return target
            _validate_image(target)
            return target
        except Exception:
            # A partial/stale binary must never silently win over the source.
            try:
                target.unlink()
            except OSError:
                pass

    source_dir = target.parent
    encoded = []
    missing = []
    for name in REFERENCE_PARTS:
        part = source_dir / name
        if not part.is_file():
            missing.append(name)
            continue
        encoded.append("".join(part.read_text(encoding="ascii").split()))
    if missing:
        raise FileNotFoundError("missing reference scene parts: " + ", ".join(missing))

    joined = "".join(encoded)
    if len(joined) != 72880:
        raise RuntimeError(f"reference base64 length {len(joined)} != 72880")
    try:
        payload = base64.b64decode(joined, validate=True)
    except Exception as exc:
        raise RuntimeError(f"reference base64 is invalid: {exc}") from exc
    if len(payload) < 50000 or not payload.startswith(b"\xff\xd8\xff"):
        raise RuntimeError(f"reference JPEG payload is invalid ({len(payload)} bytes)")

    source_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".jpg.tmp")
    tmp.write_bytes(payload)
    tmp.replace(target)
    if validate:
        _validate_image(target)
    return target


def reference_digest(root: str | Path | None = None) -> str:
    path = ensure_reference_scene(root)
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "REFERENCE_WIDTH",
    "REFERENCE_HEIGHT",
    "REFERENCE_RELATIVE_PATH",
    "REFERENCE_PARTS",
    "ensure_reference_scene",
    "reference_digest",
]
