"""JARVIS - bloqueio opcional por voz do usuário.

Não é usado como único wake-word. Ele é uma terceira barreira opcional:
Vosk restrito + Vosk livre + (se cadastrado) embedding de voz.

O perfil fica local em <pasta do JARVIS>/data/voice_profile.npy.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Iterable, Optional, Tuple

import numpy as np

from jarvis_identity import env as jarvis_env


MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/"
    "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
)
MODEL_FILENAME = "speaker_guard_campplus.onnx"
SAMPLE_RATE = 16000


class SpeakerGuard:
    def __init__(self, project_dir: str, logger=None, threshold: Optional[float] = None):
        self.project_dir = Path(project_dir)
        self.logger = logger
        self.data_dir = self.project_dir / "data"
        self.models_dir = self.data_dir / "voice_models"
        self.profile_path = self.data_dir / "voice_profile.npy"
        self.model_path = self.models_dir / MODEL_FILENAME
        self.threshold = float(
            threshold if threshold is not None else jarvis_env("SPEAKER_THRESHOLD", "0.58")
        )
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._extractor = None
        self._profile = None

    def _log(self, level: str, message: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "SPEAKER")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    @property
    def enrolled(self) -> bool:
        return self.profile_path.exists()

    def status(self) -> dict:
        return {
            "enrolled": self.enrolled,
            "threshold": self.threshold,
            "model_ready": self.model_path.exists(),
            "profile": str(self.profile_path),
        }

    def _ensure_model(self):
        if self.model_path.exists() and self.model_path.stat().st_size > 500_000:
            return
        temp = self.model_path.with_suffix(".download")
        self._log("info", "Baixando modelo local de identificação de voz...")
        urllib.request.urlretrieve(MODEL_URL, temp)
        if not temp.exists() or temp.stat().st_size < 500_000:
            raise RuntimeError("download do modelo de voz inválido")
        temp.replace(self.model_path)

    def _load_extractor(self):
        if self._extractor is not None:
            return self._extractor
        self._ensure_model()
        import sherpa_onnx
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(self.model_path),
            num_threads=1,
            debug=False,
            provider="cpu",
        )
        if not config.validate():
            raise RuntimeError("configuração inválida do SpeakerGuard")
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        return self._extractor

    @staticmethod
    def _pcm_to_float(audio: bytes) -> np.ndarray:
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return samples
        return np.ascontiguousarray(samples / 32768.0)

    @staticmethod
    def _trim_voice(samples: np.ndarray) -> np.ndarray:
        """Remove silêncio nas pontas sem alterar o miolo da frase."""
        if samples.size < int(SAMPLE_RATE * 0.35):
            return samples
        frame = int(SAMPLE_RATE * 0.02)
        if frame <= 0:
            return samples
        rms = []
        for start in range(0, samples.size - frame + 1, frame):
            part = samples[start:start + frame]
            rms.append(float(np.sqrt(np.mean(part * part) + 1e-12)))
        if not rms:
            return samples
        arr = np.asarray(rms, dtype=np.float32)
        noise = float(np.percentile(arr, 25))
        peak = float(np.max(arr))
        threshold = max(0.0045, min(0.055, noise * 2.2 + 0.003))
        threshold = min(threshold, peak * 0.42) if peak > 0 else threshold
        active = np.where(arr >= threshold)[0]
        if active.size == 0:
            return samples
        pad_frames = 5  # 100 ms
        first = max(0, int(active[0]) - pad_frames)
        last = min(len(arr) - 1, int(active[-1]) + pad_frames)
        begin = first * frame
        end = min(samples.size, (last + 1) * frame)
        trimmed = samples[begin:end]
        return trimmed if trimmed.size >= int(SAMPLE_RATE * 0.40) else samples

    def embedding_from_pcm(self, audio: bytes) -> np.ndarray:
        extractor = self._load_extractor()
        samples = self._trim_voice(self._pcm_to_float(audio))
        if samples.size < int(SAMPLE_RATE * 0.45):
            raise ValueError("amostra de voz curta demais")
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=samples)
        stream.input_finished()
        if not extractor.is_ready(stream):
            raise RuntimeError("modelo de voz não ficou pronto para a amostra")
        embedding = np.asarray(extractor.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(embedding))
        if norm <= 1e-8:
            raise RuntimeError("embedding de voz vazio")
        return embedding / norm

    def _load_profile(self) -> np.ndarray:
        if self._profile is not None:
            return self._profile
        if not self.enrolled:
            raise FileNotFoundError("perfil de voz ainda não cadastrado")
        profile = np.asarray(np.load(self.profile_path), dtype=np.float32)
        norm = float(np.linalg.norm(profile))
        if norm <= 1e-8:
            raise RuntimeError("perfil de voz inválido")
        self._profile = profile / norm
        return self._profile

    def enroll(self, samples: Iterable[bytes]) -> float:
        embeddings = [self.embedding_from_pcm(item) for item in samples if item]
        if len(embeddings) < 3:
            raise ValueError("grave pelo menos 3 amostras")
        profile = np.mean(np.stack(embeddings, axis=0), axis=0)
        profile /= max(float(np.linalg.norm(profile)), 1e-8)
        np.save(self.profile_path, profile.astype(np.float32))
        self._profile = profile.astype(np.float32)
        # Similaridade média interna ajuda a detectar uma gravação ruim.
        sims = [float(np.dot(self._profile, emb)) for emb in embeddings]
        return float(sum(sims) / len(sims))

    def verify(self, audio: bytes) -> Tuple[bool, float]:
        if not self.enrolled:
            return True, 1.0
        try:
            profile = self._load_profile()
            candidate = self.embedding_from_pcm(audio)
            score = float(np.dot(profile, candidate))
            return score >= self.threshold, score
        except Exception as exc:
            # Fail-closed quando o usuário ativou um perfil: melhor não acordar
            # do que abrir o JARVIS por uma voz errada.
            self._log("warning", f"Falha ao verificar voz: {exc}")
            return False, 0.0


def _record_one(seconds: float = 2.0) -> bytes:
    import sounddevice as sd
    print(f"Gravando por {seconds:.1f}s... diga: Oi Jarvis")
    data = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    return data.tobytes()


def enroll_cli(project_dir: str):
    guard = SpeakerGuard(project_dir)
    print("\nJARVIS - CADASTRO DA SUA VOZ")
    print("Isso reduz muito ativações por outras pessoas/calls.")
    print("Use o mesmo microfone que você usará normalmente.\n")
    recordings = []
    for index in range(4):
        input(f"Amostra {index + 1}/4 - pressione ENTER e depois diga 'Oi Jarvis' claramente...")
        time.sleep(0.15)
        recordings.append(_record_one(2.0))
        time.sleep(0.2)
    score = guard.enroll(recordings)
    print(f"\nPerfil salvo em: {guard.profile_path}")
    print(f"Consistência das amostras: {score:.3f}")
    if score < 0.60:
        print("AVISO: as gravações variaram bastante. Vale refazer em ambiente silencioso.")
    else:
        print("Cadastro concluído. O JARVIS agora pode validar a sua voz no wake word.")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    if len(sys.argv) >= 2 and sys.argv[1].lower() == "enroll":
        enroll_cli(str(root))
    else:
        print("Uso: python speaker_guard.py enroll")
