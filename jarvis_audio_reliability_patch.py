"""Runtime reliability patch for JARVIS VoiceEngine.

Windows audio policy:
- prefer WASAPI -> MME -> DirectSound;
- WDM-KS is last resort because PortAudio blocking streams are unreliable there;
- probe the device native rate before forcing 16 kHz;
- let PortAudio choose the hardware buffer (blocksize=0), then resample to
  JARVIS' 16 kHz inside _StableDirectStream;
- missing/unplugged microphone is recoverable, not a fatal visual error.

Voice interaction policy:
- wake phrases are conservative but tolerant of common Vosk renderings of
  "Jarvis" (javis/jarves/jervis/ja vis);
- a stable exact wake partial is enough; we do not require an unnecessarily
  strong final confidence outside call-guard contexts;
- AntonioNeural remains preferred, but speech must fail open: other Brazilian
  male neural voices and finally a local Windows voice are preferable to
  silently dropping a response;
- if the TTS worker ever dies, the next speak() request restarts it.
"""
from __future__ import annotations

import sys
import threading
import time


_PATCHED = False


def install(voice_cls) -> bool:
    global _PATCHED
    if _PATCHED or voice_cls is None:
        return bool(_PATCHED)

    original_state = getattr(voice_cls, "_state", None)
    original_supervisor = getattr(voice_cls, "_voice_supervisor_loop", None)
    original_speak = getattr(voice_cls, "speak", None)
    original_normalize = getattr(voice_cls, "_normalize", None)
    module = sys.modules.get(getattr(voice_cls, "__module__", ""))
    stable_stream_cls = getattr(module, "_StableDirectStream", None) if module else None
    if not callable(original_state) or not callable(original_supervisor) or stable_stream_cls is None:
        return False

    # ------------------------------------------------------------------
    # Wake word: keep exact-phrase semantics but cover how the PT Vosk model
    # commonly renders the English proper name JARVIS.
    # ------------------------------------------------------------------
    existing_phrases = list(getattr(voice_cls, "WAKE_PHRASES", ()) or ())
    wake_variants = (
        "jarvis", "javis", "jarves", "jervis", "jarvi", "jarvisse", "jarbas", "ja vis",
        "oi jarvis", "oi javis", "oi jarves", "oi jervis", "oi ja vis",
        "ei jarvis", "ei javis", "ei jarves", "ei jervis", "ei ja vis",
        "e ai jarvis", "e ai javis", "e ai jarves", "e ai jervis", "e ai ja vis",
        "eae jarvis", "eae javis", "eae jarves",
        "ola jarvis", "ola javis", "ola jarves", "ola jervis",
        "alo jarvis", "alo javis", "o jarvis", "o javis",
    )
    voice_cls.WAKE_PHRASES = tuple(dict.fromkeys([*existing_phrases, *wake_variants]))
    voice_cls.DUAL_WAKE = False
    voice_cls.WAKE_FAST_PARTIAL = True
    try:
        voice_cls.WAKE_PARTIAL_STABLE = min(float(getattr(voice_cls, "WAKE_PARTIAL_STABLE", 0.10)), 0.055)
    except Exception:
        voice_cls.WAKE_PARTIAL_STABLE = 0.055
    try:
        voice_cls.WAKE_MIN_FINAL_CONFIDENCE = min(float(getattr(voice_cls, "WAKE_MIN_FINAL_CONFIDENCE", 0.34)), 0.22)
    except Exception:
        voice_cls.WAKE_MIN_FINAL_CONFIDENCE = 0.22
    voice_cls.WAKE_MIN_LEAD_SILENCE = 0.0
    try:
        voice_cls.CALL_WAKE_MIN_LEAD_SILENCE = min(float(getattr(voice_cls, "CALL_WAKE_MIN_LEAD_SILENCE", 0.08)), 0.05)
    except Exception:
        voice_cls.CALL_WAKE_MIN_LEAD_SILENCE = 0.05

    if callable(original_normalize):
        def normalize_voice_text(text: str) -> str:
            value = original_normalize(text)
            replacements = {
                "javis": "jarvis",
                "jarves": "jarvis",
                "jervis": "jarvis",
                "jarvi": "jarvis",
                "jarvisse": "jarvis",
                "jarbas": "jarvis",
                "ja vis": "jarvis",
                "jar viz": "jarvis",
                "eae": "e ai",
            }
            for source, target in replacements.items():
                value = value.replace(source, target)
            return " ".join(value.split()).strip()
        voice_cls._normalize = staticmethod(normalize_voice_text)

    # ------------------------------------------------------------------
    # TTS: preferred identity first, reliability second, silence never.
    # ------------------------------------------------------------------
    voice_cls.TTS_VOICE_LOCK = False
    voice_cls.TTS_ALLOW_LOCAL_FALLBACK = True

    if callable(original_speak):
        def reliable_speak(self, *args, **kwargs):
            # A prior playback/backend exception must not permanently silence
            # the process. Restart only the TTS worker, never the microphone.
            try:
                worker = getattr(self, "_tts_thread", None)
                stop_event = getattr(self, "_stop_event", None)
                stopped = bool(stop_event and stop_event.is_set())
                if not stopped and (worker is None or not worker.is_alive()):
                    self._tts_thread = threading.Thread(
                        target=self._tts_worker,
                        name="JARVIS-TTS-RECOVERY",
                        daemon=True,
                    )
                    self._tts_thread.start()
                    try:
                        self._log("warning", "Worker de TTS reiniciado automaticamente.")
                    except Exception:
                        pass
            except Exception:
                pass
            return original_speak(self, *args, **kwargs)
        voice_cls.speak = reliable_speak

    def _host_name(hostapis, device):
        try:
            idx = int(device.get("hostapi", -1))
            if 0 <= idx < len(hostapis):
                return str(hostapis[idx].get("name") or "")
        except Exception:
            pass
        return ""

    def _is_wdm(host: str) -> bool:
        key = str(host or "").lower().replace("_", "-")
        return "wdm-ks" in key or "wdm ks" in key

    def detect_microphone(self):
        """Open a real Windows input stream using the driver's native format."""
        self._mic_available = False
        self._input_device_index = None
        self._capture_sample_rate = self.SAMPLE_RATE
        self._input_hostapi = ""
        self._input_candidate_count = 0
        self._input_candidate_pos = 0
        self.input_device_name = ""
        self._capture_mode = "no-usable-input"
        self._auto_recovery_suspended = False

        try:
            devices = list(self._sd.query_devices())
        except Exception as exc:
            self.last_error = f"PortAudio não conseguiu listar entradas: {exc}"
            try:
                self._log("warning", self.last_error)
            except Exception:
                pass
            return
        try:
            hostapis = list(self._sd.query_hostapis())
        except Exception:
            hostapis = []
        try:
            default_input = int(self._sd.default.device[0])
        except Exception:
            default_input = -1

        good_words = ("microphone", "microfone", "mic ", "headset", "headphone", "usb", "webcam")
        poor_words = (
            "audio cd", "áudio cd", "cd input", "entrada de cd", "stereo mix",
            "mixagem estereo", "mixagem estéreo", "what u hear", "loopback", "wave out",
        )
        candidates = []
        for index, device in enumerate(devices):
            try:
                if int(device.get("max_input_channels", 0) or 0) < 1:
                    continue
            except Exception:
                continue
            name = str(device.get("name", "") or "")
            normalized = self._normalize(name)
            host = _host_name(hostapis, device)
            host_key = str(host or "").lower()
            score = 0
            if "wasapi" in host_key:
                score += 500
            elif "mme" in host_key:
                score += 420
            elif "directsound" in host_key or "direct sound" in host_key:
                score += 340
            elif _is_wdm(host):
                score -= 500
            else:
                score += 120
            if index == default_input:
                score += 90
            if any(self._normalize(word) in normalized for word in good_words):
                score += 80
            if any(self._normalize(word) in normalized for word in poor_words):
                score -= 600
            candidates.append((score, index, device, host))

        candidates.sort(key=lambda row: (-row[0], row[1]))
        non_wdm = [row for row in candidates if not _is_wdm(row[3])]
        wdm = [row for row in candidates if _is_wdm(row[3])]
        candidates = non_wdm + wdm
        self._input_candidate_count = len(candidates)
        if not candidates:
            self.last_error = "Nenhum dispositivo de entrada de áudio foi encontrado pelo PortAudio."
            try:
                self._log("warning", self.last_error)
            except Exception:
                pass
            return

        errors = []
        for position, (_, index, device, host) in enumerate(candidates):
            try:
                native = int(round(float(device.get("default_samplerate") or 0)))
            except Exception:
                native = 0
            rates = []
            for rate in (native, 48000, 44100, 32000, self.SAMPLE_RATE):
                if rate > 0 and rate not in rates:
                    rates.append(rate)

            for rate in rates:
                stream = None
                try:
                    self._sd.check_input_settings(
                        device=index,
                        channels=self.CHANNELS,
                        dtype="int16",
                        samplerate=rate,
                    )
                    stream = self._sd.RawInputStream(
                        samplerate=rate,
                        blocksize=0,
                        dtype="int16",
                        channels=self.CHANNELS,
                        device=index,
                    )
                    stream.start()
                    probe_frames = max(64, int(round(rate * 0.020)))
                    stream.read(probe_frames)
                except Exception as exc:
                    errors.append(f"#{index}@{rate}/{host or '?'}: {exc}")
                    continue
                finally:
                    if stream is not None:
                        try:
                            stream.stop()
                        except Exception:
                            pass
                        try:
                            stream.close()
                        except Exception:
                            pass

                self._input_device_index = int(index)
                self._capture_sample_rate = int(rate)
                self._input_hostapi = str(host or "desconhecido")
                self._input_candidate_pos = int(position)
                self.input_device_name = str(device.get("name", "") or f"Entrada {index}")
                try:
                    self._load_mic_profile()
                except Exception:
                    pass
                self._mic_available = True
                self._auto_recovery_suspended = False
                self._direct_open_failures = 0
                self.last_error = ""
                self._capture_mode = (
                    "stable-direct-driver-buffer-16k"
                    if rate == self.SAMPLE_RATE
                    else f"stable-direct-driver-buffer-{rate}-to-{self.SAMPLE_RATE}"
                )
                try:
                    self._log(
                        "info",
                        f"Microfone selecionado: {self.input_device_name} "
                        f"(#{index}, {rate} Hz, {self._input_hostapi}, buffer=driver).",
                    )
                except Exception:
                    pass
                return

        detail = " | ".join(errors[:8]) if errors else "nenhum stream de entrada pôde ser aberto"
        self._input_probe_errors = list(errors[:16])
        self._auto_recovery_suspended = False
        self.last_error = (
            "Entrada de microfone detectada no Windows, mas nenhuma rota PortAudio abriu. "
            "O JARVIS continuará tentando automaticamente. "
            f"Tentativas: {detail}"
        )
        try:
            self._log("warning", self.last_error)
        except Exception:
            pass

    def state(self, state_name: str, detail: str = ""):
        state_key = str(state_name or "").upper()
        if state_key in {
            "AGUARDANDO", "ACORDOU", "OUVINDO", "ENTENDENDO", "PROCESSANDO",
            "PENSANDO", "FALANDO", "EXECUTANDO",
        }:
            try:
                if bool(getattr(self, "_mic_available", False)):
                    self.last_error = ""
                    self._auto_recovery_suspended = False
            except Exception:
                pass
        return original_state(self, state_name, detail)

    def wake_loop(self):
        """Classic wake loop with a driver-selected PortAudio block size."""
        block_frames = 320
        while not self._stop_event.is_set():
            self._stream_restart_event.clear()
            recognizer = self._new_wake_recognizer()
            got_frame = False
            try:
                capture_rate = int(getattr(self, "_capture_sample_rate", self.SAMPLE_RATE) or self.SAMPLE_RATE)
                with self._sd.RawInputStream(
                    samplerate=capture_rate,
                    blocksize=0,
                    dtype="int16",
                    channels=self.CHANNELS,
                    device=self._input_device_index,
                ) as raw_stream:
                    stream = stable_stream_cls(raw_stream, self, input_rate=capture_rate)
                    self._audio_ring = stream
                    self._capture_mode = (
                        "stable-direct-driver-buffer-16k"
                        if capture_rate == self.SAMPLE_RATE
                        else f"stable-direct-driver-buffer-{capture_rate}-to-{self.SAMPLE_RATE}"
                    )
                    self.last_error = ""
                    self._state("AGUARDANDO", f"Diga '{getattr(module, 'PUBLIC_NAME', 'JARVIS').title()}'")
                    before = self._direct_frames_read
                    self._listen_on_stream(stream, recognizer, block_frames)
                    got_frame = self._direct_frames_read > before
                self._audio_ring = None
                if got_frame:
                    self._direct_open_failures = 0
            except Exception as exc:
                self._audio_ring = None
                if self._stop_event.is_set():
                    return
                self._direct_open_failures += 1
                self.last_error = str(exc)
                try:
                    self._log("warning", f"Falha real de leitura do microfone: {exc}")
                except Exception:
                    pass
                if self._direct_open_failures >= 3:
                    self._ready = False
                    self._ready_event.clear()
                    self._mic_available = False
                    self._auto_recovery_suspended = False
                    self._state("RECONECTANDO", "Reabrindo entrada de áudio")
                    return
                self._state("AGUARDANDO", "Reabrindo entrada de áudio")
                if self._stop_event.wait(0.25):
                    return

    def supervisor(self):
        """Fast bounded recovery: 1.2s -> 2.4s -> 4.8s -> 8s max for audio."""
        transient_delay = 0.55
        resource_delay = 1.2
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
            detail = str(self.last_error or "Entrada de audio indisponivel").strip()
            detail_key = detail.lower()
            model_problem = any(token in detail_key for token in ("vosk", "wake word", ".download", "modelo", "download"))

            if model_problem:
                wait_s = min(30.0, max(4.0, resource_delay * 2.0))
                resource_delay = min(30.0, max(4.0, wait_s * 1.7))
                self._state("AGUARDANDO_RECURSO", detail[:180])
            else:
                wait_s = resource_delay if not bool(self._mic_available) else transient_delay
                resource_delay = min(8.0, max(1.2, resource_delay * 2.0))
                transient_delay = min(3.0, transient_delay * 1.5)
                self._auto_recovery_suspended = False
                self._state("RECONECTANDO", detail[:180])

            try:
                self._log(
                    "warning",
                    f"Voz será reaberta em {wait_s:.2f}s (tentativa {self._startup_attempts}).",
                )
            except Exception:
                pass
            if self._stop_event.wait(wait_s):
                return

    voice_cls._detect_microphone = detect_microphone
    voice_cls._state = state
    voice_cls._wake_loop = wake_loop
    voice_cls._voice_supervisor_loop = supervisor
    _PATCHED = True
    return True


__all__ = ["install"]
