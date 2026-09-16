"""More natural continuous male pt-BR speech for JARVIS 1.3.12.

Keeps the proven lazy worker from jarvis_antonio_tts, but uses a newer male
multilingual voice when available, much longer synthesis passages, and caption
timing driven by the audio player's actual playback position.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import threading
import time
from pathlib import Path

from jarvis_antonio_tts import AntonioNeuralTTS


NATURAL_PRIMARY_VOICE = "pt-BR-MacerioMultilingualNeural"
NATURAL_FALLBACK_VOICE = "pt-BR-AntonioNeural"
NATURAL_RATE = "-1%"
NATURAL_PITCH = "0Hz"


class NaturalSpeechTTS1312(AntonioNeuralTTS):
    """Antonio-compatible worker with smoother prosody and live subtitles."""

    @staticmethod
    def _split_text(text: str):
        """Synthesize most normal answers as one continuous neural utterance.

        A file boundary is an audible boundary with pygame/MP3.  1,100-char
        targets remove almost all boundaries from ordinary replies while still
        preventing extremely long requests from monopolising one network call.
        """
        text = " ".join(str(text or "").split()).strip()
        if not text:
            return []
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()] or [text]
        chunks = []
        target = 1100
        hard = 1450
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if current and len(candidate) > target:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
            while len(current) > hard:
                cut = current.rfind(" ", 760, hard + 1)
                if cut < 0:
                    cut = hard
                chunks.append(current[:cut].strip())
                current = current[cut:].strip()
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _caption_segments(text: str):
        """Short rolling subtitle phrases that are easy to follow by eye."""
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return []
        clauses = [part.strip() for part in re.split(r"(?<=[.!?;,])\s+", clean) if part.strip()] or [clean]
        out = []
        for clause in clauses:
            words = clause.split()
            while words:
                take = min(9, len(words))
                phrase = " ".join(words[:take])
                words = words[take:]
                if out and len(out[-1]) + 1 + len(phrase) <= 66 and len(out[-1].split()) < 8:
                    out[-1] = f"{out[-1]} {phrase}"
                else:
                    out.append(phrase)
        return out

    def _cache_path_for_voice(self, text: str, voice: str) -> Path:
        key = hashlib.sha256(
            f"natural-1312|{voice}|{NATURAL_RATE}|{NATURAL_PITCH}|{text}".encode("utf-8", errors="ignore")
        ).hexdigest()
        return self.cache_dir / f"{key}.mp3"

    async def _synthesize_voice_async(self, text: str, path: Path, voice: str) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=NATURAL_RATE,
            pitch=NATURAL_PITCH,
            volume="+0%",
        )
        await communicate.save(str(path))

    def _synthesize_for_voice(self, text: str, voice: str) -> Path:
        path = self._cache_path_for_voice(text, voice)
        try:
            if path.is_file() and path.stat().st_size > 512:
                return path
        except Exception:
            pass
        tmp = path.with_name(f"{path.stem}.tmp.{threading.get_ident()}.mp3")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        asyncio.run(self._synthesize_voice_async(text, tmp, voice))
        if not tmp.is_file() or tmp.stat().st_size <= 512:
            raise RuntimeError(f"{voice} não retornou áudio válido")
        try:
            if path.is_file() and path.stat().st_size > 512:
                tmp.unlink(missing_ok=True)
                return path
            tmp.replace(path)
        except Exception:
            path = tmp
        return path

    def _synthesize(self, text: str) -> Path:
        primary_error = None
        for voice in (NATURAL_PRIMARY_VOICE, NATURAL_FALLBACK_VOICE):
            try:
                return self._synthesize_for_voice(text, voice)
            except Exception as exc:
                if primary_error is None:
                    primary_error = exc
                self._log("debug", f"Voz {voice} indisponível neste trecho: {exc}")
        raise RuntimeError(f"vozes neurais indisponíveis: {primary_error}")

    def _duration_for(self, path: Path, text: str) -> float:
        try:
            return super()._duration_for(path, text)
        except Exception:
            return max(0.9, len(str(text or "").split()) / 2.45)

    def _play(self, path: Path, generation: int, spoken_text: str) -> bool:
        self._ensure_mixer()
        duration = self._duration_for(path, spoken_text)
        segments = self._caption_segments(spoken_text)
        weights = [max(1, len(segment.split())) for segment in segments]
        total_weight = max(1, sum(weights))
        thresholds = []
        consumed = 0
        for weight in weights:
            thresholds.append(duration * consumed / total_weight)
            consumed += weight

        self._pygame.mixer.music.load(str(path))
        self._pygame.mixer.music.play()
        started = time.monotonic()
        caption_index = -1
        if segments:
            caption_index = 0
            self._emit_caption(segments[0])

        while self._pygame.mixer.music.get_busy():
            if generation != self._current_generation() or self._closed.is_set():
                self._pygame.mixer.music.stop()
                return False

            # pygame reports the position of the audio that is actually being
            # played.  This follows buffer/device delays far better than a wall
            # clock and makes the subtitle advance with the heard sentence.
            try:
                pos_ms = int(self._pygame.mixer.music.get_pos())
            except Exception:
                pos_ms = -1
            elapsed = (pos_ms / 1000.0) if pos_ms >= 0 else (time.monotonic() - started)
            while caption_index + 1 < len(segments) and elapsed >= thresholds[caption_index + 1]:
                caption_index += 1
                self._emit_caption(segments[caption_index])
            time.sleep(0.010)

        if segments and caption_index < len(segments) - 1 and generation == self._current_generation():
            self._emit_caption(segments[-1])
        return generation == self._current_generation() and not self._closed.is_set()


__all__ = [
    "NaturalSpeechTTS1312",
    "NATURAL_PRIMARY_VOICE",
    "NATURAL_FALLBACK_VOICE",
    "NATURAL_RATE",
    "NATURAL_PITCH",
]
