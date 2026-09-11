"""Runtime reliability patch for JARVIS VoiceEngine.

Keeps the modern VoiceEngine implementation intact while shortening recovery
latency after a microphone/driver/resource interruption and clearing stale
error state as soon as a real audio stream becomes healthy again.
"""
from __future__ import annotations

import time


_PATCHED = False


def install(voice_cls) -> bool:
    global _PATCHED
    if _PATCHED or voice_cls is None:
        return bool(_PATCHED)

    original_detect = getattr(voice_cls, "_detect_microphone", None)
    original_state = getattr(voice_cls, "_state", None)
    original_supervisor = getattr(voice_cls, "_voice_supervisor_loop", None)
    if not callable(original_detect) or not callable(original_state) or not callable(original_supervisor):
        return False

    def detect_microphone(self):
        result = original_detect(self)
        if bool(getattr(self, "_mic_available", False)):
            # A successful real RawInputStream probe is authoritative. Old
            # watchdog/PortAudio errors must not leak into the new healthy run.
            self.last_error = ""
            try:
                self._auto_recovery_suspended = False
                self._direct_open_failures = 0
            except Exception:
                pass
        return result

    def state(self, state_name: str, detail: str = ""):
        state_key = str(state_name or "").upper()
        # Once the engine reports a healthy operational state, remove stale
        # error text immediately instead of leaving GUI/diagnostics in ERRO.
        if state_key in {"AGUARDANDO", "ACORDOU", "OUVINDO", "ENTENDENDO", "PROCESSANDO", "PENSANDO", "FALANDO"}:
            try:
                if bool(getattr(self, "_mic_available", False)):
                    self.last_error = ""
                    self._auto_recovery_suspended = False
            except Exception:
                pass
        return original_state(self, state_name, detail)

    def supervisor(self):
        """Fast bounded recovery: 2s -> 4s -> 8s -> 15s -> 30s max."""
        transient_delay = 0.65
        resource_delay = 2.0
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

            resource_problem = (
                not bool(self._mic_available)
                or "vosk" in detail_key
                or "wake word" in detail_key
                or ".download" in detail_key
                or "modelo" in detail_key
                or "download" in detail_key
            )

            if resource_problem:
                # Do not freeze recovery for minutes. USB/headset/driver changes
                # are common on Windows and should recover quickly by themselves.
                self._auto_recovery_suspended = False
                wait_s = resource_delay
                resource_delay = min(30.0, resource_delay * 2.0)
                transient_delay = 0.65
                visual_state = "SEM_MICROFONE" if not bool(self._mic_available) else "AGUARDANDO_RECURSO"
                self._state(visual_state, detail[:180])
                try:
                    self._log(
                        "warning",
                        f"Voz aguardando recurso; nova tentativa em {wait_s:.1f}s "
                        f"(tentativa {self._startup_attempts}).",
                    )
                except Exception:
                    pass
            else:
                self._auto_recovery_suspended = False
                resource_delay = 2.0
                wait_s = transient_delay
                transient_delay = min(4.0, transient_delay * 1.55)
                self._state("RECONECTANDO", detail[:180])
                try:
                    self._log(
                        "warning",
                        f"Motor de voz sera reaberto em {wait_s:.2f}s "
                        f"(tentativa {self._startup_attempts}).",
                    )
                except Exception:
                    pass

            if self._stop_event.wait(wait_s):
                return

    voice_cls._detect_microphone = detect_microphone
    voice_cls._state = state
    voice_cls._voice_supervisor_loop = supervisor
    _PATCHED = True
    return True


__all__ = ["install"]
