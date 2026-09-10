"""
JARVIS - Voice Engine
Wake word offline + reconhecimento local de comandos + voz masculina neural.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import math
import os
import queue
import re
import struct
import tempfile
import threading
import time
import unicodedata
import urllib.request
import wave
import zipfile
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

from jarvis_version import PUBLIC_NAME, WAKE_NAME
from jarvis_identity import env as jarvis_env
from typing import Callable, Optional, Tuple

try:
    from text_sanitizer import sanitize_text
except Exception:
    def sanitize_text(text, *, limit=260, preserve_newlines=False):
        value = unicodedata.normalize("NFC", str(text or "")).replace("\ufffd", "")
        value = "".join(ch for ch in value if not unicodedata.category(ch).startswith("C"))
        value = " ".join(value.split()).strip()
        return value[:limit] if limit and len(value) > limit else value

try:
    from intent_parser import (
        normalize_command,
        looks_like_local_command,
        is_complete_local_command,
    )
except Exception:
    normalize_command = lambda text: str(text or "").strip()
    looks_like_local_command = lambda text: False
    is_complete_local_command = lambda text: False

try:
    from jarvis_router import V8Router as VoiceV8Router
except Exception:
    VoiceV8Router = None

try:
    from hardware_profile import HardwareProfile
except Exception:
    HardwareProfile = None

try:
    from speaker_guard import SpeakerGuard
except Exception:
    SpeakerGuard = None

try:
    from universal_app_resolver import (
        load_voice_terms, normalize_name as normalize_app_name,
        spoken_similarity as spoken_app_similarity,
    )
except Exception:
    load_voice_terms = lambda project_dir, limit=220: []
    normalize_app_name = lambda text: str(text or "").lower().strip()
    spoken_app_similarity = lambda a, b: 0.0

try:
    from vad_engine import HybridVAD
except Exception:
    HybridVAD = None

try:
    from jarvis_state import JarvisStateMachine
except Exception:
    JarvisStateMachine = None

try:
    from jarvis_reliability import ReliabilityTracker
except Exception:
    ReliabilityTracker = None

try:
    from deepgram_flux import (
        DeepgramFluxSession,
        get_api_key as get_deepgram_api_key,
        get_key_state as get_deepgram_key_state,
        mark_key_invalid as mark_deepgram_key_invalid,
        mark_key_valid as mark_deepgram_key_valid,
        is_configured as deepgram_is_configured,
        load_project_keyterms,
    )
except Exception:
    DeepgramFluxSession = None
    get_deepgram_api_key = lambda project_dir: ""
    get_deepgram_key_state = lambda project_dir: {"configured": False, "invalid_auth": False}
    mark_deepgram_key_invalid = lambda project_dir, api_key, error="": None
    mark_deepgram_key_valid = lambda project_dir, api_key: None
    deepgram_is_configured = lambda project_dir: False
    load_project_keyterms = lambda project_dir, limit=100: []


class VoiceEngineError(RuntimeError):
    pass


class _AudioRingStream:
    """Callback de audio -> ring buffer com reblocagem para 20 ms.

    PortAudio pode entregar blocos de tamanho variavel quando ``blocksize=0``.
    O callback apenas copia bytes, recompõe quadros fixos e coloca no ring; VAD,
    Vosk e Whisper continuam fora da thread do driver. Se o consumidor atrasar,
    o quadro mais antigo e descartado para preservar audio recente.
    """

    SAMPLE_WIDTH = 2  # int16 mono

    def __init__(self, block_frames: int, sample_rate: int, seconds: float = 8.0, watchdog: float = 1.4):
        self.block_frames = int(block_frames)
        self.sample_rate = int(sample_rate)
        self._chunk_bytes = max(2, self.block_frames * self.SAMPLE_WIDTH)
        chunk_seconds = max(0.001, self.block_frames / max(1, self.sample_rate))
        max_chunks = max(80, int(float(seconds) / chunk_seconds))
        self._queue = queue.Queue(maxsize=max_chunks)
        self._watchdog = max(0.5, float(watchdog))
        self._last_callback = time.monotonic()
        self._dropped = 0
        self._overflow_seen = False
        self._driver_overflows = 0
        self._pending = bytearray()
        self._pending_lock = threading.Lock()
        self._lock = threading.Lock()

    def _offer(self, raw: bytes) -> None:
        item = (raw, False)
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
        except Exception:
            pass
        with self._lock:
            self._dropped += 1
            self._overflow_seen = True
        try:
            self._queue.put_nowait(item)
        except Exception:
            pass

    def callback(self, indata, frames, time_info, status):
        raw = bytes(indata)
        overflow = bool(getattr(status, "input_overflow", False)) if status is not None else False
        with self._lock:
            self._last_callback = time.monotonic()
            if overflow:
                self._overflow_seen = True
                self._driver_overflows += 1

        # Callback serial do PortAudio; discard() pode ser chamado pelo
        # consumidor entre interacoes, por isso a reblocagem usa lock proprio.
        chunks = []
        with self._pending_lock:
            self._pending.extend(raw)
            while len(self._pending) >= self._chunk_bytes:
                chunks.append(bytes(self._pending[:self._chunk_bytes]))
                del self._pending[:self._chunk_bytes]
        for chunk in chunks:
            self._offer(chunk)

    def read(self, frames: int):
        try:
            raw, _ = self._queue.get(timeout=self._watchdog)
        except queue.Empty as exc:
            age = time.monotonic() - self._last_callback
            raise VoiceEngineError(
                f"Watchdog do microfone: driver sem entregar audio por {age:.2f}s"
            ) from exc
        with self._lock:
            flagged = bool(self._overflow_seen)
            self._overflow_seen = False
        return raw, flagged

    def read_latest(self, frames: int, max_backlog_chunks: int = 18):
        """Leitura de baixa latencia para o wake loop.

        Se o consumidor ficou para tras, descarta somente audio antigo de wake
        e volta para uma janela recente. Captura de comando usa read() normal.
        """
        max_backlog_chunks = max(4, int(max_backlog_chunks))
        try:
            depth = self._queue.qsize()
        except Exception:
            depth = 0
        if depth > max_backlog_chunks:
            remove = depth - max_backlog_chunks
            removed = 0
            for _ in range(remove):
                try:
                    self._queue.get_nowait()
                    removed += 1
                except queue.Empty:
                    break
            if removed:
                with self._lock:
                    self._dropped += removed
                    self._overflow_seen = True
        return self.read(frames)

    def discard(self):
        removed = 0
        while True:
            try:
                self._queue.get_nowait()
                removed += 1
            except queue.Empty:
                break
        with self._pending_lock:
            self._pending.clear()
        return removed

    @property
    def depth(self) -> int:
        try:
            return int(self._queue.qsize())
        except Exception:
            return 0

    @property
    def dropped(self) -> int:
        with self._lock:
            return int(self._dropped)

    @property
    def driver_overflows(self) -> int:
        with self._lock:
            return int(self._driver_overflows)

    @property
    def callback_age_ms(self) -> int:
        with self._lock:
            age = max(0.0, time.monotonic() - self._last_callback)
        return int(round(age * 1000.0))


class _StableDirectStream:
    """Leitura direta do PortAudio, com normalização opcional para 16 kHz.

    O wake/STT do JARVIS trabalha em 16 kHz, mas vários drivers Windows só
    expõem o microfone em 44,1/48 kHz. O adaptador lê na taxa nativa escolhida
    por ``_detect_microphone`` e devolve sempre blocos mono int16 equivalentes
    a ``VoiceEngine.SAMPLE_RATE``. Assim um headset válido não fica mudo só
    porque o host API recusou abrir 16 kHz diretamente.
    """

    def __init__(self, stream, owner, input_rate=None):
        self._stream = stream
        self._owner = owner
        self._driver_overflows = 0
        self._target_rate = int(getattr(owner, "SAMPLE_RATE", 16000) or 16000)
        try:
            self._input_rate = int(round(float(input_rate or self._target_rate)))
        except Exception:
            self._input_rate = self._target_rate
        if self._input_rate <= 0:
            self._input_rate = self._target_rate

    def _resample_to_target(self, raw: bytes, target_frames: int) -> bytes:
        if self._input_rate == self._target_rate:
            return raw
        try:
            np = self._owner._np
            samples = np.frombuffer(raw, dtype=np.int16)
            wanted = max(1, int(target_frames))
            if samples.size == wanted:
                return samples.tobytes()
            if samples.size < 2:
                return (np.zeros(wanted, dtype=np.int16)).tobytes()
            # Interpolação por bloco é suficiente para wake/STT e mantém a
            # dependência enxuta (não exige scipy/librosa no runtime).
            x_old = np.linspace(0.0, 1.0, num=samples.size, endpoint=False, dtype=np.float64)
            x_new = np.linspace(0.0, 1.0, num=wanted, endpoint=False, dtype=np.float64)
            converted = np.interp(x_new, x_old, samples.astype(np.float64))
            converted = np.clip(converted, -32768, 32767).astype(np.int16)
            return converted.tobytes()
        except Exception as exc:
            try:
                self._owner.last_error = f"Falha ao normalizar taxa do microfone: {exc}"
            except Exception:
                pass
            raise

    def read(self, frames: int):
        target_frames = max(1, int(frames))
        source_frames = max(1, int(round(target_frames * self._input_rate / self._target_rate)))
        data, overflowed = self._stream.read(source_frames)
        raw = self._resample_to_target(bytes(data), target_frames)
        now = time.monotonic()
        try:
            self._owner._last_direct_frame_at = now
            self._owner._direct_frames_read += 1
            self._owner._direct_open_failures = 0
            # Um quadro real invalida erros antigos de callback/watchdog.
            if "Watchdog do microfone" in str(getattr(self._owner, "last_error", "")):
                self._owner.last_error = ""
        except Exception:
            pass
        if overflowed:
            self._driver_overflows += 1
        return raw, overflowed

    def read_latest(self, frames: int, max_backlog_chunks: int = 18):
        # Em leitura direta nao existe backlog de callback: cada read pega o
        # proximo bloco do driver.
        return self.read(frames)

    def discard(self):
        return 0

    @property
    def depth(self) -> int:
        return 0

    @property
    def dropped(self) -> int:
        return 0

    @property
    def driver_overflows(self) -> int:
        return int(self._driver_overflows)

    @property
    def callback_age_ms(self):
        return None


class VoiceEngine:
    SAMPLE_RATE = 16000
    CHANNELS = 1

    # V6.4: Deepgram Flux e o STT online principal depois do wake word.
    # Se nao houver chave/rede, o JARVIS cai automaticamente no caminho local.
    STT_ENGINE = jarvis_env("STT_ENGINE", "auto").strip().lower()
    DEEPGRAM_MODEL = jarvis_env("DEEPGRAM_MODEL", "flux-general-multi").strip()
    # Flux multilingual: PT-BR e EN-US sao hints simultaneos, nao um roteador
    # de idioma. Isso permite code-switching real (ex.: "abre Discord and play").
    DEEPGRAM_LANGUAGE = jarvis_env("DEEPGRAM_LANGUAGE", "pt-BR,en-US").strip()
    DEEPGRAM_LANGUAGE_HINTS = tuple(
        item.strip() for item in DEEPGRAM_LANGUAGE.replace(";", ",").split(",") if item.strip()
    ) or ("pt-BR", "en-US")
    DEEPGRAM_EAGER_EOT = float(jarvis_env("DEEPGRAM_EAGER_EOT", "0.50"))
    DEEPGRAM_EOT = float(jarvis_env("DEEPGRAM_EOT", "0.72"))
    DEEPGRAM_EOT_TIMEOUT_MS = int(jarvis_env("DEEPGRAM_EOT_TIMEOUT_MS", "2800"))
    DEEPGRAM_LOCAL_CEILING = float(jarvis_env("DEEPGRAM_LOCAL_CEILING", "0.95"))
    # 13.12.0 Voice Core: Flux can change endpoint thresholds while a turn is
    # still being spoken. Incomplete phrases become more patient; complete
    # local commands become faster. This never executes on EagerEndOfTurn.
    FLUX_ADAPTIVE_ENDPOINT = jarvis_env("FLUX_ADAPTIVE_ENDPOINT", "1").strip().lower() in ("1", "true", "on", "yes")
    FLUX_LOW_WORD_CONF = max(0.45, min(float(jarvis_env("FLUX_LOW_WORD_CONF", "0.72")), 0.90))

    VOSK_MODEL_NAME = "vosk-model-small-pt-0.3"
    VOSK_MODEL_URL = (
        "https://alphacephei.com/vosk/models/"
        "vosk-model-small-pt-0.3.zip"
    )
    VOSK_MODEL_MD5 = "458c69371c5a0b9ab6ee8fa417bf89da"

    # O modo padrão prioriza resposta rápida no Windows/CPU.
    # V6.3: base e o padrao em CPU: muito mais rapido que small neste PC, mantendo pt-BR.
    # Para forcar outro modelo: JARVIS_WHISPER_MODEL=small|medium|turbo no .env (ZERO_* ainda aceito como legado).
    WHISPER_MODEL = jarvis_env("WHISPER_MODEL", "base")
    WHISPER_DEVICE = jarvis_env("WHISPER_DEVICE", "auto").strip().lower()
    WHISPER_COMPUTE_TYPE = jarvis_env("WHISPER_COMPUTE_TYPE", "auto").strip().lower()
    WHISPER_SECOND_PASS = jarvis_env("WHISPER_SECOND_PASS", "0").strip().lower() in ("1", "true", "on", "yes")
    WHISPER_BEAM_SIZE = max(1, min(5, int(jarvis_env("WHISPER_BEAM_SIZE", "2"))))
    # Build 9: modo bilingue. `auto` deixa Whisper detectar o idioma da frase
    # enquanto preserva nomes próprios/marcas em inglês dentro de pt-BR.
    WHISPER_LANGUAGE = jarvis_env("WHISPER_LANGUAGE", "pt-en").strip().lower() or "pt-en"
    # V8: STT neutro por padrão. Bias de prompt/hotwords só entra por opt-in.
    WHISPER_BIAS = jarvis_env("WHISPER_BIAS", "0").strip().lower() in ("1", "true", "on", "yes")

    # Wake word duplo: o restrito e o livre precisam concordar. Isso reduz
    # ativações durante calls, vídeos e conversas que não mencionam o JARVIS.
    DUAL_WAKE = jarvis_env("DUAL_WAKE", "0").strip().lower() not in (
        "0", "false", "off", "no"
    )
    WAKE_CONSENSUS_WINDOW = float(jarvis_env("WAKE_WINDOW", "0.82"))
    WAKE_FINAL_CONFIDENCE = float(jarvis_env("WAKE_CONF", "0.90"))
    # Por padrão, um único reconhecedor NÃO pode acordar o JARVIS.
    WAKE_ALLOW_SINGLE_FINAL = jarvis_env("WAKE_SINGLE_FINAL", "0").strip().lower() in (
        "1", "true", "on", "yes"
    )
    # Ao menos um dos reconhecedores deve fechar uma hipótese final. Parciais
    # de duas instâncias não são suficientes para acordar durante uma call.
    WAKE_REQUIRE_FINAL = jarvis_env("WAKE_REQUIRE_FINAL", "0").strip().lower() not in (
        "0", "false", "off", "no"
    )
    WAKE_MIN_FINAL_CONFIDENCE = float(jarvis_env("WAKE_FINAL_CONF", "0.34"))
    CALL_GUARD = jarvis_env("CALL_GUARD", "1").strip().lower() not in (
        "0", "false", "off", "no"
    )
    CALL_WINDOW_KEYWORDS = (
        "discord", "microsoft teams", "teams", "zoom", "google meet",
        "meet.google", "whatsapp", "telegram", "skype",
    )
    # Wake deve começar como uma chamada separada, não no meio de uma frase.
    WAKE_MIN_LEAD_SILENCE = float(jarvis_env("WAKE_LEAD_SILENCE", "0.03"))
    CALL_WAKE_MIN_LEAD_SILENCE = float(jarvis_env("CALL_WAKE_LEAD_SILENCE", "0.08"))
    # V5: wake exato, mas menos burocrático que o duplo-final da V4.1.
    WAKE_PARTIAL_STABLE = float(jarvis_env("WAKE_PARTIAL_STABLE", "0.10"))
    WAKE_FAST_PARTIAL = jarvis_env("WAKE_FAST_PARTIAL", "1").strip().lower() in ("1", "true", "on", "yes")
    WAKE_COOLDOWN = max(0.55, float(jarvis_env("WAKE_COOLDOWN", "0.85")))
    SPEAKER_GUARD_ENABLED = jarvis_env("SPEAKER_GUARD", "0").strip().lower() in (
        "1", "true", "on", "yes"
    )
    FOLLOWUP_START_TIMEOUT = float(jarvis_env("FOLLOWUP_TIMEOUT", "6.5"))
    INITIAL_START_TIMEOUT = float(jarvis_env("INITIAL_LISTEN_TIMEOUT", "5.0"))

    # Build 12 R2: identidade de voz e prioridade absoluta. A voz do JARVIS nao
    # deve mudar no meio de uma sessao so porque um provedor demorou. Por padrao
    # usamos exclusivamente AntonioNeural; fallbacks de outra identidade ficam
    # disponiveis apenas por opt-in no .env.
    TTS_VOICE = jarvis_env("TTS_VOICE", "pt-BR-AntonioNeural")
    TTS_VOICE_LOCK = jarvis_env("TTS_VOICE_LOCK", "1").strip().lower() not in (
        "0", "false", "off", "no"
    )
    TTS_ALLOW_LOCAL_FALLBACK = jarvis_env("TTS_ALLOW_LOCAL_FALLBACK", "0").strip().lower() in (
        "1", "true", "on", "yes"
    )
    TTS_FALLBACK_VOICES = (
        "pt-BR-HumbertoNeural",
        "pt-BR-FabioNeural",
        "pt-BR-DonatoNeural",
        "pt-BR-JulioNeural",
        "pt-BR-NicolauNeural",
        "pt-BR-ValerioNeural",
    )
    # Menos aceleracao e quase nenhuma alteracao de pitch deixam a voz neural
    # mais humana. O antigo +14/+16% em frases curtas soava apressado/robotico.
    TTS_RATE = jarvis_env("TTS_RATE", "+10%")
    TTS_PITCH = jarvis_env("TTS_PITCH", "+0Hz")
    TTS_VOLUME = jarvis_env("TTS_VOLUME", "+0%")
    # Micro-prosody changes only rate by a few percent; pitch/voice identity stay
    # locked. Pronunciation overrides live in data/tts_pronunciation.json.
    TTS_DYNAMIC_PROSODY = jarvis_env("TTS_DYNAMIC_PROSODY", "1").strip().lower() in ("1", "true", "on", "yes")
    TTS_CACHE_MAX_MB = max(32, min(int(jarvis_env("TTS_CACHE_MAX_MB", "96")), 512))
    TTS_CACHE_MAX_FILES = max(120, min(int(jarvis_env("TTS_CACHE_MAX_FILES", "480")), 2400))
    # 13.12.2: o gate adaptativo de ruido deixa de bloquear a fala por padrao.
    # O VAD continua separando voz/silencio, mas piso/gate persistentes nao
    # decidem mais se o usuario comecou a falar depois do wake word.
    MIC_NOISE_GATE = jarvis_env("MIC_NOISE_GATE", "0").strip().lower() in ("1", "true", "on", "yes")
    MIC_SENSITIVITY = max(0.85, min(float(jarvis_env("MIC_SENSITIVITY", "1.12")), 1.35))

    # Build 8: endpoint adaptativo com pausa humana. Consultas auto-contidas
    # continuam rápidas, mas conversa/ordens extensíveis toleram hesitação real.
    # Build 12 R2: endpoint mais agressivo para ordens locais. A decisao continua
    # semantica: frases incompletas recebem mais cauda, enquanto comandos locais
    # inequivocos fecham assim que a palavra final estabiliza.
    ENDPOINT_LOCAL = float(jarvis_env("ENDPOINT_LOCAL", "0.08"))
    ENDPOINT_NORMAL = float(jarvis_env("ENDPOINT_NORMAL", "0.36"))
    ENDPOINT_SHORT = float(jarvis_env("ENDPOINT_SHORT", "0.20"))
    ENDPOINT_INCOMPLETE = float(jarvis_env("ENDPOINT_INCOMPLETE", "0.92"))
    ENDPOINT_CONFIRMATION = float(jarvis_env("ENDPOINT_CONFIRM", "0.08"))
    ACOUSTIC_FALLBACK_ENDPOINT = float(jarvis_env("ACOUSTIC_ENDPOINT", "0.40"))
    TTS_CHAIN_GRACE = float(jarvis_env("TTS_CHAIN_GRACE", "0.12"))
    CAPTION_WORD_SYNC = jarvis_env("CAPTION_WORD_SYNC", "1").strip().lower() in ("1", "true", "on", "yes")
    # Uma frase final ao vivo com confianca muito alta pode dispensar Whisper
    # mesmo em conversa comum. Isso corta 1.5-3 s sem aceitar hipoteses medianas
    # como as de 0.75-0.88 observadas no log real.
    # Conversa nao pula o STT forte com uma hipotese Vosk mediocre. Comandos
    # locais reversiveis possuem uma regra separada; dialogo exige mais certeza.
    LIVE_FINAL_BYPASS_CONF = max(0.93, min(float(jarvis_env("LIVE_FINAL_BYPASS_CONF", "0.94")), 0.995))
    FAST_LANE_LOCAL_CONF = max(0.52, min(float(jarvis_env("FAST_LANE_LOCAL_CONF", "0.70")), 0.95))
    FAST_LANE_APP_CONF = max(0.58, min(float(jarvis_env("FAST_LANE_APP_CONF", "0.72")), 0.97))
    FAST_LANE_SEARCH_CONF = max(0.70, min(float(jarvis_env("FAST_LANE_SEARCH_CONF", "0.82")), 0.98))
    # Build 10: sons de estado originais. Somente acordar/iniciar e entrar em
    # OUVINDO geram cue; AGUARDANDO/FALANDO permanecem silenciosos.
    STATE_SOUNDS = jarvis_env("STATE_SOUNDS", "1").strip().lower() in ("1", "true", "on", "yes")
    STATE_SOUND_VOLUME = max(0.04, min(float(jarvis_env("STATE_SOUND_VOLUME", "0.16")), 0.35))
    # Hotfix 13.11.2: Modo Conversa e um open-mic explicito. Depois de ligado
    # pelo usuario, permanece armado ate ser desligado; janelas curtas de
    # captura podem reiniciar internamente, mas nunca devolvem a sessao ao wake.
    CONVERSATION_LISTEN_TIMEOUT = max(4.0, min(float(jarvis_env("CONVERSATION_LISTEN_TIMEOUT", "6.5")), 15.0))
    CONVERSATION_SESSION_IDLE = max(15.0, min(float(jarvis_env("CONVERSATION_SESSION_IDLE", "30")), 120.0))
    CONVERSATION_NATURAL_WINDOW = max(10.0, min(float(jarvis_env("CONVERSATION_NATURAL_WINDOW", "22")), 45.0))
    CONVERSATION_SMART_IDLE = jarvis_env("CONVERSATION_SMART_IDLE", "1").strip().lower() in ("1", "true", "on", "yes")
    CONVERSATION_ALWAYS_LISTEN = jarvis_env("CONVERSATION_ALWAYS_LISTEN", "1").strip().lower() in ("1", "true", "on", "yes")
    # Cues de estado sao uteis no modo normal, mas no open-mic viram ruido e
    # podem ser capturados pelo proprio microfone. Por padrao ficam desligados.
    CONVERSATION_STATE_SOUNDS = jarvis_env("CONVERSATION_STATE_SOUNDS", "0").strip().lower() in ("1", "true", "on", "yes")
    # 13.11.6: barge-in permanece FORA deste hotfix. A interrupcao por wake
    # durante o proprio TTS fica desativada por padrao; so existe se o usuario
    # ativar explicitamente BARGE_IN_WAKE=1 no .env.
    BARGE_IN_WAKE = jarvis_env("BARGE_IN_WAKE", "0").strip().lower() in ("1", "true", "on", "yes")
    # Build 12 R2: wake nao bloqueia mais esperando "Sim?". O overlay/cue confirma
    # visualmente e a captura abre imediatamente. Quem preferir o protocolo antigo
    # pode reativar JARVIS_VOICE_ACK=1.
    VOICE_ACK = jarvis_env("VOICE_ACK", "0").strip().lower() in ("1", "true", "on", "yes")

    LEGACY_ZERO_WAKE = jarvis_env("LEGACY_WAKE", jarvis_env("LEGACY_ZERO_WAKE", "0")).strip().lower() in ("1", "true", "on", "yes")
    JARVIS_WAKE_PHRASES = (
        "jarvis",
        "oi jarvis",
        "ei jarvis",
        "e ai jarvis",
        "ola jarvis",
        # aproximações que o Vosk pt-BR pode produzir para o nome inglês
        "jarves",
        "jervis",
        "jarbas",
        "jarvi",
        "jarvisse",
        "ja vis",
        "oi jarves",
        "oi jarbas",
        "ei jarves",
        "ei jarbas",
        "alo jarvis",
        "o jarvis",
    )
    LEGACY_WAKE_PHRASES = (
        "oi zero", "e ai zero", "ei zero", "ola zero", "eae zero",
        "oi ziro", "ei ziro",
    )
    WAKE_PHRASES = JARVIS_WAKE_PHRASES + (LEGACY_WAKE_PHRASES if LEGACY_ZERO_WAKE else ())


    HALLUCINATION_PATTERNS = (
        "obrigado por assistir",
        "obrigada por assistir",
        "legendas pela comunidade",
        "inscreva se no canal",
        "ate o proximo video",
        "thank you for watching",
    )

    def __init__(
        self,
        project_dir: Optional[str] = None,
        logger=None,
        on_state: Optional[Callable[[str, str], None]] = None,
        on_wake: Optional[Callable[[], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        on_transcript_rejected: Optional[Callable[[str], None]] = None,
        on_tts_start: Optional[Callable[[str], None]] = None,
        on_tts_end: Optional[Callable[[], None]] = None,
        on_level: Optional[Callable[[float], None]] = None,
        on_audio_metrics: Optional[Callable[[dict], None]] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
        on_caption: Optional[Callable[[str], None]] = None,
        on_live_transcript: Optional[Callable[[str], None]] = None,
    ):
        self.project_dir = Path(
            project_dir or os.environ.get("JARVIS_APP_DIR") or Path(__file__).resolve().parent
        )
        self.data_dir = self.project_dir / "data"
        self.models_dir = self.data_dir / "voice_models"
        self.tts_cache_dir = self.data_dir / "tts_cache"

        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.tts_cache_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logger
        self.on_state = on_state
        self.on_wake = on_wake
        self.on_command = on_command
        self.on_transcript_rejected = on_transcript_rejected
        self.on_tts_start = on_tts_start
        self.on_tts_end = on_tts_end
        self.on_level = on_level
        self.on_audio_metrics = on_audio_metrics
        self.on_interrupt = on_interrupt
        self.on_caption = on_caption
        self.on_live_transcript = on_live_transcript

        self._stop_event = threading.Event()
        self._manual_trigger = threading.Event()
        self._followup_trigger = threading.Event()
        self._followup_mode = "followup"
        self._listening_session = threading.Event()
        # V5.2: distingue sessão conversacional de captura REAL do microfone.
        # Isso impede o TTS de pintar a esfera como FALANDO enquanto o mic já
        # está aberto para receber a resposta do usuário.
        self._mic_capture_active = threading.Event()
        self._listening_visual_state = "OUVINDO"
        self._speaking = threading.Event()
        self._assistant_busy = threading.Event()
        self._tts_cancel_event = threading.Event()
        # Build 10: modo conversa continuo. Quando ativo, o wake loop alterna
        # automaticamente FALANDO -> OUVINDO sem exigir "Oi Jarvis" a cada turno.
        self._conversation_mode = threading.Event()
        self._conversation_mode_started_at = 0.0
        self._conversation_last_activity_at = 0.0
        self._conversation_passive = False
        self._last_external_state = ""
        self._last_state_sound_at = 0.0

        self._wake_thread = None
        self._wake_thread_lock = threading.Lock()
        # Desktop 1.1: a thread de wake agora e supervisionada. No executavel
        # empacotado o driver de audio pode levar alguns segundos para ficar
        # disponivel apos login/instalacao; uma falha de boot nao deve matar a
        # voz ate o proximo restart do JARVIS.
        self._ready_event = threading.Event()
        self._startup_attempts = 0
        self._supervisor_restarts = 0
        self._background_voice_services_started = False
        self._tts_thread = None
        self._tts_queue = queue.Queue()

        # Build 5: perfil dinamico. Em Xeon/CPU grande nao saturamos todos os
        # cores com Whisper; reservamos capacidade para PortAudio, VAD, UI e TTS.
        self._hardware_profile = None
        if HardwareProfile is not None:
            try:
                self._hardware_profile = HardwareProfile(self.project_dir, logger=self.logger)
            except Exception:
                self._hardware_profile = None
        tts_workers = (
            self._hardware_profile.tts_prefetch_workers()
            if self._hardware_profile is not None else 4
        )
        self._tts_prefetch_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=tts_workers,
            thread_name_prefix="JARVIS-TTS-PREFETCH",
        )
        self._tts_lock_guard = threading.Lock()
        self._tts_key_locks = {}
        # Build 12 R2: com voice lock, a identidade ativa nasce fixada. Sem lock
        # preservamos o comportamento legado de descobrir uma voz operacional.
        self._active_tts_voice = self.TTS_VOICE if self.TTS_VOICE_LOCK else None
        self._caption_boundary_supported = True
        self._caption_boundary_warned = False
        self._tts_voice_warned = set()

        # Telemetria nunca bloqueia a thread que le o microfone.
        self._telemetry_queue = queue.Queue(maxsize=2)
        self._telemetry_thread = None

        self._sd = None
        self._np = None
        self._vosk = None
        self._vosk_model = None
        self._whisper_model = None
        self._whisper_model_name = None
        self._whisper_backend = "faster-whisper"
        self._gpu_stt_config = (
            self._hardware_profile.gpu_stt_config()
            if self._hardware_profile is not None else {}
        )
        self._gpu_stt_last_error = ""

        # V6.4 Deepgram Flux. Nenhuma chave e registrada em log.
        self._deepgram_configured = bool(deepgram_is_configured(self.project_dir))
        self._deepgram_failures = 0
        self._deepgram_disabled_until = 0.0
        self._deepgram_last_error = ""
        self._deepgram_last_transcript = ""
        self._deepgram_last_word_confidence = 0.0
        self._deepgram_last_eot_confidence = 0.0
        self._deepgram_last_words = ()
        self._deepgram_last_low_confidence_words = ()
        self._deepgram_last_tail_ms = None
        self._deepgram_last_connect_ms = None
        self._deepgram_last_languages = ()
        self._recent_voice_terms = deque(maxlen=24)
        self._flux_last_profile = ""
        self._stt_backend = "deepgram-flux" if self._deepgram_configured else "local"

        self._interrupt_recognizer = None
        self._interrupt_voice_votes = deque(maxlen=24)
        self._interrupt_audio_window = deque(maxlen=60)
        self._interrupt_peak_ratio = 0.0
        self._interrupt_partial_hits = 0
        self._interrupt_last_partial = ""
        self._interrupt_last_partial_at = 0.0
        self._tts_started_at = 0.0
        self._last_tts_end_at = 0.0
        self._current_tts_text = ""
        self._input_device_index = None
        self._capture_sample_rate = self.SAMPLE_RATE
        self._input_hostapi = ""
        self._input_candidate_count = 0
        self._input_candidate_pos = 0
        self._auto_recovery_suspended = False
        self._audio_ring = None
        self._capture_mode = "stable-direct-16k"
        self._last_direct_frame_at = 0.0
        self._direct_frames_read = 0
        self._direct_open_failures = 0
        self._audio_overflow_total = 0
        self._audio_overflow_since_log = 0
        self._last_overflow_log_at = 0.0
        self._last_ring_drop_reported = 0
        self._stream_restart_event = threading.Event()
        self._calibration_requested = threading.Event()
        self._calibration_due_at = 0.0
        # Build 15: recalibracao usa o proprio stream de captura. Isso evita
        # fechar/reabrir o microfone apenas porque o usuario pediu calibracao.
        self._calibration_started_at = 0.0
        self._calibration_samples = deque(maxlen=160)

        # Telemetria de reconhecimento.
        self._recognition_passes = 0
        self._last_consensus_score = None
        self._whisper_runtime_device = ""
        self._whisper_runtime_compute = ""

        self._pygame = None
        self._mixer_ready = False

        self._started = False
        self._ready = False
        self._mic_available = False
        self._last_wake_at = 0.0
        self._last_interrupt_at = 0.0

        # Nível visual do microfone.
        self._visual_noise_floor = 100.0
        self._visual_peak = 1200.0
        self._last_level_emit = 0.0
        self._last_metrics_emit = 0.0
        self._adaptive_gate_raw = 150.0
        self._mic_sensitivity = float(self.MIC_SENSITIVITY)
        self._current_rms = 0.0
        self._last_noise_percent = 0
        self._last_gate_percent = 0
        self._last_snr_db = 0.0
        self._mic_quality = "CALIBRANDO"
        self._mic_calibrated = False
        self._last_stt_ms = None
        self._last_capture_ms = None
        self._last_capture_speech_ms = None
        self._last_capture_peak_ratio = None
        self._last_whisper_load_ms = None
        self._last_whisper_infer_ms = None
        self._last_whisper_total_ms = None
        self._last_detected_language = ""
        self._webrtcvad = None
        self._last_live_transcript = ""
        self._last_live_confidence = 0.0
        self._last_live_has_final = False
        self._last_live_emit_at = 0.0
        self._last_live_emit_text = ""
        # Texto literal exibido ao usuario e texto interpretado para o Router
        # sao coisas diferentes. Nunca esconda uma correcao semantica como se
        # ela tivesse vindo do microfone.
        self._last_raw_stt_text = ""
        self.last_verbatim_transcript = ""
        self._recent_stt_language = "pt"
        self._wake_audio_history = deque(maxlen=64)
        self._pending_wake_preroll = b""
        self._explicit_wake_turn = False
        self._last_endpoint_ms = None
        self._last_endpoint_reason = ""
        self._last_command_dispatch_at = 0.0
        self._last_voice_response_queue_ms = None
        self._last_tts_first_audio_ms = None
        self._hybrid_vad = None
        self._voice_terms_cache = []
        self._voice_terms_cache_at = 0.0

        # V7: observabilidade central. A FSM inicialmente observa sem bloquear
        # o legado; assim podemos medir transicoes invalidas antes de endurecer.
        self._state_machine = JarvisStateMachine() if JarvisStateMachine is not None else None
        self._reliability = ReliabilityTracker(str(self.project_dir)) if ReliabilityTracker is not None else None

        self._wake_model_path = (
            self.models_dir / self.VOSK_MODEL_NAME
        )

        self.last_error = ""
        self.last_transcript = ""
        self.last_confidence = None
        self.input_device_name = ""

        self.speaker_guard = None
        if self.SPEAKER_GUARD_ENABLED and SpeakerGuard is not None:
            try:
                self.speaker_guard = SpeakerGuard(
                    str(self.project_dir),
                    logger=self.logger,
                )
            except Exception:
                self.speaker_guard = None

        # Diagnóstico real de TTS.
        self.tts_last_ok = None
        self.tts_provider = ""
        self.tts_last_error = ""

    def _log(self, level: str, message: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "VOICE")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    def _state_sound_path(self, kind: str) -> Path:
        name = "jarvis_state_start.wav" if kind == "start" else "jarvis_state_listening.wav"
        return self.project_dir / name

    def _play_state_sound(self, kind: str, force: bool = False) -> bool:
        """Toca cue curto sem usar TTS e sem bloquear o microfone.

        Os WAVs fazem parte do build. Em Windows usamos winsound assíncrono;
        pygame é apenas fallback. Não existe cue para FALANDO/AGUARDANDO.
        """
        if not self.STATE_SOUNDS:
            return False
        now = time.monotonic()
        if not force and now - float(self._last_state_sound_at or 0.0) < 0.16:
            return False
        path = self._state_sound_path(kind)
        if not path.is_file():
            return False
        self._last_state_sound_at = now
        try:
            if os.name == "nt":
                import winsound
                winsound.PlaySound(
                    str(path),
                    winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
                return True
        except Exception:
            pass
        try:
            self._init_mixer()
            sound = self._pygame.mixer.Sound(str(path))
            sound.set_volume(float(self.STATE_SOUND_VOLUME))
            sound.play()
            return True
        except Exception:
            return False

    def play_state_cue(self, kind: str) -> bool:
        return self._play_state_sound(str(kind or "").strip().lower(), force=True)

    def set_microphone_sensitivity(self, value=1.0) -> float:
        if isinstance(value, str):
            key = value.strip().lower()
            aliases = {"normal": 1.0, "sensivel": 1.18, "sensível": 1.18, "alto": 1.18, "muito sensivel": 1.28, "muito sensível": 1.28}
            value = aliases.get(key, value)
        try:
            factor = float(value)
        except Exception:
            factor = 1.0
        self._mic_sensitivity = max(0.85, min(factor, 1.35))
        return self._mic_sensitivity

    def set_tts_rate(self, rate: str) -> str:
        value = str(rate or "+10%").strip()
        if not re.fullmatch(r"[+-]\d{1,2}%", value):
            raise ValueError("velocidade de voz inválida")
        number = max(-30, min(int(value[:-1]), 35))
        self.TTS_RATE = f"{number:+d}%"
        return self.TTS_RATE

    @property
    def conversation_mode(self) -> bool:
        return self._conversation_mode.is_set()

    def set_conversation_mode(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        if enabled:
            newly_enabled = not self._conversation_mode.is_set()
            self._conversation_mode.set()
            self._conversation_mode_started_at = time.monotonic()
            self._conversation_last_activity_at = self._conversation_mode_started_at
            self._conversation_passive = False
            self._followup_trigger.clear()
            if newly_enabled:
                if self.CONVERSATION_STATE_SOUNDS:
                    self._play_state_sound("start", force=True)
                self._log("info", "Modo conversa contínua ativado: open-mic sem wake e sem cues de estado.")
        else:
            if self._conversation_mode.is_set():
                self._log("info", "Modo conversa contínua desativado: wake word voltou a ser obrigatório.")
            self._conversation_mode.clear()
            self._conversation_mode_started_at = 0.0
            self._conversation_last_activity_at = 0.0
            self._conversation_passive = False
        return self._conversation_mode.is_set()

    def _state(self, state: str, detail: str = ""):
        state = str(state or "").upper()
        previous = self._last_external_state
        self._last_external_state = state
        # Sons somente em transicoes reais. No Modo Conversa open-mic eles
        # ficam completamente silenciosos por padrao para nao poluir a conversa
        # nem realimentar o microfone.
        conversation_silent = bool(
            getattr(self, "_conversation_mode", None)
            and self._conversation_mode.is_set()
            and not self.CONVERSATION_STATE_SOUNDS
        )
        if state != previous and not conversation_silent:
            if state == "ACORDOU":
                self._play_state_sound("start")
            elif state in ("OUVINDO", "ESPERANDO_RESPOSTA"):
                self._play_state_sound("listening")
        if self._state_machine is not None:
            try:
                transition = self._state_machine.observe(state, detail)
                if self._reliability is not None and not transition.valid:
                    self._reliability.event(
                        "invalid_state_transition",
                        from_state=transition.from_state,
                        to_state=transition.to_state,
                        external_state=state,
                    )
            except Exception:
                pass
        if self.on_state:
            try:
                self.on_state(state, detail)
            except Exception:
                pass

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def microphone_available(self) -> bool:
        return self._mic_available

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    @property
    def has_pending_speech(self) -> bool:
        """True enquanto existe áudio tocando OU ainda enfileirado para tocar."""
        try:
            return self._speaking.is_set() or (not self._tts_queue.empty())
        except Exception:
            return self._speaking.is_set()

    def status(self) -> dict:
        return {
            "started": self._started,
            "ready": self._ready,
            "microphone_available": self._mic_available,
            "input_device": self.input_device_name,
            "wake_model": str(self._wake_model_path),
            "wake_model_ready": self._wake_model_path.exists(),
            "whisper_model": (
                self._whisper_model_name
                or self.WHISPER_MODEL
            ),
            "whisper_language": self.WHISPER_LANGUAGE,
            "bilingual_recognition": self.WHISPER_LANGUAGE in {"auto", "pt-en", "bilingual", "pt+en"},
            "stt_language_policy": "pt-en-guarded" if self.WHISPER_LANGUAGE in {"pt-en", "bilingual", "pt+en"} else self.WHISPER_LANGUAGE,
            "last_detected_language": self._last_detected_language,
            "conversation_mode": self._conversation_mode.is_set(),
            "conversation_passive": bool(self._conversation_passive),
            "conversation_always_listen": bool(self.CONVERSATION_ALWAYS_LISTEN),
            "conversation_state_sounds": bool(self.CONVERSATION_STATE_SOUNDS),
            "conversation_idle_seconds": round(max(0.0, time.monotonic() - float(getattr(self, "_conversation_last_activity_at", 0.0) or getattr(self, "_conversation_mode_started_at", 0.0) or time.monotonic())), 1) if self._conversation_mode.is_set() else 0.0,
            "state_sounds": self.STATE_SOUNDS,
            "whisper_device": self._whisper_runtime_device or self.WHISPER_DEVICE,
            "whisper_compute_type": self._whisper_runtime_compute or self.WHISPER_COMPUTE_TYPE,
            "whisper_backend": self._whisper_backend,
            "gpu_stt_configured": bool(self._gpu_stt_config.get("enabled")),
            "gpu_stt_name": self._gpu_stt_config.get("gpu_name") or "",
            "gpu_stt_last_error": self._gpu_stt_last_error,
            "whisper_cpu_threads": self._physical_cpu_threads(),
            "tts_voice": self.TTS_VOICE,
            "tts_voice_lock": self.TTS_VOICE_LOCK,
            "tts_local_fallback_allowed": self.TTS_ALLOW_LOCAL_FALLBACK,
            "speaking": self._speaking.is_set(),
            "assistant_busy": self._assistant_busy.is_set(),
            "last_transcript": self.last_transcript,
            "last_confidence": self.last_confidence,
            "last_error": self.last_error,
            "interrupt_phrase": f"{PUBLIC_NAME.title()}, para",
            "recognition_passes": self._recognition_passes,
            "consensus_score": self._last_consensus_score,
            "whisper_ready": self._whisper_model is not None,
            "tts_ok": self.tts_last_ok,
            "tts_provider": self.tts_provider,
            "tts_last_error": self.tts_last_error,
            "speaker_guard_enrolled": bool(
                self.speaker_guard and self.speaker_guard.enrolled
            ),
            "stt_backend": self._stt_backend,
            "deepgram_configured": self._deepgram_configured,
            "deepgram_model": self.DEEPGRAM_MODEL,
            "deepgram_eot_confidence": round(float(self._deepgram_last_eot_confidence or 0.0), 3),
            "deepgram_word_confidence": round(float(self._deepgram_last_word_confidence or 0.0), 3),
            "deepgram_low_confidence_words": [
                {"word": str(word), "confidence": round(float(conf), 3)}
                for word, conf in (self._deepgram_last_low_confidence_words or ())[:8]
            ],
            "deepgram_tail_ms": self._deepgram_last_tail_ms,
            "flux_endpoint_profile": self._flux_last_profile,
            "deepgram_connect_ms": self._deepgram_last_connect_ms,
            "deepgram_languages": list(self._deepgram_last_languages or ()),
            "deepgram_last_error": self._deepgram_last_error,
            "endpoint_vad": "flux" if self._stt_backend == "deepgram-flux" else (
                getattr(self._hybrid_vad, "backend", None) or ("webrtc" if self._webrtcvad else "rms")
            ),
            "vad_status": self._hybrid_vad.status() if self._hybrid_vad is not None else {"backend": "webrtc" if self._webrtcvad else "rms"},
            "state_machine": self._state_machine.snapshot() if self._state_machine is not None else {},
            "reliability": self._reliability.snapshot() if self._reliability is not None else {},
            "endpoint_ms": self._last_endpoint_ms,
            "endpoint_reason": self._last_endpoint_reason,
            "stt_ms": self._last_stt_ms,
            "capture_ms": self._last_capture_ms,
            "capture_speech_ms": self._last_capture_speech_ms,
            "capture_peak_ratio": self._last_capture_peak_ratio,
            "post_speech_ms": (
                int(self._last_endpoint_ms or 0) + int(self._last_stt_ms or 0)
                if (self._last_endpoint_ms is not None or self._last_stt_ms is not None) else None
            ),
            "voice_response_queue_ms": self._last_voice_response_queue_ms,
            "tts_first_audio_ms": self._last_tts_first_audio_ms,
            "end_of_speech_to_audio_ms": (
                int(self._last_endpoint_ms or 0) + int(self._last_stt_ms or 0) + int(self._last_tts_first_audio_ms or 0)
                if self._last_tts_first_audio_ms is not None and (self._last_endpoint_ms is not None or self._last_stt_ms is not None)
                else None
            ),
            "voice_ack_enabled": self.VOICE_ACK,
            "whisper_load_ms": self._last_whisper_load_ms,
            "whisper_infer_ms": self._last_whisper_infer_ms,
            "whisper_total_ms": self._last_whisper_total_ms,
            "audio_ring_depth": getattr(self._audio_ring, "depth", 0) if self._audio_ring else 0,
            "audio_ring_dropped": getattr(self._audio_ring, "dropped", 0) if self._audio_ring else 0,
            "audio_driver_overflows": getattr(self._audio_ring, "driver_overflows", self._audio_overflow_total) if self._audio_ring else self._audio_overflow_total,
            "audio_callback_age_ms": getattr(self._audio_ring, "callback_age_ms", None) if self._audio_ring else None,
            "noise_percent": self._last_noise_percent,
            "gate_percent": self._last_gate_percent,
            "mic_sensitivity": round(float(getattr(self, "_mic_sensitivity", 1.0)), 2),
            "snr_db": round(float(self._last_snr_db or 0.0), 1),
            "mic_quality": self._mic_quality,
            "mic_calibrated": self._mic_calibrated,
            "wake_requires_final": self.WAKE_REQUIRE_FINAL,
            "call_guard": self.CALL_GUARD,
            "tts_rate": self.TTS_RATE,
            "tts_active_voice": self._active_tts_voice or self.TTS_VOICE,
            "caption_word_sync": self.CAPTION_WORD_SYNC,
            "transcript_mode": "full-utterance+semantic-fastlane",
            "capture_mode": self._capture_mode,
            "capture_sample_rate": int(getattr(self, "_capture_sample_rate", self.SAMPLE_RATE) or self.SAMPLE_RATE),
            "input_device_index": self._input_device_index,
            "input_hostapi": str(getattr(self, "_input_hostapi", "") or ""),
            "input_candidate_count": int(getattr(self, "_input_candidate_count", 0) or 0),
            "input_candidate_pos": int(getattr(self, "_input_candidate_pos", 0) or 0),
            "auto_recovery_suspended": bool(getattr(self, "_auto_recovery_suspended", False)),
            "wake_thread_alive": bool(self._wake_thread and self._wake_thread.is_alive()),
            "startup_attempts": int(self._startup_attempts),
            "supervisor_restarts": int(self._supervisor_restarts),
            "direct_frames_read": int(self._direct_frames_read),
            "last_audio_frame_age_ms": (
                int(round(max(0.0, time.monotonic() - self._last_direct_frame_at) * 1000.0))
                if self._last_direct_frame_at else None
            ),
            "direct_open_failures": int(self._direct_open_failures),
        }

    def _spawn_wake_thread_classic(self) -> bool:
        """Inicia uma unica thread supervisionada de wake/audio."""
        with self._wake_thread_lock:
            if self._wake_thread is not None and self._wake_thread.is_alive():
                return True
            self._wake_thread = threading.Thread(
                target=self._voice_supervisor_loop,
                name="JARVIS-WAKE",
                daemon=True,
            )
            self._wake_thread.start()
            return True

    def _start_background_voice_services_once(self):
        if self._background_voice_services_started:
            return
        self._background_voice_services_started = True
        threading.Thread(
            target=self._maintain_tts_cache,
            name="JARVIS-TTS-CACHE-MAINT",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._prewarm_ack,
            name="JARVIS-TTS-PREWARM",
            daemon=True,
        ).start()

    def _voice_supervisor_loop(self):
        """Mantém a voz viva sem criar tempestade de logs/reconexões.

        Falta de microfone e falhas de recurso (ex.: download/modelo Vosk)
        usam backoff longo. Falhas transitórias de stream continuam com retry
        rápido, preservando a recuperação automática normal.
        """
        transient_delay = 0.75
        resource_delay = 30.0
        while not self._stop_event.is_set():
            self._startup_attempts += 1
            self._ready_event.clear()
            self._ready = False
            self._bootstrap_and_listen()
            if self._stop_event.is_set():
                return

            self._ready = False
            self._ready_event.clear()
            self._supervisor_restarts += 1
            detail = str(self.last_error or "Entrada de áudio indisponível").strip()
            detail_key = detail.lower()

            resource_problem = (
                not bool(self._mic_available)
                or "vosk" in detail_key
                or "wake word" in detail_key
                or ".download" in detail_key
                or "modelo" in detail_key
                or "download" in detail_key
            )

            if resource_problem:
                self._auto_recovery_suspended = True
                wait_s = resource_delay
                resource_delay = min(300.0, resource_delay * 2.0)
                transient_delay = 0.75
                state = "SEM_MICROFONE" if not bool(self._mic_available) else "AGUARDANDO_RECURSO"
                self._state(state, detail[:180])
                self._log(
                    "warning",
                    f"Voz aguardando recurso; nova tentativa em {int(wait_s)}s "
                    f"(tentativa {self._startup_attempts}).",
                )
            else:
                self._auto_recovery_suspended = False
                resource_delay = 30.0
                wait_s = transient_delay
                transient_delay = min(5.0, transient_delay * 1.65)
                self._state("RECONECTANDO", detail[:180])
                self._log(
                    "warning",
                    f"Motor de voz será reaberto em {wait_s:.2f}s "
                    f"(tentativa {self._startup_attempts}).",
                )

            if self._stop_event.wait(wait_s):
                return
    def wait_until_ready(self, timeout: float = 0.0) -> bool:
        if self._ready:
            return True
        try:
            return bool(self._ready_event.wait(max(0.0, float(timeout))))
        except Exception:
            return bool(self._ready)

    def start(self):
        if self._started:
            return

        self._started = True
        self._stop_event.clear()

        self._tts_thread = threading.Thread(
            target=self._tts_worker,
            name="JARVIS-TTS",
            daemon=True,
        )
        self._tts_thread.start()

        self._telemetry_thread = threading.Thread(
            target=self._telemetry_worker,
            name="JARVIS-MIC-TELEMETRY",
            daemon=True,
        )
        self._telemetry_thread.start()

        self._spawn_wake_thread_classic()

    def stop(self):
        self._stop_event.set()
        self._ready = False
        self._ready_event.clear()
        self._manual_trigger.set()
        self._followup_trigger.set()
        try:
            self._tts_queue.put_nowait(None)
        except Exception:
            pass
        try:
            self._telemetry_queue.put_nowait(None)
        except Exception:
            pass
        self.stop_speaking()
        try:
            self._tts_prefetch_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def set_assistant_busy(self, busy: bool):
        if busy:
            self._assistant_busy.set()
        else:
            self._assistant_busy.clear()

    def trigger_manual(self):
        self._manual_trigger.set()

    def trigger_followup(self, mode: str = "followup"):
        """Escuta resposta sem wake. mode='confirmation' mostra estado específico."""
        self._followup_mode = str(mode or "followup").strip().lower()
        self._followup_trigger.set()

    def speak(
        self,
        text: str,
        wait: bool = False,
        interrupt: bool = False,
        post_delay: float = 0.0,
        prompt: bool = False,
        fast: bool = False,
    ):
        clean = self._clean_tts_text(text)
        if not clean:
            return None

        if interrupt:
            self.stop_speaking(clear_queue=True)

        done = threading.Event()

        # A síntese começa AGORA, no momento em que o trecho entra na fila.
        # Enquanto o trecho anterior toca, o próximo já está sendo preparado.
        # Isso elimina a pausa "parágrafo -> espera -> parágrafo".
        future = None
        try:
            future = self._tts_prefetch_pool.submit(
                self._synthesize_edge,
                clean,
            )
        except Exception:
            future = None

        command_origin = 0.0
        if self._assistant_busy.is_set() and self._last_command_dispatch_at:
            command_origin = float(self._last_command_dispatch_at)
            if self._last_voice_response_queue_ms is None:
                self._last_voice_response_queue_ms = int(round((time.monotonic() - command_origin) * 1000.0))

        self._tts_queue.put({
            "text": clean,
            "command_origin": command_origin,
            "done": done,
            "post_delay": max(0.0, float(post_delay)),
            "future": future,
            "prompt": bool(prompt),
            "fast": bool(fast),
        })

        if wait:
            done.wait(timeout=120)

        return done

    def _clear_tts_queue(self):
        while True:
            try:
                item = self._tts_queue.get_nowait()
            except queue.Empty:
                break

            if item is None:
                try:
                    self._tts_queue.put_nowait(None)
                except Exception:
                    pass
                break

            done = item.get("done") if isinstance(item, dict) else None
            if done:
                try:
                    done.set()
                except Exception:
                    pass

    def stop_speaking(self, clear_queue: bool = True):
        """Interrompe TTS atual e, por padrão, descarta o restante da resposta."""
        self._tts_cancel_event.set()

        if clear_queue:
            self._clear_tts_queue()

        try:
            if self._pygame and self._mixer_ready:
                self._pygame.mixer.music.stop()
        except Exception:
            pass

        try:
            engine = getattr(self, "_fallback_engine", None)
            if engine is not None:
                engine.stop()
        except Exception:
            pass

    def _bootstrap_and_listen(self):
        try:
            self._state("PREPARANDO", "Inicializando voz")
            self._load_audio_dependencies()
            self._detect_microphone()

            if not self._mic_available:
                self._ready = False
                self._ready_event.clear()
                if not self.last_error:
                    self.last_error = "Nenhum dispositivo de entrada disponível"
                self._state(
                    "SEM_MICROFONE",
                    self.last_error
                )
                return

            self._ensure_vosk_model()
            if self._vosk_model is None:
                self._load_vosk_model()
            self._auto_calibrate_microphone(duration=1.05)

            self._ready = True
            self._ready_event.set()
            self._state(
                "AGUARDANDO",
                f"Diga '{PUBLIC_NAME.title()}'"
            )

            if self._deepgram_should_use("normal"):
                self._stt_backend = "deepgram-flux"
                self._log("info", "Deepgram Flux configurado como STT principal; Whisper fica como fallback.")
            else:
                self._stt_backend = "local"
                threading.Thread(
                    target=self._safe_preload_whisper,
                    name="JARVIS-WHISPER-PRELOAD",
                    daemon=True,
                ).start()
                if self.STT_ENGINE in ("auto", "deepgram", "flux") and not self._deepgram_configured:
                    self._log("info", "Deepgram nao configurado; usando STT local. Execute CONFIGURAR_DEEPGRAM.bat.")

            self._start_background_voice_services_once()
            self._wake_loop()

        except Exception as exc:
            self.last_error = str(exc)
            self._ready = False
            self._ready_event.clear()
            self._log("error", f"Falha no sistema de voz: {exc}")
            self._state("ERRO", str(exc))

    def _load_audio_dependencies(self):
        try:
            import sounddevice as sd
            import numpy as np
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as exc:
            raise VoiceEngineError(
                "Dependências de voz não instaladas. "
                "Execute INSTALAR_VOZ.bat."
            ) from exc

        self._sd = sd
        self._np = np

        try:
            import webrtcvad
            self._webrtcvad = webrtcvad.Vad(3)
        except Exception:
            self._webrtcvad = None

        # V7: Silero e um voto opcional de maior qualidade. Se o pacote/modelo
        # nao estiver disponivel, o caminho WebRTC atual continua intacto.
        if HybridVAD is not None:
            try:
                self._hybrid_vad = HybridVAD(
                    sample_rate=self.SAMPLE_RATE,
                    logger=self.logger,
                    fallback=self._webrtcvad,
                )
            except Exception as exc:
                self._hybrid_vad = None
                self._log("warning", f"HybridVAD indisponivel: {exc}")

        class _VoskNamespace:
            pass

        self._vosk = _VoskNamespace()
        self._vosk.KaldiRecognizer = KaldiRecognizer
        self._vosk.Model = Model
        self._vosk.SetLogLevel = SetLogLevel

        try:
            SetLogLevel(-1)
        except Exception:
            pass

    def _detect_microphone(self):
        """Seleciona uma entrada que consiga abrir o stream usado de verdade.

        ``check_input_settings`` sozinho não garante que o backend aceite a API
        bloqueante usada pelo JARVIS. Em especial, WDM-KS pode anunciar o
        formato e depois falhar com ``Blocking API not supported yet``. Por isso
        cada candidato recebe um score de dispositivo/host API e é sondado com
        um ``RawInputStream`` real antes de ser declarado disponível.
        """
        self._mic_available = False
        self._input_device_index = None
        self._capture_sample_rate = self.SAMPLE_RATE
        self._input_hostapi = ""
        self._input_candidate_count = 0
        self._input_candidate_pos = 0
        self.input_device_name = ""
        self._capture_mode = "no-usable-input"

        try:
            devices = list(self._sd.query_devices())
        except Exception as exc:
            self.last_error = f"PortAudio não conseguiu listar entradas: {exc}"
            self._log("warning", self.last_error)
            return
        try:
            hostapis = list(self._sd.query_hostapis())
        except Exception:
            hostapis = []

        try:
            default_input = int(self._sd.default.device[0])
        except Exception:
            default_input = -1

        def host_name(device):
            try:
                idx = int(device.get("hostapi", -1))
                if 0 <= idx < len(hostapis):
                    return str(hostapis[idx].get("name") or "")
            except Exception:
                pass
            return ""

        candidates = []
        good_words = ("microphone", "microfone", "mic ", "headset", "headphone", "usb", "webcam")
        poor_words = (
            "audio cd", "áudio cd", "cd input", "entrada de cd",
            "stereo mix", "mixagem estereo", "mixagem estéreo",
            "what u hear", "loopback", "wave out",
        )
        for index, device in enumerate(devices):
            try:
                channels = int(device.get("max_input_channels", 0))
            except Exception:
                channels = 0
            if channels < 1:
                continue
            name = str(device.get("name", "") or "")
            name_key = self._normalize(name)
            host = host_name(device)
            host_key = self._normalize(host)
            score = 0
            if index == default_input:
                score += 24
            if any(self._normalize(word) in name_key for word in good_words):
                score += 70
            if any(self._normalize(word) in name_key for word in poor_words):
                score -= 110
            if "wasapi" in host_key:
                score += 45
            elif "mme" in host_key:
                score += 32
            elif "directsound" in host_key or "direct sound" in host_key:
                score += 28
            elif "wdm-ks" in host_key or "wdm ks" in host_key:
                score -= 75
            candidates.append((score, index, device, host))

        candidates.sort(key=lambda row: (-row[0], row[1]))
        self._input_candidate_count = len(candidates)
        if not candidates:
            self.last_error = "Nenhum dispositivo de entrada de áudio foi encontrado."
            self._log("warning", self.last_error)
            return

        errors = []
        for position, (_, index, device, host) in enumerate(candidates):
            rates = [self.SAMPLE_RATE]
            try:
                native = int(round(float(device.get("default_samplerate") or 0)))
            except Exception:
                native = 0
            for rate in (native, 48000, 44100):
                if rate > 0 and rate not in rates:
                    rates.append(rate)

            for rate in rates:
                try:
                    self._sd.check_input_settings(
                        device=index, channels=self.CHANNELS, dtype="int16", samplerate=rate,
                    )
                    source_frames = max(1, int(round(320 * rate / self.SAMPLE_RATE)))
                    # Abertura real no mesmo modo usado pelo wake word.
                    with self._sd.RawInputStream(
                        samplerate=rate, blocksize=source_frames, dtype="int16",
                        channels=self.CHANNELS, device=index,
                    ):
                        pass
                except Exception as exc:
                    errors.append(f"#{index}@{rate}/{host or '?'}: {exc}")
                    continue

                self._input_device_index = int(index)
                self._capture_sample_rate = int(rate)
                self._input_hostapi = str(host or "desconhecido")
                self._input_candidate_pos = int(position)
                self.input_device_name = str(device.get("name", "") or f"Entrada {index}")
                self._load_mic_profile()
                self._mic_available = True
                self._auto_recovery_suspended = False
                self.last_error = ""
                self._capture_mode = (
                    "stable-direct-16k" if rate == self.SAMPLE_RATE
                    else f"stable-direct-{rate}-to-{self.SAMPLE_RATE}"
                )
                if rate != self.SAMPLE_RATE:
                    self._log(
                        "warning",
                        f"Microfone '{self.input_device_name}' usando {rate} Hz com reamostragem interna "
                        f"(host {self._input_hostapi}).",
                    )
                else:
                    self._log(
                        "info",
                        f"Microfone selecionado: {self.input_device_name} "
                        f"(#{index}, {rate} Hz, {self._input_hostapi}).",
                    )
                return

        tail = errors[0] if errors else "nenhum stream bloqueante pôde ser aberto"
        self._auto_recovery_suspended = True
        self.last_error = (
            "Nenhuma entrada de microfone utilizável pôde ser aberta. "
            "Conecte/ative um microfone ou headset; o JARVIS verificará novamente. "
            f"Detalhe: {tail}"
        )
        self._log("warning", self.last_error)

    def _mic_profile_file(self) -> Path:
        return self.data_dir / "mic_profiles.json"

    def _mic_profile_key(self) -> str:
        return self._normalize(self.input_device_name or "microfone padrao") or "microfone_padrao"

    def _load_mic_profile(self):
        """Restaura calibracao somente se o gate adaptativo foi reativado."""
        if not self.MIC_NOISE_GATE:
            self._mic_calibrated = False
            self._adaptive_gate_raw = 55.0
            return False
        try:
            path = self._mic_profile_file()
            if not path.exists():
                return False
            payload = json.loads(path.read_text(encoding="utf-8"))
            profile = (payload or {}).get(self._mic_profile_key()) or {}
            baseline = float(profile.get("noise_floor") or 0.0)
            gate = float(profile.get("gate") or 0.0)
            if baseline >= 20.0 and gate >= baseline:
                self._visual_noise_floor = baseline
                self._adaptive_gate_raw = gate
                self._mic_calibrated = True
                self._log("info", f"Perfil de microfone restaurado: piso={baseline:.0f} gate={gate:.0f}")
                return True
        except Exception:
            pass
        return False

    def _save_mic_profile(self):
        if not self.MIC_NOISE_GATE:
            return
        try:
            path = self._mic_profile_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {}
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    payload = {}
            payload[self._mic_profile_key()] = {
                "device": self.input_device_name,
                "noise_floor": round(float(self._visual_noise_floor), 2),
                "gate": round(float(self._adaptive_gate_raw), 2),
                "updated_at": time.time(),
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _auto_calibrate_microphone(self, duration: float = 1.25):
        """Calibra apenas no modo legado opt-in.

        13.12.2 volta ao comportamento permissivo por padrao: nenhuma medicao
        de ruido ambiente pode elevar um gate persistente e impedir a frase
        dita logo depois de "Jarvis". O VAD continua ativo.
        """
        if not self.MIC_NOISE_GATE:
            self._visual_noise_floor = 100.0
            self._adaptive_gate_raw = 55.0
            self._mic_calibrated = False
            self._mic_quality = "MIC PRONTO"
            self._log("info", "Gate/calibracao adaptativa de ruido desativados (13.12.2); VAD permissivo ativo.")
            return True
        if self._sd is None or self._np is None or not self._mic_available:
            return False
        self._state("CALIBRANDO", "Medindo ruido ambiente")
        values = []
        frames = 320
        deadline = time.monotonic() + max(0.65, float(duration))
        try:
            capture_rate = int(getattr(self, "_capture_sample_rate", self.SAMPLE_RATE) or self.SAMPLE_RATE)
            source_frames = max(1, int(round(frames * capture_rate / self.SAMPLE_RATE)))
            with self._sd.RawInputStream(
                samplerate=capture_rate,
                blocksize=source_frames,
                dtype="int16",
                channels=self.CHANNELS,
                device=self._input_device_index,
            ) as raw_stream:
                stream = _StableDirectStream(raw_stream, self, input_rate=capture_rate)
                while time.monotonic() < deadline and not self._stop_event.is_set():
                    data, overflowed = stream.read(frames)
                    raw = bytes(data)
                    level = self._rms(raw)
                    if level >= 0:
                        values.append(level)
                    self._publish_level(raw)
        except Exception as exc:
            self._log("warning", f"Calibracao automatica do microfone ignorada: {exc}")
            return False

        if len(values) < 12:
            return False
        try:
            arr = self._np.asarray(values, dtype=self._np.float32)
            p20 = float(self._np.percentile(arr, 20))
            p35 = float(self._np.percentile(arr, 35))
            p80 = float(self._np.percentile(arr, 80))
            baseline = max(24.0, min(1800.0, p20 * 0.72 + p35 * 0.28))
            # Gate mais baixo que V6.2: o Logitech do teste tinha piso ~729 e
            # a voz mal ultrapassava o gate 1048.
            gate = max(55.0, min(2200.0, baseline * 1.20 + 18.0))
            self._visual_noise_floor = baseline
            self._adaptive_gate_raw = gate
            self._visual_peak = max(self._visual_peak, baseline * 1.8, baseline + 260.0)
            self._mic_calibrated = True
            contaminated = p80 > max(p20 * 2.4, p20 + 650.0)
            self._log(
                "info",
                f"Microfone calibrado V6.3: piso={baseline:.0f} gate={gate:.0f} faixa={p20:.0f}-{p80:.0f} contaminada={int(contaminated)}",
            )
            self._save_mic_profile()
            return True
        except Exception:
            return False

    def _ensure_vosk_model(self):
        """Garante o modelo Vosk com download único, verificação e troca atômica.

        Evita o arquivo global ``.download`` que podia desaparecer durante uma
        recuperação concorrente e não considera uma pasta parcial como modelo
        válido.
        """
        import shutil

        target = self._wake_model_path
        required = ("final.mdl", "Gr.fst", "HCLr.fst", "phones.txt", "mfcc.conf")

        def model_ready(path):
            try:
                return path.is_dir() and all((path / name).is_file() for name in required)
            except Exception:
                return False

        if model_ready(target):
            return

        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._state("PREPARANDO", "Preparando modelo leve de wake word")

        unique = (
            f"{self.VOSK_MODEL_NAME}.{os.getpid()}."
            f"{threading.get_ident()}.{int(time.time() * 1000)}"
        )
        temp_path = self.models_dir / f"{unique}.download"
        zip_path = self.models_dir / f"{unique}.zip"
        extract_dir = None

        try:
            request = urllib.request.Request(
                self.VOSK_MODEL_URL,
                headers={"User-Agent": "JARVIS-Desktop/1.1.3"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                with temp_path.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)

            if not temp_path.is_file() or temp_path.stat().st_size < 1024:
                raise VoiceEngineError("O download do modelo Vosk veio vazio/incompleto.")

            digest = hashlib.md5()
            with temp_path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)

            if digest.hexdigest().lower() != self.VOSK_MODEL_MD5.lower():
                raise VoiceEngineError("O modelo de wake word falhou na verificação MD5.")

            temp_path.replace(zip_path)
            extract_dir = Path(
                tempfile.mkdtemp(
                    prefix=f".{self.VOSK_MODEL_NAME}-",
                    dir=str(self.models_dir),
                )
            )

            with zipfile.ZipFile(zip_path, "r") as archive:
                bad_member = archive.testzip()
                if bad_member:
                    raise VoiceEngineError(
                        f"O ZIP do modelo Vosk está corrompido: {bad_member}"
                    )
                archive.extractall(extract_dir)

            extracted = extract_dir / self.VOSK_MODEL_NAME
            if not model_ready(extracted):
                matches = [
                    path for path in extract_dir.rglob(self.VOSK_MODEL_NAME)
                    if model_ready(path)
                ]
                if matches:
                    extracted = matches[0]

            if not model_ready(extracted):
                raise VoiceEngineError(
                    "O modelo Vosk foi extraído, mas os arquivos obrigatórios não apareceram."
                )

            # Outra thread/processo pode ter terminado primeiro. Se o destino já
            # está íntegro, basta usar o que venceu a corrida.
            if model_ready(target):
                return

            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink()

            shutil.move(str(extracted), str(target))

            if not model_ready(target):
                raise VoiceEngineError(
                    "O modelo Vosk não ficou íntegro após a instalação."
                )

            self._log("info", f"Modelo Vosk pronto em: {target}")

        except Exception as exc:
            if model_ready(target):
                return
            raise VoiceEngineError(
                f"Não consegui preparar o modelo Vosk com segurança: {exc}"
            ) from exc
        finally:
            for path in (temp_path, zip_path):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
            try:
                if extract_dir and extract_dir.exists():
                    shutil.rmtree(extract_dir, ignore_errors=True)
            except Exception:
                pass
    def _load_vosk_model(self):
        self._vosk_model = self._vosk.Model(
            str(self._wake_model_path)
        )

    @staticmethod
    def _normalize(text: str) -> str:
        value = unicodedata.normalize("NFKD", str(text or ""))
        value = "".join(
            ch for ch in value
            if not unicodedata.combining(ch)
        )
        value = value.lower().replace("0", "zero")
        value = re.sub(r"[^a-z0-9 ]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip()

        replacements = {
            "zeiro": "zero",
            "ziro": "zero",
            "cero": "zero",
            "sero": "zero",
            "jarbas": "jarvis",
            "jarves": "jarvis",
            "jervis": "jarvis",
            "jarvi": "jarvis",
            "jarvisse": "jarvis",
            "ja vis": "jarvis",
            "eae": "e ai",
        }

        for source, target in replacements.items():
            value = value.replace(source, target)

        return re.sub(r"\s+", " ", value).strip()

    def _is_wake_phrase(self, text: str) -> bool:
        """Wake sem fuzzy matching: evita "e zero" virar "ei zero" em calls."""
        candidate = self._normalize(text)
        if not candidate:
            return False
        tokens = candidate.split()
        if len(tokens) < 1 or len(tokens) > 5:
            return False
        for phrase in self.WAKE_PHRASES:
            target = self._normalize(phrase)
            if candidate == target or candidate.startswith(target + " "):
                return True
        return False

    @staticmethod
    def _vosk_result_confidence(payload: dict) -> float:
        try:
            words = payload.get("result") or []
            values = [
                float(item.get("conf"))
                for item in words
                if item.get("conf") is not None
            ]
            if values:
                return sum(values) / len(values)
        except Exception:
            pass
        return 0.0

    def _wake_text_from_payload(self, payload: dict) -> str:
        return str(
            payload.get("text")
            or payload.get("partial")
            or ""
        ).strip()

    def _new_wake_recognizer(self):
        grammar = json.dumps(
            [*self.WAKE_PHRASES, "[unk]"],
            ensure_ascii=False,
        )

        recognizer = self._vosk.KaldiRecognizer(
            self._vosk_model,
            self.SAMPLE_RATE,
            grammar,
        )
        try:
            recognizer.SetWords(True)
        except Exception:
            pass
        return recognizer

    def _new_loose_wake_recognizer(self):
        """Segundo reconhecedor livre; serve como confirmação independente."""
        recognizer = self._vosk.KaldiRecognizer(
            self._vosk_model,
            self.SAMPLE_RATE,
        )
        try:
            recognizer.SetWords(True)
        except Exception:
            pass
        return recognizer

    @staticmethod
    def _dbfs_percent(raw_level: float) -> int:
        try:
            dbfs = 20.0 * math.log10(max(float(raw_level), 1.0) / 32768.0)
            # -60 dBFS = 0%; -18 dBFS = 100%.
            return int(max(0, min(100, round((dbfs + 60.0) / 42.0 * 100.0))))
        except Exception:
            return 0

    def _queue_telemetry(self, level_norm: float, metrics: dict):
        item = (float(level_norm), dict(metrics))
        try:
            self._telemetry_queue.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            self._telemetry_queue.get_nowait()
        except Exception:
            pass
        try:
            self._telemetry_queue.put_nowait(item)
        except Exception:
            pass

    def _telemetry_worker(self):
        """Callbacks de UI/IPC fora da thread de captura para impedir overflow."""
        while not self._stop_event.is_set():
            try:
                item = self._telemetry_queue.get(timeout=0.20)
            except queue.Empty:
                continue
            if item is None:
                return
            level_norm, metrics = item
            try:
                if self.on_level:
                    self.on_level(level_norm)
            except Exception:
                pass
            try:
                if self.on_audio_metrics:
                    self.on_audio_metrics(metrics)
            except Exception:
                pass

    def _note_audio_overflow(self, context: str = "mic"):
        """Agrega overflows para nao transformar um problema de audio em log storm."""
        self._audio_overflow_total = int(getattr(self, "_audio_overflow_total", 0)) + 1
        self._audio_overflow_since_log = int(getattr(self, "_audio_overflow_since_log", 0)) + 1
        now = time.monotonic()
        last = float(getattr(self, "_last_overflow_log_at", 0.0) or 0.0)
        if last and now - last < 5.0:
            return
        self._last_overflow_log_at = now
        count = int(getattr(self, "_audio_overflow_since_log", 0))
        self._audio_overflow_since_log = 0
        dropped = int(getattr(self._audio_ring, "dropped", 0) if self._audio_ring else 0)
        previous_dropped = int(getattr(self, "_last_ring_drop_reported", 0) or 0)
        dropped_delta = max(0, dropped - previous_dropped)
        self._last_ring_drop_reported = dropped
        depth = int(getattr(self._audio_ring, "depth", 0) if self._audio_ring else 0)
        self._log(
            "warning",
            f"Audio input instavel ({context}): {count} overflow(s) agregados; "
            f"ring_depth={depth} descartados={dropped_delta}. Captura continua.",
        )

    def _publish_level(self, raw: bytes):
        """Atualiza telemetria sem bloquear a leitura do sounddevice."""
        now = time.monotonic()
        try:
            level = self._rms(raw)
            self._current_rms = float(level)

            if self.MIC_NOISE_GATE:
                learning = 0.012 if not self._mic_capture_active.is_set() else 0.0015
                # Modo opt-in legado: aprende o piso apenas quando solicitado.
                learn_ceiling = max(self._visual_noise_floor * 1.38, self._visual_noise_floor + 160.0)
                if level <= learn_ceiling:
                    self._visual_noise_floor = (
                        self._visual_noise_floor * (1.0 - learning) + level * learning
                    )
                self._adaptive_gate_raw = max(
                    55.0,
                    min(2200.0, self._visual_noise_floor * 1.20 + 18.0),
                )
            else:
                # Telemetria continua funcionando, mas o nivel ambiente nao
                # cria um gate que possa bloquear a fala.
                self._adaptive_gate_raw = 55.0
            self._visual_peak = max(
                level,
                self._visual_peak * 0.982,
                self._adaptive_gate_raw * 1.55,
            )

            snr_db = 20.0 * math.log10(max(level, 1.0) / max(self._visual_noise_floor, 1.0))
            # VOZ e uma medida ACIMA do ruido, nao uma porcentagem do pico historico.
            voice_percent = int(max(0, min(100, round((snr_db - 1.0) / 14.0 * 100.0))))
            if level < self._adaptive_gate_raw * 0.92:
                voice_percent = 0
            normalized = voice_percent / 100.0

            noise_percent = self._dbfs_percent(self._visual_noise_floor)
            gate_percent = self._dbfs_percent(self._adaptive_gate_raw)
            if snr_db >= 12.0:
                quality = "MIC OK"
            elif snr_db >= 6.0:
                quality = "MIC MEDIO"
            else:
                quality = "SINAL BAIXO" if self._mic_capture_active.is_set() else "MIC PRONTO"

            self._last_noise_percent = noise_percent
            self._last_gate_percent = gate_percent
            self._last_snr_db = max(0.0, snr_db)
            self._mic_quality = quality

            if now - self._last_metrics_emit >= 0.055:
                self._last_metrics_emit = now
                self._queue_telemetry(normalized, {
                    "voice": voice_percent,
                    "noise": noise_percent,
                    "gate": gate_percent,
                    "snr_db": round(max(0.0, snr_db), 1),
                    "quality": quality,
                    "calibrated": bool(self._mic_calibrated),
                    "capturing": bool(self._mic_capture_active.is_set()),
                    "raw_rms": int(level),
                    "noise_floor_raw": int(self._visual_noise_floor),
                    "gate_raw": int(self._adaptive_gate_raw),
                })
        except Exception:
            pass

    def _emit_live_transcript(self, text: str, *, force: bool = False):
        """Expose stable user dictation without blocking the audio thread."""
        if not self.on_live_transcript:
            return
        clean = sanitize_text(text, limit=220)
        now = time.monotonic()
        if not force:
            if not clean or clean == self._last_live_emit_text:
                return
            if now - self._last_live_emit_at < 0.085:
                return
        self._last_live_emit_at = now
        self._last_live_emit_text = clean
        try:
            self.on_live_transcript(clean)
        except Exception:
            pass

    def _conversation_openmic_active(self) -> bool:
        """True quando o Modo Conversa está em escuta contínua explícita."""
        return bool(
            getattr(self, "_conversation_mode", None)
            and self._conversation_mode.is_set()
            and bool(getattr(self, "CONVERSATION_ALWAYS_LISTEN", False))
        )

    def _conversation_tts_interrupt_allowed(self, text: str) -> bool:
        """Protege respostas longas do eco no Modo Conversa.

        Em open-mic o próprio TTS inevitavelmente volta ao microfone. Palavras
        curtas como ``para``/``pare`` são especialmente fáceis de surgir como
        falso positivo. Por isso, durante a fala do JARVIS, o modo contínuo só
        aceita interrupção explícita pelo nome (``Jarvis``) ou nome + comando
        de parada. Fora do Modo Conversa o comportamento clássico é preservado.
        """
        if not self._conversation_openmic_active():
            return True

        key = self._normalize(text)
        if not key:
            return False

        if self._is_barge_in_wake_phrase(key):
            return True

        explicit = {
            "jarvis para", "para jarvis", "jarvis pare", "pare jarvis",
            "jarvis cancela", "cancela jarvis",
            "jarbas para", "para jarbas", "jarves para", "para jarves",
            "jervis para", "para jervis",
        }
        if self.LEGACY_ZERO_WAKE:
            explicit.update({
                "zero para", "para zero", "zero pare", "pare zero",
                "zero cancela", "cancela zero",
            })
        return key in explicit

    def _new_interrupt_recognizer(self):
        phrases = [
            "jarvis para", "para jarvis", "jarvis pare", "pare jarvis",
            "jarvis cancela", "cancela jarvis",
            "jarbas para", "para jarbas", "jarves para", "para jarves",
            "jervis para", "para jervis",
            # Barge-in natural: dizer apenas o nome durante a fala do JARVIS
            # interrompe o TTS e abre uma nova captura.
            "jarvis", "jarbas", "jarves", "jervis", "oi jarvis", "ei jarvis",
        ]
        # No open-mic, "para"/"pare" sozinhos são removidos da gramática de
        # interrupção. O eco do próprio TTS e ruído ambiente geravam falsos
        # cancelamentos no meio de respostas longas.
        if not self._conversation_openmic_active():
            phrases.extend(["para", "pare"])
        if self.LEGACY_ZERO_WAKE:
            phrases.extend(["zero para", "para zero", "zero pare", "pare zero", "zero cancela", "cancela zero"])
        grammar = json.dumps([*phrases, "[unk]"], ensure_ascii=False)

        return self._vosk.KaldiRecognizer(
            self._vosk_model,
            self.SAMPLE_RATE,
            grammar,
        )

    def _is_interrupt_phrase(self, text: str) -> bool:
        candidate = self._normalize(
            text
        )

        if not candidate:
            return False

        targets = [
            "jarvis para", "para jarvis", "jarvis pare", "pare jarvis",
            "jarvis cancela", "cancela jarvis",
            "jarbas para", "para jarbas", "jarves para", "para jarves",
            "jervis para", "para jervis",
            "para", "pare",
        ]
        if self.LEGACY_ZERO_WAKE:
            targets.extend(("zero para", "para zero", "zero pare", "pare zero", "zero cancela", "cancela zero"))

        for target in targets:
            if candidate == target:
                return True

            ratio = SequenceMatcher(
                None,
                candidate,
                target
            ).ratio()

            if ratio >= 0.90:
                return True

        return False


    def _is_barge_in_wake_phrase(self, text: str) -> bool:
        if not self.BARGE_IN_WAKE:
            return False
        key = self._normalize(text)
        if not key:
            return False
        targets = {
            "jarvis", "jarbas", "jarves", "jervis", "jarvi",
            "oi jarvis", "ei jarvis", "ola jarvis", "e ai jarvis",
            "oi jarbas", "ei jarbas", "oi jarves", "ei jarves",
        }
        if key in targets:
            return True
        # Só fuzzy em uma palavra curta; frases longas nunca viram barge-in
        # por semelhança para evitar TV/jogo interrompendo o assistente.
        if len(key.split()) == 1:
            return max(SequenceMatcher(None, key, t).ratio() for t in ("jarvis", "jarbas", "jarves", "jervis")) >= 0.88
        return False

    def _process_interrupt_audio(self, raw: bytes):
        """Priority Interrupt V8: final ou parcial estável + anti-eco.

        Durante TTS contínuo o Vosk pode não produzir FINAL; uma parcial exata
        repetida é aceita com evidência acústica externa. Se houver perfil de
        voz cadastrado, a amostra também precisa pertencer ao usuário.
        """
        if not self._speaking.is_set():
            self._interrupt_recognizer = None
            self._interrupt_voice_votes.clear()
            self._interrupt_audio_window.clear()
            self._interrupt_peak_ratio = 0.0
            return

        if not self._vosk_model:
            return

        now = time.monotonic()
        # Os primeiros ms de playback têm transientes fortes de caixa/driver.
        if now - float(self._tts_started_at or 0.0) < 0.18:
            return

        level = self._rms(raw)
        noise = max(24.0, float(self._visual_noise_floor or 90.0))
        ratio = level / max(noise, 1.0)
        try:
            vad = bool(self._vad_is_speech(raw))
        except Exception:
            vad = False
        strong_voice = bool(
            vad
            and level >= max(85.0, noise * 1.15 + 18.0, float(self._adaptive_gate_raw or 0.0) * 0.72)
        )
        self._interrupt_voice_votes.append(1 if strong_voice else 0)
        self._interrupt_audio_window.append(bytes(raw))
        if strong_voice:
            self._interrupt_peak_ratio = max(self._interrupt_peak_ratio, ratio)

        if self._interrupt_recognizer is None:
            self._interrupt_recognizer = self._new_interrupt_recognizer()

        recognizer = self._interrupt_recognizer
        detected = ""
        partial = ""
        try:
            if recognizer.AcceptWaveform(raw):
                payload = json.loads(recognizer.Result())
                detected = str(payload.get("text") or "").strip()
                self._interrupt_recognizer = self._new_interrupt_recognizer()
                self._interrupt_partial_hits = 0
                self._interrupt_last_partial = ""
            else:
                payload = json.loads(recognizer.PartialResult())
                partial = str(payload.get("partial") or "").strip()
        except Exception:
            detected = ""
            partial = ""

        # Durante playback contínuo o Vosk às vezes nunca fecha um FINAL porque
        # o próprio TTS mantém energia acústica. Uma parcial EXATA repetida é
        # aceita só com evidência de voz externa e nunca se a frase estiver no TTS.
        partial_is_stop = bool(partial and self._is_interrupt_phrase(partial))
        partial_is_wake = bool(partial and self._is_barge_in_wake_phrase(partial))
        if not detected and partial and (partial_is_stop or partial_is_wake):
            pkey = self._normalize(partial)
            if pkey == self._interrupt_last_partial and now - self._interrupt_last_partial_at <= 0.45:
                self._interrupt_partial_hits += 1
            else:
                self._interrupt_partial_hits = 1
                self._interrupt_last_partial = pkey
            self._interrupt_last_partial_at = now
            acoustic_votes = sum(self._interrupt_voice_votes)
            # Dizer apenas "Jarvis" durante o TTS exige evidência um pouco mais
            # forte que "Jarvis, para", reduzindo falsos cortes por TV/jogo.
            required_ratio = 1.45 if partial_is_wake and not partial_is_stop else 1.35
            if self._interrupt_partial_hits >= 2 and (acoustic_votes >= 2 or self._interrupt_peak_ratio >= required_ratio):
                detected = partial

        if not detected:
            return
        detected_is_stop = self._is_interrupt_phrase(detected)
        detected_is_wake = self._is_barge_in_wake_phrase(detected)
        if not (detected_is_stop or detected_is_wake):
            # Hipotese final alheia ao comando de interrupcao: a evidencia
            # acustica pertence a outra fala e nao pode contaminar a proxima.
            self._interrupt_voice_votes.clear()
            self._interrupt_audio_window.clear()
            self._interrupt_peak_ratio = 0.0
            return

        # Hotfix 13.11.3: no Modo Conversa open-mic, uma palavra curta
        # reconhecida como "para"/"pare" não pode derrubar uma resposta longa.
        # O microfone está aberto enquanto o próprio TTS toca e pode escutar eco.
        # Interrupção continua disponível por "Jarvis" ou "Jarvis, para".
        if not self._conversation_tts_interrupt_allowed(detected):
            self._log(
                "warning",
                f"Priority Interrupt ignorado no Modo Conversa (anti-eco): {detected}",
            )
            self._interrupt_recognizer = self._new_interrupt_recognizer()
            self._interrupt_voice_votes.clear()
            self._interrupt_audio_window.clear()
            self._interrupt_peak_ratio = 0.0
            self._interrupt_partial_hits = 0
            self._interrupt_last_partial = ""
            return

        # Proteção direta contra o próprio TTS dizendo a frase de interrupção.
        tts_key = self._normalize(self._current_tts_text)
        detected_key = self._normalize(detected)
        if detected_key and detected_key in tts_key:
            self._log("warning", "Priority Interrupt rejeitado: frase estava no próprio TTS.")
            return

        acoustic_votes = sum(self._interrupt_voice_votes)
        partial_confirmed = self._interrupt_partial_hits >= 2
        if detected_is_wake and not detected_is_stop:
            acoustic_ok = bool(
                (acoustic_votes >= 2 and self._interrupt_peak_ratio >= 1.20)
                or self._interrupt_peak_ratio >= 1.55
                or (partial_confirmed and acoustic_votes >= 2 and self._interrupt_peak_ratio >= 1.38)
            )
        else:
            acoustic_ok = bool(
                (acoustic_votes >= 2 and self._interrupt_peak_ratio >= 1.10)
                or self._interrupt_peak_ratio >= 1.42
                or (partial_confirmed and (acoustic_votes >= 1 or self._interrupt_peak_ratio >= 1.35))
            )
        if not acoustic_ok:
            self._log(
                "warning",
                f"Priority Interrupt rejeitado por evidência acústica fraca: votes={acoustic_votes} ratio={self._interrupt_peak_ratio:.2f}",
            )
            return

        # Se o usuário cadastrou a voz, usa isso como barreira anti-eco adicional.
        if self.speaker_guard and self.speaker_guard.enrolled:
            try:
                sample = b"".join(self._interrupt_audio_window)
                speaker_ok, speaker_score = self.speaker_guard.verify(sample)
                if not speaker_ok:
                    self._log("warning", f"Priority Interrupt rejeitado pelo SpeakerGuard: {speaker_score:.3f}")
                    return
            except Exception as exc:
                self._log("warning", f"Priority Interrupt sem confirmação de voz: {exc}")
                return

        if now - self._last_interrupt_at < 1.8:
            return

        self._last_interrupt_at = now
        barge_in = bool(detected_is_wake and not detected_is_stop)
        self._log("info", f"{'Barge-in' if barge_in else 'Interrupção de voz'} confirmado: {detected}")
        # Preserva até ~1,1 s de áudio que levou ao wake para não comer o começo
        # de "Jarvis, abre..." quando o usuário fala por cima do TTS.
        if barge_in:
            try:
                sample = b"".join(self._interrupt_audio_window)
                max_bytes = int(self.SAMPLE_RATE * 2 * 1.10)
                self._pending_wake_preroll = sample[-max_bytes:] if sample else b""
            except Exception:
                self._pending_wake_preroll = b""
        self._interrupt_voice_votes.clear()
        self._interrupt_audio_window.clear()
        self._interrupt_peak_ratio = 0.0
        self._interrupt_partial_hits = 0
        self._interrupt_last_partial = ""
        self.stop_speaking(clear_queue=True)
        self._assistant_busy.clear()
        self._state("OUVINDO" if barge_in else "AGUARDANDO", "Barge-in: pode falar" if barge_in else "Fala interrompida")

        if self.on_interrupt:
            try:
                self.on_interrupt()
            except Exception:
                pass
        if barge_in:
            self._conversation_passive = False
            self._manual_trigger.set()

    def _call_guard_active(self) -> bool:
        """Call Guard leve: só reforça se uma janela de call estiver realmente ativa."""
        if not self.CALL_GUARD or os.name != "nt":
            return False
        now = time.monotonic()
        cached = getattr(self, "_call_guard_cached", None)
        if cached and now - cached[0] < 1.5:
            return bool(cached[1])
        active = False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = self._normalize(buf.value)
                    active = any(k in title for k in self.CALL_WINDOW_KEYWORDS)
        except Exception:
            active = False
        self._call_guard_cached = (now, active)
        return active

    def _wake_loop(self):
        """Wake clássico por leitura direta de 20 ms.

        Não usa callback, fila nem watchdog de callback. O mesmo ``read()``
        usado pela calibracao e usado durante toda a escuta. Apenas erros reais
        levantados pelo PortAudio provocam uma reabertura; depois de 3 falhas
        consecutivas a thread para com erro claro, em vez de alternar
        OUVINDO/RECONECTANDO infinitamente.
        """
        block_frames = 320

        while not self._stop_event.is_set():
            self._stream_restart_event.clear()
            recognizer = self._new_wake_recognizer()
            got_frame = False

            try:
                capture_rate = int(getattr(self, "_capture_sample_rate", self.SAMPLE_RATE) or self.SAMPLE_RATE)
                source_block_frames = max(1, int(round(block_frames * capture_rate / self.SAMPLE_RATE)))
                with self._sd.RawInputStream(
                    samplerate=capture_rate,
                    blocksize=source_block_frames,
                    dtype="int16",
                    channels=self.CHANNELS,
                    device=self._input_device_index,
                ) as raw_stream:
                    stream = _StableDirectStream(raw_stream, self, input_rate=capture_rate)
                    self._audio_ring = stream
                    self._capture_mode = (
                        "stable-direct-16k"
                        if capture_rate == self.SAMPLE_RATE
                        else f"stable-direct-{capture_rate}-to-{self.SAMPLE_RATE}"
                    )
                    self.last_error = ""
                    self._state("AGUARDANDO", f"Diga '{PUBLIC_NAME.title()}'")
                    # O primeiro read acontece dentro de _listen_on_stream e,
                    # quando chega, zera _direct_open_failures no adaptador.
                    before = self._direct_frames_read
                    self._listen_on_stream(stream, recognizer, block_frames)
                    got_frame = self._direct_frames_read > before
                self._audio_ring = None

                if got_frame:
                    self._direct_open_failures = 0

                # A recalibracao manual e processada dentro de _listen_on_stream.
                # Nao abra um segundo RawInputStream aqui: em alguns drivers do
                # Windows isso gerava reconexao, atraso e disputa pelo headset.

            except Exception as exc:
                self._audio_ring = None
                if self._stop_event.is_set():
                    return
                self._direct_open_failures += 1
                self.last_error = str(exc)
                self._log("warning", f"Falha real de leitura do microfone: {exc}")
                if self._direct_open_failures >= 3:
                    self._ready = False
                    self._ready_event.clear()
                    self._mic_available = False
                    self._auto_recovery_suspended = True
                    self._state("ERRO", "Microfone parou de entregar áudio")
                    self._log(
                        "error",
                        "Entrada de áudio interrompida após 3 falhas reais; "
                        "o supervisor tentará reabrir automaticamente.",
                    )
                    return
                # Sem estado RECONECTANDO: uma falha real recebe no máximo duas
                # reaberturas discretas e nunca cria loop visual infinito.
                self._state("AGUARDANDO", "Reabrindo entrada de áudio")
                time.sleep(0.35)

    def _discard_stream_backlog(self, stream) -> int:
        """Descarta áudio velho acumulado enquanto STT/ações estavam ocupados."""
        try:
            removed = int(stream.discard()) if hasattr(stream, "discard") else 0
            if removed:
                self._log("info", f"Ring buffer: descartados {removed} quadros antigos após interação.")
            return removed
        except Exception:
            return 0

    def _inline_calibration_tick(self, raw: bytes) -> bool:
        """Consome amostras do stream corrente para recalibrar sem reinicia-lo.

        Retorna True quando uma calibracao pendente foi concluida neste frame.
        O modo padrao continua permissivo (MIC_NOISE_GATE=0); nesse caso a
        solicitacao apenas normaliza os limites visuais e termina imediatamente.
        """
        if not self._calibration_requested.is_set():
            return False

        now = time.monotonic()
        if now < float(self._calibration_due_at or 0.0):
            return False

        if not self.MIC_NOISE_GATE:
            self._visual_noise_floor = 100.0
            self._adaptive_gate_raw = 55.0
            self._mic_calibrated = False
            self._mic_quality = "MIC PRONTO"
            self._calibration_samples.clear()
            self._calibration_started_at = 0.0
            self._calibration_requested.clear()
            self._state("AGUARDANDO", "Microfone pronto")
            return True

        if self._calibration_started_at <= 0.0:
            self._calibration_started_at = now
            self._calibration_samples.clear()
            self._mic_quality = "CALIBRANDO"
            self._state("CALIBRANDO", "Medindo ruido ambiente")

        try:
            level = float(self._rms(raw))
            if level >= 0.0:
                self._calibration_samples.append(level)
        except Exception:
            pass

        # ~0,9 s e suficiente para um piso de ruido estavel sem segurar o boot.
        if (now - self._calibration_started_at) < 0.90 or len(self._calibration_samples) < 12:
            return False

        values = list(self._calibration_samples)
        try:
            arr = self._np.asarray(values, dtype=self._np.float32)
            p20 = float(self._np.percentile(arr, 20))
            p35 = float(self._np.percentile(arr, 35))
            p80 = float(self._np.percentile(arr, 80))
            baseline = max(24.0, min(1800.0, p20 * 0.72 + p35 * 0.28))
            gate = max(55.0, min(2200.0, baseline * 1.20 + 18.0))
            self._visual_noise_floor = baseline
            self._adaptive_gate_raw = gate
            self._visual_peak = max(self._visual_peak, baseline * 1.8, baseline + 260.0)
            self._mic_calibrated = True
            contaminated = p80 > max(p20 * 2.4, p20 + 650.0)
            self._mic_quality = "MIC PRONTO"
            self._save_mic_profile()
            self._log(
                "info",
                f"Microfone recalibrado no stream: piso={baseline:.0f} gate={gate:.0f} "
                f"faixa={p20:.0f}-{p80:.0f} contaminada={int(contaminated)}",
            )
        except Exception as exc:
            self._log("warning", f"Recalibracao no stream ignorada: {exc}")
        finally:
            self._calibration_samples.clear()
            self._calibration_started_at = 0.0
            self._calibration_requested.clear()
            self._state("AGUARDANDO", "Calibracao concluida")
        return True

    def _listen_on_stream(self, stream, recognizer, block_frames: int):
        """
        Wake V5 BALANCED:
        - continua aceitando apenas frases exatas de chamada;
        - não exige dois resultados finais, que deixava o Oi Jarvis difícil;
        - consenso de dois reconhecedores OU final forte do restrito;
        - em janela de call exige consenso, mas não biometria de voz.
        """
        loose_recognizer = None
        if self.DUAL_WAKE:
            try:
                loose_recognizer = self._new_loose_wake_recognizer()
            except Exception:
                loose_recognizer = None

        chunk_seconds = block_frames / self.SAMPLE_RATE
        # Pre-roll do wake: preserva o inicio quando a pessoa fala
        # "Oi Jarvis, tudo bom?" sem pausa. Ele nao entra no endpoint ao vivo;
        # so e anexado ao STT forte depois que houve fala real.
        wake_preroll = deque(maxlen=max(16, int(0.85 / max(chunk_seconds, 0.001))))
        strict_match_at = loose_match_at = 0.0
        strict_started_at = loose_started_at = 0.0
        strict_final_at = loose_final_at = 0.0
        strict_final_conf = loose_final_conf = 0.0
        strict_text = loose_text = ""

        wake_noise_floor = max(45.0, min(float(self._visual_noise_floor or 90.0), 900.0))
        wake_silence = 1.0
        current_lead_silence = 1.0
        wake_segment_active = False

        def reset_candidates():
            nonlocal strict_match_at, loose_match_at, strict_started_at, loose_started_at
            nonlocal strict_final_at, loose_final_at, strict_final_conf, loose_final_conf
            nonlocal strict_text, loose_text
            strict_match_at = loose_match_at = 0.0
            strict_started_at = loose_started_at = 0.0
            strict_final_at = loose_final_at = 0.0
            strict_final_conf = loose_final_conf = 0.0
            strict_text = loose_text = ""

        while not self._stop_event.is_set():
            if self._stream_restart_event.is_set():
                return

            if self._followup_trigger.is_set():
                self._followup_trigger.clear()
                if not self._assistant_busy.is_set():
                    mode = self._followup_mode
                    self._handle_followup_interaction(stream, block_frames, mode=mode)
                    self._discard_stream_backlog(stream)
                    recognizer = self._new_wake_recognizer()
                    if self.DUAL_WAKE:
                        try:
                            loose_recognizer = self._new_loose_wake_recognizer()
                        except Exception:
                            loose_recognizer = None
                    reset_candidates()
                continue

            if self._manual_trigger.is_set():
                self._manual_trigger.clear()
                if not self._assistant_busy.is_set():
                    self._handle_interaction(stream, block_frames)
                    self._discard_stream_backlog(stream)
                    recognizer = self._new_wake_recognizer()
                    if self.DUAL_WAKE:
                        try:
                            loose_recognizer = self._new_loose_wake_recognizer()
                        except Exception:
                            loose_recognizer = None
                    reset_candidates()
                continue

            # Build 10: em modo conversa a captura de turno é a dona do stream.
            # Só começa quando JARVIS terminou de falar/processar; durante TTS o
            # loop normal continua monitorando a frase prioritária "Jarvis, para".
            if (
                self._conversation_mode.is_set()
                and (self.CONVERSATION_ALWAYS_LISTEN or not self._conversation_passive)
                and not self._assistant_busy.is_set()
                and not self._speaking.is_set()
                and not self._listening_session.is_set()
                and not self.has_pending_speech
            ):
                self._handle_conversation_interaction(stream, block_frames)
                self._discard_stream_backlog(stream)
                recognizer = self._new_wake_recognizer()
                if self.DUAL_WAKE:
                    try:
                        loose_recognizer = self._new_loose_wake_recognizer()
                    except Exception:
                        loose_recognizer = None
                reset_candidates()
                continue

            if hasattr(stream, "read_latest"):
                data, overflowed = stream.read_latest(block_frames, max_backlog_chunks=24)
            else:
                data, overflowed = stream.read(block_frames)
            raw = bytes(data)
            if overflowed:
                self._note_audio_overflow("wake")
            self._publish_level(raw)
            self._inline_calibration_tick(raw)
            wake_preroll.append(raw)

            try:
                level = self._rms(raw)
                vad = self._vad_is_speech(raw)
                sensitivity = max(0.85, float(getattr(self, "_mic_sensitivity", 1.0)))
                threshold = max(82.0, (wake_noise_floor * 1.70 + 22.0) / sensitivity)
                speech = bool(vad) if not self.MIC_NOISE_GATE else (vad and level >= max(56.0, threshold * 0.40))
                if speech:
                    if not wake_segment_active:
                        current_lead_silence = wake_silence
                        wake_segment_active = True
                    wake_silence = 0.0
                else:
                    wake_silence += chunk_seconds
                    if self.MIC_NOISE_GATE and level < threshold:
                        wake_noise_floor = wake_noise_floor * 0.985 + level * 0.015
                    if wake_segment_active and wake_silence >= 0.12:
                        wake_segment_active = False
            except Exception:
                pass

            if self._speaking.is_set():
                self._process_interrupt_audio(raw)
                continue
            self._interrupt_recognizer = None
            self._interrupt_voice_votes.clear()
            self._interrupt_audio_window.clear()
            self._interrupt_peak_ratio = 0.0
            self._interrupt_partial_hits = 0
            self._interrupt_last_partial = ""
            if self._assistant_busy.is_set() or self._listening_session.is_set() or self.has_pending_speech:
                continue

            now = time.monotonic()
            newest = max(strict_match_at, loose_match_at)
            if newest and now - newest > self.WAKE_CONSENSUS_WINDOW * 1.7:
                reset_candidates()

            try:
                is_final = bool(recognizer.AcceptWaveform(raw))
                payload = json.loads(recognizer.Result() if is_final else recognizer.PartialResult())
                text = self._wake_text_from_payload(payload)
                if self._is_wake_phrase(text):
                    if not strict_started_at:
                        strict_started_at = now
                    strict_match_at = now
                    strict_text = text
                    if is_final:
                        strict_final_at = now
                        strict_final_conf = self._vosk_result_confidence(payload)
                elif is_final:
                    strict_started_at = 0.0
            except Exception:
                pass

            if loose_recognizer is not None:
                try:
                    is_final = bool(loose_recognizer.AcceptWaveform(raw))
                    payload = json.loads(loose_recognizer.Result() if is_final else loose_recognizer.PartialResult())
                    text = self._wake_text_from_payload(payload)
                    if self._is_wake_phrase(text):
                        if not loose_started_at:
                            loose_started_at = now
                        loose_match_at = now
                        loose_text = text
                        if is_final:
                            loose_final_at = now
                            loose_final_conf = self._vosk_result_confidence(payload)
                    elif is_final:
                        loose_started_at = 0.0
                except Exception:
                    pass

            strict_recent = strict_match_at and now - strict_match_at <= self.WAKE_CONSENSUS_WINDOW
            loose_recent = loose_match_at and now - loose_match_at <= self.WAKE_CONSENSUS_WINDOW
            consensus = bool(strict_recent and loose_recent and abs(strict_match_at - loose_match_at) <= self.WAKE_CONSENSUS_WINDOW)
            stable_both = bool(
                consensus and strict_started_at and loose_started_at
                and now - strict_started_at >= self.WAKE_PARTIAL_STABLE
                and now - loose_started_at >= self.WAKE_PARTIAL_STABLE
            )
            any_final = bool(
                (strict_final_at and now - strict_final_at <= self.WAKE_CONSENSUS_WINDOW)
                or (loose_final_at and now - loose_final_at <= self.WAKE_CONSENSUS_WINDOW)
            )
            strict_strong_final = bool(
                strict_final_at
                and now - strict_final_at <= self.WAKE_CONSENSUS_WINDOW
                and strict_final_conf >= 0.46
            )
            strict_stable_partial = bool(
                self.WAKE_FAST_PARTIAL
                and strict_recent
                and strict_started_at
                and now - strict_started_at >= self.WAKE_PARTIAL_STABLE
                and self._is_wake_phrase(strict_text)
            )

            call_guard = self._call_guard_active()
            if call_guard:
                # Em Discord/Meet/Zoom mantemos uma barreira mais alta, mas um
                # FINAL muito forte ainda pode acordar o JARVIS mesmo sem o
                # segundo reconhecedor. Isso evita o paradoxo de ficar surdo
                # justamente quando Discord está em primeiro plano.
                accepted = (consensus and (any_final or stable_both)) or (strict_strong_final and strict_final_conf >= 0.82)
                minimum_lead = self.CALL_WAKE_MIN_LEAD_SILENCE
            else:
                accepted = (consensus and (any_final or stable_both)) or strict_strong_final or strict_stable_partial
                minimum_lead = self.WAKE_MIN_LEAD_SILENCE

            if not accepted or current_lead_silence < minimum_lead:
                continue
            if now - self._last_wake_at < self.WAKE_COOLDOWN:
                continue

            best_conf = max(strict_final_conf, loose_final_conf)
            if best_conf > 0.0 and best_conf < self.WAKE_MIN_FINAL_CONFIDENCE and not stable_both:
                reset_candidates()
                continue

            self._last_wake_at = now
            self._log(
                "info",
                f"Wake V5: restrito='{strict_text}' livre='{loose_text}' conf={best_conf:.2f} call_guard={int(call_guard)}",
            )
            self._pending_wake_preroll = b"".join(wake_preroll)
            wake_preroll.clear()
            self._handle_interaction(stream, block_frames)
            self._discard_stream_backlog(stream)
            recognizer = self._new_wake_recognizer()
            if self.DUAL_WAKE:
                try:
                    loose_recognizer = self._new_loose_wake_recognizer()
                except Exception:
                    loose_recognizer = None
            reset_candidates()

    def _is_bare_wake_text(self, text: str) -> bool:
        key = self._normalize(text)
        if not key:
            return False
        return any(key == self._normalize(phrase) for phrase in self.WAKE_PHRASES)

    def _handle_interaction(self, stream, block_frames: int):
        if self._assistant_busy.is_set():
            return

        self._conversation_passive = False
        if self._conversation_mode.is_set():
            self._conversation_last_activity_at = time.monotonic()
        self._explicit_wake_turn = True
        self._state("ACORDOU", "Wake word reconhecido")
        if self.on_wake:
            try:
                self.on_wake()
            except Exception:
                pass

        self._listening_visual_state = "OUVINDO"
        if self.VOICE_ACK:
            self._state("FALANDO", "Confirmando wake")
            ack_done = self.speak("Sim?", wait=False, post_delay=0.0, prompt=True)
        else:
            self._state("OUVINDO", "Pode falar")
            ack_done = None
        self._last_live_transcript = ""
        self.last_verbatim_transcript = ""
        self._last_live_confidence = 0.0
        self._last_live_has_final = False
        self._emit_live_transcript("", force=True)

        self._listening_session.set()
        try:
            audio = self._capture_utterance(
                stream, block_frames, gate_event=ack_done,
                start_timeout=self.INITIAL_START_TIMEOUT,
            )

            # Em conversa contínua, silêncio/ruído de ambiente não é um turno do
            # usuário. Ignora sem Whisper e sem responder "Pode falar", evitando
            # loops de TTS + microfone e liberando CPU para a próxima fala real.
            if not audio and (self.conversation_mode or self._last_endpoint_reason == "noise_rejected"):
                self._state("AGUARDANDO", "Ruído/silêncio ignorado")
                return

            # Depois de um wake explícito, ainda vale pedir fala uma vez se a
            # pessoa chamou o JARVIS mas demorou para continuar.
            if not audio:
                self._state("FALANDO", "Pedindo fala")
                prompt_done = self.speak("Pode falar.", wait=False, prompt=True)
                audio = self._capture_utterance(
                    stream, block_frames, gate_event=prompt_done, start_timeout=5.5
                )
            if not audio:
                self._state("AGUARDANDO", "Nenhuma fala detectada")
                return

            # Até duas tentativas de transcrição sem exigir novo Oi Jarvis.
            for attempt in range(3):
                self._state("ENTENDENDO", "Confirmando fala")
                transcript, confidence = self._transcribe_command(audio)
                self.last_transcript = transcript or ""
                self.last_confidence = confidence
                if transcript:
                    literal = " ".join(str(getattr(self, "last_verbatim_transcript", "") or transcript).split()).strip()
                    if self._normalize(literal) != self._normalize(transcript):
                        self._log(
                            "info",
                            f"STT FINAL: literal='{literal[:180]}' | interpretado='{transcript[:180]}'",
                        )
                    else:
                        self._log("info", f"STT FINAL: '{literal[:180]}'")
                    self._assistant_busy.set()
                    self._last_command_dispatch_at = time.monotonic()
                    self._last_voice_response_queue_ms = None
                    self._last_tts_first_audio_ms = None
                    if looks_like_local_command(transcript):
                        self._state("EXECUTANDO", transcript)
                    else:
                        self._state("PROCESSANDO", transcript)
                    self._explicit_wake_turn = False
                    if self.on_command:
                        try:
                            self.on_command(transcript)
                        except Exception as exc:
                            self._assistant_busy.clear()
                            self.last_error = str(exc)
                            self._log("error", f"Erro ao entregar comando à interface: {exc}")
                    return

                # V6: se a pessoa disser "Oi Jarvis" duas vezes, a segunda chamada
                # não vira erro nem pedido de repetição; apenas continuamos ouvindo.
                if self._is_bare_wake_text(self._last_live_transcript):
                    self._state("OUVINDO", "Já estou ouvindo")
                    audio = self._capture_utterance(
                        stream, block_frames, gate_event=None,
                        start_timeout=5.0, capture_mode="normal"
                    )
                    if audio:
                        continue
                    self._state("AGUARDANDO", "Nenhum comando após o wake")
                    return

                if self.on_transcript_rejected:
                    try:
                        self.on_transcript_rejected("Não consegui confirmar o que foi dito.")
                    except Exception:
                        pass
                if attempt >= 2:
                    self._state("AGUARDANDO", "Fala não confirmada")
                    return

                self._state("FALANDO", "Pedindo repetição")
                repeat_done = self.speak("Repete?", wait=False, prompt=True)
                audio = self._capture_utterance(
                    stream, block_frames, gate_event=repeat_done, start_timeout=7.0
                )
                if not audio:
                    self._state("OUVINDO", "Ainda estou esperando")
                    audio = self._capture_utterance(
                        stream, block_frames, gate_event=None, start_timeout=4.5
                    )
                    if not audio:
                        self._state("AGUARDANDO", "Sem resposta")
                        return
        finally:
            self._listening_session.clear()

    def _flush_stream(self, stream, block_frames: int, duration: float):
        end = time.monotonic() + duration

        while (
            time.monotonic() < end
            and not self._stop_event.is_set()
        ):
            try:
                stream.read(block_frames)
            except Exception:
                break

    def _vad_is_speech(self, raw: bytes) -> bool:
        if self._hybrid_vad is not None:
            try:
                return bool(self._hybrid_vad.is_speech(raw))
            except Exception:
                pass
        if self._webrtcvad is not None:
            try:
                return bool(self._webrtcvad.is_speech(raw, self.SAMPLE_RATE))
            except Exception:
                return False
        return False

    def _rms(self, raw: bytes) -> float:
        samples = self._np.frombuffer(raw, dtype=self._np.int16)

        if samples.size == 0:
            return 0.0

        values = samples.astype(self._np.float32)

        return float(
            self._np.sqrt(
                self._np.mean(values * values)
            )
        )

    def _conversation_turn_is_directed(self, text: str, confidence: Optional[float] = None) -> bool:
        """Decide se um turno sem wake foi dirigido ao JARVIS.

        O modo conversa nao pode transformar fala ambiente em comando. A regra
        e intencionalmente assimetrica: comandos locais seguros e respostas
        curtas ao que o JARVIS acabou de dizer passam; conversa longa sem sinais
        de enderecamento e ignorada. Em caso de duvida, pedir "Jarvis" e a
        saida segura.
        """
        raw = " ".join(str(text or "").split()).strip()
        key = self._normalize(raw)
        if not key:
            return False
        if self._is_wake_phrase(raw) or re.search(r"\bjarvis\b", key):
            return True

        # Saudações para audiencia/terceiros sao forte evidencia de stream,
        # jogo, TV ou conversa presencial.
        ambient_patterns = (
            r"^(?:e ai|fala|salve|ola|oi)\s+(?:galera|pessoal|gente|todo mundo|rapaziada|familia)\b",
            r"^(?:hey|hello)\s+(?:everybody|everyone|guys)\b",
            r"^(?:eu|a gente)\s+(?:falei|disse|comentei)\s+(?:pra|para)\s+(?:ele|ela|eles|elas)\b",
            r"^(?:ele|ela|eles|elas)\s+(?:falou|disse|perguntou|comentou)\b",
            r"^(?:mano|cara|irmao|amor|mae|pai|filho|filha)[, ]+(?:voce|tu)\b",
        )
        if any(re.search(p, key) for p in ambient_patterns):
            return False
        if key in {"hey everybody", "hey everyone", "hello everyone", "what's up guys", "whats up guys"}:
            return False

        # Acoes locais passam pelo Router, que ainda aplica contexto e safety.
        try:
            if self._is_fast_safe_local_command(raw) or looks_like_local_command(raw):
                return True
        except Exception:
            pass

        now = time.monotonic()
        since_tts = now - float(self._last_tts_end_at or 0.0)
        recent_assistant = 0.0 <= since_tts <= self.CONVERSATION_NATURAL_WINDOW
        session_anchor = max(
            float(getattr(self, "_conversation_last_activity_at", 0.0) or 0.0),
            float(getattr(self, "_conversation_mode_started_at", 0.0) or 0.0),
            float(self._last_tts_end_at or 0.0),
        )
        recent_session = bool(
            bool(getattr(self, "_conversation_mode", None) and self._conversation_mode.is_set())
            and session_anchor > 0.0
            and 0.0 <= (now - session_anchor) <= self.CONVERSATION_NATURAL_WINDOW
        )
        words = key.split()
        word_count = len(words)

        # Respostas elipticas naturais so fazem sentido logo depois de uma fala
        # do assistente. Isso cobre "sim", "o segundo", "nao, o outro"
        # sem deixar essas mesmas frases ativarem o JARVIS horas depois.
        short_reply = bool(re.fullmatch(
            r"(?:sim|nao|isso|esse|essa|este|esta|pode|claro|beleza|ok|okay|continua|continue|"
            r"o primeiro|o segundo|o terceiro|a primeira|a segunda|a terceira|o outro|a outra|"
            r"esse ai|essa ai|isso mesmo|exatamente|nao esse|nao essa|nao o outro|nao a outra)",
            key,
        ))
        if short_reply:
            return recent_assistant

        # Enderecamento explicito sem precisar repetir o nome.
        directed_markers = bool(re.search(
            r"\b(?:voce|vc|te|contigo|pra voce|para voce|me ajuda|me diga|me fala|me mostra|"
            r"me explica|me responde|pode me|consegue me|faz pra mim|faca pra mim)\b",
            key,
        ))
        if directed_markers:
            return True

        # Uma pergunta curta imediatamente apos a resposta do JARVIS e um
        # follow-up plausivel; fora dessa janela exigimos o nome novamente.
        is_question_like = bool(re.match(
            r"^(?:o que|qual|quais|como|onde|quando|quem|quanto|quantos|por que|porque|e se|sera que)\b",
            key,
        ))
        if recent_assistant and is_question_like and word_count <= 18:
            return True

        # Confiança baixa ou fala majoritariamente inglesa sem wake: rejeita.
        try:
            conf_value = float(confidence) if confidence is not None else None
            if conf_value is not None and conf_value < 0.42:
                return False
        except Exception:
            conf_value = None
        tokens = set(words)
        pt = {"eu","voce","meu","minha","que","como","onde","para","pra","nao","sim","agora","aqui","isso","abre","fecha","modo","tela","musica","acho","quero","gosto","prefiro","entao","mas","tambem","pode","vamos"}
        en = {"i","you","your","the","this","that","it","im","gonna","kill","dead","here","hey","what","why","how","out","come","go","get","we","us"}
        if len(tokens & en) >= 2 and len(tokens & pt) == 0:
            return False

        # Hotfix 13.11.2: o usuario escolheu explicitamente um open-mic. Depois
        # dos guards fortes acima (audiencia/terceiros, confianca e idioma),
        # fala natural em portugues e tratada como dirigida ao JARVIS sem janela
        # temporal. Isso corrige frases como "cara queria saber algum filme".
        if (
            bool(getattr(self, "_conversation_mode", None) and self._conversation_mode.is_set())
            and bool(getattr(self, "CONVERSATION_ALWAYS_LISTEN", False))
            and 1 <= word_count <= 40
        ):
            if conf_value is None or conf_value >= 0.42:
                return True

        # Hotfix 13.11.1: depois que o usuario explicitamente entra em Modo
        # Conversa (ou acabou de responder ao JARVIS), uma frase natural nao
        # precisa ser pergunta/comando. Ainda exigimos uma sessao recente e
        # mantemos todos os filtros de audio ambiente acima.
        if recent_session and 1 <= word_count <= 32:
            if conf_value is None or conf_value >= 0.46:
                return True

        # Falas nao operacionais fora da janela natural ficam de fora.
        # Isso preserva a protecao contra TV/jogo/conversa presencial antiga.
        return False

    def _handle_conversation_interaction(self, stream, block_frames: int):
        self._explicit_wake_turn = False
        """Um turno do modo conversa contínua, sem wake e sem prompts invasivos."""
        if self._assistant_busy.is_set() or self._speaking.is_set():
            return
        # Hotfix 13.11.2: Modo Conversa permanece semanticamente OUVINDO. A
        # esfera e travada em verde/compacta pela GUI e nao pulsa de tamanho.
        self._listening_visual_state = "OUVINDO"
        self._listening_session.set()
        try:
            # Pequeno echo-guard após a fala do próprio JARVIS. É curto o bastante
            # para manter o diálogo fluido e evita que a cauda do TTS vire o
            # começo do próximo turno. O cue de OUVINDO toca depois desse guard.
            elapsed = time.monotonic() - float(self._last_tts_end_at or 0.0)
            if 0.0 <= elapsed < 0.08:
                self._flush_stream(stream, block_frames, 0.08 - elapsed)
            self._last_live_transcript = ""
            self._last_live_confidence = 0.0
            self._last_live_has_final = False
            self._emit_live_transcript("", force=True)
            self._state("OUVINDO", "Modo conversa contínua")
            audio = self._capture_utterance(
                stream, block_frames, gate_event=None,
                start_timeout=self.CONVERSATION_LISTEN_TIMEOUT,
                capture_mode="conversation",
            )
            if not audio:
                if self.CONVERSATION_ALWAYS_LISTEN:
                    # Janela interna terminou em silencio, mas o open-mic nao.
                    # O loop abre imediatamente outra janela sem beep/wake.
                    self._conversation_passive = False
                    self._state("OUVINDO", "Modo conversa: microfone continuamente armado")
                    return
                # Compatibilidade opcional com a politica antiga de espera.
                now = time.monotonic()
                anchor = max(
                    float(getattr(self, "_conversation_last_activity_at", 0.0) or 0.0),
                    float(getattr(self, "_conversation_mode_started_at", 0.0) or 0.0),
                    float(self._last_tts_end_at or 0.0),
                )
                idle_for = max(0.0, now - anchor) if anchor else 0.0
                if self.CONVERSATION_SMART_IDLE and idle_for >= self.CONVERSATION_SESSION_IDLE:
                    self._conversation_passive = True
                    self._state("AGUARDANDO", "Modo conversa em espera; diga Jarvis para retomar")
                else:
                    self._conversation_passive = False
                    self._state("AGUARDANDO", "Modo conversa aguardando sua fala")
                return
            self._state("ENTENDENDO", "Transcrevendo turno")
            transcript, confidence = self._transcribe_command(audio)
            self.last_transcript = transcript or ""
            self.last_confidence = confidence
            if not transcript:
                self._state("OUVINDO", "Não confirmei; continuo ouvindo")
                return
            if not self._conversation_turn_is_directed(transcript, confidence):
                self._log("info", f"Conversa: provável áudio ambiente ignorado: '{transcript[:100]}'")
                now = time.monotonic()
                anchor = max(float(getattr(self, "_conversation_last_activity_at", 0.0) or 0.0), float(self._last_tts_end_at or 0.0))
                idle_for = max(0.0, now - anchor) if anchor else 0.0
                self._conversation_passive = bool(
                    (not self.CONVERSATION_ALWAYS_LISTEN)
                    and self.CONVERSATION_SMART_IDLE
                    and idle_for >= self.CONVERSATION_SESSION_IDLE
                )
                self._state(
                    "OUVINDO" if self.CONVERSATION_ALWAYS_LISTEN else "AGUARDANDO",
                    "Áudio ambiente ignorado; open-mic continua" if self.CONVERSATION_ALWAYS_LISTEN else (
                        "Áudio ambiente ignorado; conversa continua" if not self._conversation_passive else "Áudio ambiente ignorado; diga Jarvis para retomar"
                    ),
                )
                return
            self._conversation_passive = False
            self._conversation_last_activity_at = time.monotonic()
            self._assistant_busy.set()
            self._last_command_dispatch_at = time.monotonic()
            self._last_voice_response_queue_ms = None
            self._last_tts_first_audio_ms = None
            if looks_like_local_command(transcript):
                self._state("EXECUTANDO", transcript)
            else:
                self._state("PROCESSANDO", transcript)
            if self.on_command:
                try:
                    self.on_command(transcript)
                except Exception as exc:
                    self._assistant_busy.clear()
                    self.last_error = str(exc)
                    self._log("error", f"Erro ao entregar turno contínuo à interface: {exc}")
        finally:
            self._listening_session.clear()

    def _handle_followup_interaction(self, stream, block_frames: int, mode: str = "followup"):
        self._explicit_wake_turn = False
        """Continua ouvindo após pergunta, pedido de repetição ou confirmação."""
        if self._assistant_busy.is_set():
            return
        confirmation = str(mode or "").lower() == "confirmation"
        listen_state = "ESPERANDO_RESPOSTA" if confirmation else "OUVINDO"
        self._listening_visual_state = listen_state
        listen_detail = "Responda sim ou não" if confirmation else "Pode responder"

        self._listening_session.set()
        try:
            for attempt in range(3):
                self._state(listen_state, listen_detail)
                self._last_live_transcript = ""
                self._last_live_confidence = 0.0
                audio = self._capture_utterance(
                    stream, block_frames, gate_event=None,
                    start_timeout=(4.5 if confirmation else self.FOLLOWUP_START_TIMEOUT) if attempt == 0 else 5.0,
                    capture_mode="confirmation" if confirmation else "followup",
                )
                if not audio:
                    if attempt == 0:
                        # Dá uma segunda janela silenciosa para quem está pensando.
                        continue
                    self._state("AGUARDANDO", "Follow-up encerrado")
                    return

                self._state("ENTENDENDO", "Confirmando resposta")
                transcript, confidence = (self._transcribe_confirmation_fast(audio) if confirmation else self._transcribe_command(audio))
                self.last_transcript = transcript or ""
                self.last_confidence = confidence
                if transcript:
                    self._assistant_busy.set()
                    self._last_command_dispatch_at = time.monotonic()
                    self._last_voice_response_queue_ms = None
                    self._last_tts_first_audio_ms = None
                    if looks_like_local_command(transcript):
                        self._state("EXECUTANDO", transcript)
                    else:
                        self._state("PROCESSANDO", transcript)
                    if self.on_command:
                        try:
                            self.on_command(transcript)
                        except Exception as exc:
                            self._assistant_busy.clear()
                            self.last_error = str(exc)
                            self._log("error", f"Erro ao entregar follow-up à interface: {exc}")
                    return

                if self.on_transcript_rejected:
                    try:
                        self.on_transcript_rejected("Não consegui confirmar o que foi dito.")
                    except Exception:
                        pass
                if attempt < 2:
                    self._state("FALANDO", "Pedindo repetição")
                    done = self.speak("Repete?", wait=False, prompt=True)
                    # Consome o próprio TTS e volta a ouvir automaticamente.
                    audio2 = self._capture_utterance(
                        stream, block_frames, gate_event=done, start_timeout=5.0,
                        capture_mode="confirmation" if confirmation else "followup"
                    )
                    if audio2:
                        self._state("ENTENDENDO", "Confirmando resposta")
                        transcript, confidence = (self._transcribe_confirmation_fast(audio2) if confirmation else self._transcribe_command(audio2))
                        if transcript:
                            self.last_transcript = transcript
                            self.last_confidence = confidence
                            self._assistant_busy.set()
                            self._last_command_dispatch_at = time.monotonic()
                            self._last_voice_response_queue_ms = None
                            self._last_tts_first_audio_ms = None
                            self._state("PROCESSANDO", transcript)
                            if self.on_command:
                                self.on_command(transcript)
                            return
            self._state("AGUARDANDO", "Resposta não confirmada")
        finally:
            self._listening_session.clear()

    def _transcribe_confirmation_fast(self, audio: bytes) -> Tuple[str, Optional[float]]:
        """Confirmações sim/não não passam pelo Whisper salvo quando necessário."""
        candidates = [self._last_live_transcript or ""]
        try:
            candidates.append(self._transcribe_vosk(audio))
        except Exception:
            pass
        yes = {"sim", "confirmo", "confirma", "pode", "pode sim", "isso", "isso mesmo", "correto", "certo"}
        no = {"nao", "não", "negativo", "cancela", "cancelar", "cancele", "nao pode", "não pode"}
        for candidate in candidates:
            key = self._normalize(candidate)
            if key in yes or key.startswith("sim "):
                self._log("info", f"CONFIRMAÇÃO FAST: sim <- {candidate}")
                return "sim", 1.0
            if key in {self._normalize(x) for x in no} or key.startswith("nao "):
                self._log("info", f"CONFIRMAÇÃO FAST: não <- {candidate}")
                return "não", 1.0
        return self._transcribe_command(audio)

    def _live_phrase_needs_more_time(self, candidate: str) -> bool:
        key = self._normalize(candidate)
        if not key:
            return True
        words = key.split()
        # Antes de considerar uma rota local "completa", verifica se a forma
        # falada costuma aceitar complemento. Isso protege pausas como
        # "move Opera ... para outra tela" e "abre Opera ... no monitor 2".
        if re.match(r"^(?:move|mova|mover|coloca|coloque|bota|bote|joga|leva|manda|passa|transfere)\b", key):
            if not re.search(r"\b(?:monitor|tela|display|outra|outro|primeir|segund|terceir|quart)\w*\b", key):
                return True
        if re.match(r"^(?:abre|abra|abrir|inicia|inicie)\b", key) and len(words) <= 4:
            return True
        if words and words[-1] in {"o", "a", "os", "as", "um", "uma", "uns", "umas"}:
            return True
        if is_complete_local_command(candidate):
            return False
        tail = " ".join(words[-4:])
        unfinished_words = {
            "e", "que", "porque", "para", "pra", "de", "do", "da", "com",
            "se", "tipo", "entao", "mas", "quando", "onde", "como", "qual",
            "quero", "abre", "abrir", "coloca", "colocar", "mova", "move",
        }
        if words[-1] in unfinished_words:
            return True
        unfinished_tails = (
            "deixa eu", "pera ai", "espera ai", "eu quero que",
            "quero que voce", "pode abrir", "quero abrir", "eu acho que",
            "na verdade", "tipo assim",
        )
        return any(tail.endswith(x) or key.endswith(x) for x in unfinished_tails)

    def _deepgram_should_use(self, capture_mode: str = "normal") -> bool:
        """True quando Flux pode ser tentado sem repetir uma autenticação inválida."""
        if str(capture_mode or "normal").lower() == "confirmation":
            return False
        if self.STT_ENGINE in ("local", "offline", "whisper", "vosk"):
            return False
        if DeepgramFluxSession is None:
            return False

        # Reavalia a cada turno. Se a chave mudou, o hash deixa de coincidir com
        # o estado 401 anterior e o JARVIS testa a nova chave automaticamente.
        try:
            state = get_deepgram_key_state(self.project_dir)
            self._deepgram_configured = bool(state.get("configured") and not state.get("invalid_auth"))
            if state.get("invalid_auth"):
                self._deepgram_last_error = state.get("last_error") or "Chave Deepgram marcada como inválida"
                self._stt_backend = "local"
                return False
        except Exception:
            self._deepgram_configured = bool(deepgram_is_configured(self.project_dir))

        if not self._deepgram_configured:
            return False
        if time.monotonic() < float(self._deepgram_disabled_until or 0.0):
            return False
        return True

    def _remember_voice_target(self, transcript: str) -> None:
        """Remember recent command targets as temporary Flux keyterms.

        Only local, reversible-looking commands are eligible. This avoids
        poisoning normal dictation with arbitrary words from conversation.
        """
        text = " ".join(str(transcript or "").split()).strip()
        if not text or not self._is_fast_safe_local_command(text):
            return
        key = self._normalize(text)
        target = re.sub(
            r"^(?:abre|abra|abrir|inicia|inicie|fecha|feche|minimiza|minimize|maximiza|maximize|"
            r"restaura|restaure|move|mova|coloca|coloque|joga|jogue|leva|leve|pesquisa|pesquise|"
            r"procura|procure|busca|busque|clica|clique|pausa|pause|continua|continue)\s+",
            "", key, count=1,
        ).strip()
        if not target or len(target) < 3 or len(target) > 56 or len(target.split()) > 5:
            return
        stop = {"o", "a", "os", "as", "um", "uma", "no", "na", "do", "da", "pra", "para", "ai", "por favor"}
        if target in stop:
            return
        existing = {self._normalize(x) for x in self._recent_voice_terms}
        if self._normalize(target) not in existing:
            self._recent_voice_terms.appendleft(target)

    def _flux_endpoint_profile(self, transcript: str, capture_mode: str = "normal") -> tuple[str, float, float, int]:
        """Choose an endpoint profile from semantics without executing anything."""
        mode = str(capture_mode or "normal").lower()
        text = " ".join(str(transcript or "").split()).strip()
        if mode == "confirmation":
            return "confirmation", 0.58, 0.38, 1200
        if text:
            needs_more = self._live_phrase_needs_more_time(text)
            if self._is_fast_safe_local_command(text):
                if needs_more:
                    return "local_extendable", 0.70, 0.48, 2300
                return "local_fast", 0.60, 0.40, 1400
            if needs_more:
                return "incomplete", 0.84, 0.62, 3800
            tokens = len(self._normalize(text).split())
            if tokens <= 3:
                return "short", 0.66, 0.44, 1900
        if mode == "conversation":
            return "conversation", max(0.76, self.DEEPGRAM_EOT), min(0.54, max(0.30, self.DEEPGRAM_EAGER_EOT)), max(3200, self.DEEPGRAM_EOT_TIMEOUT_MS)
        return "normal", self.DEEPGRAM_EOT, self.DEEPGRAM_EAGER_EOT, self.DEEPGRAM_EOT_TIMEOUT_MS

    def _new_deepgram_session(self, capture_mode: str = "normal"):
        api_key = get_deepgram_api_key(self.project_dir)
        if not api_key or DeepgramFluxSession is None:
            return None
        # 13.12.0: recent verified command targets go first, then the regular
        # installed-app vocabulary. The 100-keyterm cap remains strict.
        keyterms = []
        seen = set()
        try:
            dynamic_terms = load_voice_terms(str(self.project_dir), limit=160)
        except Exception:
            dynamic_terms = []
        try:
            legacy_terms = load_project_keyterms(self.project_dir, limit=100)
        except Exception:
            legacy_terms = []
        for term in list(self._recent_voice_terms) + list(dynamic_terms) + list(legacy_terms):
            clean = " ".join(str(term or "").split()).strip()
            key = self._normalize(clean)
            if clean and key and key not in seen:
                seen.add(key)
                keyterms.append(clean)
            if len(keyterms) >= 100:
                break
        profile, eot, eager, timeout_ms = self._flux_endpoint_profile("", capture_mode)
        self._flux_last_profile = profile
        return DeepgramFluxSession(
            api_key,
            sample_rate=self.SAMPLE_RATE,
            keyterms=keyterms,
            language_hint=self.DEEPGRAM_LANGUAGE_HINTS[0],
            language_hints=self.DEEPGRAM_LANGUAGE_HINTS,
            model=self.DEEPGRAM_MODEL,
            eager_eot_threshold=min(eager, eot),
            eot_threshold=eot,
            eot_timeout_ms=timeout_ms,
            logger=lambda level, msg: self._log(level, msg),
        )

    def _deepgram_failure(self, message: str):
        self._deepgram_failures += 1
        self._deepgram_last_error = str(message or "Falha Deepgram")
        key = self._deepgram_last_error.lower()
        auth_failure = any(token in key for token in (
            "401", "unauthorized", "authentication", "auth failed",
            "invalid api key", "invalid credentials", "forbidden",
        ))
        if auth_failure:
            api_key = get_deepgram_api_key(self.project_dir)
            mark_deepgram_key_invalid(self.project_dir, api_key, self._deepgram_last_error)
            self._deepgram_configured = False
            # Não repete a tentativa enquanto o hash da chave não mudar.
            self._deepgram_disabled_until = 0.0
            self._log("warning", "Deepgram desativado por autenticação inválida; fallback local até a chave mudar.")
            return
        # Circuit breaker para falhas transitórias de rede/serviço.
        if self._deepgram_failures >= 3:
            self._deepgram_disabled_until = time.monotonic() + 60.0
            self._log("warning", "Deepgram temporariamente em fallback local por 60 s apos falhas repetidas.")

    def _capture_utterance_flux(
        self,
        stream,
        block_frames: int,
        gate_event=None,
        start_timeout: float = 6.0,
        capture_mode: str = "normal",
    ) -> bytes:
        """Stream mic audio to Flux and let its turn model decide EndOfTurn.

        A conservative local acoustic ceiling remains only as a fail-safe. It
        does not normally decide the endpoint, avoiding both long waits and
        aggressive 100-300 ms cutoffs from the old local VAD pipeline.
        """
        session = self._new_deepgram_session(capture_mode)
        if session is None:
            self._stt_backend = "local"
            return self._capture_utterance_inner(
                stream, block_frames, gate_event=gate_event,
                start_timeout=start_timeout, capture_mode=capture_mode,
            )

        wake_seed = bytes(getattr(self, "_pending_wake_preroll", b"") or b"")
        self._deepgram_last_transcript = ""
        self._deepgram_last_word_confidence = 0.0
        self._deepgram_last_eot_confidence = 0.0
        self._deepgram_last_words = ()
        self._deepgram_last_low_confidence_words = ()
        self._deepgram_last_tail_ms = None
        self._deepgram_last_connect_ms = None
        self._deepgram_last_languages = ()
        self._deepgram_last_error = ""
        self._last_live_transcript = ""
        self._last_live_confidence = 0.0
        self._last_live_has_final = False

        session.start()
        chunk_seconds = block_frames / self.SAMPLE_RATE
        noise_floor = max(24.0, min(float(self._visual_noise_floor or 90.0), 1800.0))
        pre_roll = deque(maxlen=max(3, int(0.08 / chunk_seconds)))

        # While JARVIS says "Sim?", keep draining sounddevice to avoid overflow.
        # We don't send this audio to Flux, which prevents the assistant's own
        # TTS/echo from becoming the beginning of the user's turn.
        if gate_event is not None:
            gate_deadline = time.monotonic() + 2.4
            while not gate_event.is_set() and not self._stop_event.is_set() and time.monotonic() < gate_deadline:
                try:
                    data, overflowed = stream.read(block_frames)
                    raw = bytes(data)
                    self._publish_level(raw)
                    if overflowed:
                        self._note_audio_overflow("ack")
                    pre_roll.append(raw)
                except Exception:
                    time.sleep(0.002)

        wait_deadline = time.monotonic() + max(0.8, float(start_timeout))
        absolute_deadline = time.monotonic() + 24.0
        frames: list[bytes] = []
        started = False
        local_voice_votes = deque(maxlen=4)
        local_last_voice_at = time.monotonic()
        local_started_at = 0.0
        fallback_reason = ""
        flux_failed = False
        adaptive_profile = self._flux_last_profile or "normal"
        adaptive_text_key = ""
        adaptive_updated_at = 0.0

        # If authentication/network already failed while the acknowledgement was
        # playing, fall back before consuming the user's command audio.
        if session.failed:
            self._deepgram_failure(session.last_error or "Flux falhou antes da captura")
            self._stt_backend = "local-fallback"
            session.close(wait=0.05)
            return self._capture_utterance_inner(
                stream, block_frames, gate_event=None,
                start_timeout=start_timeout, capture_mode=capture_mode,
            )

        # Se wake e comando vieram emendados ("Oi Jarvis, abre o Opera"),
        # Flux tambem recebe o pre-roll do wake. O prefixo e removido do texto
        # final por _strip_wake_prefix; isso preserva a primeira palavra real.
        if wake_seed:
            frames.append(wake_seed)
            session.feed(wake_seed)
            self._pending_wake_preroll = b""

        # Only the last 40 ms of pre-roll is useful and limits acknowledgement echo.
        for raw in list(pre_roll)[-2:]:
            frames.append(raw)
            session.feed(raw)

        try:
            while not self._stop_event.is_set() and time.monotonic() < absolute_deadline:
                data, overflowed = stream.read(block_frames)
                raw = bytes(data)
                now = time.monotonic()
                frames.append(raw)
                if not flux_failed:
                    session.feed(raw)
                self._publish_level(raw)

                if overflowed:
                    self._note_audio_overflow("flux")

                level = self._rms(raw)
                ratio = level / max(noise_floor, 1.0)
                try:
                    vad_speech = self._vad_is_speech(raw)
                except Exception:
                    vad_speech = False
                local_voice = (vad_speech and ratio >= 1.04) or ratio >= 1.34
                local_voice_votes.append(1 if local_voice else 0)

                if session.start_of_turn_event.is_set() or sum(local_voice_votes) >= 2:
                    if not started:
                        started = True
                        local_started_at = now
                    if local_voice:
                        local_last_voice_at = now

                # 13.12.0: tune Flux while the sentence evolves. Eager/partial
                # text is used only to tune listening; it never dispatches an
                # action and never starts TTS. A resumed turn simply keeps
                # listening and may move back to the incomplete profile.
                if self.FLUX_ADAPTIVE_ENDPOINT and not flux_failed:
                    adaptive_text = " ".join(str(session.latest_transcript() or "").split()).strip()
                    adaptive_key = self._normalize(adaptive_text)
                    if adaptive_key and adaptive_key != adaptive_text_key and (now - adaptive_updated_at) >= 0.08:
                        adaptive_text_key = adaptive_key
                        profile, eot, eager, timeout_ms = self._flux_endpoint_profile(adaptive_text, capture_mode)
                        if profile != adaptive_profile:
                            if session.update_listen(
                                eot_threshold=eot,
                                eager_eot_threshold=min(eager, eot),
                                eot_timeout_ms=timeout_ms,
                                language_hints=self.DEEPGRAM_LANGUAGE_HINTS,
                            ):
                                adaptive_profile = profile
                                self._flux_last_profile = profile
                                adaptive_updated_at = now
                                self._log("info", f"FLUX PERFIL: {profile} eot={eot:.2f} timeout={timeout_ms}ms")

                # Flux gives a final transcript + model-integrated EndOfTurn.
                if session.end_event.is_set():
                    result = session.result
                    if result.transcript:
                        self._deepgram_last_transcript = result.transcript
                        self._deepgram_last_word_confidence = float(result.word_confidence or 0.0)
                        self._deepgram_last_eot_confidence = float(result.eot_confidence or 0.0)
                        self._deepgram_last_words = tuple(result.words or ())
                        self._deepgram_last_low_confidence_words = tuple(
                            (word, conf) for word, conf, _start, _end in self._deepgram_last_words
                            if float(conf) < self.FLUX_LOW_WORD_CONF
                        )
                        self._deepgram_last_languages = tuple(result.languages or ())
                        self._last_live_transcript = result.transcript
                        self._last_live_confidence = float(result.word_confidence or 0.0)
                        self._last_live_has_final = True
                        self._last_endpoint_reason = "deepgram_flux_eot"
                        self._stt_backend = "deepgram-flux"
                        self._deepgram_failures = 0
                        try:
                            mark_deepgram_key_valid(self.project_dir, get_deepgram_api_key(self.project_dir))
                        except Exception:
                            pass
                        if session.connected_at and session.started_at:
                            self._deepgram_last_connect_ms = int(round((session.connected_at-session.started_at)*1000))
                        self._deepgram_last_tail_ms = int(round(max(0.0, now-local_last_voice_at)*1000)) if started else None
                        self._last_endpoint_ms = self._deepgram_last_tail_ms
                        self._log(
                            "info",
                            f"FLUX EOT: texto='{result.transcript[:140]}' word_conf={result.word_confidence:.2f} "
                            f"eot_conf={result.eot_confidence:.2f} tail={self._deepgram_last_tail_ms or '-'}ms "
                            f"low_words={len(self._deepgram_last_low_confidence_words)}",
                        )
                        break

                if session.failed and not flux_failed:
                    fallback_reason = session.last_error or "Flux falhou"
                    self._deepgram_failure(fallback_reason)
                    self._stt_backend = "local-fallback"
                    self._log("warning", f"Flux indisponivel nesta fala; continuando captura para fallback local: {fallback_reason}")
                    flux_failed = True
                    session.close(wait=0.0)
                    # Não reinicia o stream aqui: frames/pre-roll já coletados
                    # pertencem a esta fala. Continuamos no mesmo buffer e o
                    # endpoint acústico local assume a partir deste ponto. Isso
                    # evita perder a primeira sílaba se o socket cair no começo.

                if not started and now >= wait_deadline:
                    # Flux may have an Update before StartOfTurn in edge cases.
                    if not session.latest_transcript():
                        session.close(wait=0.05)
                        return b""
                    started = True
                    local_started_at = now

                # If Flux failed after speech had already started, keep the
                # captured command and finish with a conservative local endpoint.
                if flux_failed and started and (now - local_last_voice_at) >= 0.46:
                    fallback_reason = "flux_failure_local_endpoint"
                    self._last_endpoint_reason = fallback_reason
                    self._last_endpoint_ms = int(round((now-local_last_voice_at)*1000))
                    break

                # Fail-safe only. Give Flux >1 s after local voice stops so its
                # own EOT model remains the normal endpoint owner.
                if started and (now - local_last_voice_at) >= self.DEEPGRAM_LOCAL_CEILING:
                    fallback_reason = "flux_local_ceiling"
                    self._last_endpoint_reason = fallback_reason
                    self._last_endpoint_ms = int(round((now-local_last_voice_at)*1000))
                    break

                if started and local_started_at and (now - local_started_at) >= 20.0:
                    fallback_reason = "flux_turn_max"
                    self._last_endpoint_reason = fallback_reason
                    break
        finally:
            session.close(wait=0.25)

        if self._deepgram_last_transcript:
            return b"".join(frames)

        # Preserve any useful eager/update transcript if the socket closed just
        # before a formal EndOfTurn, but only as a fallback candidate.
        candidate = " ".join((session.latest_transcript() or "").split()).strip()
        if candidate and session.eager_event.is_set() and not session.failed:
            self._deepgram_last_transcript = candidate
            self._deepgram_last_word_confidence = float(session.result.word_confidence or 0.0)
            self._deepgram_last_eot_confidence = float(session.result.eot_confidence or 0.0)
            self._last_live_transcript = candidate
            self._stt_backend = "deepgram-flux-partial"
            self._log("info", f"Flux fallback transcript: '{candidate[:140]}'")
            return b"".join(frames)

        if not frames:
            return b""
        # _transcribe_command will use local Whisper/Vosk on these exact frames.
        if fallback_reason:
            self._deepgram_last_error = fallback_reason
        return b"".join(frames)

    def _capture_utterance(
        self,
        stream,
        block_frames: int,
        gate_event=None,
        start_timeout: float = 6.0,
        capture_mode: str = "normal",
    ) -> bytes:
        """
        Wrapper V5.2: marca o instante EXATO em que o microfone está capturando.
        O overlay usa isso como fonte de verdade para ficar verde + OUVINDO.
        """
        capture_started = time.monotonic()
        self._mic_capture_active.set()
        try:
            # Se existe um prompt TTS servindo de gate (Sim?/Repete?), ainda
            # nao estamos semanticamente OUVINDO. O callback continua drenando
            # o driver, mas a janela do usuario abre somente depois do `done`.
            if gate_event is None or gate_event.is_set():
                self._state(self._listening_visual_state, "Microfone aberto")
            else:
                self._state("FALANDO", "Aguardando fim do prompt")
            if self._deepgram_should_use(capture_mode):
                return self._capture_utterance_flux(
                    stream,
                    block_frames,
                    gate_event=gate_event,
                    start_timeout=start_timeout,
                    capture_mode=capture_mode,
                )
            self._stt_backend = "local"
            return self._capture_utterance_inner(
                stream,
                block_frames,
                gate_event=gate_event,
                start_timeout=start_timeout,
                capture_mode=capture_mode,
            )
        finally:
            self._mic_capture_active.clear()
            self._last_capture_ms = int(round((time.monotonic() - capture_started) * 1000))
            if self._reliability is not None:
                try:
                    self._reliability.duration(
                        "voice_capture",
                        self._last_capture_ms,
                        endpoint_ms=self._last_endpoint_ms,
                        endpoint_reason=self._last_endpoint_reason,
                    )
                except Exception:
                    pass
            self._log(
                "info",
                f"LATENCIA voz: captura={self._last_capture_ms}ms endpoint={self._last_endpoint_ms or '-'}ms",
            )

    def _capture_utterance_inner(
        self,
        stream,
        block_frames: int,
        gate_event=None,
        start_timeout: float = 6.0,
        capture_mode: str = "normal",
    ) -> bytes:
        """V6.3: endpoint hibrido acustico + semantico.

        Comandos completos fecham rapido, mas uma pausa de pensamento nao corta
        a frase. O termino acustico funciona mesmo quando o Vosk nao entendeu
        nenhuma palavra, evitando ficar OUVINDO por varios segundos.
        """
        chunk_seconds = block_frames / self.SAMPLE_RATE
        wake_seed = bytes(getattr(self, "_pending_wake_preroll", b"") or b"")
        self._pending_wake_preroll = b""
        pre_roll = deque(maxlen=max(6, int(0.24 / chunk_seconds)))
        frames = []
        started = False
        speech_chunks = 0
        quiet_chunks = 0
        start_votes = deque(maxlen=5)

        noise_floor = max(24.0, min(float(self._visual_noise_floor or 90.0), 1800.0))
        gate = max(55.0, min(2200.0, float(self._adaptive_gate_raw or (noise_floor * 1.20 + 18.0))))
        speech_peak = max(gate * 1.35, noise_floor * 1.7)

        if gate_event is not None:
            gate_deadline = time.monotonic() + 3.0
            while not gate_event.is_set() and not self._stop_event.is_set() and time.monotonic() < gate_deadline:
                try:
                    data, _ = stream.read(block_frames)
                    raw = bytes(data)
                    self._publish_level(raw)
                    # Drena o driver, mas nao guarda o proprio TTS como pre-roll.
                except Exception:
                    time.sleep(0.002)
            # Zera qualquer eco residual do prompt e so AGORA sinaliza OUVINDO.
            pre_roll.clear()
            start_votes.clear()
            self._state(self._listening_visual_state, "Microfone aberto")

        wait_deadline = time.monotonic() + max(0.8, float(start_timeout))
        absolute_deadline = time.monotonic() + 22.0
        speech_started_at = 0.0
        endpoint_reason = "timeout"

        live_recognizer = None
        live_final_parts = []
        live_partial = ""
        live_conf_values = []
        live_frame_counter = 0
        last_candidate_key = ""
        last_candidate_change = time.monotonic()
        # O Router semantico so e consultado quando o texto Vosk muda, nao a
        # cada quadro de 20 ms. Isso reduz CPU/lock pressure durante a fala.
        cached_fast_key = ""
        cached_fast_safe = False
        cached_fast_endpoint = self.ENDPOINT_LOCAL
        last_acoustic_voice_at = time.monotonic()
        mode_key = str(capture_mode or "normal").lower()

        try:
            if self._vosk_model is not None:
                live_recognizer = self._vosk.KaldiRecognizer(self._vosk_model, self.SAMPLE_RATE)
                try:
                    live_recognizer.SetWords(True)
                except Exception:
                    pass
        except Exception:
            live_recognizer = None

        def feed_live(raw: bytes):
            nonlocal live_partial, live_frame_counter
            live_frame_counter += 1
            if live_recognizer is None:
                return ""
            try:
                if live_recognizer.AcceptWaveform(raw):
                    payload = json.loads(live_recognizer.Result())
                    text = str(payload.get("text") or "").strip()
                    if text:
                        live_final_parts.append(text)
                    for item in payload.get("result") or []:
                        if item.get("conf") is not None:
                            live_conf_values.append(float(item["conf"]))
                    live_partial = ""
                elif live_frame_counter % 2 == 0:
                    payload = json.loads(live_recognizer.PartialResult())
                    live_partial = str(payload.get("partial") or "").strip()
            except Exception:
                pass
            candidate = " ".join(live_final_parts + ([live_partial] if live_partial else []))
            candidate = normalize_command(candidate)
            if candidate:
                self._emit_live_transcript(candidate)
            return candidate

        while not self._stop_event.is_set() and time.monotonic() < absolute_deadline:
            data, overflowed = stream.read(block_frames)
            raw = bytes(data)
            now = time.monotonic()
            level = self._rms(raw)
            self._publish_level(raw)

            if overflowed:
                # Nao aborta a fala por overflow; ring/callback preserva os quadros
                # recentes e o log e agregado para nao piorar a pressao da CPU.
                self._note_audio_overflow("capture")

            try:
                vad_speech = self._vad_is_speech(raw)
            except Exception:
                vad_speech = False

            ratio = level / max(noise_floor, 1.0)
            sensitivity = max(0.85, float(getattr(self, "_mic_sensitivity", 1.0)))
            start_gate = max(44.0, (noise_floor * 1.16 + 14.0) / sensitivity)
            if self.MIC_NOISE_GATE:
                acoustic_voice = (vad_speech and ratio >= (1.06 / min(sensitivity, 1.20)) and level >= noise_floor + (18.0 / sensitivity)) or level >= start_gate * 1.10
            else:
                # Depois do wake, WebRTC/HybridVAD tem prioridade absoluta.
                # Piso de ruido salvo ou ambiente alto nao pode silenciar o usuario.
                acoustic_voice = bool(vad_speech)

            if not started:
                pre_roll.append(raw)
                start_votes.append(1 if acoustic_voice else 0)
                if self.MIC_NOISE_GATE and not acoustic_voice and level < noise_floor * 1.35 + 80.0:
                    noise_floor = noise_floor * 0.985 + level * 0.015
                    gate = max(55.0, noise_floor * 1.20 + 18.0)
                if sum(start_votes) >= 2 or ratio >= 1.48:
                    started = True
                    speech_started_at = now
                    if mode_key == "conversation":
                        self._listening_visual_state = "OUVINDO"
                        self._state("OUVINDO", "Fala detectada no modo conversa")
                    frames.extend(pre_roll)
                    for buffered in pre_roll:
                        feed_live(buffered)
                    speech_chunks = max(1, sum(start_votes))
                    speech_peak = max(speech_peak, level)
                    last_acoustic_voice_at = now
                    quiet_chunks = 0
                elif now > wait_deadline:
                    return b""
                continue

            frames.append(raw)
            live_candidate = feed_live(raw)
            candidate_key = self._normalize(live_candidate)
            candidate_changed = bool(candidate_key and candidate_key != last_candidate_key)
            if candidate_changed:
                last_candidate_key = candidate_key
                last_candidate_change = now
                cached_fast_key = candidate_key
                cached_fast_safe = self._is_fast_safe_local_command(live_candidate)
                # Acoes encadeaveis ganham uma cauda um pouco maior para nao
                # cortar "abre Opera [pausa] e OBS". Consultas/read-only podem
                # terminar em ~100 ms sem sacrificar a pausa natural do plano.
                if cached_fast_safe and re.match(
                    r"^(?:mova|move|mover|coloca|coloque|joga|jogue|leva|leve|manda|mandar|passa|passe)\b",
                    candidate_key,
                ) and re.search(r"\b(?:monitor|tela|display|outra|outro)\b", candidate_key):
                    # Destination is already explicit: no reason to keep 180 ms
                    # just in case another clause arrives.
                    cached_fast_endpoint = max(self.ENDPOINT_LOCAL, 0.12)
                elif cached_fast_safe and re.match(
                    r"^(?:minimiza|minimize|maximiza|maximize|expande|expanda|restaura|restaure)\b",
                    candidate_key,
                ):
                    cached_fast_endpoint = max(self.ENDPOINT_LOCAL, 0.12)
                elif cached_fast_safe and re.match(
                    r"^(?:abre|abra|abrir|entra|entre|vai|pesquisa|pesquise|procura|busca)\b",
                    candidate_key,
                ):
                    # Open/search phrases are more likely to continue with "e...".
                    cached_fast_endpoint = max(self.ENDPOINT_LOCAL, 0.18)
                else:
                    cached_fast_endpoint = self.ENDPOINT_LOCAL

            speech_peak = max(level, speech_peak * 0.988)
            transcript_stable = (now - last_candidate_change) >= 0.10
            if self.MIC_NOISE_GATE:
                # Modo legado/adaptativo opt-in.
                acoustic_voice = (vad_speech and ratio >= 1.05) or ratio >= 1.34
                post_peak_drop = speech_peak >= noise_floor * 1.45 and level <= speech_peak * 0.46
                near_floor = ratio <= 1.18 or level <= gate * 0.94
                acoustic_quiet = near_floor or (post_peak_drop and transcript_stable)
            else:
                # 13.12.2: fim de fala segue VAD/hangover, nao o gate de ruido.
                acoustic_voice = bool(vad_speech)
                acoustic_quiet = not acoustic_voice

            if candidate_changed:
                # Palavra nova: nunca termine neste quadro.
                acoustic_quiet = False

            if acoustic_voice and not acoustic_quiet:
                speech_chunks += 1
                quiet_chunks = 0
                last_acoustic_voice_at = now
            else:
                quiet_chunks += 1

            speech_elapsed = now - speech_started_at
            quiet_seconds = quiet_chunks * chunk_seconds
            stable_for = now - last_candidate_change

            # O endpoint usa o mesmo Router V8 da fast-lane, mas o resultado
            # fica em cache enquanto o candidato Vosk nao muda.
            if candidate_key and candidate_key != cached_fast_key:
                cached_fast_key = candidate_key
                cached_fast_safe = self._is_fast_safe_local_command(live_candidate)
                cached_fast_endpoint = self.ENDPOINT_LOCAL
            complete_local = bool(live_candidate and cached_fast_safe)
            needs_more = self._live_phrase_needs_more_time(live_candidate)
            token_count = len(candidate_key.split()) if candidate_key else 0

            # Pausa natural: alguns comandos sao semanticamente completos mas
            # costumam receber complemento depois de uma micro-pausa. Ex.:
            # "abre Opera ... na tela 2" ou "minimiza Opera ... e abre OBS".
            # Nesses casos nao fechamos em 120-180 ms. Consultas instantaneas
            # auto-contidas (hora/RAM/CPU etc.) continuam extremamente rapidas.
            extendable_local = bool(complete_local and re.match(
                r"^(?:abre|abra|abrir|inicia|inicie|minimiza|minimize|maximiza|maximize|"
                r"restaura|restaure|move|mova|mover|coloca|coloque|joga|leva|manda|passa|"
                r"bota|poe|pesquisa|pesquise|procura|busca|descreve|analisa)\b",
                candidate_key,
            ))
            if mode_key == "confirmation":
                endpoint = self.ENDPOINT_CONFIRMATION
            elif mode_key == "conversation":
                # Conversa contínua privilegia frase completa. Ainda fecha em
                # menos de ~1 s de silêncio, mas não corta uma pausa humana de
                # 300-500 ms no meio do raciocínio.
                endpoint = max(0.44, self.ENDPOINT_NORMAL) if live_candidate else max(0.48, self.ACOUSTIC_FALLBACK_ENDPOINT)
            elif complete_local and not extendable_local:
                endpoint = max(self.ENDPOINT_LOCAL, cached_fast_endpoint)
            elif complete_local and extendable_local:
                endpoint = max(0.42 if needs_more else 0.30, cached_fast_endpoint)
            elif needs_more and live_candidate:
                endpoint = self.ENDPOINT_INCOMPLETE
            elif token_count <= 2:
                endpoint = self.ENDPOINT_SHORT
            else:
                endpoint = self.ENDPOINT_NORMAL

            # Comando local completo: rapido, mas respeita hesitacao natural.
            if complete_local and mode_key != "conversation" and speech_elapsed >= 0.20 and stable_for >= 0.12 and quiet_seconds >= endpoint:
                self._last_endpoint_ms = int(round(quiet_seconds * 1000))
                endpoint_reason = "local_complete"
                break

            # Confirmacao sim/nao: curta, mas nao 40 ms a ponto de comer a palavra.
            if mode_key == "confirmation" and speech_elapsed >= 0.12 and quiet_seconds >= endpoint:
                self._last_endpoint_ms = int(round(quiet_seconds * 1000))
                endpoint_reason = "confirmation"
                break

            # Frase normal/incompleta usa estabilidade semantica.
            if live_candidate and speech_elapsed >= 0.24 and stable_for >= 0.16 and quiet_seconds >= endpoint:
                self._last_endpoint_ms = int(round(quiet_seconds * 1000))
                endpoint_reason = "semantic_stable"
                break

            # Ponto essencial da V6.3: mesmo sem Vosk entender palavra alguma,
            # uma queda acustica real encerra a captura. Isso elimina capturas de 6-12s.
            if not live_candidate and speech_elapsed >= 0.28 and quiet_seconds >= self.ACOUSTIC_FALLBACK_ENDPOINT:
                self._last_endpoint_ms = int(round(quiet_seconds * 1000))
                endpoint_reason = "acoustic_no_text"
                break

            # Anti-ruido: frase estavel nao fica presa porque o VAD insiste em voz.
            if live_candidate and not needs_more and stable_for >= 0.55 and ratio <= 1.26 and (now - last_acoustic_voice_at) >= 0.42:
                self._last_endpoint_ms = int(round((now - last_acoustic_voice_at) * 1000))
                endpoint_reason = "anti_noise_stable"
                break

            # Teto semantico: em ambiente com caixa/jogo o VAD pode continuar
            # marcando voz mesmo depois que o usuario terminou. Se o texto nao
            # muda por quase 1 s, nao deixamos a captura ficar 6-10 segundos
            # aberta so por causa do ruido de fundo. Conversa ganha uma folga
            # maior que comandos para preservar pausas naturais.
            semantic_ceiling = 1.15 if mode_key == "conversation" else 0.90
            if live_candidate and not needs_more and speech_elapsed >= 0.55 and stable_for >= semantic_ceiling:
                self._last_endpoint_ms = int(round(stable_for * 1000))
                endpoint_reason = "semantic_force"
                break

        if speech_chunks * chunk_seconds < 0.08 and not frames:
            return b""

        if live_recognizer is not None:
            try:
                payload = json.loads(live_recognizer.FinalResult())
                text = str(payload.get("text") or "").strip()
                if text:
                    live_final_parts.append(text)
                for item in payload.get("result") or []:
                    if item.get("conf") is not None:
                        live_conf_values.append(float(item["conf"]))
            except Exception:
                pass

        quick = normalize_command(" ".join(part for part in live_final_parts if part).strip() or live_partial)
        speech_seconds = max(0.0, speech_chunks * chunk_seconds)
        peak_ratio = float(speech_peak / max(noise_floor, 1.0))
        self._last_capture_speech_ms = int(round(speech_seconds * 1000.0))
        self._last_capture_peak_ratio = round(peak_ratio, 2)
        self._last_live_transcript = quick
        self._last_live_has_final = bool(live_final_parts)
        self._last_live_confidence = (
            sum(live_conf_values) / len(live_conf_values) if live_conf_values else 0.0
        )

        # Em modo conversa, ruído curto podia abrir uma captura, esperar 560-700 ms
        # e ainda gastar 1.5-3 s de Whisper sem haver palavra alguma. Se nem o
        # Vosk ao vivo viu texto e a evidência acústica foi curtíssima/fraca,
        # descarta antes do STT pesado. Fala real continua indo ao Whisper.
        if (
            endpoint_reason == "acoustic_no_text"
            and not quick
            and speech_seconds < 0.20
            and peak_ratio < 2.40
        ):
            endpoint_reason = "noise_rejected"
            self._last_endpoint_reason = endpoint_reason
            self._last_stt_ms = 0
            self._log(
                "info",
                f"CAPTURA descartada antes do Whisper: fala={self._last_capture_speech_ms}ms peak={peak_ratio:.2f}x",
            )
            return b""

        if quick:
            self._emit_live_transcript(quick, force=True)
        self._last_endpoint_reason = endpoint_reason
        self._log(
            "info",
            f"ENDPOINT V6.3: motivo={endpoint_reason} ms={self._last_endpoint_ms or '-'} live='{quick[:120]}' conf={self._last_live_confidence:.2f}",
        )
        payload = b"".join(frames)
        return (wake_seed + payload) if payload and wake_seed else payload

    def _condition_audio_for_stt(self, audio: bytes) -> bytes:
        """Condicionamento pós-VAD: remove DC, AGC moderado e limiter.

        O trecho já foi aceito como fala pelo endpoint híbrido; portanto não há
        segundo gate nem atenuação de quadros fracos que possa comer consoantes
        de quem fala baixo.
        """
        if not audio or self._np is None:
            return audio
        try:
            x = self._np.frombuffer(audio, dtype=self._np.int16).astype(self._np.float32)
            if x.size < 320:
                return audio
            x -= float(self._np.mean(x))
            # V8: o VAD ja selecionou fala. Nao aplicar um segundo gate que
            # enfraquece silabas de quem fala baixo; apenas AGC suave + limiter.
            out = x.copy()
            rms_all = float(self._np.sqrt(self._np.mean(out * out) + 1e-6))
            target_rms = 3000.0
            if 0 < rms_all < target_rms:
                out *= min(2.2, target_rms / max(rms_all, 1.0))
            peak = float(self._np.max(self._np.abs(out))) if out.size else 0.0
            if peak > 28500.0:
                out *= 28500.0 / peak
            out = self._np.clip(out, -32768, 32767).astype(self._np.int16)
            return out.tobytes()
        except Exception:
            return audio

    def _choose_whisper_model(self) -> str:
        """V6.3: base prioriza baixa latencia no CPU sem abandonar pt-BR."""
        requested = str(self.WHISPER_MODEL or "base").strip().lower()

        if requested in ("", "auto", "balanced"):
            return "base"

        return requested

    def _choose_whisper_runtime(self):
        """Seleciona GPU quando realmente disponivel; falha sempre volta ao CPU."""
        requested_device = str(self.WHISPER_DEVICE or "auto").strip().lower()
        requested_compute = str(self.WHISPER_COMPUTE_TYPE or "auto").strip().lower()

        device = requested_device
        if device in ("", "auto"):
            device = "cpu"
            try:
                import ctranslate2
                if int(ctranslate2.get_cuda_device_count() or 0) > 0:
                    device = "cuda"
            except Exception:
                device = "cpu"

        if requested_compute in ("", "auto"):
            compute = "float16" if device == "cuda" else "int8"
        else:
            compute = requested_compute

        return device, compute

    def set_input_device_by_name(self, query: str) -> bool:
        """
        Seleciona o dispositivo que o sounddevice usará no próximo stream.
        """
        if self._sd is None:
            return False

        target = self._normalize(query)

        if not target:
            return False

        try:
            candidates = []

            for index, device in enumerate(
                self._sd.query_devices()
            ):
                try:
                    if int(
                        device.get(
                            "max_input_channels",
                            0
                        )
                    ) < 1:
                        continue

                    name = str(
                        device.get(
                            "name",
                            ""
                        )
                    ).strip()

                    if not name:
                        continue

                    normalized = self._normalize(name)

                    if target == normalized:
                        score = 1.0
                    elif target in normalized:
                        score = 0.96
                    else:
                        score = SequenceMatcher(
                            None,
                            target,
                            normalized
                        ).ratio()

                    candidates.append(
                        (
                            score,
                            index,
                            name
                        )
                    )
                except Exception:
                    continue

            candidates.sort(
                key=lambda item: item[0],
                reverse=True
            )

            if (
                not candidates
                or candidates[0][0] < 0.55
            ):
                return False

            _, index, name = candidates[0]

            self._input_device_index = int(index)
            self.input_device_name = name
            self._stream_restart_event.set()

            self._log(
                "info",
                f"Microfone do VoiceEngine alterado: {name}"
            )

            return True

        except Exception as exc:
            self._log(
                "warning",
                f"Não foi possível trocar o microfone do VoiceEngine: {exc}"
            )
            return False

    def request_microphone_calibration(self, delay: float = 1.35):
        """Agenda recalibracao no stream atual, sem reiniciar o microfone."""
        self._calibration_due_at = time.monotonic() + max(0.0, float(delay))
        self._calibration_started_at = 0.0
        self._calibration_samples.clear()
        self._mic_quality = "CALIBRANDO"
        self._calibration_requested.set()
        return True

    def restart_input_stream(self):
        """Reabre a entrada e revive a thread clássica se ela tiver parado."""
        self._direct_open_failures = 0
        self.last_error = ""
        self._stream_restart_event.set()
        thread = self._wake_thread
        if thread is None or not thread.is_alive():
            self._stream_restart_event.clear()
            self._ready = False
            self._stop_event.clear()
            return self._spawn_wake_thread_classic()
        return True

    def refresh_output_device(self):
        """Reinicializa o mixer para seguir a nova saída padrão do Windows."""
        try:
            if self._pygame and self._mixer_ready:
                try:
                    self._pygame.mixer.music.stop()
                except Exception:
                    pass

                try:
                    self._pygame.mixer.quit()
                except Exception:
                    pass

            self._mixer_ready = False

            if self._pygame:
                self._pygame.mixer.init()
                self._mixer_ready = True

            self._log(
                "info",
                "Saída do TTS reinicializada."
            )

        except Exception as exc:
            self._mixer_ready = False
            self._log(
                "warning",
                f"Não foi possível reinicializar a saída do TTS: {exc}"
            )

    def _voice_hotwords(self) -> str:
        if not self.WHISPER_BIAS:
            return ""
        # V7: o dicionario ativo e montado a partir dos apps realmente
        # instalados/ensinados. O catalogo global enorme fica fora do prompt
        # para nao criar colisoes foneticas no STT.
        now = time.monotonic()
        if not self._voice_terms_cache or now - self._voice_terms_cache_at > 45.0:
            try:
                self._voice_terms_cache = list(load_voice_terms(str(self.project_dir), limit=220))
            except Exception:
                self._voice_terms_cache = []
            self._voice_terms_cache_at = now

        # V8: STT deve ser neutro. So poucos nomes realmente distintivos entram
        # como bias; catalogo de apps pertence ao App Resolver, nao ao Whisper.
        core_terms = [PUBLIC_NAME, "ChatGPT", "Opera GX", "OBS Studio"]
        seen = set()
        terms = []
        for term in core_terms + list(self._voice_terms_cache):
            term = " ".join(str(term or "").split()).strip()
            key = self._normalize(term)
            if key and key not in seen:
                seen.add(key)
                terms.append(term)
        # Limite defensivo: mais vocabulario nao significa mais precisao.
        return " ".join(terms[:24])

    def _refresh_voice_terms(self):
        now = time.monotonic()
        cache = list(getattr(self, "_voice_terms_cache", []) or [])
        cache_at = float(getattr(self, "_voice_terms_cache_at", 0.0) or 0.0)
        if not cache or now - cache_at > 45.0:
            try:
                project_dir = getattr(self, "project_dir", Path(os.environ.get("JARVIS_APP_DIR") or Path(__file__).resolve().parent))
                cache = list(load_voice_terms(str(project_dir), limit=220))
            except Exception:
                cache = []
            try:
                self._voice_terms_cache = cache
                self._voice_terms_cache_at = now
            except Exception:
                pass
        return list(cache)

    def _best_spoken_app_term(self, target: str):
        """Resolve apenas a *grafia* de uma entidade falada; não executa nada."""
        query = " ".join(str(target or "").split()).strip()
        qn = normalize_app_name(query)
        qcompact = qn.replace(" ", "")
        terms = self._refresh_voice_terms()
        # Acrônimos curtos (OBS, VLC, EA) só são corrigidos por igualdade exata
        # ou compacta; fuzzy curto seria arriscado.
        for term in terms:
            clean = " ".join(str(term or "").split()).strip()
            tn = normalize_app_name(clean)
            if tn and (qn == tn or (qcompact and qcompact == tn.replace(" ", ""))):
                return clean
        if len(qcompact) < 4:
            return None
        scored = []
        for term in terms:
            clean = " ".join(str(term or "").split()).strip()
            tn = normalize_app_name(clean)
            if not tn:
                continue
            score = float(spoken_app_similarity(qn, tn) or 0.0)
            if score >= 0.72:
                scored.append((score, clean, tn))
        if not scored:
            return None
        scored.sort(key=lambda row: (row[0], -len(row[1])), reverse=True)
        top = scored[0]
        second = next((row for row in scored[1:] if row[2] != top[2]), None)
        margin = top[0] - (second[0] if second else 0.0)
        # Correção de texto exige mais certeza que o App Resolver.
        if top[0] >= 0.88 or (top[0] >= 0.80 and margin >= 0.10):
            return top[1]
        return None

    def _repair_mixed_language_app_entity(self, text: str) -> str:
        """Corrige nomes de apps ingleses sem alterar o significado da frase."""
        raw = " ".join(str(text or "").split()).strip()
        if not raw:
            return raw
        m = re.match(
            r"^(abre|abra|abrir|abril|inicia|inicie|fecha|feche|fechar|"
            r"minimiza|minimize|maximiza|maximize|expande|restaura|"
            r"move|mova|mover|manda|passa|coloca|bota|transfere)\s+(.+)$",
            raw, flags=re.I,
        )
        if not m:
            return raw
        verb, rest = m.group(1), m.group(2).strip()
        # Destino de monitor não faz parte do nome da entidade.
        suffix = ""
        target = rest
        mm = re.match(
            r"^(.+?)(\s+(?:para|pra|pro|na|no)\s+(?:(?:a|o)\s+)?(?:"
            r"outra\s+tela|outro\s+monitor|(?:tela|monitor|display)\s*\d+|"
            r"(?:primeira|segunda|terceira|quarta|primeiro|segundo|terceiro|quarto)\s+(?:tela|monitor|display)))$",
            rest, flags=re.I,
        )
        if mm:
            target, suffix = mm.group(1).strip(), mm.group(2)
        target = re.sub(r"^(?:o|a)\s+", "", target, flags=re.I).strip()
        repaired = self._best_spoken_app_term(target)
        if not repaired:
            return raw
        return f"{verb} {repaired}{suffix}".strip()

    def _postprocess_transcript(self, text: str) -> str:
        value = " ".join(
            str(text or "").split()
        ).strip()

        corrections = [
            (r"\bcorel\s+draw\b", "CorelDRAW"),
            # Build 15: grafias foneticas comuns que nao mudam a intencao.
            (r"\bprossim([oa])\b", r"próxim\1"),
            (r"\bpros(s)?im([oa])\b", r"próxim\2"),
            (r"\bmonito\s+(?=\d|um\b|dois\b|tres\b|tr[eê]s\b)", "monitor "),
            (r"\bmicofone\b", "microfone"),
            (r"\bmicrofoni\b", "microfone"),
            (r"\bchat\s*gpt\b", "ChatGPT"),
            (r"\bopera\s+g\s*x\b", "Opera GX"),
            (r"\bobs\s+studio\b", "OBS Studio"),
            (r"\brevo\s+uninstaller\b", "Revo Uninstaller"),
            (r"^abriu\s+", "abre "),
            (r"^placa\s+m[uú]sica\b", "coloca música"),
            (r"\bpente\b", "Paint"),
            (r"\bauto\s*falante\b", "alto falante"),
            (r"\bliving\s+on\s+the\s+player\b", "Livin on a Prayer"),
            (r"\bleave\s+it\s+on\s+the\s+player\b", "Livin on a Prayer"),
            (r"\blivin\s+on\s+the\s+player\b", "Livin on a Prayer"),
            (r"\bmicrofono\b", "microfone"),
            (r"\bmicr[oó]fono\b", "microfone"),
            (r"\bcalipro\b", "calibrar microfone"),
            (r"\bcalibro\b", "calibrar microfone"),
            # 13.11.6: erros foneticos observaveis em fala rapida pt-BR.
            # As formas abaixo corrigem apenas tokens, nunca inventam um alvo.
            (r"^\s*(?:fexa|feixa|fexa ai)\s+", "fecha "),
            (r"^\s*(?:prucura|percura|pisquisa|pesquiza)\s+", "pesquisa "),
            (r"^\s*(?:minimisa|minimiza ai)\s+", "minimiza "),
            (r"^\s*(?:maximisa|maximiza ai)\s+", "maximiza "),
        ]

        for pattern, replacement in corrections:
            value = re.sub(
                pattern,
                replacement,
                value,
                flags=re.I
            )

        # "open" so vira Opera em contexto de controle de aplicativo. Em uma
        # conversa sobre "open source" a palavra permanece intacta.
        app_context = self._normalize(value)
        if re.match(r"^(abre|abrir|abra|abrih|abrei|abril|fecha|fechar|feche|minimiza|minimizar|maximiza|maximizar|expande|expandir|restaura|restaurar|mova|move|mover)\b", app_context):
            value = re.sub(r"\b(?:open|opem|[óo]pero|oper)\b", "Opera", value, flags=re.I)
            value = re.sub(r"\b(?:descorte|descoredo|discordia|do sorte|do sort|de cordinho)\b", "Discord", value, flags=re.I)
            value = re.sub(r"\b(?:chat de pt|chat g pt|chat gepete)\b", "ChatGPT", value, flags=re.I)
            value = re.sub(r"\b(?:bloody strike|bloody striking|blood striking)\b", "BLOODSTRIKE", value, flags=re.I)
        value = re.sub(r"^(?:abrih|abrei|abreh|abri se|abri ce)\s+", "abre ", value, flags=re.I)

        value = self._repair_mixed_language_app_entity(value)
        return value.strip()

    def _transcript_quality(
        self,
        text: str,
        confidence: Optional[float],
    ) -> float:
        if not text:
            return 0.0

        score = 0.58

        if confidence is not None:
            score += max(
                -0.30,
                min(
                    0.28,
                    (confidence + 1.0) * 0.32
                )
            )

        normalized = self._normalize(text)

        known = (
            "abre abrir fecha fechar minimize minimizar maximize maximizar "
            "volume musica pesquise tela monitor photoshop coreldraw comercial "
            "chatgpt opera youtube spotify"
        ).split()

        if any(
            token in normalized
            for token in known
        ):
            score += 0.10

        if len(
            normalized.split()
        ) >= 3:
            score += 0.05

        return max(
            0.0,
            min(score, 1.0)
        )

    def _run_whisper_pass(
        self,
        model,
        wav_path,
        beam_size: int,
        prompt: str,
        language_override: Optional[str] = None,
    ):
        infer_started = time.monotonic()

        if self._whisper_backend == "whispercpp-server-vulkan":
            language_mode = (language_override or self.WHISPER_LANGUAGE or "pt").lower()
            server_language = "auto" if language_mode in {"auto", "pt-en", "bilingual", "pt+en"} else language_mode
            text = model.transcribe(wav_path, language=server_language, timeout=7.0)
            self._last_whisper_infer_ms = int(round((time.monotonic() - infer_started) * 1000))
            self._stt_backend = "local-vulkan-gpu"
            self._last_raw_stt_text = str(text or "").strip()
            return self._postprocess_transcript(self._last_raw_stt_text), None, {"backend": "whispercpp-server-vulkan", "language": server_language}

        if self._whisper_backend == "whispercpp-vulkan":
            # pywhispercpp aceita float32 numpy diretamente, mantendo o modelo
            # carregado na RX 580 entre falas. Nao ha prompt/hotwords aqui: o
            # Router/Entity Resolver continuam responsaveis pelo significado.
            language_mode = (language_override or self.WHISPER_LANGUAGE or "pt").lower()
            cpp_language = "auto" if language_mode in {"auto", "pt-en", "bilingual", "pt+en"} else language_mode
            try:
                segments = model.transcribe(
                    wav_path,
                    language=cpp_language,
                translate=False,
                no_context=True,
                temperature=0.0,
                print_progress=False,
                print_realtime=False,
                    print_timestamps=False,
                )
            except Exception:
                # Builds antigos do binding podem não aceitar `auto`.
                segments = model.transcribe(
                    wav_path, language="pt", translate=False, no_context=True,
                    temperature=0.0, print_progress=False, print_realtime=False,
                    print_timestamps=False,
                )
            segment_list = list(segments or [])
            self._last_whisper_infer_ms = int(round((time.monotonic() - infer_started) * 1000))
            self._stt_backend = "local-amd-vulkan"
            text = " ".join(
                str(getattr(segment, "text", "") or "").strip()
                for segment in segment_list
                if str(getattr(segment, "text", "") or "").strip()
            ).strip()
            self._last_raw_stt_text = text
            return self._postprocess_transcript(text), None, {"backend": "whispercpp-vulkan", "language": language_mode}

        hotwords = self._voice_hotwords() if self.WHISPER_BIAS else None
        initial_prompt = str(prompt or "") if self.WHISPER_BIAS else None
        language_mode = (language_override or self.WHISPER_LANGUAGE or "pt").lower()
        whisper_language = None if language_mode in {"auto", "pt-en", "bilingual", "pt+en"} else language_mode
        segments, info = model.transcribe(
            wav_path,
            language=whisper_language,
            beam_size=beam_size,
            best_of=1,
            patience=1.0,
            temperature=0.0,
            condition_on_previous_text=False,
            # A captura V8 ja fez endpoint/VAD. Rodar VAD de novo pode comer
            # consoantes de fala baixa, então Whisper recebe o áudio selecionado.
            vad_filter=False,
            hotwords=hotwords,
            initial_prompt=initial_prompt,
            no_speech_threshold=0.55,
            log_prob_threshold=-1.15,
            compression_ratio_threshold=2.40,
            repetition_penalty=1.08,
            no_repeat_ngram_size=3,
        )

        segment_list = list(segments)
        self._last_whisper_infer_ms = int(round((time.monotonic() - infer_started) * 1000))
        self._stt_backend = "local-faster-whisper"

        text = " ".join(
            segment.text.strip()
            for segment in segment_list
            if segment.text.strip()
        ).strip()
        self._last_raw_stt_text = text

        values = [
            float(segment.avg_logprob)
            for segment in segment_list
            if getattr(
                segment,
                "avg_logprob",
                None
            ) is not None
        ]

        confidence = (
            sum(values) / len(values)
            if values
            else None
        )

        return (
            self._postprocess_transcript(text),
            confidence,
            info,
        )

    def _safe_preload_whisper(self):
        try:
            self._load_whisper_model()
        except Exception as exc:
            self._log(
                "warning",
                f"Whisper ficará em fallback até carregar: {exc}"
            )

    def _physical_cpu_threads(self) -> int:
        """Threads de STT escolhidos pelo perfil do hardware.

        Em Xeon com muitos cores, usar todos pode piorar frases curtas por
        oversubscription. O perfil reserva folga para captura/VAD/TTS/UI.
        """
        if self._hardware_profile is not None:
            try:
                return int(self._hardware_profile.recommended_whisper_threads())
            except Exception:
                pass
        count = 0
        try:
            import psutil as _psutil
            count = int(_psutil.cpu_count(logical=False) or 0)
        except Exception:
            count = 0
        if count <= 0:
            logical = int(os.cpu_count() or 4)
            count = max(2, logical // 2) if logical >= 4 else logical
        override = jarvis_env("WHISPER_CPU_THREADS", "").strip()
        if override:
            try:
                count = int(override)
            except Exception:
                pass
        return max(2, min(int(count or 2), 12))

    def _load_whisper_model(self):
        if self._whisper_model is not None:
            return self._whisper_model

        from faster_whisper import WhisperModel

        model_name = self._choose_whisper_model()
        self._whisper_model_name = model_name
        runtime_device, runtime_compute = self._choose_whisper_runtime()

        # Lightweight AMD/Intel/NVIDIA Vulkan fallback. The optional GPU setup
        # downloads a prebuilt whisper.cpp server and keeps the model resident.
        if bool(self._gpu_stt_config.get("enabled")) and str(self._gpu_stt_config.get("backend") or "").lower() == "whispercpp-server-vulkan":
            try:
                from vulkan_whisper import VulkanWhisperClient
                load_started = time.monotonic()
                self._state("PREPARANDO", "Iniciando Whisper local na GPU Vulkan")
                client = VulkanWhisperClient(
                    self._gpu_stt_config, sample_rate=self.SAMPLE_RATE,
                    logger=lambda level, msg: self._log(level, msg),
                )
                client.ensure_server(timeout=12.0)
                self._whisper_model = client
                self._whisper_backend = "whispercpp-server-vulkan"
                self._whisper_runtime_device = "vulkan-gpu"
                self._whisper_runtime_compute = "ggml-q5"
                self._last_whisper_load_ms = int(round((time.monotonic() - load_started) * 1000))
                self._gpu_stt_last_error = ""
                self._log("info", f"Whisper GPU Vulkan pronto: {self._gpu_stt_config.get('gpu_name') or 'GPU'}")
                return self._whisper_model
            except Exception as exc:
                self._gpu_stt_last_error = str(exc)
                self._log("warning", f"Whisper Vulkan indisponivel; fallback CPU: {exc}")
                self._whisper_model = None
                self._whisper_backend = "faster-whisper"

        # Legacy source-build Vulkan backend remains supported.
        if bool(self._gpu_stt_config.get("enabled")) and str(self._gpu_stt_config.get("backend") or "").lower() == "pywhispercpp-vulkan":
            try:
                from pywhispercpp.model import Model as WhisperCppModel
                cpp_model = str(self._gpu_stt_config.get("model") or model_name or "base")
                models_dir = self.models_dir / "whispercpp"
                models_dir.mkdir(parents=True, exist_ok=True)
                load_started = time.monotonic()
                self._state("PREPARANDO", f"Carregando Whisper {cpp_model} na GPU AMD/Vulkan")
                self._whisper_model = WhisperCppModel(
                    cpp_model,
                    models_dir=str(models_dir),
                    n_threads=max(2, min(self._physical_cpu_threads(), 8)),
                    print_progress=False,
                    print_realtime=False,
                    print_timestamps=False,
                    no_context=True,
                    context_params={
                        "use_gpu": True,
                        "gpu_device": int(self._gpu_stt_config.get("gpu_device", 0) or 0),
                    },
                )
                self._whisper_backend = "whispercpp-vulkan"
                self._whisper_runtime_device = "amd-vulkan"
                self._whisper_runtime_compute = "ggml"
                self._last_whisper_load_ms = int(round((time.monotonic() - load_started) * 1000))
                self._gpu_stt_last_error = ""
                self._log(
                    "info",
                    f"Whisper GPU pronto: backend=whisper.cpp/Vulkan modelo={cpp_model} "
                    f"gpu={self._gpu_stt_config.get('gpu_name') or 'AMD'} load={self._last_whisper_load_ms}ms",
                )
                self._state("AGUARDANDO", f"Reconhecimento {cpp_model} AMD/Vulkan pronto")
                return self._whisper_model
            except Exception as exc:
                self._gpu_stt_last_error = str(exc)
                self._log("warning", f"STT AMD/Vulkan indisponivel; fallback Xeon/CPU: {exc}")
                self._whisper_model = None
                self._whisper_backend = "faster-whisper"

        self._state(
            "PREPARANDO",
            f"Carregando Whisper {model_name}"
        )

        kwargs = dict(
            device=runtime_device,
            compute_type=runtime_compute,
            cpu_threads=self._physical_cpu_threads(),
        )
        load_started = time.monotonic()

        try:
            self._whisper_model = WhisperModel(
                model_name,
                **kwargs
            )
            self._whisper_runtime_device = runtime_device
            self._whisper_runtime_compute = runtime_compute
            self._whisper_backend = "faster-whisper"
        except Exception as exc:
            # CUDA sem DLL/driver compativel nunca derruba o reconhecimento.
            if runtime_device == "cuda":
                self._log(
                    "warning",
                    f"Whisper CUDA indisponivel; voltando ao CPU int8: {exc}"
                )
                cpu_kwargs = dict(kwargs)
                cpu_kwargs["device"] = "cpu"
                cpu_kwargs["compute_type"] = "int8"
                try:
                    self._whisper_model = WhisperModel(model_name, **cpu_kwargs)
                    self._whisper_runtime_device = "cpu"
                    self._whisper_runtime_compute = "int8"
                    self._whisper_backend = "faster-whisper"
                    exc = None
                except Exception as cpu_exc:
                    exc = cpu_exc

            if self._whisper_model is not None:
                pass
            elif model_name != "small":
                self._log(
                    "warning",
                    f"Whisper {model_name} falhou; tentando small: {exc}"
                )

                model_name = "small"
                self._whisper_model_name = model_name

                self._whisper_model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=kwargs["cpu_threads"],
                )
                self._whisper_runtime_device = "cpu"
                self._whisper_runtime_compute = "int8"
                self._whisper_backend = "faster-whisper"
            else:
                raise

        self._last_whisper_load_ms = int(round((time.monotonic() - load_started) * 1000))
        self._log(
            "info",
            f"Whisper pronto: modelo={model_name} device={self._whisper_runtime_device} "
            f"threads={kwargs['cpu_threads']} load={self._last_whisper_load_ms}ms",
        )
        self._state(
            "AGUARDANDO",
            f"Reconhecimento {model_name} pronto"
        )

        return self._whisper_model

    def _write_temp_wav(self, audio: bytes) -> str:
        fd, path = tempfile.mkstemp(
            prefix="jarvis_voice_",
            suffix=".wav",
        )
        os.close(fd)

        with wave.open(path, "wb") as wav_file:
            wav_file.setnchannels(self.CHANNELS)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.SAMPLE_RATE)
            wav_file.writeframes(audio)

        return path

    def _is_fast_safe_local_command(self, text: str) -> bool:
        """Fast Lane V8: Vosk só pula Whisper para uma rota local clara e segura."""
        value = " ".join(str(text or "").split()).strip()
        key = self._normalize(value)
        if not value:
            return False

        # Controles de mídia extremamente reversíveis não precisam pagar o
        # custo do Whisper quando o Vosk ao vivo já captou a intenção. Esta é a
        # diferença entre um "pausa" que parece instantâneo e um comando que
        # chega 2-4 s depois do usuário terminar de falar.
        instant_media = (
            r"^(?:pause|pausa|pausar|play|resume|continua|continue)$",
            r"^(?:pula|pular|pule|skip)(?:\s+(?:a|o))?\s+(?:abertura|intro|introducao)$",
            r"^(?:(?:proximo|proxima|next)\s+(?:episodio|episode|faixa|track|musica|song)|(?:passa|passar|passe)\s+(?:(?:pro|para o|pelo)\s+)?proximo(?:\s+(?:episodio|ep))?)$",
            r"^(?:episodio|faixa|musica)\s+(?:anterior|passada)$",
            r"^(?:muta|mute|silencia|silenciar|tira\s+o\s+som)$",
        )
        if any(re.match(pattern, key) for pattern in instant_media):
            return True

        # Ações destrutivas/irreversíveis nunca pulam o reconhecimento forte.
        dangerous = (
            "feche ", "fecha ", "fechar ", "apague ", "delete ",
            "exclua ", "remova ", "desligue", "reinicie", "suspenda",
            "bloqueie", "esvazie",
        )
        if key.startswith(dangerous):
            return False

        if VoiceV8Router is not None:
            try:
                # Instância descartável: a checagem de fast-lane não pode alterar
                # o contexto linguístico usado depois pela GUI.
                routed = VoiceV8Router().route(value)
                if not routed or routed.kind != "local" or not routed.commands:
                    return False
                if routed.intent in {
                    "LOCAL_INSTANT", "WINDOWS_LOCAL", "CAPABILITIES", "PERFORMANCE",
                    "SOCIAL_CHAT", "PC_DIAGNOSE", "PC_OPINION", "VISION", "VISION_CONTEXT", "SCREENSHOT",
                    "CLARIFY", "CLARIFY_APP", "CLARIFY_MOVE", "USER_CORRECTION",
                    "PRIORITY_INTERRUPT", "MODE_AUTO", "MODE_CONVERSATION", "MODE_COMMAND",
                    "MODE_GAMER", "FULLSCREEN", "MEDIA_CONTROL", "MEDIA_NEXT", "MEDIA_PREVIOUS",
                    "CRUNCHY_SKIP", "CRUNCHY_NEXT",
                    # Começar/parar/listar a gravação de uma rotina não executa
                    # a rotina gravada e é facilmente reversível. RUN/DELETE
                    # ficam propositalmente fora desta via rápida.
                    "WORKFLOW_START", "WORKFLOW_STOP", "WORKFLOW_LIST",
                }:
                    return True
                # Pesquisa livre fica fora da Fast Lane: termos abertos/ingleses
                # precisam da transcrição final bilíngue antes de navegar.
                safe_actions = {
                    "OPEN_APP", "OPEN_SITE", "OPEN_SITE_IN_APP",
                    "MINIMIZE_WINDOW", "MAXIMIZE_WINDOW",
                    "RESTORE_WINDOW", "MOVE_WINDOW", "MOVE_OTHER",
                }
                steps = list(getattr(routed, "steps", None) or [])
                if not steps or not all(getattr(step, "action", "") in safe_actions for step in steps):
                    return False
                # OPEN_APP em Fast Lane precisa de uma entidade minimamente
                # reconhecível; fala ruim não pode pular Whisper só porque começa
                # com "abre". Resolver final ainda faz a checagem de segurança.
                for step in steps:
                    if getattr(step, "action", "") == "OPEN_APP":
                        target = str(getattr(step, "target", "") or "").strip()
                        if not target or len(normalize_app_name(target).replace(" ", "")) < 3:
                            return False
                        # Só consulta o vocabulário quando ele já está em memória.
                        # Isso evita I/O/resolver no caminho crítico e mantém o
                        # primeiro boot/testes autocontidos.
                        terms_cache = getattr(self, "_voice_terms_cache", None)
                        if terms_cache:
                            repaired = self._best_spoken_app_term(target)
                            if not repaired:
                                return False
                return True
            except Exception:
                pass

        # Compatibilidade caso o Router V8 não carregue: conserva a regra antiga.
        if not is_complete_local_command(value):
            return False
        return looks_like_local_command(value)

    def _looks_like_local_intent_candidate(self, text: str) -> bool:
        """True quando uma hipótese latina já tem forma válida de comando local.

        Isto NÃO executa a ação nem ativa a Fast Lane. Serve apenas para impedir
        que o detector de idioma do Whisper force uma segunda passagem pt-BR
        quando ele rotula acidentalmente uma frase portuguesa como it/pl/de.
        """
        value = " ".join(str(text or "").split()).strip()
        if not value or self._has_unsupported_script(value):
            return False
        if VoiceV8Router is not None:
            try:
                routed = VoiceV8Router().route(value)
                return bool(routed and routed.kind == "local" and routed.commands)
            except Exception:
                pass
        try:
            return bool(looks_like_local_command(value))
        except Exception:
            return False

    def _is_reversible_browser_search(self, text: str) -> bool:
        """Reconhece pesquisa simples; usada só com confiança Vosk alta.

        Mantemos esta categoria fora de `_is_fast_safe_local_command` para não
        encerrar cedo uma consulta cuja grafia ainda esteja oscilando. Depois que
        o áudio terminou, porém, uma hipótese ao vivo forte pode pular Whisper:
        pesquisar o termo errado é reversível e não altera arquivos/contas.
        """
        value = " ".join(str(text or "").split()).strip()
        if not value or VoiceV8Router is None:
            return False
        try:
            routed = VoiceV8Router().route(value)
            if not routed or routed.kind != "local" or routed.intent != "BROWSER_SEARCH":
                return False
            command = str((routed.commands or [""])[0] or "")
            parts = command.split("|", 1)
            query = parts[1].strip() if len(parts) == 2 else ""
            return len(self._normalize(query).replace(" ", "")) >= 2
        except Exception:
            return False

    def _detected_whisper_language(self, info) -> str:
        try:
            if isinstance(info, dict):
                value = info.get("language") or info.get("lang") or ""
            else:
                value = getattr(info, "language", "") or ""
            return str(value).strip().lower().split("-")[0]
        except Exception:
            return ""

    @staticmethod
    def _has_unsupported_script(text: str) -> bool:
        # PT/EN usam Latin. Se auto-STT produzir cirílico/CJK/árabe/grego numa
        # sessão configurada PT<->EN, tratamos como hipótese errada e refazemos
        # a passagem em português, em vez de dizer ao Gemini que o usuário
        # "falou russo/chinês".
        for ch in str(text or ""):
            code = ord(ch)
            if (
                0x0370 <= code <= 0x052F
                or 0x0590 <= code <= 0x08FF
                or 0x3040 <= code <= 0x30FF
                or 0x3400 <= code <= 0x9FFF
                or 0xAC00 <= code <= 0xD7AF
            ):
                return True
        return False

    def _looks_like_guarded_pt_en_latin(self, text: str) -> bool:
        """Aceita falso código de idioma quando o texto já parece PT/EN útil.

        Whisper às vezes marca fala latina curta como `la`, `sk` ou `pl`. Se a
        própria transcrição contém estrutura clara de português/inglês ou um
        comando local, repetir Whisper em pt-BR só adiciona latência.
        """
        value = normalize_command(self._postprocess_transcript(text or ""))
        if not value or self._has_unsupported_script(value):
            return False
        if looks_like_local_command(value):
            return True
        key = self._normalize(value)
        tokens = set(key.split())
        pt = {
            "eu", "voce", "você", "me", "meu", "minha", "que", "como", "onde",
            "abre", "abrir", "fecha", "fechar", "move", "volume", "modo", "conversa",
            "pesquisa", "procura", "para", "no", "na", "do", "da", "um", "uma",
            "quero", "pode", "agora", "depois", "tela", "monitor", "memoria", "hora",
        }
        en = {
            "i", "you", "the", "a", "an", "to", "in", "on", "open", "close", "move",
            "search", "play", "pause", "next", "skip", "download", "file", "browser",
            "what", "how", "where", "please", "steam", "discord", "spotify", "opera",
        }
        if tokens & pt or tokens & en:
            return True
        # Nomes conhecidos instalados também são uma evidência forte de que a
        # fala curta é uma entidade, não polonês/latim acidental.
        try:
            repaired = self._best_spoken_app_term(value)
            if repaired:
                return True
        except Exception:
            pass
        return False

    def _set_verbatim_transcript(self, raw_text: str) -> str:
        """Guarda/exibe a transcricao literal sem as correcoes do Router.

        O texto interpretado pode corrigir "opero" -> "Opera" para executar
        com seguranca, mas a UI deve mostrar o que o STT realmente retornou.
        """
        raw = " ".join(str(raw_text or "").split()).strip()
        raw = self._strip_wake_prefix(raw)
        raw = sanitize_text(raw, limit=500)
        if raw:
            self.last_verbatim_transcript = raw
            self._emit_live_transcript(raw, force=True)
        return raw

    def _preferred_local_language(self, hint_text: str = "") -> str:
        """Escolhe pt/en sem deixar o detector curto inventar ru/pl/it.

        Em modo offline o usuario deste projeto fala majoritariamente pt-BR,
        mas alterna para ingles. Uma escolha deterministica pt/en e mais
        confiavel que auto-detect em falas de 1-3 s. O idioma recente serve de
        desempate; Flux, quando configurado, continua fazendo code-switching
        nativo e nao usa esta heuristica.
        """
        key = self._normalize(hint_text or "")
        tokens = set(key.split())
        pt_words = {
            "eu", "voce", "voces", "me", "meu", "minha", "isso", "aqui", "agora",
            "abre", "abrir", "fecha", "fechar", "pesquisa", "procura", "busca",
            "como", "que", "qual", "onde", "quando", "porque", "por", "para",
            "tudo", "bom", "bem", "cara", "mano", "episodio", "musica", "tela",
            "monitor", "proximo", "proxima", "quero", "pode", "continua", "pausa",
        }
        en_words = {
            "i", "im", "i'm", "you", "your", "we", "they", "the", "this", "that",
            "what", "how", "where", "when", "why", "can", "could", "would", "please",
            "open", "close", "search", "find", "play", "pause", "resume", "next",
            "episode", "song", "skip", "intro", "fullscreen", "browser", "tell", "me",
        }
        pt_score = sum(1 for t in tokens if t in pt_words)
        en_score = sum(1 for t in tokens if t in en_words)
        if re.match(r"^(?:open|close|search|find|play|pause|resume|next|skip|what|how|where|can you|could you)\b", key):
            en_score += 3
        if re.match(r"^(?:abre|abra|fecha|feche|pesquisa|procura|busca|como|me explica|tudo|e ai|oi)\b", key):
            pt_score += 3
        if en_score >= pt_score + 2:
            return "en"
        if pt_score >= en_score + 1:
            return "pt"
        return "en" if getattr(self, "_recent_stt_language", "pt") == "en" else "pt"

    def _fast_lane_min_confidence(self, text: str) -> float:
        key = self._normalize(text or "")
        if re.match(r"^(?:pause|pausa|play|resume|continua|mute|muta|silencia)$", key):
            return 0.52
        if re.match(r"^(?:pula|pular|skip|proximo|proxima|next)\b", key):
            return 0.58
        if re.match(r"^(?:abre|abra|abrir|open)\b", key):
            # A known installed app name is much less ambiguous than a generic
            # free-form open request, so it can use the fast lane earlier.
            try:
                target = re.sub(r"^(?:abre|abra|abrir|open)\s+", "", str(text or ""), flags=re.I).strip()
                if target and self._best_spoken_app_term(target):
                    return min(self.FAST_LANE_APP_CONF, 0.62)
            except Exception:
                pass
            return self.FAST_LANE_APP_CONF
        return self.FAST_LANE_LOCAL_CONF

    def _fuse_local_interpretation(self, final_text: str, quick_text: str = "", vosk_text: str = "", quick_conf: float = 0.0) -> str:
        """Prefer a safe local interpretation when strong STT and live STT disagree.

        The UI still shows the literal strong transcript. This function only
        decides what the local router receives.
        """
        safe_intents = {
            "OPEN_APP", "OPEN_APP_CONTEXT", "BROWSER_SEARCH", "MEDIA_CONTROL",
            "MEDIA_NEXT", "MEDIA_PREVIOUS", "CRUNCHY_SKIP", "CRUNCHY_NEXT",
            "CRUNCHY_SEEK", "FULLSCREEN", "MODE_GAMER", "MODE_AUTO",
            "MODE_CONVERSATION", "PRIORITY_INTERRUPT",
        }

        def local_route(candidate: str):
            value = " ".join(str(candidate or "").split()).strip()
            if not value or VoiceV8Router is None:
                return None
            try:
                routed = VoiceV8Router().route(value)
                if routed and routed.kind == "local" and routed.intent in safe_intents:
                    return routed
            except Exception:
                pass
            return None

        final = " ".join(str(final_text or "").split()).strip()
        final_route = local_route(final)

        # Build 15: uma transcricao forte pode manter o verbo correto mas errar
        # justamente o nome do aplicativo. Antes de aceitar esse alvo, compare
        # com a hipotese ao vivo e com o vocabulario realmente instalado.
        # A regra so atua em OPEN_APP e nunca inventa um app fora do indice local.
        if final_route and getattr(final_route, "intent", "") == "OPEN_APP":
            def _known_open_app(route_obj):
                try:
                    for step in list(getattr(route_obj, "steps", None) or []):
                        if getattr(step, "action", "") == "OPEN_APP":
                            target = str(getattr(step, "target", "") or "").strip()
                            if target:
                                return self._best_spoken_app_term(target)
                except Exception:
                    pass
                return None

            final_known = _known_open_app(final_route)
            for candidate in (quick_text, vosk_text):
                candidate = " ".join(str(candidate or "").split()).strip()
                if not candidate or float(quick_conf or 0.0) < 0.42:
                    continue
                candidate_route = local_route(candidate)
                if not candidate_route or getattr(candidate_route, "intent", "") != "OPEN_APP":
                    continue
                live_known = _known_open_app(candidate_route)
                if live_known and not final_known:
                    rescued = f"abre {live_known}"
                    if local_route(rescued):
                        self._log(
                            "info",
                            f"STT CONSENSO APP: literal='{final[:100]}' + live='{candidate[:100]}' -> '{rescued}'",
                        )
                        return rescued
                if live_known and final_known and self._normalize(live_known) == self._normalize(final_known):
                    # Ambas hipoteses apontam para o mesmo app; devolve a grafia
                    # canonica do indice, eliminando ruido fonetico no roteador.
                    return f"abre {final_known}"

        if final_route:
            return final

        explicit = bool(getattr(self, "_explicit_wake_turn", False))

        def app_entity_rescue_allowed(candidate: str) -> bool:
            """Nao deixa fala comum/midia virar nome de aplicativo por fuzzy."""
            key = self._normalize(candidate)
            if not key:
                return False
            if re.search(
                r"\b(?:musica|faixa|track|som|audio|video|play|plei|pley|pause|pausa|"
                r"proxim[oa]|anterior|seguinte|passa|passe|passar|toca|toque|spotify|"
                r"youtube|netflix|crunchy|prime|disney|max|monitor|monito|tela|display|"
                r"funcionou|nao foi|quem|oque|como|qual|porque)\b",
                key, re.I,
            ):
                return False
            if re.match(r"^(?:um|uma|o|a|os|as|meu|minha|essa|esse|esta|este)\s+", key):
                return False
            return True

        # Fuse a live action verb with an app entity recovered by the stronger
        # transcript. This targets real noisy cases such as live="abrir escolha"
        # + final="ja abri o descorte" without globally treating statements
        # like "ja abri o Discord" as commands.
        if explicit and float(quick_conf or 0.0) >= 0.46:
            live_action = next((
                c for c in (quick_text, vosk_text)
                if re.match(r"^(?:abre|abra|abrir|open)\b", self._normalize(c))
            ), "")
            if live_action:
                final_key = self._normalize(final)
                app_aliases = (
                    (r"\b(?:descorte|descoredo|discordia|do sorte|do sort|de cordinho|discord)\b", "Discord"),
                    (r"\b(?:chat de pt|chat g pt|chat gepete|chatgpt|chat gpt)\b", "ChatGPT"),
                    (r"\b(?:bloody strike|bloody striking|blood strike|blood striking)\b", "BLOODSTRIKE"),
                    (r"\b(?:opera gx|opera|opero|oper)\b", "Opera"),
                )
                for pattern, app_name in app_aliases:
                    if re.search(pattern, final_key, re.I):
                        rescued = f"abre {app_name}"
                        if local_route(rescued):
                            self._log(
                                "info",
                                f"STT FUSAO VERBO+APP: live='{live_action[:80]}' + literal='{final[:100]}' -> '{rescued}'",
                            )
                            return rescued

        threshold = 0.46 if explicit else 0.64
        for candidate in (quick_text, vosk_text):
            candidate = " ".join(str(candidate or "").split()).strip()
            if candidate and float(quick_conf or 0.0) >= threshold and local_route(candidate):
                self._log("info", f"STT FUSAO LOCAL: literal='{final[:120]}' -> interpretado='{candidate[:120]}'")
                return candidate

        # After an explicit wake, a short isolated installed-app entity is a
        # useful rescue when the action verb was swallowed by noise.
        if explicit:
            for candidate in (quick_text, vosk_text):
                raw_original = str(candidate or "").strip()
                if not app_entity_rescue_allowed(raw_original):
                    continue
                raw = re.sub(r"^(?:o|a|the)\s+", "", raw_original, flags=re.I)
                if not raw or len(self._normalize(raw).split()) > 4:
                    continue
                try:
                    app = self._best_spoken_app_term(raw)
                except Exception:
                    app = None
                if app and float(quick_conf or 0.0) >= 0.44:
                    rescued = f"abre {app}"
                    if local_route(rescued):
                        self._log("info", f"STT RESGATE APP: '{raw[:80]}' -> '{rescued}'")
                        return rescued

        return final

    def _transcribe_command(
        self,
        audio: bytes,
    ) -> Tuple[str, Optional[float]]:
        """V6.3: STT de baixa latencia.

        - Vosk ao vivo continua servindo apenas para fast-lane segura;
        - Whisper recebe numpy diretamente (sem WAV/FFmpeg/PyAV);
        - uma unica passagem e o padrao;
        - segunda passagem so existe se JARVIS_WHISPER_SECOND_PASS=1.
        """
        stt_started = time.monotonic()
        self._recognition_passes = 0
        self._last_consensus_score = None

        # Flux already transcribed while the user was speaking. There is no
        # second STT wait after EndOfTurn.
        if self._deepgram_last_transcript:
            raw_flux = self._deepgram_last_transcript
            self._last_raw_stt_text = raw_flux
            flux_text = normalize_command(self._postprocess_transcript(raw_flux))
            flux_conf = float(self._deepgram_last_word_confidence or 0.0) or None
            flux_text = self._validate_transcript(flux_text, None, relaxed=True)
            if flux_text:
                langs = tuple(getattr(self, "_deepgram_last_languages", ()) or ())
                if langs:
                    lead_lang = str(langs[0]).lower()
                    if lead_lang.startswith("en"):
                        self._recent_stt_language = "en"
                    elif lead_lang.startswith("pt"):
                        self._recent_stt_language = "pt"
                self._last_consensus_score = 1.0
                self._recognition_passes = 0
                self._last_stt_ms = int(round((time.monotonic() - stt_started) * 1000))
                self._stt_backend = "deepgram-flux"
                self._log("info", f"STT FLUX FINAL: {flux_text} conf={float(flux_conf or 0):.2f} STT={self._last_stt_ms}ms low_words={len(self._deepgram_last_low_confidence_words)}")
                self._remember_voice_target(flux_text)
                self._deepgram_last_transcript = ""
                self._set_verbatim_transcript(raw_flux)
                return flux_text, flux_conf

        raw_quick = " ".join(str(self._last_live_transcript or "").split()).strip()
        quick = normalize_command(self._postprocess_transcript(raw_quick))
        quick = self._repair_mixed_language_app_entity(quick)
        quick_conf = float(self._last_live_confidence or 0.0)
        quick = self._validate_transcript(quick, None, relaxed=True)
        quick_safe = bool(quick and self._is_fast_safe_local_command(quick))
        quick_search = bool(
            quick and quick_conf >= self.FAST_LANE_SEARCH_CONF and self._is_reversible_browser_search(quick)
        )
        local_threshold = self._fast_lane_min_confidence(quick) if quick_safe else 1.0
        if quick and ((quick_safe and quick_conf >= local_threshold) or quick_search):
            self._last_consensus_score = 1.0
            self._last_stt_ms = int(round((time.monotonic() - stt_started) * 1000))
            self._log("info", f"FAST-LANE ao vivo: {quick} conf={quick_conf:.2f} min={min(local_threshold, self.FAST_LANE_SEARCH_CONF):.2f}")
            self._log("info", f"LATENCIA voz: STT={self._last_stt_ms}ms passes=0")
            self._set_verbatim_transcript(raw_quick or quick)
            return quick, quick_conf or None

        # Para fala conversacional clara, uma hipotese FINAL com confianca muito
        # alta ja e boa o bastante. Frases medianas continuam no Whisper.
        if (
            quick and self._last_live_has_final
            and quick_conf >= self.LIVE_FINAL_BYPASS_CONF
            and len(self._normalize(quick)) >= 4
            and not self._has_unsupported_script(quick)
        ):
            self._last_consensus_score = quick_conf
            self._last_stt_ms = int(round((time.monotonic() - stt_started) * 1000))
            self._log("info", f"FAST-LANE fala final confiavel: {quick} conf={quick_conf:.2f}")
            self._log("info", f"LATENCIA voz: STT={self._last_stt_ms}ms passes=0")
            self._set_verbatim_transcript(raw_quick or quick)
            return quick, quick_conf

        conditioned_audio = self._condition_audio_for_stt(audio)
        # O Vosk ao vivo já processou exatamente esta fala durante a captura.
        # Repassar o buffer inteiro por outro KaldiRecognizer antes da GPU era
        # redundante e adicionava uma cauda perceptível em frases longas. Só
        # fazemos a passagem offline quando não existe hipótese ao vivo útil.
        raw_vosk_quick = raw_quick
        vosk_quick = quick
        if not quick or quick_conf < 0.28:
            try:
                raw_vosk_quick = self._transcribe_vosk(conditioned_audio)
                vosk_quick = normalize_command(self._postprocess_transcript(raw_vosk_quick))
                vosk_quick = self._repair_mixed_language_app_entity(vosk_quick)
                vosk_quick = self._validate_transcript(vosk_quick, None, relaxed=True)
            except Exception:
                vosk_quick = quick or ""
        else:
            self._log("info", f"STT: reutilizando hipótese Vosk ao vivo ({quick_conf:.2f}); passagem offline dispensada")

        try:
            vosk_safe = bool(vosk_quick and self._is_fast_safe_local_command(vosk_quick))
            vosk_search = bool(
                vosk_quick and quick_conf >= 0.55 and self._is_reversible_browser_search(vosk_quick)
            )
            if vosk_quick and (vosk_safe or vosk_search):
                agree = bool(quick and self._normalize(quick) == self._normalize(vosk_quick))
                vosk_threshold = self._fast_lane_min_confidence(vosk_quick) if vosk_safe else self.FAST_LANE_SEARCH_CONF
                effective_conf = quick_conf if quick_conf > 0 else (0.74 if agree else 0.0)
                if (agree and effective_conf >= min(0.62, vosk_threshold)) or effective_conf >= vosk_threshold:
                    self._last_consensus_score = 1.0
                    self._last_stt_ms = int(round((time.monotonic() - stt_started) * 1000))
                    self._log("info", f"FAST-LANE Vosk final: {vosk_quick} agree={int(agree)} conf={effective_conf:.2f}")
                    self._log("info", f"LATENCIA voz: STT={self._last_stt_ms}ms passes=0")
                    self._set_verbatim_transcript(raw_vosk_quick or raw_quick or vosk_quick)
                    return vosk_quick, quick_conf or None
        except Exception:
            pass

        prompt_a = (
            "Transcreva fielmente a fala em português do Brasil. Use o contexto da frase para escolher a grafia "
            "correta de palavras comuns quando o áudio produzir homófonos ou sílabas cortadas, sem inventar conteúdo. "
            "A fala pode conter nomes próprios, marcas, jogos, aplicativos e termos em inglês; preserve a grafia desses nomes. "
            "Não complete frases, não acrescente palavras e não transforme conversa em comando."
        )

        try:
            model = self._load_whisper_model()
            # faster-whisper aceita waveform float32 16 kHz diretamente.
            waveform = self._np.frombuffer(conditioned_audio, dtype=self._np.int16).astype(self._np.float32)
            if waveform.size:
                waveform /= 32768.0
            local_hint = self._preferred_local_language(raw_quick or raw_vosk_quick or quick or vosk_quick)
            first, conf_a, info_a = self._run_whisper_pass(
                model, waveform, beam_size=self.WHISPER_BEAM_SIZE, prompt=prompt_a, language_override=local_hint
            )
            self._recognition_passes = 1
            detected = self._detected_whisper_language(info_a) or local_hint
            self._last_detected_language = detected
            if detected in {"pt", "en"}:
                self._recent_stt_language = detected

            # Build 12 STT: o fallback local escolhe explicitamente pt/en para
            # falas curtas. Isso evita detectar ru/pl/it e repetir a mesma fala.
            # O guard abaixo permanece apenas para backends que ainda retornem
            # um codigo inesperado apesar do language_override.

            # Build 10: auto só é árbitro entre português e inglês. Uma hipótese
            # detectada como ru/zh/pl/etc. não é passada para o diálogo. Repassa
            # a MESMA fala forçando pt; isso acontece apenas quando o detector
            # saiu do par permitido, portanto não dobra a latência normal.
            guarded_mode = self.WHISPER_LANGUAGE in {"pt-en", "bilingual", "pt+en"}
            foreign_code = bool(detected and detected not in {"pt", "en"})
            bad_script = self._has_unsupported_script(first)
            plausible_latin = bool(
                guarded_mode and foreign_code and not bad_script
                and (
                    self._looks_like_guarded_pt_en_latin(first)
                    or self._looks_like_local_intent_candidate(first)
                )
            )
            if plausible_latin:
                self._last_detected_language = "pt-en-guarded"
                self._log(
                    "info",
                    f"STT PT-EN guard: código '{detected}' ignorado; texto latino plausível aceito sem segunda passagem.",
                )
            elif guarded_mode and (foreign_code or bad_script):
                self._log(
                    "info",
                    f"STT PT-EN guard: hipótese '{detected or 'script'}' rejeitada; refazendo em pt-BR.",
                )
                pt_first, pt_conf, pt_info = self._run_whisper_pass(
                    model, waveform, beam_size=1, prompt=prompt_a, language_override="pt"
                )
                self._recognition_passes = 2
                if pt_first and not self._has_unsupported_script(pt_first):
                    first, conf_a, info_a = pt_first, pt_conf, pt_info
                    detected = "pt"
                    self._last_detected_language = "pt"
                else:
                    first = vosk_quick or quick or ""
                    conf_a = quick_conf or None
                    detected = "pt-fallback"
                    self._last_detected_language = detected

            first_valid = self._validate_transcript(first, conf_a, relaxed=True)
            if first_valid and not (guarded_mode and self._has_unsupported_script(first_valid)):
                first_valid = normalize_command(self._postprocess_transcript(first_valid))
                first_valid = self._repair_mixed_language_app_entity(first_valid)
                quality_a = self._transcript_quality(first_valid, conf_a)
                # Melhor uma transcricao plausivel em ~1 passe que esperar 2 passes
                # de 4-9 s. Acoes perigosas ainda pedem confirmacao na GUI.
                if quality_a >= 0.44 or (conf_a is not None and conf_a >= -1.55):
                    self._last_consensus_score = 1.0
                    self._set_verbatim_transcript(self._last_raw_stt_text or first_valid)
                    interpreted = self._fuse_local_interpretation(first_valid, quick, vosk_quick, quick_conf)
                    return interpreted, conf_a

            if self.WHISPER_SECOND_PASS:
                second, conf_b, _ = self._run_whisper_pass(
                    model, waveform, beam_size=2,
                    prompt=("Transcreva literalmente. A fala pode misturar pt-BR com nomes em inglês. "
                            "Preserve marcas e nomes próprios; não invente nem complete palavras."),
                )
                self._recognition_passes = 2
                second_valid = self._validate_transcript(second, conf_b, relaxed=True)
                if second_valid:
                    final_second = normalize_command(self._postprocess_transcript(second_valid))
                    self._set_verbatim_transcript(self._last_raw_stt_text or second_valid)
                    return final_second, conf_b

            fallback = vosk_quick or quick
            if fallback:
                self._set_verbatim_transcript(raw_vosk_quick or raw_quick or fallback)
            return (fallback, quick_conf or None) if fallback else ("", conf_a)

        except Exception as exc:
            self._log("warning", f"Whisper indisponivel; usando Vosk fallback: {exc}")
            fallback = vosk_quick or quick or self._postprocess_transcript(self._transcribe_vosk(conditioned_audio))
            fallback = self._validate_transcript(fallback, None, relaxed=True)
            return (normalize_command(self._postprocess_transcript(fallback)), None) if fallback else ("", None)
        finally:
            self._last_stt_ms = int(round((time.monotonic() - stt_started) * 1000))
            self._last_whisper_total_ms = self._last_stt_ms if self._recognition_passes else None
            if self._reliability is not None:
                try:
                    self._reliability.duration(
                        "stt",
                        self._last_stt_ms,
                        backend=self._stt_backend,
                        passes=self._recognition_passes,
                    )
                except Exception:
                    pass
            self._log("info", f"LATENCIA voz: STT={self._last_stt_ms}ms passes={self._recognition_passes}")

    def _transcribe_vosk(self, audio: bytes) -> str:
        if not self._vosk_model:
            return ""

        recognizer = self._vosk.KaldiRecognizer(
            self._vosk_model,
            self.SAMPLE_RATE,
        )
        recognizer.AcceptWaveform(audio)

        try:
            return str(
                json.loads(
                    recognizer.FinalResult()
                ).get("text", "")
            ).strip()
        except Exception:
            return ""

    def _strip_wake_prefix(self, text: str) -> str:
        result = str(text or "").strip()
        normalized = self._normalize(result)

        # Only after a real wake event, tolerate phonetic renderings of
        # "Oi Jarvis" without changing the spelling of the remaining literal STT.
        if getattr(self, "_explicit_wake_turn", False):
            fuzzy_patterns = (
                r"^(?:oi|ei)[\s,.-]+(?:jarvis|jarves|jarbas|arvis|arvies)\b[\s,.:;-]*",
                r"^e[\s,.-]+a[iy][\s,.-]+(?:jarvis|jarves|jarbas|arvis|arvies)\b[\s,.:;-]*",
                r"^hoj[e\u00e9][\s,.-]+(?:jarvis|arvis|arvies)\b[\s,.:;-]*",
                r"^hoj[e\u00e9][\s,.-]+a[\s,.-]+revise\b[\s,.:;-]*",
                r"^oj[a\u00e1][\s,.-]+vim\b[\s,.:;-]*",
            )
            for pattern in fuzzy_patterns:
                updated = re.sub(pattern, "", result, count=1, flags=re.I).strip(" ,.!?:;")
                if updated != result.strip(" ,.!?:;"):
                    result = updated
                    normalized = self._normalize(result)
                    break

        for phrase in self.WAKE_PHRASES:
            target = self._normalize(phrase)

            if normalized.startswith(target):
                count = len(target.split())
                result = " ".join(result.split()[count:]).strip()
                break

        return result

    def _validate_transcript(
        self,
        text: str,
        confidence: Optional[float],
        relaxed: bool = False,
    ) -> str:
        value = " ".join(
            str(text or "").split()
        ).strip(" .,!?:;")

        value = self._strip_wake_prefix(value)

        if len(value) < 2 or len(value) > 500:
            return ""

        normalized = self._normalize(value)

        if any(
            pattern in normalized
            for pattern in self.HALLUCINATION_PATTERNS
        ):
            return ""

        if (
            confidence is not None
            and confidence < -1.45
            and not relaxed
        ):
            self._log(
                "warning",
                f"Transcrição rejeitada por baixa confiança: "
                f"{confidence:.2f} | {value}"
            )
            return ""

        words = normalized.split()

        if len(words) >= 6:
            unique_ratio = len(set(words)) / max(1, len(words))

            if unique_ratio < 0.28:
                return ""

        return value

    def _tts_pronunciation_overrides(self) -> dict[str, str]:
        cached = getattr(self, "_tts_pronunciation_cache", None)
        if isinstance(cached, dict):
            return cached
        mapping: dict[str, str] = {}
        path = self.data_dir / "tts_pronunciation.json"
        try:
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    for source, spoken in payload.items():
                        source = " ".join(str(source or "").split()).strip()
                        spoken = " ".join(str(spoken or "").split()).strip()
                        if 1 <= len(source) <= 48 and 1 <= len(spoken) <= 96:
                            mapping[source] = spoken
        except Exception as exc:
            self._log("warning", f"Dicionario TTS ignorado: {exc}")
        self._tts_pronunciation_cache = mapping
        return mapping

    def _normalize_tts_units(self, value: str) -> str:
        """Make common PC metrics sound natural without changing chat text."""
        value = re.sub(r"(?<=\d)\s*%", " por cento", value)
        value = re.sub(r"(?<=\d)\s*°\s*C\b", " graus Celsius", value, flags=re.I)
        units = {
            "GHz": "gigahertz", "MHz": "megahertz", "kHz": "quilohertz",
            "GB": "gigabytes", "MB": "megabytes", "TB": "terabytes",
            "ms": "milissegundos",
        }
        for unit, spoken in units.items():
            value = re.sub(rf"(?<=\d)\s*{re.escape(unit)}\b", f" {spoken}", value, flags=re.I)
        return value

    def _clean_tts_text(self, text: str) -> str:
        value = str(text or "")
        value = re.sub(r"```.*?```", " ", value, flags=re.S)
        value = re.sub(r"https?://\S+", " ", value)
        value = re.sub(r"[#*_`>|]+", " ", value)
        value = self._normalize_tts_units(value)
        for source, spoken in self._tts_pronunciation_overrides().items():
            value = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", spoken, value, flags=re.I)
        value = re.sub(r"\s+", " ", value).strip()

        if len(value) > 36000:
            value = value[:36000].rstrip()
        return value

    def _split_tts_chunks(self, text: str, max_chars: int = 430):
        """Divide long responses at natural speech boundaries."""
        clean = self._clean_tts_text(text)
        if not clean:
            return []
        sentences = re.split(r"(?<=[.!?;:])\s+|\n+", clean)
        chunks = []
        current = ""

        def push_long(part):
            part = part.strip()
            while len(part) > max_chars:
                cut = part.rfind(" ", 0, max_chars + 1)
                if cut < int(max_chars * 0.55):
                    cut = max_chars
                chunks.append(part[:cut].strip())
                part = part[cut:].strip()
            return part

        for sentence in sentences:
            sentence = push_long(sentence.strip())
            if not sentence:
                continue
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = sentence
        if current:
            chunks.append(current)
        return [chunk for chunk in chunks if chunk]

    @staticmethod
    def _tts_rate_with_delta(rate: str, delta: int) -> str:
        match = re.fullmatch(r"([+-]?)(\d+)%", str(rate or "").strip())
        if not match:
            return rate
        value = int(match.group(2)) * (-1 if match.group(1) == "-" else 1)
        value = max(-30, min(value + int(delta), 35))
        return f"{value:+d}%"

    def _tts_prosody(self, text: str):
        """Stable identity plus small rate changes based on utterance shape."""
        if not self.TTS_DYNAMIC_PROSODY:
            return self.TTS_RATE, self.TTS_PITCH
        clean = " ".join(str(text or "").split()).strip()
        words = len(clean.split())
        delta = 0
        if words <= 5 and len(clean) <= 52:
            delta = 2
        elif len(clean) >= 280 or words >= 48:
            delta = -2
        if re.search(r"\b(?:atencao|atenção|cuidado|erro|falha|problema|alerta)\b", clean, flags=re.I):
            delta = min(delta, -3)
        return self._tts_rate_with_delta(self.TTS_RATE, delta), self.TTS_PITCH

    def _maintain_tts_cache(self) -> None:
        """Bound generated voice cache so long-running installs do not bloat."""
        try:
            files = [p for p in self.tts_cache_dir.glob("*.mp3") if p.is_file()]
            total = sum(p.stat().st_size for p in files)
            max_bytes = int(self.TTS_CACHE_MAX_MB) * 1024 * 1024
            if len(files) <= self.TTS_CACHE_MAX_FILES and total <= max_bytes:
                return
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            keep = []
            kept_bytes = 0
            for item in files:
                size = item.stat().st_size
                if len(keep) < self.TTS_CACHE_MAX_FILES and kept_bytes + size <= max_bytes:
                    keep.append(item)
                    kept_bytes += size
                    continue
                # Never touch audio synthesized in the last ten minutes.
                if time.time() - item.stat().st_mtime < 600:
                    continue
                try:
                    item.unlink()
                    timing = self._tts_timing_path(item)
                    if timing.exists():
                        timing.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    def _tts_cache_path(self, text: str) -> Path:
        rate, pitch = self._tts_prosody(text)
        fingerprint = hashlib.sha1(
            (self.TTS_VOICE + "|" + rate + "|" + pitch + "|" + self.TTS_VOLUME + "|" + text).encode("utf-8")
        ).hexdigest()
        return self.tts_cache_dir / f"{fingerprint}.mp3"

    def _tts_timing_path(self, media_path: Path) -> Path:
        return media_path.with_suffix(".timing.json")

    def _tts_key_lock(self, media_path: Path):
        key = str(media_path)
        with self._tts_lock_guard:
            lock = self._tts_key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._tts_key_locks[key] = lock
            return lock

    def _prewarm_ack(self):
        # Respostas locais comuns ficam em cache antes do primeiro comando. As
        # mais frequentes vêm primeiro para o JARVIS já soar instantâneo mesmo se
        # o usuário falar poucos segundos depois de abrir o programa.
        phrases = [
            "Abrindo.", "Pronto.", "Feito.", "Pesquisando.", "Pausei.",
            "Certo.", "Continuando.", "Minimizei.", "Maximizei.", "Voltei.",
            "Modo automático.", "Modo conversa.", "Modo comando.",
            "Modo gamer ativado.", "Tela cheia.",
            "Repete?", "Pode falar.",
            "Qual aplicativo ou janela você quer usar?",
            "Qual aplicativo?",
            "Para qual monitor você quer mover a janela?",
            "Para qual monitor?",
            "Não encontrei esse aplicativo.",
            "O que você quer pesquisar?",
            "Entendi. Registrei que a última ação não funcionou como esperado.",
            "Cancelado.",
        ]
        if self.VOICE_ACK:
            phrases.insert(0, "Sim?")
        for phrase in phrases:
            if self._stop_event.is_set():
                return
            try:
                self._synthesize_edge(phrase)
            except Exception:
                continue

    def _synthesize_edge(self, text: str) -> Path:
        """Gera MP3 + WordBoundary para legenda sincronizada."""
        path = self._tts_cache_path(text)
        timing_path = self._tts_timing_path(path)

        def cache_ready():
            if not (path.exists() and path.stat().st_size > 1024):
                return False
            if self.CAPTION_WORD_SYNC and getattr(self, "_caption_boundary_supported", True):
                try:
                    return timing_path.exists() and timing_path.stat().st_size >= 2
                except Exception:
                    return False
            return True

        if cache_ready():
            return path

        import edge_tts

        lock = self._tts_key_lock(path)
        with lock:
            if cache_ready():
                return path

            unique = f"{threading.get_ident()}_{int(time.time() * 1000)}"
            temp = path.with_name(path.stem + f".{unique}.tmp.mp3")
            temp_timing = timing_path.with_name(
                timing_path.stem + f".{unique}.tmp.json"
            )

            rate, pitch = self._tts_prosody(text)

            async def create_with_voice(voice_name: str):
                boundaries = []
                communicate_kwargs = {
                    "text": text,
                    "voice": voice_name,
                    "rate": rate,
                    "pitch": pitch,
                    "volume": self.TTS_VOLUME,
                }
                if self.CAPTION_WORD_SYNC and getattr(self, "_caption_boundary_supported", True):
                    communicate_kwargs["boundary"] = "WordBoundary"
                try:
                    communicate = edge_tts.Communicate(**communicate_kwargs)
                except TypeError as exc:
                    if "boundary" not in communicate_kwargs:
                        raise
                    communicate_kwargs.pop("boundary", None)
                    self._caption_boundary_supported = False
                    if not self._caption_boundary_warned:
                        self._caption_boundary_warned = True
                        self._log("warning", f"edge-tts sem WordBoundary; usando legenda estavel: {exc}")
                    communicate = edge_tts.Communicate(**communicate_kwargs)

                with open(temp, "wb") as media:
                    async for chunk in communicate.stream():
                        kind = chunk.get("type")
                        if kind == "audio":
                            media.write(chunk.get("data") or b"")
                        elif kind in ("WordBoundary", "SentenceBoundary"):
                            boundaries.append({
                                "type": kind,
                                "offset": int(chunk.get("offset") or 0),
                                "duration": int(chunk.get("duration") or 0),
                                "text": str(chunk.get("text") or ""),
                            })
                return boundaries

            if self.TTS_VOICE_LOCK:
                voices = [self.TTS_VOICE]
            else:
                ordered = []
                if self._active_tts_voice:
                    ordered.append(self._active_tts_voice)
                for item in (self.TTS_VOICE, *self.TTS_FALLBACK_VOICES):
                    if item not in ordered:
                        ordered.append(item)
                voices = ordered
            last_exc = None
            boundaries = []

            for voice_name in voices:
                try:
                    if temp.exists():
                        temp.unlink(missing_ok=True)
                    boundaries = asyncio.run(create_with_voice(voice_name))
                    if temp.exists() and temp.stat().st_size > 1024:
                        previous = self._active_tts_voice
                        self._active_tts_voice = self.TTS_VOICE if self.TTS_VOICE_LOCK else voice_name
                        if not self.TTS_VOICE_LOCK:
                            if voice_name != self.TTS_VOICE and voice_name not in self._tts_voice_warned:
                                self._tts_voice_warned.add(voice_name)
                                self._log("warning", f"Voz principal indisponivel; fixando {voice_name} nesta sessao.")
                            elif previous and previous != voice_name:
                                self._log("info", f"TTS mudou para voz operacional: {voice_name}")
                        break
                except Exception as exc:
                    last_exc = exc
                    if not self.TTS_VOICE_LOCK and self._active_tts_voice == voice_name:
                        self._active_tts_voice = None
                    try:
                        temp.unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                raise VoiceEngineError(
                    f"O TTS neural nao gerou audio valido: {last_exc}"
                )

            try:
                temp_timing.write_text(
                    json.dumps(boundaries, ensure_ascii=False),
                    encoding="utf-8",
                )
                temp_timing.replace(timing_path)
            except Exception:
                try:
                    temp_timing.unlink(missing_ok=True)
                except Exception:
                    pass

            temp.replace(path)
            return path

    def _init_mixer(self):
        if self._mixer_ready:
            return

        import pygame

        self._pygame = pygame
        pygame.mixer.init()
        self._mixer_ready = True

    def _sanitize_caption(self, text: str, limit: int = 520) -> str:
        """Single UTF-8/NFC sanitizer shared with the Qt overlay."""
        return sanitize_text(text, limit=limit)

    def _play_mp3(self, path: Path, caption_text: str = ""):
        """Toca áudio e envia legenda de palavras sincronizada, se disponível."""
        self._init_mixer()
        self._tts_cancel_event.clear()

        timings = []
        if self.CAPTION_WORD_SYNC:
            try:
                timing_path = self._tts_timing_path(path)
                if timing_path.exists():
                    timings = json.loads(timing_path.read_text(encoding="utf-8"))
                    timings = [
                        item for item in timings
                        if item.get("type") == "WordBoundary" and item.get("text")
                    ]
            except Exception:
                timings = []

        self._pygame.mixer.music.load(str(path))
        started_at = time.monotonic()
        self._pygame.mixer.music.play()

        timing_index = 0
        rolling_words = deque(maxlen=18)
        last_caption_emit = 0.0
        caption_text = self._sanitize_caption(caption_text)

        if self.on_caption and caption_text:
            try:
                self.on_caption(caption_text)
            except Exception:
                pass

        while (
            self._pygame.mixer.music.get_busy()
            and not self._stop_event.is_set()
            and not self._tts_cancel_event.is_set()
        ):
            elapsed = time.monotonic() - started_at

            if timings and self.on_caption:
                changed = False
                while timing_index < len(timings):
                    item = timings[timing_index]
                    # edge-tts offsets are in 100-ns ticks.
                    offset_seconds = float(item.get("offset") or 0) / 10_000_000.0
                    if offset_seconds > elapsed + 0.025:
                        break
                    word = self._sanitize_caption(str(item.get("text") or ""), limit=64)
                    if word:
                        # Evita boundary duplicado/flicker.
                        if not rolling_words or word.casefold() != str(rolling_words[-1]).casefold():
                            rolling_words.append(word)
                            changed = True
                    timing_index += 1

                now = time.monotonic()
                if changed and now - last_caption_emit >= 0.065:
                    last_caption_emit = now
                    try:
                        self.on_caption(self._sanitize_caption(" ".join(rolling_words)))
                    except Exception:
                        pass

            time.sleep(0.018)

        if self._tts_cancel_event.is_set():
            try:
                self._pygame.mixer.music.stop()
            except Exception:
                pass

    def _speak_fallback(self, text: str):
        """Local fallback that never changes JARVIS to another identity silently."""
        import pyttsx3

        engine = pyttsx3.init()
        self._fallback_engine = engine
        self._tts_cancel_event.clear()
        male_candidates = []
        pt_male_candidates = []

        try:
            for voice in engine.getProperty("voices"):
                descriptor = (
                    f"{getattr(voice, 'name', '')} "
                    f"{getattr(voice, 'id', '')} "
                    f"{getattr(voice, 'languages', '')}"
                ).lower()
                gender = str(getattr(voice, "gender", "") or "").lower()
                portuguese = any(token in descriptor for token in ("portugu", "brazil", "pt-br", "pt_br"))
                male = (
                    gender.startswith("male")
                    or any(token in descriptor for token in (
                        "antonio", "macerio", "fabio", "donato", "daniel",
                        "humberto", "julio", "nicolau", "valerio", " male", "mascul"
                    ))
                )
                if male:
                    male_candidates.append(voice.id)
                    if portuguese:
                        pt_male_candidates.append(voice.id)

            all_voices = list(engine.getProperty("voices") or [])
            selected = (pt_male_candidates or male_candidates or [None])[0]
            self._fallback_emergency_voice = False
            if selected:
                engine.setProperty("voice", selected)
            elif all_voices:
                # Último recurso de confiabilidade: é melhor falar com a voz
                # padrão do Windows do que ficar completamente mudo. Isso só
                # acontece depois de todas as vozes masculinas Edge falharem.
                self._fallback_emergency_voice = True
                default_id = getattr(all_voices[0], "id", None)
                if default_id:
                    engine.setProperty("voice", default_id)
                self._log("warning", "TTS fallback de emergência: nenhuma voz local masculina; usando voz padrão do Windows para não ficar mudo.")
            else:
                raise VoiceEngineError("Nenhuma voz TTS local instalada no Windows.")
        except Exception:
            self._fallback_engine = None
            try:
                engine.stop()
            except Exception:
                pass
            raise

        engine.setProperty("rate", 184)
        engine.setProperty("volume", 0.95)
        if not self._tts_cancel_event.is_set():
            engine.say(text)
            engine.runAndWait()

        self._fallback_engine = None

    def _locked_cached_fallback(self, requested_text: str):
        """Retorna um ACK já cacheado na MESMA voz neural, sem sintetizar.

        Usado somente em respostas locais rápidas quando a rede falha. Assim o
        JARVIS pode dizer "Pronto" com a identidade correta em vez de trocar para
        SAPI/pyttsx3. Conversas completas não usam este atalho, pois perderiam
        conteúdo semântico.
        """
        requested_key = self._normalize(requested_text)
        for phrase in ("Pronto.", "Certo.", "Feito.", "Abrindo."):
            if self._normalize(phrase) == requested_key:
                continue
            try:
                path = self._tts_cache_path(phrase)
                if path.exists() and path.stat().st_size > 1024:
                    return path, phrase
            except Exception:
                continue
        return None, ""

    def _tts_worker(self):
        """Playback contínuo com síntese antecipada dos próximos trechos."""
        while not self._stop_event.is_set():
            try:
                item = self._tts_queue.get(timeout=0.12)
            except queue.Empty:
                continue

            if item is None:
                return

            text = item.get("text", "")
            done = item.get("done")
            future = item.get("future")
            command_origin = float(item.get("command_origin", 0.0) or 0.0)
            post_delay = float(item.get("post_delay", 0.0) or 0.0)
            is_prompt = bool(item.get("prompt"))
            is_fast = bool(item.get("fast"))

            if not text:
                if done:
                    done.set()
                continue

            self._tts_cancel_event.clear()
            self._speaking.set()
            self._tts_started_at = time.monotonic()
            self._current_tts_text = str(text or "")
            # Build 7: prompts de protocolo ("Sim?", "Repete?") nunca
            # aparecem como OUVINDO enquanto o proprio JARVIS ainda esta falando.
            # A captura pode estar drenando o driver, mas a janela de fala do
            # usuario so abre depois do evento `done`.
            if is_prompt:
                self._state("FALANDO", text)
            elif self._mic_capture_active.is_set():
                self._state(self._listening_visual_state, "Microfone aberto")
            else:
                self._state("FALANDO", text)

            if self.on_tts_start:
                try:
                    self.on_tts_start(text)
                except Exception:
                    pass
            try:
                path = None
                if is_prompt:
                    # Com identidade travada, prompt de protocolo tambem usa a
                    # MESMA voz neural. Como os prompts comuns sao pre-aquecidos,
                    # isso normalmente e leitura imediata de cache.
                    cached_prompt = self._tts_cache_path(text)
                    if cached_prompt.exists() and cached_prompt.stat().st_size > 1024:
                        path = cached_prompt
                    elif self.TTS_VOICE_LOCK:
                        try:
                            path = future.result(timeout=1.40) if future is not None else self._synthesize_edge(text)
                        except concurrent.futures.TimeoutError:
                            raise RuntimeError("__JARVIS_LOCKED_TTS_TIMEOUT__")
                    else:
                        raise RuntimeError("__JARVIS_FAST_PROTOCOL_PROMPT__")
                elif future is not None:
                    try:
                        # Resposta local curta: Edge tem uma janela pequena. Se a
                        # rede atrasar, preferimos começar a falar com SAPI local
                        # e deixar o future terminar apenas para aquecer o cache.
                        timeout = 0.48 if (is_fast and len(text) <= 100) else 35
                        path = future.result(timeout=timeout)
                    except concurrent.futures.TimeoutError:
                        if is_fast and len(text) <= 100:
                            raise RuntimeError("__JARVIS_FAST_SHORT_TTS__")
                        path = None
                    except Exception:
                        path = None
                if path is None:
                    path = self._synthesize_edge(text)

                if command_origin and self._last_tts_first_audio_ms is None:
                    self._last_tts_first_audio_ms = int(round((time.monotonic() - command_origin) * 1000.0))
                    self._log(
                        "info",
                        f"LATENCIA voz: comando->filaTTS={self._last_voice_response_queue_ms or '-'}ms "
                        f"comando->audio={self._last_tts_first_audio_ms}ms",
                    )
                    if abs(float(self._last_command_dispatch_at or 0.0) - command_origin) < 0.001:
                        self._last_command_dispatch_at = 0.0

                self._play_mp3(path, caption_text=text)

                if not self._tts_cancel_event.is_set():
                    self.tts_last_ok = True
                    self.tts_provider = "edge-tts"
                    self.tts_last_error = ""

            except Exception as exc:
                protocol_fallback = str(exc) == "__JARVIS_FAST_PROTOCOL_PROMPT__"
                fast_short_fallback = str(exc) == "__JARVIS_FAST_SHORT_TTS__"
                locked_timeout = str(exc) == "__JARVIS_LOCKED_TTS_TIMEOUT__"
                if not protocol_fallback and not fast_short_fallback and not locked_timeout:
                    self._log("warning", f"TTS neural indisponivel: {exc}")
                try:
                    # Se uma resposta local curta atrasou na rede, use um ACK
                    # já cacheado na MESMA voz imediatamente. O future continua
                    # sintetizando em segundo plano e aquece o cache para a
                    # próxima vez; não esperamos mais 1.25 s sem necessidade.
                    if fast_short_fallback and self.TTS_VOICE_LOCK:
                        cached_path, cached_text = self._locked_cached_fallback(text)
                        if cached_path is not None:
                            if command_origin and self._last_tts_first_audio_ms is None:
                                self._last_tts_first_audio_ms = int(round((time.monotonic() - command_origin) * 1000.0))
                                self._log(
                                    "info",
                                    f"LATENCIA voz: comando->audio={self._last_tts_first_audio_ms}ms "
                                    "backend=edge-locked-cache-fast",
                                )
                            self._play_mp3(cached_path, caption_text=cached_text)
                            if not self._tts_cancel_event.is_set():
                                self.tts_last_ok = True
                                self.tts_provider = "edge-tts-locked-cache-fast"
                                self.tts_last_error = ""
                            continue

                    # Build 12 R2: antes de cogitar qualquer fallback, da uma
                    # segunda janela curta para a MESMA future/voz neural. Isso
                    # elimina mudancas de timbre em respostas curtas.
                    if (fast_short_fallback or locked_timeout) and future is not None:
                        try:
                            late_path = future.result(timeout=1.25)
                        except Exception:
                            late_path = None
                        if late_path is not None:
                            if command_origin and self._last_tts_first_audio_ms is None:
                                self._last_tts_first_audio_ms = int(round((time.monotonic() - command_origin) * 1000.0))
                                self._log("info", f"LATENCIA voz: comando->audio={self._last_tts_first_audio_ms}ms backend=edge-locked-late")
                            self._play_mp3(late_path, caption_text=text)
                            if not self._tts_cancel_event.is_set():
                                self.tts_last_ok = True
                                self.tts_provider = "edge-tts-locked-late" if self.TTS_VOICE_LOCK else "edge-tts-male-late"
                                self.tts_last_error = ""
                            continue

                    if self.on_caption:
                        try:
                            self.on_caption(text)
                        except Exception:
                            pass

                    # Identidade forte: por padrao e preferivel ficar sem audio
                    # naquele turno do que trocar a voz do JARVIS. A resposta em
                    # texto/legenda continua disponivel e o proximo turno tenta
                    # a voz principal novamente.
                    if self.TTS_VOICE_LOCK and not self.TTS_ALLOW_LOCAL_FALLBACK:
                        if is_fast:
                            cached_path, cached_text = self._locked_cached_fallback(text)
                            if cached_path is not None:
                                if command_origin and self._last_tts_first_audio_ms is None:
                                    self._last_tts_first_audio_ms = int(round((time.monotonic() - command_origin) * 1000.0))
                                    self._log(
                                        "info",
                                        f"LATENCIA voz: comando->audio={self._last_tts_first_audio_ms}ms "
                                        "backend=edge-locked-cache",
                                    )
                                self._play_mp3(cached_path, caption_text=cached_text)
                                if not self._tts_cancel_event.is_set():
                                    self.tts_last_ok = True
                                    self.tts_provider = "edge-tts-locked-cache"
                                    self.tts_last_error = ""
                                continue
                        self.tts_last_ok = False
                        self.tts_provider = "edge-tts-locked"
                        self.tts_last_error = str(exc)
                        self._log("warning", "TTS preservou a identidade: fallback com outra voz foi bloqueado.")
                        continue

                    if command_origin and self._last_tts_first_audio_ms is None:
                        self._last_tts_first_audio_ms = int(round((time.monotonic() - command_origin) * 1000.0))
                        self._log(
                            "info",
                            f"LATENCIA voz: comando->filaTTS={self._last_voice_response_queue_ms or '-'}ms "
                            f"comando->audio={self._last_tts_first_audio_ms}ms backend=local-fast",
                        )
                        if abs(float(self._last_command_dispatch_at or 0.0) - command_origin) < 0.001:
                            self._last_command_dispatch_at = 0.0
                    self._speak_fallback(text)
                    if not self._tts_cancel_event.is_set():
                        self.tts_last_ok = True
                        emergency_voice = bool(getattr(self, "_fallback_emergency_voice", False))
                        self.tts_provider = (
                            "pyttsx3-emergency" if emergency_voice
                            else "pyttsx3-protocol" if protocol_fallback
                            else "pyttsx3-fast" if fast_short_fallback
                            else "pyttsx3"
                        )
                        self.tts_last_error = ""
                except Exception as fallback_exc:
                    self.last_error = str(fallback_exc)
                    self.tts_last_ok = False
                    self.tts_provider = ""
                    self.tts_last_error = str(fallback_exc)
                    self._log("error", f"Falha de TTS: {fallback_exc}")

            finally:
                if done:
                    try:
                        done.set()
                    except Exception:
                        pass

                if post_delay and not self._tts_cancel_event.is_set():
                    time.sleep(min(post_delay, 0.08))

                # V6: janela curta de encadeamento. O streaming pode entregar o
                # próximo trecho alguns ms depois; não emitimos TTS_END no meio da
                # resposta, evitando FALANDO -> OUVINDO e pausas artificiais.
                if self._tts_queue.empty():
                    deadline = time.monotonic() + max(0.04, self.TTS_CHAIN_GRACE)
                    while (
                        self._tts_queue.empty()
                        and not self._stop_event.is_set()
                        and not self._tts_cancel_event.is_set()
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)

                if self._tts_queue.empty():
                    self._speaking.clear()
                    self._current_tts_text = ""
                    self._last_tts_end_at = time.monotonic()
                    if self.on_tts_end:
                        try:
                            self.on_tts_end()
                        except Exception:
                            pass
                    if not self._assistant_busy.is_set() and not self._listening_session.is_set():
                        pass
