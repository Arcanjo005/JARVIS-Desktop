from __future__ import annotations

import re
import json
import threading
import time
import unicodedata
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from context_engine import ContextEngine
except Exception:
    ContextEngine = None

try:
    from conditional_rules import ConditionalRuleEngine
except Exception:
    ConditionalRuleEngine = None

try:
    from semantic_language import (
        normalize_action_utterance, normalize_close_target, is_other_monitor_fragment,
        resolve_self_correction, classify_speech_act, normalize_broken_command
    )
except Exception:
    def normalize_action_utterance(text):
        value = " ".join(str(text or "").split())
        key = unicodedata.normalize("NFKD", value)
        key = "".join(ch for ch in key if not unicodedata.combining(ch)).lower()
        repairs = {
            "abro ": "abre ", "abri ": "abre ", "minimmiza ": "minimiza ",
            "fichar ": "fecha ", "movel ": "move ",
        }
        for src, dst in repairs.items():
            if key.startswith(src):
                return dst + value[len(src):]
        return value
    def normalize_close_target(text):
        value = " ".join(str(text or "").split()).strip()
        key = unicodedata.normalize("NFKD", value)
        key = "".join(ch for ch in key if not unicodedata.combining(ch)).lower()
        if key in {"bs", "obs", "o bs", "o obs"}:
            return "OBS"
        return value
    def is_other_monitor_fragment(text):
        value = unicodedata.normalize("NFKD", str(text or ""))
        value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
        value = re.sub(r"[^a-z0-9 ]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return bool(re.fullmatch(r"(?:(?:para|pra|pro|na|no) )?(?:outra tela|outro monitor|outro display|outra|outro)(?: agora)?", value))
    def resolve_self_correction(text):
        return " ".join(str(text or "").split()).strip()
    def classify_speech_act(text):
        return "neutral"
    def normalize_broken_command(text):
        return " ".join(str(text or "").split()).strip()


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9% ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_social(text: str) -> str:
    """Remove cortesia/fillers sem remover palavras que carregam intenção."""
    raw = " ".join(str(text or "").split()).strip()
    # Wake variants observed in real STT. They are stripped only at the
    # beginning of the utterance, so they cannot rewrite ordinary content.
    wake_name = r"(?:jarvis|jarbas|jarves|javes|jervis|j[aá]\s*vis(?:h)?|arvies)"
    prefixes = (
        rf"e\s*a[ií][.?!, ]+{wake_name}[.?!, ]+",
        rf"e[.?!, ]+{wake_name}[.?!, ]+",
        rf"ei[.?!, ]+{wake_name}[.?!, ]+",
        rf"oi[.?!, ]+{wake_name}[.?!, ]+",
        rf"ol[aá][.?!, ]+{wake_name}[.?!, ]+",
        rf"{wake_name}[.?!, ]+",
        r"e\s*a[ií][, ]+zero[, ]+",
        r"ei[, ]+zero[, ]+",
        r"oi[, ]+zero[, ]+",
        r"zero[, ]+",
        r"por\s+favor[, ]+",
        r"cara[, ]+",
        r"mano[, ]+",
        r"man[, ]+",
        r"velho[, ]+",
        r"a[ií][, ]+",
        r"agora[, ]+",
        r"(?:eita\s+peste|vish|vixe|vixi|ixi|oxe|oxente|oxenti|oxi|eita)[.?!, ]+",
        r"(?:olha|olha\s+s[oó]|viu|tipo|ent[aã]o|bom|certo)[.?!, ]+",
        r"(?:ah+|aah+|eh+|hum+|hmm+)[.?!, ]+",
    )
    for _ in range(4):
        old = raw
        for pat in prefixes:
            raw = re.sub(r"^" + pat, "", raw, flags=re.I).strip(" ,")
        if raw == old:
            break
    raw = re.sub(
        r"\s+(?:por favor|pra mim|para mim|a[ií]|cara)\s*$",
        "",
        raw,
        flags=re.I,
    ).strip(" ,")

    # STT pode repetir o complemento depois de uma pausa. Se o segundo trecho
    # ja e literalmente o sufixo semantico do primeiro, removemos a duplicata.
    chunks = [c.strip(" ,") for c in re.split(r"[.!?;]+", raw) if c.strip(" ,")]
    if len(chunks) == 2:
        first_key, second_key = _norm(chunks[0]), _norm(chunks[1])
        if second_key and first_key.endswith(second_key):
            raw = chunks[0]
    return raw


def _unwrap_action_request(text: str) -> str:
    """Remove molduras naturais quando o restante é claramente uma ação.

    Ex.: "mano, eu quero que você abra o Opera" -> "abra o Opera".
    A remoção só acontece quando o restante começa por um verbo operacional,
    evitando transformar perguntas sobre uma ação em execução acidental.
    """
    raw = " ".join(str(text or "").split()).strip(" ,")
    wrappers = (
        r"^(?:eu\s+)?(?:quero|queria|preciso)\s+que\s+(?:voce|voces)\s+",
        r"^(?:eu\s+)?(?:quero|queria|preciso)\s+",
        r"^(?:voce\s+)?(?:pode|consegue)\s+(?:por\s+favor\s+)?",
        r"^(?:faz|faca)\s+(?:o\s+)?favor\s+(?:de\s+)?",
        r"^(?:da|daria)\s+pra\s+",
    )
    candidate = raw
    for pattern in wrappers:
        updated = re.sub(pattern, "", candidate, flags=re.I).strip(" ,")
        if updated != candidate:
            candidate = updated
            break
    key = _norm(candidate)
    operational = re.match(
        r"^(?:abre|abra|abrir|abrih|abrei|abril|fecha|feche|fechar|minimiza|minimize|maximiza|maximize|"
        r"restaura|restaure|move|mova|mover|coloca|coloque|pula|pular|pule|pausa|pause|play|continua|continue|"
        r"proximo|proxima|pesquisa|pesquise|pesquisar|procura|procurar|busca|buscar|vai|entra|entre|entrar|"
        r"modo|tela cheia|sair da tela cheia|volume|muta|mute|silencia|captura|tira um print)\b",
        key, re.I,
    )
    return candidate if operational else raw


def _request_key(text: str) -> str:
    """Normaliza pedidos informacionais sem transformar conversa em comando.

    Esta camada permite formas naturais como "quero hora", "me passa a RAM",
    "pode me mostrar os programas abertos" e equivalentes. Ela e aplicada
    somente depois da barreira de CONVERSATION/SOCIAL_CHAT.
    """
    key = _norm(_strip_social(text))
    prefixes = (
        r"^(?:eu\s+)?(?:quero|queria)(?:\s+saber)?\s+",
        r"^saber\s+",
        r"^(?:me\s+)?(?:diz|diga|dizer|fala|fale|falar|informa|informe|informar|"
        r"mostra|mostre|mostrar|passa|passe|passar|manda|mande|mandar|envia|envie|enviar)\s+",
        r"^pode\s+(?:me\s+)?(?:dizer|falar|informar|mostrar|passar|mandar|enviar)\s+",
        r"^me\s+(?:da|de)\s+",
        r"^consegue\s+(?:me\s+)?(?:dizer|falar|informar|mostrar|passar|mandar|enviar)\s+",
    )
    removed_wrapper = False
    for _ in range(3):
        old = key
        for pat in prefixes:
            updated = re.sub(pat, "", key, flags=re.I).strip()
            if updated != key:
                removed_wrapper = True
            key = updated
        if key == old:
            break
    if removed_wrapper:
        key = re.sub(r"^(?:a|o|os|as)\s+", "", key).strip()
    key = re.sub(r"\s+(?:agora|ai|pra mim|para mim)$", "", key).strip()
    return key


def _semantic_info_command(query_key: str) -> Optional[tuple[str, str]]:
    """Resolve entidades informacionais, nao frases literais.

    A mesma intencao aceita muitas molduras linguisticas porque a camada
    _request_key ja remove "quero/me passa/me mostra". Aqui o que manda e a
    entidade: hora, RAM, CPU, disco, rede, bateria, janelas etc.
    """
    key = _norm(query_key)
    tokens = set(key.split())

    if key in {"hora", "horas", "ora", "horario", "horario atual"} or re.search(r"\b(?:que horas|qual(?: e)?(?: a)? hora|qual(?: e)?(?: o)? horario|hora atual)\b", key):
        return "v8:time", "LOCAL_INSTANT"
    if key in {"data", "dia", "data de hoje", "dia de hoje"} or re.search(r"\b(?:que dia|qual(?: e)?(?: a)? data|qual(?: e)?(?: o)? dia|hoje e que dia)\b", key):
        return "v8:date", "LOCAL_INSTANT"

    # "memoria" em um pedido de status do computador significa RAM; memoria
    # conversacional continua fora desta rota (ex.: "lembra da minha memoria").
    if (
        "ram" in tokens
        or "memoria ram" in key
        or key in {"memoria", "memoria do pc", "memoria do computador"}
        or ("memoria" in tokens and re.search(r"\b(?:uso|usando|usada|consum|quanto|livre|disponivel|total|tem|ocupad)\w*\b", key))
    ):
        if not re.search(r"\b(?:lembr|conversa|historico|salva|persistente)\b", key):
            return "v8:ram", "LOCAL_INSTANT"
    if "cpu" in tokens or "processador" in tokens or key in {"uso do processador", "uso de processador"}:
        return "v8:cpu", "LOCAL_INSTANT"
    if tokens & {"disco", "armazenamento", "ssd", "hd"} or "espaco livre" in key or "espaco no disco" in key:
        return "v8:disk", "LOCAL_INSTANT"
    if tokens & {"rede", "internet", "conexao"} and not re.search(r"\b(?:pesquisa|site|web|navegador)\b", key):
        return "v8:network", "LOCAL_INSTANT"
    if tokens & {"bateria", "battery"} or "carga da bateria" in key:
        return "v8:battery", "LOCAL_INSTANT"

    if key in {"janela ativa", "programa ativo", "aplicativo ativo", "o que esta em foco", "qual esta em foco"} or re.search(r"\bjanela ativa\b", key):
        return "v8:active_window", "WINDOWS_LOCAL"
    if (tokens & {"programa", "programas", "janela", "janelas", "aplicativo", "aplicativos"} and tokens & {"aberto", "abertos", "aberta", "abertas", "rodando"}) or key in {"o que esta aberto", "o que esta aberto agora"} or re.search(r"\b(?:o que|quais?) (?:esta|ta|estao|tao) rodando(?: no (?:pc|computador))?\b", key):
        return "v8:open_windows", "WINDOWS_LOCAL"
    if key in {"volume", "volume atual", "som", "som atual"} or ("volume" in tokens and (tokens & {"atual", "quanto", "qual", "nivel", "porcentagem"})):
        return "v8:volume", "LOCAL_INSTANT"
    if key in {"microfone", "microfone atual", "entrada de audio"} or ("microfone" in tokens and tokens & {"qual", "atual"}):
        return "v8:microphone", "LOCAL_INSTANT"
    if (tokens & {"monitor", "monitores", "tela", "telas", "display", "displays"} and tokens & {"quantos", "quantas", "numero", "ativo", "tenho", "tem"}) or key in {"monitores", "telas", "monitor ativo"}:
        return "v8:monitors", "LOCAL_INSTANT"
    if key in {"print", "um print", "screenshot", "um screenshot", "captura de tela", "captura da tela"} or re.search(r"\b(?:tirar|tira|fazer|faz|quero) (?:um )?(?:print|screenshot)\b", key):
        mon = _monitor_number(key)
        return (f"v8:screenshot:{mon}" if mon else "v8:screenshot"), "SCREENSHOT"
    if key in {"capacidades", "funcoes", "funcoes do zero", "funcoes do jarvis", "mapa de capacidades", "o que voce pode fazer", "o que voce consegue fazer", "o que voce sabe fazer", "o que o zero pode fazer", "o que o zero sabe fazer", "o que o jarvis pode fazer", "o que o jarvis sabe fazer"}:
        return "v8:capabilities", "CAPABILITIES"
    if key in {"latencia", "performance", "desempenho", "tempo de resposta", "tempos de resposta", "velocidade do zero", "velocidade do jarvis"} or "tempo de resposta" in key:
        return "v8:performance", "PERFORMANCE"
    return None


PC_DIAG_RE = re.compile(
    r"^(?:como (?:esta|ta|vai|anda|funciona|esta funcionando|ta funcionando) (?:(?:o\s+)?meu|o) (?:pc|computador|sistema)|"
    r"(?:meu|o) (?:pc|computador) (?:esta|ta) (?:bem|normal|ok)|"
    r"(?:(?:ta|esta)\s+)?tudo (?:bem|certo) com (?:meu|o) (?:pc|computador)|"
    r"status (?:do|de) (?:pc|computador|sistema)|diagnostico (?:do|de) (?:pc|computador|sistema)|"
    r"como (?:esta|ta) a maquina)\b",
    re.I,
)

VISUAL_ANCHOR_RE = re.compile(
    r"\b(?:tela|monitor|display|area de trabalho|desktop|imagem|print|screenshot|janela que estou vendo)\b",
    re.I,
)
VISUAL_INTENT_RE = re.compile(
    r"\b(?:descrev\w*|analis\w*|olh\w*|observ\w*|examin\w*|mostr\w*|veja|ver|ve|"
    r"explic\w*|interpret\w*|identific\w*|vend\w*|diz(?:er)? o que (?:tem|aparece)|o que (?:tem|aparece|esta aparecendo))\b",
    re.I,
)


CONVERSATION_RE = re.compile(
    r"^(?:como\s+(?:e\s+que\s+)?funciona|funciona\s+(?:o|a)|"
    r"me\s+explica|me\s+explique|pode\s+me\s+explicar|explica\s+mais|explique\s+mais|"
    r"o\s+que\s+e|oque\s+e|quem\s+e|por\s+que|porque|qual\s+a\s+diferenca|"
    r"o\s+que\s+voce\s+sabe|oque\s+voce\s+sabe|o\s+que\s+sabe|"
    r"fala\s+mais\s+sobre|fale\s+mais\s+sobre|me\s+fala\s+sobre|me\s+fale\s+sobre|"
    r"me\s+conte\s+sobre|conta\s+mais\s+sobre|quero\s+saber\s+sobre|queria\s+saber\s+sobre|"
    r"ta\s+tudo\s+bem|tudo\s+bem|tudo\s+bom|como\s+voce\s+ta|como\s+estao\s+as\s+coisas|"
    r"e\s+ai|oi|ola|bom\s+dia|boa\s+tarde|boa\s+noite|ah\s+pois\s+e|pois\s+e|beleza|show|valeu)\b",
    re.I,
)

SOCIAL_RE = re.compile(
    r"^(?:ta\s+tudo\s+bem|tudo\s+bem|tudo\s+bom|como\s+voce\s+ta|como\s+ce\s+ta|"
    r"e\s+ai|oi|ola|bom\s+dia|boa\s+tarde|boa\s+noite|"
    r"ah\s+pois\s+e|pois\s+e|beleza|show|valeu)\b",
    re.I,
)

VISION_RE = re.compile(
    r"\b(?:descrev\w*|analis\w*|olh\w*|observ\w*|examin\w*|mostr\w*|veja|ver|ve|o\s+que\s+tem|o\s+que\s+aparece)\b"
    r".*\b(?:tela|monitor|area\s+de\s+trabalho)\b",
    re.I,
)

ACTION_RE = re.compile(
    r"^(?:abre|abra|abrir|fecha|feche|fechar|minimiza|minimize|minimizar|"
    r"maximiza|maximize|maximizar|expande|expanda|expandir|restaura|restaure|restaurar|"
    r"mova|move|mover|coloca|coloque|joga|jogue|leva|leve|manda|mandar|envia|envie|enviar|"
    r"cria|crie|criar|faz|faca|fazer|volume|abaixa|abaixe|abaixar|abaixo|reduz|reduza|reduzir|diminui|diminua|volta|volte|retorna|retorne|pausa|pause|continua|continue|pesquisa|pesquise|"
    r"procura|procure|procurar|procurando|busca|busque|buscar|buscando|pesquisar|pesquisando|passa|passe|passar|apaga|apague|delete|exclua|acesse|acessar|"
    r"entra|entre|entrar|vai|tira|tire|tirar|deixa|deixe|deixar|esconde|esconda|esconder|traz|traga|trazer|captura|capture|capturar|screenshot)\b",
    re.I,
)

WINDOW_VERB_RE = re.compile(
    r"^(minimiza|minimize|minimizar|maximiza|maximize|maximizar|expande|expanda|expandir|"
    r"restaura|restaure|restaurar|mova|move|mover|coloca|coloque|joga|jogue|leva|leve|"
    r"manda|mandar|envia|envie|enviar|passa|passe|passar)\b",
    re.I,
)

SITE_ALIASES = {
    "youtube": "youtube.com",
    "youtube.com": "youtube.com",
    "mlabs": "accounts.mlabs.io",
    "m labs": "accounts.mlabs.io",
    "spotify": "open.spotify.com",
    "crunchyroll": "crunchyroll.com",
    "crunchy roll": "crunchyroll.com",
    "crunchyroll.com": "crunchyroll.com",
    "instagram": "instagram.com",
    "facebook": "facebook.com",
    "gmail": "mail.google.com",
    "google": "google.com",
    "linkedin": "linkedin.com",
    "whatsapp": "web.whatsapp.com",
    "whatsapp web": "web.whatsapp.com",
    "gerenciador de anuncios": "adsmanager.facebook.com",
    "gerenciador anuncios": "adsmanager.facebook.com",
    "meta ads": "adsmanager.facebook.com",
    "meta ads manager": "adsmanager.facebook.com",
    "ads manager": "adsmanager.facebook.com",
}


def _clean_spoken_search_query(text: str) -> str:
    """Limpa apenas artefatos muito comuns de STT na consulta falada.

    Não tenta "adivinhar" frases longas. Corrige somente artigos/fillers na
    borda e um pequeno conjunto de acrônimos observados em logs reais.
    """
    query = " ".join(str(text or "").split()).strip(" ,;.!?")
    query = re.sub(r"^(?:por|sobre)\s+", "", query, flags=re.I).strip()
    query = re.sub(r"^(?:o|a)\s+(?!que\b)", "", query, flags=re.I).strip()
    # Vosk/Whisper às vezes materializam o 'e' de ligação de
    # "Opera e pesquisa X" como primeira palavra da consulta.
    if re.match(r"^e\s+\S+", _norm(query)) and len(_norm(query).split()) >= 2:
        query = re.sub(r"^[eé]\s+", "", query, flags=re.I).strip()
    # Acrônimo OBS observado como 'obrece/obesse'. Só corrige se a consulta
    # inteira for esse token; não altera texto livre.
    qkey = _norm(query)
    if qkey in {"obrece", "obesse", "obes", "o b s"}:
        return "OBS"
    return query


@dataclass
class V8PlanStep:
    command: str
    action: str = "LEGACY"
    target: Optional[str] = None
    depends_on: Optional[int] = None
    require_success: bool = False


@dataclass
class V8Route:
    kind: str
    commands: List[str]
    intent: str = ""
    steps: List[V8PlanStep] = field(default_factory=list)


class V8Router:
    """Router local conservador, com contexto curto para referências explícitas."""

    CONTEXT_TTL = 180.0

    def __init__(self, context=None):
        self._lock = threading.RLock()
        self.context = context or (ContextEngine(ttl=self.CONTEXT_TTL) if ContextEngine is not None else None)
        # Fallback preserva compatibilidade se o Context Engine nao carregar.
        self._last_app: Optional[str] = None
        self._last_monitor: Optional[int] = None
        self._context_at = 0.0

    def reset_context(self):
        if self.context is not None:
            self.context.reset()
        with self._lock:
            self._last_app = None
            self._last_monitor = None
            self._context_at = 0.0

    def _fresh(self) -> bool:
        return bool(self._context_at and time.monotonic() - self._context_at <= self.CONTEXT_TTL)

    def _remember_app(self, app: Optional[str]):
        if app:
            if self.context is not None:
                self.context.remember_app(app)
            with self._lock:
                self._last_app = app
                self._context_at = time.monotonic()

    def mark_app_success(self, app: Optional[str]):
        """Atualiza contexto entre turnos somente apos execucao confirmada."""
        self._remember_app(app)

    def mark_action_success(self, action: str, target: str = "", before=None, after=None):
        if self.context is not None:
            self.context.record_action(action, target, verified=True, before=before or {}, after=after or {})
        if target and str(action or "").upper() in {
            "OPEN_APP", "MINIMIZE_WINDOW", "MAXIMIZE_WINDOW", "RESTORE_WINDOW",
            "MOVE_WINDOW", "MOVE_OTHER", "OPEN_SITE_IN_APP", "BROWSER_SEARCH",
        }:
            self._remember_app(target)
        monitor = (after or {}).get("monitor") if isinstance(after, dict) else None
        if monitor:
            self._remember_monitor(monitor)

    def mark_feedback(self, text: str):
        if self.context is not None:
            self.context.mark_feedback(text)

    def observe_context(self, app: str = "", monitor: Optional[int] = None, site: str = "", title: str = ""):
        if self.context is not None:
            try:
                self.context.observe_active(app=app, monitor=monitor, site=site, title=title)
            except Exception:
                pass

    def remember_topic(self, topic: str):
        if self.context is not None:
            try:
                self.context.remember_topic(topic)
            except Exception:
                pass

    def remember_media(self, media):
        if self.context is not None:
            try:
                self.context.remember_media(media, verified=False, confidence=0.88)
            except Exception:
                pass

    def _remember_monitor(self, monitor: Optional[int]):
        if monitor:
            if self.context is not None:
                self.context.remember_monitor(int(monitor))
            with self._lock:
                self._last_monitor = int(monitor)
                self._context_at = time.monotonic()

    def _context(self):
        if self.context is not None:
            app = self.context.current_app()
            mon = self.context.current_monitor()
            if app is not None or mon is not None:
                return app, mon
        with self._lock:
            if not self._fresh():
                return None, None
            return self._last_app, self._last_monitor

    def route(self, text: str) -> Optional[V8Route]:
        original = " ".join(str(text or "").split()).strip()
        if not original:
            return None
        original_key = _norm(original)
        # Interrupcao explicita digitada/final tambem e local. Durante TTS, a
        # via acustica dedicada continua sendo a principal e mais rapida.
        if original_key in {"jarvis para", "jarvis pare", "jarvis cancela", "jarvis cancelar", "zero para", "zero pare", "zero cancela", "zero cancelar"}:
            return _make_route("local", ["v8:interrupt"], "PRIORITY_INTERRUPT")

        cleaned = _unwrap_action_request(_strip_social(original))
        # Hotfix 4: autocorreção e fala quebrada são resolvidas ANTES do parser.
        # A classificação de ato de fala impede que negação/afirmação sejam
        # reinterpretadas por fuzzy/legado como ordens ao Windows.
        cleaned = resolve_self_correction(cleaned)
        cleaned = normalize_broken_command(cleaned)
        key = _norm(cleaned)
        speech_act = classify_speech_act(cleaned)
        if speech_act == "negated_command":
            # Mantém o contrato histórico: negação é semanticamente conversa/no-op,
            # nunca uma ação local. A GUI reconhece o intent e responde sem Gemini.
            return V8Route("conversation", [], intent="NEGATED_COMMAND")
        if speech_act == "assertion":
            return V8Route("conversation", [], intent="ACTION_ASSERTION")

        # 13.11.5: normalize cedo SOMENTE molduras regionais/coloquiais.
        # O caminho geral continua na etapa historica mais abaixo; assim termos
        # como "baixa esse arquivo" nao podem ser aproximados para ABAIXA/MINIMIZA
        # antes que o Agent reconheca DOWNLOAD.
        pre_key = _norm(cleaned)
        regional_pre_normalize = bool(re.match(
            r"^(?:bora|simbora|vamo|vamos|partiu|tu\b|ce\b|meu rei\b|meu chapa\b|meu patrao\b|"
            r"chefe\b|macho\b|home\b|homem\b|da pra\b|tem como\b|teria como\b|ve se\b|veja se\b|"
            r"olha se\b|olhe se\b|me quebra essa\b|quebra essa\b|da essa moral\b|da uma moral\b|"
            r"vai (?:abrindo|fechando|fexando|minimizando|maximizando|restaurando|movendo|jogando|botando|"
            r"colocando|pesquisando|procurando|prucurando|buscando|clicando|pausando|continuando)\b|"
            r"manda (?:abre|abra|abrir|fecha|feche|fechar|fexa|fexar|minimiza|minimize|minimizar|"
            r"maximiza|maximize|maximizar|pesquisa|pesquise|pesquisar|procura|procure|procurar)\b|"
            r"deixa .+ (?:aberto|aberta|fechado|fechada|minimizado|minimizada|maximizado|maximizada)$|"
            r"(?:bota|bote|coloca|coloque) .+ (?:pra|para) (?:rodar|funcionar|abrir)$)",
            pre_key, re.I,
        ))
        if regional_pre_normalize:
            semantic_cleaned = normalize_action_utterance(cleaned)
            if semantic_cleaned and semantic_cleaned != cleaned:
                cleaned = semantic_cleaned
                key = _norm(cleaned)

        # Identidade de tratamento da sessão, sem cadastro/biometria de voz.
        # É deliberadamente explícita: o usuário informa o nome e JARVIS o usa
        # apenas como contexto de tratamento daquela sessão.
        if key in {"esquece meu nome", "esqueca meu nome", "nao use meu nome", "pare de usar meu nome"}:
            return _make_route("local", ["v8:user_name:clear"], "SESSION_IDENTITY")
        if key in {"qual nome voce esta usando", "como voce esta me chamando", "qual e meu nome aqui", "quem sou eu", "qual e meu nome", "voce lembra meu nome"}:
            return _make_route("local", ["v8:user_name:status"], "SESSION_IDENTITY")
        m_name = re.match(
            r"^(?:me chama de|me chame de|pode me chamar de|pode me chama de|me trate como|meu nome (?:e|é))(?:\s+o)?\s+([A-Za-zÀ-ÖØ-öø-ÿ'’ -]{1,48})[.!?]*$",
            cleaned,
            flags=re.I,
        )
        if m_name:
            raw_name = re.sub(r"\s+", " ", m_name.group(1)).strip(" .,!?:;")
            if raw_name:
                return _make_route("local", [f"v8:user_name:{raw_name}"], "SESSION_IDENTITY")

        # "eu sou X" é um atalho apenas para primeiro nome. Estados/profissões
        # comuns continuam sendo conversa normal, não identidade da sessão.
        m_i_am = re.match(
            r"^eu sou(?:\s+o)?\s+([A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,32})[.!?]*$",
            cleaned,
            flags=re.I,
        )
        if m_i_am:
            raw_name = re.sub(r"\s+", " ", m_i_am.group(1)).strip(" .,!?:;")
            blocked_identity = {
                "bem", "mal", "feliz", "triste", "cansado", "cansada",
                "brasileiro", "brasileira", "homem", "mulher", "usuario",
                "usuário", "programador", "programadora", "estudante",
                "novo", "nova", "aqui",
            }
            if raw_name and _norm(raw_name) not in {_norm(item) for item in blocked_identity}:
                return _make_route("local", [f"v8:user_name:{raw_name}"], "SESSION_IDENTITY")

        # Build 12: reparos conservadores para erros de STT observados em uso real.
        # Sao aplicados somente a frases operacionais muito especificas, para nao
        # transformar conversa comum em comando.
        stt_exact = {
            "prosto no episodio": "proximo episodio",
            "para o nosso episodio": "proximo episodio",
            "pro leite episodio": "proximo episodio",
            "para a abertura": "pula a abertura",
            "para abertura": "pula abertura",
            "na tela um colar introducao": "na tela 1 pular introducao",
            "a pre ddyhotina trabalu": "aprende rotina trabalho",
            "pela cheia": "tela cheia",
            "tela sie ja": "tela cheia",
            "ate la cheio": "tela cheia",
            "modo autor": "modo auto",
            "modo alto": "modo auto",
            "mordo game": "modo gamer",
            "mordo gamer": "modo gamer",
            "modo de jogo": "modo gamer",
            "abrei o opero": "abre opera",
            "abrei o opera": "abre opera",
            "abril opera": "abre opera",
            "abrih bloody strike": "abre BLOODSTRIKE",
            "abrei bloody strike": "abre BLOODSTRIKE",
            "abril do sorte": "abre Discord",
            "abre o descorte": "abre Discord",
            "abre descorte": "abre Discord",
            "abre discordia": "abre Discord",
            "minimmiza opera": "minimiza opera",
            "movel opera para outra tela": "move opera para outra tela",
            "fichar o bs": "fecha OBS",
            "fe se eu chatei de pete": "fecha ChatGPT",
            "fe se ao chat e ja petei": "fecha ChatGPT",
            "apoisa": "ah pois e",
            "hoje a abrir discord": "abre Discord",
            "oja vim abri se descoredo": "abre Discord",
            "oja vim abri se descorte": "abre Discord",
            "hoje arvies pula 10 segundos": "pula 10 segundos",
            "hoje arvies pular episodio": "pular episodio",
            "hoje a revise pular abertura": "pular abertura",
            "olha ai pular a abertura": "pular abertura",
            "10 jarves volume em 50": "volume 50",
        }
        repaired_key = stt_exact.get(key, key)
        repaired_key = re.sub(r"^(?:abro|abri)\s+", "abre ", repaired_key)
        # Com wake explicito, o STT frequentemente materializa o imperativo
        # "abre" como passado "abriu". Só corrigimos quando a frase continua
        # com outra ação operacional, reduzindo o risco de executar conversa.
        repaired_key = re.sub(
            r"^abriu\s+(.+?)\s+e\s+pesquis(?:a|am|ar)\s+",
            r"abre \1 e pesquisa ",
            repaired_key, flags=re.I,
        )
        repaired_key = re.sub(r"^(?:fecho|fechei)\s+", "fecha ", repaired_key)
        repaired_key = re.sub(r"^(?:bota|bote|poe)\s+(.+?)\s+(?:na|no|pra|para)\s+(outra tela|outro monitor|outro display)$", r"move \1 para \2", repaired_key)
        repaired_key = re.sub(
            r"^(?:aprei(?: de)?|aprendi(?: de)?|apreendi(?: de)?|aprende de|aprender de)\s+(?:a\s+)?rotina\s+(?:de\s+)?",
            "aprende rotina ",
            repaired_key,
        )
        repaired_key = re.sub(r"\b(pula(?:r)?)(?:\s+a)?\s+betura\b", r"\1 a abertura", repaired_key)
        # 'ópero' apareceu repetidamente no STT para o navegador Opera. Só
        # normalizamos dentro de uma frase operacional, nunca em conversa livre.
        if re.search(r"\b(?:abre|abra|abrir|abrei|abrih|abril|vai|entra|pesquisa|pesquise|pesquisar|procura|busca)\b", repaired_key):
            repaired_key = re.sub(r"\b(?:opero|oper)\b", "opera", repaired_key)
            repaired_key = re.sub(r"\b(?:bloody strike|bloody striking|blood striking)\b", "BLOODSTRIKE", repaired_key)
            repaired_key = re.sub(r"\b(?:descorte|descoredo|discordia|do sorte|do sort|de cordinho)\b", "Discord", repaired_key)
            repaired_key = re.sub(r"\b(?:chat de pt|chat g pt|chat gepete)\b", "ChatGPT", repaired_key)
        # Explicação curta observada como 'Bishplica'. Corrigir o verbo impede
        # que 'memória RAM' seja confundida com pedido de telemetria.
        repaired_key = re.sub(r"^(?:bishplica|bisplica|bexplica)\s+(?:sobre\s+)?", "me explica ", repaired_key)
        if repaired_key != key:
            key = repaired_key
            cleaned = repaired_key

        # Ordens operacionais em ingles usam o mesmo executor local. A fala
        # exibida ao usuario continua literal; esta canonizacao e interna.
        english_exact = {
            "next episode": "proximo episodio",
            "skip intro": "pular abertura",
            "skip opening": "pular abertura",
            "full screen": "tela cheia",
            "fullscreen": "tela cheia",
            "go fullscreen": "tela cheia",
            "next song": "proxima musica",
            "next track": "proxima musica",
            "previous song": "musica anterior",
            "previous track": "musica anterior",
            "game mode": "modo gamer",
            "gaming mode": "modo gamer",
            "conversation mode": "modo conversa",
            "automatic mode": "modo auto",
        }
        if key in english_exact:
            key = english_exact[key]
            cleaned = key
        else:
            m_en = re.match(r"^(?:open|launch|start)\s+(.+)$", key, re.I)
            if m_en:
                key = f"abre {m_en.group(1).strip()}"
                cleaned = key
            else:
                m_en = re.match(r"^(?:close|quit|exit)\s+(.+)$", key, re.I)
                if m_en:
                    key = f"fecha {m_en.group(1).strip()}"
                    cleaned = key
                # Pesquisa em ingles e tratada adiante usando `cleaned` bruto,
                # para preservar pontuacao como "Python 3.13".

        # Hotfix 5: recuperação explícita do pipeline de voz sem precisar
        # encerrar a interface. Útil quando um headset USB troca de endpoint.
        if key in {
            "reiniciar voz", "reinicia voz", "reinicie a voz", "reiniciar a voz",
            "reiniciar microfone", "reinicia o microfone", "reinicie o microfone",
            "voltar a ouvir", "volta a ouvir", "reativar escuta", "reativa a escuta",
            "reiniciar escuta", "reinicia a escuta",
        }:
            return _make_route("local", ["v8:voice_restart"], "VOICE_RESTART")

        if key in {"microfone muito sensivel", "microfone muito sensível", "modo microfone muito sensivel", "modo microfone muito sensível", "me ouve bem mais baixo"}:
            return _make_route("local", ["v8:mic_sensitivity:1.28"], "MIC_SENSITIVITY")
        if key in {"microfone sensivel", "microfone sensível", "modo microfone sensivel", "modo microfone sensível", "me ouve mais baixo"}:
            return _make_route("local", ["v8:mic_sensitivity:1.18"], "MIC_SENSITIVITY")
        if key in {"microfone normal", "sensibilidade normal do microfone", "volta microfone normal"}:
            return _make_route("local", ["v8:mic_sensitivity:1.00"], "MIC_SENSITIVITY")
        if key in {"fala mais rapido", "fala mais rápido", "fale mais rapido", "fale mais rápido", "voz mais rapida", "voz mais rápida"}:
            return _make_route("local", ["v8:tts_rate:+14%"], "TTS_RATE")
        if key in {"velocidade normal da voz", "fala normal", "voz normal"}:
            return _make_route("local", ["v8:tts_rate:+10%"], "TTS_RATE")
        if key in {"fala mais devagar", "fale mais devagar", "voz mais devagar"}:
            return _make_route("local", ["v8:tts_rate:+4%"], "TTS_RATE")

        # Build 10: modos de interação são comandos locais determinísticos.
        # Ativação é exata para não confundir "vamos conversar sobre X" com
        # mudança de modo; a partir do modo conversa o wake deixa de ser exigido.
        mode_key = re.sub(r"\s+(?:agora|ai)\s*$", "", key, flags=re.I).strip()
        conversation_on = {
            "modo conversa", "ativar modo conversa", "ativa modo conversa",
            "entre no modo conversa", "entrar no modo conversa",
            "conversar", "vamos conversar", "modo de conversa",
        }
        conversation_off = {
            "sair do modo conversa", "sai do modo conversa",
            "desativar modo conversa", "desativa modo conversa",
            "encerrar modo conversa", "terminar modo conversa",
        }
        if mode_key in conversation_on:
            return _make_route("local", ["v8:mode:conversation"], "MODE_CONVERSATION")
        if mode_key in conversation_off:
            return _make_route("local", ["v8:mode:auto"], "MODE_AUTO")
        if mode_key in {"modo auto", "modo automatico", "o modo automatico", "ativar modo auto", "voltar modo auto"}:
            return _make_route("local", ["v8:mode:auto"], "MODE_AUTO")
        if mode_key in {"modo comando", "ativar modo comando", "entre no modo comando"}:
            return _make_route("local", ["v8:mode:command"], "MODE_COMMAND")

        # Controles extremamente comuns ficam explícitos no V8 em vez de
        # depender do parser legado. São reversíveis e ideais para Fast Lane.
        # "agora" é apenas um marcador temporal e não deve expulsar um comando
        # simples da rota rápida.
        direct_key = re.sub(r"\s+(?:agora|ai)\s*$", "", key, flags=re.I).strip()
        # "já" e marcador de afirmacao em frases como "já abri o Discord" e
        # nao pode ser removido globalmente. So o tratamos como hesitacao quando
        # o restante e um controle de midia inequivoco.
        direct_key = re.sub(
            r"^ja\s+(?=(?:proxima musica|proxima faixa|proximo|proxima|seguinte|passa(?:r)? (?:a )?musica)\b)",
            "", direct_key, flags=re.I,
        ).strip()
        # Context Engine V3: perguntas sobre a midia atual nao vao ao Gemini.
        if re.search(r"\b(?:que|qual|oque|o que)\s+(?:musica|música|faixa)\s+(?:esta|está|ta|tá)\s+(?:tocando|ouvindo)\b", key) or key in {
            "que musica estou ouvindo", "qual musica estou ouvindo", "o que esta tocando", "oque esta tocando",
            "que episodio estou vendo", "qual episodio estou vendo", "o que estou assistindo", "oque estou assistindo",
        }:
            return _make_route("local", ["v8:media:status"], "MEDIA_STATUS")

        # Regras condicionais locais: QUANDO X -> FACA Y.
        if key in {"listar regras", "liste as regras", "minhas regras", "regras automaticas", "regras automáticas", "automacoes condicionais", "automações condicionais"}:
            return _make_route("local", ["v8:rules:list"], "CONDITIONAL_RULES")
        m_rule_del = re.match(r"^(?:apaga|apague|exclui|exclua|remove|remova)\s+(?:a\s+)?regra\s+(\d+)\b", key)
        if m_rule_del:
            return _make_route("local", [f"v8:rules:delete:{m_rule_del.group(1)}"], "CONDITIONAL_RULES")
        m_rule_toggle = re.match(r"^(ativa|ative|ativar|desativa|desative|desativar)\s+(?:a\s+)?regra\s+(\d+)\b", key)
        if m_rule_toggle:
            verb = m_rule_toggle.group(1)
            mode = "disable" if verb.startswith("des") else "enable"
            return _make_route("local", [f"v8:rules:{mode}:{m_rule_toggle.group(2)}"], "CONDITIONAL_RULES")
        if key in {"faz isso sempre", "faca isso sempre", "faça isso sempre", "de agora em diante faz isso", "sempre faz isso"}:
            return _make_route("local", ["v8:rules:promote_last"], "CONDITIONAL_RULES")
        if ConditionalRuleEngine is not None and key.startswith("quando "):
            try:
                parsed_rule = ConditionalRuleEngine.parse_request(cleaned)
            except Exception:
                parsed_rule = None
            if parsed_rule:
                builtin = str(parsed_rule.get("builtin") or "")
                if builtin == "auto_skip_intro":
                    return _make_route("local", ["v8:player_auto:skip:on"], "CONDITIONAL_RULES")
                if builtin == "auto_next_episode":
                    return _make_route("local", ["v8:player_auto:next:on"], "CONDITIONAL_RULES")
                payload = quote(json.dumps(parsed_rule, ensure_ascii=False, separators=(",", ":")), safe="")
                return _make_route("local", [f"v8:rules:add:{payload}"], "CONDITIONAL_RULES")

        # Fala natural costuma trazer um pequeno preambulo antes do controle
        # de midia ("vish, proxima musica", "tchau gente, proxima musica",
        # "ja, vixi, passa a musica"). Removemos SOMENTE prefixes sociais
        # conhecidos e somente quando o sufixo e um comando de midia exato.
        # Negacao nunca entra aqui.
        media_prefixes = {
            "vish", "vixi", "ixi", "eita", "opa", "beleza", "certo", "entao",
            "agora", "vai", "vamos", "tchau gente", "tchau", "jarvis", "javis",
            "oi jarvis", "ei jarvis", "e ai jarvis", "ja", "ja vish", "ja vixi",
        }

        media_map = {
            "pausa": "pausa", "pause": "pausa", "pausar": "pausa", "pausi": "pausa",
            "pausa a musica": "pausa", "pausa musica": "pausa", "pausa a faixa": "pausa",
            "continua": "continua", "continue": "continua", "continuar": "continua",
            "play": "continua", "plei": "continua", "pley": "continua", "resume": "continua",
            "toca": "continua", "toque": "continua", "tocar": "continua",
            "reproduz": "continua", "reproduza": "continua", "reproduzir": "continua",
            "retoma": "continua", "retome": "continua", "retomar": "continua",
            "para um pouco": "pausa", "mas para um pouco": "pausa",
            "para ai um pouco": "pausa", "da uma pausa": "pausa", "da uma pausada": "pausa",
            "proxima musica": "proxima musica", "proxima faixa": "proxima faixa",
            "proximo": "proxima musica", "proxima": "proxima musica", "seguinte": "proxima musica",
            "passa musica": "proxima musica", "passa a musica": "proxima musica",
            "passar musica": "proxima musica", "passe a musica": "proxima musica",
            "troca musica": "proxima musica", "troca a musica": "proxima musica",
            "muda musica": "proxima musica", "muda a musica": "proxima musica",
            "pula musica": "proxima musica", "pula a musica": "proxima musica",
            "pula essa musica": "proxima musica", "pula esta musica": "proxima musica",
            "manda musica": "proxima musica", "manda a musica": "proxima musica",
            "manda faixa": "proxima musica", "manda a faixa": "proxima musica",
            "manda outra musica": "proxima musica", "manda outra faixa": "proxima musica",
            "bota outra musica": "proxima musica", "bote outra musica": "proxima musica",
            "segura a musica": "pausa", "segura a faixa": "pausa", "segura o som": "pausa",
            "musica anterior": "musica anterior", "faixa anterior": "faixa anterior",
            "volta musica": "musica anterior", "volta a musica": "musica anterior",
        }
        if direct_key not in media_map and not re.search(r"\b(?:nao|não|nunca|nem)\b", direct_key):
            for phrase in sorted(media_map, key=len, reverse=True):
                suffix = " " + phrase
                if direct_key.endswith(suffix):
                    prefix = direct_key[:-len(suffix)].strip(" ,.-")
                    if prefix in media_prefixes:
                        direct_key = phrase
                        break

        if direct_key in media_map:
            mapped_media = media_map[direct_key]
            intent = "MEDIA_NEXT" if mapped_media.startswith("proxima") else "MEDIA_PREVIOUS" if "anterior" in mapped_media else "MEDIA_CONTROL"
            return _make_route("local", [mapped_media], intent)

        if direct_key in {
            "tela cheia", "modo tela cheia", "coloca em tela cheia", "coloque em tela cheia",
            "fica em tela cheia", "ficar em tela cheia", "fullscreen",
            "sai da tela cheia", "sair da tela cheia", "tira da tela cheia", "tirar da tela cheia",
        }:
            return _make_route("local", ["v8:fullscreen"], "FULLSCREEN")

        if direct_key in {
            "modo gamer", "modo game", "ativar modo gamer", "ativa modo gamer",
            "ativar modo de jogo", "ativa modo de jogo",
        }:
            return _make_route("local", ["v8:gamer:on"], "MODE_GAMER")

        # Build 13.11: percentuais reais do painel tambem podem ser ajustados por texto/voz.
        m_presence_pct = re.fullmatch(r"(?:presenca|presença)(?:\s+do\s+jarvis)?\s+(20|40|60|80|100)(?:\s*por\s*cento|\s*%)?", direct_key, re.I)
        if m_presence_pct:
            return _make_route("local", [f"v8:presence_percent:{m_presence_pct.group(1)}"], "PRESENCE_MODE")
        m_autonomy_pct = re.fullmatch(r"autonomia(?:\s+do\s+jarvis)?\s+(20|40|60|80|100)(?:\s*por\s*cento|\s*%)?", direct_key, re.I)
        if m_autonomy_pct:
            return _make_route("local", [f"v8:autonomy_percent:{m_autonomy_pct.group(1)}"], "AUTONOMY_MODE")

        # Build 11: niveis de presenca e autonomia ficam separados do modo de voz.
        presence_map = {
            "zero discreto": "discreto", "jarvis discreto": "discreto", "modo discreto": "discreto",
            "zero assistente": "assistente", "jarvis assistente": "assistente", "modo assistente": "assistente",
            "zero jarvis": "jarvis", "jarvis": "jarvis", "modo jarvis": "jarvis", "presenca jarvis": "jarvis",
        }
        original_mode_key = re.sub(r"\s+(?:agora|ai)\s*$", "", original_key, flags=re.I).strip()
        presence_key = original_mode_key if original_mode_key in presence_map else direct_key
        if presence_key in presence_map:
            return _make_route("local", [f"v8:presence:{presence_map[presence_key]}"], "PRESENCE_MODE")
        autonomy_map = {
            "autonomia manual": "manual", "modo manual": "manual",
            "autonomia assistida": "assistido", "modo assistido": "assistido",
            "autonomia autonoma": "autonomo", "autonomia autonomo": "autonomo",
            "modo autonomo": "autonomo",
        }
        if direct_key in autonomy_map:
            return _make_route("local", [f"v8:autonomy:{autonomy_map[direct_key]}"], "AUTONOMY_MODE")

        # Automação explícita do player. É opt-in e persistente; não nasce
        # apenas por estar em modo autônomo.
        player_auto = re.sub(r"\s+(?:agora|ai)$", "", direct_key).strip()
        if re.fullmatch(r"(?:pular|pule|pula) (?:as )?(?:aberturas|intros|introducoes) automaticamente", player_auto):
            return _make_route("local", ["v8:player_auto:skip:on"], "PLAYER_AUTOMATION")
        if re.fullmatch(r"(?:nao |nao quero )?(?:pular|pule|pula) (?:as )?(?:aberturas|intros|introducoes) automaticamente", player_auto) and player_auto.startswith("nao"):
            return _make_route("local", ["v8:player_auto:skip:off"], "PLAYER_AUTOMATION")
        if player_auto in {"desativa pular abertura automatico", "desativar pular abertura automatico", "parar de pular aberturas automaticamente"}:
            return _make_route("local", ["v8:player_auto:skip:off"], "PLAYER_AUTOMATION")
        if re.fullmatch(r"(?:ir|vai|passa|passar) (?:para o )?proximo episodio automaticamente", player_auto):
            return _make_route("local", ["v8:player_auto:next:on"], "PLAYER_AUTOMATION")
        if player_auto in {"desativa proximo episodio automatico", "desativar proximo episodio automatico", "parar proximo episodio automatico"}:
            return _make_route("local", ["v8:player_auto:next:off"], "PLAYER_AUTOMATION")
        if player_auto in {
            "automacao do streaming", "automacoes do streaming", "automacao de streaming",
            "status da automacao do streaming", "status automacao streaming",
            "automacao do player", "automacoes do player", "status automacao player",
            # Compatibilidade com o nome usado na Build 12.
            "automacao do crunchyroll", "automacoes do crunchyroll",
            "status da automacao do crunchyroll", "status automacao crunchyroll",
        }:
            return _make_route("local", ["v8:player_auto:status"], "PLAYER_AUTOMATION")

        # Contexto operacional: respostas locais e verificáveis, sem Gemini.
        if key in {
            "o que voce sabe agora", "o que voce sabe", "contexto atual",
            "contexto operacional", "onde estamos", "onde eu estou agora",
        }:
            return _make_route("local", ["v8:operational_context"], "OPERATIONAL_CONTEXT")
        if key in {"ultimo download", "qual foi o ultimo download", "o que eu baixei agora", "arquivo que baixei agora"}:
            return _make_route("local", ["v8:last_download"], "LAST_DOWNLOAD")
        if key in {"o que copiei", "o que esta copiado", "area de transferencia", "clipboard"}:
            return _make_route("local", ["v8:clipboard"], "CLIPBOARD_CONTEXT")

        # Comando curto e contextual. Primeiro tenta um botao de pular no
        # player/navegador; se nao houver, a camada de execucao cai para
        # proxima faixa do player do Windows.
        if key in {"pula", "skip"}:
            return _make_route("local", ["v8:smart_skip"], "SMART_SKIP")

        # Rotinas aprendidas usam apenas comandos de alto nivel verificados.
        m_workflow_start = re.match(r"^(?:aprende|aprender|aprenda|ensina|ensinar|grava|gravar) (?:a )?(?:rotina|workflow)(?:\s+(?:de|da|do|das|dos))?\s+(.+)$", key)
        if m_workflow_start:
            return _make_route("local", [f"v8:workflow:start:{m_workflow_start.group(1).strip()}"], "WORKFLOW_START")
        if key in {"terminar rotina", "finalizar rotina", "parar de aprender rotina", "salvar rotina"}:
            return _make_route("local", ["v8:workflow:stop"], "WORKFLOW_STOP")
        # "abre rotina trabalho" e natural em voz e deve executar a rotina,
        # nunca cair no resolvedor de aplicativos do Windows.
        m_workflow_run = re.match(r"^(?:executa|execute|rodar|roda|inicia|iniciar|abre|abra|abrir) (?:a )?(?:rotina|workflow)(?:\s+(?:de|da|do|das|dos))?\s+(.+)$", key)
        if m_workflow_run:
            return _make_route("local", [f"v8:workflow:run:{m_workflow_run.group(1).strip()}"], "WORKFLOW_RUN")
        if key in {"listar rotinas", "lista rotinas", "minhas rotinas", "quais rotinas"}:
            return _make_route("local", ["v8:workflow:list"], "WORKFLOW_LIST")
        m_workflow_delete = re.match(r"^(?:apaga|apagar|exclui|excluir|esquece) (?:a )?(?:rotina|workflow)(?:\s+(?:de|da|do|das|dos))?\s+(.+)$", key)
        if m_workflow_delete:
            return _make_route("local", [f"v8:workflow:delete:{m_workflow_delete.group(1).strip()}"], "WORKFLOW_DELETE")

        # English browser search keeps the original punctuation from `cleaned`.
        m_en_search = re.match(
            r"^(?:search|look up|find)\s+(.+?)\s+(?:on|in)\s+opera(?:\s+gx)?$",
            cleaned, re.I,
        )
        if not m_en_search:
            m_en_search = re.match(
                r"^(?:search|look up|find)\s+(?:on|in)\s+opera(?:\s+gx)?\s+(.+)$",
                cleaned, re.I,
            )
        if m_en_search:
            query = _clean_spoken_search_query(m_en_search.group(1))
            return _make_route("local", [f"v8:browser_search:Opera|{query}"], "BROWSER_SEARCH")

        # Pesquisa falada no formato "vai no Opera pesquisar X". Para uma
        # unica pesquisa nao precisamos acionar o planner: abrir a URL de busca
        # no Opera ja abre/foca o navegador e reduz latencia. Objetivos compostos
        # continuam indo para o Agent logo abaixo.
        m_go_search = re.match(
            r"^(?:vai|va|abre|abra|entra|entre)\s+(?:(?:no|na|pro|pra|para o|para a|o|a)\s+)?(?:[óo]pera(?: gx)?|opero(?: gx)?|oper(?: gx)?|meu navegador|navegador)\s+(?:e\s+)?(?:pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar)\s+(.+)$",
            cleaned, re.I,
        )
        if m_go_search:
            query = _clean_spoken_search_query(m_go_search.group(1))
            if not re.search(r"\b(?:depois|agora|entao)\b.*\b(?:abre|entra|baixa|download|clica)\b", query, re.I):
                return _make_route("local", [f"v8:browser_search:Opera|{query}"], "BROWSER_SEARCH")

        # Objetivos autonomos: mantem o texto original para o planner local.
        agent_key = key
        search_agent_verb = r"(?:pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar)"
        monitor_prefix = (
            r"(?:(?:(?:na|no)\s+)?(?:tela|monitor|display)\s*(?:numero\s*)?"
            r"(?:\d+|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|"
            r"primeiro|primeira|segundo|segunda|terceiro|terceira|quarto|quarta)\s+)?"
        )
        # Controles simples do player nao precisam do Goal Executor. Eles sao
        # locais, reversiveis e ganham uma rota direta (menor latencia e sem HUD
        # de objetivo para uma acao de um unico passo).
        # Player desktop direcionado. Frases como "e no Spotify" guardam o
        # alvo para o próximo comando curto; "pausa no Spotify" já executa
        # diretamente no processo correto via WM_APPCOMMAND.
        m_media_context = re.match(
            r"^(?:e|eh|era)\s+(?:no|na)\s+(spotify|vlc)\b",
            agent_key,
            re.I,
        )
        if (
            not m_media_context
            and not re.match(r"^(?:pausa|pause|pausar|pausi|continua|continue|continuar|play|plei|pley|toca|toque|tocar|retoma|retome|retomar|reproduz|reproduza|reproduzir|proxima|anterior)\b", agent_key, re.I)
            and re.search(r"\b(?:play|pause|pausa|tentando|controlar|controle)\b", agent_key, re.I)
        ):
            m_media_context = re.search(r"\b(?:no|na)\s+(spotify|vlc)\b", agent_key, re.I)
        if m_media_context:
            return _make_route("local", [f"v8:media_target:{m_media_context.group(1).lower()}"], "MEDIA_TARGET")

        m_media_direct = re.fullmatch(
            r"(pausa|pause|pausar|pausi|continua|continue|continuar|play|plei|pley|toca|toque|tocar|"
            r"retoma|retome|retomar|reproduz|reproduza|reproduzir|proxima|próxima|anterior)"
            r"\s+(?:a\s+musica\s+)?(?:(?:no|na)\s+)?(spotify|vlc)"
            r"(?:\s+(?:no|na)?\s*(?:monitor|monito|tela|display)\s*(?:\d+|um|dois|tres|quatro))?",
            agent_key,
            re.I,
        )
        if m_media_direct:
            verb = _norm(m_media_direct.group(1))
            target = m_media_direct.group(2).lower()
            if verb in {"pausa", "pause", "pausar"}:
                action = "pause"
            elif verb in {"continua", "continue", "continuar", "play", "plei", "pley", "toca", "toque", "tocar", "retoma", "retome", "retomar", "reproduz", "reproduza", "reproduzir"}:
                action = "play"
            elif verb in {"proxima", "próxima"}:
                action = "next"
            else:
                action = "previous"
            return _make_route("local", [f"v8:media:{action}|{target}"], "MEDIA_CONTROL")

        # Streaming universal. Quando uma plataforma e citada explicitamente,
        # preservamos o nome para o BrowserAutonomy validar contexto/atalhos.
        streaming_name = r"(?:crunchy\s*roll|netflix|prime\s*video|amazon\s*prime|disney(?:\s*plus|\+)?|hbo\s*max|max|globoplay|globo\s*play|paramount(?:\s*plus|\+)?|apple\s*tv|youtube|twitch|plex|jellyfin|stremio|kodi|mubi|claro\s*tv(?:\+)?)"

        # Forma muito comum em pt-BR: acao primeiro, plataforma depois.
        m_stream_suffix_skip = re.match(
            monitor_prefix + rf"(?:pula(?:r)? (?:a )?(?:abertura|intro|introducao)|skip (?:intro|opening))\s+(?:no|na)\s+({streaming_name})\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_stream_suffix_skip:
            monitor = _monitor_number(agent_key) or 0
            service = m_stream_suffix_skip.group(1).strip().replace("|", " ")
            return _make_route("local", [f"v8:player:skip:{monitor}|{service}"], "STREAMING_SKIP")

        m_stream_suffix_next = re.match(
            monitor_prefix + rf"(?:proximo episodio|proximo ep|pula(?:r)? episodio|(?:passa|passar|passe)(?:\s+(?:pro|para o|pelo)\s+proximo(?: episodio| ep)?|\s+episodio)|next episode)\s+(?:no|na)\s+({streaming_name})\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_stream_suffix_next:
            monitor = _monitor_number(agent_key) or 0
            service = m_stream_suffix_next.group(1).strip().replace("|", " ")
            return _make_route("local", [f"v8:player:next:{monitor}|{service}"], "STREAMING_NEXT")

        m_stream_suffix_seek = re.match(
            monitor_prefix + rf"(?:(?:pula|pular|avanca|avancar|adianta|adiantar)\s+(\d+)\s*(?:segundos?|s)|(?:volta|voltar|retrocede|retroceder)\s+(\d+)\s*(?:segundos?|s))\s+(?:no|na)\s+({streaming_name})\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_stream_suffix_seek:
            monitor = _monitor_number(agent_key) or 0
            forward, backward = m_stream_suffix_seek.group(1), m_stream_suffix_seek.group(2)
            seconds = int(forward or backward or 10) * (-1 if backward else 1)
            seconds = max(-600, min(seconds, 600))
            service = m_stream_suffix_seek.group(3).strip().replace("|", " ")
            return _make_route("local", [f"v8:player:seek:{seconds}:{monitor}|{service}"], "STREAMING_SEEK")

        m_stream_suffix_simple = re.match(
            monitor_prefix + rf"(?:(pausa|pause|continua|continue|play|reproduz|reproduzir)|(tela cheia|fullscreen|full screen)|(legendas|legenda|subtitles|closed captions|cc)|(mudo|mute|mutar))\s+(?:no|na)\s+({streaming_name})\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_stream_suffix_simple:
            service = m_stream_suffix_simple.group(5).strip().replace("|", " ")
            action = "play_pause" if m_stream_suffix_simple.group(1) else "fullscreen" if m_stream_suffix_simple.group(2) else "captions" if m_stream_suffix_simple.group(3) else "mute"
            return _make_route("local", [f"v8:player:{action}:0|{service}"], "STREAMING_CONTROL")

        m_stream_skip = re.match(
            monitor_prefix + rf"(?:(?:no|na)\s+({streaming_name})\s+)?"
            r"(?:pula(?:r)? (?:a )?(?:abertura|intro|introducao)|skip (?:intro|opening))\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_stream_skip and m_stream_skip.group(1):
            monitor = _monitor_number(agent_key) or 0
            service = m_stream_skip.group(1).strip().replace("|", " ")
            return _make_route("local", [f"v8:player:skip:{monitor}|{service}"], "STREAMING_SKIP")

        m_stream_next = re.match(
            monitor_prefix + rf"(?:(?:no|na)\s+({streaming_name})\s+)?"
            r"(?:proximo episodio|proximo ep|pula(?:r)? episodio|(?:passa|passar|passe)(?:\s+(?:pro|para o|pelo)\s+proximo(?: episodio| ep)?|\s+episodio)|next episode)"
            r"\s*(?:ai|agora|por favor)?$", agent_key, re.I,
        )
        if m_stream_next and m_stream_next.group(1):
            monitor = _monitor_number(agent_key) or 0
            service = m_stream_next.group(1).strip().replace("|", " ")
            return _make_route("local", [f"v8:player:next:{monitor}|{service}"], "STREAMING_NEXT")

        m_stream_seek = re.match(
            monitor_prefix + rf"(?:(?:no|na)\s+({streaming_name})\s+)?"
            r"(?:(?:pula|pular|avanca|avancar|adianta|adiantar)\s+(\d+)\s*(?:segundos?|s)|"
            r"(?:volta|voltar|retrocede|retroceder)\s+(\d+)\s*(?:segundos?|s))\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_stream_seek and m_stream_seek.group(1):
            monitor = _monitor_number(agent_key) or 0
            forward = m_stream_seek.group(2)
            backward = m_stream_seek.group(3)
            seconds = int(forward or backward or 10) * (-1 if backward else 1)
            seconds = max(-600, min(seconds, 600))
            service = m_stream_seek.group(1).strip().replace("|", " ")
            return _make_route("local", [f"v8:player:seek:{seconds}:{monitor}|{service}"], "STREAMING_SEEK")

        m_stream_simple = re.match(
            rf"(?:(?:no|na)\s+({streaming_name})\s+)?(?:"
            r"(pausa|pause|continua|continue|play|reproduz|reproduzir)|"
            r"(tela cheia|fullscreen|full screen)|"
            r"(legendas|legenda|subtitles|closed captions|cc)|"
            r"(mudo|mute|mutar))\s*(?:ai|agora|por favor)?$", agent_key, re.I,
        )
        if m_stream_simple and m_stream_simple.group(1):
            service = m_stream_simple.group(1).strip().replace("|", " ")
            action = "play_pause" if m_stream_simple.group(2) else "fullscreen" if m_stream_simple.group(3) else "captions" if m_stream_simple.group(4) else "mute"
            return _make_route("local", [f"v8:player:{action}:0|{service}"], "STREAMING_CONTROL")

        m_crunchy_skip = re.match(
            monitor_prefix + r"(?:(?:no|na)\s+crunchyroll\s+)?"
            r"(?:pula(?:r)? (?:a )?(?:abertura|intro|introducao))\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_crunchy_skip:
            monitor = _monitor_number(agent_key) or 0
            return _make_route("local", [f"v8:crunchy:skip:{monitor}"], "CRUNCHY_SKIP")

        m_crunchy_seek = re.match(
            monitor_prefix + r"(?:(?:no|na)\s+crunchyroll\s+)?"
            r"(?:(?:pula|pular|avanca|avancar|adianta|adiantar)\s+(\d+)\s*(?:segundos?|s)|"
            r"(?:skip|jump)(?:\s+forward)?\s+(\d+)\s*(?:seconds?|s))\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_crunchy_seek:
            monitor = _monitor_number(agent_key) or 0
            seconds = int(m_crunchy_seek.group(1) or m_crunchy_seek.group(2) or 10)
            seconds = max(1, min(seconds, 180))
            return _make_route("local", [f"v8:crunchy:seek:{seconds}:{monitor}"], "CRUNCHY_SEEK")

        m_crunchy_back = re.match(
            monitor_prefix + r"(?:(?:no|na)\s+crunchyroll\s+)?"
            r"(?:(?:volta|voltar|retrocede|retroceder)\s+(\d+)\s*(?:segundos?|s)|"
            r"(?:go|jump)\s+back\s+(\d+)\s*(?:seconds?|s))\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_crunchy_back:
            monitor = _monitor_number(agent_key) or 0
            seconds = int(m_crunchy_back.group(1) or m_crunchy_back.group(2) or 10)
            seconds = -max(1, min(seconds, 180))
            return _make_route("local", [f"v8:crunchy:seek:{seconds}:{monitor}"], "CRUNCHY_SEEK")

        m_crunchy_next = re.match(
            monitor_prefix + r"(?:(?:no|na)\s+crunchyroll\s+)?"
            r"(?:proximo episodio|proximo ep|pula(?:r)? episodio|"
            r"(?:passa|passar|passe)(?:(?:\s+(?:pro|para o|pelo)\s+proximo(?: episodio| ep)?)|(?:\s+episodio)))"
            r"\s*(?:ai|agora|por favor)?$",
            agent_key, re.I,
        )
        if m_crunchy_next:
            monitor = _monitor_number(agent_key) or 0
            return _make_route("local", [f"v8:crunchy:next:{monitor}"], "CRUNCHY_NEXT")

        direct_agent = bool(
            re.match(
                monitor_prefix + r"(?:(?:no|na)\s+crunchyroll\s+)?"
                r"(?:pula(?:r)? (?:a )?(?:abertura|intro|introducao)|pula(?:r)? episodio|proximo episodio|proximo ep|"
                r"(?:passa|passar|passe) (?:(?:pro|para o|pelo) )?proximo(?: episodio| ep)?)\b",
                agent_key, re.I,
            )
            or re.match(
                rf"^(?:vai|va|abre|abra|entra|entre)\s+(?:(?:no|na|pro|pra|para o|para a)\s+)?"
                rf"(?:opera(?: gx)?|opero(?: gx)?|meu navegador|navegador)\s+(?:e\s+)?{search_agent_verb}\b.*"
                rf"(?:depois|agora|entao|e)\s+(?:abre|abra|entra|entre|baixa|baixe|baixar|download|clica|clique)\b",
                agent_key, re.I,
            )
            or re.match(
                rf"^{search_agent_verb}\b.*(?:depois|agora|entao|e)\s+"
                rf"(?:abre|abra|entra|entre|baixa|baixe|baixar|download|clica|clique)\b",
                agent_key, re.I,
            )
            or re.match(
                r"^(?:abre|abra|entra|entre)\b.*(?:depois|agora|entao|e)\s+(?:baixa|baixe|baixar|download)\b",
                agent_key, re.I,
            )
            or re.match(r"^(?:baixa|baixe|baixar|download)\s+(?:esse|este|o)\s+(?:arquivo|download)\b", agent_key, re.I)
            or re.match(r"^(?:entra|entre|abre|abra)\s+(?:nesse|neste|no)\s+(?:site|resultado)\b", agent_key, re.I)
            or re.match(r"^(?:clica|clique)\s+(?:no|na|em)\b", agent_key, re.I)
        )
        # Perguntas, explicacoes e negacoes que apenas mencionam uma acao nao
        # podem disparar automacao. Ex.: "como pular a abertura?" ou
        # "nao pula a abertura" devem permanecer conversa/no-op.
        if direct_agent and re.match(
            r"^(?:nao|nunca|como|por que|porque|quando|onde|qual|quais|quem|o que|"
            r"(?:voce\s+)?consegue|da pra|daria pra|quero saber|me explica|explique|vamos conversar sobre)\b",
            agent_key, re.I,
        ):
            direct_agent = False
        # Verbos genéricos como "faz/cria" já pertencem ao Router local.
        # O Agent só assume quando a autonomia foi pedida explicitamente no fim.
        m_goal = re.match(
            r"^(?:zero[, ]+)?(?:faz|faca|resolve|resolva|executa|execute)\s+(.+?)\s+(?:por mim|sozinho|sozinha)$",
            cleaned, re.I,
        )
        if m_goal and len(m_goal.group(1).strip()) >= 3:
            goal = m_goal.group(1).strip().replace("|", " ")
            return _make_route("local", [f"v8:goal:{goal}"], "AGENT_GOAL")
        if direct_agent:
            goal = cleaned.strip().replace("|", " ")
            return _make_route("local", [f"v8:goal:{goal}"], "AGENT_GOAL")

        # Slots de dialogo curtos: completam somente a informacao que faltou no
        # turno anterior. Nao transformam qualquer frase em comando e expiram.
        if self.context is not None:
            if key in {"cancela", "cancelar", "deixa", "deixa pra la", "esquece"}:
                if self.context.pending_kinds():
                    self.context.clear_pending()
                    return _make_route("local", ["v8:slot_cancelled"], "DIALOG_CANCEL")

            pending_move = self.context.pending("move_monitor")
            if pending_move:
                target = str(pending_move.get("value") or "").strip()
                monitor = _monitor_number(key)
                if monitor is None:
                    simple = {"1": 1, "um": 1, "primeiro": 1, "primeira": 1,
                              "2": 2, "dois": 2, "segundo": 2, "segunda": 2,
                              "3": 3, "tres": 3, "terceiro": 3, "terceira": 3,
                              "4": 4, "quatro": 4, "quarto": 4, "quarta": 4}
                    monitor = simple.get(key)
                if target and monitor:
                    self.context.clear_pending("move_monitor")
                    return _make_route("local", [f"move {target} para monitor {monitor}"], "MOVE_WINDOW_CONTEXT")
                if target and is_other_monitor_fragment(cleaned):
                    self.context.clear_pending("move_monitor")
                    return _make_route("local", [f"v8:move_other:{target}"], "MOVE_OTHER_CONTEXT")
                # Um novo comando explicito abandona a pergunta antiga.
                if ACTION_RE.match(key):
                    self.context.clear_pending("move_monitor")

            pending_search = self.context.pending("browser_search")
            if pending_search:
                browser = str(pending_search.get("value") or "Opera").strip() or "Opera"
                if not ACTION_RE.match(key) and len(cleaned.strip()) >= 2:
                    self.context.clear_pending("browser_search")
                    query = cleaned.replace("|", " ").strip()
                    return _make_route("local", [f"v8:browser_search:{browser}|{query}"], "BROWSER_SEARCH_CONTEXT")
                if ACTION_RE.match(key):
                    self.context.clear_pending("browser_search")

            pending_target = self.context.pending("action_target")
            if pending_target:
                action = str(pending_target.get("value") or "").strip().lower()
                if not ACTION_RE.match(key) and len(cleaned.strip()) >= 2:
                    target = _clean_target(cleaned)
                    self.context.clear_pending("action_target")
                    if action == "close":
                        return _make_route("local", [f"fecha {target}"], "CLOSE_APP_CONTEXT")
                    if action == "open":
                        return _make_route("local", [f"abre {target}"], "OPEN_APP_CONTEXT")
                if ACTION_RE.match(key):
                    self.context.clear_pending("action_target")

        # Feedback positivo tambem e uma intencao local. Antes, frases comuns
        # como "funcionou" iam ao Gemini e, se a rede oscilasse, viravam o
        # fallback sem sentido "Entendi. Pode continuar.".
        feedback_key = _norm(cleaned)
        if re.match(
            r"^(?:funcionou|agora foi|deu certo|foi agora|foi sim|resolveu|resolvido|"
            r"perfeito|perfeita|boa|muito bom|muito boa|excelente|isso ai|isso mesmo|foi)\b",
            feedback_key,
        ):
            return _make_route("local", ["v8:positive_feedback"], "USER_SUCCESS")

        # Feedback operacional vem antes de conversa/legado. Frases longas como
        # "nao foi, so moveu o painel do Photoshop" continuam sendo feedback.
        if re.match(
            r"^(?:nao foi|nao funcionou|nao deu certo|deu errado|isso nao foi|isso nao funcionou|"
            r"continua errado|ta errado|esta errado|errou)\b",
            feedback_key,
        ):
            self.mark_feedback(cleaned)
            return _make_route("local", ["v8:correction_feedback"], "USER_CORRECTION")

        # Follow-up pronominal sem uma acao estruturada nao pode virar CRIACAO.
        # "faz isso" e "faz aquilo" precisam de contexto conversacional; antes
        # chegavam ao legado como "cria isso".
        if feedback_key in {
            "faz isso", "faca isso", "fazer isso", "faz isto", "faca isto",
            "faz aquilo", "faca aquilo", "faz o que voce falou", "faz o que disse",
        }:
            return V8Route("conversation", [], intent="CONTEXT_FOLLOWUP")

        # Undo contextual: nunca usa a janela ativa por chute. So existe se uma
        # acao verificada deixou evidencia suficiente no Context Engine.
        if feedback_key in {"volta", "voltar", "desfaz", "desfazer", "desfaz isso", "volta isso", "volta como tava", "volta como estava"}:
            undo = self.context.undo_command() if self.context is not None else None
            return _make_route("local", [undo or "v8:clarify_undo"], "UNDO_LAST_ACTION")

        # Perguntas sobre o próprio JARVIS devem refletir as capacidades locais
        # reais, sem deixar o modelo inventar que "não consegue mexer no PC".
        if re.search(r"\b(?:o que voce consegue fazer|o que voce sabe fazer|quais sao suas funcoes|suas funcoes|funcoes do jarvis|o que o jarvis (?:pode|consegue|sabe) fazer)\b", key):
            return _make_route("local", ["v8:capabilities"], "CAPABILITIES")
        if key in {"velocidade do jarvis", "latencia do jarvis", "tempo de resposta do jarvis"}:
            return _make_route("local", ["v8:performance"], "PERFORMANCE")

        # Opinião sobre o PC usa telemetria real e uma avaliação curta local.
        if re.search(r"^(?:o que voce acha|que que voce acha|qual sua opiniao)\s+(?:do|sobre o)\s+(?:meu|o)\s+(?:pc|computador)\b", key):
            return _make_route("local", ["v8:pc_opinion"], "PC_OPINION")

        # Diagnostico do computador e visao sao semanticos e precisam ganhar de
        # "me explica...", que normalmente e conversa. Mas "me explica como
        # colocar em tela cheia" é uma pergunta sobre uma ação, não um pedido
        # para observar/capturar a tela.
        if PC_DIAG_RE.search(key):
            return _make_route("local", ["status do pc"], "PC_DIAGNOSE")
        if re.match(r"^(?:me explica|me explique|pode me explicar)\s+como\b", key, re.I):
            return V8Route("conversation", [], intent="CONVERSATION")
        if VISUAL_ANCHOR_RE.search(key) and VISUAL_INTENT_RE.search(key):
            mon = _monitor_number(key)
            # Preserve the original question only when the user asks about a
            # specific visual object/meaning. Generic "descreve a tela" keeps
            # the compact canonical command used by older modules/tests.
            specific = bool(re.search(
                r"\b(?:imagem|foto|figura|botao|icone|erro|aviso|texto|mensagem|objeto|parte|detalhe)\b",
                key, re.I,
            ))
            if mon:
                self._remember_monitor(mon)
                if specific:
                    question = cleaned.replace("|", " ")
                    return _make_route("local", [f"v8:vision:{mon}|{question}"], "VISION")
                return _make_route("local", [f"descreve monitor {mon}"], "VISION")
            if specific:
                question = cleaned.replace("|", " ")
                return _make_route("local", [f"v8:vision:active|{question}"], "VISION")
            return _make_route("local", ["descreve minha tela"], "VISION")

        # Conversa ganha antes de parsers de app/arquivo, exceto as rotas
        # semanticas explicitas acima.
        if CONVERSATION_RE.match(key):
            # Diagnostico de PC ja foi decidido acima por PC_DIAG_RE. Nao basta
            # conter a palavra "computador": "como funciona a memoria de um
            # computador" e uma pergunta explicativa, nao um pedido de status.
            if SOCIAL_RE.match(key):
                return _make_route("local", ["v8:social_chat"], "SOCIAL_CHAT")
            return V8Route("conversation", [], intent="CONVERSATION")

        # Pedidos informacionais usam entidade + contexto, nao listas de frases.
        query_key = _request_key(cleaned)
        semantic_info = _semantic_info_command(query_key)
        if semantic_info:
            command, intent = semantic_info
            return _make_route("local", [command], intent)

        # Referência curta e segura: "tela 2" / "monitor dois" significa
        # descrever aquela tela. Não passa por Gemini nem pelo parser legado.
        direct_mon = _monitor_number(query_key)
        if direct_mon and re.match(
            r"^(?:(?:monitor|tela|display)\s*(?:\d+|um|dois|tres|quatro)|"
            r"(?:primeiro|segundo|terceiro|quarto|primeira|segunda|terceira|quarta)\s+(?:monitor|tela|display))$",
            query_key,
        ):
            self._remember_monitor(direct_mon)
            return _make_route("local", [f"descreve monitor {direct_mon}"], "VISION")

        # 3) Visão explícita e contexto curto: "nele" só é aceito se houver monitor lembrado.
        if VISION_RE.search(key):
            mon = _monitor_number(key)
            if mon:
                self._remember_monitor(mon)
                return _make_route("local", [f"descreve monitor {mon}"], "VISION")
            return _make_route("local", ["descreve minha tela"], "VISION")

        last_app, last_monitor = self._context()

        # "o outro" aponta para o alvo verificado anterior, nunca para uma
        # janela aleatoria. Ex.: abre OBS e Opera -> "o outro manda pra tela 2".
        m_other_ref = re.match(
            r"^(?:agora\s+)?(?:o\s+outro|a\s+outra|outro|outra)\s+(?:manda|mande|move|mova|coloca|coloque|joga|jogue|leva|leve)\s+"
            r"(?:(?:ele|ela)\s+)?(?:(?:para|pra|pro|na|no)\s+)?(?:o\s+|a\s+)?(?:monitor|tela|display)\s*(\d+|um|dois|tres|quatro)$",
            key, flags=re.I,
        )
        if not m_other_ref:
            # normalize_broken_command converte "o outro manda..." para
            # "move outro para..." antes desta etapa. Aceite a forma canonica
            # sem deixar "outro" virar nome de aplicativo.
            m_other_ref = re.match(
                r"^(?:move|mova|coloca|coloque|joga|jogue|leva|leve)\s+(?:o\s+|a\s+)?(?:outro|outra)\s+"
                r"(?:(?:para|pra|pro|na|no)\s+)?(?:o\s+|a\s+)?(?:monitor|tela|display)\s*(\d+|um|dois|tres|quatro)$",
                key, flags=re.I,
            )
        if m_other_ref and self.context is not None:
            try:
                if hasattr(self.context, "resolve_reference"):
                    ref = self.context.resolve_reference("o outro", domain="app", exclude=last_app or "")
                    other_target = str((ref or {}).get("value") or "") or None
                else:
                    other_target = self.context.previous_target(exclude=last_app or "")
            except Exception:
                other_target = None
            monitor_value = _monitor_number(f"tela {m_other_ref.group(1)}")
            if other_target and monitor_value:
                return _make_route("local", [f"move {other_target} para monitor {monitor_value}"], "MOVE_WINDOW_CONTEXT")
            return _make_route("local", ["v8:clarify_app"], "CLARIFY_APP")

        # O STT pode engolir o verbo: "Opera para a segunda tela". Como o
        # destino de monitor e explicito, a intencao de janela e restrita; o
        # executor ainda verifica a existencia do aplicativo antes de mover.
        bare_move = re.match(
            r"^(.+?)\s+(?:para|pra|pro|na|no)\s+(?:(?:a|o)\s+)?"
            r"(?:(?:monitor|monito|tela|display)\s*(\d+)|(primeira|segunda|terceira|quarta|primeiro|segundo|terceiro|quarto)\s+(?:monitor|monito|tela|display))$",
            cleaned, flags=re.I,
        )
        if bare_move:
            target = _clean_target(bare_move.group(1))
            target_key = _norm(target)
            if target_key not in {"eu", "voce", "vc", "isso", "isto", "aquilo", "musica", "faixa"} and not re.match(
                r"^(?:abre|abra|abrir|fecha|feche|fechar|minimiza|minimize|maximiza|maximize|"
                r"move|mova|mover|coloca|coloque|colocar|bota|bote|botar|transfere|transfira|transferir|"
                r"passa|passe|passar|manda|mande|mandar|envia|envie|enviar|joga|jogue|jogar|mete|meta|taca|taque|empurra|empurre|"
                r"leva|leve|levar|volta|volte|retorna|retorne|pesquisa|pesquise|procura|busca|pausa|pause|play|continua)\b",
                target_key,
            ):
                monitor_value = bare_move.group(2) or {
                    "primeira": "1", "primeiro": "1", "segunda": "2", "segundo": "2",
                    "terceira": "3", "terceiro": "3", "quarta": "4", "quarto": "4",
                }.get(_norm(bare_move.group(3)), "")
                if monitor_value:
                    return _make_route("local", [f"move {target} para monitor {monitor_value}"], "MOVE_WINDOW")

        # Follow-up elíptico comum em voz: depois de falar de uma janela,
        # "outra tela", "para outra tela" ou "pra outra agora" significa
        # mover o alvo verificado. Sem contexto, não chutamos uma janela.
        if is_other_monitor_fragment(cleaned):
            if last_app:
                return _make_route("local", [f"v8:move_other:{last_app}"], "MOVE_OTHER")
            return _make_route("local", ["v8:clarify_app"], "CLARIFY")

        if re.match(r"^(?:agora\s+)?(?:descreve|descreva|analisa|analise)\b.*\b(?:nele|nesse|neste)\b", key):
            if last_monitor:
                return _make_route("local", [f"descreve monitor {last_monitor}"], "VISION_CONTEXT")
            return _make_route("local", ["v8:clarify_monitor"], "CLARIFY")

        # Ação elíptica sem alvo: guarda somente o slot que falta.
        if re.fullmatch(r"(?:agora\s+)?(?:fecha|feche|fechar)(?:\s+agora)?", key):
            if last_app:
                return _make_route("local", [f"fecha {last_app}"], "CLOSE_APP_CONTEXT")
            if self.context is not None:
                self.context.set_pending("action_target", "close", ttl=35.0)
            return _make_route("local", ["v8:clarify_app"], "CLARIFY_APP")
        if re.fullmatch(r"(?:agora\s+)?(?:abre|abra|abrir)(?:\s+agora)?", key):
            if self.context is not None:
                self.context.set_pending("action_target", "open", ttl=35.0)
            return _make_route("local", ["v8:clarify_app"], "CLARIFY_APP")

        # 13.12.1: verbo de busca sem objeto real e cheio de fillers e um
        # follow-up conversacional, nao uma acao local. Ex.: "busca ai pra mim"
        # depois de "quer que eu busque rotinas?". Antes isso virava o comando
        # legado literal "Busca" e falhava no executor.
        vague_search_key = _norm(cleaned)
        if re.fullmatch(
            r"(?:busca|busque|buscar|pesquisa|pesquise|pesquisar|procura|procure|procurar)"
            r"(?:\s+(?:ai|aqui|la|isso|isto|aquilo|algo|pra|para|mim|por|favor|entao|agora))*",
            vague_search_key,
            flags=re.I,
        ):
            return V8Route("conversation", [], intent="CONTEXT_FOLLOWUP")

        # 4) Variações naturais de criação. O parser recebe uma forma canônica curta.
        action_candidate = normalize_action_utterance(cleaned)
        action_candidate = re.sub(
            r"^(?:(?:mano|cara|velho)\s+)?(?:(?:eu\s+)?(?:quero|queria)(?:\s+que)?\s+(?:voc[eê]\s+)?|(?:eu\s+)?preciso\s+que\s+(?:voc[eê]\s+)?|pode\s+(?:me\s+)?|consegue\s+(?:me\s+)?)",
            "",
            action_candidate,
            flags=re.I,
        ).strip()
        if re.match(r"^(?:faz|faça|fazer)\b", action_candidate, flags=re.I) and re.search(
            r"\b(?:pasta|arquivo|texto|documento|nota|lembrete|atalho|rotina|lista|planilha|imagem|captura|projeto)\b",
            _norm(action_candidate),
        ):
            action_candidate = re.sub(r"^(?:faz|faça|fazer)\b", "cria", action_candidate, flags=re.I).strip()

        temporal_plan = bool(re.search(r"\b(?:mas\s+antes|mas\s+primeiro|e\s+depois|em\s+seguida)\b", _norm(action_candidate))) or bool(
            re.match(r"^(?:antes de|depois de|primeiro)\b", _norm(action_candidate))
        )
        if ACTION_RE.match(_norm(action_candidate)) or temporal_plan:
            commands, steps = _split_plan(action_candidate, last_app=last_app)
            if self.context is not None:
                for cmd in commands:
                    if cmd.startswith("v8:clarify_move:"):
                        self.context.set_pending("move_monitor", cmd.split(":", 2)[2].strip(), ttl=45.0)
                    elif cmd.startswith("v8:browser_search:") and cmd.endswith("|"):
                        payload = cmd.split(":", 2)[2]
                        browser = payload.partition("|")[0].strip() or "Opera"
                        self.context.set_pending("browser_search", browser, ttl=45.0)
            # Nao grava app no contexto aqui: parsing nao prova que a abertura
            # funcionou. A GUI chama mark_app_success apenas apos verificacao.
            intent = "MULTI_ACTION" if len(commands) > 1 else (steps[0].action if steps else "LOCAL_ACTION")
            return V8Route("local", commands, intent=intent, steps=steps)

        # 5) Sem verbo de ação claro, conversa. App Resolver nunca recebe frase comum.
        return V8Route("conversation", [], intent="CONVERSATION")


def _make_route(kind: str, commands: List[str], intent: str) -> V8Route:
    steps = [_step_from_command(cmd) for cmd in commands]
    return V8Route(kind, commands, intent=intent, steps=steps)


def _clean_target(text: str) -> str:
    text = " ".join(str(text or "").split()).strip(" ,;.!?")
    text = re.sub(r"^(?:o|a|os|as)\s+", "", text, flags=re.I)
    text = re.sub(r"^janela\s+", "", text, flags=re.I)
    # Nunca deixe local de destino ou cortesia virar parte do nome/alvo.
    text = re.sub(
        r"\s+(?:na|no)\s+(?:[áa]rea\s+de\s+trabalho|desktop)$",
        "", text, flags=re.I,
    ).strip(" ,")
    for _ in range(4):
        old = text
        text = re.sub(
            r"\s+(?:por favor|pra mim|para mim|a[ií]|cara|mano|agora)$",
            "", text, flags=re.I,
        ).strip(" ,")
        if text == old:
            break
    return text


def _monitor_number(text: str) -> Optional[int]:
    key = _norm(text)
    m = re.search(r"\b(?:monitor|monito|tela|display)\s*(\d+)\b", key)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(primeiro|segundo|terceiro|quarto|primeira|segunda|terceira|quarta)\s+(?:monitor|monito|tela|display)\b", key)
    if m:
        return {
            "primeiro": 1, "primeira": 1,
            "segundo": 2, "segunda": 2,
            "terceiro": 3, "terceira": 3,
            "quarto": 4, "quarta": 4,
        }.get(m.group(1))
    m = re.search(r"\b(?:monitor|monito|tela|display)\s+(um|dois|tres|quatro)\b", key)
    if m:
        return {"um": 1, "dois": 2, "tres": 3, "quatro": 4}.get(m.group(1))
    return None


def _canonical_single(text: str, last_target: Optional[str] = None) -> tuple[str, bool]:
    """Retorna comando canônico e se ele usou referência ao passo anterior."""
    raw = normalize_action_utterance(_strip_social(text))
    raw = re.sub(
        r"^(?:(?:eu\s+)?(?:quero|queria)(?:\s+que)?\s+(?:voc[eê]\s+)?|(?:eu\s+)?preciso\s+que\s+(?:voc[eê]\s+)?)",
        "", raw, flags=re.I
    ).strip()
    if re.match(r"^(?:faz|faça|fazer)\b", raw, flags=re.I) and re.search(
        r"\b(?:pasta|arquivo|texto|documento|nota|lembrete|atalho|rotina|lista|planilha|imagem|captura|projeto)\b",
        _norm(raw),
    ):
        raw = re.sub(r"^(?:faz|faça|fazer)\b", "cria", raw, flags=re.I).strip()
    key = _norm(raw)

    # Volume: combina verbo + entidade + valor, tolerando transcricoes como
    # "abaixo ao volume para 50" sem contaminar o verbo "passa" de janelas.
    vm = re.match(r"^(?:abaixa|abaixe|abaixar|baixo|abaixo|reduz|reduza|reduzir|diminui|diminua)\s+(?:o|ao)?\s*(?:volume|som)\s+(?:para|pra|em|a)\s*(\d{1,3})$", key)
    if vm:
        raw = f"volume em {vm.group(1)}"
        key = _norm(raw)

    # Referencia explicita de retorno para uma tela nao e UNDO generico: e um
    # movimento de janela com alvo e destino informados.
    back_move = re.match(r"^(?:volta|volte|retorna|retorne)\s+(?:(?:ao|aos|o|a)\s+)?(.+?)\s+(?:para|pra|na|no)\s+(?:a|o)?\s*(?:(?:tela|monitor)\s*(\d+)|(primeira|segunda|terceira|quarta)\s+(?:tela|monitor))$", raw, re.I)
    if back_move:
        monitor_value = back_move.group(2) or {"primeira": "1", "segunda": "2", "terceira": "3", "quarta": "4"}.get(_norm(back_move.group(3)), "")
        raw = f"move {_clean_target(back_move.group(1))} para monitor {monitor_value}"
        key = _norm(raw)

    # Significados de janela: a linguagem pode expressar estado sem usar o
    # verbo tecnico "maximizar/minimizar/restaurar". Convertemos a estrutura
    # semantica para a forma canonica antes de resolver o alvo.
    m = re.match(r"^(?:deixa|deixe|deixar)\s+(.+?)\s+(?:grande|maximizad[oa]|em tela cheia)$", raw, re.I)
    if m:
        raw = f"maximiza {_clean_target(m.group(1))}"
    else:
        m = re.match(r"^(?:esconde|esconda|esconder|encolhe|encolher|recolhe|recolher)\s+(.+)$", raw, re.I)
        if m:
            raw = f"minimiza {_clean_target(m.group(1))}"
        else:
            m = re.match(r"^(?:tira|tire|tirar)\s+(.+?)\s+da frente$", raw, re.I)
            if m:
                raw = f"minimiza {_clean_target(m.group(1))}"
            else:
                m = re.match(r"^(?:traz|traga|trazer|mostra|mostre|mostrar)\s+(.+?)\s+(?:de volta|de novo)$", raw, re.I)
                if m:
                    raw = f"restaura {_clean_target(m.group(1))}"
    if _norm(raw) in {"deixa grande", "deixe grande", "deixa em tela cheia", "deixe em tela cheia"}:
        raw = f"maximiza {last_target}" if last_target else "v8:clarify_app"
    elif _norm(raw) in {"esconde", "esconda", "esconde agora"}:
        raw = f"minimiza {last_target}" if last_target else "v8:clarify_app"
    elif _norm(raw) in {"traz de volta", "traga de volta", "traz de novo"}:
        raw = f"restaura {last_target}" if last_target else "v8:clarify_app"
    key = _norm(raw)

    # Verbos naturais equivalentes de mover janela.
    raw = re.sub(r"^(?:manda|mandar|envia|envie|enviar|passa|passe|passar)\b", "move", raw, flags=re.I).strip()
    key = _norm(raw)

    # Arquivos/pastas. Preserva somente o nome, não a frase inteira.
    # Destinos conhecidos são entidades separadas do nome da pasta.
    prefix_desktop = re.match(
        r"^(?:cria|crie|criar)\s+(?:uma\s+)?pasta\s+(?:no|na)\s+(?:desktop|[áa]rea\s+de\s+trabalho)\s+(.+)$",
        raw, re.I,
    )
    if prefix_desktop:
        name = re.sub(r"^(?:(?:chamada|chamado|nomeada|nomeado)\s+|(?:com\s+nome\s+de|de\s+nome)\s+)", "", _clean_target(prefix_desktop.group(1)), flags=re.I)
        return f"crie pasta no desktop {name}", False
    m = re.match(
        r"^(?:cria|crie|criar)\s+(?:uma\s+)?pasta(?:\s+(?:chamada|chamado|nomeada|nomeado)|\s+com\s+nome\s+de|\s+de\s+nome)?\s+(.+?)\s+"
        r"(?:em|no|na|nos|nas)\s+(downloads?|documentos?|documents?|imagens?|pictures?)$",
        raw,
        re.I,
    )
    if m:
        name = _clean_target(m.group(1))
        dest_key = _norm(m.group(2))
        destination = (
            "downloads" if dest_key.startswith("download")
            else "documents" if dest_key.startswith(("document", "documento"))
            else "pictures"
        )
        return f"v8:create_folder:{destination}|{name}", False

    m = re.match(
        r"^(?:cria|crie|criar)\s+(?:uma\s+)?pasta\s+"
        r"(?:chamada|chamado)\s+(.+?)(?:\s+(?:na|no)\s+(?:[áa]rea\s+de\s+trabalho|desktop))?$",
        raw,
        re.I,
    )
    if m:
        return f"crie pasta no desktop {_clean_target(m.group(1))}", False

    m = re.match(
        r"^(?:cria|crie|criar)\s+(?:uma\s+)?pasta\s+(.+?)\s+"
        r"(?:na|no)\s+(?:[áa]rea\s+de\s+trabalho|desktop)$",
        raw,
        re.I,
    )
    if m:
        name = re.sub(r"^(?:(?:chamada|chamado|nomeada|nomeado)\s+|(?:com\s+nome\s+de|de\s+nome)\s+)", "", _clean_target(m.group(1)), flags=re.I)
        return f"crie pasta no desktop {name}", False

    # Sem destino explícito, criação de pasta simples usa o Desktop. Isso evita
    # criar caminhos relativos ao CWD do JARVIS (ex.: C:\JARVIS\arcanjo).
    m = re.match(r"^(?:cria|crie|criar)\s+(?:uma\s+)?pasta\s+(.+)$", raw, re.I)
    if m:
        name = re.sub(r"^(?:(?:chamada|chamado|nomeada|nomeado)\s+|(?:com\s+nome\s+de|de\s+nome)\s+)", "", _clean_target(m.group(1)), flags=re.I)
        if name:
            return f"crie pasta no desktop {name}", False

    m = re.match(
        r"^(?:cria|crie|criar)\s+(?:um\s+)?arquivo(?:\s+de\s+texto)?"
        r"(?:\s+(?:chamado|chamada))?\s+(.+?)(?:\s+(?:na|no)\s+(?:[áa]rea\s+de\s+trabalho|desktop))?$",
        raw,
        re.I,
    )
    if m:
        return f"v8:create_text:{_clean_target(m.group(1))}", False

    # Pesquisa real no navegador. A consulta e livre: nao depende de lista de
    # sites, API de busca nem Gemini. Aceita tanto "pesquisa X no Opera" quanto
    # "pesquisa no Opera X" e infinitivos naturais usados por texto/STT.
    search_verbs = r"(?:pesquisa|pesquise|pesquisar|pesquisando|procura|procure|procurar|procurando|busca|busque|buscar|buscando)"
    browser_expr = r"(?:[óo]pera(?:\s+gx)?|opero(?:\s+gx)?|meu\s+navegador|navegador)"
    search_query = ""
    search_match = re.match(
        rf"^{search_verbs}\s+(.+?)\s+(?:no|na)\s+{browser_expr}$",
        raw,
        re.I,
    )
    if search_match:
        search_query = search_match.group(1).strip()
    else:
        search_match = re.match(
            rf"^{search_verbs}\s+(?:no|na)\s+{browser_expr}(?:\s+(?:por|sobre))?\s+(.+)$",
            raw,
            re.I,
        )
        if search_match:
            search_query = search_match.group(1).strip()
    if not search_query:
        spoken_search = re.match(rf"^{search_verbs}\s+(?:o\s+)?{browser_expr}\s+(.+)$", raw, re.I)
        if spoken_search:
            search_query = spoken_search.group(1).strip()
    if search_query:
        search_query = _clean_spoken_search_query(search_query)
        search_query = re.sub(r"^(?:oq|oque)\b", "o que", search_query, flags=re.I).strip()
        return f"v8:browser_search:Opera|{search_query}", False
    if re.match(rf"^{search_verbs}\s+(?:no|na)\s+{browser_expr}\s*$", raw, re.I):
        return "v8:browser_search:Opera|", False

    if re.match(r"^(?:abre|abra|abrir)\s+(?:o\s+)?meu\s+navegador$", key):
        return "abre Opera", False

    # Crunchyroll deve abrir diretamente no Opera quando o usuario pedir o site
    # explicitamente. Esse caminho vem antes do parser generico de site/app para
    # evitar que "abre Crunchyroll no Opera" vire conversa ou nome de app.
    crunchy_open = re.match(
        r"^(?:abre|abra|abrir|entra|entre|entrar|vai|acesse|acessar)\s+"
        r"(?:(?:o|no|na|pro|pra|para o)\s+)?crunchy\s*roll"
        r"(?:\.com)?(?:\s+(?:no|na|pelo|pelo navegador|no navegador)\s+opera(?:\s+gx)?)?\s*$",
        key, re.I,
    )
    if crunchy_open:
        return "v8:open_site_in_app:Opera|crunchyroll.com", False

    # Acoes de janela sem alvo reutilizam exclusivamente o ultimo alvo
    # verificado. Nunca caem na janela ativa (que normalmente e o proprio JARVIS
    # quando o usuario digitou o comando).
    targetless_window = re.match(
        r"^(minimiza|minimize|minimizar|maximiza|maximize|maximizar|expande|expanda|expandir|"
        r"restaura|restaure|restaurar)(?:\s+agora)?$",
        raw,
        flags=re.I,
    )
    if targetless_window:
        if not last_target:
            return "v8:clarify_app", False
        return f"{targetless_window.group(1)} {last_target}", True

    site_match = re.match(
        r"^(?:abre|abra|abrir|entra|entre|entrar|vai|acesse|acessar)\s+"
        r"(?:(?:no|na|pro|pra|para o|para a|o|a)\s+)?(.+?)$",
        key,
    )
    if site_match:
        site_key = site_match.group(1).strip()
        address = SITE_ALIASES.get(site_key)
        if address:
            if last_target and any(browser in _norm(last_target) for browser in ("opera", "chrome", "edge", "firefox", "brave")):
                return f"v8:open_site_in_app:{last_target}|{address}", True
            return f"abra o site {address}", False
        # Destino inedito dentro de um navegador confirmado: em vez de tratar
        # como nome de aplicativo ou exigir cadastro, faz uma busca real.
        if (
            last_target
            and re.match(r"^(?:entra|entre|entrar|vai|acesse|acessar)\b", key)
            and any(browser in _norm(last_target) for browser in ("opera", "chrome", "edge", "firefox", "brave"))
        ):
            return f"v8:browser_search:{last_target}|{site_key}", True

        # Se não era um alias de site nem um destino dentro de navegador já
        # confirmado, "entra no Opera/OBS/..." é linguagem natural para abrir
        # um aplicativo. O App Resolver continua sendo quem valida o alvo.
        if re.match(r"^(?:entra|entre|entrar)\b", key) and not re.search(r"[./:]", site_key):
            return f"abre {_clean_target(site_key)}", False

    # "outro monitor/outra tela" nao precisa conhecer a numeracao: a
    # ferramenta descobre em qual monitor a janela esta e escolhe outro real.
    other_move = re.match(
        r"^(?:mova|move|mover|coloca|coloque|joga|jogue|leva|leve)\s+(.+?)\s+"
        r"(?:pro|para|pra|no|na)\s+(?:o\s+|a\s+)?(?:outro\s+monitor|outra\s+tela|outro\s+display)\s*$",
        raw,
        flags=re.I,
    )
    if other_move:
        other_target = _clean_target(other_move.group(1))
        if _norm(other_target) in {"ele", "ela", "isso", "essa janela", "esta janela"}:
            if not last_target:
                return "v8:clarify_app", False
            return f"v8:move_other:{last_target}", True
        return f"v8:move_other:{other_target}", False
    missing_other = re.match(
        r"^(?:mova|move|mover|coloca|coloque|joga|jogue|leva|leve)\s+"
        r"(?:(?:pro|para|pra|no|na)\s+)?(?:o\s+|a\s+)?(?:outro\s+monitor|outra\s+tela|outro\s+display)\s*$",
        raw,
        flags=re.I,
    )
    if missing_other:
        return (f"v8:move_other:{last_target}", True) if last_target else ("v8:clarify_app", False)

    # "mover para tela 2" / "passa pra segunda tela" usa o ultimo app
    # confirmado; sem contexto, pergunta em vez de mover a janela ativa.
    mon_missing_target = _monitor_number(raw)
    if mon_missing_target:
        missing_numbered = re.match(
            r"^(?:mova|move|mover|coloca|coloque|joga|jogue|leva|leve)\s+"
            r"(?:(?:pro|para|pra|no|na)\s+)?(?:o\s+|a\s+)?(?:"
            r"(?:monitor|tela|display)\s*(?:\d+|um|dois|tres|quatro)|"
            r"(?:primeiro|segundo|terceiro|quarto|primeira|segunda|terceira|quarta)\s+(?:monitor|tela|display))\s*$",
            raw,
            flags=re.I,
        )
        if missing_numbered:
            return (f"move {last_target} para monitor {mon_missing_target}", True) if last_target else ("v8:clarify_app", False)

    used_reference = False
    reference_action = bool(
        WINDOW_VERB_RE.match(key)
        or re.match(r"^(?:abre|abra|abrir|fecha|feche|fechar)\b", key)
    )
    has_reference = bool(re.search(r"\b(?:ele|ela|isso|essa janela|esta janela)\b", raw, flags=re.I))
    if reference_action and has_reference:
        if not last_target:
            # Sem um app confirmado, jamais deixe o legado interpretar "ele"
            # como janela ativa ou escolher um alvo implícito.
            return "v8:clarify_app", False
        before = raw
        raw = re.sub(r"\b(?:ele|ela|isso|essa janela|esta janela)\b", last_target, raw, flags=re.I)
        used_reference = raw != before

    # Normaliza monitor ordinal/número para um único formato.
    mon = _monitor_number(raw)
    if mon and WINDOW_VERB_RE.match(_norm(raw)):
        m = re.match(
            r"^(coloca|coloque|mova|move|mover|joga|jogue|leva|leve)\s+(.+?)\s+"
            r"(?:pro|para|pra|no|na)\s+(?:o\s+|a\s+)?(?:"
            r"(?:monitor|tela|display)\s*\d+|"
            r"(?:primeiro|segundo|terceiro|quarto|primeira|segunda|terceira|quarta)\s+(?:monitor|tela|display))\s*$",
            raw,
            flags=re.I,
        )
        if m:
            raw = f"{m.group(1)} {_clean_target(m.group(2))} para monitor {mon}"

    # Fillers depois do verbo.
    raw = re.sub(r"^(abre|abra|abrir)\s+a[ií]\s+", r"\1 ", raw, flags=re.I)
    raw = re.sub(
        r"^(abre|abra|abrir|fecha|feche|fechar|minimiza|minimize|maximiza|maximize|expande|expanda)\s+(?:o|a)\s+",
        r"\1 ",
        raw,
        flags=re.I,
    )
    # Limpa fillers restantes do alvo sem alterar o verbo.
    m = re.match(
        r"^(abre|abra|abrir|fecha|feche|fechar|minimiza|minimize|minimizar|"
        r"maximiza|maximize|maximizar|expande|expanda|expandir)\s+(.+)$",
        raw, flags=re.I,
    )
    if m:
        verb = m.group(1)
        target = _clean_target(m.group(2))
        if _norm(verb) in {"fecha", "feche", "fechar"}:
            target = normalize_close_target(target)
        raw = f"{verb} {target}"

    # "move" sozinho também é um pedido incompleto, não conversa. Se existe
    # alvo verificado, só falta o destino; sem alvo, pedimos o aplicativo.
    if _norm(raw) in {"move", "mova", "mover"}:
        if last_target:
            return f"v8:clarify_move:{last_target}", True
        return "v8:clarify_app", False

    # "move Opera" is incomplete but meaningful. Keep the target and ask only
    # for the missing destination instead of falling through to Gemini/legacy.
    move_only = re.match(r"^(?:mova|move|mover)\s+(.+?)$", raw, flags=re.I)
    if move_only and not re.search(r"\b(?:monitor|tela|display|outra|outro)\b", _norm(raw)):
        target = _clean_target(move_only.group(1))
        if _norm(target) in {"ele", "ela", "isso", "essa janela", "esta janela"} and last_target:
            target = last_target
            used_reference = True
        return f"v8:clarify_move:{target}", used_reference

    return raw.strip(" ,.!?"), used_reference


def _extract_target(command: str) -> Optional[str]:
    m = re.match(r"^(?:abre|abra|abrir)\s+(?:o\s+|a\s+)?(.+)$", command, flags=re.I)
    if not m:
        return None
    target = _clean_target(m.group(1))
    if target.lower().startswith("site ") or "youtube.com" in target.lower():
        return None
    return target or None


def _step_from_command(command: str, depends_on: Optional[int] = None, require_success: bool = False) -> V8PlanStep:
    key = _norm(command)
    target = None
    action = "LEGACY"
    if command.startswith("v8:"):
        action = command.split(":", 2)[1].upper()
        if action == "OPEN_SITE_IN_APP":
            try:
                target = command.split(":", 2)[2].split("|", 1)[0].strip() or None
            except Exception:
                target = None
        elif action == "BROWSER_SEARCH":
            try:
                target = command.split(":", 2)[2].split("|", 1)[0].strip() or None
            except Exception:
                target = None
        elif action == "MOVE_OTHER":
            try:
                target = command.split(":", 2)[2].strip() or None
            except Exception:
                target = None
    elif re.match(r"^(?:abre|abra|abrir)\b", key):
        action = "OPEN_APP"
        target = _extract_target(command)
        if "site " in key or ".com" in key:
            action = "OPEN_SITE"
    elif re.match(r"^(?:fecha|feche|fechar)\b", key):
        action = "CLOSE_APP"
    elif re.match(r"^(?:minimiza|minimize|minimizar)\b", key):
        action = "MINIMIZE_WINDOW"
        m = re.match(r"^(?:minimiza|minimize|minimizar)\s+(.+)$", command, flags=re.I)
        target = _clean_target(m.group(1)) if m else None
    elif re.match(r"^(?:maximiza|maximize|maximizar|expande|expanda|expandir)\b", key):
        action = "MAXIMIZE_WINDOW"
        m = re.match(r"^(?:maximiza|maximize|maximizar|expande|expanda|expandir)\s+(.+)$", command, flags=re.I)
        target = _clean_target(m.group(1)) if m else None
    elif re.match(r"^(?:restaura|restaure|restaurar)\b", key):
        action = "RESTORE_WINDOW"
        m = re.match(r"^(?:restaura|restaure|restaurar)\s+(.+)$", command, flags=re.I)
        target = _clean_target(m.group(1)) if m else None
    elif re.match(r"^(?:mova|move|mover|coloca|coloque|joga|jogue|leva|leve)\b", key):
        action = "MOVE_WINDOW"
        m = re.match(r"^(?:mova|move|mover|coloca|coloque|joga|jogue|leva|leve)\s+(.+?)\s+para\s+monitor\s+\d+\s*$", command, flags=re.I)
        target = _clean_target(m.group(1)) if m else None
    elif command.lower().startswith("crie pasta"):
        action = "CREATE_FOLDER"
    elif key.startswith("descreve"):
        action = "VISION"
    return V8PlanStep(command, action=action, target=target, depends_on=depends_on, require_success=require_success)


def _split_plan(text: str, last_app: Optional[str] = None) -> tuple[List[str], List[V8PlanStep]]:
    raw = _strip_social(text)

    # Um único verbo pode governar dois apps com o mesmo destino:
    # "abre OBS e o Opera no monitor 2". Sem este caso, o App Resolver recebe
    # incorretamente "OBS e o Opera" como se fosse um único nome.
    shared_monitor = re.match(
        r"^(?:abre|abra|abrir)\s+(?:o\s+|a\s+)?(.+?)\s+e\s+(?:o\s+|a\s+)?(.+?)\s+"
        r"(?:no|na|pro|pra|para)\s+(?:o\s+|a\s+)?(?:monitor|monito|tela|display)\s*"
        r"(\d+|um|dois|tres|quatro)\s*$",
        raw,
        flags=re.I,
    )
    if shared_monitor:
        first_target = _clean_target(shared_monitor.group(1))
        second_target = _clean_target(shared_monitor.group(2))
        mon = _monitor_number(f"monitor {shared_monitor.group(3)}")
        if first_target and second_target and mon:
            out: List[str] = []
            steps: List[V8PlanStep] = []
            for target in (first_target, second_target):
                open_cmd = f"abre {target}"
                out.append(open_cmd)
                steps.append(_step_from_command(open_cmd))
                open_index = len(steps) - 1
                move_cmd = f"move {target} para monitor {mon}"
                out.append(move_cmd)
                steps.append(_step_from_command(move_cmd, depends_on=open_index, require_success=True))
            return out, steps

    # Planner temporal geral. Marcadores de ordem viram dependencias de plano,
    # independentemente da acao concreta (app, arquivo, pesquisa, navegador...).
    action_head = (
        r"(?:abre|abra|abrir|fecha|feche|fechar|minimiza|minimize|minimizar|maximiza|maximize|maximizar|"
        r"expande|expanda|expandir|restaura|restaure|restaurar|mova|move|mover|coloca|coloque|joga|jogue|"
        r"leva|leve|manda|mandar|passa|passe|passar|cria|crie|criar|faz|faca|fazer|entra|entre|entrar|vai|acesse|"
        r"acessar|pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar|deixa|deixe|deixar|esconde|esconda|esconder|traz|traga|trazer)"
    )
    before = re.match(
        r"^(.+?)\s*,?\s*mas\s+antes\s+de\s+(?:fazer\s+)?(?:isso|isto)\s+(.+)$",
        raw, flags=re.I,
    )
    if before:
        raw = f"{before.group(2).strip()} e depois {before.group(1).strip()}"
    else:
        before = re.match(r"^(.+?)\s*,?\s*mas\s+primeiro\s+(.+)$", raw, flags=re.I)
        if before:
            raw = f"{before.group(2).strip()} e depois {before.group(1).strip()}"
        else:
            before = re.match(rf"^(.+?)\s*,?\s*mas\s+antes\s+({action_head}\b.+)$", raw, flags=re.I)
            if before:
                raw = f"{before.group(2).strip()} e depois {before.group(1).strip()}"
            else:
                direct = re.match(rf"^antes\s+de\s+(.+?)\s*,\s*({action_head}\b.+)$", raw, flags=re.I)
                if not direct:
                    # A fala raramente inclui uma pausa/coma: "antes de abrir Opera cria pasta X".
                    # Procura uma segunda cabeca de acao e usa a primeira clausula como dependencia.
                    direct = re.match(rf"^antes\s+de\s+(.+?)\s+({action_head}\b.+)$", raw, flags=re.I)
                if direct:
                    raw = f"{direct.group(2).strip()} e depois {direct.group(1).strip()}"
                else:
                    after = re.match(rf"^depois\s+de\s+(.+?)\s*,\s*({action_head}\b.+)$", raw, flags=re.I)
                    if not after:
                        after = re.match(rf"^depois\s+de\s+(.+?)\s+({action_head}\b.+)$", raw, flags=re.I)
                    if after:
                        raw = f"{after.group(1).strip()} e depois {after.group(2).strip()}"
                    else:
                        # Tambem entende "abre Opera depois de criar pasta X" e
                        # "cria pasta X antes de abrir Opera".
                        suffix_after = re.match(rf"^(.+?)\s+depois\s+de\s+({action_head}\b.+)$", raw, flags=re.I)
                        suffix_before = re.match(rf"^(.+?)\s+antes\s+de\s+({action_head}\b.+)$", raw, flags=re.I)
                        if suffix_after:
                            raw = f"{suffix_after.group(2).strip()} e depois {suffix_after.group(1).strip()}"
                        elif suffix_before:
                            raw = f"{suffix_before.group(1).strip()} e depois {suffix_before.group(2).strip()}"
                        else:
                            raw = re.sub(r"^primeiro\s+", "", raw, flags=re.I)
    raw = re.sub(
        r"[,;]\s*(?=(?:abre|abra|fecha|feche|minimiza|minimize|maximiza|maximize|expande|expanda|"
        r"mova|move|coloca|coloque|cria|crie|faz|faça|entra|entre|entrar|vai|pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar)\b)",
        " e depois ",
        raw,
        flags=re.I,
    )
    raw = re.sub(
        r"\s+e\s+(?=(?:abre|abra|fecha|feche|minimiza|minimize|maximiza|maximize|expande|expanda|"
        r"mova|move|coloca|coloque|cria|crie|faz|faça|entra|entre|entrar|vai|pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar)\b)",
        " e depois ",
        raw,
        flags=re.I,
    )
    segments = [
        x.strip(" ,;")
        for x in re.split(r"\s+(?:e\s+depois|depois|em\s+seguida|e\s+entao)\s+", raw, flags=re.I)
        if x.strip(" ,;")
    ]

    out: List[str] = []
    steps: List[V8PlanStep] = []
    last_target: Optional[str] = last_app
    last_open_index: Optional[int] = None

    for seg in segments:
        # Fala natural sem conjunção: "abre Opera coloca(r) na tela 2".
        # A entidade entre OPEN e MOVE é separada antes de chegar ao App Resolver.
        fused = re.match(
            r"^(abre|abra|abrir)\s+(?:o\s+|a\s+)?(.+?)\s+"
            r"(?:e\s+)?(?:coloca|coloque|colocar|move|mova|mover|manda|mande|mandar|passa|passe|passar)\s+"
            r"(?:(?:ele|ela)\s+)?(?:(?:na|no|para|pra|pro)\s+)?(?:o\s+|a\s+)?"
            r"(?:monitor|tela|display)\s*(\d+|um|dois|tres|quatro)\s*$",
            seg, flags=re.I,
        )
        if fused:
            target = _clean_target(fused.group(2))
            mon = _monitor_number(f"tela {fused.group(3)}")
            if mon:
                open_cmd, _ = _canonical_single(f"{fused.group(1)} {target}", last_target)
                out.append(open_cmd)
                steps.append(_step_from_command(open_cmd))
                open_index = len(steps) - 1
                new_target = _extract_target(open_cmd) or target
                move_cmd = f"move {new_target} para monitor {mon}"
                out.append(move_cmd)
                steps.append(_step_from_command(move_cmd, depends_on=open_index, require_success=True))
                last_target = new_target
                last_open_index = open_index
                continue

        # "abre Opera na tela 2" = OPEN Opera -> MOVE Opera monitor 2.
        # O MOVE depende de uma abertura confirmada e nunca recebe "opera na tela 2".
        mon = _monitor_number(seg)
        if mon:
            open_mon = re.match(
                r"^(abre|abra|abrir)\s+(?:o\s+|a\s+)?(.+?)\s+"
                r"(?:na|no|pro|pra|para)\s+(?:o\s+|a\s+)?(?:"
                r"(?:monitor|tela|display)\s*(?:\d+|um|dois|tres|quatro)|"
                r"(?:primeiro|segundo|terceiro|quarto|primeira|segunda|terceira|quarta)\s+(?:monitor|tela|display))\s*$",
                seg,
                flags=re.I,
            )
            if open_mon:
                target = _clean_target(open_mon.group(2))
                open_cmd, _ = _canonical_single(f"{open_mon.group(1)} {target}", last_target)
                open_step = _step_from_command(open_cmd)
                out.append(open_cmd)
                steps.append(open_step)
                open_index = len(steps) - 1
                new_target = _extract_target(open_cmd) or target
                move_cmd = f"move {new_target} para monitor {mon}"
                out.append(move_cmd)
                steps.append(_step_from_command(move_cmd, depends_on=open_index, require_success=True))
                last_target = new_target
                last_open_index = open_index
                continue

        m = re.match(r"^(abre|abra|abrir|fecha|feche|fechar)\s+(.+)$", seg, flags=re.I)
        if m and (" e " in m.group(2).lower() or "," in m.group(2) or ";" in m.group(2)):
            verb, tail = m.group(1), m.group(2)
            items = [x for x in re.split(r"\s*[,;]\s*|\s+e\s+", tail, flags=re.I) if x.strip()]
            if 2 <= len(items) <= 6 and all(not ACTION_RE.match(_norm(x)) for x in items[1:]):
                for item in items:
                    cmd, used_ref = _canonical_single(f"{verb} {_clean_target(item)}", last_target)
                    step = _step_from_command(cmd)
                    out.append(cmd)
                    steps.append(step)
                    new_target = _extract_target(cmd)
                    if new_target:
                        last_target = new_target
                        last_open_index = len(steps) - 1
                continue

        cmd, used_ref = _canonical_single(seg, last_target)
        dep = last_open_index if used_ref else None
        step = _step_from_command(cmd, depends_on=dep, require_success=bool(used_ref and dep is not None))
        out.append(cmd)
        steps.append(step)
        new_target = _extract_target(cmd)
        if new_target:
            last_target = new_target
            last_open_index = len(steps) - 1

    return [x for x in out if x], [s for s in steps if s.command]


_ROUTER = V8Router()


def route(text: str) -> Optional[V8Route]:
    return _ROUTER.route(text)


def reset_context() -> None:
    _ROUTER.reset_context()


def mark_app_success(app: Optional[str]) -> None:
    _ROUTER.mark_app_success(app)


def mark_action_success(action: str, target: str = "", before=None, after=None) -> None:
    _ROUTER.mark_action_success(action, target, before=before or {}, after=after or {})


def mark_feedback(text: str) -> None:
    _ROUTER.mark_feedback(text)


def observe_context(app: str = "", monitor: Optional[int] = None, site: str = "", title: str = "") -> None:
    _ROUTER.observe_context(app=app, monitor=monitor, site=site, title=title)


def remember_topic(topic: str) -> None:
    _ROUTER.remember_topic(topic)


def remember_media(media) -> None:
    _ROUTER.remember_media(media)


def context_status() -> dict:
    if getattr(_ROUTER, "context", None) is None:
        return {}
    return _ROUTER.context.status()


__all__ = [
    "V8Route", "V8PlanStep", "V8Router", "route", "reset_context",
    "mark_app_success", "mark_action_success", "mark_feedback", "observe_context",
    "remember_topic", "remember_media", "context_status",
]
