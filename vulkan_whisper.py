"""Lightweight whisper.cpp Vulkan server client for JARVIS local STT fallback.

The GPU runtime is installed separately by ATIVAR_GPU_STT_AMD.bat so the normal
Build 12 patch stays small. The server keeps the model loaded between turns.
"""
from __future__ import annotations

import atexit
import io
import json
import os
import subprocess
import threading
import time
import urllib.request
import uuid
import wave
from pathlib import Path


class VulkanWhisperError(RuntimeError):
    pass


class VulkanWhisperClient:
    def __init__(self, config: dict, sample_rate: int = 16000, logger=None):
        self.config = dict(config or {})
        self.sample_rate = int(sample_rate)
        self.logger = logger
        self.port = int(self.config.get("port") or 8177)
        self.host = "127.0.0.1"
        self.binary = Path(str(self.config.get("server_exe") or ""))
        self.model = Path(str(self.config.get("model_path") or ""))
        self.threads = max(2, min(int(self.config.get("cpu_threads") or 6), 12))
        self.process = None
        self._lock = threading.RLock()
        atexit.register(self.close)

    def _log(self, level: str, text: str) -> None:
        if callable(self.logger):
            try:
                self.logger(level, text)
            except Exception:
                pass

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _alive(self) -> bool:
        try:
            with urllib.request.urlopen(self.base_url + "/", timeout=0.35) as response:
                return int(getattr(response, "status", 200)) < 500
        except Exception:
            return False

    def ensure_server(self, timeout: float = 10.0) -> None:
        with self._lock:
            if self._alive():
                return
            if not self.binary.is_file():
                raise VulkanWhisperError(f"whisper-server nao encontrado: {self.binary}")
            if not self.model.is_file():
                raise VulkanWhisperError(f"modelo whisper.cpp nao encontrado: {self.model}")
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.terminate()
                except Exception:
                    pass
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            cmd = [
                str(self.binary), "-m", str(self.model), "-t", str(self.threads),
                "-l", "auto", "--host", self.host, "--port", str(self.port), "-nt",
            ]
            self._log("info", f"Iniciando Whisper Vulkan GPU local na porta {self.port}")
            self.process = subprocess.Popen(
                cmd,
                cwd=str(self.binary.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            deadline = time.monotonic() + max(2.0, float(timeout))
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise VulkanWhisperError(f"whisper-server encerrou com codigo {self.process.returncode}")
                if self._alive():
                    self._log("info", "Whisper Vulkan GPU pronto")
                    return
                time.sleep(0.10)
            raise VulkanWhisperError("timeout ao iniciar whisper-server Vulkan")

    def _wav_bytes(self, waveform) -> bytes:
        try:
            import numpy as np
            arr = np.asarray(waveform, dtype=np.float32).reshape(-1)
            arr = np.clip(arr, -1.0, 1.0)
            pcm = (arr * 32767.0).astype(np.int16).tobytes()
        except Exception as exc:
            raise VulkanWhisperError(f"audio invalido: {exc}") from exc
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm)
        return out.getvalue()

    @staticmethod
    def _multipart(wav_data: bytes, language: str = "auto") -> tuple[bytes, str]:
        boundary = "----jarvis" + uuid.uuid4().hex
        chunks = []
        def field(name: str, value: str) -> None:
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        field("response_format", "json")
        field("temperature", "0.0")
        field("language", language or "auto")
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\n"
            "Content-Type: audio/wav\r\n\r\n".encode("utf-8")
        )
        chunks.append(wav_data)
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def transcribe(self, waveform, language: str = "auto", timeout: float = 7.0) -> str:
        self.ensure_server()
        wav_data = self._wav_bytes(waveform)
        body, content_type = self._multipart(wav_data, language=language)
        req = urllib.request.Request(
            self.base_url + "/inference",
            data=body,
            method="POST",
            headers={"Content-Type": content_type, "Accept": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=max(1.5, float(timeout))) as response:
                raw = response.read()
        except Exception as exc:
            raise VulkanWhisperError(f"falha na inferencia Vulkan: {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            text = raw.decode("utf-8", errors="replace").strip()
            self._log("info", f"Whisper Vulkan inferencia={int((time.monotonic()-started)*1000)}ms")
            return text
        text = ""
        if isinstance(payload, dict):
            text = str(payload.get("text") or payload.get("transcription") or "").strip()
            if not text and isinstance(payload.get("data"), dict):
                text = str(payload["data"].get("text") or "").strip()
        self._log("info", f"Whisper Vulkan inferencia={int((time.monotonic()-started)*1000)}ms")
        return text

    def close(self) -> None:
        with self._lock:
            proc = self.process
            self.process = None
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


__all__ = ["VulkanWhisperClient", "VulkanWhisperError"]
