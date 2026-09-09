#!/usr/bin/env python3
"""Reconstruct large runtime assets split for GitHub browser uploads."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "voice_models" / "speaker_guard_campplus.onnx"
PART_DIR = ROOT / "build" / "asset_parts"
EXPECTED_SHA256 = "f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11"
EXPECTED_SIZE = 28281138


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main():
    if TARGET.exists() and TARGET.stat().st_size == EXPECTED_SIZE and digest(TARGET) == EXPECTED_SHA256:
        print("Large asset already present and valid.")
        return
    parts = sorted(PART_DIR.glob("speaker_guard_campplus.onnx.part*"))
    if not parts:
        raise SystemExit("speaker_guard_campplus.onnx ausente e nenhuma parte foi encontrada em build/asset_parts")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temp = TARGET.with_suffix(TARGET.suffix + ".tmp")
    with temp.open("wb") as out:
        for part in parts:
            with part.open("rb") as src:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
    if temp.stat().st_size != EXPECTED_SIZE or digest(temp) != EXPECTED_SHA256:
        temp.unlink(missing_ok=True)
        raise SystemExit("Falha de integridade ao reconstruir speaker_guard_campplus.onnx")
    temp.replace(TARGET)
    print("speaker_guard_campplus.onnx reconstruído e SHA-256 validado.")


if __name__ == "__main__":
    main()
