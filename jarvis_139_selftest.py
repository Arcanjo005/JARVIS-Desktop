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
    scene = (ROOT / "jarvis_reference_scene_139.py").read_text(encoding="utf-8")
    overlay = (ROOT / "jarvis_voice_overlay_139.py").read_text(encoding="utf-8")
    hot = (ROOT / "hot_update_runtime.py").read_text(encoding="utf-8")
    antonio = (ROOT / "jarvis_antonio_tts.py").read_text(encoding="utf-8")
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")

    check("_setup_desktop_integration" in shell and "JARVIS-BOOT-DESKTOP-SAFE" in shell,
          "bandeja/hotkey nao sao restaurados no boot seguro")
    check("Copiar conversa" in shell and "_copy_conversation" in shell,
          "botao de copiar conversa nao esta exposto")
    check("Nova conversa" in shell and "Buscar conversas" in shell and "JARVIS" in shell,
          "barra lateral deixou de representar conversas como na referencia")
    check("JARVIS fala" in shell and "Legenda na tela" in shell and "Modo Rápido" in shell and "Modo Detalhado" in shell,
          "dock inferior nao contem os controles da referencia")

    # Validate the actual scene contract instead of comments/variable names.
    # The previous check looked for the literal words "pedestal" and "waveform",
    # which made harmless source cleanup fail the release even when the renderer
    # remained connected and functional.
    check("from jarvis_reference_scene_139 import render_reference_scene" in shell,
          "shell nao importa o renderer cinematografico de referencia")
    check("render_reference_scene(" in shell and "def render_reference_scene(" in scene,
          "cenario cinematografico de referencia nao esta conectado")
    from jarvis_reference_scene_139 import render_reference_scene
    probe = render_reference_scene(320, 180)
    check(getattr(probe, "size", None) == (320, 180) and getattr(probe, "mode", None) == "RGB",
          "renderer cinematografico nao produz uma cena RGB valida")

    compact_shell = "".join(shell.split())
    check("_fast_standalone_question" in shell and "conversation_history=list(conversation_historyor[])[-2:]" in compact_shell,
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
    check("from voice_overlay_qt import _run_child" in main_src,
          "bootstrap principal foi alterado desnecessariamente")

    from jarvis_voice_overlay_139 import (
        _visible_orb_geometry,
        clamp_overlay_position,
        corner_overlay_position,
    )

    left, top, right, bottom = 0, 0, 1920, 1040
    width, height = 420, 160
    orb_cx, orb_cy, radius = _visible_orb_geometry(width, height)

    x, y = corner_overlay_position(width, height, left, top, right, bottom, 0)
    check(x + orb_cx + radius <= right, "esfera ultrapassou borda direita")
    check(y + orb_cy + radius <= bottom, "esfera ultrapassou borda inferior")
    check(x + width > right, "canvas transparente ainda esta artificialmente preso na direita")
    check(y + height > bottom, "canvas transparente ainda esta artificialmente preso embaixo")

    free_x, free_y = clamp_overlay_position(-9999, -9999, width, height, left, top, right, bottom, 0)
    check(free_x < left, "barreira invisivel esquerda ainda limita o canvas em vez da esfera")
    check(free_x + orb_cx - radius >= left,
          "esfera ficou parcialmente fora da borda esquerda")

    orb_top = free_y + orb_cy - radius
    check(0 <= orb_top <= 8,
          "limite superior reservou espaco invisivel alem da margem fisica da esfera")
    check(free_y < height,
          "limite superior esta usando a altura inteira do canvas")

    _, low_y = clamp_overlay_position(0, 99999, width, height, left, top, right, bottom, 0)
    check(low_y + height > bottom,
          "barreira invisivel inferior ainda limita o canvas em vez da esfera")
    check(low_y + orb_cy + radius <= bottom,
          "esfera ultrapassou borda inferior ao liberar canvas")

    print("JARVIS 1.3.9 SELFTEST: PASS")


if __name__ == "__main__":
    main()
