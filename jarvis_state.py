"""JARVIS - maquina de estados observavel e retrocompativel."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Deque, Dict, Optional


class RuntimeState(str, Enum):
    BOOTING = "BOOTING"
    IDLE = "IDLE"
    WAKE = "WAKE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SPEAKING = "SPEAKING"
    RECOVERING = "RECOVERING"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


EXTERNAL_TO_RUNTIME = {
    "PREPARANDO": RuntimeState.BOOTING,
    "CALIBRANDO": RuntimeState.BOOTING,
    "AGUARDANDO": RuntimeState.IDLE,
    "REPOUSO": RuntimeState.IDLE,
    "ACORDOU": RuntimeState.WAKE,
    "OUVINDO": RuntimeState.LISTENING,
    "ESPERANDO_RESPOSTA": RuntimeState.LISTENING,
    "ENTENDENDO": RuntimeState.TRANSCRIBING,
    "PROCESSANDO": RuntimeState.THINKING,
    "PENSANDO": RuntimeState.THINKING,
    "EXECUTANDO": RuntimeState.EXECUTING,
    "VERIFICANDO": RuntimeState.VERIFYING,
    "FALANDO": RuntimeState.SPEAKING,
    "RECONECTANDO": RuntimeState.RECOVERING,
    "ERRO": RuntimeState.ERROR,
    "PARADO": RuntimeState.STOPPED,
}

ALLOWED = {
    RuntimeState.BOOTING: {RuntimeState.IDLE, RuntimeState.RECOVERING, RuntimeState.ERROR, RuntimeState.STOPPED},
    RuntimeState.IDLE: {RuntimeState.WAKE, RuntimeState.LISTENING, RuntimeState.SPEAKING, RuntimeState.BOOTING, RuntimeState.ERROR, RuntimeState.STOPPED},
    RuntimeState.WAKE: {RuntimeState.LISTENING, RuntimeState.SPEAKING, RuntimeState.IDLE, RuntimeState.ERROR},
    RuntimeState.LISTENING: {RuntimeState.TRANSCRIBING, RuntimeState.IDLE, RuntimeState.SPEAKING, RuntimeState.RECOVERING, RuntimeState.ERROR},
    RuntimeState.TRANSCRIBING: {RuntimeState.THINKING, RuntimeState.EXECUTING, RuntimeState.LISTENING, RuntimeState.IDLE, RuntimeState.ERROR},
    RuntimeState.THINKING: {RuntimeState.EXECUTING, RuntimeState.SPEAKING, RuntimeState.IDLE, RuntimeState.ERROR},
    RuntimeState.EXECUTING: {RuntimeState.VERIFYING, RuntimeState.SPEAKING, RuntimeState.IDLE, RuntimeState.THINKING, RuntimeState.ERROR},
    RuntimeState.VERIFYING: {RuntimeState.EXECUTING, RuntimeState.SPEAKING, RuntimeState.IDLE, RuntimeState.ERROR},
    RuntimeState.SPEAKING: {RuntimeState.LISTENING, RuntimeState.IDLE, RuntimeState.EXECUTING, RuntimeState.ERROR},
    RuntimeState.RECOVERING: {RuntimeState.BOOTING, RuntimeState.IDLE, RuntimeState.LISTENING, RuntimeState.ERROR, RuntimeState.STOPPED},
    RuntimeState.ERROR: {RuntimeState.RECOVERING, RuntimeState.BOOTING, RuntimeState.IDLE, RuntimeState.STOPPED},
    RuntimeState.STOPPED: {RuntimeState.BOOTING},
}


@dataclass
class StateTransition:
    at: float
    from_state: str
    to_state: str
    external_state: str
    detail: str
    valid: bool
    elapsed_ms: int


class JarvisStateMachine:
    """Observa o legado sem quebrar a GUI e detecta transicoes incoerentes.

    O V7 inicialmente nao bloqueia transicoes invalidas: ele as contabiliza.
    Isso permite endurecer o sistema com dados reais antes de tornar a FSM strict.
    """

    def __init__(self, history_size: int = 80):
        self._lock = threading.RLock()
        self._state = RuntimeState.BOOTING
        self._external_state = "PREPARANDO"
        self._detail = ""
        self._changed_at = time.monotonic()
        self._history: Deque[StateTransition] = deque(maxlen=max(20, int(history_size)))
        self._invalid_count = 0

    @staticmethod
    def canonical(external_state: str) -> RuntimeState:
        key = str(external_state or "").strip().upper()
        return EXTERNAL_TO_RUNTIME.get(key, RuntimeState.THINKING)

    def observe(self, external_state: str, detail: str = "") -> StateTransition:
        now = time.monotonic()
        new_state = self.canonical(external_state)
        with self._lock:
            previous = self._state
            elapsed_ms = int(round((now - self._changed_at) * 1000))
            valid = new_state == previous or new_state in ALLOWED.get(previous, set())
            if not valid:
                self._invalid_count += 1
            transition = StateTransition(
                at=time.time(),
                from_state=previous.value,
                to_state=new_state.value,
                external_state=str(external_state or ""),
                detail=str(detail or ""),
                valid=valid,
                elapsed_ms=elapsed_ms,
            )
            self._history.append(transition)
            self._state = new_state
            self._external_state = str(external_state or "")
            self._detail = str(detail or "")
            self._changed_at = now
            return transition

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "canonical_state": self._state.value,
                "external_state": self._external_state,
                "detail": self._detail,
                "state_age_ms": int(round((time.monotonic() - self._changed_at) * 1000)),
                "invalid_transitions": self._invalid_count,
                "history": [asdict(x) for x in list(self._history)[-12:]],
            }

# Backwards compatibility for older imports.
ZeroStateMachine = JarvisStateMachine
