"""JARVIS - Deepgram Flux streaming backend.

Primary online STT/turn-detection backend for the JARVIS voice assistant.
Uses the raw Deepgram Listen v2 WebSocket so Flux multilingual events are
parsed explicitly. Whisper/Vosk remain available in voice_engine.py as local
fallbacks when the API key, network or service is unavailable.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlencode

try:
    from dotenv import load_dotenv
except Exception:  # optional at import time; installer provides it
    load_dotenv = None


DEFAULT_KEYTERMS = (
    "JARVIS",
    "Opera GX",
    "Opera",
    "OBS Studio",
    "Photoshop",
    "Illustrator",
    "CorelDRAW",
    "Revo Uninstaller",
    "ChatGPT",
    "Spotify",
    "YouTube",
    "WhatsApp",
    "Microsoft Store",
    "Paint",
    "Bloco de Notas",
    "Explorador de Arquivos",
    "BloodStrike",
    "Blood Strike",
    "Discord",
    "Crunchyroll",
    "Comercial",
    "calibrar microfone",
    "minimizar",
    "maximizar",
    "restaurar",
    "volume",
    "próxima música",
    "música anterior",
    # PT-BR/Nordeste: poucos termos distintivos para ajudar o STT sem
    # contaminar a transcrição com um dicionário gigantesco.
    "abrir",
    "fechar",
    "pesquisar",
    "procurar",
    "monitor",
    "tela",
    "simbora",
    "oxente",
    "visse",
    "bota",
)


def _load_env(project_dir: Path) -> None:
    if load_dotenv is None:
        return
    try:
        load_dotenv(project_dir / ".env", override=False)
    except Exception:
        pass


def get_api_key(project_dir: str | Path) -> str:
    root = Path(project_dir)
    _load_env(root)
    return str(os.getenv("DEEPGRAM_API_KEY") or "").strip()


def _key_hash(api_key: str) -> str:
    value = str(api_key or "").encode("utf-8", errors="ignore")
    return hashlib.sha256(value).hexdigest() if value else ""


def _state_path(project_dir: str | Path) -> Path:
    root = Path(project_dir)
    path = root / "data" / "deepgram_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_key_state(project_dir: str | Path) -> dict:
    api_key = get_api_key(project_dir)
    current_hash = _key_hash(api_key)
    payload = {}
    try:
        path = _state_path(project_dir)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload = raw
    except Exception:
        payload = {}
    invalid_for_current = bool(
        api_key
        and payload.get("invalid_auth")
        and payload.get("key_hash") == current_hash
    )
    return {
        "configured": bool(api_key),
        "key_hash": current_hash,
        "invalid_auth": invalid_for_current,
        "last_error": str(payload.get("last_error") or "") if invalid_for_current else "",
        "checked_at": payload.get("checked_at"),
    }


def mark_key_invalid(project_dir: str | Path, api_key: str, error: str = "") -> None:
    if not api_key:
        return
    payload = {
        "key_hash": _key_hash(api_key),
        "invalid_auth": True,
        "last_error": str(error or "Falha de autenticação"),
        "checked_at": time.time(),
    }
    try:
        path = _state_path(project_dir)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def mark_key_valid(project_dir: str | Path, api_key: str) -> None:
    if not api_key:
        return
    payload = {
        "key_hash": _key_hash(api_key),
        "invalid_auth": False,
        "last_error": "",
        "checked_at": time.time(),
    }
    try:
        path = _state_path(project_dir)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def is_configured(project_dir: str | Path) -> bool:
    state = get_key_state(project_dir)
    return bool(state.get("configured") and not state.get("invalid_auth"))


def _clean_term(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) < 2 or len(text) > 72:
        return ""
    return text


def load_project_keyterms(project_dir: str | Path, limit: int = 100) -> list[str]:
    """Build Flux keyterms from JARVIS's real app cache/index plus core phrases."""
    root = Path(project_dir)
    items: list[str] = list(DEFAULT_KEYTERMS)

    def add(value: object) -> None:
        term = _clean_term(value)
        if term:
            items.append(term)

    # query -> target cache
    try:
        path = root / "app_cache.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in data:
                    if not str(key).startswith("_"):
                        add(key)
    except Exception:
        pass

    # taught aliases
    try:
        path = root / "data" / "app_aliases.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for alias, payload in data.items():
                    add(alias)
                    if isinstance(payload, dict):
                        add(payload.get("display_name"))
    except Exception:
        pass

    # indexed applications
    try:
        path = root / "data" / "app_index.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for payload in data:
                    if isinstance(payload, dict):
                        add(payload.get("label"))
    except Exception:
        pass

    seen = set()
    result = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= max(1, min(int(limit), 100)):
            break
    return result


@dataclass
class FluxResult:
    transcript: str = ""
    word_confidence: float = 0.0
    eot_confidence: float = 0.0
    event: str = ""
    languages: tuple[str, ...] = ()
    words: tuple[tuple[str, float, float, float], ...] = ()
    received_at: float = 0.0
    audio_window_end: float = 0.0

    @property
    def low_confidence_words(self) -> tuple[tuple[str, float], ...]:
        return tuple((word, conf) for word, conf, _start, _end in self.words if conf < 0.72)


class DeepgramFluxSession:
    """One conversational turn over Deepgram Flux Listen v2.

    Audio may be fed immediately after start(); the class buffers 20 ms input
    into 80 ms network packets, matching Deepgram's recommended Flux chunk size.
    """

    def __init__(
        self,
        api_key: str,
        *,
        sample_rate: int = 16000,
        keyterms: Optional[Iterable[str]] = None,
        language_hint: str = "pt-BR",
        language_hints: Optional[Iterable[str]] = None,
        model: str = "flux-general-multi",
        eager_eot_threshold: float = 0.50,
        eot_threshold: float = 0.72,
        eot_timeout_ms: int = 2800,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self.api_key = str(api_key or "").strip()
        self.sample_rate = int(sample_rate)
        self.keyterms = list(keyterms or [])[:100]
        raw_hints = list(language_hints or [])
        if not raw_hints:
            raw_hints = [item.strip() for item in str(language_hint or "pt-BR").replace(";", ",").split(",") if item.strip()]
        seen_hints = set()
        self.language_hints = []
        for item in raw_hints:
            hint = str(item or "").strip()
            key = hint.casefold()
            if hint and key not in seen_hints:
                seen_hints.add(key)
                self.language_hints.append(hint)
        if not self.language_hints:
            self.language_hints = ["pt-BR", "en-US"]
        self.language_hint = self.language_hints[0]
        self.model = str(model or "flux-general-multi")
        self.eager_eot_threshold = float(eager_eot_threshold)
        self.eot_threshold = float(eot_threshold)
        self.eot_timeout_ms = max(500, min(int(eot_timeout_ms), 60000))
        self.logger = logger

        self.ready_event = threading.Event()
        self.start_of_turn_event = threading.Event()
        self.eager_event = threading.Event()
        self.end_event = threading.Event()
        self.error_event = threading.Event()
        self.closed_event = threading.Event()
        self.listen_updated_event = threading.Event()

        self.result = FluxResult()
        self.eager_transcript = ""
        self.update_transcript = ""
        self.last_error = ""
        self.connected_at = 0.0
        self.started_at = 0.0
        self.last_message_at = 0.0

        self._send_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=96)
        self._control_queue: queue.Queue[dict] = queue.Queue(maxsize=8)
        self._packet_buffer = bytearray()
        self._packet_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_requested = threading.Event()

        # 80 ms, mono linear16.
        self._packet_bytes = max(320, int(self.sample_rate * 2 * 0.080))

    def _log(self, level: str, message: str) -> None:
        if self.logger:
            try:
                self.logger(level, message)
            except Exception:
                pass

    @property
    def active(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self.closed_event.is_set())

    @property
    def failed(self) -> bool:
        return self.error_event.is_set()

    def start(self) -> None:
        if not self.api_key:
            self.last_error = "DEEPGRAM_API_KEY não configurada"
            self.error_event.set()
            return
        if self._thread and self._thread.is_alive():
            return
        self.started_at = time.monotonic()
        self._thread = threading.Thread(target=self._thread_main, name="JARVIS-FLUX", daemon=True)
        self._thread.start()

    def feed(self, pcm16: bytes) -> None:
        if not pcm16 or self._stop_requested.is_set() or self.end_event.is_set():
            return
        chunks: list[bytes] = []
        with self._packet_lock:
            self._packet_buffer.extend(pcm16)
            while len(self._packet_buffer) >= self._packet_bytes:
                chunks.append(bytes(self._packet_buffer[: self._packet_bytes]))
                del self._packet_buffer[: self._packet_bytes]
        for chunk in chunks:
            try:
                self._send_queue.put_nowait(chunk)
            except queue.Full:
                # Never block sounddevice. Drop the oldest packet and keep the latest.
                try:
                    self._send_queue.get_nowait()
                except Exception:
                    pass
                try:
                    self._send_queue.put_nowait(chunk)
                except Exception:
                    pass

    def latest_transcript(self) -> str:
        return self.result.transcript or self.eager_transcript or self.update_transcript

    def update_listen(
        self,
        *,
        eot_threshold: float | None = None,
        eager_eot_threshold: float | None = None,
        eot_timeout_ms: int | None = None,
        keyterms: Optional[Iterable[str]] = None,
        language_hints: Optional[Iterable[str]] = None,
    ) -> bool:
        """Queue a Deepgram Flux UpdateListen without blocking microphone audio.

        This is deliberately best-effort. A failed/tardy update never blocks or
        terminates the active turn; the session keeps its previous settings.
        """
        provider = {
            "type": "deepgram",
            "version": "v2",
            "model": self.model,
        }
        if eot_threshold is not None:
            provider["eot_threshold"] = max(0.5, min(float(eot_threshold), 0.9))
        if eager_eot_threshold is not None:
            provider["eager_eot_threshold"] = max(0.3, min(float(eager_eot_threshold), 0.9))
        if eot_timeout_ms is not None:
            provider["eot_timeout_ms"] = max(500, min(int(eot_timeout_ms), 60000))
        if keyterms is not None:
            cleaned = []
            seen = set()
            for item in keyterms:
                term = _clean_term(item)
                key = term.casefold()
                if term and key not in seen:
                    seen.add(key)
                    cleaned.append(term)
                if len(cleaned) >= 100:
                    break
            provider["keyterms"] = cleaned
        if language_hints is not None:
            hints = []
            seen = set()
            for item in language_hints:
                hint = str(item or "").strip()
                key = hint.casefold()
                if hint and key not in seen:
                    seen.add(key)
                    hints.append(hint)
            provider["language_hints"] = hints
        elif self.language_hints:
            # UpdateListen clears language_hints when omitted. Always preserve
            # the multilingual bias unless the caller explicitly replaces it.
            provider["language_hints"] = list(self.language_hints)

        if len(provider) <= 3:
            return False
        payload = {"type": "UpdateListen", "listen": {"provider": provider}}
        self.listen_updated_event.clear()
        try:
            self._control_queue.put_nowait(payload)
            return True
        except queue.Full:
            try:
                self._control_queue.get_nowait()
                self._control_queue.put_nowait(payload)
                return True
            except Exception:
                return False

    def close(self, wait: float = 0.35) -> None:
        if self._stop_requested.is_set():
            return
        self._stop_requested.set()
        with self._packet_lock:
            if self._packet_buffer:
                try:
                    self._send_queue.put_nowait(bytes(self._packet_buffer))
                except Exception:
                    pass
                self._packet_buffer.clear()
        try:
            self._send_queue.put_nowait(None)
        except Exception:
            pass
        if self._thread and wait > 0:
            self._thread.join(timeout=wait)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._async_main())
        except Exception as exc:
            self._set_error(str(exc))
        finally:
            self.closed_event.set()

    def _uri(self) -> str:
        query = [
            ("model", self.model),
            ("encoding", "linear16"),
            ("sample_rate", str(self.sample_rate)),
        ]
        # Flux Multilingual accepts repeated language_hint values and handles
        # code-switching natively. PT-BR + EN-US is the normal JARVIS profile.
        for hint in self.language_hints:
            query.append(("language_hint", hint))
        query.extend([
            ("eager_eot_threshold", f"{self.eager_eot_threshold:.2f}"),
            ("eot_threshold", f"{self.eot_threshold:.2f}"),
            ("eot_timeout_ms", str(self.eot_timeout_ms)),
            ("numerals", "true"),
            ("tag", "jarvis-voice-v70"),
        ])
        return "wss://api.deepgram.com/v2/listen?" + urlencode(query)

    async def _async_main(self) -> None:
        try:
            import websockets
        except Exception as exc:
            raise RuntimeError("Pacote 'websockets' não instalado") from exc

        headers = {"Authorization": f"Token {self.api_key}"}
        uri = self._uri()

        # websockets 15+ uses additional_headers. This package pins 15<=v<17.
        async with websockets.connect(
            uri,
            additional_headers=headers,
            open_timeout=5,
            close_timeout=1,
            ping_interval=20,
            ping_timeout=20,
            max_size=2 * 1024 * 1024,
        ) as ws:
            self.connected_at = time.monotonic()
            self.ready_event.set()
            self._log("info", f"Deepgram Flux conectado em {int((self.connected_at-self.started_at)*1000)} ms")

            configure = {"type": "Configure"}
            if self.keyterms:
                configure["keyterms"] = self.keyterms
            if self.language_hints:
                configure["language_hints"] = self.language_hints
            if len(configure) > 1:
                try:
                    await ws.send(json.dumps(configure, ensure_ascii=False))
                except Exception as exc:
                    self._log("warning", f"Flux Configure não aplicado: {exc}")

            sender = asyncio.create_task(self._sender(ws))
            receiver = asyncio.create_task(self._receiver(ws))
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)

            # If the caller stopped sending before EOT, force Deepgram to flush.
            if sender in done and not self.end_event.is_set() and not self.error_event.is_set():
                try:
                    await ws.send(json.dumps({"type": "CloseStream"}))
                    await asyncio.wait_for(receiver, timeout=1.2)
                except Exception:
                    pass

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _sender(self, ws) -> None:
        # Non-blocking queue polling avoids leaking executor threads when an
        # EndOfTurn cancels the sender while no audio is waiting. Control
        # messages have priority so endpoint/keyterm tuning lands quickly.
        while not self._stop_requested.is_set() and not self.end_event.is_set():
            try:
                control = self._control_queue.get_nowait()
            except queue.Empty:
                control = None
            if control is not None:
                try:
                    await ws.send(json.dumps(control, ensure_ascii=False))
                except Exception as exc:
                    self._log("warning", f"Flux UpdateListen nao aplicado: {exc}")
                continue
            try:
                chunk = self._send_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.005)
                continue
            if chunk is None:
                return
            try:
                await ws.send(chunk)
            except Exception as exc:
                self._set_error(f"Falha enviando audio ao Flux: {exc}")
                return

    async def _receiver(self, ws) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                self._handle_message(payload)
                if self.end_event.is_set() or self.error_event.is_set():
                    return
        except Exception as exc:
            if not self._stop_requested.is_set() and not self.end_event.is_set():
                self._set_error(f"Flux WebSocket: {exc}")

    def _handle_message(self, payload: dict) -> None:
        """Parse a raw Listen v2 message. Kept separate for offline self-tests."""
        self.last_message_at = time.monotonic()
        msg_type = str(payload.get("type") or "")
        if msg_type == "Error":
            self._set_error(str(payload.get("description") or payload.get("code") or "Erro Deepgram"))
            return
        if msg_type == "ListenUpdated":
            self.listen_updated_event.set()
            return
        if msg_type != "TurnInfo":
            return

        event = str(payload.get("event") or "")
        transcript = " ".join(str(payload.get("transcript") or "").split()).strip()
        eot_conf = float(payload.get("end_of_turn_confidence") or 0.0)
        words = payload.get("words") or []
        confidences = []
        word_details = []
        for word in words:
            if not isinstance(word, dict):
                continue
            token = " ".join(str(word.get("word") or "").split()).strip()
            try:
                confidence = float(word.get("confidence") or 0.0)
            except Exception:
                confidence = 0.0
            try:
                start = float(word.get("start") or 0.0)
                end = float(word.get("end") or 0.0)
            except Exception:
                start = end = 0.0
            if word.get("confidence") is not None:
                confidences.append(confidence)
            if token:
                word_details.append((token, confidence, start, end))
        word_conf = sum(confidences) / len(confidences) if confidences else 0.0
        languages = tuple(str(x) for x in (payload.get("languages") or []) if x)

        if event == "StartOfTurn":
            self.start_of_turn_event.set()
        elif event == "Update":
            if transcript:
                self.update_transcript = transcript
        elif event == "EagerEndOfTurn":
            if transcript:
                self.eager_transcript = transcript
                self.update_transcript = transcript
            self.eager_event.set()
        elif event == "TurnResumed":
            self.eager_event.clear()
            self.eager_transcript = ""
        elif event == "EndOfTurn":
            self.result = FluxResult(
                transcript=transcript,
                word_confidence=word_conf,
                eot_confidence=eot_conf,
                event=event,
                languages=languages,
                words=tuple(word_details),
                received_at=time.monotonic(),
                audio_window_end=float(payload.get("audio_window_end") or 0.0),
            )
            self.end_event.set()

    def _set_error(self, message: str) -> None:
        self.last_error = str(message or "Erro desconhecido do Deepgram")
        self.error_event.set()
        self._log("warning", self.last_error)


__all__ = [
    "DeepgramFluxSession",
    "FluxResult",
    "get_api_key",
    "get_key_state",
    "mark_key_invalid",
    "mark_key_valid",
    "is_configured",
    "load_project_keyterms",
]
