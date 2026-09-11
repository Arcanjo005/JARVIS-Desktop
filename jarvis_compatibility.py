"""Adaptive compatibility profile for JARVIS Desktop 1.2.1.

This module is deliberately isolated from the chat/Gemini pipeline.  It only
observes inexpensive machine capabilities, persists last-known-good choices and
returns recommendations to individual subsystems (voice/audio/UI).  Every
operation is fail-open: a broken profile must never prevent JARVIS from starting.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA_VERSION = 1
PUBLIC_VERSION = "1.2.1"
_ALLOWED_MODES = {"auto", "performance", "safe"}


def _now() -> int:
    return int(time.time())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _default_state_dir() -> Path:
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / "JARVIS"
    root = os.environ.get("XDG_STATE_HOME")
    if root:
        return Path(root) / "jarvis"
    return Path.home() / ".jarvis"


def _cuda_driver_present() -> bool:
    """Cheap driver-level probe only; never imports CUDA/ML libraries."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        lib = ctypes.WinDLL("nvcuda.dll")
        return lib is not None
    except Exception:
        return False


def _ram_gb() -> float:
    try:
        import psutil  # already a JARVIS dependency
        return round(float(psutil.virtual_memory().total) / (1024.0 ** 3), 1)
    except Exception:
        pass
    if os.name == "posix":
        try:
            pages = int(os.sysconf("SC_PHYS_PAGES"))
            size = int(os.sysconf("SC_PAGE_SIZE"))
            return round((pages * size) / (1024.0 ** 3), 1)
        except Exception:
            pass
    return 0.0


def _physical_cores(logical: int) -> int:
    try:
        import psutil
        value = psutil.cpu_count(logical=False)
        if value:
            return max(1, int(value))
    except Exception:
        pass
    return max(1, int(logical or 1) // 2) if int(logical or 1) >= 4 else max(1, int(logical or 1))


class CompatibilityManager:
    """Creates a small, machine-local profile without touching the chat core."""

    def __init__(self, state_dir: Optional[Path] = None, snapshot_override: Optional[Dict[str, Any]] = None):
        self.state_dir = Path(state_dir) if state_dir is not None else _default_state_dir()
        self.state_file = self.state_dir / "compatibility_profile.json"
        self._lock = threading.RLock()
        self._snapshot_override = dict(snapshot_override or {})
        self._boot_started_here = False
        self._state = self._load_state()
        self._refresh_machine_if_needed()

    def _empty_state(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "version": PUBLIC_VERSION,
            "mode": "auto",
            "machine": {},
            "machine_fingerprint": "",
            "last_good": {"audio": {}},
            "last_failure": {},
            "boot": {
                "pending": False,
                "started_at": 0,
                "ready_at": 0,
                "consecutive_early_failures": 0,
                "safe_boot": False,
            },
            "updated_at": 0,
        }

    def _load_state(self) -> Dict[str, Any]:
        state = self._empty_state()
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in state:
                    if key in raw:
                        state[key] = raw[key]
        except Exception:
            pass
        if str(state.get("mode") or "auto") not in _ALLOWED_MODES:
            state["mode"] = "auto"
        if not isinstance(state.get("last_good"), dict):
            state["last_good"] = {"audio": {}}
        state["last_good"].setdefault("audio", {})
        if not isinstance(state.get("boot"), dict):
            state["boot"] = self._empty_state()["boot"]
        for key, value in self._empty_state()["boot"].items():
            state["boot"].setdefault(key, value)
        return state

    def _atomic_save(self) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._state["updated_at"] = _now()
            fd, name = tempfile.mkstemp(prefix="compat-", suffix=".json.tmp", dir=str(self.state_dir))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._state, fh, ensure_ascii=False, indent=2, sort_keys=True)
                    fh.write("\n")
                os.replace(name, self.state_file)
            finally:
                try:
                    if os.path.exists(name):
                        os.unlink(name)
                except Exception:
                    pass
        except Exception:
            # Compatibility persistence is optional. Never break the application.
            pass

    def _fast_snapshot(self) -> Dict[str, Any]:
        if self._snapshot_override:
            snap = dict(self._snapshot_override)
            logical = max(1, int(snap.get("logical_cores") or 1))
            snap.setdefault("physical_cores", _physical_cores(logical))
            snap.setdefault("ram_gb", 0.0)
            snap.setdefault("cuda_driver", False)
            snap.setdefault("system", "Windows" if os.name == "nt" else platform.system())
            snap.setdefault("release", platform.release())
            snap.setdefault("machine", platform.machine())
            snap.setdefault("processor", "")
            return snap

        logical = max(1, int(os.cpu_count() or 1))
        return {
            "system": platform.system() or ("Windows" if os.name == "nt" else "Unknown"),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cores": logical,
            "physical_cores": _physical_cores(logical),
            "ram_gb": _ram_gb(),
            "cuda_driver": _cuda_driver_present(),
        }

    @staticmethod
    def _fingerprint(snapshot: Dict[str, Any]) -> str:
        # Node name is included only in the one-way hash so profiles copied to a
        # different PC are not accidentally reused.  It is never exposed.
        material = "|".join([
            platform.node(),
            str(snapshot.get("system") or ""),
            str(snapshot.get("release") or ""),
            str(snapshot.get("machine") or ""),
            str(snapshot.get("processor") or ""),
            str(snapshot.get("logical_cores") or ""),
            str(round(_safe_float(snapshot.get("ram_gb")), 0)),
        ])
        return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()[:24]

    def _refresh_machine_if_needed(self) -> None:
        with self._lock:
            snapshot = self._fast_snapshot()
            fingerprint = self._fingerprint(snapshot)
            previous = str(self._state.get("machine_fingerprint") or "")
            self._state["machine"] = snapshot
            self._state["machine_fingerprint"] = fingerprint
            if previous and previous != fingerprint:
                # Hardware changed or profile was copied to another PC: keep the
                # user's mode choice, but discard hardware-specific last-good IO.
                self._state["last_good"] = {"audio": {}}
                self._state["last_failure"] = {}
                self._state["boot"] = self._empty_state()["boot"]
            self._atomic_save()

    def mode(self) -> str:
        value = str(self._state.get("mode") or "auto").lower()
        return value if value in _ALLOWED_MODES else "auto"

    def set_mode(self, mode: str) -> str:
        key = str(mode or "auto").strip().lower()
        aliases = {
            "automatico": "auto", "automático": "auto", "balanced": "auto",
            "desempenho": "performance", "performance": "performance",
            "compatibilidade": "safe", "maxima": "safe", "máxima": "safe", "safe": "safe",
        }
        key = aliases.get(key, key)
        if key not in _ALLOWED_MODES:
            key = "auto"
        with self._lock:
            self._state["mode"] = key
            self._atomic_save()
        return key

    def begin_boot(self) -> Dict[str, Any]:
        """Track only repeated *early* failures; one forced close never flips mode."""
        with self._lock:
            if self._boot_started_here:
                return dict(self._state.get("boot") or {})
            self._boot_started_here = True
            boot = self._state.setdefault("boot", self._empty_state()["boot"])
            now = _now()
            previous_pending = bool(boot.get("pending"))
            previous_started = int(boot.get("started_at") or 0)
            recent = previous_started > 0 and (now - previous_started) <= 30 * 60
            failures = int(boot.get("consecutive_early_failures") or 0)
            if previous_pending and recent:
                failures += 1
            elif not previous_pending:
                failures = 0
            # Compatibility Maximum only after two consecutive early failures.
            safe_boot = failures >= 2
            boot.update({
                "pending": True,
                "started_at": now,
                "ready_at": 0,
                "consecutive_early_failures": failures,
                "safe_boot": safe_boot,
            })
            self._atomic_save()
            return dict(boot)

    def mark_boot_ready(self) -> None:
        with self._lock:
            boot = self._state.setdefault("boot", self._empty_state()["boot"])
            boot.update({
                "pending": False,
                "ready_at": _now(),
                "consecutive_early_failures": 0,
                "safe_boot": False,
            })
            self._atomic_save()

    def effective_mode(self) -> str:
        boot = self._state.get("boot") or {}
        if bool(boot.get("safe_boot")):
            return "safe"
        return self.mode()

    def machine(self) -> Dict[str, Any]:
        return dict(self._state.get("machine") or {})

    def voice_policy(self) -> Dict[str, Any]:
        machine = self.machine()
        mode = self.effective_mode()
        logical = max(1, int(machine.get("logical_cores") or 1))
        physical = max(1, int(machine.get("physical_cores") or logical))
        ram = _safe_float(machine.get("ram_gb"))
        cuda = bool(machine.get("cuda_driver"))

        if mode == "safe":
            threads = max(1, min(4, physical, logical))
            return {
                "mode": mode,
                "whisper_device": "cpu",
                "whisper_compute": "int8",
                "whisper_model": "base",
                "whisper_second_pass": False,
                "cpu_threads": threads,
                "prefer_gpu": False,
            }

        if mode == "performance":
            threads = max(2, min(8, physical if physical > 1 else logical))
            return {
                "mode": mode,
                "whisper_device": "auto" if cuda else "cpu",
                "whisper_compute": "auto" if cuda else "int8",
                "whisper_model": "base",
                "whisper_second_pass": bool(ram >= 24.0 and logical >= 8),
                "cpu_threads": threads,
                "prefer_gpu": cuda,
            }

        # AUTO: conservative on ordinary office PCs, more parallel only when the
        # machine clearly has headroom. CUDA still has to pass ctranslate2's
        # real runtime probe in voice_engine before it is used.
        if logical <= 4 and 0 < ram < 12.0:
            threads = max(1, min(2, physical, logical))
        elif logical >= 12 and ram >= 24.0:
            threads = max(2, min(6, physical, logical))
        else:
            threads = max(2, min(4, physical if physical > 1 else logical))
        return {
            "mode": mode,
            "whisper_device": "auto" if cuda else "cpu",
            "whisper_compute": "auto" if cuda else "int8",
            "whisper_model": "base",
            "whisper_second_pass": False,
            "cpu_threads": threads,
            "prefer_gpu": cuda,
        }

    def audio_policy(self) -> Dict[str, Any]:
        mode = self.effective_mode()
        audio = dict((self._state.get("last_good") or {}).get("audio") or {})
        # Keep WDM-KS as a last resort. It is not banned because a minority of
        # drivers expose only that API, but stable Windows hosts are preferred.
        host_penalty = {
            "wasapi": -30,
            "directsound": -12,
            "mme": 0,
            "wdm-ks": 160 if mode == "safe" else 120,
            "wdm ks": 160 if mode == "safe" else 120,
        }
        return {
            "mode": mode,
            "host_penalty": host_penalty,
            "last_good_device": str(audio.get("device_name") or ""),
            "last_good_hostapi": str(audio.get("hostapi") or ""),
            "last_good_rate": int(audio.get("sample_rate") or 0),
            "fallback_rates": [48000, 44100, 16000],
        }

    def record_audio_success(self, device_name: str, hostapi: str, sample_rate: int) -> None:
        with self._lock:
            self._state.setdefault("last_good", {}).setdefault("audio", {}).update({
                "device_name": str(device_name or ""),
                "hostapi": str(hostapi or ""),
                "sample_rate": int(sample_rate or 0),
                "ok_at": _now(),
            })
            self._state.get("last_failure", {}).pop("audio", None)
            self._atomic_save()

    def record_audio_failure(self, detail: str) -> None:
        with self._lock:
            self._state.setdefault("last_failure", {})["audio"] = {
                "at": _now(),
                "detail": str(detail or "")[-1200:],
            }
            self._atomic_save()

    def status(self) -> Dict[str, Any]:
        machine = self.machine()
        voice = self.voice_policy()
        audio = self.audio_policy()
        return {
            "public_version": PUBLIC_VERSION,
            "mode": self.mode(),
            "effective_mode": self.effective_mode(),
            "system": str(machine.get("system") or ""),
            "release": str(machine.get("release") or ""),
            "architecture": str(machine.get("machine") or ""),
            "logical_cores": int(machine.get("logical_cores") or 1),
            "physical_cores": int(machine.get("physical_cores") or 1),
            "ram_gb": _safe_float(machine.get("ram_gb")),
            "cuda_driver": bool(machine.get("cuda_driver")),
            "voice": voice,
            "audio_last_good": {
                "device_name": audio.get("last_good_device") or "",
                "hostapi": audio.get("last_good_hostapi") or "",
                "sample_rate": int(audio.get("last_good_rate") or 0),
            },
            "safe_boot": bool((self._state.get("boot") or {}).get("safe_boot")),
        }

    def summary_text(self) -> str:
        data = self.status()
        labels = {"auto": "AUTOMATICA", "performance": "DESEMPENHO", "safe": "COMPATIBILIDADE MAXIMA"}
        voice = data["voice"]
        last = data["audio_last_good"]
        audio_line = "ainda nao aprendido"
        if last.get("device_name"):
            audio_line = f"{last['device_name']} | {last.get('hostapi') or '-'} | {last.get('sample_rate') or '-'} Hz"
        return "\n".join([
            "=== COMPATIBILIDADE ADAPTATIVA ===",
            f"Modo escolhido: {labels.get(data['mode'], data['mode'])}",
            f"Modo efetivo: {labels.get(data['effective_mode'], data['effective_mode'])}",
            f"Sistema: {data['system']} {data['release']} | {data['architecture']}",
            f"CPU: {data['physical_cores']} fisicos / {data['logical_cores']} logicos | RAM={data['ram_gb']:.1f} GB",
            f"CUDA detectado: {'SIM' if data['cuda_driver'] else 'NAO'}",
            f"Whisper recomendado: {voice['whisper_device']} / {voice['whisper_compute']} | threads={voice['cpu_threads']}",
            f"Audio aprendido: {audio_line}",
            f"Fallback de boot: {'ATIVO' if data['safe_boot'] else 'NAO'}",
        ])


_SINGLETON: Optional[CompatibilityManager] = None
_SINGLETON_LOCK = threading.Lock()


def get_compatibility_manager() -> CompatibilityManager:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = CompatibilityManager()
    return _SINGLETON


__all__ = ["CompatibilityManager", "get_compatibility_manager", "SCHEMA_VERSION", "PUBLIC_VERSION"]
