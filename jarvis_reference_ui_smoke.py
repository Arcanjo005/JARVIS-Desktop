#!/usr/bin/env python3
"""Real Tk smoke test for the final 1.3.12 production shell."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace

from PIL import ImageGrab

from gui_reference_release_1312 import JarvisGUI
from jarvis_ui_selftest import CaptureLogger

ROOT = Path(__file__).resolve().parent


class ReferenceTestApplication(JarvisGUI):
    def _start_deferred_runtime(self):
        pass

    def _start_persistent_reminder_watcher(self):
        pass

    def _start_jarvis_player_watcher(self):
        pass

    def _v136_schedule_prewarm(self):
        pass

    def _process_message(self, message, source="text"):
        token = self._begin_work_generation()
        self.requests.append((token, message, source))
        return token


def pump(app, seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.root.update()
        time.sleep(0.006)
    app.root.update_idletasks()


def check(value, message):
    if not value:
        raise AssertionError(message)


def main():
    evidence = ROOT / "validation"
    evidence.mkdir(exist_ok=True)
    old = {key: os.environ.get(key) for key in ("JARVIS_APP_DIR", "LOCALAPPDATA", "GEMINI_API_KEY")}
    logger = CaptureLogger()
    app = None
    with tempfile.TemporaryDirectory(prefix="jarvis-reference-ui-") as td:
        os.environ["JARVIS_APP_DIR"] = td
        os.environ["LOCALAPPDATA"] = td
        os.environ.pop("GEMINI_API_KEY", None)
        try:
            app = ReferenceTestApplication(logger, SimpleNamespace(), SimpleNamespace())
            app.requests = []
            app.root.geometry("1360x820")
            pump(app, 1.0)

            check(app._reference_scene_source is not None, "scene 1440p real nao foi carregada")
            check(tuple(app._reference_scene_source.size) == (2560, 1440), "scene carregada com dimensao incorreta")
            check(app._reference_chat_panel is not None, "painel real do chat nao existe")

            # A home cinematic may collapse an empty transcript, but the actual
            # widget must still exist and become visible as soon as chat starts.
            app._set_reference_chat_visible(False)
            pump(app, 0.12)
            check(not app._reference_chat_panel.winfo_viewable(), "home vazio nao recolheu transcript")
            app.add_message("Voce", "TESTE-CHAT-VISIVEL", is_user=True)
            pump(app, 0.22)
            check(app._reference_chat_panel.winfo_viewable(), "chat nao voltou ao receber mensagem")
            check(any("TESTE-CHAT-VISIVEL" in row.get("message", "") for row in app.chat_history),
                  "mensagem nao entrou no historico real")

            # Saved-conversation opening must also restore the real chat surface.
            conversation_id = app.active_conversation_id
            app._new_conversation()
            pump(app, 0.12)
            check(not app._reference_chat_panel.winfo_viewable(), "nova conversa vazia deveria abrir na home")
            app._switch_conversation(conversation_id)
            pump(app, 0.28)
            check(app._reference_chat_panel.winfo_viewable(), "historico nao reabriu o chat")

            # Composer stays interactive after all home/chat transitions.
            app._composer_focus_in()
            app.text_input.delete("1.0", "end")
            app.text_input.insert("1.0", "Mensagem depois de restaurar o chat")
            app.send_button.invoke()
            pump(app, 0.08)
            check(app.requests and app.requests[-1][1] == "Mensagem depois de restaurar o chat",
                  "composer deixou de enviar depois das transicoes")

            # Capture the actual final shell as CI evidence.
            x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
            w, h = app.root.winfo_width(), app.root.winfo_height()
            if w > 20 and h > 20:
                ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(evidence / "reference-1312-smoke.png")

            check(not logger.errors, "erros de controller/Tk: " + repr(logger.errors))
            print("JARVIS REFERENCE UI SMOKE: PASS")
        finally:
            if app is not None:
                try:
                    app._orb_worker.close()
                except Exception:
                    pass
                try:
                    app.root.destroy()
                except Exception:
                    pass
                try:
                    app.memory_store.close()
                except Exception:
                    pass
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    main()
