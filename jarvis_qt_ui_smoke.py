#!/usr/bin/env python3
"""Headless structural smoke for the rebuilt PySide6 desktop shell."""
from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from gui_qt_reference import JarvisGUI


class Logger:
    def info(self, *args, **kwargs):
        pass

    def system(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class Core:
    def process_message_stream(self, message, history, memories, system_commands_info="", on_chunk=None, **kwargs):
        answer = f"Resposta Qt para: {message}"
        if callable(on_chunk):
            on_chunk("Resposta Qt ")
            on_chunk(f"para: {message}")
        return answer


def wait(ms=100):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def check(value, message):
    if not value:
        raise AssertionError(message)


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="jarvis-qt-smoke-") as td:
        os.environ["JARVIS_APP_DIR"] = td
        window = JarvisGUI(Logger(), object(), Core())
        window.resize(1280, 780)
        window.show()
        wait(120)

        check(window.sidebar.width() == 292, "sidebar Qt perdeu largura de referencia")
        check(window.transcript_frame.isVisible(), "chat Qt nao esta visivel")
        check(window.composer.isVisible(), "composer Qt nao esta visivel")
        check(window.scene.isVisible(), "cena Qt nao esta visivel")
        check(window.history is not None, "historico Qt ausente")

        window.composer.submitted.emit("teste funcional")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            app.processEvents()
            rows = window.bridge.memory.load_messages(window.bridge.active_conversation_id)
            if len(rows) >= 2:
                break
            time.sleep(0.01)
        rows = window.bridge.memory.load_messages(window.bridge.active_conversation_id)
        check(any(row.get("is_user") and row.get("message") == "teste funcional" for row in rows),
              "mensagem do usuario nao persistiu")
        check(any(row.get("is_jarvis") and "Resposta Qt para" in row.get("message", "") for row in rows),
              "resposta Qt nao persistiu")

        old_id = window.bridge.active_conversation_id
        window.bridge.new_conversation()
        app.processEvents()
        check(window.bridge.active_conversation_id != old_id, "nova conversa Qt nao mudou sessao")
        check(window.transcript_frame.isVisible(), "nova conversa ocultou o chat Qt")

        window.close()
        app.processEvents()
    print("JARVIS QT UI SMOKE: PASS")


if __name__ == "__main__":
    main()
