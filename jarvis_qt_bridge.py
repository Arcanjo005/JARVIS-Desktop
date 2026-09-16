"""Qt-safe bridge between the new JARVIS UI and the existing runtime.

This module deliberately contains no visual code.  It owns conversation
persistence and conversational streaming so the PySide6 shell can be rebuilt
without inheriting the legacy Tk widget/controller hierarchy.
"""
from __future__ import annotations

import threading
from typing import Iterable

from PySide6.QtCore import QObject, Signal, Slot

from memory_store import MemoryStore


class JarvisQtBridge(QObject):
    """Thread-safe facade used by the Qt shell.

    The existing ``JarvisCore`` remains the source of conversational responses.
    Network/model work runs in a daemon thread and only Qt signals cross back to
    the GUI thread.
    """

    conversations_changed = Signal(list)
    conversation_loaded = Signal(int, str, list)
    user_message_saved = Signal(dict)
    response_started = Signal(int)
    response_chunk = Signal(int, str)
    response_finished = Signal(int, str)
    response_failed = Signal(int, str)
    busy_changed = Signal(bool)

    def __init__(self, core, logger=None, parent: QObject | None = None):
        super().__init__(parent)
        self.core = core
        self.logger = logger
        self.memory = MemoryStore(logger=logger)
        self._lock = threading.RLock()
        self._generation = 0
        self._closed = False
        self.active_conversation_id = self.memory.get_or_create_active_conversation()

    def _log(self, level: str, text: str) -> None:
        target = getattr(self.logger, level, None) if self.logger is not None else None
        if callable(target):
            try:
                target(text, "QT")
            except TypeError:
                try:
                    target(text)
                except Exception:
                    pass
            except Exception:
                pass

    def _next_generation(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return not self._closed and generation == self._generation

    @Slot()
    def refresh_conversations(self) -> None:
        rows = self.memory.list_conversations(limit=80)
        self.conversations_changed.emit(rows)

    @Slot()
    def load_active_conversation(self) -> None:
        self.load_conversation(self.active_conversation_id)

    @Slot(int)
    def load_conversation(self, conversation_id: int) -> None:
        if not self.memory.switch_conversation(int(conversation_id)):
            return
        with self._lock:
            self._generation += 1
            self.active_conversation_id = int(conversation_id)
        title = self.memory.get_conversation_title(self.active_conversation_id)
        rows = self.memory.load_messages(self.active_conversation_id, limit=500)
        self.conversation_loaded.emit(self.active_conversation_id, title, rows)
        self.refresh_conversations()

    @Slot()
    def new_conversation(self) -> None:
        conversation_id = self.memory.create_conversation()
        with self._lock:
            self._generation += 1
            self.active_conversation_id = conversation_id
        self.conversation_loaded.emit(conversation_id, "Nova conversa", [])
        self.refresh_conversations()

    def _conversation_context(self, conversation_id: int) -> list[dict]:
        rows = self.memory.recent_context(conversation_id, limit=24)
        return [
            {
                "sender": row.get("sender", ""),
                "message": row.get("message", ""),
                "is_user": bool(row.get("is_user")),
                "is_jarvis": bool(row.get("is_jarvis")),
                "is_system": bool(row.get("is_system")),
            }
            for row in rows
        ]

    @Slot(str)
    def send_message(self, text: str) -> None:
        message = " ".join(str(text or "").split()).strip()
        if not message:
            return

        with self._lock:
            if self._closed:
                return
            conversation_id = self.active_conversation_id
            generation = self._next_generation()

        # Context must represent the state before the current user turn, because
        # ``message`` is passed separately to JarvisCore.
        history = self._conversation_context(conversation_id)
        message_id = self.memory.save_message(
            conversation_id,
            "Você",
            message,
            is_user=True,
        )
        self.user_message_saved.emit(
            {
                "id": message_id,
                "sender": "Você",
                "message": message,
                "is_user": True,
                "is_jarvis": False,
                "is_system": False,
            }
        )
        self.refresh_conversations()
        self.busy_changed.emit(True)
        self.response_started.emit(generation)

        worker = threading.Thread(
            target=self._response_worker,
            args=(generation, conversation_id, message, history),
            name=f"JARVIS-QT-CHAT-{generation}",
            daemon=True,
        )
        worker.start()

    def _response_worker(
        self,
        generation: int,
        conversation_id: int,
        message: str,
        history: list[dict],
    ) -> None:
        try:
            def on_chunk(chunk: str) -> None:
                if self._is_current(generation):
                    self.response_chunk.emit(generation, str(chunk or ""))

            response = self.core.process_message_stream(
                message,
                history,
                [],
                "",
                on_chunk=on_chunk,
                speaker_name="",
                source="text",
            )
            response = str(response or "").strip()
            if not self._is_current(generation):
                return
            if not response:
                response = "Não consegui produzir uma resposta neste turno."
            self.memory.save_message(
                conversation_id,
                "JARVIS",
                response,
                is_jarvis=True,
            )
            self.response_finished.emit(generation, response)
            self.refresh_conversations()
        except Exception as exc:
            self._log("error", f"Falha no chat Qt: {type(exc).__name__}: {exc}")
            if self._is_current(generation):
                self.response_failed.emit(generation, "Não consegui concluir essa resposta.")
        finally:
            if self._is_current(generation):
                self.busy_changed.emit(False)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._generation += 1
        try:
            self.memory.close()
        except Exception:
            pass


__all__ = ["JarvisQtBridge"]
