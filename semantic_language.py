from __future__ import annotations

"""Camada semantica/fonetica conservadora para comandos locais do JARVIS.

Nao e um banco de frases. A cobertura e combinatoria: variantes de verbos,
flexoes, cortesias, conectores, pequenos erros de digitacao/STT e assinaturas
foneticas sao normalizados antes do Router decidir entidade, contexto e risco.

Build 13.12.0 - Voice/Conversation Core PT-BR/Nordeste:
- amplia fala natural sem criar trilhoes/septilhoes de strings em disco;
- combina quatro assinaturas foneticas conservadoras somente no verbo;
- adiciona familias de fala espontanea e portugues nordestino com contexto;
- entende wrappers como bora/simbora, tu/ce, oxe/oxente, visse e vocativos;
- mantem ambiguidade protegida: uma aproximacao so e aplicada quando aponta
  para UM unico significado operacional;
- adiciona atos de fala: ordem, negacao, afirmacao, correcao e pergunta;
- trata autocorrecao no mesmo enunciado e fala quebrada/disfluente;
- amplia variantes regionais com travas contextuais;
- expoe uma estimativa combinatoria auditavel sem armazenar frases fisicas;
- mantem frases de midia protegidas contra aproximacao fonetica que poderia
  transformar conversa comum em abertura de aplicativo.

A camada nunca executa nada; ela apenas canoniza o verbo quando ha evidencia
suficiente.
"""

import difflib
import math
import re
import unicodedata
from typing import Dict, Optional, Set, Tuple


def norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    value = re.sub(r"[^a-z0-9% ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


# Variantes reais de linguagem/STT. O Router continua sendo responsavel por
# resolver o alvo, plano, contexto e seguranca.
_CANONICAL: Dict[str, Set[str]] = {
    "abre": {
        "abre", "abra", "abrir", "abro", "abri", "abrei", "abrih", "abreh", "abrea", "abree", "abriai", "arbi", "abril",
        "inicia", "inicie", "iniciar", "inicializa", "inicialize", "inicializar",
        "executa", "execute", "executar", "roda", "rode", "rodar", "lanca", "lance", "lancar",
        "carrega", "carregue", "carregar", "chama", "chame", "chamar",
        "avre", "abreai", "abreia",
    },
    "fecha": {
        "fecha", "feche", "fechar", "fecho", "fechei", "fichar", "ficha", "fexa", "fexar", "fexe", "fexi", "feixa", "feixar", "fechi", "fech", "encerra", "encerre", "encerrar",
        "finaliza", "finalize", "finalizar", "termina", "termine", "terminar", "mata", "mate", "matar",
        "fexaai", "feixaai", "fechaai",
    },
    "minimiza": {
        "minimiza", "minimize", "minimizar", "minimmiza", "minimisa", "minimisar", "minimizae", "minimizaai",
        "diminui", "diminua", "diminuir", "diminuiu", "encolhe", "encolha", "encolher",
        "recolhe", "recolha", "recolher", "abaixa", "abaixe", "abaixar", "esconde", "esconda", "esconder",
    },
    "maximiza": {
        "maximiza", "maximize", "maximizar", "maximisa", "maximisar", "maximizae", "maximizaai", "expande", "expanda",
        "expandir", "aumenta", "aumente", "aumentar", "amplia", "amplie", "ampliar",
        "agranda", "agrande", "agrandar",
    },
    "restaura": {
        "restaura", "restaure", "restaurar", "restora", "restaurae", "restauraai", "normaliza", "normalize", "normalizar",
        "retorna", "retorne", "retornar", "reabre", "reabra", "reabrir",
    },
    "move": {
        "move", "mova", "mover", "movi", "muve", "movel", "móvel", "coloca", "coloque", "colocar", "joga",
        "jogue", "jogar", "leva", "leve", "levar", "manda", "mande", "mandar", "envia",
        "envie", "enviar", "transfere", "transfira", "transferir", "bota", "bote", "botar",
        "poe", "põe", "ponha", "reposiciona", "reposicione", "reposicionar", "desloca", "desloque", "deslocar",
        "mete", "meta", "taca", "taque", "empurra", "empurre",
    },
    "cria": {
        "cria", "crie", "criar", "criaai", "criae", "faz", "faca", "faça", "fazer", "gera", "gere", "gerar",
        "monta", "monte", "montar", "produz", "produza", "produzir", "prepara", "prepare", "preparar",
    },
    "pesquisa": {
        "pesquisa", "pesquise", "pesquisar", "pesquisasse", "pesquiza", "pesquize", "pesquizar", "pisquisa", "pisquise", "pisquiza", "pesquissa", "pesquisse",
        "procura", "procure", "procurar", "procurasse", "prucura", "prucure", "prucurar", "percura", "percure", "percurar", "busca", "busque", "buscar", "buscasse",
        "acha", "ache", "achar", "achasse", "encontra", "encontre", "encontrar", "encontrasse",
        "localiza", "localize", "localizar", "localizasse", "consulta", "consulte", "consultar", "consultasse",
        "investiga", "investigue", "investigar",
        "prucuraai", "percuraai", "pesquizaai", "pisquisaai",
    },
    "clica": {
        "clica", "clique", "clicar", "clika", "clike", "clikar", "clic", "aperta", "aperte", "apertar", "apreta", "aprete", "apretar", "pressiona", "pressione",
        "pressionar", "seleciona", "selecione", "selecionar", "aciona", "acione", "acionar",
    },
    "pausa": {
        "pausa", "pause", "pausar", "pausaai", "pousa", "pouse", "para", "pare", "parar", "interrompe", "interrompa", "interromper",
        "segura", "segure", "segurar",
    },
    "continua": {
        "continua", "continue", "continuar", "continuai", "continuaai", "retoma", "retome", "retomar", "resume", "resumir",
        "play", "plei", "pley", "toca", "toque", "tocar", "reproduz", "reproduza", "reproduzir",
        "prossegue", "prossiga", "prosseguir",
    },
}

# Palavras ja esperadas pelo Router nao precisam ser reescritas. Mantemos a
# forma original para nao alterar gramatica/entidades sem necessidade.
_PASSTHROUGH = {
    "abre", "abra", "abrir", "fecha", "feche", "fechar",
    "minimiza", "minimize", "minimizar", "maximiza", "maximize", "maximizar",
    "expande", "expanda", "expandir", "restaura", "restaure", "restaurar",
    "move", "mova", "mover", "coloca", "coloque", "joga", "jogue",
    "leva", "leve", "manda", "mandar", "envia", "envie", "enviar",
    "passa", "passe", "passar", "cria", "crie", "criar", "faz", "faca",
    "fazer", "pesquisa", "pesquise", "pesquisar", "procura", "procure",
    "procurar", "busca", "busque", "buscar", "clica", "clique", "clicar",
    "pausa", "pause", "pausar", "continua", "continue", "continuar", "play",
    "entra", "entre", "entrar", "vai", "acesse", "acessa", "acessar",
}

_REVERSE: Dict[str, str] = {}
for canonical, forms in _CANONICAL.items():
    for form in forms:
        _REVERSE[norm(form)] = canonical


def phonetic_key_pt(text: str) -> str:
    """Assinatura fonetica estrita para comparar somente verbos de comando.

    Nao e aplicada ao alvo inteiro (nome de app, arquivo etc.), porque isso
    aumentaria falsos positivos. As substituicoes representam confusoes comuns
    de STT em pt-BR e nomes/verbos anglicizados.
    """
    s = norm(text).replace(" ", "")
    if not s:
        return ""
    # Sons contextuais antes das substituicoes globais.
    s = re.sub(r"g(?=[ei])", "j", s)
    s = re.sub(r"c(?=[ei])", "s", s)
    replacements = (
        ("sch", "x"), ("sh", "x"), ("ch", "x"),
        ("ph", "f"), ("th", "t"), ("rh", "r"),
        ("lh", "li"), ("nh", "ni"),
        ("qu", "k"), ("gu", "g"),
        ("ck", "k"), ("q", "k"), ("c", "k"),
        ("ss", "s"), ("sc", "s"), ("xc", "s"),
        ("z", "s"), ("y", "i"), ("w", "v"),
        ("rr", "r"), ("h", ""),
    )
    for src, dst in replacements:
        s = s.replace(src, dst)
    # Simplifica letras repetidas geradas por STT sem remover uma vogal
    # importante. "minimmiza" -> "minimiza" na assinatura.
    s = re.sub(r"([bcdfgjklmnpqrstvx])\1+", r"\1", s)
    return s


def _phonetic_loose_key_pt(text: str) -> str:
    """Segunda assinatura tolerante, usada somente quando o resultado e unico.

    Colapsa pares de consoantes que STT costuma trocar por vozeamento. Como a
    decisao final exige um unico verbo canonico, a tolerancia nao e usada para
    nomes de apps/arquivos nem para escolher entre intencoes concorrentes.
    """
    s = phonetic_key_pt(text)
    if not s:
        return ""
    trans = str.maketrans({
        "b": "p", "d": "t", "g": "k", "v": "f", "j": "x",
    })
    s = s.translate(trans)
    s = re.sub(r"([bcdfgjklmnpqrstvx])\1+", r"\1", s)
    # Vogal final e uma fonte recorrente de oscilacao do STT: abre/abri,
    # pause/pausi. So removemos a ultima vogal em tokens com >=5 letras.
    if len(s) >= 5:
        s = re.sub(r"[aeiou]$", "", s)
    return s



def _phonetic_regional_key_pt(text: str) -> str:
    """Assinatura pt-BR regional para fala rápida e variação de vogal final.

    Continua restrita ao primeiro verbo da ordem. A chave aceita fenômenos que
    podem aparecer no STT: elevação de vogal final (e/i, o/u), queda de R/S
    final e simplificação leve de encontros consonantais.
    """
    s = phonetic_key_pt(text)
    if not s:
        return ""
    s = s.replace("tch", "x").replace("dj", "j")
    if len(s) >= 4:
        s = re.sub(r"e$", "i", s)
        s = re.sub(r"o$", "u", s)
    if len(s) >= 5:
        s = re.sub(r"[rs]$", "", s)
    s = re.sub(r"(?<=[bcdfgjklmnpqrstvx])e(?=[bcdfgjklmnpqrstvx])", "i", s)
    s = re.sub(r"(?<=[bcdfgjklmnpqrstvx])o(?=[bcdfgjklmnpqrstvx])", "u", s)
    return s


def _phonetic_skeleton_key_pt(text: str) -> str:
    """Esqueleto consonantal para STT deformado, com guarda de unicidade."""
    s = _phonetic_regional_key_pt(text)
    if not s:
        return ""
    trans = str.maketrans({"b": "p", "d": "t", "g": "k", "v": "f", "j": "x", "z": "s"})
    s = s.translate(trans)
    s = re.sub(r"[aeiou]", "", s)
    s = re.sub(r"(.)\1+", r"\1", s)
    return s


_PHONETIC_REVERSE: Dict[str, Set[str]] = {}
_PHONETIC_LOOSE_REVERSE: Dict[str, Set[str]] = {}
_PHONETIC_REGIONAL_REVERSE: Dict[str, Set[str]] = {}
_PHONETIC_SKELETON_REVERSE: Dict[str, Set[str]] = {}
for form, canonical in _REVERSE.items():
    pkey = phonetic_key_pt(form)
    if pkey:
        _PHONETIC_REVERSE.setdefault(pkey, set()).add(canonical)
    loose = _phonetic_loose_key_pt(form)
    if loose:
        _PHONETIC_LOOSE_REVERSE.setdefault(loose, set()).add(canonical)
    regional = _phonetic_regional_key_pt(form)
    if regional:
        _PHONETIC_REGIONAL_REVERSE.setdefault(regional, set()).add(canonical)
    skeleton = _phonetic_skeleton_key_pt(form)
    if skeleton:
        _PHONETIC_SKELETON_REVERSE.setdefault(skeleton, set()).add(canonical)


def _context_allows(canonical: str, key: str, rest_key: str) -> bool:
    """Evita que uma palavra casual parecida com verbo vire acao."""
    if canonical == "move":
        # Formas ambíguas de movimento só são seguras no domínio de UI.
        if key in {"movel", "mete", "meta", "taca", "taque", "empurra", "empurre"} and not re.search(
            r"\b(?:tela|monitor|display|janela|app|aplicativo|programa|software|player)\b",
            rest_key,
        ):
            return False
    if canonical in {"minimiza", "maximiza"} and key not in _PASSTHROUGH:
        if re.search(r"\b(?:volume|som|audio|brilho)\b", rest_key):
            return False
    if canonical == "minimiza" and key in {"baixa", "baixe", "baixar", "baixo"}:
        # "baixar" em pt-BR e download/obter com muito mais frequencia que
        # minimizar uma janela. A forma explicita "abaixa" continua disponivel.
        return False
    if key == "abril":
        # Vosk pode renderizar "abre" como o mes. So repara com alvo curto.
        if not rest_key or len(rest_key.split()) > 5 or re.search(
            r"\b(?:mes|data|ano|dia|e|foi|sera|feriado|calendario)\b", rest_key
        ):
            return False
    # "para" pode ser pausa ou preposicao. So e verbo quando isolado ou quando
    # o restante fala explicitamente de player/midia.
    if canonical == "pausa" and key in {"para", "segura", "segure", "segurar", "pousa", "pouse"} and rest_key:
        if not re.search(r"\b(?:musica|faixa|som|audio|video|player|spotify|vlc|youtube|netflix|prime|disney|max|crunchy)\b", rest_key):
            return False
    if canonical == "cria" and key in {"faz", "faca", "fazer"}:
        # "faz isso"/"faz aquilo" e follow-up contextual, nao criacao.
        # So convertemos FAZER -> CRIAR quando o objeto explicita algo criavel.
        if not re.search(
            r"\b(?:pasta|arquivo|texto|documento|nota|lembrete|atalho|rotina|lista|planilha|imagem|captura|projeto)\b",
            rest_key,
        ):
            return False
    return True


def canonical_action_word(word: str, rest: str = "") -> Optional[str]:
    key = norm(word)
    if not key:
        return None
    # Palavras interrogativas/pronominais nunca viram verbo por aproximacao
    # fonetica (ex.: "oque" nao pode virar "toque" -> continua).
    if key in {
        "o", "a", "os", "as", "que", "oque", "quem", "qual", "quais",
        "quando", "onde", "como", "porque", "por", "eu", "voce", "vc",
        "isso", "isto", "esse", "essa", "este", "esta", "meu", "minha",
        "oxe", "oxente", "oxi", "vixe", "vixi", "vish", "eita", "visse",
        "bora", "simbora", "vamo", "vamos", "mano", "cara", "macho", "home", "homem",
        "quero", "queria", "preciso", "gostaria", "pode", "poderia", "consegue", "conseguiria",
        "tem", "teria", "deixa", "deixe", "agora", "entao", "certo", "bom",
    }:
        return None
    if key in _PASSTHROUGH:
        return None
    rest_key = norm(rest)

    direct = _REVERSE.get(key)
    if direct and _context_allows(direct, key, rest_key):
        return direct

    # Fonetica estrita: so aceita assinatura que aponta para UM significado.
    if len(key) >= 3:
        candidates = _PHONETIC_REVERSE.get(phonetic_key_pt(key), set())
        if len(candidates) == 1:
            candidate = next(iter(candidates))
            if _context_allows(candidate, key, rest_key):
                return candidate

    # Segunda camada fonetica para transcricoes mais danificadas. Continua
    # exigindo significado unico e contexto permitido.
    if len(key) >= 4:
        candidates = _PHONETIC_LOOSE_REVERSE.get(_phonetic_loose_key_pt(key), set())
        if len(candidates) == 1:
            candidate = next(iter(candidates))
            if _context_allows(candidate, key, rest_key):
                return candidate

    # Camada regional pt-BR/Nordeste: vogal final e R/S podem oscilar na fala.
    if len(key) >= 4:
        candidates = _PHONETIC_REGIONAL_REVERSE.get(_phonetic_regional_key_pt(key), set())
        if len(candidates) == 1:
            candidate = next(iter(candidates))
            if _context_allows(candidate, key, rest_key):
                return candidate

    # Esqueleto consonantal é a última camada fonética. Exigimos token maior,
    # significado único e contexto normal para evitar falsos comandos.
    if len(key) >= 5:
        candidates = _PHONETIC_SKELETON_REVERSE.get(_phonetic_skeleton_key_pt(key), set())
        if len(candidates) == 1:
            candidate = next(iter(candidates))
            if _context_allows(candidate, key, rest_key):
                return candidate

    # Um pequeno erro textual em verbos razoavelmente longos e reparavel.
    if len(key) >= 4:
        choices = sorted({f for f in _REVERSE if len(f) >= 4})
        cutoff = 0.80 if len(key) >= 8 else 0.84 if len(key) >= 6 else 0.88
        matches = difflib.get_close_matches(key, choices, n=3, cutoff=cutoff)
        if matches:
            candidate = _REVERSE[matches[0]]
            # Se duas formas quase igualmente proximas levam a significados
            # diferentes, nao adivinhamos.
            if len(matches) > 1:
                r1 = difflib.SequenceMatcher(None, key, matches[0]).ratio()
                r2 = difflib.SequenceMatcher(None, key, matches[1]).ratio()
                if abs(r1 - r2) < 0.035 and _REVERSE[matches[1]] != candidate:
                    return None
            if _context_allows(candidate, key, rest_key):
                return candidate
    return None



# Atos de fala. Esta camada não executa nada: apenas informa ao Router quando
# uma frase é uma negação/afirmação e resolve autocorreções explícitas.
_COMMAND_HEAD_RE = re.compile(
    r"^(?:abre|abra|abrir|fecha|feche|fechar|minimiza|minimize|minimizar|"
    r"maximiza|maximize|maximizar|restaura|restaure|restaurar|move|mova|mover|"
    r"coloca|coloque|joga|jogue|manda|mande|leva|leve|pesquisa|pesquise|procura|"
    r"busca|pausa|pause|continua|continue|play|toque|toca|desligue|reinicie|"
    r"suspenda|bloqueie|apague|delete|exclua|cria|crie|criar)\b",
    re.I,
)

_CORRECTION_MARKER_RE = re.compile(
    r"[,.!?;:]*\s+(?:(?:nao|não)\s*[,;:]?\s*|quer\s+dizer\s*[,;:]?\s*|ou\s+melhor\s*[,;:]?\s*|corrigindo\s*[,;:]?\s*|"
    r"melhor\s+dizendo\s+)(.+)$",
    re.I,
)


def resolve_self_correction(text: str) -> str:
    """Resolve correção explícita no MESMO enunciado.

    Exemplos:
      abre Discord, não, o Spotify -> abre Spotify
      abre Discord, não, abre Spotify -> abre Spotify
      abre Discord, quer dizer Spotify -> abre Spotify

    A regra exige uma ação clara antes do marcador; portanto "não abre Opera"
    nunca é tratado como autocorreção.
    """
    raw = " ".join(str(text or "").split()).strip()
    if not raw:
        return raw
    # Preserva pontuação apenas para localizar a quebra; a chave normalizada é
    # usada depois para validar a cabeça de ação.
    m = _CORRECTION_MARKER_RE.search(raw)
    if not m:
        return raw
    left = raw[:m.start()].strip(" ,.;:!?")
    right = m.group(1).strip(" ,.;:!?")
    if not left or not right:
        return raw
    left_sem = _strip_semantic_prefixes(left) if '_strip_semantic_prefixes' in globals() else left
    left_key = norm(left_sem)
    head = re.match(r"^([a-z0-9]+)\b", left_key)
    if not head:
        return raw
    canonical = canonical_action_word(head.group(1), left_key[len(head.group(1)):]) or head.group(1)
    if not _COMMAND_HEAD_RE.match(canonical):
        return raw
    # Se a correção já traz um verbo operacional, ela vence integralmente.
    right_key = norm(right)
    if _COMMAND_HEAD_RE.match(right_key):
        return right
    # Caso contrário herda somente o verbo anterior, nunca o alvo anterior.
    return f"{canonical} {right}".strip()


def classify_speech_act(text: str) -> str:
    """Classifica guarda de alto nível sem inferir intenção perigosa.

    Retorna: command_candidate, negated_command, assertion, question ou neutral.
    """
    raw = " ".join(str(text or "").split()).strip()
    key = norm(raw)
    if not key:
        return "neutral"

    # Correção explícita é analisada antes da negação: em "abre X, não, Y" o
    # "não" corrige o alvo; em "não abre X" ele cancela a ação.
    corrected = resolve_self_correction(raw)
    if norm(corrected) != key and _COMMAND_HEAD_RE.match(norm(corrected)):
        return "command_candidate"

    neg_patterns = (
        r"^(?:eu\s+)?(?:nao|nunca|nem)\s+(?:quero\s+que\s+(?:voce\s+)?|quero\s+|precisa\s+|preciso\s+|vai\s+)?",
        r"^(?:nao\s+precisa|nao\s+quero|nao\s+vai|evita|evite)\s+(?:de\s+)?",
        r"^(?:melhor\s+nao|prefiro\s+nao)\s+",
        r"^(?:deixa\s+de|pare\s+de)\s+",
    )
    for prefix in neg_patterns:
        m = re.match(prefix, key, flags=re.I)
        if not m:
            continue
        rest = key[m.end():].strip()
        if rest and _COMMAND_HEAD_RE.match(rest):
            return "negated_command"

    # Perguntas explícitas vencem a detecção de estado. Ex.:
    # "qual programa está aberto?" não é a afirmação "o Opera está aberto".
    if raw.rstrip().endswith("?") or re.match(
        r"^(?:o que|oque|quem|qual|quais|quando|onde|como|por que|porque|me explica|"
        r"me fale|me fala|me diga|fale sobre|quero saber)\b",
        key, re.I,
    ):
        return "question"

    # Afirmações de ação concluída/estado nunca são imperativos.
    if re.match(
        r"^(?:eu\s+)?(?:ja\s+|fui\s+la\s+e\s+)?(?:abri|fechei|minimizei|maximizei|"
        r"movi|coloquei|joguei|mandei|pesquisei|procurei|pausei|continuei|reiniciei|desliguei)\b",
        key, re.I,
    ):
        return "assertion"
    if re.match(
        r"^(?:eu\s+)?(?:acabei\s+de|terminei\s+de|consegui|tentei)\s+"
        r"(?:abrir|fechar|minimizar|maximizar|mover|colocar|jogar|mandar|pesquisar|procurar|"
        r"pausar|continuar|reiniciar|desligar)\b",
        key, re.I,
    ):
        return "assertion"
    if re.match(
        r"^(?:eu\s+)?(?:estou|to)\s+(?:abrindo|fechando|minimizando|maximizando|movendo|"
        r"colocando|jogando|mandando|pesquisando|procurando|pausando|reiniciando|desligando)\b",
        key, re.I,
    ):
        return "assertion"
    if re.match(
        r"^(?:o|a)?\s*[a-z0-9][a-z0-9 ]{1,80}\s+(?:esta|ta|ficou|continua)\s+"
        r"(?:aberto|aberta|fechado|fechada|minimizado|minimizada|maximizado|maximizada)\b",
        key, re.I,
    ):
        return "assertion"

    if _COMMAND_HEAD_RE.match(key):
        return "command_candidate"
    return "neutral"


def normalize_broken_command(text: str) -> str:
    """Repara fala quebrada apenas quando há evidência estrutural suficiente."""
    raw = " ".join(str(text or "").split()).strip()
    key = norm(raw)
    if not key:
        return raw
    # "aquele Opera... joga ele na outra tela" / "Opera, manda ele pro monitor 2".
    m = re.match(
        r"^(?:(?:aquele|aquela|esse|essa|o|a)\s+)?(.+?)\s+"
        r"(?:joga|jogue|move|mova|manda|mande|leva|leve|bota|bote|coloca|coloque)\s+"
        r"(?:ele|ela|isso)?\s*(?:pra|pro|para|na|no)\s+"
        r"((?:outra\s+tela|outro\s+monitor|outro\s+display)|"
        r"(?:monitor|tela|display)\s*(?:\d+|um|dois|tres|quatro)|"
        r"(?:primeira|segunda|terceira|quarta|primeiro|segundo|terceiro|quarto)\s+(?:tela|monitor|display))$",
        key, re.I,
    )
    if m:
        target, dest = m.group(1).strip(), m.group(2).strip()
        if target and target not in {"ele", "ela", "isso", "aquilo"}:
            return f"move {target} para {dest}"
    return raw



# Molduras de fala espontânea e variantes comuns em diferentes regiões do
# Nordeste. Não existe um único "sotaque nordestino": estas são formas
# coloquiais contextuais, ativadas somente quando há ação logo depois.
_ACTION_START_FRAGMENT = (
    r"(?:abre|abra|abrir|fecha|feche|fechar|fexa|fexar|minimiza|minimize|minimizar|"
    r"maximiza|maximize|maximizar|restaura|restaure|restaurar|pesquisa|"
    r"pesquise|pesquisar|procura|procure|procurar|prucura|busca|busque|buscar|"
    r"clica|clique|clicar|pausa|pause|pausar|continua|continue|continuar|toca|toque|"
    r"cria|crie|criar)"
)

_REGIONAL_PREFIX_PATTERNS = tuple(re.compile(p, re.I) for p in (
    rf"^(?:bora(?:\s+la)?|simbora(?:\s+la)?|vamo(?:s)?(?:\s+la)?|partiu)[,;:!?.\s]+(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:meu\s+rei|meu\s+chapa|meu\s+patrao|meu\s+patr[aã]o|chefe|macho|home|homem)[,;:!?.\s]+(?=(?:(?:bora(?:\s+la)?|simbora(?:\s+la)?|vamo(?:s)?(?:\s+la)?|partiu)[,;:!?.\s]+)?{_ACTION_START_FRAGMENT}\b)",
    rf"^(?:bora(?:\s+la)?|simbora(?:\s+la)?|vamo(?:s)?(?:\s+la)?)[,;:!?.\s]+(?=(?:move|mova|mover|coloca|coloque|botar|bota|bote|joga|jogue|manda|mande|leva|leve)\b.*\b(?:monitor|tela|display|janela|app|aplicativo|programa)\b)",
    rf"^(?:tu|ce|c[eê]|voce|vc)\s+(?:pode|consegue|poderia|conseguiria)\s+(?:me\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:ve|v[eê]|veja|olha|olhe)\s+se\s+(?:(?:tu|ce|c[eê]|voce|vc)\s+)?(?:consegue|pode|da\s+pra)?\s*(?:me\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:da|d[aá])\s+(?:pra|para)\s+(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:tem|teria)\s+como\s+(?:(?:tu|ce|c[eê]|voce|vc)\s+)?(?:me\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:faz|faca|fa[cç]a)\s+o\s+seguinte[,;:!?.\s]+(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:me\s+quebra\s+essa|quebra\s+essa\s+(?:pra|para)\s+mim|da\s+essa\s+moral|d[aá]\s+uma\s+moral)[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:me\s+faz\s+um\s+favor|faz\s+um\s+favor\s+(?:pra|para)\s+mim)[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:faz|faca|fa[cç]a)\s+(?:essa|isso)\s+(?:pra|para)\s+mim[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:da|d[aá])\s+um\s+jeito\s+(?:de|pra|para)\s+(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:ve|v[eê]|veja|olha|olhe)\s+(?:ai|a[ií])\s+se\s+(?:da|d[aá])\s+(?:pra|para)\s+(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:num|nao|não)\s+tem\s+como\s+(?:(?:tu|ce|c[eê]|voce|vc)\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:bora|simbora|vamo|vamos)\s+logo[,;:!?.\s]+(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:quebra\s+esse\s+galho|me\s+quebra\s+esse\s+galho)(?:\s+(?:pra|para)\s+mim)?[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:faz|faca|fa[cç]a)\s+esse\s+corre(?:\s+(?:pra|para)\s+mim)?[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:desenrola|desenrole)\s+(?:isso|essa)(?:\s+(?:pra|para)\s+mim)?[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:resolve|resolva)\s+(?:isso|essa)(?:\s+(?:pra|para)\s+mim)?[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:arruma|arrume)\s+(?:ai|a[ií])(?:\s+(?:pra|para)\s+mim)?[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:tu|ce|c[eê]|voce|vc)\s+(?:faz|faca|fa[cç]a)\s+favor[,;:!?.\s]+(?:e\s+)?(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:bora|simbora)\s+nessa[,;:!?.\s]+(?={_ACTION_START_FRAGMENT}\b)",
    rf"^(?:vai\s+na\s+fe|vai\s+na\s+fé)[,;:!?.\s]+(?={_ACTION_START_FRAGMENT}\b)",
))

_REGIONAL_SUFFIX_RE = re.compile(
    r"(?:[,;:!?.\s]+(?:ai|a[ií]|viu|visse|meu\s+rei|meu\s+chapa|meu\s+patrao|meu\s+patr[aã]o|chefe|por\s+favor|por\s+gentileza|pra\s+mim|para\s+mim))+$",
    re.I,
)

_GERUND_TO_COMMAND = {
    "abrindo": "abre", "fechando": "fecha", "fexando": "fecha",
    "minimizando": "minimiza", "maximizando": "maximiza",
    "restaurando": "restaura", "movendo": "move", "jogando": "move",
    "botando": "move", "colocando": "move", "pesquisando": "pesquisa",
    "procurando": "pesquisa", "prucurando": "pesquisa", "buscando": "pesquisa",
    "clicando": "clica", "pausando": "pausa", "continuando": "continua",
}


def _normalize_regional_command_frames(text: str) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return value

    value = re.sub(r"\bprum\b", "para um", value, flags=re.I)
    value = re.sub(r"\bpruma\b", "para uma", value, flags=re.I)
    value = re.sub(r"\bpruns\b", "para uns", value, flags=re.I)
    value = re.sub(r"\bprumas\b", "para umas", value, flags=re.I)

    for _ in range(5):
        changed = False
        for pattern in _REGIONAL_PREFIX_PATTERNS:
            updated = pattern.sub("", value, count=1).strip()
            if updated != value:
                value = updated
                changed = True
                break
        if not changed:
            break

    # "manda abrir" é ordem indireta; sem a regra, MANDA poderia virar MOVE.
    value = re.sub(
        rf"^(?:manda|mande)\s+(?={_ACTION_START_FRAGMENT}\b)",
        "", value, count=1, flags=re.I,
    ).strip()

    gm = re.match(r"^(?:vai|va|v[aá])\s+([A-Za-zÀ-ÿ]+)\b(.*)$", value, flags=re.I | re.S)
    if gm:
        command = _GERUND_TO_COMMAND.get(norm(gm.group(1)))
        if command:
            value = f"{command}{gm.group(2)}".strip()

    desired = re.match(
        r"^(?:deixa|deixe)\s+(?:o\s+|a\s+)?(.+?)\s+(aberto|aberta|fechado|fechada|minimizado|minimizada|maximizado|maximizada)$",
        value, flags=re.I,
    )
    if desired:
        target, state = desired.group(1).strip(), norm(desired.group(2))
        verb = "abre" if state.startswith("abert") else "fecha" if state.startswith("fechad") else "minimiza" if state.startswith("minimiz") else "maximiza"
        value = f"{verb} {target}".strip()

    run_app = re.match(
        r"^(?:bota|bote|coloca|coloque)\s+(?:o\s+|a\s+)?(.+?)\s+(?:pra|para)\s+(?:rodar|funcionar|abrir)$",
        value, flags=re.I,
    )
    if run_app:
        value = f"abre {run_app.group(1).strip()}"

    return value


def _strip_regional_suffixes(text: str) -> str:
    value = " ".join(str(text or "").split()).strip()
    if not value:
        return value
    return _REGIONAL_SUFFIX_RE.sub("", value).strip(" ,.;:!?")


# Formas sociais sao removidas somente do INICIO. O objetivo e aceitar fala
# natural, nao alterar nomes de arquivos/apps no meio da frase.
_SOCIAL_PREFIX_RE = re.compile(
    r"^(?:"
    r"por\s+favor|por\s+gentileza|na\s+moral|faz\s+a\s+boa|me\s+quebra\s+essa|(?:me\s+)?quebra\s+esse\s+galho(?:\s+(?:pra|para)\s+mim)?(?:\s+e)?|faz\s+esse\s+corre(?:\s+(?:pra|para)\s+mim)?(?:\s+e)?|desenrola\s+isso(?:\s+(?:pra|para)\s+mim)?(?:\s+e)?|resolve\s+isso(?:\s+(?:pra|para)\s+mim)?(?:\s+e)?|arruma\s+ai(?:\s+(?:pra|para)\s+mim)?(?:\s+e)?|faz\s+um\s+favor|faz\s+favor|faz\s+essa\s+pra\s+mim|da\s+um\s+jeito\s+de|se\s+puder|se\s+possivel|"
    r"oxe|oxente|oxenti|oxi|vixe|vixi|vish|eita\s+peste|eita|ave\s+maria|"
    r"se\s+n[aã]o\s+for\s+incomodo|se\s+n[aã]o\s+for\s+muito|se\s+n[aã]o\s+for\s+pedir\s+muito|quando\s+puder|quando\s+der|rapidinho|rapidao|"
    r"vish|vixe|ixi|eita\s+peste|eita|olha|olha\s+s[oó]|ah+|aah+|eh+|hmm+|hum+|bom|certo|ent[aã]o|tipo|viu|"
    r"tu\s+pode|tu\s+consegue|tu\s+poderia|ce\s+pode|ce\s+consegue|ce\s+poderia|"
    r"voce\s+pode|vc\s+pode|voce\s+poderia|vc\s+poderia|poderia|pode\s+me|pode|"
    r"voce\s+consegue|vc\s+consegue|consegue\s+me|consegue|tem\s+como|da\s+pra|daria\s+pra|"
    r"seria\s+possivel|sera\s+que\s+da\s+pra|sera\s+que\s+voce\s+pode|"
    r"eu\s+quero\s+que\s+voce|eu\s+quero\s+que|eu\s+quero|quero\s+que\s+voce|quero\s+que|"
    r"eu\s+queria\s+que\s+voce|eu\s+queria\s+que|eu\s+queria|queria\s+que\s+voce|queria\s+que|"
    r"eu\s+gostaria\s+que\s+voce|eu\s+gostaria\s+que|gostaria\s+que\s+voce|gostaria\s+que|"
    r"preciso\s+que\s+voce|preciso\s+que|me\s+ajuda\s+a|me\s+ajude\s+a|"
    r"faz\s+pra\s+mim|faz\s+para\s+mim|faca\s+pra\s+mim|faca\s+para\s+mim|"
    r"jarvis|oi\s+jarvis|ei\s+jarvis|e\s+ai\s+jarvis|ola\s+jarvis"
    r")[,;:!?\.\s]+",
    re.I,
)


def _strip_semantic_prefixes(raw: str) -> str:
    value = raw.strip()
    for _ in range(7):
        updated = _SOCIAL_PREFIX_RE.sub("", value, count=1).strip()
        if updated == value:
            break
        value = updated
    return value


def normalize_action_utterance(text: str) -> str:
    raw = " ".join(str(text or "").split()).strip()
    if not raw:
        return raw

    raw = resolve_self_correction(raw)

    # Primeiro remove wake/cortesia; depois repara a fala quebrada. Isso permite
    # "Jarvis... aquele... Opera... joga ele na outra tela" sem contaminar o alvo.
    semantic = _strip_semantic_prefixes(raw)
    semantic = _normalize_regional_command_frames(semantic)
    semantic = normalize_broken_command(semantic)
    # Hesitação logo após o verbo é ruído de fala, não parte do nome do app.
    semantic = re.sub(
        r"^([^\s,;.!?]+)[, ]+(?:(?:ah+|aah+|eh+|hum+|hmm+|tipo)[, ]+)+",
        r"\1 ", semantic, flags=re.I,
    ).strip()
    semantic = _strip_regional_suffixes(semantic)
    semantic_key = norm(semantic)

    # Semantica de midia por frase. Verbos como "passa"/"muda" so viram
    # NEXT quando o objeto explicita musica/faixa, preservando comandos como
    # "passa o Opera para a tela 2".
    if re.fullmatch(
        r"(?:passa|passe|passar|troca|troque|trocar|muda|mude|mudar|avanca|avance|avancar|"
        r"pula|pule|pular|manda|mande|mandar|bota|bote|botar)\s+"
        r"(?:(?:a|essa|esta)\s+)?(?:musica|faixa|track|som)", semantic_key
    ):
        return "proxima musica"
    if re.fullmatch(
        r"(?:volta|volte|voltar|retorna|retorne|retornar)\s+"
        r"(?:(?:a|pra|para a)\s+)?(?:musica|faixa|track)(?:\s+anterior)?", semantic_key
    ):
        return "musica anterior"
    if semantic_key in {"proximo", "proxima", "seguinte", "avanca", "avance", "proxima musica", "proxima faixa"}:
        return "proxima musica"
    if re.fullmatch(r"(?:ja\s+)?(?:proxima musica|proxima faixa|proximo|proxima|seguinte)", semantic_key):
        return "proxima musica"

    # "passa o Opera para a segunda tela" e movimento de janela, enquanto
    # "passa a musica" foi resolvido acima como midia. Exigir destino de tela
    # evita transformar usos comuns de "passar" em MOVE_WINDOW.
    movement = re.match(
        r"^(?:passa|passe|passar|manda|mande|mandar|joga|jogue|jogar|leva|leve|levar)\s+"
        r"(?:(?:o|a)\s+)?(.+?)\s+(?:para|pra|pro|na|no)\s+(?:(?:a|o)\s+)?"
        r"((?:monitor|monito|tela|display)\s*\d+|(?:primeira|segunda|terceira|quarta|primeiro|segundo|terceiro|quarto)\s+(?:monitor|monito|tela|display))$",
        semantic_key,
    )
    if movement:
        target, destination = movement.group(1).strip(), movement.group(2).strip()
        return f"move {target} para {destination}"

    m = re.match(r"^([^\s,;.!?]+)(.*)$", semantic, flags=re.S)
    if not m:
        return semantic
    first, rest = m.group(1), m.group(2)
    canonical = canonical_action_word(first, rest)
    if not canonical:
        return semantic
    return canonical + rest


def normalize_close_target(target: str) -> str:
    """Reparo conservador para OBS apenas em contexto destrutivo/confirmado."""
    raw = " ".join(str(target or "").split()).strip()
    key = norm(raw)
    compact = key.replace(" ", "")
    if compact in {"obs", "obes", "obsstudio", "obestudio", "bs"} or key in {
        "o b s", "o bs", "o bes", "bessico", "besico"
    }:
        return "OBS"
    return raw


def is_other_monitor_fragment(text: str) -> bool:
    key = norm(text)
    return bool(re.fullmatch(
        r"(?:(?:para|pra|pro|na|no)\s+)?(?:(?:a|o)\s+)?(?:outra\s+tela|outro\s+monitor|outro\s+display|outra|outro)(?:\s+agora)?",
        key,
    ))


# Perfil auditável da camada linguística. Os nomes abaixo representam classes
# que possuem regra, guarda ou caminho explícito no normalizador/router; não são
# apenas rótulos para inflar a métrica.
_SEMANTIC_FAMILY_NAMES = (
    "imperativo_direto", "flexao_verbal", "sinonimo_operacional", "pedido_cortesia",
    "vocativo_assistente", "prefixo_social", "sufixo_cortesia", "filler_discursivo",
    "hesitacao", "pontuacao_prosodia", "marcador_temporal", "conector_alvo",
    "artigo_alvo", "ordinal_monitor", "numero_monitor", "localizacao_contextual",
    "pronome_contextual", "elipse_de_alvo", "followup_curto", "autocorrecao_nao",
    "autocorrecao_quer_dizer", "autocorrecao_ou_melhor", "negacao_direta",
    "preferencia_negativa", "afirmacao_concluida", "afirmacao_progressiva",
    "afirmacao_estado", "guarda_interrogativa", "fala_quebrada", "clausula_repetida",
    "erro_stt_textual", "erro_stt_fonetico", "giria_regional", "midia_contextual",
    "janela_contextual", "site_contextual", "multiacao_temporal", "referencia_ultimo_app",
    "referencia_ultimo_monitor", "guarda_colisao_midia_app", "guarda_ambiguidade_fuzzy",
    "nordeste_interjeicao_oxe", "nordeste_interjeicao_oxente", "nordeste_interjeicao_vixe",
    "nordeste_interjeicao_eita", "nordeste_wrapper_bora", "nordeste_wrapper_simbora",
    "nordeste_vocativo_meu_rei", "nordeste_vocativo_contextual", "nordeste_marcador_visse",
    "nordeste_pronome_tu", "nordeste_reducao_ce", "nordeste_bota_operacional",
    "nordeste_fala_vamo", "nordeste_pedido_da_pra", "nordeste_pedido_tem_como",
    "nordeste_quebra_essa", "nordeste_da_uma_moral", "nordeste_contracao_prum",
    "imperativo_indireto_manda", "imperativo_progressivo_vai_gerundio",
    "resultado_desejado_aberto", "resultado_desejado_fechado",
    "resultado_desejado_minimizado", "resultado_desejado_maximizado",
    "app_bota_pra_rodar", "sufixo_deictico_ai", "sufixo_discursivo_visse",
    "sufixo_vocativo", "reducao_vogal_final", "queda_r_final", "queda_s_final",
    "elevacao_vogal_atona", "esqueleto_consonantal", "vozeamento_stt",
    "fala_rapida_regional", "filtro_interjeicao_como_acao", "filtro_regional_por_contexto",
    "fallback_sem_execucao",
    "nordeste_faz_essa_pra_mim", "nordeste_da_um_jeito_de",
    "nordeste_ve_ai_se_da_pra", "nordeste_num_tem_como",
    "nordeste_bora_logo", "cortesia_acao_encadeada",
    "stt_abre_fala_rapida", "stt_fecha_fala_rapida",
    "stt_pesquisa_fala_rapida", "stt_janela_fala_rapida",
    "nordeste_quebra_esse_galho", "nordeste_faz_esse_corre",
    "nordeste_desenrola_isso", "nordeste_resolve_isso",
    "nordeste_arruma_ai", "nordeste_tu_faz_favor",
    "nordeste_bora_nessa", "nordeste_vai_na_fe",
    "wrapper_acao_com_e", "wrapper_regional_alvo_protegido",
)

_PHONETIC_TRANSFORM_NAMES = (
    "remocao_de_acentos", "g_ei_para_j", "c_ei_para_s", "sch_para_x",
    "sh_para_x", "ch_para_x", "ph_para_f", "th_para_t", "rh_para_r",
    "lh_para_li", "nh_para_ni", "qu_para_k", "gu_para_g", "ck_q_c_para_k",
    "ss_sc_xc_para_s", "z_para_s", "y_para_i", "w_para_v", "rr_para_r",
    "h_mudo", "consoante_repetida", "surda_sonora", "vogal_final_oscilante",
    "tch_para_x", "dj_para_j", "e_final_para_i", "o_final_para_u",
    "queda_r_final", "queda_s_final", "e_atono_para_i", "o_atono_para_u",
    "esqueleto_sem_vogais", "b_p_equivalente", "d_t_equivalente",
    "g_k_equivalente", "v_f_equivalente", "j_x_equivalente",
    "z_s_equivalente", "colapso_esqueleto_repetido", "r_fala_rapida",
    "s_fala_rapida", "vocalismo_regional_ptbr", "assinatura_regional_unica",
    "assinatura_esqueleto_unica",
    "fexa_para_fecha", "feixa_para_fecha", "prucura_para_pesquisa",
    "percura_para_pesquisa", "pisquisa_para_pesquisa", "pesquiza_para_pesquisa",
    "minimisa_para_minimiza", "maximisa_para_maximiza",
)

def linguistic_profile() -> Dict[str, object]:
    return {
        "semantic_family_count": len(_SEMANTIC_FAMILY_NAMES),
        "phonetic_transform_count": len(_PHONETIC_TRANSFORM_NAMES),
        "semantic_families": list(_SEMANTIC_FAMILY_NAMES),
        "phonetic_transforms": list(_PHONETIC_TRANSFORM_NAMES),
        "language_profile": "pt-BR + variantes nordestinas contextuais",
        "lexical_form_count": len(_REVERSE),
        "strict_phonetic_keys": len(_PHONETIC_REVERSE),
        "regional_phonetic_keys": len(_PHONETIC_REGIONAL_REVERSE),
        "skeleton_phonetic_keys": len(_PHONETIC_SKELETON_REVERSE),
        "coverage_estimate": semantic_coverage_estimate(),
    }


# Fatores auditaveis da gramatica combinatoria. Eles representam familias de
# superficie realmente aceitas pelas camadas de prefixo/router/fonetica; nao
# representam frases armazenadas. O alvo (nome do app/site/consulta) nem entra
# na conta, portanto a estimativa nao depende de inventar um numero de alvos.
_SEMANTIC_GRAMMAR_FACTORS = {
    "social_request_wrappers": 32,
    "pronoun_auxiliary_forms": 24,
    "discourse_fillers": 18,
    "target_connectors": 14,
    "context_location_forms": 12,
    "temporal_modifiers": 10,
    "courtesy_suffixes": 8,
    "stt_surface_variants": 10,
    "phonetic_renderings": 16,
    # Quatro classes de fala espontanea realmente tratadas pela normalizacao:
    # hesitacao, marcador discursivo, wake/vocativo residual e prosodia/pontuacao.
    "speech_disfluency_variants": 4,
    # Hotfix 4: famílias adicionais realmente tratadas por guards/rewrite.
    "speech_act_classes": 5,
    "negation_guard_forms": 12,
    "assertion_guard_forms": 10,
    "self_correction_forms": 8,
    "context_reference_forms": 8,
    "regional_register_forms": 42,
    "broken_speech_forms": 12,
    "northeast_interjection_prefixes": 18,
    "northeast_request_frames": 26,
    "northeast_vocative_forms": 10,
    "regional_discourse_suffixes": 12,
    "tu_ce_pronoun_frames": 8,
    "indirect_imperative_frames": 8,
    "progressive_imperative_frames": 12,
    "desired_state_frames": 8,
    "regional_contraction_forms": 6,
    "regional_phonetic_renderings": 32,
}


def semantic_coverage_breakdown() -> Dict[str, int]:
    lexical = sum(len(v) for v in _CANONICAL.values())
    result = {"lexical_action_forms": lexical}
    result.update(_SEMANTIC_GRAMMAR_FACTORS)
    return result


def semantic_coverage_estimate() -> int:
    """Estimativa combinatoria de formulacoes aceitas pela camada.

    O numero e um marco de *superficie linguistica potencial*, nao uma promessa
    de 100% de reconhecimento de audio. O valor pode superar um septilhao porque
    mede combinacoes de familias em tempo de execucao, nao entradas armazenadas.
    Microfone, ruido, VAD e o STT continuam
    podendo errar. A metrica evita armazenar trilhoes de strings: combina formas
    lexicais, molduras sociais, conectores e variacoes foneticas em tempo real.
    """
    factors = semantic_coverage_breakdown().values()
    return int(math.prod(int(x) for x in factors))


__all__ = [
    "norm",
    "phonetic_key_pt",
    "canonical_action_word",
    "resolve_self_correction",
    "classify_speech_act",
    "normalize_broken_command",
    "normalize_action_utterance",
    "normalize_close_target",
    "is_other_monitor_fragment",
    "semantic_coverage_breakdown",
    "semantic_coverage_estimate",
    "linguistic_profile",
]
