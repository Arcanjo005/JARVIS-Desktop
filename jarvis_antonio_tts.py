"""Low-latency natural speech path for Microsoft Antonio Neural.

Normal typed chat uses this module without initializing microphone, Whisper,
Vosk or Qt.  Speech is synthesized in long natural phrases with look-ahead so
sentence boundaries do not create audible gaps.  Caption callbacks are emitted
while the audio is actually playing instead of when synthesis begins.
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
# +10% made long answers sound rushed/robotic.  A small positive rate keeps
# response latency good while preserving vowels and punctuation naturally.
ANTONIO_RATE = "+3%"
ANTONIO_PITCH = "-1Hz"


class AntonioNeuralTTS:
    """Serial TTS worker with natural phrasing, look-ahead and live captions."""

    def __init__(
        self,
        project_dir,
        logger=None,
        on_start: Optional[Callable[[str], None]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_end: Optional[Callable[[], None]] = None,
    ):
        self.project_dir = Path(project_dir)
        self.logger = logger
        self.on_start = on_start
        self.on_chunk = on_chunk
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
        self._closed = threading.Event()

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
        if self._closed.is_set():
            return
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

    def close(self, timeout: float = 1.5) -> None:
        """Stop playback and let the worker exit before temporary files vanish."""
        if self._closed.is_set():
            return
        self.stop(clear_queue=True)
        self._closed.set()
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        try:
            if self._pygame is not None and self._mixer_ready:
                self._pygame.mixer.music.stop()
                self._pygame.mixer.music.unload()
        except Exception:
            pass

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    def speak(self, text: str, interrupt: bool = True) -> bool:
        clean = self._normalize_for_speech(text)
        if not clean or self._closed.is_set():
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

    def prefetch(self, text: str) -> bool:
        """Warm a deterministic phrase without opening an audio device."""
        clean = self._normalize_for_speech(text)
        if not clean:
            return False
        try:
            for chunk in self._split_text(clean):
                self._synthesize(chunk)
            return True
        except Exception as exc:
            self._log("debug", f"Prefetch Antonio ignorado: {exc}")
            return False

    @staticmethod
    def _normalize_for_speech(text: str) -> str:
        clean = " ".join(str(text or "").replace("…", ".").split()).strip()
        if not clean:
            return ""
        # Remove markdown that Edge would otherwise pronounce awkwardly.
        clean = re.sub(r"[`*_#]+", "", clean)
        clean = re.sub(r"\s+([,.;:!?])", r"\1", clean)
        clean = re.sub(r"([,.;:!?])(?=[A-Za-zÀ-ÿ])", r"\1 ", clean)
        # Repeated punctuation creates exaggerated pauses.
        clean = re.sub(r"\.{2,}", ".", clean)
        clean = re.sub(r"([!?])\1+", r"\1", clean)
        return clean.strip()

    @staticmethod
    def _split_text(text: str):
        """Use long natural chunks so playback is effectively continuous.

        The first implementation used ~118-180 characters and therefore loaded
        a new MP3 after nearly every sentence.  Long phrases give Edge enough
        linguistic context for prosody and give the look-ahead worker plenty of
        time to synthesize the following phrase before playback reaches it.
        """
        text = " ".join(str(text or "").split()).strip()
        if not text:
            return []
        # Keep sentence punctuation because the neural voice uses it for prosody.
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if not sentences:
            sentences = [text]
        chunks = []
        target = 520
        hard = 720
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if current and len(candidate) > target:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
            while len(current) > hard:
                cut = current.rfind(" ", 360, hard + 1)
                if cut < 0:
                    cut = hard
                chunks.append(current[:cut].strip())
                current = current[cut:].strip()
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _caption_segments(text: str):
        """Small readable phrases used only for visual subtitles."""
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return []
        clauses = [x.strip() for x in re.split(r"(?<=[.!?;,])\s+", clean) if x.strip()]
        out = []
        for clause in clauses or [clean]:
            words = clause.split()
            while len(words) > 15:
                out.append(" ".join(words[:13]))
                words = words[13:]
            if words:
                phrase = " ".join(words)
                if out and len(out[-1]) + 1 + len(phrase) <= 105:
                    out[-1] = f"{out[-1]} {phrase}"
                else:
                    out.append(phrase)
        return out

    def _cache_path(self, text: str) -> Path:
        key = hashlib.sha256(
            f"{ANTONIO_VOICE}|{ANTONIO_RATE}|{ANTONIO_PITCH}|{text}".encode("utf-8", errors="ignore")
        ).hexdigest()
        return self.cache_dir / f"{key}.mp3"

    async def _synthesize_async(self, text: str, path: Path) -> None:
        import edge_tts
        communicate = edge_tts.Communicate(
            text=text,
            voice=ANTONIO_VOICE,
            rate=ANTONIO_RATE,
            pitch=ANTONIO_PITCH,
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
        tmp = path.with_name(f"{path.stem}.tmp.{threading.get_ident()}.mp3")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        asyncio.run(self._synthesize_async(text, tmp))
        if not tmp.is_file() or tmp.stat().st_size <= 512:
            raise RuntimeError("Antonio Neural não retornou áudio válido")
        try:
            if path.is_file() and path.stat().st_size > 512:
                try:
                    tmp.unlink()
                except Exception:
                    pass
                return path
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
            # Moderate buffer: lower values can crackle on older integrated audio;
            # larger values make interruption and subtitles feel delayed.
            pygame.mixer.init(buffer=1024)
        self._mixer_ready = True

    def _duration_for(self, path: Path, text: str) -> float:
        self._ensure_mixer()
        try:
            sound = self._pygame.mixer.Sound(str(path))
            duration = float(sound.get_length() or 0.0)
            del sound
            if duration > 0.2:
                return duration
        except Exception:
            pass
        # Natural Brazilian Portuguese at ~3% above normal averages roughly
        # 2.6 spoken words/s. This fallback is only for subtitle timing.
        return max(0.8, len(str(text or "").split()) / 2.6)

    def _emit_caption(self, text: str) -> None:
        try:
            if callable(self.on_chunk):
                self.on_chunk(text)
        except Exception:
            pass

    def _play(self, path: Path, generation: int, spoken_text: str) -> bool:
        self._ensure_mixer()
        duration = self._duration_for(path, spoken_text)
        segments = self._caption_segments(spoken_text)
        weights = [max(1, len(segment.split())) for segment in segments]
        total_weight = max(1, sum(weights))
        thresholds = []
        acc = 0
        for weight in weights:
            thresholds.append(duration * acc / total_weight)
            acc += weight

        self._pygame.mixer.music.load(str(path))
        self._pygame.mixer.music.play()
        started = time.monotonic()
        caption_index = -1
        while self._pygame.mixer.music.get_busy():
            if generation != self._current_generation() or self._closed.is_set():
                self._pygame.mixer.music.stop()
                return False
            elapsed = time.monotonic() - started
            while caption_index + 1 < len(segments) and elapsed >= thresholds[caption_index + 1]:
                caption_index += 1
                self._emit_caption(segments[caption_index])
            time.sleep(0.012)
        # Guarantee the last subtitle phrase is not skipped on a very short MP3.
        if segments and caption_index < len(segments) - 1 and generation == self._current_generation():
            self._emit_caption(segments[-1])
        return generation == self._current_generation() and not self._closed.is_set()

    def _prefetch_next(self, text: str, generation: int, box: dict, ready: threading.Event) -> None:
        try:
            if generation != self._current_generation() or self._closed.is_set():
                return
            box["audio"] = self._synthesize(text)
        except Exception as exc:
            box["error"] = exc
        finally:
            ready.set()

    def _worker(self) -> None:
        while not self._closed.is_set():
            item = self._queue.get()
            if item is None or self._closed.is_set():
                break
            generation, text = item
            if generation != self._current_generation():
                continue
            chunks = self._split_text(text)
            if not chunks:
                continue
            started = False
            try:
                current_audio = self._synthesize(chunks[0])
                for index, chunk in enumerate(chunks):
                    if generation != self._current_generation() or self._closed.is_set():
                        break

                    next_box = {}
                    next_ready = None
                    if index + 1 < len(chunks):
                        next_ready = threading.Event()
                        threading.Thread(
                            target=self._prefetch_next,
                            args=(chunks[index + 1], generation, next_box, next_ready),
                            name="JARVIS-ANTONIO-PREFETCH",
                            daemon=True,
                        ).start()

                    if not started:
                        started = True
                        self._speaking.set()
                        try:
                            if callable(self.on_start):
                                self.on_start(text)
                        except Exception:
                            pass

                    if not self._play(current_audio, generation, chunk):
                        break

                    if next_ready is not None:
                        # In normal speech the next chunk has already finished
                        # synthesizing before playback reaches this point.
                        while not next_ready.wait(0.012):
                            if generation != self._current_generation() or self._closed.is_set():
                                break
                        if generation != self._current_generation() or self._closed.is_set():
                            break
                        if "error" in next_box:
                            raise next_box["error"]
                        current_audio = next_box.get("audio")
                        if current_audio is None:
                            current_audio = self._synthesize(chunks[index + 1])
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


__all__ = ["AntonioNeuralTTS", "ANTONIO_VOICE", "ANTONIO_RATE", "ANTONIO_PITCH"]
