#!/usr/bin/env python3
"""Focused non-interactive regression checks for JARVIS Desktop 1.3.9."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    shell = (ROOT / "gui_conversation_shell.py").read_text(encoding="utf-8")
    overlay = (ROOT / "jarvis_voice_overlay_139.py").read_text(encoding="utf-8")
    hot = (ROOT / "hot_update_runtime.py").read_text(encoding="utf-8")
    antonio = (ROOT / "jarvis_antonio_tts.py").read_text(encoding="utf-8")
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")

    check("_setup_desktop_integration" in shell and "JARVIS-BOOT-DESKTOP-SAFE" in shell,
          "bandeja/hotkey nao sao restaurados no boot seguro")
    check("Copiar conversa" in shell and "_copy_conversation" in shell,
          "botao de copiar conversa nao esta exposto")
    check("_fast_standalone_question" in shell and "conversation_history = list(conversation_history or [])[-2:]" in shell,
          "fast path de perguntas simples ausente")
    check("v8:browser_search:" in shell and "Certo, pesquisando." in shell,
          "ack imediato de pesquisa ausente")
    check("jarvis_voice_overlay_139" in shell,
          "shell nao usa overlay 1.3.9")
    check("JARVIS_OVERLAY_139" in overlay and "env=child_env" in overlay,
          "processo filho congelado nao recebe marcador 1.3.9")
    check("JARVIS_OVERLAY_139" in hot and 'sys.modules["voice_overlay_qt"] = overlay_139' in hot,
          "bootstrap do filho nao redireciona overlay 1.3.9")
    check("def prefetch(" in antonio and "self._synthesize(chunk)" in antonio,
          "prefetch Antonio nao esta implementado")
    # main.py remains on the stable child entry point; routing happens only in
    # the tagged child through hot_update_runtime.
    check("from voice_overlay_qt import _run_child" in main_src,
          "bootstrap principal foi alterado desnecessariamente")

    from jarvis_voice_overlay_139 import clamp_overlay_position, corner_overlay_position

    # Conversation canvas is 420x160, but only the sphere near (210,38) must be
    # kept visible. The transparent subtitle canvas is allowed beyond the edge.
    left, top, right, bottom = 0, 0, 1920, 1040
    x, y = corner_overlay_position(420, 160, left, top, right, bottom, 0)
    orb_cx, orb_cy, radius = 210, 38, 38
    check(x + orb_cx + radius <= right, "esfera ultrapassou borda direita")
    check(y + orb_cy + radius <= bottom, "esfera ultrapassou borda inferior")
    check(x + 420 > right, "canvas transparente ainda esta artificialmente preso na tela")

    free_x, free_y = clamp_overlay_position(-180, -20, 420, 160, left, top, right, bottom, 0)
    check(free_x < 0, "barreira invisivel esquerda ainda limita o canvas em vez da esfera")
    check(free_y <= 0, "barreira invisivel superior ainda limita o canvas em vez da esfera")

    print("JARVIS 1.3.9 SELFTEST: PASS")


if __name__ == "__main__":
    main()
