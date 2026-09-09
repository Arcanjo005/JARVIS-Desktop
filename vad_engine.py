"""JARVIS - VAD hibrido: Silero quando disponivel, WebRTC como fallback.

O motor usa Silero apenas como voto adicional de alta qualidade. Se a
instalacao/modelo falhar, o JARVIS continua com WebRTC sem perder voz.
"""
from __future__ import annotations

import os
import threading
from collections import deque
from typing import Optional


class HybridVAD:
    def __init__(self, sample_rate: int = 16000, logger=None, fallback=None):
        self.sample_rate = int(sample_rate)
        self.logger = logger
        self.fallback = fallback
        self.requested = os.getenv("ZERO_VAD_ENGINE", "auto").strip().lower()
        self.threshold = float(os.getenv("ZERO_SILERO_THRESHOLD", "0.52"))
        self._model = None
        self._torch = None
        self._np = None
        self._buffer = bytearray()
        self._last_probability = 0.0
        self._lock = threading.Lock()
        if self.requested in {"rms", "off"}:
            self.backend = self.requested
        else:
            self.backend = "webrtc" if fallback is not None else "rms"
        if self.requested not in {"webrtc", "rms", "off"}:
            self._try_load_silero()

    def _log(self, level: str, text: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(text, "VAD")
                except TypeError:
                    fn(text)
        except Exception:
            pass

    def _try_load_silero(self):
        try:
            import numpy as np
            import torch
            from silero_vad import load_silero_vad
            self._np = np
            self._torch = torch
            # ONNX reduz dependencia do caminho de inferencia PyTorch quando o
            # extra onnx-cpu esta instalado; o pacote cuida do fallback.
            try:
                self._model = load_silero_vad(onnx=True)
            except TypeError:
                self._model = load_silero_vad()
            self.backend = "silero+webrtc" if self.fallback is not None else "silero"
            self._log("info", "Silero VAD ativo no Voice Engine V7")
        except Exception as exc:
            self._model = None
            self.backend = "webrtc" if self.fallback is not None else "rms"
            self._log("warning", f"Silero VAD indisponivel; fallback {self.backend}: {exc}")

    @property
    def probability(self) -> float:
        return float(self._last_probability)

    def reset(self):
        with self._lock:
            self._buffer.clear()
            self._last_probability = 0.0
        try:
            if self._model is not None and hasattr(self._model, "reset_states"):
                self._model.reset_states()
        except Exception:
            pass

    def _silero_vote(self, raw: bytes) -> Optional[bool]:
        if self._model is None or self._torch is None or self._np is None:
            return None
        with self._lock:
            self._buffer.extend(raw)
            # Silero 16 kHz trabalha naturalmente com janelas de 512 samples.
            frame_bytes = 512 * 2
            updated = False
            while len(self._buffer) >= frame_bytes:
                chunk = bytes(self._buffer[:frame_bytes])
                del self._buffer[:frame_bytes]
                samples = self._np.frombuffer(chunk, dtype=self._np.int16).astype(self._np.float32) / 32768.0
                tensor = self._torch.from_numpy(samples)
                try:
                    prob = self._model(tensor, self.sample_rate)
                    if hasattr(prob, "item"):
                        prob = prob.item()
                    self._last_probability = float(prob)
                    updated = True
                except Exception:
                    return None
            if updated or self._last_probability > 0:
                return self._last_probability >= self.threshold
            return None

    def is_speech(self, raw: bytes) -> bool:
        if self.requested in {"rms", "off"}:
            return False
        silero = self._silero_vote(raw)
        web = None
        if self.fallback is not None and self.requested != "silero":
            try:
                web = bool(self.fallback.is_speech(raw, self.sample_rate))
            except Exception:
                web = None
        if silero is None:
            return bool(web)
        if web is None:
            return bool(silero)
        # Para nao cortar voz baixa: qualquer detector positivo mantem o frame.
        # O endpoint do VoiceEngine ainda exige relacao com o noise floor.
        return bool(silero or web)

    def status(self):
        return {
            "backend": self.backend,
            "silero_probability": round(float(self._last_probability), 4),
            "silero_ready": self._model is not None,
            "webrtc_ready": self.fallback is not None,
            "threshold": self.threshold,
            "requested": self.requested,
        }
