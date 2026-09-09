"""Text hygiene helpers shared by JARVIS UI/voice paths.

The overlay is a separate UTF-8 process, so a single sanitizer keeps captions
stable across Tk, Qt and TTS boundaries.  It repairs common UTF-8/Windows-1252
mojibake without changing ordinary Portuguese text.
"""
from __future__ import annotations

import re
import unicodedata

_SUSPECT_FRAGMENTS = (
    "Ã", "Â", "â€", "â€™", "â€œ", "â€\x9d", "â€“", "â€”", "ðŸ", "ï¿½", "�",
)


_UTF8_LATIN1_PAIRS = {
    "Ã¡": "á", "Ãà": "à", "Ãâ": "â", "Ãã": "ã", "Ãä": "ä",
    "ÃÁ": "Á", "ÃÀ": "À", "ÃÂ": "Â", "ÃÃ": "Ã",
    "Ã©": "é", "Ãê": "ê", "Ãë": "ë", "ÃÉ": "É", "ÃÊ": "Ê",
    "Ãí": "í", "ÃÍ": "Í", "Ãó": "ó", "Ãô": "ô", "Ãõ": "õ", "Ãö": "ö",
    "ÃÓ": "Ó", "ÃÔ": "Ô", "ÃÕ": "Õ", "Ãú": "ú", "Ãü": "ü", "ÃÚ": "Ú",
    "Ãç": "ç", "ÃÇ": "Ç", "Â ": " ",
}

_COMMON_REPLACEMENTS = {
    "â€™": "’",
    "â€˜": "‘",
    "â€œ": "“",
    "â€\x9d": "”",
    "â€“": "–",
    "â€”": "—",
    "â€¦": "…",
    "Âº": "º",
    "Âª": "ª",
    "Â°": "°",
    "Â·": "·",
    "Â": "",
}


def _badness(value: str) -> int:
    if not value:
        return 0
    score = value.count("�") * 12
    score += sum(value.count(fragment) * 3 for fragment in _SUSPECT_FRAGMENTS if fragment != "�")
    score += sum(4 for ch in value if unicodedata.category(ch) in {"Cs", "Co", "Cn"})
    return score


def repair_mojibake(text: str) -> str:
    """Repair likely UTF-8 decoded as latin-1/cp1252, conservatively."""
    value = str(text or "")
    if not value:
        return ""

    # Corrige pares UTF-8/cp1252 localmente. Fazer por pares funciona em
    # strings mistas onde um único caractere quebrado impediria converter a
    # legenda inteira de uma vez.
    def _repair_pair(match):
        pair = match.group(0)
        for codec in ("cp1252", "latin1"):
            try:
                decoded = pair.encode(codec).decode("utf-8")
                if decoded != pair:
                    return decoded
            except Exception:
                pass
        return pair
    value = re.sub(r"[ÃÂ].", _repair_pair, value)

    # Corrige também pares conhecidos do português.
    for broken, fixed in _UTF8_LATIN1_PAIRS.items():
        value = value.replace(broken, fixed)
    for broken, fixed in _COMMON_REPLACEMENTS.items():
        value = value.replace(broken, fixed)

    best = value
    best_score = _badness(best)
    if best_score:
        # A very common Windows failure is: UTF-8 bytes -> cp1252/latin1 text.
        for codec in ("cp1252", "latin1"):
            try:
                candidate = best.encode(codec, errors="strict").decode("utf-8", errors="strict")
            except Exception:
                continue
            score = _badness(candidate)
            if score < best_score:
                best, best_score = candidate, score

    return best


def sanitize_text(text: str, *, limit: int = 260, preserve_newlines: bool = False) -> str:
    value = repair_mojibake(text)
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\ufffd", "")

    cleaned = []
    for ch in value:
        if preserve_newlines and ch in "\n\t":
            cleaned.append(ch)
            continue
        category = unicodedata.category(ch)
        if category.startswith("C"):
            # Strip controls, bidi marks, zero-width chars and surrogates.
            continue
        if ch.isprintable() or ch == " ":
            cleaned.append(ch)

    value = "".join(cleaned)
    if preserve_newlines:
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r" *\n *", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value).strip()
    else:
        value = re.sub(r"\s+", " ", value).strip()

    if limit and len(value) > int(limit):
        limit = int(limit)
        cut = value.rfind(" ", 0, limit + 1)
        value = value[: cut if cut > max(16, limit // 2) else limit].rstrip() + "…"
    return value


__all__ = ["repair_mojibake", "sanitize_text"]
