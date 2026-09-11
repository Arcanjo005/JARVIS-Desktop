#!/usr/bin/env python3
"""Build a source-only JARVIS hot update in seconds (no PyInstaller required)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "build" / "hot_runtime_baseline.json"
RUNTIME_API = 1
EXCLUDED_TOP_LEVEL = {
    "main.py",
    "hot_update_runtime.py",
    "hot_update_runtime_core.py",
    "jarvis_desktop_selftest.py",
    "jarvis_build16_selftest.py",
    "jarvis_v8_selftest.py",
    "jarvis_hot_update_selftest.py",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().lower()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def parse_version(value: str) -> tuple[int, int, int]:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", text):
        raise ValueError("A versão deve usar X.Y.Z, por exemplo 1.1.1")
    return tuple(int(x) for x in text.split("."))


def validate_baseline() -> dict:
    if not BASELINE_PATH.is_file():
        raise RuntimeError("build/hot_runtime_baseline.json ausente; faça um build completo da base hot-update.")
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if int(baseline.get("runtime_api") or 0) != RUNTIME_API:
        raise RuntimeError("Runtime API do baseline é incompatível.")
    locked = baseline.get("locked_files") or {}
    if not isinstance(locked, dict) or not locked:
        raise RuntimeError("Baseline sem arquivos protegidos.")
    changed = []
    missing = []
    for relative, expected in sorted(locked.items()):
        path = ROOT / Path(*Path(relative).parts)
        if not path.is_file():
            missing.append(relative)
            continue
        actual = sha256_file(path)
        if actual != str(expected).lower():
            changed.append(relative)
    if missing or changed:
        details = []
        if missing:
            details.append("ausentes: " + ", ".join(missing))
        if changed:
            details.append("alterados: " + ", ".join(changed))
        raise RuntimeError(
            "Arquivos que exigem build completo mudaram (" + "; ".join(details) + "). "
            "Não publique hot update; gere um novo instalador base."
        )
    return baseline


def hot_source_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name in EXCLUDED_TOP_LEVEL or path.name.startswith("test_"):
            continue
        files.append(path)
    return files


def patched_version_source(path: Path, version: str, run_number: str) -> bytes:
    text = path.read_text(encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    replacements = {
        "VERSION": version,
        "BUILD": f"{stamp}-hot.{run_number}",
        "CHANNEL": "stable",
    }
    for name, value in replacements.items():
        pattern = rf'(?m)^{name}\s*=\s*["\'][^"\']*["\']\s*$'
        text, count = re.subn(pattern, f'{name} = {json.dumps(value)}', text, count=1)
        if count != 1:
            raise RuntimeError(f"Não encontrei {name} em {path.name}")
    return text.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--minimum-bootstrap", default="1.1.0")
    parser.add_argument("--repository", default="")
    parser.add_argument("--run-number", default="1")
    args = parser.parse_args()

    version_tuple = parse_version(args.version)
    minimum_tuple = parse_version(args.minimum_bootstrap)
    if version_tuple <= minimum_tuple:
        raise SystemExit("A versão do hot update deve ser maior que o bootstrap mínimo.")

    baseline = validate_baseline()
    baseline_floor = str(baseline.get("bootstrap_version") or "1.1.0")
    if minimum_tuple < parse_version(baseline_floor):
        raise SystemExit(f"minimum-bootstrap não pode ser menor que {baseline_floor}.")

    files_payload: list[tuple[str, bytes]] = []
    for path in hot_source_files():
        data = patched_version_source(path, args.version, args.run_number) if path.name == "jarvis_version.py" else path.read_bytes()
        try:
            compile(data.decode("utf-8"), path.name, "exec")
        except Exception as exc:
            raise SystemExit(f"Falha de sintaxe em {path.name}: {exc}")
        files_payload.append((path.name, data))

    entries = [
        {"path": name, "size": len(data), "sha256": sha256_bytes(data)}
        for name, data in files_payload
    ]
    manifest = {
        "format": 1,
        "runtime_api": RUNTIME_API,
        "version": args.version,
        "minimum_bootstrap": args.minimum_bootstrap,
        "repository": str(args.repository or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "file_count": len(entries),
        "uncompressed_bytes": sum(item["size"] for item in entries),
        "files": entries,
    }

    release_dir = ROOT / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"JARVIS_HotUpdate_{args.version}"
    zip_path = release_dir / f"{base_name}.zip"
    meta_path = release_dir / f"{base_name}.json"
    sha_path = release_dir / f"{base_name}.zip.sha256"

    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    # Level 6 is a better latency/size tradeoff for source-only updates. Level 9
    # spends noticeably more CPU for a very small size gain on Python sources.
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in files_payload:
            archive.writestr(name, data)
        archive.writestr("runtime_manifest.json", manifest_bytes)

    package_hash = sha256_file(zip_path)
    meta = {
        "format": 1,
        "kind": "jarvis-hot-update",
        "runtime_api": RUNTIME_API,
        "version": args.version,
        "minimum_bootstrap": args.minimum_bootstrap,
        "repository": str(args.repository or "").strip(),
        "asset": zip_path.name,
        "sha256": package_hash,
        "size": zip_path.stat().st_size,
        "file_count": len(entries),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sha_path.write_text(f"{package_hash}  {zip_path.name}\n", encoding="ascii")

    print(f"JARVIS hot update {args.version}: {len(entries)} arquivos")
    print(f"Pacote: {zip_path}")
    print(f"Tamanho: {zip_path.stat().st_size / 1024:.1f} KiB")
    print(f"SHA256: {package_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
