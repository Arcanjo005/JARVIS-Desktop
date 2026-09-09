"""JARVIS - Universal App Resolver.

Camada unica para descobrir, indexar e resolver aplicativos com seguranca.

Principios:
- Conhecimento global pode ser enorme, mas nunca autoriza abrir algo sozinho.
- Aplicativos instalados recebem prioridade maxima.
- Alias pessoal e match exato vencem fuzzy.
- Ambiguidade gera recusa segura em vez de abrir o app errado.
- O catalogo global do winget e usado como conhecimento/hint, nao como alvo local.
- Hotwords de voz sao derivados apenas do conjunto local/relevante.
"""
from __future__ import annotations

import difflib
import json
import math
import ntpath
import os
import re
import shutil
import string
import subprocess
import tempfile
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from jarvis_identity import env as jarvis_env

try:
    import winreg
except Exception:  # pragma: no cover - Linux/static tests
    winreg = None


CATALOG_VERSION = 7
BAD_EXECUTABLE_WORDS = {
    "uninstall", "uninstaller", "update", "updater", "helper", "setup",
    "installer", "crash", "service", "telemetry", "reporter", "repair",
    "bootstrapper", "launcherhelper", "maintenanceservice",
}

# Alias de alta confianca. A lista nao precisa carregar todos os apps do mundo:
# o catalogo global + descoberta local fazem isso dinamicamente. Estes aliases
# existem principalmente para variacoes de fala e nomes muito populares.
COMMON_APP_ALIASES: Dict[str, Tuple[str, ...]] = {
    "Opera GX": ("opera", "opera gx", "opera g x", "o pera", "opera gamer", "operar"),
    "Google Chrome": ("chrome", "google chrome", "crome", "gugou chrome"),
    "Microsoft Edge": ("edge", "microsoft edge", "edje"),
    "Mozilla Firefox": ("firefox", "mozilla", "mozilla firefox", "fire fox"),
    "Brave": ("brave", "brave browser"),
    "Vivaldi": ("vivaldi",),
    "Tor Browser": ("tor", "tor browser"),
    "Visual Studio Code": ("vs code", "vscode", "visual code", "visual studio code", "ve esse code"),
    "Visual Studio": ("visual studio", "vs", "ve esse"),
    "PyCharm": ("pycharm", "pai charm"),
    "IntelliJ IDEA": ("intellij", "intellij idea", "idea"),
    "Android Studio": ("android studio",),
    "Sublime Text": ("sublime", "sublime text"),
    "Notepad++": ("notepad plus plus", "notepad++", "notepad mais mais"),
    "Windows Terminal": ("terminal", "windows terminal", "wt"),
    "PowerShell": ("powershell", "power shell"),
    "Command Prompt": ("cmd", "prompt", "prompt de comando"),
    "Git Bash": ("git bash",),
    "GitHub Desktop": ("github desktop", "git hub desktop"),
    "Docker Desktop": ("docker", "docker desktop"),
    "Postman": ("postman",),
    "Insomnia": ("insomnia",),
    "DBeaver": ("dbeaver", "d beaver"),
    "HeidiSQL": ("heidi sql", "heidisql"),
    "MySQL Workbench": ("mysql workbench", "my sql workbench"),
    "SQL Server Management Studio": ("ssms", "sql server management studio"),
    "OBS Studio": ("obs", "obs studio", "o b s", "obes", "o bes"),
    "Streamlabs Desktop": ("streamlabs", "stream labs"),
    "Adobe Photoshop": ("photoshop", "adobe photoshop", "foto shop"),
    "Adobe Illustrator": ("illustrator", "adobe illustrator"),
    "Adobe Premiere Pro": ("premiere", "premiere pro", "adobe premiere"),
    "Adobe After Effects": ("after effects", "after", "adobe after effects"),
    "Adobe Audition": ("audition", "adobe audition"),
    "Adobe Media Encoder": ("media encoder", "adobe media encoder"),
    "Adobe Acrobat": ("acrobat", "adobe acrobat", "acrobat reader", "pdf reader"),
    "Adobe InDesign": ("indesign", "in design"),
    "CorelDRAW": ("corel", "corel draw", "coreldraw"),
    "DaVinci Resolve": ("davinci", "davinci resolve", "da vinci"),
    "Blender": ("blender",),
    "GIMP": ("gimp", "guimp"),
    "Krita": ("krita",),
    "Figma": ("figma",),
    "Canva": ("canva",),
    "Paint": ("paint", "mspaint", "pbrush", "pente"),
    "Paint 3D": ("paint 3d", "paint tres d"),
    "Spotify": ("spotify", "spot fai", "spotfy"),
    "Apple Music": ("apple music",),
    "iTunes": ("itunes", "ai tunes"),
    "VLC media player": ("vlc", "v l c", "vlc player"),
    "Media Player": ("media player", "windows media player"),
    "Audacity": ("audacity",),
    "Discord": ("discord", "dis cor d", "discordia", "dix cor de", "discor de", "descord", "duscird", "discordio"),
    "Blood Strike": ("bloodstrike", "blood strike", "bloody strike", "blodi strike", "blod strike", "blude strike"),
    "Microsoft Teams": ("teams", "microsoft teams"),
    "Zoom": ("zoom",),
    "Slack": ("slack",),
    "Telegram": ("telegram",),
    "WhatsApp": ("whatsapp", "zap", "whats app"),
    "Signal": ("signal",),
    "Skype": ("skype",),
    "Steam": ("steam", "istim", "estim", "stym"),
    "Epic Games Launcher": ("epic", "epic games", "epic games launcher"),
    "EA app": ("ea", "ea app", "e a"),
    "Ubisoft Connect": ("ubisoft", "ubisoft connect"),
    "GOG Galaxy": ("gog", "gog galaxy"),
    "Battle.net": ("battle net", "battlenet", "battle.net"),
    "Riot Client": ("riot", "riot client"),
    "VALORANT": ("valorant", "valo"),
    "League of Legends": ("league", "league of legends", "lol"),
    "Counter-Strike 2": ("counter strike", "counter strike 2", "cs2", "cs dois"),
    "Fortnite": ("fortnite", "fort night"),
    "Minecraft": ("minecraft", "mine craft"),
    "Roblox": ("roblox",),
    "Grand Theft Auto V": ("gta", "gta 5", "gta v", "grand theft auto"),
    "Call of Duty": ("call of duty", "cod"),
    "Cyberpunk 2077": ("cyberpunk", "cyberpunk 2077"),
    "Forza Horizon": ("forza", "forza horizon"),
    "Rocket League": ("rocket league",),
    "Overwatch 2": ("overwatch", "overwatch 2"),
    "Apex Legends": ("apex", "apex legends"),
    "Dota 2": ("dota", "dota 2"),
    "PUBG": ("pubg", "p u b g"),
    "Microsoft Word": ("word", "microsoft word"),
    "Microsoft Excel": ("excel", "microsoft excel"),
    "Microsoft PowerPoint": ("powerpoint", "power point"),
    "Microsoft Outlook": ("outlook", "out look"),
    "Microsoft OneNote": ("onenote", "one note"),
    "Microsoft Access": ("access", "microsoft access"),
    "Microsoft Store": ("store", "microsoft store", "loja", "loja microsoft"),
    "File Explorer": ("explorer", "explorador de arquivos", "gerenciador de arquivos", "meus arquivos"),
    "Task Manager": ("task manager", "gerenciador de tarefas"),
    "Calculator": ("calculadora", "calculator", "calc"),
    "Notepad": ("bloco de notas", "notepad"),
    "Settings": ("configuracoes", "configuracao", "settings"),
    "7-Zip": ("7zip", "7 zip", "sete zip"),
    "WinRAR": ("winrar", "win rar"),
    "WinZip": ("winzip", "win zip"),
    "Everything": ("everything", "everything search"),
    "PowerToys": ("powertoys", "power toys"),
    "Revo Uninstaller": ("revo", "revo uninstaller"),
    "Geek Uninstaller": ("geek", "geek uninstaller"),
    "CCleaner": ("ccleaner", "c cleaner"),
    "AnyDesk": ("anydesk", "any desk"),
    "TeamViewer": ("teamviewer", "team viewer"),
    "Remote Desktop": ("remote desktop", "area de trabalho remota", "mstsc"),
    "VirtualBox": ("virtualbox", "virtual box"),
    "VMware Workstation": ("vmware", "vmware workstation"),
    "Hyper-V Manager": ("hyper v", "hyper-v", "gerenciador hyper v"),
}


@dataclass
class AppRecord:
    name: str
    target: str = ""
    source: str = ""
    installed: bool = True
    package_id: str = ""
    aliases: List[str] = field(default_factory=list)
    publisher: str = ""
    version: str = ""
    last_seen: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RankedApp:
    record: AppRecord
    score: float
    exact: bool = False
    matched_form: str = ""
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = self.record.to_dict()
        data.update({
            "score": round(float(self.score), 4),
            "confidence": round(float(self.score), 4),
            "exact": bool(self.exact),
            "matched_form": self.matched_form,
            "reasons": list(self.reasons),
            "label": self.record.name,
        })
        return data


@dataclass
class ResolveResult:
    query: str
    selected: Optional[RankedApp]
    candidates: List[RankedApp]
    confidence: float
    margin: float
    safe: bool
    reason: str

    def selected_dict(self) -> Optional[Dict[str, Any]]:
        if not self.selected:
            return None
        data = self.selected.to_dict()
        data["resolver_reason"] = self.reason
        data["resolver_margin"] = round(self.margin, 4)
        data["safe"] = self.safe
        return data


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\b(?:x64|x86|64 bit|32 bit|stable|beta|launcher version)\b", " ", value)
    value = re.sub(r"\b20\d{2}\b", " ", value)
    return " ".join(value.split())


def compact_name(value: str) -> str:
    return normalize_name(value).replace(" ", "")


def spoken_phonetic_key(value: str) -> str:
    """Chave fonética leve para nomes de apps misturados pt-BR/inglês.

    Não tenta ser um algoritmo linguístico universal. O objetivo é aproximar
    pronúncia casual/STT de entidades já conhecidas e instaladas, sem autorizar
    execução por si só. A decisão final continua usando confiança + margem do
    UniversalAppResolver.
    """
    text = normalize_name(value)
    if not text:
        return ""
    compact = text.replace(" ", "")
    # Dígrafos comuns preservam mais a pronúncia que a grafia literal.
    compact = (
        compact.replace("tch", "x")
        .replace("dge", "j")
        .replace("dj", "j")
        .replace("ph", "f")
        .replace("sh", "x")
        .replace("ch", "x")
        .replace("th", "t")
        .replace("lh", "l")
        .replace("nh", "n")
        .replace("rr", "r")
        .replace("qu", "k")
        .replace("ck", "k")
    )
    mapped = []
    for ch in compact:
        if ch in "aeiouy":
            continue
        if ch in "cqk":
            ch = "k"
        elif ch in "xsz":
            ch = "s"
        elif ch in "gj":
            ch = "j"
        elif ch == "w":
            ch = "v"
        elif ch == "h":
            continue
        if not mapped or mapped[-1] != ch:
            mapped.append(ch)
    return "".join(mapped)



def spoken_regional_key(value: str) -> str:
    """Chave fonética frouxa para variações de voz/STT em pt-BR.

    Agrupa pares surda/sonora (p/b, t/d, f/v) e aproxima j/x. A chave entra
    apenas como evidência adicional de baixa ponderação; confiança e margem do
    resolver continuam obrigatórias antes de qualquer app ser selecionado.
    """
    key = spoken_phonetic_key(value)
    if not key:
        return ""
    trans = str.maketrans({"b": "p", "d": "t", "v": "f", "j": "x"})
    key = key.translate(trans)
    key = re.sub(r"(.)\1+", r"\1", key)
    return key


def spoken_similarity(a: str, b: str) -> float:
    """Similaridade ortográfica + fonética, sempre limitada a 0..1."""
    an = normalize_name(a)
    bn = normalize_name(b)
    if not an or not bn:
        return 0.0
    ac, bc = compact_name(an), compact_name(bn)
    literal = max(
        difflib.SequenceMatcher(None, an, bn).ratio(),
        difflib.SequenceMatcher(None, ac, bc).ratio() if ac and bc else 0.0,
    )
    ak, bk = spoken_phonetic_key(an), spoken_phonetic_key(bn)
    phon = difflib.SequenceMatcher(None, ak, bk).ratio() if ak and bk else 0.0
    # Chave fonética exata em nomes com conteúdo suficiente é evidência forte,
    # mas não pula a margem/ambiguidade do resolver.
    if len(ak) >= 3 and ak == bk:
        phon = 1.0
    ark, brk = spoken_regional_key(an), spoken_regional_key(bn)
    regional = difflib.SequenceMatcher(None, ark, brk).ratio() if ark and brk else 0.0
    # A camada regional é propositalmente mais fraca para não abrir app errado.
    return max(literal, phon * 0.96, regional * 0.86)


def _canonical_common_query(value: str) -> str:
    """Collapse harmless spacing/accent variants of known app aliases.

    This is entity normalization, not fuzzy execution: it only fires when the
    compact form exactly matches a known strong alias (e.g. "ó per a" ->
    "opera", "o b s" -> "obs").
    """
    q = normalize_name(value)
    qc = compact_name(q)
    if not q or not qc:
        return q
    matches = []
    for canonical, aliases in COMMON_APP_ALIASES.items():
        forms = (canonical, *aliases)
        for alias in forms:
            if compact_name(normalize_name(alias)) == qc:
                matches.append((canonical, normalize_name(alias)))
                break
    families = {normalize_name(item[0]) for item in matches}
    if len(families) == 1 and matches:
        # Return the shortest matching alias; this tends to be the spoken name
        # ("opera", "obs") and improves exact-family resolution.
        aliases = sorted((item[1] for item in matches), key=lambda x: (len(x), x))
        return aliases[0]
    return q


def _clean_display_name(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"\s+\d+(?:\.\d+){1,4}(?:\s+.*)?$", "", value).strip()
    value = re.sub(r"\s+(?:x64|x86|64-bit|32-bit|Stable)$", "", value, flags=re.I).strip()
    return value or str(value or "").strip()


def _acronym(value: str) -> str:
    tokens = [t for t in normalize_name(value).split() if t not in {"microsoft", "adobe", "google", "the", "of", "and", "app"}]
    if len(tokens) < 2:
        return ""
    return "".join(t[0] for t in tokens if t)


def _spoken_variants(value: str) -> List[str]:
    """Gera variantes conservadoras de fala/STT para um nome conhecido."""
    n = normalize_name(value)
    out = {n, n.replace(" plus ", " + ")}
    if not n:
        return []
    compact = n.replace(" ", "")
    out.add(compact)
    acro = _acronym(n)
    if 2 <= len(acro) <= 6:
        out.add(acro)
        out.add(" ".join(acro))
    replacements = {
        "opera": ("o pera", "opera"),
        "obs": ("o b s",),
        "vscode": ("vs code", "ve esse code"),
        "visual studio code": ("vs code", "vscode", "visual code"),
        "coreldraw": ("corel draw", "corel"),
        "chatgpt": ("chat gpt", "chat g p t"),
        "powerpoint": ("power point",),
        "onenote": ("one note",),
        "anydesk": ("any desk",),
        "teamviewer": ("team viewer",),
        "battle net": ("battlenet",),
    }
    for key, vals in replacements.items():
        if key in n or key in compact:
            out.update(normalize_name(x) for x in vals)
    return sorted(x for x in out if x)


def _common_alias_applies(record_name: str, canonical: str) -> bool:
    rn = normalize_name(record_name)
    cn = normalize_name(canonical)
    if not rn or not cn:
        return False
    if rn == cn or compact_name(rn) == compact_name(cn):
        return True
    rn_tokens = rn.split()
    cn_tokens = cn.split()
    # Permite apenas qualificadores inocuos de fabricante/edicao. Evita, por
    # exemplo, tratar "Visual Studio Tools for Applications" como "Visual Studio".
    if all(token in rn_tokens for token in cn_tokens):
        extras = [t for t in rn_tokens if t not in cn_tokens]
        harmless = {
            "microsoft", "adobe", "google", "mozilla", "desktop", "classic",
            "stable", "browser", "navegador", "edition", "graphics", "suite",
            "professional", "pro", "reader",
        }
        return bool(extras) and len(extras) <= 2 and all(t in harmless for t in extras)
    return False


def _semantic_family(record: AppRecord) -> str:
    """Agrupa representações do mesmo produto vindas de fontes diferentes."""
    rn = normalize_name(record.name)
    for canonical, aliases in COMMON_APP_ALIASES.items():
        cn = normalize_name(canonical)
        alias_names = {normalize_name(x) for x in aliases}
        if _common_alias_applies(rn, cn) or rn in alias_names or compact_name(rn) in {compact_name(x) for x in alias_names}:
            return "common:" + compact_name(cn)
    return "name:" + compact_name(rn)


def _forms_for_record(record: AppRecord) -> List[str]:
    forms = set()
    for raw in [record.name, *record.aliases]:
        forms.update(_spoken_variants(raw))
    if record.target and not record.target.startswith(("shell:", "steam:", "com.epicgames")):
        raw_target = record.target.strip('"')
        stem = ntpath.splitext(ntpath.basename(raw_target))[0]
        if stem:
            forms.update(_spoken_variants(stem))
    if record.package_id:
        tail = record.package_id.rsplit(".", 1)[-1]
        forms.update(_spoken_variants(tail))
    return sorted(forms)


class UniversalAppResolver:
    LOCAL_SOURCES = {
        "Ensinado", "Alias pessoal", "Cache", "App Paths", "Registro", "StartApps",
        "Atalho", "Portable", "Steam", "Epic", "Disco", "Legacy", "Winget Installed",
    }

    def __init__(self, project_dir: str, logger=None, load_global: bool = True):
        self.project_dir = Path(project_dir).resolve()
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger
        self.index_path = self.data_dir / "app_index_v7.json"
        self.alias_path = self.data_dir / "app_aliases_v7.json"
        self.usage_path = self.data_dir / "app_usage_v7.json"
        self.global_path = self.data_dir / "app_catalog_global_v7.json"
        self.global_meta_path = self.data_dir / "app_catalog_global_v7.meta.json"
        self._lock = threading.RLock()
        self._index = [r for r in self._load_records(self.index_path) if not self._is_self_launcher(r)]
        self._aliases = self._load_dict(self.alias_path)
        self._usage = self._load_dict(self.usage_path)
        self._load_global_enabled = bool(load_global)
        self._global = self._load_records(self.global_path) if self._load_global_enabled else []
        self._global_loaded = bool(load_global)
        self._global_count_hint = len(self._global) if self._global_loaded else self._load_global_count_hint()
        self._forms_cache: Dict[str, List[str]] = {}
        self._exact_forms_lookup: Dict[str, List[AppRecord]] = {}
        self._exact_lookup_ready = False
        self._last_rebuild = 0.0
        self._catalog_thread: Optional[threading.Thread] = None
        self.min_confidence = float(jarvis_env("APP_MIN_CONFIDENCE", "0.82") or 0.82)
        self.min_margin = float(jarvis_env("APP_MIN_MARGIN", "0.10") or 0.10)
        self.single_word_confidence = float(jarvis_env("APP_SINGLE_WORD_CONFIDENCE", "0.88") or 0.88)
        self.short_word_confidence = float(jarvis_env("APP_SHORT_WORD_CONFIDENCE", "0.95") or 0.95)
        self._ingest_legacy_files()

    def _load_global_count_hint(self) -> int:
        try:
            data = json.loads(self.global_meta_path.read_text(encoding="utf-8"))
            return max(0, int(data.get("count", 0) or 0)) if isinstance(data, dict) else 0
        except Exception:
            return 0

    def _ensure_global_loaded(self):
        if self._global_loaded:
            return
        with self._lock:
            if self._global_loaded:
                return
            self._global = self._load_records(self.global_path)
            self._global_count_hint = len(self._global)
            self._global_loaded = True

    def _log(self, level: str, text: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(text, "APP-V7")
                except TypeError:
                    fn(text)
        except Exception:
            pass

    @staticmethod
    def _load_dict(path: Path) -> Dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _load_records(path: Path) -> List[AppRecord]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw = raw.get("apps", [])
            out = []
            for item in raw if isinstance(raw, list) else []:
                if not isinstance(item, dict):
                    continue
                out.append(AppRecord(
                    name=str(item.get("name") or item.get("label") or "").strip(),
                    target=str(item.get("target") or "").strip(),
                    source=str(item.get("source") or "").strip(),
                    installed=bool(item.get("installed", True)),
                    package_id=str(item.get("package_id") or item.get("id") or "").strip(),
                    aliases=[str(x) for x in item.get("aliases", []) if str(x).strip()],
                    publisher=str(item.get("publisher") or "").strip(),
                    version=str(item.get("version") or "").strip(),
                    last_seen=str(item.get("last_seen") or "").strip(),
                ))
            return [r for r in out if r.name]
        except Exception:
            return []

    @staticmethod
    def _atomic_json(path: Path, data: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _save_index(self):
        payload = {
            "version": CATALOG_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "apps": [r.to_dict() for r in self._index],
        }
        self._atomic_json(self.index_path, payload)

    def _save_global(self):
        generated_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "version": CATALOG_VERSION,
            "generated_at": generated_at,
            "apps": [r.to_dict() for r in self._global],
        }
        self._atomic_json(self.global_path, payload)
        self._global_count_hint = len(self._global)
        self._global_loaded = True
        self._atomic_json(self.global_meta_path, {
            "version": CATALOG_VERSION,
            "generated_at": generated_at,
            "count": self._global_count_hint,
        })

    def _ingest_legacy_files(self):
        legacy_index = self.data_dir / "app_index.json"
        if legacy_index.exists():
            try:
                raw = json.loads(legacy_index.read_text(encoding="utf-8"))
                self.ingest_candidates(raw if isinstance(raw, list) else [], source_default="Legacy", save=False)
            except Exception:
                pass
        legacy_alias = self.data_dir / "app_aliases.json"
        if legacy_alias.exists():
            try:
                raw = json.loads(legacy_alias.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for alias, data in raw.items():
                        if isinstance(data, dict) and data.get("target"):
                            key = normalize_name(alias)
                            self._aliases.setdefault(key, {
                                "target": str(data.get("target")),
                                "display_name": str(data.get("display_name") or alias),
                                "learned_at": str(data.get("learned_at") or "legacy"),
                            })
            except Exception:
                pass

    @staticmethod
    def _merge_record(a: AppRecord, b: AppRecord) -> AppRecord:
        # Prefere a fonte que prova instalacao e o nome mais informativo.
        name = a.name if len(a.name) >= len(b.name) else b.name
        source = a.source or b.source
        if b.source in UniversalAppResolver.LOCAL_SOURCES and a.source not in UniversalAppResolver.LOCAL_SOURCES:
            source = b.source
        target = a.target or b.target
        if b.target and (not a.target or b.source in {"Ensinado", "Alias pessoal", "App Paths", "Steam", "Epic"}):
            target = b.target
        aliases = sorted(set(a.aliases + b.aliases))
        return AppRecord(
            name=name,
            target=target,
            source=source,
            installed=a.installed or b.installed,
            package_id=a.package_id or b.package_id,
            aliases=aliases,
            publisher=a.publisher or b.publisher,
            version=a.version or b.version,
            last_seen=b.last_seen or a.last_seen,
        )

    @staticmethod
    def _identity_key(record: AppRecord) -> str:
        target = record.target.strip().lower()
        if target:
            return "target:" + target
        if record.package_id:
            return "pkg:" + record.package_id.lower()
        return "name:" + compact_name(record.name)

    @staticmethod
    def _is_self_launcher(record: AppRecord) -> bool:
        """Nao indexa atalhos do proprio assistente, inclusive nomes historicos."""
        name_key = normalize_name(record.name)
        target_key = str(record.target or "").replace("/", "\\").lower()
        if name_key in {"jarvis", "jarvis assistant", "abrir jarvis", "abrir zero"}:
            return True
        return any(token in target_key for token in ("abrir_jarvis.bat", "abrir_zero.bat"))

    def ingest_candidates(self, items: Iterable[Any], source_default: str = "Legacy", save: bool = True):
        with self._lock:
            by_key = {self._identity_key(r): r for r in self._index}
            for item in items or []:
                if isinstance(item, AppRecord):
                    rec = item
                elif isinstance(item, dict):
                    name = str(item.get("name") or item.get("label") or "").strip()
                    target = str(item.get("target") or "").strip()
                    if not name:
                        continue
                    rec = AppRecord(
                        name=_clean_display_name(name),
                        target=target,
                        source=str(item.get("source") or source_default),
                        installed=bool(item.get("installed", True)),
                        package_id=str(item.get("package_id") or item.get("id") or ""),
                        aliases=[str(x) for x in item.get("aliases", []) if str(x).strip()],
                        publisher=str(item.get("publisher") or ""),
                        version=str(item.get("version") or ""),
                        last_seen=datetime.now(timezone.utc).isoformat(),
                    )
                else:
                    continue
                if not rec.name or self._is_self_launcher(rec):
                    continue
                key = self._identity_key(rec)
                if key in by_key:
                    by_key[key] = self._merge_record(by_key[key], rec)
                else:
                    by_key[key] = rec
            self._index = list(by_key.values())
            self._forms_cache.clear()
            self._exact_forms_lookup.clear()
            self._exact_lookup_ready = False
            if save:
                self._save_index()

    def _alias_variants_for(self, record: AppRecord) -> List[str]:
        key = self._identity_key(record)
        cached = self._forms_cache.get(key)
        if cached is not None:
            return cached
        forms = set(_forms_for_record(record))
        rn = normalize_name(record.name)
        for canonical, aliases in COMMON_APP_ALIASES.items():
            canonical_n = normalize_name(canonical)
            if _common_alias_applies(rn, canonical_n):
                forms.update(normalize_name(x) for x in aliases)
                forms.add(canonical_n)
        self._forms_cache[key] = sorted(x for x in forms if x)
        return self._forms_cache[key]

    def prewarm_local_forms(self) -> dict:
        """Precalcula aliases/formas e um lookup exato fora do primeiro comando."""
        started = time.perf_counter()
        with self._lock:
            records = list(self._index)
        built = 0
        exact_lookup: Dict[str, List[AppRecord]] = {}
        for record in records:
            try:
                forms = self._alias_variants_for(record)
                for form in forms:
                    fn = normalize_name(form)
                    if not fn:
                        continue
                    exact_lookup.setdefault("n:" + fn, []).append(record)
                    fc = compact_name(fn)
                    if fc:
                        exact_lookup.setdefault("c:" + fc, []).append(record)
                built += 1
            except Exception:
                continue
        with self._lock:
            self._exact_forms_lookup = exact_lookup
            self._exact_lookup_ready = True
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._log("info", f"App Resolver V8 prewarm: {built} app(s) em {elapsed_ms:.1f} ms")
        return {"apps": built, "elapsed_ms": elapsed_ms, "exact_keys": len(exact_lookup)}

    def _usage_bonus(self, record: AppRecord) -> float:
        data = self._usage.get(self._identity_key(record), {}) if isinstance(self._usage, dict) else {}
        count = max(0, int(data.get("count", 0) or 0)) if isinstance(data, dict) else 0
        return min(0.035, math.log1p(count) * 0.008)

    def _source_bonus(self, record: AppRecord) -> float:
        source = record.source
        if source in {"Ensinado", "Alias pessoal"}:
            return 0.10
        if source == "Cache":
            return 0.055
        if source in {"App Paths", "Registro", "StartApps", "Portable", "Steam", "Epic", "Atalho"}:
            return 0.045
        if record.installed:
            return 0.03
        return 0.0

    def _personal_alias_record(self, query: str) -> Optional[AppRecord]:
        data = self._aliases.get(normalize_name(query))
        if not isinstance(data, dict):
            return None
        target = str(data.get("target") or "").strip()
        if not target:
            return None
        return AppRecord(
            name=str(data.get("display_name") or query),
            target=target,
            source="Alias pessoal",
            installed=True,
            aliases=[query],
        )

    def _score_record(self, query: str, record: AppRecord) -> RankedApp:
        q = normalize_name(query)
        qc = compact_name(q)
        q_tokens = set(q.split())
        best = 0.0
        best_form = ""
        exact = False
        reasons: List[str] = []

        forms = self._alias_variants_for(record)
        for form in forms:
            f = normalize_name(form)
            fc = compact_name(f)
            if not f:
                continue
            score = 0.0
            local_exact = False
            if q == f:
                score = 0.985
                local_exact = True
            elif qc and qc == fc:
                score = 0.975
                local_exact = True
            else:
                f_tokens = set(f.split())
                ratio = difflib.SequenceMatcher(None, q, f).ratio()
                compact_ratio = difflib.SequenceMatcher(None, qc, fc).ratio() if qc and fc else 0.0
                phonetic_ratio = spoken_similarity(q, f)
                overlap_q = len(q_tokens & f_tokens) / max(1, len(q_tokens))
                overlap_f = len(q_tokens & f_tokens) / max(1, len(f_tokens))
                prefix = 1.0 if (f.startswith(q + " ") or q.startswith(f + " ")) else 0.0
                substring = 1.0 if (len(q) >= 4 and (q in f or f in q)) else 0.0
                score = (
                    ratio * 0.39
                    + compact_ratio * 0.15
                    + overlap_q * 0.17
                    + overlap_f * 0.07
                    + prefix * 0.04
                    + substring * 0.03
                    + phonetic_ratio * 0.15
                )
                phon_key_q = spoken_phonetic_key(q)
                phon_key_f = spoken_phonetic_key(f)
                if len(phon_key_q) >= 3 and phon_key_q == phon_key_f:
                    score = max(score, 0.89)
                    reasons.append("phonetic")
                if len(q_tokens) == 1 and len(q) <= 3 and not (q == f or qc == fc):
                    score *= 0.62
            if score > best:
                best = score
                best_form = f
                exact = local_exact

        if exact:
            reasons.append("exact")
        if record.installed:
            reasons.append("installed")
        if record.source in {"Ensinado", "Alias pessoal"}:
            reasons.append("personal_alias")
        best += self._source_bonus(record) + self._usage_bonus(record)

        # Registros de desinstalação/atualização às vezes expõem um DisplayIcon
        # que não é o executável principal. Eles podem permanecer no índice para
        # conhecimento, mas jamais devem vencer um launcher real do mesmo app.
        target = str(record.target or "")
        if target and not target.startswith(("shell:", "steam:", "com.epicgames")):
            ext_n = ntpath.splitext(target.strip('"'))[1].lower()
            if ext_n in {".ico", ".png", ".jpg", ".jpeg", ".bmp", ".dll"}:
                best -= 0.55
                reasons.append("non_launchable_target")
            stem_n = normalize_name(ntpath.splitext(ntpath.basename(target.strip('"')))[0])
            strong_bad = ("setup", "unins", "uninstall", "update", "updater", "repair", "crash")
            helper_bad = ("helper", "bootstrap", "info", "reporter", "service")
            if any(token in stem_n for token in strong_bad):
                best -= 0.38
                reasons.append("unsafe_target_name")
            elif any(token in stem_n for token in helper_bad):
                best -= 0.18
                reasons.append("helper_target_name")
        return RankedApp(record=record, score=max(0.0, min(best, 1.0)), exact=exact, matched_form=best_form, reasons=reasons)

    def _exact_local_matches(self, query: str) -> List[RankedApp]:
        """Fast path for exact/spacing-normalized local aliases.

        Startup already prewarms spoken forms. Common commands such as
        "opera", "ó per a" and "obs" should not pay SequenceMatcher cost
        across the whole local catalog. Ambiguity rules are preserved.
        """
        q = normalize_name(_canonical_common_query(query) or query)
        qc = compact_name(q)
        if not q:
            return []
        matches: Dict[str, RankedApp] = {}
        personal = self._personal_alias_record(q)
        if personal is not None:
            ranked = RankedApp(
                record=personal, score=1.0, exact=True, matched_form=q,
                reasons=["personal_alias"],
            )
            matches[self._identity_key(personal)] = ranked
        with self._lock:
            if self._exact_lookup_ready:
                records = list(self._exact_forms_lookup.get("n:" + q, []))
                if qc:
                    records.extend(self._exact_forms_lookup.get("c:" + qc, []))
            else:
                records = list(self._index)
        seen_records = set()
        for rec in records:
            identity = self._identity_key(rec)
            if identity in seen_records or not rec.installed:
                continue
            seen_records.add(identity)
            exact_form = ""
            for form in self._alias_variants_for(rec):
                fn = normalize_name(form)
                if q == fn or (qc and qc == compact_name(fn)):
                    exact_form = fn
                    break
            if not exact_form:
                continue
            ranked = self._score_record(q, rec)
            ranked.exact = True
            ranked.matched_form = exact_form
            key = identity
            old = matches.get(key)
            if old is None or ranked.score > old.score:
                matches[key] = ranked
        out = list(matches.values())
        out.sort(key=lambda x: (x.score, x.exact, x.record.installed), reverse=True)
        return out

    def rank(self, query: str, limit: int = 8, include_global: bool = False) -> List[RankedApp]:
        query = str(query or "").strip()
        query = _canonical_common_query(query) or query
        if not query:
            return []
        records: List[AppRecord] = []
        personal = self._personal_alias_record(query)
        if personal:
            records.append(personal)
        with self._lock:
            records.extend(self._index)
        if include_global:
            self._ensure_global_loaded()
            with self._lock:
                records.extend(self._global)
        # Dedupe before scoring.
        unique: Dict[str, AppRecord] = {}
        for rec in records:
            key = self._identity_key(rec)
            unique[key] = self._merge_record(unique[key], rec) if key in unique else rec
        ranked = [self._score_record(query, rec) for rec in unique.values()]
        ranked.sort(key=lambda x: (x.score, x.exact, x.record.installed), reverse=True)
        return ranked[:max(1, int(limit))]

    def resolve(self, query: str, limit: int = 8) -> ResolveResult:
        # An explicitly taught alias is authoritative and can bypass all fuzzy
        # ranking. This makes the user's most common apps effectively O(1).
        canonical_query = _canonical_common_query(query) or str(query or "").strip()
        personal = self._personal_alias_record(canonical_query)
        if personal is not None:
            top = RankedApp(
                record=personal, score=1.0, exact=True,
                matched_form=normalize_name(canonical_query), reasons=["personal_alias"],
            )
            return ResolveResult(
                query=query, selected=top, candidates=[top], confidence=1.0,
                margin=1.0, safe=True, reason="personal_alias_exact",
            )
        # Exact local aliases are overwhelmingly common in interactive use.
        # Resolve them without fuzzy-scoring the full catalog.
        exact_ranked = self._exact_local_matches(canonical_query)
        ranked = exact_ranked[:max(1, int(limit))] if exact_ranked else self.rank(query, limit=limit, include_global=False)
        if not ranked:
            return ResolveResult(query, None, [], 0.0, 0.0, False, "no_candidates")
        top = ranked[0]
        top_name = compact_name(top.record.name)
        second = next(
            (item for item in ranked[1:] if compact_name(item.record.name) != top_name),
            None,
        )
        margin = top.score - (second.score if second else 0.0)
        q = normalize_name(query)
        q_tokens = q.split()

        exact_installed = [
            item for item in ranked
            if item.exact and item.record.installed and "unsafe_target_name" not in item.reasons and "non_launchable_target" not in item.reasons
        ]
        exact_families = {_semantic_family(item.record) for item in exact_installed}
        personal_exact = bool(top.exact and "personal_alias" in top.reasons)

        if personal_exact:
            safe = True
            reason = "personal_alias_exact"
        elif top.exact and top.record.installed and len(exact_families) <= 1:
            safe = True
            reason = "exact_installed"
        elif top.exact and top.record.installed and len(exact_families) > 1:
            # Ex.: dois produtos diferentes que aceitam o mesmo alias curto.
            # Melhor pedir esclarecimento do que abrir o errado.
            safe = False
            reason = "multiple_exact_installed"
        else:
            threshold = self.min_confidence
            required_margin = self.min_margin
            if len(q_tokens) == 1:
                threshold = self.single_word_confidence if len(q) >= 4 else self.short_word_confidence
                required_margin = 0.13
            safe = bool(top.record.installed and top.score >= threshold and margin >= required_margin)
            reason = "confident_installed" if safe else "ambiguous_or_low_confidence"

        return ResolveResult(
            query=query,
            selected=top if safe else None,
            candidates=ranked,
            confidence=top.score,
            margin=margin,
            safe=safe,
            reason=reason,
        )

    def find_candidates(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self.rank(query, limit=limit, include_global=False)]

    def record_success(self, record_or_target: Any):
        if isinstance(record_or_target, RankedApp):
            key = self._identity_key(record_or_target.record)
        elif isinstance(record_or_target, AppRecord):
            key = self._identity_key(record_or_target)
        elif isinstance(record_or_target, dict):
            rec = AppRecord(name=str(record_or_target.get("name") or record_or_target.get("label") or ""), target=str(record_or_target.get("target") or ""), source=str(record_or_target.get("source") or ""))
            key = self._identity_key(rec)
        else:
            key = "target:" + str(record_or_target or "").strip().lower()
        if not key:
            return
        with self._lock:
            row = self._usage.get(key, {}) if isinstance(self._usage.get(key), dict) else {}
            row["count"] = int(row.get("count", 0) or 0) + 1
            row["last_success"] = datetime.now(timezone.utc).isoformat()
            self._usage[key] = row
            self._atomic_json(self.usage_path, self._usage)

    def learn_alias(self, alias: str, target: str, display_name: str = "") -> bool:
        key = normalize_name(alias)
        if not key or not target:
            return False
        with self._lock:
            self._aliases[key] = {
                "target": str(target),
                "display_name": str(display_name or alias).strip(),
                "learned_at": datetime.now(timezone.utc).isoformat(),
            }
            self._atomic_json(self.alias_path, self._aliases)
        return True

    def forget_alias(self, alias: str) -> bool:
        key = normalize_name(alias)
        with self._lock:
            existed = key in self._aliases
            self._aliases.pop(key, None)
            self._atomic_json(self.alias_path, self._aliases)
        return existed

    def voice_terms(self, limit: int = 220) -> List[str]:
        """Termos para STT: somente apps locais + aliases fortes/recentes.

        Nunca retorna o catalogo global inteiro. Isso evita degradar o modelo de
        fala com dezenas de milhares de hotwords concorrentes.
        """
        ranked_terms: List[Tuple[float, str]] = []
        seen = set()
        with self._lock:
            records = list(self._index)
            aliases = dict(self._aliases)
        voice_blacklist = {
            "runtime", "redistributable", "driver", "manual", "manuals", "documentation",
            "uninstall", "uninstaller", "updater", "update", "wizard", "extension",
            "webview", "service", "services", "developer", "faq", "site", "history",
            "helper", "bootstrapper", "telemetry", "license", "licensing", "tools",
            "libraries", "library", "faq", "faqs", "learn", "history", "reset",
        }
        voice_phrase_blacklist = {
            "run time libraries", "saiba mais", "on the web", "frequently asked questions",
            "refresh manager", "usb display", "easy photo print", "gaming mouse",
        }
        for rec in records:
            if not rec.installed:
                continue
            rn = normalize_name(rec.name)
            target_n = normalize_name(ntpath.splitext(ntpath.basename(rec.target.strip('"')))[0]) if rec.target and not rec.target.startswith(("shell:", "steam:", "com.epicgames")) else ""
            noisy = set((rn + " " + target_n).split()) & BAD_EXECUTABLE_WORDS
            if noisy:
                continue
            common_match = any(_common_alias_applies(rn, normalize_name(canonical)) for canonical in COMMON_APP_ALIASES)
            usage_row = self._usage.get(self._identity_key(rec), {}) if isinstance(self._usage, dict) else {}
            used = bool(isinstance(usage_row, dict) and int(usage_row.get("count", 0) or 0) > 0)
            if set(rn.split()) & voice_blacklist and not (common_match or used):
                continue
            if any(phrase in rn for phrase in voice_phrase_blacklist) and not (common_match or used):
                continue
            if any(ch in rec.name for ch in "¢Æµ‡¡") and not used:
                continue
            # Exclui executaveis internos pouco pronunciaveis; eles continuam no
            # resolver, apenas nao poluem o vocabulario do STT.
            friendly = bool(" " in rec.name or rec.source in {"Registro", "StartApps", "Steam", "Epic", "Atalho"})
            if rec.source == "App Paths" and not friendly and len(rn) > 13:
                continue
            base_score = self._source_bonus(rec) + self._usage_bonus(rec)
            if rec.source in {"StartApps", "Steam", "Epic", "Registro"}:
                base_score += 0.07
            if " " in rec.name:
                base_score += 0.025
            variants = [rec.name]
            # Apenas aliases conhecidos de alta qualidade, nao todas as formas fuzzy.
            for canonical, vals in COMMON_APP_ALIASES.items():
                cn = normalize_name(canonical)
                if _common_alias_applies(rn, cn):
                    variants.extend(vals[:4])
                    base_score += 0.05
            acro = _acronym(rec.name)
            if acro:
                variants.append(acro)
            for term in variants:
                clean = " ".join(str(term).split()).strip()
                key = normalize_name(clean)
                if not key or key in seen or len(clean) > 70:
                    continue
                seen.add(key)
                score = base_score + (0.10 if clean == rec.name else 0.04)
                ranked_terms.append((score, clean))
        for alias in aliases:
            if alias not in seen:
                ranked_terms.append((1.0, alias))
        ranked_terms.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in ranked_terms[:max(20, int(limit))]]

    def _registry_candidates(self) -> List[AppRecord]:
        results: List[AppRecord] = []
        if winreg is None or os.name != "nt":
            return results
        app_path_roots = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        ]
        for hive, key_path in app_path_roots:
            try:
                with winreg.OpenKey(hive, key_path) as root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            child = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, child) as key:
                                target = str(winreg.QueryValueEx(key, None)[0]).strip('"')
                            target = os.path.expandvars(target)
                            if os.path.isfile(target):
                                results.append(AppRecord(name=Path(child).stem, target=target, source="App Paths", installed=True))
                        except Exception:
                            pass
            except Exception:
                pass

        uninstall_roots = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, key_path in uninstall_roots:
            try:
                with winreg.OpenKey(hive, key_path) as root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            child = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, child) as key:
                                def val(name: str) -> str:
                                    try:
                                        return str(winreg.QueryValueEx(key, name)[0])
                                    except Exception:
                                        return ""
                                display = val("DisplayName").strip()
                                icon = val("DisplayIcon").split(",")[0].strip('"')
                                location = val("InstallLocation").strip('"')
                                publisher = val("Publisher").strip()
                                version = val("DisplayVersion").strip()
                            target = ""
                            icon = os.path.expandvars(icon)
                            location = os.path.expandvars(location)
                            if icon and os.path.isfile(icon):
                                icon_stem = normalize_name(ntpath.splitext(ntpath.basename(icon))[0])
                                if not any(bad in icon_stem for bad in ("setup", "unins", "uninstall", "update", "updater", "repair")):
                                    target = icon
                            elif location and os.path.isdir(location):
                                exes = []
                                try:
                                    for name in os.listdir(location):
                                        p = os.path.join(location, name)
                                        if os.path.isfile(p) and name.lower().endswith(".exe"):
                                            exes.append(p)
                                except Exception:
                                    pass
                                if exes:
                                    display_n = normalize_name(display)
                                    target = max(exes, key=lambda p: difflib.SequenceMatcher(None, display_n, normalize_name(Path(p).stem)).ratio())
                            if display and target:
                                results.append(AppRecord(name=_clean_display_name(display), target=target, source="Registro", installed=True, publisher=publisher, version=version))
                        except Exception:
                            pass
            except Exception:
                pass
        return results

    def _startapps_candidates(self) -> List[AppRecord]:
        if os.name != "nt":
            return []
        try:
            script = "Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }"
            proc = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=15, errors="ignore")
            out = []
            for line in proc.stdout.splitlines():
                if "|" not in line:
                    continue
                name, app_id = line.split("|", 1)
                if name.strip() and app_id.strip():
                    out.append(AppRecord(name=name.strip(), target="shell:AppsFolder\\" + app_id.strip(), source="StartApps", installed=True, package_id=app_id.strip()))
            return out
        except Exception:
            return []

    def _shortcut_candidates(self) -> List[AppRecord]:
        if os.name != "nt":
            return []
        roots = [
            Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.getenv("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.getenv("USERPROFILE", "")) / "Desktop",
            Path(os.getenv("PUBLIC", r"C:\Users\Public")) / "Desktop",
        ]
        out: List[AppRecord] = []
        for root in roots:
            if not root.is_dir():
                continue
            for current, dirs, files in os.walk(root):
                try:
                    if len(Path(current).parts) - len(root.parts) > 8:
                        dirs[:] = []
                        continue
                except Exception:
                    pass
                for name in files:
                    if name.lower().endswith((".lnk", ".url", ".exe", ".bat", ".cmd")):
                        out.append(AppRecord(name=Path(name).stem, target=str(Path(current) / name), source="Atalho", installed=True))
        return out

    def _portable_candidates(self) -> List[AppRecord]:
        """Varredura conservadora de locais comuns de aplicativos portáteis.

        Não percorre o disco inteiro: isso seria lento e introduziria milhares
        de helpers/uninstallers. Apps fora destes locais continuam sendo
        encontrados por atalhos, App Paths, Registro ou alias ensinado.
        """
        if os.name != "nt":
            return []
        roots = [
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs",
            Path(os.getenv("USERPROFILE", "")) / "Applications",
            Path(os.getenv("USERPROFILE", "")) / "PortableApps",
            Path(os.getenv("USERPROFILE", "")) / "Desktop",
            Path(r"C:\PortableApps"),
        ]
        bad = BAD_EXECUTABLE_WORDS | {
            "setup", "install", "installer", "update", "updater", "uninstall",
            "crash", "report", "helper", "service", "bootstrap", "repair",
        }
        out: List[AppRecord] = []
        seen = set()
        for root in roots:
            if not root or not root.is_dir():
                continue
            for current, dirs, files in os.walk(root):
                current_path = Path(current)
                try:
                    depth = len(current_path.relative_to(root).parts)
                except Exception:
                    depth = 99
                if depth >= 3:
                    dirs[:] = []
                # Evita árvores de dependências e caches gigantes.
                dirs[:] = [d for d in dirs if normalize_name(d) not in {"node modules", "cache", "temp", "logs", "packages"}]
                for filename in files:
                    if not filename.lower().endswith(".exe"):
                        continue
                    stem = Path(filename).stem
                    normalized = normalize_name(stem)
                    if len(normalized) < 2 or set(normalized.split()) & bad:
                        continue
                    target = str(current_path / filename)
                    key = target.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    # Diretório costuma conter um nome mais amigável que o exe.
                    parent = current_path.name.strip()
                    parent_n = normalize_name(parent)
                    name = parent if parent_n and parent_n not in {"bin", "app", "application", "program", "programs"} else stem
                    out.append(AppRecord(name=_clean_display_name(name), target=target, source="Portable", installed=True, aliases=[stem]))
        return out

    def _steam_candidates(self) -> List[AppRecord]:
        if os.name != "nt":
            return []
        roots = []
        for base in [os.getenv("PROGRAMFILES(X86)", ""), os.getenv("PROGRAMFILES", "")]:
            if base:
                p = Path(base) / "Steam"
                if p.is_dir():
                    roots.append(p)
        if winreg is not None:
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for key_path in (r"Software\Valve\Steam", r"Software\WOW6432Node\Valve\Steam"):
                    try:
                        with winreg.OpenKey(hive, key_path) as key:
                            for value_name in ("SteamPath", "InstallPath"):
                                try:
                                    p = Path(str(winreg.QueryValueEx(key, value_name)[0]))
                                    if p.is_dir():
                                        roots.append(p)
                                except Exception:
                                    pass
                    except Exception:
                        pass
        libraries = set()
        for root in roots:
            libraries.add(root)
            vdf = root / "steamapps/libraryfolders.vdf"
            try:
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                    p = Path(match.group(1).replace("\\\\", "\\"))
                    if p.is_dir():
                        libraries.add(p)
            except Exception:
                pass
        out: List[AppRecord] = []
        for lib in libraries:
            steamapps = lib / "steamapps"
            if not steamapps.is_dir():
                continue
            for manifest in steamapps.glob("appmanifest_*.acf"):
                try:
                    text = manifest.read_text(encoding="utf-8", errors="ignore")
                    name_m = re.search(r'"name"\s+"([^"]+)"', text)
                    appid_m = re.search(r'"appid"\s+"([^"]+)"', text)
                    if name_m and appid_m:
                        out.append(AppRecord(name=name_m.group(1), target=f"steam://rungameid/{appid_m.group(1)}", source="Steam", installed=True, package_id=appid_m.group(1)))
                except Exception:
                    pass
        return out

    def _epic_candidates(self) -> List[AppRecord]:
        if os.name != "nt":
            return []
        root = Path(os.getenv("PROGRAMDATA", r"C:\ProgramData")) / "Epic/EpicGamesLauncher/Data/Manifests"
        if not root.is_dir():
            return []
        out: List[AppRecord] = []
        for item in root.glob("*.item"):
            try:
                data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
                name = str(data.get("DisplayName") or "").strip()
                app_name = str(data.get("AppName") or data.get("CatalogItemId") or "").strip()
                install = str(data.get("InstallLocation") or "").strip()
                launch_exe = str(data.get("LaunchExecutable") or "").strip()
                target = str(Path(install) / launch_exe) if install and launch_exe else ""
                if target and not Path(target).is_file():
                    target = ""
                if not target and app_name:
                    target = f"com.epicgames.launcher://apps/{app_name}?action=launch&silent=true"
                if name and target:
                    out.append(AppRecord(name=name, target=target, source="Epic", installed=True, package_id=app_name))
            except Exception:
                pass
        return out

    def rebuild_installed_index(self, extra_candidates: Optional[Iterable[Any]] = None) -> int:
        found: List[Any] = []
        if extra_candidates:
            found.extend(list(extra_candidates))
        found.extend(self._registry_candidates())
        found.extend(self._startapps_candidates())
        found.extend(self._shortcut_candidates())
        found.extend(self._portable_candidates())
        found.extend(self._steam_candidates())
        found.extend(self._epic_candidates())
        self.ingest_candidates(found, source_default="Legacy", save=True)
        self._last_rebuild = time.time()
        self._log("info", f"Indice V7 atualizado: {len(self._index)} apps locais")
        return len(self._index)

    @staticmethod
    def _parse_winget_search(stdout: str) -> List[AppRecord]:
        lines = [line.rstrip() for line in str(stdout or "").splitlines()]
        # Remove progress spinners/controle ANSI.
        lines = [re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line) for line in lines]
        start = None
        for i, line in enumerate(lines):
            if re.match(r"^\s*-{3,}", line):
                start = i + 1
                break
        if start is None:
            return []
        out = []
        for line in lines[start:]:
            if not line.strip() or line.lstrip().startswith("-"):
                continue
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) < 2:
                continue
            name, package_id = parts[0].strip(), parts[1].strip()
            if not name or not package_id or package_id.lower() in {"id", "identificador"}:
                continue
            out.append(AppRecord(name=name, target="", source="winget-global", installed=False, package_id=package_id))
        return out

    def build_global_catalog(self, timeout: float = 300.0) -> int:
        """Materializa o catalogo disponivel do winget em JSON local.

        Nao roda no caminho critico de abrir aplicativos. Pode ser disparado em
        thread de background. O resultado e apenas conhecimento global.
        """
        if os.name != "nt" or not shutil.which("winget"):
            return len(self._global)
        cmd = [
            "winget", "search", "--query", "",
            "--accept-source-agreements", "--disable-interactivity",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", timeout=max(30.0, float(timeout)))
            records = self._parse_winget_search(proc.stdout)
            if not records:
                self._log("warning", "winget nao retornou catalogo global parseavel")
                return len(self._global)
            unique: Dict[str, AppRecord] = {}
            for rec in records:
                key = (rec.package_id or compact_name(rec.name)).lower()
                unique[key] = rec
            with self._lock:
                self._global = list(unique.values())
                self._save_global()
            self._log("info", f"Catalogo global winget: {len(self._global)} pacotes")
            return len(self._global)
        except Exception as exc:
            self._log("warning", f"Falha ao atualizar catalogo winget: {exc}")
            return len(self._global)

    def ensure_global_catalog_background(self, max_age_days: int = 7):
        if os.name != "nt" or not shutil.which("winget"):
            return False
        try:
            fresh = self.global_path.exists() and (time.time() - self.global_path.stat().st_mtime) < max_age_days * 86400
        except Exception:
            fresh = False
        if fresh:
            return False
        with self._lock:
            if self._catalog_thread and self._catalog_thread.is_alive():
                return False
            self._catalog_thread = threading.Thread(target=self.build_global_catalog, name="JARVIS-AppCatalog", daemon=True)
            self._catalog_thread.start()
            return True

    def global_hints(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        # Global catalog is knowledge only and must NEVER add seconds to the
        # critical path of "abre X". Cheap lexical prefilter first; expensive
        # SequenceMatcher scoring is capped to a small candidate pool.
        q = normalize_name(query)
        if not q:
            return []
        # The resolver is intentionally created with load_global=False in the
        # critical path. Do not materialize ~14k global records just because a
        # local app name was not found; background/catalog tools may load them.
        if not self._global_loaded:
            return []
        q_tokens = {t for t in q.split() if len(t) >= 2}
        qc = compact_name(q)
        with self._lock:
            global_records = list(self._global)

        shortlist = []
        for rec in global_records:
            name = normalize_name(rec.name)
            package = normalize_name(rec.package_id)
            hay = f"{name} {package}".strip()
            hc = compact_name(hay)
            tokens = set(hay.split())
            if (
                (qc and len(qc) >= 4 and (qc in hc or hc.startswith(qc)))
                or (q_tokens and bool(q_tokens & tokens))
            ):
                shortlist.append(rec)
                if len(shortlist) >= 600:
                    break
        if not shortlist:
            return []

        ranked = [self._score_record(query, rec) for rec in shortlist]
        ranked.sort(key=lambda r: r.score, reverse=True)
        return [r.to_dict() for r in ranked[:max(1, limit)] if r.score >= 0.55]

    def installed_records(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in self._index if r.installed]

    def status(self) -> Dict[str, Any]:
        with self._lock:
            local = len([r for r in self._index if r.installed])
            return {
                "version": CATALOG_VERSION,
                "local_apps": local,
                "global_apps": len(self._global) if self._global_loaded else self._global_count_hint,
                "global_loaded": self._global_loaded,
                "personal_aliases": len(self._aliases),
                "min_confidence": self.min_confidence,
                "min_margin": self.min_margin,
                "index_path": str(self.index_path),
                "global_path": str(self.global_path),
                "global_refresh_running": bool(self._catalog_thread and self._catalog_thread.is_alive()),
                "last_rebuild_epoch": self._last_rebuild,
            }


def load_voice_terms(project_dir: str, limit: int = 220) -> List[str]:
    """Carrega o vocabulário de voz sem reconstruir o App Resolver.

    O caminho antigo instanciava ``UniversalAppResolver`` a cada refresh de
    hotwords. Em uma instalação real com ~600 apps isso custa ~1-2 s e acabava
    entrando no caminho crítico do STT. Para voz precisamos só dos rótulos já
    persistidos em ``data/app_index.json`` + aliases/cache.

    A descoberta pesada continua sendo responsabilidade do prewarm/rebuild em
    background; esta função é deliberadamente leitura-only e O(n) em JSON.
    """
    root = Path(project_dir)
    cap = max(1, min(int(limit or 220), 500))
    values: List[str] = []

    def add(value: object) -> None:
        text = " ".join(str(value or "").split()).strip()
        if 1 < len(text) <= 96:
            values.append(text)

    try:
        path = root / "data" / "app_index.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        add(item.get("label"))
    except Exception:
        pass

    try:
        path = root / "data" / "app_aliases.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for alias, item in payload.items():
                    add(alias)
                    if isinstance(item, dict):
                        add(item.get("display_name"))
    except Exception:
        pass

    try:
        path = root / "app_cache.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for alias in payload:
                    if not str(alias).startswith("_"):
                        add(alias)
    except Exception:
        pass

    # Alguns nomes importantes devem existir mesmo antes do primeiro rebuild.
    for canonical, aliases in COMMON_APP_ALIASES.items():
        add(canonical)
        for alias in aliases[:3]:
            add(alias)

    seen = set()
    result: List[str] = []
    for value in values:
        key = normalize_name(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= cap:
            break
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="JARVIS Universal App Resolver")
    parser.add_argument("--project", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--rebuild", action="store_true", help="reconstroi indice local")
    parser.add_argument("--global-catalog", action="store_true", help="materializa catalogo global do winget")
    parser.add_argument("--query", default="", help="testa resolucao de um app")
    args = parser.parse_args()
    resolver = UniversalAppResolver(args.project)
    if args.rebuild:
        print("local_apps", resolver.rebuild_installed_index())
    if args.global_catalog:
        print("global_apps", resolver.build_global_catalog())
    if args.query:
        result = resolver.resolve(args.query)
        print(json.dumps({
            "safe": result.safe,
            "reason": result.reason,
            "confidence": result.confidence,
            "margin": result.margin,
            "selected": result.selected_dict(),
            "candidates": [x.to_dict() for x in result.candidates[:5]],
        }, ensure_ascii=False, indent=2))
    if not (args.rebuild or args.global_catalog or args.query):
        print(json.dumps(resolver.status(), ensure_ascii=False, indent=2))
