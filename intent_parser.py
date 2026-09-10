"""JARVIS - normalização local de comandos e fast-lane de voz.

Objetivos:
- aceitar linguagem natural sem mandar comandos claros ao Gemini;
- corrigir erros comuns de STT sem transformar conversa normal em comando;
- permitir ao voice_engine decidir quando uma transcrição Vosk já é segura
  o bastante para pular o Whisper e reduzir latência.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

try:
    from universal_app_resolver import load_voice_terms
except Exception:
    load_voice_terms = None


try:
    from semantic_language import (
        resolve_self_correction, normalize_broken_command, classify_speech_act,
        normalize_action_utterance,
    )
except Exception:
    resolve_self_correction = lambda text: " ".join(str(text or "").split()).strip()
    normalize_broken_command = resolve_self_correction
    classify_speech_act = lambda text: "neutral"
    normalize_action_utterance = resolve_self_correction


APP_WORDS = {
    "opera", "opera gx", "spotify", "photoshop", "illustrator", "corel",
    "coreldraw", "comercial", "obs", "obs studio", "revo", "geek",
    "paint", "explorer", "gerenciador de arquivos", "chatgpt", "chat gpt",
    "bloodstrike", "blood strike", "calculadora", "bloco de notas",
}

ACTION_WORDS = {
    "abre", "abra", "abrir", "feche", "fecha", "fechar",
    "minimize", "minimiza", "minimizar", "maximize", "maximiza", "maximizar",
    "expanda", "expande", "expandir", "amplie", "amplia", "ampliar",
    "restaure", "restaura", "restaurar", "mova", "move", "mover", "joga", "jogue",
    "volume", "mute", "mudo", "pausa", "pause", "continua", "continue",
    "proxima", "próxima", "anterior", "musica", "música", "spotify", "youtube",
    "brilho", "screenshot", "captura", "pesquise", "pesquisar", "procure", "buscar",
    "som", "headset", "microfone", "monitor", "desligue", "reinicie", "suspenda",
    "diagnostico", "diagnóstico", "rede", "lixeira", "apague", "delete", "exclua",
}

_DYNAMIC_APP_TERMS = set()
_DYNAMIC_APP_TERMS_AT = 0.0


def _is_known_local_app_term(value: str) -> bool:
    """Confere nomes locais sem transformar o catálogo global em gatilho de comando."""
    global _DYNAMIC_APP_TERMS, _DYNAMIC_APP_TERMS_AT
    key = normalized_key(value)
    if not key:
        return False
    now = time.monotonic()
    if load_voice_terms is not None and (not _DYNAMIC_APP_TERMS or now - _DYNAMIC_APP_TERMS_AT > 60.0):
        try:
            terms = load_voice_terms(str(Path(os.environ.get("JARVIS_APP_DIR") or Path(__file__).resolve().parent)), limit=1200)
            _DYNAMIC_APP_TERMS = {normalized_key(term) for term in terms if normalized_key(term)}
            _DYNAMIC_APP_TERMS_AT = now
        except Exception:
            pass
    compact = key.replace(" ", "")
    key_versionless = re.sub(r"\b20\d{2}\b", " ", key)
    key_versionless = re.sub(r"\s+", " ", key_versionless).strip()
    compact_versionless = key_versionless.replace(" ", "")
    return any(
        key == term
        or compact == term.replace(" ", "")
        or key_versionless == term
        or compact_versionless == term.replace(" ", "")
        for term in _DYNAMIC_APP_TERMS
    )


def strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def normalized_key(value: str) -> str:
    value = strip_accents(value).lower()
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


_NUMBERS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
    "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13,
    "catorze": 14, "quatorze": 14, "quinze": 15, "dezesseis": 16,
    "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20,
    "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60,
    "setenta": 70, "oitenta": 80, "noventa": 90, "cem": 100,
}


def parse_pt_number(value: str) -> Optional[int]:
    clean = normalized_key(value)
    if clean.isdigit():
        return int(clean)
    if clean in _NUMBERS:
        return _NUMBERS[clean]
    parts = [p for p in clean.split() if p != "e"]
    if len(parts) == 2 and parts[0] in _NUMBERS and parts[1] in _NUMBERS:
        tens = _NUMBERS[parts[0]]
        unit = _NUMBERS[parts[1]]
        if tens in (20, 30, 40, 50, 60, 70, 80, 90) and 0 <= unit <= 9:
            return tens + unit
    return None


def _remove_politeness(value: str) -> str:
    # Prefixos ordenados dos mais longos aos mais curtos.
    patterns = [
        r"^eu\s+quero\s+que\s+voce\s+",
        r"^eu\s+gostaria\s+que\s+voce\s+",
        r"^eu\s+gostaria\s+que\s+",
        r"^quero\s+que\s+voce\s+",
        r"^quero\s+que\s+",
        r"^eu\s+quero\s+",
        r"^quero\s+",
        r"^gostaria\s+que\s+voce\s+",
        r"^sera\s+que\s+voce\s+pode\s+",
        r"^voce\s+consegue\s+",
        r"^voce\s+pode\s+",
        r"^pode\s+por\s+favor\s+",
        r"^pode\s+",
        r"^poderia\s+",
        r"^faz\s+o\s+favor\s+de\s+",
        r"^por\s+favor\s+",
    ]
    raw = value
    key = normalized_key(raw)
    for _ in range(4):
        changed = False
        for pattern in patterns:
            match = re.match(pattern, key, flags=re.I)
            if match:
                # Removemos pelo número de palavras capturadas no texto normalizado.
                consumed_words = len(match.group(0).split())
                words = raw.split()
                raw = " ".join(words[consumed_words:]).strip()
                key = normalized_key(raw)
                changed = True
                break
        if not changed:
            break
    return raw


def normalize_command(message: str) -> str:
    original = " ".join(str(message or "").split()).strip()
    value = original.strip(" \t\r\n,.;:!?")
    if not value:
        return ""

    original_key = normalized_key(value)

    # Interrupção é um comando real; aceite JARVIS e mantenha Zero como legado.
    if original_key in {"jarvis para", "para jarvis", "jarvis pare", "pare jarvis", "jarvis cancela", "cancela jarvis",
                        "jarbas para", "para jarbas", "jarves para", "para jarves", "jervis para", "para jervis",
                        "zero para", "para zero", "zero pare", "pare zero", "zero cancela", "cancela zero"}:
        return "jarvis para"

    had_assistant_prefix = bool(re.match(r"^(?:jarvis|jarbas|jarves|jervis|zero)\b", original_key))

    # Wake vazando para o comando.
    value = re.sub(
        r"^(?:(?:oi|ol[aá]|ei|e\s*a[ií]|eae)\s+(?:jarvis|jarbas|jarves|jervis|jarvi|jarvisse|ja\s+vis|zero)|(?:jarvis|jarbas|jarves|jervis|jarvi|jarvisse|ja\s+vis|zero))\s*[,\-:]?\s+",
        "",
        value,
        flags=re.I,
    ).strip()

    # V6.3: pontuacao do STT nao pode quebrar "Abrir, Open".
    value = re.sub(r"[,;:]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    # Variacoes naturais/ruidosas: "se voce abre o OBS" / "se abra o Opera".
    value = re.sub(
        r"^se\s+(?:voc[eê]\s+)?(abre|abra|abrir|fecha|feche|fechar|minimiza|minimize|maximiza|maximize)\s+",
        r"\1 ", value, flags=re.I,
    )
    value = re.sub(
        r"^voc[eê]\s+(abre|abra|fecha|feche|minimiza|minimize|maximiza|maximize)\s+",
        r"\1 ", value, flags=re.I,
    )

    value = _remove_politeness(value)

    # Hotfix 4: a mesma camada semântica usada pelo Router atua antes da
    # fast-lane. Autocorreções explícitas podem ser aceleradas; negações e
    # afirmações ficam fora da fast-lane para nunca disparar ação por engano.
    value = resolve_self_correction(value)
    value = normalize_broken_command(value)
    speech_act = classify_speech_act(value)
    if speech_act in {"negated_command", "assertion"}:
        return re.sub(r"\s+", " ", value).strip()
    value = normalize_action_utterance(value)

    value = re.sub(
        r"(?:[,;]?\s+(?:por\s+favor|pra\s+mim|para\s+mim|por\s+gentileza|a[ií]))+$",
        "",
        value,
        flags=re.I,
    ).strip(" ,.;:!?")

    # Frases de diagnóstico/capacidades que devem permanecer 100% locais.
    status_key = normalized_key(value)
    if status_key in {
        "me diz como e que ta o pc", "me diz como esta o pc",
        "me diga como e que ta o pc", "me diga como esta o pc",
        "como e que ta o pc", "como e que esta o pc",
        "como ta o computador", "como esta o computador",
    }:
        value = "status do pc"

    capability_key = normalized_key(value)
    if capability_key in {
        "o que voce consegue fazer", "me diz o que voce consegue fazer",
        "me diga o que voce consegue fazer", "o que o jarvis consegue fazer", "o que o zero consegue fazer",
        "quais comandos voce tem", "quais sao seus comandos",
    }:
        value = "o que voce consegue fazer"

    # Correções observadas no uso real.
    fixes = [
        (r"^abriu\s+", "abre "),
        (r"^abri\s+e\s+", "abre "),
        (r"^abri\s+", "abre "),
        (r"^abrir\s+e\s+", "abre "),
        (r"^criam\s+", "criar "),
        (r"^criao\s+", "criar "),
        (r"^(?:para|pare)\s+(?:jarvis|jarbas|jarves|jervis|zero)$", "jarvis para"),
        (r"^placa\s+m[uú]sica\b", "coloca música"),
        (r"^pl[aá]ca\s+m[uú]sica\b", "coloca música"),
        (r"\bauto\s*falante\b", "alto falante"),
        (r"\bblunt\s*strike\b", "BloodStrike"),
        (r"\bblood\s*strike\b", "BloodStrike"),
        (r"\bliving\s+on\s+the\s+player\b", "Livin on a Prayer"),
        (r"\bleave\s+it\s+on\s+the\s+player\b", "Livin on a Prayer"),
        (r"\blivin\s+on\s+the\s+player\b", "Livin on a Prayer"),
        (r"\bliving\s+on\s+a\s+prayer\b", "Livin on a Prayer"),
        (r"\bsystem\s+of\s+federal\b", "System of a Down"),
    ]
    for pattern, replacement in fixes:
        value = re.sub(pattern, replacement, value, flags=re.I)

    if re.match(r"^(?:abre|abra|abrir)\b", value, flags=re.I):
        value = re.sub(r"\bpente\b", "Paint", value, flags=re.I)

    # V6.2 - correção contextual de nomes de aplicativos para STT.
    # Só atua quando a frase já é claramente um comando de janela/app, para
    # nunca trocar a palavra "open" em conversa comum por "Opera".
    app_command = re.match(
        r"^(abre|abra|abrir|feche|fecha|fechar|minimize|minimiza|minimizar|"
        r"maximize|maximiza|maximizar|restaure|restaura|restaurar|mova|move|mover)\s+(.+)$",
        value,
        flags=re.I,
    )
    if app_command:
        verb = app_command.group(1)
        target = app_command.group(2).strip()
        target_key = normalized_key(target)
        target_key = re.sub(r"^(?:o|a|um|uma)\s+", "", target_key).strip()
        stt_app_aliases = {
            "open": "Opera",
            "opem": "Opera",
            "openn": "Opera",
            "opera g x": "Opera GX",
            "opera gx": "Opera GX",
            "spot fy": "Spotify",
            "espotify": "Spotify",
            "fotoxop": "Photoshop",
            "photoshopp": "Photoshop",
            "obs estudio": "OBS Studio",
            "revo uninstall": "Revo Uninstaller",
            "corel dro": "CorelDRAW",
            "corel draw": "CorelDRAW",
            "chat gepete": "ChatGPT",
            "chat gpt": "ChatGPT",
            "notebook": "Bloco de Notas",
        }
        corrected = stt_app_aliases.get(target_key)
        if corrected:
            value = f"{verb} {corrected}"

    # Verbos naturais que o STT costuma produzir para abrir aplicativos.
    value = re.sub(
        r"^(?:inicia|inicie|iniciar|executa|execute|executar)\s+(?:o\s+|a\s+)?",
        "abre ",
        value,
        flags=re.I,
    )

    # V6 - linguagem natural para maximizar/expandir janelas.
    value = re.sub(
        r"^(?:expanda|expande|expandir|amplie|amplia|ampliar)\s+(?:o\s+|a\s+)?",
        "maximize ",
        value,
        flags=re.I,
    )

    # V6.3: "criam uma chamada Projeto na area de trabalho" e erros
    # semelhantes do STT sao interpretados como pasta chamada Projeto.
    malformed_folder = re.match(
        r"^(?:crie|cria|criar|criam|faz|faca)\s+(?:uma\s+)?(?:pasta\s+)?chamada\s+(.+?)\s+"
        r"(?:na|no|em)\s+(?:a\s+)?(?:area\s+de\s+trabalho|área\s+de\s+trabalho|desktop)$",
        value, flags=re.I,
    )
    if malformed_folder:
        value = f"crie pasta no desktop {malformed_folder.group(1).strip()}"

    # V6 - criacao de pasta na Area de Trabalho em linguagem natural.
    desktop_folder = re.match(
        r"^(?:crie|cria|criar|faca|faça|faz|fazer)\s+(?:uma\s+)?pasta\s+"
        r"(?:na|no|em)\s+(?:a\s+)?(?:area\s+de\s+trabalho|área\s+de\s+trabalho|desktop)"
        r"(?:\s+(?:chamada|com\s+o\s+nome|de\s+nome))?\s+(.+)$",
        value, flags=re.I,
    )
    if desktop_folder:
        value = f"crie pasta no desktop {desktop_folder.group(1).strip()}"
    else:
        desktop_folder_2 = re.match(
            r"^(?:crie|cria|criar|faca|faça|faz|fazer)\s+(?:uma\s+)?pasta\s+"
            r"(?:chamada|com\s+o\s+nome|de\s+nome)\s+(.+?)\s+"
            r"(?:na|no|em)\s+(?:a\s+)?(?:area\s+de\s+trabalho|área\s+de\s+trabalho|desktop)$",
            value, flags=re.I,
        )
        if desktop_folder_2:
            value = f"crie pasta no desktop {desktop_folder_2.group(1).strip()}"

    # V5.2 - comandos sobre a janela atual em linguagem natural.
    # Exemplos: "minimiza isso", "minimiza essa janela", "maximiza",
    # "passa essa janela pro outro monitor". O AdvancedWindows resolve
    # "janela atual" diretamente pelo HWND em primeiro plano.
    generic_window_key = normalized_key(value)
    if re.fullmatch(
        r"(?:minimize|minimiza|minimizar)(?: (?:isso|essa janela|esta janela|a janela|janela|janela atual|janela aberta|a janela aberta|a janela que esta aberta|o que esta aberto|o que ta aberto|essa tela|tela atual|programa|aplicativo|tela))?",
        generic_window_key,
    ):
        value = "minimize janela atual"
    elif re.fullmatch(
        r"(?:maximize|maximiza|maximizar)(?: (?:isso|essa janela|esta janela|a janela|janela|janela atual|janela aberta|a janela aberta|a janela que esta aberta|o que esta aberto|o que ta aberto|essa tela|tela atual|programa|aplicativo|tela))?",
        generic_window_key,
    ):
        value = "maximize janela atual"
    elif re.fullmatch(
        r"(?:restaure|restaura|restaurar)(?: (?:isso|essa janela|esta janela|a janela|janela|janela atual|janela aberta|a janela aberta|a janela que esta aberta|o que esta aberto|o que ta aberto|essa tela|tela atual|programa|aplicativo|tela))?",
        generic_window_key,
    ):
        value = "restaure janela atual"

    current_other = re.fullmatch(
        r"(?:passa|passe|passar|mova|move|mover|joga|jogue|manda|mande|leva|leve|coloca|coloque) "
        r"(?:(?:isso|essa janela|esta janela|a janela|janela|janela atual|janela aberta|a janela aberta|a janela que esta aberta|o que esta aberto|o que ta aberto|essa tela|tela atual|programa|aplicativo) )?"
        r"(?:para|pro|pra|no) (?:o )?outro monitor",
        generic_window_key,
    )
    if current_other:
        value = "mova janela atual para outro monitor"

    current_numbered = re.fullmatch(
        r"(?:passa|passe|passar|mova|move|mover|joga|jogue|manda|mande|leva|leve|coloca|coloque) "
        r"(?:(?:isso|essa janela|esta janela|a janela|janela|janela atual|janela aberta|a janela aberta|a janela que esta aberta|o que esta aberto|o que ta aberto|essa tela|tela atual|programa|aplicativo) )?"
        r"(?:para|pro|pra|no) (?:o )?(?:monitor )?(primeiro|segundo|terceiro|[123])(?: monitor)?",
        generic_window_key,
    )
    if current_numbered:
        token = current_numbered.group(1)
        idx = {
            "primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2,
            "terceiro": 3, "terceira": 3, "quarto": 4, "quarta": 4,
        }.get(token, int(token) if token.isdigit() else 1)
        value = f"mova janela atual para monitor {idx}"

    # "abre pra mim o Opera" que sobreviveu à limpeza de cortesia.
    value = re.sub(
        r"^(abre|abra|abrir)\s+(?:pra|para)\s+mim\s+",
        r"\1 ",
        value,
        flags=re.I,
    )

    # "transcreva/transfira a janela do Opera para o segundo monitor"
    move = re.match(
        r"^(?:transcreva|transfira|transfere|transfira|mova|move|joga|jogue)\s+"
        r"(?:a\s+janela\s+(?:do|da)\s+)?(.+?)\s+"
        r"(?:para|pro|pra)\s+(?:o\s+)?(primeiro|segundo|terceiro|monitor\s*\d+)(?:\s+monitor)?$",
        value,
        flags=re.I,
    )
    if move:
        target = move.group(1).strip()
        mon = normalized_key(move.group(2))
        idx = {"primeiro": 1, "segundo": 2, "terceiro": 3}.get(mon)
        if idx is None:
            m = re.search(r"\d+", mon)
            idx = int(m.group()) if m else 1
        value = f"mova {target} para monitor {idx}"

    # Pedidos em que o JARVIS deve escolher sozinho uma música e tocar no Opera.
    choose_music_key = normalized_key(value)
    choose_music_phrases = {
        "escolhe uma musica", "escolha uma musica", "escolhe uma musica pra mim",
        "escolha uma musica pra mim", "coloca qualquer musica", "toque qualquer musica",
        "toca qualquer musica", "coloca uma musica que voce escolher",
        "toque uma musica que voce escolher", "escolhe algo pra tocar",
    }
    if choose_music_key in choose_music_phrases or choose_music_key in {"escolha uma musica e", "escolhe uma musica e"}:
        value = "escolha uma musica"

    media_key = normalized_key(value)
    if media_key in {"proximo", "proxima", "proximo som", "proxima faixa"}:
        value = "proxima musica"
    elif re.fullmatch(r"play\s*\d+", media_key):
        value = "play"

    # "musica Eagles Hotel California" sem verbo e claramente um pedido de faixa.
    bare_music = re.match(r"^m[uú]sica\s+(.{3,})$", value, flags=re.I)
    if bare_music and normalized_key(value) not in {"musica anterior", "musica proxima"}:
        value = f"coloca musica {bare_music.group(1).strip()}"

    # V5.2 - alvo nomeado + monitor numerado/ordinal usando verbos naturais.
    # Ex.: "passa o Opera pro segundo monitor", "coloca Photoshop no monitor 2".
    named_numbered = re.match(
        r"^(?:passa|passe|passar|coloca|coloque|mova|move|manda|mande|leva|leve|joga|jogue)\s+"
        r"(?:a\s+janela\s+(?:do|da)\s+|o\s+|a\s+)?(.+?)\s+"
        r"(?:para|pro|pra|no|na)\s+(?:o\s+|a\s+)?(?:(?:monitor|tela|display)\s*)?"
        r"(primeiro|segundo|terceiro|quarto|primeira|segunda|terceira|quarta|[1234])"
        r"(?:\s+(?:monitor|tela|display))?$",
        value, flags=re.I,
    )
    if named_numbered:
        target = named_numbered.group(1).strip()
        token = normalized_key(named_numbered.group(2))
        idx = {
            "primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2,
            "terceiro": 3, "terceira": 3, "quarto": 4, "quarta": 4,
        }.get(token, int(token) if token.isdigit() else 1)
        value = f"mova {target} para monitor {idx}"

    # "passa o Opera para o outro monitor" / "coloca o Opera no outro monitor".
    other_monitor = re.match(
        r"^(?:passa|passe|passar|coloca|coloque|mova|move|manda|mande)\s+"
        r"(?:a\s+janela\s+(?:do|da)\s+|o\s+|a\s+)?(.+?)\s+"
        r"(?:para|pro|pra|no)\s+(?:o\s+)?outro\s+monitor$",
        value, flags=re.I,
    )
    if other_monitor:
        value = f"mova {other_monitor.group(1).strip()} para outro monitor"

    # Spotify deve vencer a rota genérica do YouTube quando é citado explicitamente.
    spotify = re.match(
        r"^(?:coloca|coloque|colocar|toca|toque|tocar)\s+(?:a\s+)?m[uú]sica\s+(.+?)\s+no\s+spotify$",
        value,
        flags=re.I,
    )
    if spotify:
        value = f"toque no spotify {spotify.group(1).strip()}"

    # Troca de saída de áudio em linguagem natural.
    audio_switch = re.match(
        r"^(?:troca|troque|trocar|muda|mude|mudar|alternar|alterna)\s+"
        r"(?:do|de|o)?\s*(?:fone(?:\s+de\s+ouvido)?|headset)\s+"
        r"(?:para|pro|pra)\s+(?:o\s+)?(.+)$",
        value,
        flags=re.I,
    )
    if audio_switch:
        value = f"manda o som para {audio_switch.group(1).strip()}"

    # Volume por extenso.
    vol = re.match(
        r"^(.*?\bvolume(?:\s+do\s+sistema)?\s+(?:em|para|a)\s+)([A-Za-zÀ-ÿ\s]+)$",
        value,
        flags=re.I,
    )
    if vol:
        number = parse_pt_number(vol.group(2))
        if number is not None:
            value = vol.group(1) + str(number)

    calibration_key = normalized_key(value)
    if calibration_key in {
        "calibre o microfone", "calibrar microfone", "calibra o microfone",
        "recalibre o microfone", "recalibrar microfone", "ajuste o microfone",
        "calibrar microfono", "calibre microfono", "calibra microfono",
        "calibrar mic", "calibre mic", "calibra mic", "calibrar micro", "calibre micro", "calibra micro", "calipro", "calibro",
    }:
        value = "calibre microfone"

    # Se a pessoa chamou "JARVIS Opera", o restante é um alvo curto de app.
    # Isso NÃO vale para frases comuns que apenas começam com "zero" num contexto matemático.
    if had_assistant_prefix and value and not looks_like_local_command(value):
        key = normalized_key(value)
        compact = key.replace(" ", "")
        legacy_exact = any(
            key == normalized_key(app)
            or compact == normalized_key(app).replace(" ", "")
            for app in APP_WORDS
        )
        conversational = key.startswith((
            "como ", "o que ", "oque ", "quem ", "porque ", "por que ",
            "me explique", "me fala sobre", "me diga sobre", "qual ", "quais ",
        ))
        if not conversational and len(key.split()) <= 6 and (
            legacy_exact or _is_known_local_app_term(value)
        ):
            value = f"abre {value}"

    # Título deformado sem verbo, observado em voz.
    if re.fullmatch(r"(?:Livin on a Prayer|Living on a Prayer)", value, flags=re.I):
        value = "coloca música Livin on a Prayer"

    return re.sub(r"\s+", " ", value).strip()


def is_complete_local_command(message: str) -> bool:
    """Usado pelo endpoint de voz: só acelera o corte quando a intenção já tem alvo/valor."""
    value = normalize_command(message) if message else ""
    key = normalized_key(value)
    if not key:
        return False

    # Abrir/fechar/janelas precisam de alvo depois do verbo.
    m = re.match(
        r"^(?:abre|abra|abrir|feche|fecha|fechar|minimize|minimiza|minimizar|maximize|maximiza|maximizar|"
        r"restaure|restaura|restaurar)\s+(?:o\s+|a\s+)?(.+)$",
        key,
    )
    if m and len(m.group(1).strip()) >= 2:
        return True

    # Volume só está completo quando há valor/ação definida.
    if re.match(r"^volume\s+(?:em|a|para)\s+\d{1,3}$", key):
        return True
    if key in {"mute", "mudo", "tirar mute", "desmutar", "aumenta volume", "abaixa volume"}:
        return True

    # Mover entre monitores requer alvo + número/ordinal já normalizado.
    if re.match(r"^(?:mova|move|joga|jogue)\s+.+\s+para\s+monitor\s+\d+$", key):
        return True
    if re.match(r"^(?:mova|move)\s+.+\s+para\s+outro\s+monitor$", key):
        return True

    if key == "escolha uma musica":
        return True

    if re.match(r"^crie pasta no desktop .{1,120}$", key):
        return True

    if key in {
        "descreva minha tela", "descreve minha tela", "descrever minha tela",
        "analise minha tela", "analisa minha tela", "o que tem na minha tela",
        "o que esta na minha tela", "o que voce ve na minha tela",
    }:
        return True

    # Mídia/áudio.
    if re.match(r"^(?:toque|toca|coloca|coloque|colocar)\s+.+", key):
        return True
    if re.match(r"^(?:manda|mande)\s+o\s+som\s+para\s+.+", key):
        return True
    if re.match(r"^(?:use|usa)\s+(?:o\s+)?microfone\s+.+", key):
        return True

    # Comandos unitários e status locais.
    if key in {
        "pause", "pausa", "continua", "continue", "proxima", "proxima musica",
        "anterior", "musica anterior", "screenshot", "captura de tela",
        "diagnostico", "diagnostico completo", "analisar minha rede", "analise minha rede",
        "como esta o pc", "como ta o pc", "status do pc", "zero para", "para zero",
        "o que voce consegue fazer", "quais sao seus comandos", "calibre microfone",
        "qual monitor estou usando", "monitor ativo", "quantos monitores tenho",
    }:
        return True

    return False


def looks_like_local_command(message: str) -> bool:
    """Conservador: pula Whisper apenas quando existe intenção local explícita."""
    value = normalize_command(message) if message else ""
    key = normalized_key(value)
    if not key or len(key.split()) > 22:
        return False

    # Conversa/pergunta conceitual nunca vira comando só por conter nome de app/hardware.
    if key.startswith((
        "oque ", "o que ", "quem ", "porque ", "por que ", "como funciona",
        "me explique", "me fala sobre", "me diga sobre", "quanto e", "qual a diferenca",
    )) and key not in {
        "o que tem na minha tela", "o que esta na minha tela",
        "o que voce consegue fazer",
    }:
        return False

    if is_complete_local_command(value):
        return True

    patterns = (
        r"^(?:abre|abra|abrir|feche|fecha|fechar|minimize|minimiza|minimizar|maximize|maximiza|maximizar|restaure|restaura|restaurar)\b",
        r"^volume\b",
        r"^(?:mova|move|joga|jogue)\b.*\bmonitor\b",
        r"^(?:toque|toca|coloca|coloque|colocar)\b.*\b(?:spotify|youtube|musica)\b",
        r"^(?:manda|mande)\b.*\bsom\b",
        r"^(?:use|usa)\b.*\bmicrofone\b",
        r"^(?:diagnostico|analisar minha rede|analise minha rede|status da rede)$",
        r"^(?:desligue|reinicie|suspenda|bloqueie)\b",
        r"^(?:apague|delete|exclua|remova)\b",
        r"^(?:pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar)\b",
        r"^(?:crie|cria|criar)\s+pasta\s+no\s+desktop\b",
        r"^(?:descreva|descreve|descrever|analise|analisa|olhe|olha|veja|ve)\b.*\btela\b",
    )
    return any(re.search(p, key, flags=re.I) for p in patterns)

