"""Lightweight neural TTS path locked to Microsoft Antonio Neural.

This module intentionally does not initialize microphone, Vosk, Whisper, Qt or
any wake-word service. It exists so normal chat replies can speak immediately
without paying the cost of the full VoiceEngine.
"""
from __future__ import annotations

import asyncio
import hashlib
import queue
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional


ANTONIO_VOICE = "pt-BR-AntonioNeural"
ANTONIO_RATE = "+10%"


class AntonioNeuralTTS:
    """Small serial TTS worker that never falls back to a different voice."""

    def __init__(
        self,
        project_dir,
        logger=None,
        on_start: Optional[Callable[[str], None]] = None,
        on_end: Optional[Callable[[], None]] = None,
    ):
        self.project_dir = Path(project_dir)
        self.logger = logger
        self.on_start = on_start
        self.on_end = on_end
        self.cache_dir = self.project_dir / "data" / "tts_cache_antonio"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._queue = queue.Queue(maxsize=4)
        self._thread = None
        self._thread_lock = threading.Lock()
        self._generation = 0
        self._generation_lock = threading.Lock()
        self._pygame = None
        self._mixer_ready = False
        self._speaking = threading.Event()

    def _log(self, level: str, message: str) -> None:
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "TTS")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    def _ensure_worker(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker,
                name="JARVIS-ANTONIO-TTS",
                daemon=True,
            )
            self._thread.start()

    def _current_generation(self) -> int:
        with self._generation_lock:
            return int(self._generation)

    def _next_generation(self) -> int:
        with self._generation_lock:
            self._generation += 1
            return int(self._generation)

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            except Exception:
                return

    def stop(self, clear_queue: bool = True) -> None:
        self._next_generation()
        if clear_queue:
            self._drain()
        try:
            if self._pygame is not None and self._mixer_ready:
                self._pygame.mixer.music.stop()
        except Exception:
            pass
        self._speaking.clear()

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    def speak(self, text: str, interrupt: bool = True) -> bool:
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return False
        self._ensure_worker()
        generation = self._next_generation() if interrupt else self._current_generation()
        if interrupt:
            self._drain()
            try:
                if self._pygame is not None and self._mixer_ready:
                    self._pygame.mixer.music.stop()
            except Exception:
                pass
        try:
            self._queue.put_nowait((generation, clean))
        except queue.Full:
            self._drain()
            self._queue.put_nowait((generation, clean))
        return True

    @staticmethod
    def _split_text(text: str):
        """Return short chunks so the first audio starts quickly."""
        text = " ".join(str(text or "").split()).strip()
        if not text:
            return []
        sentences = [part.strip() for part in re.split(r"(?<=[.!?;:])\s+", text) if part.strip()]
        if not sentences:
            sentences = [text]
        chunks = []
        limit = 118
        for sentence in sentences:
            remaining = sentence
            while len(remaining) > limit:
                cut = remaining.rfind(" ", 0, limit + 1)
                if cut < 48:
                    cut = limit
                chunks.append(remaining[:cut].strip())
                remaining = remaining[cut:].strip()
                limit = 180
            if remaining:
                if chunks and len(chunks[-1]) + 1 + len(remaining) <= limit:
                    chunks[-1] = f"{chunks[-1]} {remaining}".strip()
                else:
                    chunks.append(remaining)
            limit = 180
        return chunks

    def _cache_path(self, text: str) -> Path:
        key = hashlib.sha256(
            f"{ANTONIO_VOICE}|{ANTONIO_RATE}|{text}".encode("utf-8", errors="ignore")
        ).hexdigest()
        return self.cache_dir / f"{key}.mp3"

    async def _synthesize_async(self, text: str, path: Path) -> None:
        import edge_tts
        communicate = edge_tts.Communicate(
            text=text,
            voice=ANTONIO_VOICE,
            rate=ANTONIO_RATE,
            volume="+0%",
        )
        await communicate.save(str(path))

    def _synthesize(self, text: str) -> Path:
        path = self._cache_path(text)
        try:
            if path.is_file() and path.stat().st_size > 512:
                return path
        except Exception:
            pass
        tmp = path.with_suffix(".tmp.mp3")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        asyncio.run(self._synthesize_async(text, tmp))
        if not tmp.is_file() or tmp.stat().st_size <= 512:
            raise RuntimeError("Antonio Neural não retornou áudio válido")
        try:
            tmp.replace(path)
        except Exception:
            path = tmp
        return path

    def _ensure_mixer(self) -> None:
        if self._mixer_ready:
            return
        import pygame
        self._pygame = pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        self._mixer_ready = True

    def _play(self, path: Path, generation: int) -> bool:
        self._ensure_mixer()
        self._pygame.mixer.music.load(str(path))
        self._pygame.mixer.music.play()
        while self._pygame.mixer.music.get_busy():
            if generation != self._current_generation():
                self._pygame.mixer.music.stop()
                return False
            time.sleep(0.018)
        return generation == self._current_generation()

    def _worker(self) -> None:
        while True:
            generation, text = self._queue.get()
            if generation != self._current_generation():
                continue
            chunks = self._split_text(text)
            if not chunks:
                continue
            started = False
            try:
                for chunk in chunks:
                    if generation != self._current_generation():
                        break
                    audio = self._synthesize(chunk)
                    if generation != self._current_generation():
                        break
                    if not started:
                        started = True
                        self._speaking.set()
                        try:
                            if callable(self.on_start):
                                self.on_start(text)
                        except Exception:
                            pass
                    if not self._play(audio, generation):
                        break
            except Exception as exc:
                self._log("warning", f"Antonio Neural indisponível; sem fallback de voz: {exc}")
            finally:
                if started:
                    self._speaking.clear()
                    try:
                        if callable(self.on_end):
                            self.on_end()
                    except Exception:
                        pass


__all__ = ["AntonioNeuralTTS", "ANTONIO_VOICE", "ANTONIO_RATE"]
