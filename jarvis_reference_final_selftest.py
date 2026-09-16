#!/usr/bin/env python3
"""Focused regression gates for the approved JARVIS 1.3.12 experience."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
checks = 0


def check(value, message):
    global checks
    checks += 1
    if not value:
        raise AssertionError(message)


def main():
    final_source = (ROOT / "gui_reference_final_1312.py").read_text(encoding="utf-8")
    release_source = (ROOT / "gui_reference_release_1312.py").read_text(encoding="utf-8")
    speech_source = (ROOT / "jarvis_natural_tts_1312.py").read_text(encoding="utf-8")
    asset_source = (ROOT / "jarvis_reference_asset.py").read_text(encoding="utf-8")
    prepare = (ROOT / "tools" / "prepare_release.py").read_text(encoding="utf-8")
    build = (ROOT / "build" / "build_windows.ps1").read_text(encoding="utf-8")

    check("class JarvisGUI(ConversationJarvisGUI)" in final_source,
          "shell 1.3.12 nao herda a shell funcional de conversa")
    check("_reference_chat_panel" in final_source and "_set_reference_chat_visible" in final_source,
          "shell 1.3.12 perdeu restauracao real do chat")
    check("def send_message" in final_source and "_set_reference_chat_visible(True)" in final_source,
          "enviar mensagem nao reabre o chat")
    check("def _switch_conversation" in final_source and "_set_reference_chat_visible(True)" in final_source,
          "abrir historico nao restaura o chat")
    check("self.chat_scroll.master.grid_remove()" not in final_source,
          "regressao: chat voltou a ser removido incondicionalmente")
    check("ImageOps.fit" in final_source and "render_reference_scene" not in final_source,
          "interface ainda pode voltar ao cenário procedural antigo")
    check("Digite sua mensagem..." in final_source and "_reference_settings_button" in final_source,
          "composer 1.3.12 nao segue a referencia")
    check("_reference_update_badge" in final_source and 'text="1"' in final_source,
          "badge de atualizacao da referencia ausente")

    check("v8:clarify_search_topic" in final_source and "_repair_reference_url" in final_source,
          "busca contextual nao bloqueia pronome literal")
    check("_topic_from_history" in final_source and "youtube.com/results?search_query=" in final_source,
          "follow-up de YouTube nao recupera assunto anterior")

    check("NaturalSpeechTTS1312" in release_source,
          "release nao usa o novo caminho de fala natural")
    check("pt-BR-MacerioMultilingualNeural" in speech_source and "pt-BR-AntonioNeural" in speech_source,
          "voz natural primaria/fallback nao configuradas")
    check("target = 1100" in speech_source and "hard = 1450" in speech_source,
          "TTS voltou a fragmentar respostas em trechos curtos")
    check("mixer.music.get_pos()" in speech_source,
          "legenda nao usa a posicao real de reproducao")
    check("_caption_segments" in speech_source and "time.sleep(0.010)" in speech_source,
          "legenda progressiva nao esta ligada ao loop de audio")

    check("REFERENCE_WIDTH = 2560" in asset_source and "REFERENCE_HEIGHT = 1440" in asset_source,
          "asset aprovado nao exige resolucao 2560x1440")
    check("len(joined) != 72880" in asset_source and "base64.b64decode(joined, validate=True)" in asset_source,
          "asset nao tem gate de integridade base64")
    check("from gui_reference_release_1312 import JarvisGUI" in prepare,
          "prepare_release nao ativa a shell 1.3.12")
    check("jarvis_reference_scene_1440p.jpg" in prepare and 'ROOT / "data"' in prepare,
          "prepare_release nao stageia o cenário na pasta empacotada")
    check('"--add-data", "$DataDir;data"' in build,
          "build deixou de incluir a pasta data que carrega o cenário")

    # Reconstruct and validate the actual scene now.  This catches missing or
    # truncated chunks before a Windows installer can be published.
    from jarvis_reference_asset import ensure_reference_scene
    from PIL import Image

    asset = ensure_reference_scene(ROOT, validate=True)
    check(asset.is_file() and asset.stat().st_size > 50000,
          "JPEG aprovado nao foi reconstruido")
    with Image.open(asset) as image:
        check(tuple(image.size) == (2560, 1440),
              f"scene asset tem tamanho errado: {image.size}")
        check(str(image.format or "").upper() == "JPEG",
              f"scene asset nao e JPEG: {image.format}")

    # Pure context regression test: no Tk window required.
    from gui_reference_final_1312 import JarvisGUI
    from gui_conversation_shell import JarvisGUI as ConversationJarvisGUI
    check(issubclass(JarvisGUI, ConversationJarvisGUI),
          "MRO 1.3.12 perdeu a shell de producao")

    probe = object.__new__(JarvisGUI)
    probe._reference_last_search_topic = "RTX 5060"
    command, resolved, raw = JarvisGUI._resolve_browser_context(
        probe, "v8:browser_search:Opera|isso no YouTube"
    )
    check("youtube.com/results?search_query=RTX+5060" in command,
          "'isso no YouTube' ainda pode pesquisar literalmente 'isso'")
    check(resolved == "RTX 5060" and raw == "isso no YouTube",
          "assunto RTX 5060 nao foi preservado no follow-up")

    # Speech unit checks without network/audio devices.
    from jarvis_natural_tts_1312 import NaturalSpeechTTS1312
    long_answer = " ".join(["Esta frase explica o projeto com naturalidade."] * 12)
    chunks = NaturalSpeechTTS1312._split_text(long_answer)
    check(len(chunks) <= 2,
          f"fala longa ainda foi fragmentada demais: {len(chunks)} chunks")
    captions = NaturalSpeechTTS1312._caption_segments(
        "O ESP32 possui Wi-Fi integrado, pode controlar sensores e também automatizar sua bancada de eletrônica."
    )
    check(len(captions) >= 2 and max(len(x.split()) for x in captions) <= 9,
          "legendas nao foram quebradas em frases curtas acompanhaveis")

    print(f"JARVIS FINAL REFERENCE SELFTEST: PASS ({checks} verificacoes)")


if __name__ == "__main__":
    main()
