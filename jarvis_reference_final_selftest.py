#!/usr/bin/env python3
"""Focused checks for the final reference-first JARVIS shell."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check(value, message):
    if not value:
        raise AssertionError(message)


def main():
    source = (ROOT / "gui_reference_final_1311.py").read_text(encoding="utf-8")
    prepare = (ROOT / "tools" / "prepare_release.py").read_text(encoding="utf-8")

    check("class JarvisGUI(ConversationJarvisGUI)" in source,
          "shell final nao herda a shell funcional de conversa")
    check("Digite sua mensagem..." in source and "_reference_settings_button" in source,
          "composer final nao corresponde a referencia aprovada")
    check("_reference_update_badge" in source and 'text="1"' in source,
          "badge de atualizacao da referencia nao foi implementado")
    check("_layout_reference_overlays" in source and "self.input_shell.place(" in source,
          "composer nao esta sobreposto ao hero cinematografico")
    check("_resolve_browser_context" in source and "youtube.com/results?search_query=" in source,
          "resolucao contextual de YouTube nao esta presente")
    check("from gui_reference_final_1311 import JarvisGUI" in prepare,
          "release nao ativa a shell final")

    from gui_reference_final_1311 import JarvisGUI
    from gui_conversation_shell import JarvisGUI as ConversationJarvisGUI
    check(issubclass(JarvisGUI, ConversationJarvisGUI),
          "MRO da interface final perdeu a shell de producao")

    probe = object.__new__(JarvisGUI)
    probe._reference_last_search_topic = "RTX 5060"
    command, resolved, raw = JarvisGUI._resolve_browser_context(
        probe, "v8:browser_search:Opera|isso no YouTube"
    )
    check("youtube.com/results?search_query=RTX+5060" in command,
          "follow-up 'isso no YouTube' ainda pesquisa literalmente 'isso'")
    check(resolved == "RTX 5060" and raw == "isso no YouTube",
          "topico contextual nao foi preservado")

    print("JARVIS FINAL REFERENCE SELFTEST: PASS")


if __name__ == "__main__":
    main()
