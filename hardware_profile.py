"""JARVIS - perfil de hardware e recomendacoes de runtime.

O objetivo nao e usar todos os nucleos. O JARVIS prioriza latencia: reserva CPU para
captura de audio/UI e usa paralelismo adicional somente em trabalho de fundo.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List


class HardwareProfile:
    def __init__(self, project_dir: str | os.PathLike | None = None, logger=None):
        self.project_dir = Path(project_dir or os.environ.get("JARVIS_APP_DIR") or Path(__file__).resolve().parent)
        self.logger = logger
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.gpu_stt_config_path = self.data_dir / "gpu_stt.json"

    @staticmethod
    def _physical_cores() -> int:
        try:
            import psutil
            value = int(psutil.cpu_count(logical=False) or 0)
            if value > 0:
                return value
        except Exception:
            pass
        logical = int(os.cpu_count() or 4)
        return max(1, logical // 2) if logical >= 4 else max(1, logical)

    @staticmethod
    def _logical_cores() -> int:
        return max(1, int(os.cpu_count() or 1))

    @staticmethod
    def _ram_gb() -> float:
        try:
            import psutil
            return round(float(psutil.virtual_memory().total) / (1024 ** 3), 1)
        except Exception:
            return 0.0

    @staticmethod
    def cpu_name() -> str:
        if os.name == "nt":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                )
                try:
                    value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                    if value:
                        return " ".join(str(value).split())
                finally:
                    winreg.CloseKey(key)
            except Exception:
                pass
        return " ".join((platform.processor() or platform.machine() or "CPU desconhecida").split())

    @staticmethod
    def gpu_names(timeout: float = 2.5) -> List[str]:
        if os.name != "nt":
            return []
        commands = [
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance Win32_VideoController | ForEach-Object {$_.Name}) -join '|'",
            ],
            ["wmic", "path", "win32_VideoController", "get", "name", "/value"],
        ]
        for cmd in commands:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                raw = (proc.stdout or "").strip()
                if not raw:
                    continue
                if "Name=" in raw:
                    names = [line.split("=", 1)[1].strip() for line in raw.splitlines() if line.startswith("Name=")]
                else:
                    names = [part.strip() for part in raw.split("|") if part.strip()]
                if names:
                    # Preserva ordem e remove duplicatas.
                    return list(dict.fromkeys(names))
            except Exception:
                continue
        return []

    def gpu_stt_config(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.gpu_stt_config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def recommended_whisper_threads(self) -> int:
        override = os.getenv("ZERO_WHISPER_CPU_THREADS", "").strip()
        if override:
            try:
                return max(2, min(int(override), 24))
            except Exception:
                pass

        physical = self._physical_cores()
        logical = self._logical_cores()
        # Frases curtas sofrem com oversubscription. Em Xeon grande, usar metade
        # dos fisicos (ate 12) deixa folga para Vosk/VAD/UI/TTS e costuma reduzir
        # a cauda de latencia em vez de saturar todos os threads.
        if physical <= 4:
            value = physical
        elif physical <= 8:
            value = physical - 1
        elif physical <= 16:
            value = max(6, physical // 2 + 2)
        else:
            value = max(8, physical // 2)
        return max(2, min(int(value), 12, logical))

    def tts_prefetch_workers(self) -> int:
        physical = self._physical_cores()
        return max(2, min(6, physical // 3 if physical >= 6 else 2))

    def read_parallel_workers(self) -> int:
        physical = self._physical_cores()
        return max(2, min(8, physical // 2 if physical >= 4 else 2))

    def snapshot(self, include_gpu: bool = True) -> Dict[str, Any]:
        physical = self._physical_cores()
        logical = self._logical_cores()
        cpu = self.cpu_name()
        gpus = self.gpu_names() if include_gpu else []
        config = self.gpu_stt_config()
        return {
            "cpu": cpu,
            "is_xeon": "xeon" in cpu.lower(),
            "physical_cores": physical,
            "logical_cores": logical,
            "ram_gb": self._ram_gb(),
            "gpus": gpus,
            "amd_gpu": next((name for name in gpus if "amd" in name.lower() or "radeon" in name.lower()), ""),
            "rx580_detected": any("rx 580" in name.lower() or "rx580" in name.lower() for name in gpus),
            "whisper_cpu_threads": self.recommended_whisper_threads(),
            "tts_prefetch_workers": self.tts_prefetch_workers(),
            "read_parallel_workers": self.read_parallel_workers(),
            "gpu_stt": config,
        }


__all__ = ["HardwareProfile"]
