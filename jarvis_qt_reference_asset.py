"""Verified visual reference plate for the PySide6 rebuild.

The approved 2560x1440 office plate is kept as text chunks so repository edits
remain inspectable.  The Qt shell loads it directly from bytes; release builds do
not depend on the rejected 1.3.12 scene asset.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

REFERENCE_WIDTH = 2560
REFERENCE_HEIGHT = 1440
REFERENCE_JPEG_SIZE = 214733
REFERENCE_SHA256 = "56826f9ef079fc5a049a5e8503d1f51d58b981031166edb24ba3ba314941d391"
REFERENCE_BASE64_LENGTH = 286312
REFERENCE_CHUNKS = tuple(f"jarvis_qt_reference_plate.b64.{index:02d}" for index in range(9))


def load_reference_plate_bytes(root: Path | None = None) -> bytes:
    root = Path(root or Path(__file__).resolve().parent)
    asset_dir = root / "assets"
    parts: list[str] = []
    for name in REFERENCE_CHUNKS:
        path = asset_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Qt reference chunk missing: {path}")
        parts.append("".join(path.read_text(encoding="ascii").split()))

    encoded = "".join(parts)
    if len(encoded) != REFERENCE_BASE64_LENGTH:
        raise RuntimeError(
            f"Qt reference base64 length {len(encoded)} != {REFERENCE_BASE64_LENGTH}"
        )
    payload = base64.b64decode(encoded, validate=True)
    if len(payload) != REFERENCE_JPEG_SIZE:
        raise RuntimeError(f"Qt reference JPEG size {len(payload)} != {REFERENCE_JPEG_SIZE}")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != REFERENCE_SHA256:
        raise RuntimeError(f"Qt reference SHA-256 mismatch: {digest}")
    if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
        raise RuntimeError("Qt reference payload is not a complete JPEG")
    return payload


__all__ = [
    "REFERENCE_WIDTH",
    "REFERENCE_HEIGHT",
    "REFERENCE_JPEG_SIZE",
    "REFERENCE_SHA256",
    "REFERENCE_BASE64_LENGTH",
    "REFERENCE_CHUNKS",
    "load_reference_plate_bytes",
]
