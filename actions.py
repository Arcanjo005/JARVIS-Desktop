"""
J.A.R.V.I.S. Mark 13 - System Actions Module
Módulo responsável por todas as ações do sistema Windows, APIs web e funcionalidades de hardware.
"""

# ==================== BIBLIOTECAS PADRÃO ====================
import os
import subprocess
import webbrowser
import glob
import shutil
import time
import random
import string
import re
import threading
import json
import ntpath
import unicodedata
import ctypes
import difflib
import importlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any

# ==================== BIBLIOTECAS DE TERCEIROS ====================
import psutil

class _LazyModule:
    """Proxy pequeno para dependencias usadas apenas por acoes especificas."""
    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module = None
        self._lock = threading.Lock()

    def _load(self):
        if self._module is None:
            with self._lock:
                if self._module is None:
                    self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name):
        return getattr(self._load(), name)

# Build 15: GUI nao deve esperar automacao de mouse, HTTP, brilho ou parser
# HTML para aparecer. Cada biblioteca entra somente na primeira acao que usa.
pyautogui = _LazyModule("pyautogui")
requests = _LazyModule("requests")
sbc = _LazyModule("screen_brightness_control")

def BeautifulSoup(*args, **kwargs):
    from bs4 import BeautifulSoup as _BeautifulSoup
    return _BeautifulSoup(*args, **kwargs)

# ==================== MÓDULOS PRÓPRIOS ====================
from config import Config

try:
    from universal_app_resolver import UniversalAppResolver
except Exception:
    UniversalAppResolver = None

try:
    from action_verifier import ActionVerifier
except Exception:
    ActionVerifier = None

try:
    from jarvis_reliability import ReliabilityTracker
except Exception:
    ReliabilityTracker = None

try:
    import winreg
except Exception:
    winreg = None
# Build 15: Pycaw/WMI sao carregados somente quando uma acao realmente
# precisa deles. Importar COM/WMI no boot pode custar centenas de ms no Windows.
AUDIO_AVAILABLE = False
WMI_AVAILABLE = False
wmi = None

class SystemActions:
    """Classe responsável por todas as ações do sistema J.A.R.V.I.S. Mark 13.
    
    Esta classe centraliza todas as funcionalidades do sistema, incluindo:
    - Controle de aplicativos Windows
    - APIs web (clima, cotações, notícias)
    - Hardware (volume, brilho, screenshots)
    - Produtividade (Pomodoro, lembretes)
    - Sistema (processos, limpeza)
    
    Attributes:
        logger: Instância do logger para registrar eventos
        audio_available (bool): Indica se controle de áudio está disponível
        wmi_available (bool): Indica se WMI está disponível
        volume: Controle de volume do sistema (se disponível)
        reminders (list): Lista de lembretes ativos
    """
    
    def __init__(self, logger):
        """Inicializa a classe SystemActions.
        
        Args:
            logger: Instância do logger para registrar eventos do sistema
            
        Raises:
            Exception: Caso ocorra erro na inicialização do controle de áudio
        """
        self.logger = logger
        self.audio_available = AUDIO_AVAILABLE
        self.wmi_available = WMI_AVAILABLE
        self.last_known_volume = 50
        self._audio_last_init_attempt = 0.0
        self._audio_last_error = ""
        self._audio_retry_interval = 300.0
        self._audio_warning_logged = False
        
        # Core Audio agora e lazy: o primeiro comando de volume faz o bind.
        # Isso evita COM no caminho critico de inicializacao.
        
        # Inicializa lista de lembretes
        self.reminders = []

        # Cache local de aplicativos encontrados.
        # Isso evita procurar o disco inteiro toda vez que um app ja foi localizado.
        self.app_cache_path = os.path.join(os.getcwd(), "app_cache.json")
        self.app_cache = self._load_app_cache()

        # Dados avançados do JARVIS: aliases ensinados e índice de apps.
        self.data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.app_aliases_path = os.path.join(self.data_dir, "app_aliases.json")
        self.app_index_path = os.path.join(self.data_dir, "app_index.json")
        self.app_aliases = self._load_json_dict(self.app_aliases_path)
        self.app_index = self._load_json_list(self.app_index_path)
        self._last_app_resolution = {}
        self.app_resolver = None
        self.action_verifier = None
        self.reliability = None

        # JARVIS V7: camada unificada de resolução/validação. O índice legado
        # continua existindo para compatibilidade, mas deixa de ser a fonte de
        # verdade para decisões fuzzy.
        if UniversalAppResolver is not None:
            try:
                self.app_resolver = UniversalAppResolver(os.getcwd(), logger=self.logger, load_global=False)
                self.app_resolver.ingest_candidates(self.app_index, source_default="Legacy", save=False)
                # V8: o primeiro "abre ..." nao deve pagar o custo de montar
                # centenas de formas/aliases. Preaquece em background sem travar a UI.
                threading.Thread(
                    target=self.app_resolver.prewarm_local_forms,
                    name="zero-app-prewarm",
                    daemon=True,
                ).start()
                if str(os.getenv("ZERO_GLOBAL_APP_CATALOG", "1")).strip().lower() not in {"0", "false", "off", "no"}:
                    self.app_resolver.ensure_global_catalog_background(max_age_days=7)
            except Exception as exc:
                self.app_resolver = None
                if self.logger:
                    self.logger.warning(f"App Resolver V7 indisponível: {exc}", "APP-V7")

        if ActionVerifier is not None:
            try:
                self.action_verifier = ActionVerifier(logger=self.logger)
            except Exception:
                self.action_verifier = None

        if ReliabilityTracker is not None:
            try:
                self.reliability = ReliabilityTracker(os.getcwd())
            except Exception:
                self.reliability = None
        self._last_music_choice = ""
        
        if self.logger:
            self.logger.info("SystemActions inicializado", "ACTIONS")
            self.logger.system("Módulo de ações do sistema carregado", "INIT")
    
    def _init_audio_control(self, force: bool = False):
        """Inicializa Core Audio usando a API atual do Pycaw."""
        now = time.monotonic()

        if (
            not force
            and self._audio_last_init_attempt
            and now - self._audio_last_init_attempt < self._audio_retry_interval
            and (not self.audio_available or not hasattr(self, "volume"))
        ):
            return

        if self.audio_available and hasattr(self, "volume") and not force:
            return

        self._audio_last_init_attempt = now

        try:
            from pycaw.pycaw import AudioUtilities

            device = AudioUtilities.GetSpeakers()
            self.audio_device = device
            self.volume = device.EndpointVolume
            self.audio_available = True
            self._audio_last_error = ""
            self._audio_warning_logged = False

            try:
                # API atual também expõe volume_percent em escala 0-100.
                self.last_known_volume = int(round(float(device.volume_percent)))
            except Exception:
                try:
                    self.last_known_volume = int(
                        round(self.volume.GetMasterVolumeLevelScalar() * 100)
                    )
                except Exception:
                    pass

            if self.logger:
                self.logger.info(
                    "Controle de áudio inicializado com Pycaw EndpointVolume",
                    "ACTIONS"
                )

        except ImportError:
            self.audio_available = False
            self._audio_last_error = "pycaw indisponível"
            if self.logger and not self._audio_warning_logged:
                self._audio_warning_logged = True
                self.logger.warning(
                    "pycaw não disponível; usando fallback de volume.",
                    "ACTIONS"
                )

        except Exception as e:
            self.audio_available = False
            self._audio_last_error = str(e)
            if self.logger and not self._audio_warning_logged:
                self._audio_warning_logged = True
                self.logger.warning(
                    f"Core Audio indisponível; usando fallback: {e}",
                    "ACTIONS"
                )

    def _normalize_app_name(self, value: str) -> str:
        """Normaliza nomes para comparar aplicativos/processos."""
        value = (value or "").lower().strip()
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())

    def _is_opera_request(self, value: str) -> bool:
        """Opera/Opera GX usam executavel real; aliases AppsFolder podem abrir Explorer."""
        key = self._normalize_app_name(value)
        return key in {"opera", "opera gx", "opera g x", "operar", "opera gamer"}

    def _purge_broken_opera_shell_cache(self) -> bool:
        """Remove apenas aliases AppsFolder de Opera; preserva qualquer executavel/atalho valido."""
        changed = False
        for alias in ("opera", "opera gx", "opera g x", "operar", "opera gamer"):
            key = self._normalize_app_name(alias)
            target = str(self.app_cache.get(key) or "").strip()
            if target.lower().startswith("shell:appsfolder\\"):
                self.app_cache.pop(key, None)
                changed = True
        if changed:
            self._save_app_cache()
            if self.logger:
                self.logger.warning(
                    "Cache AppsFolder antigo do Opera removido; o executavel real sera redetectado.",
                    "APP",
                )
        return changed

    def _load_app_cache(self) -> Dict[str, str]:
        """Carrega apenas caches no formato simples query -> caminho."""
        try:
            if os.path.exists(self.app_cache_path):
                with open(self.app_cache_path, "r", encoding="utf-8") as file:
                    data = json.load(file)

                # A versão experimental de busca usava {"_version": 2, "apps": ...}.
                # Não reutilizamos esse cache porque ele pode conter associações erradas.
                if isinstance(data, dict) and "_version" in data:
                    # Cache experimental antigo é simplesmente ignorado.
                    # Não criamos cópias paralelas dentro da instalação.
                    return {}

                if isinstance(data, dict):
                    clean = {}
                    for key, value in data.items():
                        if isinstance(value, str) and value:
                            clean[key] = value
                    return clean

        except Exception as e:
            if self.logger:
                self.logger.warning(
                    f"Nao foi possivel carregar app_cache.json: {e}",
                    "APP"
                )

        return {}

    def _save_app_cache(self):
        """Salva o cache de aplicativos sem interromper o JARVIS em caso de erro."""
        try:
            with open(self.app_cache_path, "w", encoding="utf-8") as file:
                json.dump(self.app_cache, file, ensure_ascii=False, indent=2)
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Nao foi possivel salvar app_cache.json: {e}", "APP")

    def _cache_app(self, app_name: str, path: str):
        """Memoriza um executavel/atalho encontrado."""
        key = self._normalize_app_name(app_name)
        if key and path:
            if self.app_cache.get(key) == path:
                return
            self.app_cache[key] = path
            self._save_app_cache()

    def _open_cached_app(self, app_name: str) -> Optional[str]:
        """Fast path para um alvo que ja foi resolvido anteriormente.

        O cache so e preenchido depois de uma resolucao valida. Portanto nao faz
        sentido refazer fuzzy matching a cada "abre Opera". Disparamos o alvo
        imediatamente e deixamos a camada superior verificar a janela.
        """
        key = self._normalize_app_name(app_name)
        cached = str(self.app_cache.get(key) or "").strip()
        if not cached:
            return None

        try:
            launchable_uri = cached.startswith(("shell:AppsFolder\\", "ms-", "http://", "https://"))
            launchable_file = os.path.exists(cached)
            if not (launchable_uri or launchable_file):
                self.app_cache.pop(key, None)
                self._save_app_cache()
                return None
            self._launch_app_target(cached)
            if self.logger:
                self.logger.info(f"Aplicativo aberto pelo fast cache: {cached}", "ACTIONS")
            return f"Solicitei a abertura de {app_name}."
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Falha no fast cache de {app_name}: {e}", "APP")
            self.app_cache.pop(key, None)
            self._save_app_cache()
            return None

    def close_application(self, app_name: str) -> str:
        """Fecha somente processos correspondentes ao aplicativo solicitado."""
        requested = self._normalize_app_name(app_name)
        if not requested:
            return "Nao identifiquei qual aplicativo devo fechar."

        resolver_match = None
        resolver_ambiguous = False
        if self.app_resolver:
            try:
                resolution = self.app_resolver.resolve(app_name, limit=8)
                resolver_ambiguous = bool(
                    not resolution.safe
                    and resolution.candidates
                    and float(resolution.confidence or 0.0) >= 0.72
                )
                if resolution.safe and resolution.selected:
                    resolver_match = resolution.selected_dict() or {}
                elif resolver_ambiguous:
                    names = []
                    for item in resolution.candidates[:4]:
                        label = item.record.name
                        if label not in names:
                            names.append(label)
                    return (
                        f"'{app_name}' ficou ambiguo entre {', '.join(names[:3])}. "
                        "Diga qual deles você quer fechar."
                    )
            except Exception:
                resolver_match = None

        aliases = {
            "photoshop": ["photoshop"],
            "illustrator": ["illustrator"],
            "corel": ["coreldrw", "corel draw", "coreldraw"],
            "corel draw": ["coreldrw", "corel draw", "coreldraw"],
            "obs": ["obs64", "obs32", "obs studio"],
            "obs studio": ["obs64", "obs32", "obs studio"],
            "opera": ["opera"],
            "opera gx": ["opera"],
            "revo": ["revouninpro", "revouninstaller", "revo uninstaller"],
            "revo uninstaller": ["revouninpro", "revouninstaller", "revo uninstaller"],
            "geek": ["geek"],
        }

        wanted = {requested}
        for key, values in aliases.items():
            if requested == key or requested in key or key in requested:
                wanted.update(self._normalize_app_name(v) for v in values)

        if resolver_match:
            label = str(resolver_match.get("name") or resolver_match.get("label") or "")
            target = str(resolver_match.get("target") or "").strip('"')
            if label:
                wanted.add(self._normalize_app_name(label))
            if target and not target.startswith(("shell:", "steam:", "com.epicgames")):
                stem = ntpath.splitext(ntpath.basename(target))[0]
                if stem:
                    wanted.add(self._normalize_app_name(stem))

        # Se o app ja foi encontrado antes, usa o nome do executavel como pista adicional.
        cached = self.app_cache.get(requested)
        if cached:
            wanted.add(self._normalize_app_name(os.path.splitext(os.path.basename(cached))[0]))

        protected = {
            "system", "registry", "smss", "csrss", "wininit", "services",
            "lsass", "winlogon", "svchost", "dwm", "explorer"
        }

        matches = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                if int(proc.info.get("pid") or 0) == os.getpid():
                    continue
                proc_name = self._normalize_app_name(os.path.splitext(proc.info.get("name") or "")[0])
                exe = proc.info.get("exe") or ""
                exe_text = self._normalize_app_name(exe)

                if not proc_name or proc_name in protected:
                    continue

                score = 0
                for target in wanted:
                    if not target:
                        continue
                    if proc_name == target:
                        score = max(score, 100)
                    elif resolver_match and (target in proc_name or proc_name in target):
                        score = max(score, 85)
                    elif resolver_match and target in exe_text:
                        score = max(score, 75)

                if score >= 75:
                    matches.append((score, proc))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not matches:
            return f"Nao encontrei {app_name} em execucao."

        # Fecha apenas os processos que realmente combinaram com o pedido.
        matches.sort(key=lambda item: item[0], reverse=True)
        processes = [proc for _, proc in matches]
        closed = 0

        for proc in processes:
            try:
                proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        gone, alive = psutil.wait_procs(processes, timeout=3)
        closed += len(gone)

        # Fallback forcado somente para os processos que nao responderam ao terminate.
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if alive:
            killed_gone, killed_alive = psutil.wait_procs(alive, timeout=2)
            closed += len(killed_gone)
        else:
            killed_alive = []

        if closed and not killed_alive:
            self.logger.info(f"Aplicativo fechado: {app_name} ({closed} processo(s))", "ACTIONS")
            if self.reliability:
                self.reliability.count("app_close_verified")
            return f"{app_name.title()} fechado e verificado."

        if closed:
            if self.reliability:
                self.reliability.count("app_close_partial")
            return (
                f"Fechei {closed} processo(s) de {app_name}, mas ainda ha "
                f"{len(killed_alive)} processo(s) que nao consegui confirmar como encerrados."
            )

        return f"Encontrei {app_name}, mas o Windows nao permitiu encerra-lo."

    def _load_json_dict(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _load_json_list(self, path: str) -> List[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_json(self, path: str, data: Any):
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            self.logger.warning(f"Falha ao salvar {path}: {e}", "APP")

    def learn_app_alias(self, alias: str, target: str, display_name: str = "") -> str:
        alias_key = self._normalize_app_name(alias)
        target = os.path.expandvars(os.path.expanduser((target or "").strip().strip('"')))
        if not alias_key:
            return "Não entendi o nome que devo aprender."
        if not target:
            return "Nenhum aplicativo foi selecionado."
        if not (os.path.exists(target) or target.startswith("shell:AppsFolder\\")):
            return f"O caminho selecionado não existe: {target}"
        self.app_aliases[alias_key] = {
            "target": target,
            "display_name": display_name or alias.strip(),
            "learned_at": datetime.now().isoformat(timespec="seconds")
        }
        self._save_json(self.app_aliases_path, self.app_aliases)
        self._cache_app(alias, target)
        if self.app_resolver:
            try:
                self.app_resolver.learn_alias(alias, target, display_name or alias.strip())
            except Exception as exc:
                if self.logger:
                    self.logger.warning(f"Alias V7 não sincronizado: {exc}", "APP-V7")
        return f"Aprendi. Quando você disser '{alias}', vou abrir esse aplicativo."

    def list_app_aliases(self):
        """Retorna aliases ensinados em formato amigável para a interface."""
        result = []

        for alias, data in sorted(self.app_aliases.items()):
            if isinstance(data, dict):
                target = str(data.get("target") or "")
                display_name = str(data.get("display_name") or alias)
                learned_at = str(data.get("learned_at") or "")
            else:
                target = str(data or "")
                display_name = alias
                learned_at = ""

            result.append(
                {
                    "alias": alias,
                    "display_name": display_name,
                    "target": target,
                    "learned_at": learned_at,
                }
            )

        return result

    def forget_app_alias(self, alias: str) -> str:
        key = self._normalize_app_name(alias)
        removed = self.app_aliases.pop(key, None)
        self.app_cache.pop(key, None)
        self._save_json(self.app_aliases_path, self.app_aliases)
        self._save_app_cache()
        if self.app_resolver:
            try:
                self.app_resolver.forget_alias(alias)
            except Exception:
                pass
        if removed:
            return f"Esqueci a associação do aplicativo '{alias}'."
        return f"Eu não tinha uma associação ensinada para '{alias}'."

    def _app_identity_score(self, query: str, label: str, target: str = "") -> float:
        q = self._normalize_app_name(query)
        label_n = self._normalize_app_name(label)
        exe_n = self._normalize_app_name(os.path.splitext(os.path.basename(target or ""))[0])
        parent_n = self._normalize_app_name(os.path.basename(os.path.dirname(target or ""))) if target else ""
        names = [n for n in (label_n, exe_n, parent_n) if n]
        if not q or not names:
            return 0.0
        best = 0.0
        q_tokens = set(q.split())
        q_compact = q.replace(" ", "")
        for n in names:
            score = 0.0
            n_compact = n.replace(" ", "")
            if q == n:
                score += 130
            elif q_compact and q_compact == n_compact:
                # Microsoft Store costuma expor "ChatGPT" enquanto o usuário
                # naturalmente diz "chat gpt". Tratamos como match exato.
                score += 125
            elif n.startswith(q + " ") or q.startswith(n + " "):
                score += 95
            elif q in n:
                score += 85
            elif n in q and len(n) >= 4:
                score += 65
            n_tokens = set(n.split())
            if q_tokens:
                overlap = len(q_tokens & n_tokens) / max(1, len(q_tokens))
                score += overlap * 55
            ratio = difflib.SequenceMatcher(None, q, n).ratio()
            # Uma palavra só não pode abrir app por fuzzy fraco.
            if len(q_tokens) >= 2:
                score += ratio * 35
            elif ratio >= 0.92:
                score += ratio * 30
            low = f"{n} {exe_n}"
            for bad in ("uninstall", "uninstaller", "update", "updater", "helper", "setup", "installer", "crash", "service"):
                if bad in low:
                    score -= 50
            best = max(best, score)
        return best

    def _is_safe_app_match(self, query: str, label: str, target: str, score: float) -> bool:
        q = self._normalize_app_name(query)
        if not q:
            return False
        identities = [
            self._normalize_app_name(label),
            self._normalize_app_name(os.path.splitext(os.path.basename(target or ""))[0]),
            self._normalize_app_name(os.path.basename(os.path.dirname(target or ""))) if target else "",
        ]
        identities = [x for x in identities if x]
        q_compact = q.replace(" ", "")
        compact_identities = [x.replace(" ", "") for x in identities]

        if q_compact and any(q_compact == x for x in compact_identities):
            return score >= 75

        # Para uma palavra como Comercial: exige match literal forte.
        if len(q.split()) == 1:
            return score >= 85 and any(q == x or q in x or x in q for x in identities)
        return score >= 75

    def _registry_app_candidates(self) -> List[Dict[str, str]]:
        results = []
        if winreg is None:
            return results
        app_path_roots = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        ]
        for hive, key_path in app_path_roots:
            try:
                with winreg.OpenKey(hive, key_path) as root:
                    count = winreg.QueryInfoKey(root)[0]
                    for i in range(count):
                        try:
                            child = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, child) as key:
                                target = winreg.QueryValueEx(key, None)[0]
                            target = os.path.expandvars(str(target).strip('"'))
                            if os.path.isfile(target):
                                results.append({"label": os.path.splitext(child)[0], "target": target, "source": "App Paths"})
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
                    count = winreg.QueryInfoKey(root)[0]
                    for i in range(count):
                        try:
                            child = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, child) as key:
                                def val(name):
                                    try:
                                        return str(winreg.QueryValueEx(key, name)[0])
                                    except Exception:
                                        return ""
                                display = val("DisplayName")
                                icon = val("DisplayIcon").split(",")[0].strip('"')
                                location = val("InstallLocation").strip('"')
                            target = ""
                            if icon and os.path.isfile(os.path.expandvars(icon)):
                                target = os.path.expandvars(icon)
                            elif location and os.path.isdir(os.path.expandvars(location)):
                                folder = os.path.expandvars(location)
                                # Escolhe exe cujo nome mais combina com DisplayName.
                                exes = []
                                try:
                                    for name in os.listdir(folder):
                                        p = os.path.join(folder, name)
                                        if os.path.isfile(p) and name.lower().endswith('.exe'):
                                            exes.append(p)
                                except Exception:
                                    pass
                                if exes:
                                    target = max(exes, key=lambda p: self._app_identity_score(display, os.path.basename(p), p))
                            if display and target:
                                results.append({"label": display, "target": target, "source": "Registro"})
                        except Exception:
                            pass
            except Exception:
                pass
        return results

    def _shortcut_candidates(self) -> List[Dict[str, str]]:
        roots = [
            os.path.join(os.getenv("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.getenv("PROGRAMDATA", r"C:\ProgramData"), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.getenv("USERPROFILE", ""), "Desktop"),
            os.path.join(os.getenv("PUBLIC", r"C:\Users\Public"), "Desktop"),
        ]
        user = os.getenv("USERPROFILE", "")
        if user and os.path.isdir(user):
            try:
                for name in os.listdir(user):
                    if name.lower().startswith("onedrive"):
                        roots.append(os.path.join(user, name, "Desktop"))
            except Exception:
                pass
        results = []
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            for current, dirs, files in os.walk(root):
                if len(Path(current).parts) - len(Path(root).parts) > 7:
                    dirs[:] = []
                    continue
                for name in files:
                    if name.lower().endswith((".lnk", ".url", ".exe", ".bat", ".cmd")):
                        results.append({
                            "label": os.path.splitext(name)[0],
                            "target": os.path.join(current, name),
                            "source": "Atalho"
                        })
        return results

    def _start_apps_candidates(self) -> List[Dict[str, str]]:
        results = []
        try:
            ps = "Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }"
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=10, errors="ignore"
            )
            for line in proc.stdout.splitlines():
                if "|" not in line:
                    continue
                name, app_id = line.split("|", 1)
                if name.strip() and app_id.strip():
                    results.append({
                        "label": name.strip(),
                        "target": "shell:AppsFolder\\" + app_id.strip(),
                        "source": "StartApps"
                    })
        except Exception:
            pass
        return results

    def _filesystem_roots(self) -> List[str]:
        roots = []
        for p in (
            os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"),
            os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs"),
            os.getenv("LOCALAPPDATA"), os.getenv("APPDATA"),
        ):
            if p and os.path.isdir(p) and p not in roots:
                roots.append(p)
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if not os.path.exists(drive):
                continue
            for folder in ("Program Files", "Program Files (x86)", "Programs", "Apps", "Aplicativos", "Sistemas", "Software"):
                p = os.path.join(drive, folder)
                if os.path.isdir(p) and p not in roots:
                    roots.append(p)
            # Também considera pastas não-sistema diretamente na raiz, útil para sistemas comerciais legados.
            try:
                for name in os.listdir(drive):
                    p = os.path.join(drive, name)
                    if not os.path.isdir(p):
                        continue
                    if name.lower() in {"windows", "users", "programdata", "$recycle.bin", "system volume information", "recovery"}:
                        continue
                    if p not in roots:
                        roots.append(p)
            except Exception:
                pass
        return roots

    def _filesystem_candidates_for_query(self, query: str, time_budget: float = 10.0) -> List[Dict[str, str]]:
        start = time.time()
        q = self._normalize_app_name(query)
        results = []
        for root in self._filesystem_roots():
            if time.time() - start > time_budget:
                break
            try:
                for current, dirs, files in os.walk(root):
                    if time.time() - start > time_budget:
                        break
                    depth = len(Path(current).parts) - len(Path(root).parts)
                    if depth > 5:
                        dirs[:] = []
                        continue
                    dirs[:] = [d for d in dirs if d.lower() not in {"node_modules", ".git", "cache", "temp", "tmp", "windowsapps", "winsxs"}]
                    parent = os.path.basename(current)
                    parent_match = q and q in self._normalize_app_name(parent)
                    for name in files:
                        if not name.lower().endswith((".exe", ".lnk", ".bat", ".cmd")):
                            continue
                        label = os.path.splitext(name)[0]
                        label_n = self._normalize_app_name(label)
                        if q in label_n or label_n in q or parent_match:
                            results.append({"label": label, "target": os.path.join(current, name), "source": "Disco"})
                            if len(results) >= 80:
                                return results
            except (PermissionError, OSError):
                pass
        return results

    def _collect_app_candidates(self, query: str, deep: bool = True) -> List[Dict[str, Any]]:
        key = self._normalize_app_name(query)
        candidates = []
        alias = self.app_aliases.get(key)
        if isinstance(alias, dict) and alias.get("target"):
            candidates.append({"label": alias.get("display_name") or query, "target": alias["target"], "source": "Ensinado", "bonus": 300})
        cached = self.app_cache.get(key)
        if cached and os.path.exists(cached):
            # Cache antigo nunca recebe o nome digitado como identidade.
            # Isso evita repetir associações erradas como comercial -> OBS.
            cache_label = os.path.splitext(os.path.basename(cached))[0]
            candidates.append({"label": cache_label, "target": cached, "source": "Cache", "bonus": 25})
        candidates.extend(self.app_index)
        candidates.extend(self._registry_app_candidates())
        candidates.extend(self._start_apps_candidates())
        candidates.extend(self._shortcut_candidates())
        if deep:
            candidates.extend(self._filesystem_candidates_for_query(query))
        unique = {}
        ranked = []
        for item in candidates:
            label = str(item.get("label") or "").strip()
            target = str(item.get("target") or "").strip()
            if not label or not target:
                continue
            key2 = target.lower()
            score = self._app_identity_score(query, label, target) + float(item.get("bonus") or 0)
            if key2 not in unique or score > unique[key2][0]:
                unique[key2] = (score, label, target, item.get("source") or "")
        for score, label, target, source in unique.values():
            ranked.append({"score": score, "label": label, "target": target, "source": source})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked

    def find_application_candidates(self, app_name: str, limit: int = 8) -> List[Dict[str, Any]]:
        if self.app_resolver:
            try:
                ranked = self.app_resolver.find_candidates(app_name, limit=max(1, limit))
                # O restante do código legado espera score em escala 0-100.
                for item in ranked:
                    item["score"] = round(float(item.get("score", 0.0)) * 100.0, 2)
                return ranked
            except Exception as exc:
                if self.logger:
                    self.logger.warning(f"Resolver V7 falhou; usando legado: {exc}", "APP-V7")
        # Caminho interativo nunca varre Program Files/discos. O índice local é
        # reconstruído/preaquecido em background; busca profunda pertence ao
        # reindex, não ao comando "abre X".
        return self._collect_app_candidates(app_name, deep=False)[:max(1, limit)]

    def resolve_application(self, app_name: str) -> Optional[Dict[str, Any]]:
        if self.app_resolver:
            try:
                result = self.app_resolver.resolve(app_name, limit=8)
                self._last_app_resolution = {
                    "query": app_name,
                    "safe": bool(result.safe),
                    "confidence": round(float(result.confidence), 4),
                    "margin": round(float(result.margin), 4),
                    "reason": result.reason,
                    "candidates": [c.to_dict() for c in result.candidates[:4]],
                }
                if result.safe and result.selected:
                    item = result.selected_dict() or {}
                    item["score"] = round(float(result.confidence) * 100.0, 2)
                    return item
                return None
            except Exception as exc:
                if self.logger:
                    self.logger.warning(f"Resolver V7 falhou; usando legado: {exc}", "APP-V7")
        # Fallback legado também permanece bounded. Uma falha do resolver V8
        # não pode transformar um comando de voz em dezenas de segundos de I/O.
        ranked = self._collect_app_candidates(app_name, deep=False)
        for item in ranked:
            if self._is_safe_app_match(app_name, item["label"], item["target"], item["score"]):
                return item
        return None

    def rebuild_app_index(self) -> str:
        """Reconstrói um índice leve usando Registro, Start Apps e atalhos."""
        try:
            if self.app_resolver:
                count = self.app_resolver.rebuild_installed_index(extra_candidates=self.app_index)
                # Mantém o JSON antigo atualizado para módulos/versões legadas.
                self.app_index = [
                    {
                        "label": row.get("name") or row.get("label") or "",
                        "target": row.get("target") or "",
                        "source": row.get("source") or "V7",
                    }
                    for row in self.app_resolver.installed_records()
                    if row.get("target")
                ]
                self._save_json(self.app_index_path, self.app_index)
                self.app_resolver.ensure_global_catalog_background(max_age_days=7)
                status = self.app_resolver.status()
                return (
                    f"Índice V7 atualizado com {count} aplicativos locais. "
                    f"Catálogo global conhecido: {status.get('global_apps', 0)} pacotes."
                )
            items = self._registry_app_candidates() + self._start_apps_candidates() + self._shortcut_candidates()
            unique = {}
            for item in items:
                target = item.get("target")
                if target:
                    unique[str(target).lower()] = item
            self.app_index = list(unique.values())
            self._save_json(self.app_index_path, self.app_index)
            return f"Índice de aplicativos atualizado com {len(self.app_index)} entradas."
        except Exception as e:
            return f"Não consegui reconstruir o índice de aplicativos: {e}"

    def _launch_app_target(self, target: str):
        """Abre executável, atalho ou AppX com fallback do Shell do Windows."""
        target = str(target or "").strip().strip('"')

        if target.startswith("shell:AppsFolder\\"):
            app_id = target.split("\\", 1)[1]
            subprocess.Popen(
                ["explorer.exe", f"shell:AppsFolder\\{app_id}"],
                shell=False
            )
            return

        if target.startswith(("ms-", "http://", "https://")):
            os.startfile(target)
            return

        if target.lower().endswith((".lnk", ".url", ".bat", ".cmd")):
            os.startfile(target)
            return

        if os.path.isfile(target):
            try:
                subprocess.Popen(
                    [target],
                    cwd=os.path.dirname(target) or None,
                    shell=False
                )
                return
            except OSError as exc:
                # WinError 193 costuma ocorrer em launchers/stubs que o Shell
                # consegue resolver melhor do que CreateProcess.
                if getattr(exc, "winerror", None) == 193:
                    os.startfile(target)
                    return
                raise

        os.startfile(target)

    def open_application(self, app_name: str) -> str:
        """Abre app somente quando há correspondência confiável; nunca abre outro app por fuzzy fraco."""
        app_name = (app_name or "").strip().rstrip(".?!,;:").strip()
        if not app_name:
            return "Qual aplicativo devo abrir?"

        # Remove artigos naturais: "abra o ChatGPT", "abra a calculadora".
        app_name = re.sub(r"^(?:o|a|um|uma)\s+", "", app_name, flags=re.I).strip()

        # Built-ins exatos continuam usando o mecanismo legado conhecido.
        normalized = self._normalize_app_name(app_name)
        builtins = {
            "bloco de notas": "notepad.exe", "notepad": "notepad.exe",
            "calculadora": "calc.exe", "calc": "calc.exe",
            "cmd": "cmd.exe", "prompt": "cmd.exe",
            "powershell": "powershell.exe", "explorer": "explorer.exe",
            "gerenciador de arquivos": "explorer.exe", "explorador de arquivos": "explorer.exe",
            "gerenciador de tarefas": "taskmgr.exe", "task manager": "taskmgr.exe",
            "paint": "mspaint.exe", "mspaint": "mspaint.exe",
            "configuracoes": "ms-settings:", "settings": "ms-settings:",
        }
        if normalized in builtins:
            return self._executar_comando_direto(builtins[normalized], app_name)

        # Hotfix 13.11.1: Opera GX e um app Win32. Em algumas instalacoes o
        # Get-StartApps devolve um AppID que `explorer shell:AppsFolder` nao
        # consegue iniciar e o Explorer cai em Documentos. Para Opera/Opera GX
        # nunca reutilizamos esse alias: redetectamos e abrimos o executavel/lnk
        # real, reparando o fast cache para as proximas chamadas.
        if self._is_opera_request(app_name):
            self._purge_broken_opera_shell_cache()
            opera_target = self._find_opera_gx()
            if opera_target:
                try:
                    self._launch_app_target(opera_target)
                    self._cache_app("Opera GX", opera_target)
                    self._cache_app("Opera", opera_target)
                    self._cache_app(app_name, opera_target)
                    if self.logger:
                        self.logger.info(
                            f"Opera GX aberto por alvo Win32 reparado: {opera_target}",
                            "ACTIONS",
                        )
                    if self.action_verifier:
                        try:
                            verification = self.action_verifier.verify_application_open(opera_target, timeout=1.6)
                            if verification.verified:
                                return "Opera GX aberto e verificado."
                        except Exception:
                            pass
                    return "Solicitei a abertura de Opera GX pelo executavel real."
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"Falha no alvo Win32 do Opera GX: {exc}", "APP")
            # Se nao encontramos o executavel, NAO caimos no fast-cache antigo.
            # O resolver ainda pode encontrar um atalho/registro valido abaixo.
        else:
            # Build 12 R2: alvo ja confirmado em uso anterior abre antes de qualquer
            # fuzzy matching. A verificacao de janela permanece na GUI/Agent.
            cached_result = self._open_cached_app(app_name)
            if cached_result:
                return cached_result

        self.logger.system(f"[APP] Resolvendo aplicativo: {app_name}", "APP")
        found = self.resolve_application(app_name)
        if not found:
            options = self.find_application_candidates(app_name, limit=4)
            plausible = [o for o in options if o.get("score", 0) >= 45]
            if plausible:
                names = ", ".join(o["label"] for o in plausible[:4])
                return (
                    f"O nome '{app_name}' corresponde a mais de uma opção. "
                    f"Possíveis candidatos: {names}. Não abri nenhum porque o alvo ficou ambíguo. "
                    f"Use 'ensine o aplicativo {app_name}' para selecionar o correto uma vez."
                )
            if self.app_resolver:
                try:
                    hints = self.app_resolver.global_hints(app_name, limit=2)
                    if hints and float(hints[0].get("confidence", 0.0)) >= 0.88:
                        known = hints[0].get("name") or hints[0].get("label") or app_name
                        return (
                            f"Conheço '{known}' no catálogo global, mas não o detectei instalado neste computador. "
                            "Não encontrei uma instalação local para abrir."
                        )
                except Exception:
                    pass
            return (
                f"Não encontrei o aplicativo '{app_name}' instalado. "
                f"Use 'ensine o aplicativo {app_name}' e selecione o executável ou atalho correto."
            )

        try:
            if self._is_opera_request(app_name) and str(found.get("target") or "").lower().startswith("shell:appsfolder\\"):
                raise RuntimeError("Alias AppsFolder do Opera recusado; executavel Win32 nao confirmado")
            self._launch_app_target(found["target"])
            self._cache_app(app_name, found["target"])
            if self.app_resolver:
                try:
                    self.app_resolver.record_success(found)
                except Exception:
                    pass
            self.logger.info(
                f"Aplicativo aberto: {found['label']} | {found['source']} | {found['target']}",
                "ACTIONS"
            )
            if self.action_verifier:
                try:
                    verification = self.action_verifier.verify_application_open(found["target"], timeout=1.6)
                    if self.reliability:
                        self.reliability.count(
                            "app_open_verified" if verification.verified else "app_open_unverified"
                        )
                    if verification.verified:
                        return f"{found['label']} aberto e verificado."
                    if verification.status == "requested_unverifiable":
                        return f"Solicitei a abertura de {found['label']}."
                    return (
                        f"Solicitei a abertura de {found['label']}, mas ainda não consegui "
                        "confirmar que o processo iniciou."
                    )
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"Verificação de abertura falhou: {exc}", "APP-V7")
            return f"Solicitei a abertura de {found['label']}."
        except Exception as first_error:
            self.logger.warning(
                f"Alvo principal falhou para {app_name}: {first_error}",
                "ACTIONS"
            )

            # Tenta SOMENTE alternativas que também passam pela validação segura.
            try:
                alternatives = self.find_application_candidates(app_name, limit=8)
                for candidate in alternatives:
                    if candidate.get("target") == found.get("target"):
                        continue
                    if not self._is_safe_app_match(
                        app_name,
                        candidate.get("label", ""),
                        candidate.get("target", ""),
                        candidate.get("score", 0),
                    ):
                        continue
                    try:
                        if self._is_opera_request(app_name) and str(candidate.get("target") or "").lower().startswith("shell:appsfolder\\"):
                            continue
                        self._launch_app_target(candidate["target"])
                        self._cache_app(app_name, candidate["target"])
                        if self.app_resolver:
                            try:
                                self.app_resolver.record_success(candidate)
                            except Exception:
                                pass
                        self.logger.info(
                            f"Aplicativo aberto por fallback: {candidate['label']} | "
                            f"{candidate['source']} | {candidate['target']}",
                            "ACTIONS"
                        )
                        if self.action_verifier:
                            try:
                                verification = self.action_verifier.verify_application_open(candidate["target"], timeout=1.6)
                                if verification.verified:
                                    return f"{candidate['label']} aberto e verificado."
                            except Exception:
                                pass
                        return f"Solicitei a abertura de {candidate['label']}."
                    except Exception:
                        continue
            except Exception:
                pass

            self.logger.error(first_error, f"Erro ao abrir {app_name}", "ACTIONS")
            return f"Encontrei {found['label']}, mas não consegui abrir: {first_error}"

    def _rigorous_app_search(self, app_name: str) -> str:
        """Busca rigorosa com mapeamento estrito e tratamento de preposições"""
        # Normalização simples
        app_name_normalized = app_name.lower().strip()
        
        # Log de verificação
        self.logger.system(f"[DEBUG] Comando original: '{app_name_normalized}'", "APP")
        
        # Remoção de stopwords
        stopwords = ['o', 'a', 'um', 'uma', 'por favor', 'please']
        nome_limpo = app_name_normalized
        for stopword in stopwords:
            nome_limpo = nome_limpo.replace(f' {stopword} ', ' ')
            nome_limpo = nome_limpo.replace(f' {stopword}', '')
            nome_limpo = nome_limpo.replace(f'{stopword} ', '')
        
        nome_limpo = nome_limpo.strip()
        
        # Tratamento do 'D' intruso - remove preposições e extrai palavras-chave
        palavras_chave = self._extrair_palavras_chave(nome_limpo)
        nome_processado = ' '.join(palavras_chave)
        
        # Log do nome processado
        self.logger.system(f"[DEBUG] Nome processado: '{nome_processado}' (palavras-chave: {palavras_chave})", "APP")
        
        # Mapeamento estrito de termos para executáveis
        mapeamento_estrito = {
            # Notepad - múltiplas combinações
            'bloco': 'notepad.exe',
            'notas': 'notepad.exe',
            'bloco notas': 'notepad.exe',
            'bloc notas': 'notepad.exe',  # Para erros de digitação
            'blocde notas': 'notepad.exe',  # Para erros de digitação
            'anotacoes': 'notepad.exe',
            'texto': 'notepad.exe',
            'editor texto': 'notepad.exe',
            
            # Calculadora
            'calc': 'calc.exe',
            'calculadora': 'calc.exe',
            'calcular': 'calc.exe',
            
            # CMD/Terminal
            'cmd': 'cmd.exe',
            'prompt': 'cmd.exe',
            'terminal': 'cmd.exe',
            'linha comando': 'cmd.exe',
            'comando': 'cmd.exe',
            
            # PowerShell
            'powershell': 'powershell.exe',
            'power shell': 'powershell.exe',
            'powershel': 'powershell.exe',  # Para erros de digitação
            
            # Explorador
            'explorer': 'explorer.exe',
            'arquivos': 'explorer.exe',
            'gerenciador arquivos': 'explorer.exe',
            
            # Task Manager
            'task': 'taskmgr.exe',
            'taskmgr': 'taskmgr.exe',
            'gerenciador tarefas': 'taskmgr.exe',
            'tarefas': 'taskmgr.exe',
            
            # Painel de Controle
            'painel': 'control.exe',
            'controle': 'control.exe',
            'painel controle': 'control.exe',
            
            # Paint
            'paint': 'mspaint.exe',
            'desenho': 'mspaint.exe',
            'mspaint': 'mspaint.exe',
            
            # Deep Links Windows
            'configuracoes': 'ms-settings:',
            'settings': 'ms-settings:',
            'loja': 'ms-windows-store:',
            'store': 'ms-windows-store:',
            'defender': 'ms-settings:windowsdefender',
            'antivirus': 'ms-settings:windowsdefender',
            'atualizacoes': 'ms-settings:windowsupdate-action',
            'update': 'ms-settings:windowsupdate-action',
            'rede': 'ms-settings:network',
            'som': 'ms-settings:sound',
            'audio': 'ms-settings:sound',
            'energia': 'ms-settings:powersleep',
            'bateria': 'ms-settings:powersleep',
            'notificacoes': 'ms-settings:notifications',
            'privacidade': 'ms-settings:privacy',
            'contas': 'ms-settings:yourinfo',
            'hora': 'ms-settings:dateandtime',
            'data': 'ms-settings:dateandtime',
            'acessibilidade': 'ms-settings:easeofaccess'
        }
        
        # 1. Verifica no mapeamento estrito
        if nome_processado in mapeamento_estrito:
            comando = mapeamento_estrito[nome_processado]
            self.logger.system(f"[DEBUG] Mapeamento estrito: '{nome_processado}' → '{comando}'", "APP")
            return self._executar_comando_direto(comando, app_name)
        
        # 2. Verifica se contém palavras-chave específicas
        for chave, comando in mapeamento_estrito.items():
            if chave in nome_processado:
                self.logger.system(f"[DEBUG] Palavra-chave encontrada: '{chave}' → '{comando}'", "APP")
                return self._executar_comando_direto(comando, app_name)
        
        # 3. Se não encontrou, tenta fallback inteligente
        self.logger.system(f"[DEBUG] Não encontrado no mapeamento, tentando fallback: '{nome_processado}'", "APP")
        return self._fallback_inteligente(nome_processado, app_name)
    
    def _extrair_palavras_chave(self, texto: str) -> List[str]:
        """Extrai palavras-chave ignorando preposições"""
        # Lista de preposições e palavras irrelevantes
        preposicoes = {'de', 'da', 'do', 'em', 'para', 'por', 'com', 'sem', 'sob', 'sobre', 'entre', 'até'}
        
        # Divide o texto em palavras
        palavras = texto.split()
        
        # Filtra apenas palavras-chave (não preposições)
        palavras_chave = [palavra for palavra in palavras if palavra not in preposicoes and len(palavra) > 1]
        
        # Se não encontrou palavras-chave, retorna o texto original
        if not palavras_chave:
            return [texto]
        
        return palavras_chave
    
    def _executar_comando_direto(self, comando: str, original_name: str) -> str:
        """Executa comando usando subprocess.Popen com caminho direto"""
        try:
            self.logger.system(f"[DEBUG] Executando comando direto: '{comando}'", "APP")
            
            if comando.startswith('ms-') or comando.startswith('ms-windows-'):
                # Deep Links Windows
                os.startfile(comando)
                self.logger.info(f"Deep Link executado: {comando}", "ACTIONS")
                return f"Solicitei a abertura de {original_name.title()}."
            
            elif comando.endswith('.exe'):
                # Executável - tenta encontrar no PATH primeiro
                try:
                    # Tenta encontrar o executável no PATH do Windows
                    result = subprocess.run(['where', comando.split('\\')[-1]], 
                                          capture_output=True, text=True, timeout=5)
                    
                    if result.returncode == 0:
                        # Encontrou no PATH, executa com caminho completo
                        caminho_completo = result.stdout.strip().split('\n')[0]
                        subprocess.Popen([caminho_completo], shell=False)
                        self.logger.info(f"Executável encontrado no PATH: {caminho_completo}", "ACTIONS")
                        if self.action_verifier:
                            verification = self.action_verifier.verify_application_open(caminho_completo, timeout=1.6)
                            if verification.verified:
                                return f"{original_name.title()} aberto e verificado."
                        return f"Solicitei a abertura de {original_name.title()}."
                    else:
                        # Não encontrou no PATH, tenta executar direto
                        subprocess.Popen([comando], shell=False)
                        self.logger.info(f"Executável executado diretamente: {comando}", "ACTIONS")
                        if self.action_verifier:
                            verification = self.action_verifier.verify_application_open(comando, timeout=1.6)
                            if verification.verified:
                                return f"{original_name.title()} aberto e verificado."
                        return f"Solicitei a abertura de {original_name.title()}."
                        
                except subprocess.TimeoutExpired:
                    self.logger.warning("Timeout ao buscar executável no PATH", "ACTIONS")
                    # Tenta execução direta como fallback
                    subprocess.Popen([comando], shell=False)
                    self.logger.info(f"Executável executado por fallback: {comando}", "ACTIONS")
                    if self.action_verifier:
                        verification = self.action_verifier.verify_application_open(comando, timeout=1.6)
                        if verification.verified:
                            return f"{original_name.title()} aberto e verificado."
                    return f"Solicitei a abertura de {original_name.title()}."
                    
                except Exception as e:
                    self.logger.error(e, f"Erro ao executar {comando}", "ACTIONS")
                    return f"❌ Erro ao acessar {original_name}: {e}"
            
            else:
                # Outros comandos
                os.startfile(comando)
                self.logger.info(f"Comando executado: {comando}", "ACTIONS")
                return f"Solicitei a abertura de {original_name.title()}."
                
        except Exception as e:
            self.logger.error(e, f"Erro ao executar comando direto: {comando}", "ACTIONS")
            return f"❌ Erro ao acessar {original_name}: {e}"
    
    def _execute_hardcoded_command(self, command: str, original_name: str) -> str:
        """Executa comando hardcoded do dicionário"""
        try:
            self.logger.system(f"[DEBUG] Executando comando hardcoded: {command}", "APP")
            
            if command.startswith('start '):
                # Comando start do shell
                os.system(command)
            else:
                # Executável direto
                os.startfile(command)
            
            self.logger.info(f"Comando hardcoded executado com sucesso: {command}", "ACTIONS")
            return f"{original_name.title()} acessado."
            
        except Exception as e:
            self.logger.error(e, f"Erro ao executar comando hardcoded: {command}", "ACTIONS")
            return f"❌ Erro ao acessar {original_name}: {e}"
    
    def _execute_mapped_command(self, command: str, original_name: str) -> str:
        """Executa comando mapeado"""
        try:
            self.logger.system(f"[DEBUG] Executando comando mapeado: {command}", "APP")
            
            if command.startswith('ms-') or command == 'notepad.exe' or command == 'calc.exe' or command == 'cmd.exe':
                # Protocolos Windows e executáveis do sistema
                if command.endswith('.exe'):
                    # Executável do sistema
                    os.startfile(command)
                else:
                    # Protocolo Windows
                    os.startfile(command)
                
                self.logger.info(f"Comando executado com sucesso: {command}", "ACTIONS")
                return f"{original_name.title()} acessado."
            else:
                # Outros comandos
                os.startfile(command)
                self.logger.info(f"Comando executado com sucesso: {command}", "ACTIONS")
                return f"{original_name.title()} acessado."
                
        except Exception as e:
            self.logger.error(e, f"Erro ao executar comando mapeado: {command}", "ACTIONS")
            return f"❌ Erro ao acessar {original_name}: {e}"
    
    def _fallback_inteligente(self, app_name: str, original_name: str) -> str:
        """Fallback inteligente usando subprocess com verificação de sucesso"""
        try:
            self.logger.system(f"[DEBUG] Tentando fallback inteligente: '{app_name}'", "APP")
            
            # Tenta diferentes variações com subprocess.Popen
            variations = [
                app_name,
                app_name + '.exe',
                app_name.replace(' ', '') + '.exe',
                app_name.replace(' ', ''),
            ]
            
            for variation in variations:
                try:
                    self.logger.system(f"[DEBUG] Testando variação: '{variation}'", "APP")
                    
                    # Tenta encontrar no PATH primeiro
                    try:
                        result = subprocess.run(['where', variation], 
                                              capture_output=True, text=True, timeout=3)
                        
                        if result.returncode == 0:
                            caminho = result.stdout.strip().split('\n')[0]
                            process = subprocess.Popen([caminho], shell=False)
                            self.logger.info(f"App encontrado no PATH: {caminho}", "ACTIONS")
                            return f"{original_name.title()} acessado."
                    except:
                        pass
                    
                    # Se não encontrou no PATH, tenta execução direta
                    process = subprocess.Popen([variation], shell=False)
                    
                    # Verifica se o processo iniciou (espera um pouco)
                    try:
                        # Espera um curto período para verificar se o processo ainda está rodando
                        import time
                        time.sleep(0.5)
                        
                        # Verifica se o processo ainda está ativo
                        if process.poll() is None or process.returncode == 0:
                            self.logger.info(f"Executado com sucesso: {variation}", "ACTIONS")
                            return f"{original_name.title()} acessado."
                        else:
                            self.logger.warning(f"Processo falhou para: {variation}", "ACTIONS")
                            continue
                            
                    except:
                        continue
                        
                except Exception as e:
                    self.logger.warning(f"Falha na variação '{variation}': {e}", "APP")
                    continue
            
            # Se nada funcionou, tenta busca em pastas
            return self._fallback_search(app_name, original_name)
            
        except Exception as e:
            self.logger.error(e, f"Erro no fallback inteligente: {app_name}", "ACTIONS")
            return f"❌ Não consegui encontrar {original_name}."
    
    def _fallback_search(self, app_name: str, original_name: str) -> str:
        """Busca aplicativos instalados no Windows sem abrir pesquisa web."""
        try:
            self.logger.system(f"[DEBUG] Iniciando busca local para: {app_name}", "APP")
            app_lower = app_name.lower().strip()

            # 1. Tenta encontrar pelo PATH
            variations = [
                app_name,
                app_name + ".exe",
                app_name.replace(" ", "") + ".exe"
            ]

            for variation in variations:
                try:
                    result = subprocess.run(
                        ["where", variation],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    if result.returncode == 0:
                        exe_path = result.stdout.strip().splitlines()[0]
                        if os.path.exists(exe_path):
                            os.startfile(exe_path)
                            self._cache_app(original_name, exe_path)
                            self.logger.info(
                                f"Aplicativo encontrado no PATH: {exe_path}",
                                "ACTIONS"
                            )
                            return f"{original_name.title()} acessado."
                except Exception:
                    pass

            # 2. Procura atalhos no Menu Iniciar (usuario e todos os usuarios)
            start_menu_paths = [
                os.path.join(
                    os.getenv("APPDATA", ""),
                    "Microsoft", "Windows", "Start Menu", "Programs"
                ),
                os.path.join(
                    os.getenv("PROGRAMDATA", r"C:\ProgramData"),
                    "Microsoft", "Windows", "Start Menu", "Programs"
                ),
                os.path.join(os.getenv("USERPROFILE", ""), "Desktop"),
                os.path.join(os.getenv("PUBLIC", r"C:\Users\Public"), "Desktop"),
            ]

            # OneDrive pode conter atalhos do Desktop.
            user_profile = os.getenv("USERPROFILE", "")
            if user_profile and os.path.isdir(user_profile):
                try:
                    for item in os.listdir(user_profile):
                        if item.lower().startswith("onedrive"):
                            desktop = os.path.join(user_profile, item, "Desktop")
                            if os.path.isdir(desktop):
                                start_menu_paths.append(desktop)
                except Exception:
                    pass

            for start_path in start_menu_paths:
                if not os.path.exists(start_path):
                    continue

                for root, dirs, files in os.walk(start_path):
                    for file in files:
                        if not file.lower().endswith((".lnk", ".url")):
                            continue

                        file_name = os.path.splitext(file)[0].lower()
                        if app_lower in file_name or file_name in app_lower:
                            shortcut = os.path.join(root, file)
                            self.logger.system(
                                f"[DEBUG] Atalho encontrado: {shortcut}",
                                "APP"
                            )
                            try:
                                os.startfile(shortcut)
                                self._cache_app(original_name, shortcut)
                                self.logger.info(
                                    f"Aplicativo aberto pelo Menu Iniciar: {shortcut}",
                                    "ACTIONS"
                                )
                                return f"{original_name.title()} acessado."
                            except Exception as e:
                                self.logger.warning(
                                    f"Falha ao abrir atalho {shortcut}: {e}",
                                    "APP"
                                )

            # 3. Procura executaveis recursivamente nas pastas principais
            search_paths = [
                r"C:\Program Files",
                r"C:\Program Files (x86)",
                os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs"),
                os.getenv("LOCALAPPDATA", ""),
                os.getenv("APPDATA", ""),
            ]

            # Procura também em pastas comuns de outros discos montados.
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if not os.path.exists(drive):
                    continue

                for folder in [
                    "Program Files",
                    "Program Files (x86)",
                    "Programs",
                    "Apps",
                    "Aplicativos",
                    "Sistemas",
                    "Software",
                ]:
                    candidate = os.path.join(drive, folder)
                    if os.path.isdir(candidate) and candidate not in search_paths:
                        search_paths.append(candidate)

            palavras = [
                palavra.lower()
                for palavra in app_lower.split()
                if len(palavra) > 2
            ]

            # Evita uma busca sem criterio caso o nome seja muito curto
            if not palavras and app_lower:
                palavras = [app_lower]

            for search_path in search_paths:
                if not search_path or not os.path.exists(search_path):
                    continue

                self.logger.system(
                    f"[DEBUG] Procurando em: {search_path}",
                    "APP"
                )

                for root, dirs, files in os.walk(search_path):
                    for file in files:
                        if not file.lower().endswith(".exe"):
                            continue

                        exe_name = file.lower()
                        root_lower = root.lower()

                        # Considera tanto o nome do executavel quanto a pasta do produto
                        if any(
                            palavra in exe_name or palavra in root_lower
                            for palavra in palavras
                        ):
                            exe_path = os.path.join(root, file)
                            self.logger.system(
                                f"[DEBUG] Possivel aplicativo encontrado: {exe_path}",
                                "APP"
                            )
                            try:
                                os.startfile(exe_path)
                                self._cache_app(original_name, exe_path)
                                self.logger.info(
                                    f"Aplicativo encontrado e aberto: {exe_path}",
                                    "ACTIONS"
                                )
                                return f"{original_name.title()} acessado."
                            except Exception as e:
                                self.logger.warning(
                                    f"Nao foi possivel abrir {exe_path}: {e}",
                                    "APP"
                                )
                                continue

            # 4. Nao encontrou: nao abre Google automaticamente
            self.logger.warning(
                f"Aplicativo nao encontrado localmente: {original_name}",
                "ACTIONS"
            )
            return (
                f"Nao encontrei {original_name} instalado neste computador."
            )

        except Exception as e:
            self.logger.error(
                e,
                f"Erro ao procurar aplicativo: {app_name}",
                "ACTIONS"
            )
            return f"Erro ao procurar {original_name}: {e}"

    def _universal_app_search(self, app_name: str) -> str:
        """Busca universal de aplicativos usando os.startfile e protocolos do Windows"""
        app_name_lower = app_name.lower().strip()
        
        self.logger.system(f"Busca universal iniciada para: {app_name}", "APP")
        
        # Protocolos específicos do Windows (prioridade máxima)
        specific_protocols = {
            'configurações': 'ms-settings:',
            'configuracoes': 'ms-settings:',
            'settings': 'ms-settings:',
            'loja': 'ms-windows-store:',
            'store': 'ms-windows-store:',
            'microsoft store': 'ms-windows-store:',
            'calculadora': 'calc',
            'calculator': 'calc',
            'calc': 'calc',
            'painel de controle': 'control',
            'control panel': 'control',
            'notepad': 'notepad',
            'bloco de notas': 'notepad',
            'cmd': 'cmd',
            'prompt': 'cmd',
            'terminal': 'cmd',
            'powershell': 'powershell',
            'explorer': 'explorer',
            'task manager': 'taskmgr',
            'gerenciador de tarefas': 'taskmgr',
            # Deep Links Mark 12
            'atualizações': 'ms-settings:windowsupdate-action',
            'atualizacoes': 'ms-settings:windowsupdate-action',
            'windows update': 'ms-settings:windowsupdate-action',
            'update': 'ms-settings:windowsupdate-action',
            'atualizar': 'ms-settings:windowsupdate-action',
            'atualizar windows': 'ms-settings:windowsupdate-action',
            'windows defender': 'ms-settings:windowsdefender',
            'defender': 'ms-settings:windowsdefender',
            'antivírus': 'ms-settings:windowsdefender',
            'rede': 'ms-settings:network',
            'network': 'ms-settings:network',
            'conexões': 'ms-settings:network',
            'bluetooth': 'ms-settings:bluetooth',
            'som': 'ms-settings:sound',
            'áudio': 'ms-settings:sound',
            'audio': 'ms-settings:sound',
            'energia': 'ms-settings:powersleep',
            'power': 'ms-settings:powersleep',
            'bateria': 'ms-settings:powersleep',
            'notificações': 'ms-settings:notifications',
            'privacidade': 'ms-settings:privacy',
            'contas': 'ms-settings:yourinfo',
            'hora e data': 'ms-settings:dateandtime',
            'time': 'ms-settings:dateandtime',
            'data': 'ms-settings:dateandtime',
            'acessibilidade': 'ms-settings:easeofaccess'
        }
        
        # 1. Verifica se é um protocolo específico conhecido
        if app_name_lower in specific_protocols:
            protocol = specific_protocols[app_name_lower]
            try:
                self.logger.system(f"Usando os.startfile para protocolo: {protocol}", "APP")
                os.startfile(protocol)
                self.logger.info(f"Protocolo Windows executado com os.startfile: {protocol}", "ACTIONS")
                
                # Mensagem específica para cada tipo
                if app_name_lower in ['configurações', 'configuracoes', 'settings']:
                    return "Configurações acessadas."
                elif app_name_lower in ['loja', 'store', 'microsoft store']:
                    return "Microsoft Store acessada."
                elif app_name_lower in ['calculadora', 'calculator', 'calc']:
                    return "Calculadora acessada."
                else:
                    return f"{app_name.title()} acessado."
                    
            except Exception as e:
                self.logger.error(e, f"Protocolo falhou para {app_name}", "ACTIONS")
                return f"❌ o sistema operacional recusou o protocolo. Verifique se o caminho está correto."
        
        # 2. Para outros apps, usa where para encontrar o caminho real (busca agressiva)
        try:
            self.logger.system(f"Buscando caminho com 'where {app_name_lower}'", "APP")
            where_result = os.popen(f'where {app_name_lower}').read().strip()
            
            if where_result:
                # Pega a primeira linha (caminho mais relevante)
                exe_path = where_result.split('\n')[0].strip()
                self.logger.system(f"Encontrado: {exe_path}", "APP")
                
                try:
                    os.startfile(exe_path)
                    self.logger.info(f"Aplicativo executado com os.startfile: {exe_path}", "ACTIONS")
                    return f"{app_name.title()} acessado."
                except Exception as e:
                    self.logger.error(e, f"Erro ao executar {app_name}", "ACTIONS")
                    return f"❌ o sistema operacional recusou o protocolo. Verifique se o caminho está correto."
            else:
                self.logger.system(f"{app_name} não encontrado com 'where'", "APP")
                
        except Exception as e:
            self.logger.error(e, f"Erro no comando 'where'", "ACTIONS")
        
        # 2.1. Busca com variações do nome (busca agressiva)
        name_variations = [
            app_name_lower,
            app_name_lower.replace(' ', ''),
            app_name_lower.replace('-', ''),
            app_name_lower.replace('_', ''),
            app_name_lower + '.exe',
            app_name_lower.replace(' ', '') + '.exe'
        ]
        
        for variation in name_variations:
            try:
                self.logger.system(f"Tentando variação: 'where {variation}'", "APP")
                where_result = os.popen(f'where {variation}').read().strip()
                
                if where_result:
                    exe_path = where_result.split('\n')[0].strip()
                    self.logger.system(f"Encontrado com variação: {exe_path}", "APP")
                    
                    try:
                        os.startfile(exe_path)
                        self.logger.info(f"Aplicativo executado com variação: {exe_path}", "ACTIONS")
                        return f"{app_name.title()} acessado."
                    except Exception as e:
                        continue
                        
            except Exception:
                continue
        
        # 2.2. Caminhos absolutos conhecidos para aplicativos comuns
        known_paths = {
            'notepad': r'C:\Windows\System32\notepad.exe',
            'bloco de notas': r'C:\Windows\System32\notepad.exe',
            'calc': r'C:\Windows\System32\calc.exe',
            'calculadora': r'C:\Windows\System32\calc.exe',
            'calculator': r'C:\Windows\System32\calc.exe',
            'cmd': r'C:\Windows\System32\cmd.exe',
            'prompt': r'C:\Windows\System32\cmd.exe',
            'terminal': r'C:\Windows\System32\cmd.exe',
            'powershell': r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
            'explorer': r'C:\Windows\explorer.exe',
            'taskmgr': r'C:\Windows\System32\taskmgr.exe',
            'task manager': r'C:\Windows\System32\taskmgr.exe',
            'gerenciador de tarefas': r'C:\Windows\System32\taskmgr.exe',
            'mspaint': r'C:\Windows\System32\mspaint.exe',
            'paint': r'C:\Windows\System32\mspaint.exe',
            'wordpad': r'C:\Program Files\Windows NT\Accessories\wordpad.exe',
            'write': r'C:\Program Files\Windows NT\Accessories\wordpad.exe'
        }
        
        if app_name_lower in known_paths:
            known_path = known_paths[app_name_lower]
            if os.path.exists(known_path):
                try:
                    self.logger.system(f"Usando caminho conhecido: {known_path}", "APP")
                    os.startfile(known_path)
                    self.logger.info(f"Aplicativo executado com caminho conhecido: {known_path}", "ACTIONS")
                    return f"{app_name.title()} acessado."
                except Exception as e:
                    self.logger.error(e, f"Erro ao executar caminho conhecido: {known_path}", "ACTIONS")
        
        # 3. Se não encontrar com where, tenta busca direta em pastas comuns
        search_paths = [
            fr"C:\Program Files",
            fr"C:\Program Files (x86)",
            fr"C:\Users\{os.getenv('USERNAME')}\AppData\Local",
            fr"C:\Users\{os.getenv('USERNAME')}\AppData\Roaming",
            fr"C:\Users\{os.getenv('USERNAME')}\Desktop",
            "C:\\Windows\\System32"
        ]
        
        # Nomes possíveis de executáveis para buscar
        possible_names = [
            f"{app_name}.exe",
            f"{app_name_lower}.exe",
            f"{app_name.replace(' ', '')}.exe",
            f"{app_name_lower.replace(' ', '')}.exe",
            app_name,
            app_name_lower
        ]
        
        self.logger.system("Buscando em pastas do Windows...", "APP")
        
        for search_path in search_paths:
            if not os.path.exists(search_path):
                continue
                
            for possible_name in possible_names:
                try:
                    # Busca recursiva com glob
                    pattern = os.path.join(search_path, "**", possible_name)
                    matches = glob.glob(pattern, recursive=True)
                    
                    if matches:
                        # Pega o primeiro match mais relevante
                        best_match = matches[0]
                        self.logger.system(f"Encontrado: {best_match}", "APP")
                        
                        try:
                            os.startfile(best_match)
                            self.logger.info(f"Aplicativo encontrado e executado: {best_match}", "ACTIONS")
                            return f"{app_name.title()} acessado."
                        except Exception as e:
                            self.logger.error(e, f"Erro ao executar {app_name}", "ACTIONS")
                            continue
                                
                except Exception as e:
                    continue
        
        # 4. Se for pasta, tenta abrir com explorer
        if any(keyword in app_name_lower for keyword in ['pasta', 'folder', 'downloads', 'documents', 'desktop', 'pictures', 'music', 'videos']):
            return self._open_special_folder(app_name)
        
        # 5. Busca por palavras-chave em nomes de arquivos
        self.logger.system("Busca por palavras-chave...", "APP")
        for search_path in search_paths:
            if not os.path.exists(search_path):
                continue
                
            try:
                # Busca arquivos que contenham o nome do app
                pattern = os.path.join(search_path, "**", f"*{app_name_lower}*.exe")
                matches = glob.glob(pattern, recursive=True)
                
                for match in matches[:3]:  # Limita a 3 resultados mais relevantes
                    try:
                        os.startfile(match)
                        self.logger.info(f"Aplicativo encontrado por keyword: {match}", "ACTIONS")
                        return f"{app_name.title()} acessado."
                    except Exception:
                        continue
                        
            except Exception:
                continue
        
        # 6. Se nada funcionou, tenta busca no Google como último recurso
        try:
            self.logger.system(f"Tentando busca no Google para: {app_name}", "APP")
            search_url = f"https://www.google.com/search?q={app_name.replace(' ', '+')}"
            webbrowser.open(search_url)
            self.logger.info(f"Busca no Google realizada para: {app_name}", "ACTIONS")
            return f"Não encontrei {app_name} localmente. Buscando no Google."
        except Exception as e:
            self.logger.warning(f"Busca no Google falhou: {e}", "ACTIONS")
        
        # Se absolutamente nada funcionou
        self.logger.warning(f"Aplicativo não encontrado: {app_name}", "ACTIONS")
        return f"❌ Não consegui encontrar o {app_name} em seu sistema. Verifique se está instalado."
    
    def open_path(self, path: str) -> str:
        path = os.path.expandvars(os.path.expanduser((path or "").strip().strip('"')))
        if not path:
            return "Informe o caminho que devo abrir."
        if os.path.exists(path):
            os.startfile(path)
            return f"Abrindo {path}."
        return f"Não encontrei o caminho: {path}"

    def _desktop_directory(self) -> str:
        """Resolve a Área de Trabalho real (inclusive OneDrive) no Windows."""
        if os.name == "nt":
            try:
                buf = ctypes.create_unicode_buffer(32768)
                # CSIDL_DESKTOPDIRECTORY = 0x10
                if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:
                    candidate = buf.value.strip()
                    if candidate and os.path.isdir(candidate):
                        return candidate
            except Exception:
                pass
        home = Path.home()
        candidates = [
            home / "Desktop",
            Path(os.getenv("OneDrive", "")) / "Desktop" if os.getenv("OneDrive") else None,
            Path(os.getenv("OneDrive", "")) / "Área de Trabalho" if os.getenv("OneDrive") else None,
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                return str(candidate)
        return str(home / "Desktop")

    def _known_user_directory(self, kind: str) -> str:
        """Resolve diretórios comuns do usuário sem depender do CWD do JARVIS."""
        key = self._normalize_app_name(kind)
        if key in {"desktop", "area de trabalho"}:
            return self._desktop_directory()

        home = Path.home()
        env_home = Path(os.getenv("USERPROFILE", str(home)))
        candidates = []
        if key in {"downloads", "download"}:
            candidates = [env_home / "Downloads", home / "Downloads"]
        elif key in {"documents", "documentos", "documento"}:
            candidates = [env_home / "Documents", home / "Documents", env_home / "Documentos"]
        elif key in {"pictures", "imagens", "imagem"}:
            candidates = [env_home / "Pictures", home / "Pictures", env_home / "Imagens"]
        else:
            return str(env_home)

        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_dir():
                    return str(candidate)
            except Exception:
                pass
        return str(candidates[0])

    def create_folder(self, path: str) -> str:
        raw = " ".join(str(path or "").strip().strip('"').split())
        if not raw:
            return "Informe onde devo criar a pasta."
        if "\x00" in raw:
            return "Caminho de pasta inválido."
        # Blindagem na própria ferramenta: mesmo que um parser erre, nunca
        # aceite travessia por '..' em caminhos Windows ou POSIX.
        raw_parts = [part for part in re.split(r"[\\/]+", raw) if part]
        if any(part == ".." for part in raw_parts):
            return "Caminho de pasta inválido: travessia de diretórios bloqueada."

        # Linguagem natural: "desktop Projetos", "na área de trabalho Teste" etc.
        key = self._normalize_app_name(raw)
        name = ""
        for prefix in (
            "no desktop ", "desktop ", "na area de trabalho ", "area de trabalho ",
            "na área de trabalho ", "área de trabalho ",
        ):
            if raw.lower().startswith(prefix):
                name = raw[len(prefix):].strip().strip('"')
                break
        if not name and key.startswith("desktop "):
            name = raw.split(" ", 1)[1].strip().strip('"')

        if name:
            # V8: nunca aceite uma frase descritiva inteira como nome.
            name = re.sub(r"\s+(?:na|no)\s+(?:área|area)\s+de\s+trabalho.*$", "", name, flags=re.I).strip()
            name = re.sub(r"\s+no\s+desktop.*$", "", name, flags=re.I).strip()
            name = re.sub(r"^(?:chamada|chamado)\s+", "", name, flags=re.I).strip()
            if name in {".", ".."} or ".." in Path(name).parts:
                return "Nome de pasta inválido."
            if name.upper().split('.')[0] in {"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}:
                return "Esse nome é reservado pelo Windows."
            invalid = '<>:"/\\|?*'
            if any(ch in name for ch in invalid):
                return "O nome da pasta contém um caractere inválido do Windows."
            name = name.rstrip(" .")
            if not name:
                return "Informe o nome da pasta."
            path = os.path.join(self._desktop_directory(), name)
        else:
            # No caminho explícito, valida também o nome final reservado. O ':'
            # de uma letra de unidade (C:) permanece permitido por ser parte do
            # caminho, não do nome da pasta.
            leaf = next((part for part in reversed(raw_parts) if not re.fullmatch(r"[A-Za-z]:", part)), "")
            if leaf and leaf.upper().split('.')[0] in {"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}:
                return "Esse nome é reservado pelo Windows."
            path = os.path.expandvars(os.path.expanduser(raw))

        try:
            os.makedirs(path, exist_ok=True)
            return f"✓ Pasta criada: {path}"
        except Exception as e:
            return f"Não consegui criar a pasta: {e}"

    def create_text_file(self, name: str, desktop: bool = True) -> str:
        """Cria arquivo .txt com nome seguro, por padrao no Desktop."""
        raw = " ".join(str(name or "").strip().strip('"').split()).rstrip(" .")
        if not raw:
            raw = "Novo arquivo"
        if not raw.lower().endswith(".txt"):
            raw += ".txt"
        base = raw[:-4]
        if base in {".", ".."} or any(ch in raw for ch in '<>:"/\\|?*'):
            return "Nome de arquivo inválido."
        if base.upper().split('.')[0] in {"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}:
            return "Esse nome é reservado pelo Windows."
        path = os.path.join(self._desktop_directory(), raw) if desktop else os.path.abspath(raw)
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).touch(exist_ok=True)
            return f"✓ Arquivo criado: {path}"
        except Exception as e:
            return f"Não consegui criar o arquivo: {e}"

    def copy_path(self, source: str, destination: str) -> str:
        source = os.path.expandvars(os.path.expanduser(source.strip().strip('"')))
        destination = os.path.expandvars(os.path.expanduser(destination.strip().strip('"')))
        try:
            if os.path.isdir(source):
                dest = os.path.join(destination, os.path.basename(source.rstrip('\\/'))) if os.path.isdir(destination) else destination
                shutil.copytree(source, dest, dirs_exist_ok=True)
            elif os.path.isfile(source):
                os.makedirs(destination, exist_ok=True) if not os.path.splitext(destination)[1] else None
                shutil.copy2(source, destination)
            else:
                return f"Origem não encontrada: {source}"
            return "Cópia concluída."
        except Exception as e:
            return f"Não consegui copiar: {e}"

    def move_path(self, source: str, destination: str) -> str:
        source = os.path.expandvars(os.path.expanduser(source.strip().strip('"')))
        destination = os.path.expandvars(os.path.expanduser(destination.strip().strip('"')))
        try:
            if not os.path.exists(source):
                return f"Origem não encontrada: {source}"
            shutil.move(source, destination)
            return "Movimentação concluída."
        except Exception as e:
            return f"Não consegui mover: {e}"

    def find_files(self, query: str, root: str = "", limit: int = 12) -> str:
        q = self._normalize_app_name(query)
        if not q:
            return "Informe o nome do arquivo que devo procurar."
        roots = []
        if root:
            root = os.path.expandvars(os.path.expanduser(root.strip().strip('"')))
            if os.path.isdir(root):
                roots.append(root)
        else:
            user = os.getenv("USERPROFILE", "")
            for folder in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
                p = os.path.join(user, folder)
                if os.path.isdir(p):
                    roots.append(p)
        found = []
        start = time.time()
        for search_root in roots:
            for current, dirs, files in os.walk(search_root):
                if time.time() - start > 10:
                    break
                dirs[:] = [d for d in dirs if d.lower() not in {"node_modules", ".git", "cache", "temp"}]
                for name in files:
                    if q in self._normalize_app_name(name):
                        found.append(os.path.join(current, name))
                        if len(found) >= limit:
                            break
                if len(found) >= limit:
                    break
        if not found:
            return f"Não encontrei arquivos com '{query}' nas pastas pessoais."
        return "Encontrei:\n" + "\n".join(f"- {p}" for p in found)

    def lock_pc(self) -> str:
        try:
            ctypes.windll.user32.LockWorkStation()
            return "Computador bloqueado."
        except Exception as e:
            return f"Não consegui bloquear o computador: {e}"

    def search_web_in_opera(self, query: str) -> str:
        """Abre uma pesquisa real no Google dentro do Opera GX.

        Nao usa lista de consultas, WebSearch, Gemini ou API de busca. A frase
        inteira do usuario vira o parametro q da URL do mecanismo de busca.
        """
        from urllib.parse import quote_plus

        query = " ".join(str(query or "").split()).strip()
        if not query:
            return "Diga o que você quer pesquisar no Opera."
        url = "https://www.google.com/search?q=" + quote_plus(query)
        result = self.open_url_in_opera_gx(url)
        if str(result).lower().startswith(("não", "nao", "erro", "❌")):
            return result
        return f"✓ Pesquisa aberta no Opera: {query}"

    def open_website(self, address: str) -> str:
        address = (address or "").strip()
        if not address:
            return "Informe o site que devo abrir."
        aliases = {
            "youtube": "https://www.youtube.com/",
            "google": "https://www.google.com/",
            "gmail": "https://mail.google.com/",
            "whatsapp": "https://web.whatsapp.com/",
            "chatgpt": "https://chatgpt.com/",
        }
        url = aliases.get(address.lower(), address)
        if not re.match(r"^https?://", url, flags=re.I):
            if "." in url and " " not in url:
                url = "https://" + url
            else:
                url = "https://www.google.com/search?q=" + requests.utils.quote(url)
        result = self.open_url_in_opera_gx(url)
        return result if result.startswith("Não") else f"Abrindo {address} no Opera GX."

    def _find_opera_window(self):
        """Retorna HWND de uma janela do Opera, preferindo aba do YouTube."""
        if os.name != "nt":
            return None
        user32 = ctypes.windll.user32
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)
            title = title_buf.value
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                proc_name = psutil.Process(pid.value).name().lower()
            except Exception:
                proc_name = ""
            if "opera" in proc_name:
                priority = 2 if "youtube" in title.lower() else 1
                found.append((priority, hwnd, title))
            return True

        try:
            user32.EnumWindows(WNDENUMPROC(callback), 0)
        except Exception:
            return None
        if not found:
            return None
        found.sort(key=lambda x: x[0], reverse=True)
        return found[0][1]

    def _find_process_window(self, *needles):
        """Retorna uma janela visível cujo processo/título combine com ``needles``."""
        if os.name != "nt":
            return None
        wanted = [str(x or "").lower().strip() for x in needles if str(x or "").strip()]
        if not wanted:
            return None
        user32 = ctypes.windll.user32
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length:
                title_buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title_buf, length + 1)
                title = title_buf.value
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                proc_name = psutil.Process(pid.value).name().lower()
            except Exception:
                proc_name = ""
            haystack = f"{proc_name} {title.lower()}"
            if any(term in haystack for term in wanted):
                score = 2 if title else 1
                found.append((score, hwnd, proc_name, title))
            return True

        try:
            user32.EnumWindows(WNDENUMPROC(callback), 0)
        except Exception:
            return None
        if not found:
            return None
        found.sort(key=lambda item: item[0], reverse=True)
        return found[0][1]

    def _send_media_appcommand(self, appcommand: int, target_hint: str = None) -> bool:
        """Envia WM_APPCOMMAND diretamente a um player conhecido.

        Isto evita o problema de a tecla multimídia global cair no navegador
        quando o usuário disse explicitamente que quer controlar o Spotify.
        """
        if os.name != "nt" or not target_hint:
            return False
        key = self._normalize_app_name(str(target_hint))
        process_needles = []
        if "spotify" in key:
            process_needles = ["spotify"]
        elif "vlc" in key:
            process_needles = ["vlc"]
        if not process_needles:
            return False
        hwnd = self._find_process_window(*process_needles)
        if not hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            WM_APPCOMMAND = 0x0319
            SMTO_ABORTIFHUNG = 0x0002
            result = ctypes.c_ulong()
            ok = user32.SendMessageTimeoutW(
                hwnd,
                WM_APPCOMMAND,
                hwnd,
                int(appcommand) << 16,
                SMTO_ABORTIFHUNG,
                700,
                ctypes.byref(result),
            )
            return bool(ok)
        except Exception as exc:
            self.logger.warning(f"WM_APPCOMMAND falhou para {target_hint}: {exc}", "MEDIA")
            return False

    def _send_opera_youtube_shortcut(self, *keys) -> bool:
        """Foca Opera/YouTube por instantes, envia atalho e devolve foco à janela anterior."""
        if os.name != "nt":
            return False
        try:
            user32 = ctypes.windll.user32
            previous = user32.GetForegroundWindow()
            target = self._find_opera_window()
            if not target:
                return False
            user32.ShowWindow(target, 9)
            user32.SetForegroundWindow(target)
            time.sleep(0.12)
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys)
            time.sleep(0.12)
            if previous and previous != target:
                try:
                    user32.SetForegroundWindow(previous)
                except Exception:
                    pass
            return True
        except Exception as e:
            self.logger.warning(f"Atalho Opera/YouTube falhou: {e}", "MEDIA")
            return False

    def _open_special_folder(self, folder_name: str) -> str:
        """Abre pastas especiais do sistema"""
        folder_name_lower = folder_name.lower()
        
        special_folders = {
            'downloads': 'downloads',
            'documentos': 'documents',
            'documents': 'documents',
            'desktop': 'desktop',
            'área de trabalho': 'desktop',
            'imagens': 'pictures',
            'pictures': 'pictures',
            'música': 'music',
            'music': 'music',
            'vídeos': 'videos',
            'videos': 'videos'
        }
        
        if folder_name_lower in special_folders:
            folder_path = os.path.join(os.path.expanduser('~'), special_folders[folder_name_lower])
            try:
                os.startfile(folder_path)
                self.logger.info(f"Pasta aberta: {folder_path}", "ACTIONS")
                return f"Pasta {folder_name.title()} acessada."
            except Exception as e:
                self.logger.error(e, f"Erro ao abrir pasta {folder_name}", "ACTIONS")
                return f"❌ Erro ao abrir pasta {folder_name}."
        
        return "Pasta não reconhecida."
    
    def control_volume(self, action: str) -> str:
        """Controla o volume do sistema com bind Core Audio sob demanda."""
        if not self.audio_available or not hasattr(self, "volume"):
            try:
                self._init_audio_control(force=True)
            except Exception:
                pass
        if not self.audio_available or not hasattr(self, "volume"):
            return "❌ Controle de áudio não disponível."
        
        try:
            current_volume = self.volume.GetMasterVolumeLevelScalar()
            
            if action == "up":
                new_volume = min(1.0, current_volume + 0.1)
                self.volume.SetMasterVolumeLevelScalar(new_volume, None)
                self.last_known_volume = int(round(new_volume * 100))
                self.logger.info(f"Volume aumentado: {current_volume:.1f} → {new_volume:.1f}", "ACTIONS")
                return f"Volume aumentado para {int(new_volume * 100)}%."
            
            elif action == "down":
                new_volume = max(0.0, current_volume - 0.1)
                self.volume.SetMasterVolumeLevelScalar(new_volume, None)
                self.last_known_volume = int(round(new_volume * 100))
                self.logger.info(f"Volume diminuído: {current_volume:.1f} → {new_volume:.1f}", "ACTIONS")
                return f"Volume diminuído para {int(new_volume * 100)}%."
            
            elif action == "mute":
                self.volume.SetMute(1, None)
                self.logger.info("Volume silenciado", "ACTIONS")
                return "Volume silenciado."
            
            elif action == "unmute":
                self.volume.SetMute(0, None)
                self.logger.info("Volume ativado", "ACTIONS")
                return "Volume ativado."
            
        except Exception as e:
            self.logger.error(e, "Erro ao controlar volume", "ACTIONS")
            return f"❌ Erro ao controlar volume: {e}"
    
    def control_brightness(self, action: str) -> str:
        """Controla o brilho da tela"""
        try:
            if action == "up":
                sbc.set_brightness(sbc.get_brightness() + 10)
                self.logger.info("Brilho aumentado", "ACTIONS")
                return "Brilho aumentado."
            
            elif action == "down":
                sbc.set_brightness(max(0, sbc.get_brightness() - 10))
                self.logger.info("Brilho diminuído", "ACTIONS")
                return "Brilho diminuído."
            
            elif action == "max":
                sbc.set_brightness(100)
                self.logger.info("Brilho máximo", "ACTIONS")
                return "Brilho no máximo."
            
            elif action == "min":
                sbc.set_brightness(0)
                self.logger.info("Brilho mínimo", "ACTIONS")
                return "Brilho no mínimo."
            
        except Exception as e:
            self.logger.error(e, "Erro ao controlar brilho", "ACTIONS")
            return f"❌ Erro ao controlar brilho: {e}"
    
    def execute_power_command(self, action: str) -> str:
        """Executa comandos de energia do sistema (Mark 12)"""
        if action == "shutdown":
            return self._execute_shutdown()
        elif action == "restart":
            return self._execute_restart()
        elif action == "suspend":
            return self._execute_suspend()
        else:
            return f"❌ Comando de energia desconhecido: {action}"
    
    def _execute_shutdown(self) -> str:
        """Executa desligamento com aviso de 60 segundos"""
        self.logger.warning("🔌 COMANDO DE DESLIGAMENTO SOLICITADO", "ENERGIA")
        
        # Log de segurança
        log_entry = f"COMANDO_DESligAMENTO_SOLICITADO - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.logger.info(log_entry, "ENERGIA")
        
        return "🔌 os sistemas serão encerrados. Confirma o protocolo?"
    
    def _execute_restart(self) -> str:
        """Executa reinicialização com aviso de 60 segundos"""
        self.logger.warning("🔄 COMANDO DE REINICIALIZAÇÃO SOLICITADO", "ENERGIA")
        
        # Log de segurança
        log_entry = f"COMANDO_REINICIALIZACAO_SOLICITADO - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.logger.info(log_entry, "ENERGIA")
        
        return "🔄 os sistemas serão reiniciados. Confirma o protocolo?"
    
    def _execute_suspend(self) -> str:
        """Executa suspensão imediata"""
        self.logger.warning("😴 COMANDO DE SUSPENSÃO SOLICITADO", "ENERGIA")
        
        try:
            # Log de segurança
            log_entry = f"COMANDO_SUSPENSAO_EXECUTADO - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.logger.info(log_entry, "ENERGIA")
            
            # Executa suspensão
            os.system('rundll32.exe powrprof.dll,SetSuspendState 0,1,0')
            return "😴 Sistema suspenso."
        except Exception as e:
            self.logger.error(e, "Erro ao suspender sistema", "ENERGIA")
            return f"❌ Erro ao suspender sistema: {e}"
    
    def schedule_power_action(self, action: str, delay_seconds: int) -> str:
        """Agenda desligamento/reinício usando o timer nativo do Windows.

        O agendamento sobrevive ao fechamento do JARVIS e pode ser cancelado com
        `shutdown /a`. A GUI exige confirmação antes de chamar este método.
        """
        action = str(action or "shutdown").strip().lower()
        try:
            seconds = max(10, min(int(delay_seconds), 7 * 24 * 3600))
        except Exception:
            return "Não consegui interpretar o tempo do agendamento."
        if os.name != "nt":
            return "Agendamento de energia está disponível apenas no Windows."
        flag = "/s" if action == "shutdown" else "/r" if action == "restart" else ""
        if not flag:
            return "Ação de energia agendada desconhecida."
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["shutdown", flag, "/t", str(seconds)],
                capture_output=True, text=True, timeout=8, creationflags=creationflags,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "erro desconhecido").strip()
                return f"Não consegui agendar a ação: {detail}"
            label = "desligamento" if action == "shutdown" else "reinício"
            if seconds % 3600 == 0:
                when = f"{seconds // 3600} hora(s)"
            elif seconds % 60 == 0:
                when = f"{seconds // 60} minuto(s)"
            else:
                when = f"{seconds} segundo(s)"
            self.logger.info(f"{label.upper()} AGENDADO PARA {seconds}s", "ENERGIA")
            return f"✓ {label.capitalize()} agendado para daqui a {when}. Você pode dizer 'cancele o desligamento' para abortar."
        except Exception as exc:
            self.logger.error(exc, "Erro ao agendar energia", "ENERGIA")
            return f"Não consegui agendar a ação de energia: {exc}"

    def cancel_scheduled_power(self) -> str:
        if os.name != "nt":
            return "Cancelamento de energia agendada está disponível apenas no Windows."
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["shutdown", "/a"], capture_output=True, text=True, timeout=8, creationflags=creationflags
            )
            if result.returncode == 0:
                self.logger.info("AGENDAMENTO DE ENERGIA CANCELADO", "ENERGIA")
                return "✓ Desligamento ou reinício agendado cancelado."
            detail = (result.stderr or result.stdout or "").strip().lower()
            if "no shutdown" in detail or "nenhum desligamento" in detail:
                return "Não havia desligamento ou reinício agendado."
            return "Não encontrei um desligamento agendado para cancelar."
        except Exception as exc:
            self.logger.error(exc, "Erro ao cancelar energia agendada", "ENERGIA")
            return f"Não consegui cancelar o agendamento: {exc}"

    def confirm_power_action(self, action: str) -> str:
        """Confirma e executa ação de energia"""
        if action == "shutdown":
            try:
                self.logger.info("🔌 DESLIGAMENTO CONFIRMADO - EXECUTANDO", "ENERGIA")
                os.system('shutdown /s /t 60')
                return "🔌 Desligamento confirmado. O sistema será desligado em 60 segundos."
            except Exception as e:
                self.logger.error(e, "Erro ao executar desligamento", "ENERGIA")
                return f"❌ Erro ao executar desligamento: {e}"
                
        elif action == "restart":
            try:
                self.logger.info("🔄 REINICIALIZAÇÃO CONFIRMADA - EXECUTANDO", "ENERGIA")
                os.system('shutdown /r /t 60')
                return "🔄 Reinicialização confirmada. O sistema será reiniciado em 60 segundos."
            except Exception as e:
                self.logger.error(e, "Erro ao executar reinicialização", "ENERGIA")
                return f"❌ Erro ao executar reinicialização: {e}"
                
        else:
            return f"❌ Ação de energia não reconhecida: {action}"
    
    def execute_emergency_silence(self) -> str:
        """Executa o Protocolo Silêncio - fecha abas e silencia volume"""
        self.logger.info("🚨 PROTOCOLO SILÊNCIO ATIVADO", "EMERGÊNCIA")
        
        actions_performed = []
        errors = []
        
        # 1. Silenciar volume imediatamente
        try:
            if not self.audio_available or not hasattr(self, "volume"):
                self._init_audio_control(force=True)
            if self.audio_available and hasattr(self, "volume"):
                self.volume.SetMute(1, None)
                actions_performed.append("Volume silenciado")
                self.logger.info("Volume silenciado no Protocolo Silêncio", "EMERGÊNCIA")
            else:
                errors.append("Controle de áudio não disponível")
        except Exception as e:
            errors.append(f"Erro ao silenciar volume: {e}")
            self.logger.error(e, "Erro no Protocolo Silêncio", "EMERGÊNCIA")
        
        # 2. Minimizar janelas abertas
        try:
            pyautogui.hotkey('win', 'd')
            actions_performed.append("Janelas minimizadas")
            self.logger.info("Janelas minimizadas no Protocolo Silêncio", "EMERGÊNCIA")
        except Exception as e:
            errors.append(f"Erro ao minimizar janelas: {e}")
            self.logger.error(e, "Erro no Protocolo Silêncio", "EMERGÊNCIA")
        
        # 3. Tentar fechar abas do navegador (Chrome, Firefox, Edge)
        browsers = ['chrome.exe', 'firefox.exe', 'msedge.exe']
        closed_browsers = []
        
        if not self.wmi_available:
            try:
                global wmi
                if wmi is None:
                    import wmi as _wmi
                    wmi = _wmi
                self.wmi_available = True
            except Exception:
                self.wmi_available = False
        if self.wmi_available and wmi is not None:
            try:
                c = wmi.WMI()
                for process in c.Win32_Process():
                    if process.name.lower() in browsers:
                        process.Terminate()
                        closed_browsers.append(process.name)
                
                if closed_browsers:
                    actions_performed.append(f"Navegadores fechados: {', '.join(closed_browsers)}")
                    self.logger.info(f"Navegadores fechados: {', '.join(closed_browsers)}", "EMERGÊNCIA")
            except Exception as e:
                errors.append(f"Erro ao fechar navegadores: {e}")
                self.logger.error(e, "Erro no Protocolo Silêncio", "EMERGÊNCIA")
        
        # 4. Win+D novamente para restaurar desktop
        try:
            pyautogui.hotkey('win', 'd')
            actions_performed.append("Desktop restaurado")
            self.logger.info("Desktop restaurado no Protocolo Silêncio", "EMERGÊNCIA")
        except Exception as e:
            errors.append(f"Erro ao restaurar desktop: {e}")
            self.logger.error(e, "Erro no Protocolo Silêncio", "EMERGÊNCIA")
        
        # Monta mensagem de resultado
        if actions_performed:
            result = f"🚨 Protocolo Silêncio executado: {', '.join(actions_performed)}"
            self.logger.success(f"Protocolo Silêncio executado: {', '.join(actions_performed)}", "EMERGÊNCIA")
        else:
            result = "🚨 Protocolo Silêncio executado (sem ações)"
        
        if errors:
            result += f"\n⚠️ Erros: {'; '.join(errors)}"
        
        return result
    
    # ==================== MÓDULO DE HARDWARE - MARK 13 ====================
    
    def _send_windows_media_vk(self, vk_code: int, presses: int = 1) -> bool:
        """Envia uma tecla multimídia diretamente pela API do Windows."""
        if os.name != "nt":
            return False
        try:
            user32 = ctypes.windll.user32
            KEYEVENTF_KEYUP = 0x0002
            for _ in range(max(1, int(presses))):
                user32.keybd_event(vk_code, 0, 0, 0)
                user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.025)
            return True
        except Exception as e:
            self.logger.warning(f"Falha ao enviar tecla multimídia: {e}", "HARDWARE")
            return False

    def _read_bound_volume_percent(self):
        try:
            if self.audio_available and hasattr(self, "volume"):
                return max(0, min(int(round(self.volume.GetMasterVolumeLevelScalar() * 100)), 100))
        except Exception:
            return None
        return None

    def _verify_volume_target(self, target: int, tolerance: int = 2, attempts: int = 4):
        actual = None
        for index in range(max(1, int(attempts))):
            actual = self._read_bound_volume_percent()
            if actual is not None and abs(int(actual) - int(target)) <= int(tolerance):
                self.last_known_volume = int(actual)
                return True, int(actual)
            if index + 1 < attempts:
                time.sleep(0.045 + index * 0.025)
        return False, actual

    def set_volume(self, volume_percent: str) -> str:
        """Define *e verifica* o volume master do endpoint padrão atual.

        Build 9: nunca responde sucesso só porque a API aceitou SetVolume.
        Reobtém o endpoint padrão, faz readback com tolerância e tenta um
        fallback por teclas somente quando a verificação falha.
        """
        match = re.search(r"\d+", str(volume_percent))
        if not match:
            return "Especifique um volume de 0 a 100."

        target = int(match.group())
        if target < 0 or target > 100:
            return "O volume deve estar entre 0 e 100%."

        last_actual = None
        # Sempre rebind: o usuário pode ter trocado headset/HDMI/default device.
        for bind_attempt in range(2):
            try:
                self._init_audio_control()
                if self.audio_available and hasattr(self, "volume"):
                    self.volume.SetMute(0, None)
                    self.volume.SetMasterVolumeLevelScalar(target / 100.0, None)
                    ok, actual = self._verify_volume_target(target)
                    last_actual = actual
                    if ok:
                        self.logger.system(
                            f"[HARDWARE] Volume master verificado em {actual}% (alvo {target}%)",
                            "ACTIONS"
                        )
                        return f"Volume do Windows ajustado e verificado em {actual}%."
            except Exception as e:
                self.logger.warning(
                    f"Core Audio falhou ao ajustar/verificar volume (tentativa {bind_attempt + 1}): {e}",
                    "HARDWARE"
                )

        # Fallback físico do Windows. Depois dele tentamos rebind + readback;
        # se não houver telemetria confiável, a resposta deixa claro que não foi
        # possível verificar em vez de fingir sucesso.
        try:
            VK_VOLUME_DOWN = 0xAE
            VK_VOLUME_UP = 0xAF
            if self._send_windows_media_vk(VK_VOLUME_DOWN, presses=60):
                up_presses = int(round(target / 2.0))
                if up_presses:
                    self._send_windows_media_vk(VK_VOLUME_UP, presses=up_presses)
                time.sleep(0.08)
                try:
                    self._init_audio_control()
                except Exception:
                    pass
                ok, actual = self._verify_volume_target(target, tolerance=3, attempts=3)
                last_actual = actual if actual is not None else last_actual
                if ok:
                    self.logger.system(
                        f"[HARDWARE] Volume verificado após fallback: {actual}%",
                        "ACTIONS"
                    )
                    return f"Volume do Windows ajustado e verificado em {actual}%."
        except Exception as e:
            self.logger.error(e, "Erro no fallback de volume", "HARDWARE")

        if last_actual is not None:
            return (
                f"Tentei ajustar o volume para {target}%, mas o Windows continua reportando "
                f"{int(last_actual)}%. Não considerei a ação concluída."
            )
        return f"Tentei ajustar o volume para {target}%, mas não consegui verificar o valor no Windows."

    def get_volume_percent(self):
        """
        Retorna o volume master atual quando Core Audio estiver disponível.

        Se o computador não expuser o endpoint de áudio ao pycaw, retorna a
        última estimativa conhecida pelos comandos locais do JARVIS.
        """
        try:
            if not self.audio_available or not hasattr(self, "volume"):
                self._init_audio_control()

            if self.audio_available and hasattr(self, "volume"):
                try:
                    if hasattr(self, "audio_device"):
                        value = int(round(float(self.audio_device.volume_percent)))
                    else:
                        raise AttributeError
                except Exception:
                    value = int(round(self.volume.GetMasterVolumeLevelScalar() * 100))
                self.last_known_volume = value
                return max(0, min(value, 100))

        except Exception:
            pass

        if self.last_known_volume is not None:
            try:
                return max(
                    0,
                    min(int(self.last_known_volume), 100)
                )
            except Exception:
                pass

        return None

    def get_system_status(self) -> str:
        """Retorna status completo do sistema (CPU, RAM, Disco)"""
        try:
            # Uso da CPU sem sleep artificial. O monitor da GUI ja amostra CPU
            # continuamente; psutil mantem a janela interna entre chamadas.
            cpu_percent = psutil.cpu_percent(interval=None)
            
            # Uso de Memória RAM
            memory = psutil.virtual_memory()
            ram_percent = memory.percent
            ram_used = memory.used / (1024**3)  # GB
            ram_total = memory.total / (1024**3)  # GB
            
            # Uso de Disco
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            disk_used = disk.used / (1024**3)  # GB
            disk_total = disk.total / (1024**3)  # GB
            
            # Monta status
            status = f"""📊 **STATUS DO SISTEMA**
            
🖥️ **CPU**: {cpu_percent:.1f}%
🧠 **RAM**: {ram_percent:.1f}% ({ram_used:.1f}GB / {ram_total:.1f}GB)
💾 **Disco**: {disk_percent:.1f}% ({disk_used:.1f}GB / {disk_total:.1f}GB)
⏰ **Atualizado**: {datetime.now().strftime('%H:%M:%S')}"""
            
            # Registra no System Monitor
            self.logger.system(f"[HARDWARE] CPU: {cpu_percent:.1f}% | RAM: {ram_percent:.1f}% | Disco: {disk_percent:.1f}%", "ACTIONS")
            
            return status
            
        except Exception as e:
            self.logger.error(e, "Erro ao obter status do sistema", "HARDWARE")
            return f"❌ Erro ao obter status: {e}"
    
    def take_screenshot(self, filename: str = None, monitor_index: int = None) -> str:
        """Captura a tela inteira ou um monitor específico e salva em ``capturas``.

        ``pyautogui.screenshot()`` captura somente a tela primária em muitas
        configurações multi-monitor. Quando o usuário informa ``monitor_index``
        usamos MSS, que respeita a geometria real de cada display.
        """
        try:
            capturas_dir = os.path.join(os.getcwd(), "capturas")
            os.makedirs(capturas_dir, exist_ok=True)

            requested_monitor = None
            if monitor_index not in (None, "", 0, "0"):
                requested_monitor = int(monitor_index)
                if requested_monitor < 1:
                    raise ValueError("o número do monitor deve começar em 1")

            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                if requested_monitor:
                    filename = f"captura_monitor_{requested_monitor}_{timestamp}.png"
                else:
                    filename = f"captura_{timestamp}.png"
            elif not str(filename).lower().endswith('.png'):
                filename += '.png'

            filepath = os.path.join(capturas_dir, filename)

            if requested_monitor:
                try:
                    import mss
                    from mss.tools import to_png
                except Exception as exc:
                    raise RuntimeError(
                        "o módulo MSS não está disponível para captura multi-monitor"
                    ) from exc

                with mss.mss() as sct:
                    monitors = list(sct.monitors[1:])
                    if requested_monitor > len(monitors):
                        raise RuntimeError(
                            f"monitor {requested_monitor} não existe; detectei {len(monitors)} monitor(es)"
                        )
                    geometry = monitors[requested_monitor - 1]
                    shot = sct.grab(geometry)
                    to_png(shot.rgb, shot.size, output=filepath)
                self.logger.system(
                    f"[HARDWARE] Screenshot monitor {requested_monitor} salvo: {filepath}",
                    "ACTIONS",
                )
                return f"📸 Screenshot do monitor {requested_monitor} salvo em: {filepath}"

            screenshot = pyautogui.screenshot()
            screenshot.save(filepath)
            self.logger.system(f"[HARDWARE] Screenshot salvo: {filepath}", "ACTIONS")
            return f"📸 Screenshot salvo em: {filepath}"

        except Exception as e:
            self.logger.error(e, "Erro ao capturar tela", "HARDWARE")
            return f"❌ Erro ao capturar tela: {e}"
    
    def generate_password(self, length: int = 16, include_symbols: bool = True) -> str:
        """Gera uma senha forte e segura"""
        try:
            # Define caracteres
            lowercase = string.ascii_lowercase
            uppercase = string.ascii_uppercase
            digits = string.digits
            symbols = "!@#$%^&*()_+-=[]{}|;:,.<>?" if include_symbols else ""
            
            # Combina todos os caracteres
            all_chars = lowercase + uppercase + digits + symbols
            
            # Garante pelo menos um de cada tipo
            password = [
                random.choice(lowercase),
                random.choice(uppercase),
                random.choice(digits),
            ]
            
            if include_symbols:
                password.append(random.choice(symbols))
            
            # Preenche o resto
            remaining_length = length - len(password)
            password.extend(random.choices(all_chars, k=remaining_length))
            
            # Embaralha
            random.shuffle(password)
            
            # Converte para string
            final_password = ''.join(password)
            
            # Tenta copiar para clipboard
            try:
                import pyperclip
                pyperclip.copy(final_password)
                clipboard_msg = " (copiada para área de transferência)"
            except ImportError:
                clipboard_msg = ""
            
            self.logger.system(f"[UTILS] Senha gerada: {len(final_password)} caracteres", "ACTIONS")
            return f"🔐 **Senha forte gerada**{clipboard_msg}:\n`{final_password}`\n\n📏 **Comprimento**: {len(final_password)} caracteres\n🔒 **Segurança**: Alta"
            
        except Exception as e:
            self.logger.error(e, "Erro ao gerar senha", "UTILS")
            return f"❌ Erro ao gerar senha: {e}"
    
    def get_hardware_commands(self) -> Dict[str, str]:
        """Retorna dicionário de comandos de hardware disponíveis"""
        return {
            "volume": "Ajusta volume do sistema (ex: 'volume em 50')",
            "status do sistema": "Mostra uso de CPU, RAM e disco",
            "print": "Captura a tela e salva na pasta capturas",
            "screenshot": "Captura a tela e salva na pasta capturas",
            "gerar senha": "Gera uma senha forte e segura",
            "captura": "Captura a tela e salva na pasta capturas"
        }
    
    # ==================== MÓDULO DE PRODUTIVIDADE - MARK 13 FASE 2 ====================
    
    def translate_text(self, text: str, target_lang: str = 'en') -> str:
        """Traduz texto instantaneamente usando googletrans em thread separada"""
        def translate_thread():
            try:
                from googletrans import Translator
                translator = Translator()
                
                self.logger.system("[PROD] Iniciando tradução: '" + text[:50] + "...'", "ACTIONS")
                
                # Traduz para o inglês
                result = translator.translate(text, dest=target_lang)
                translated_text = result.text
                
                # Detecta idioma original
                original_lang = result.src
                
                self.logger.system(f"[PROD] Tradução concluída: {original_lang} → {target_lang}", "ACTIONS")
                
                # Atualiza resultado na interface através de callback
                if hasattr(self, 'translation_callback'):
                    self.translation_callback(f"🌍 **Tradução** ({original_lang} → {target_lang}):\n\n**Original:** {text}\n\n**Tradução:** {translated_text}")
                
            except Exception as e:
                self.logger.error(e, "Erro na tradução", "PROD")
                if hasattr(self, 'translation_callback'):
                    self.translation_callback(f"❌ Erro ao traduzir: {e}")
        
        try:
            # Executa em thread para não travar a interface
            thread = threading.Thread(target=translate_thread)
            thread.start()
            
            return "🔄 Traduzindo texto, aguarde..."
            
        except ImportError:
            return "❌ Biblioteca googletrans não disponível. Instale com: pip install googletrans==4.0.1"
    
    def set_reminder(self, time_str: str, task: str) -> str:
        """Define um lembrete rápido em thread separada"""
        def reminder_thread():
            try:
                # Extrai minutos da string
                match = re.search(r'(\d+)', time_str)
                if not match:
                    self.logger.error("Tempo inválido", "Erro no lembrete", "PROD")
                    return
                
                minutes = int(match.group())
                
                # Calcula tempo de disparo
                reminder_time = datetime.now() + timedelta(minutes=minutes)
                
                # Adiciona à lista de lembretes
                reminder_id = len(self.reminders) + 1
                self.reminders.append({
                    'id': reminder_id,
                    'task': task,
                    'time': reminder_time,
                    'minutes': minutes
                })
                
                self.logger.system(f"[PROD] Lembrete definido: '{task}' em {minutes} minutos", "ACTIONS")
                
                # Aguarda o tempo
                time.sleep(minutes * 60)
                
                # Dispara o lembrete
                self.trigger_reminder(reminder_id)
                
            except Exception as e:
                self.logger.error(e, "Erro no lembrete", "PROD")
        
        try:
            # Executa em thread
            thread = threading.Thread(target=reminder_thread)
            thread.start()
            
            return f"⏰ **Lembrete definido**: '{task}' em {time_str}"
            
        except Exception as e:
            self.logger.error(e, "Erro ao definir lembrete", "PROD")
            return f"❌ Erro ao definir lembrete: {e}"
    
    def trigger_reminder(self, reminder_id: int):
        """Dispara um lembrete específico"""
        try:
            # Encontra o lembrete
            reminder = None
            for r in self.reminders:
                if r['id'] == reminder_id:
                    reminder = r
                    break
            
            if not reminder:
                return
            
            # Remove da lista de ativos
            self.reminders = [r for r in self.reminders if r['id'] != reminder_id]
            
            # Log especial no System Monitor
            self.logger.warning(f"⏰ **LEMBRETE**: {reminder['task']} (definido há {reminder['minutes']} minutos)", "PROD")
            
            # Tenta mostrar notificação visual
            try:
                import pyautogui
                pyautogui.alert(f"⏰ Lembrete: {reminder['task']}", "J.A.R.V.I.S. - Lembrete")
            except:
                pass
            
        except Exception as e:
            self.logger.error(e, "Erro ao disparar lembrete", "PROD")
    
    def get_currency_rate(self, from_currency: str = 'USD', to_currency: str = 'BRL') -> str:
        """Obtém taxa de câmbio usando yfinance em thread separada"""
        def currency_thread():
            try:
                import yfinance as yf
                
                self.logger.system(f"[PROD] Buscando cotação: {from_currency}/{to_currency}", "ACTIONS")
                
                # Obtém cotação
                ticker = f"{from_currency}{to_currency}=X"
                data = yf.Ticker(ticker).history(period="1d")
                
                if not data.empty:
                    rate = data['Close'].iloc[-1]
                    
                    # Formatação brasileira
                    if to_currency == 'BRL':
                        formatted_rate = f"R$ {rate:.4f}"
                    else:
                        formatted_rate = f"{rate:.4f} {to_currency}"
                    
                    self.logger.system(f"[PROD] Cotação obtida: {from_currency}/{to_currency} = {formatted_rate}", "ACTIONS")
                    
                    # Atualiza através de callback
                    if hasattr(self, 'currency_callback'):
                        self.currency_callback(f"💱 **Cotação Atual**:\n\n**1 {from_currency} = {formatted_rate}**\n\n📊 **Atualizado:** {datetime.now().strftime('%H:%M:%S')}")
                else:
                    if hasattr(self, 'currency_callback'):
                        self.currency_callback(f"❌ Não foi possível obter cotação de {from_currency}/{to_currency}")
                        
            except Exception as e:
                self.logger.error(e, "Erro na cotação", "PROD")
                if hasattr(self, 'currency_callback'):
                    self.currency_callback(f"❌ Erro ao obter cotação: {e}")
        
        try:
            # Executa em thread
            thread = threading.Thread(target=currency_thread)
            thread.start()
            
            return "💱 Buscando cotação, aguarde..."
            
        except ImportError:
            return "❌ Biblioteca yfinance não disponível. Instale com: pip install yfinance"
    
    def get_weather(self, city: str = "Votorantim") -> str:
        """Obtém previsão do tempo usando OpenWeatherMap API em thread separada"""
        def weather_thread():
            try:
                # Chave fora do código. Se não estiver configurada, usa o
                # serviço moderno/fallback de clima em vez de expor segredo.
                API_KEY = str(os.getenv("OPENWEATHER_API_KEY", "") or "").strip()
                BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
                if not API_KEY:
                    if hasattr(self, 'weather_callback'):
                        self.weather_callback("Serviço OpenWeather não configurado. Use a pesquisa web do JARVIS para clima atual ou configure OPENWEATHER_API_KEY no .env.")
                    return
                
                self.logger.system(f"[PROD] Buscando clima para: {city}", "ACTIONS")
                
                # Requisição
                url = f"{BASE_URL}?q={city}&appid={API_KEY}&units=metric&lang=pt_br"
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Extrai informações
                    temp = data['main']['temp']
                    feels_like = data['main']['feels_like']
                    humidity = data['main']['humidity']
                    description = data['weather'][0]['description']
                    city_name = data['name']
                    
                    # Formatação
                    weather_info = f"""🌤️ **Clima Atual - {city_name}**
                    
🌡️ **Temperatura:** {temp}°C (sensação de {feels_like}°C)
💧 **Umidade:** {humidity}%
☁️ **Condição:** {description.title()}
🕐 **Atualizado:** {datetime.now().strftime('%H:%M:%S')}"""
                    
                    self.logger.system(f"[PROD] Clima obtido: {temp}°C em {city_name}", "ACTIONS")
                    return weather_info
                else:
                    return f"❌ Não foi possível obter clima para {city}"
                    
            except Exception as e:
                self.logger.error(e, "Erro ao obter clima", "PROD")
                return f"❌ Erro ao obter clima: {e}"
        
        try:
            # Executa em thread
            thread = threading.Thread(target=weather_thread)
            thread.start()
            
            return f"🌤️ Buscando clima para {city}, aguarde..."
            
        except Exception as e:
            self.logger.error(e, "Erro ao iniciar busca de clima", "PROD")
            return f"❌ Erro ao buscar clima: {e}"
    
    def get_productivity_commands(self) -> Dict[str, str]:
        """Retorna dicionário de comandos de produtividade disponíveis"""
        return {
            "traduzir": "Traduz texto para inglês (ex: 'traduzir hello world')",
            "me lembre": "Define lembrete (ex: 'me lembre em 30 minutos de reunião')",
            "quanto está o dólar": "Mostra cotação atual USD/BRL",
            "tempo hoje": "Mostra previsão do tempo para Votorantim",
            "clima": "Mostra clima atual (ex: 'clima São Paulo')"
        }
    
    # ==================== MÓDULO WEB E SISTEMA AVANÇADO - MARK 13 FINAL ====================
    
    def get_weather_votorantim(self) -> str:
        """Obtém informações climáticas da região de Votorantim usando API wttr.in.
        
        Esta função consulta o serviço wttr.in para obter dados meteorológicos
        da cidade de Sorocaba (próxima a Votorantim), incluindo temperatura,
        umidade e condições do tempo.
        
        Returns:
            str: String formatada com informações do clima ou mensagem de erro
            
        Raises:
            requests.RequestException: Erro de conexão com a API
            ValueError: Erro ao processar dados da API
            KeyError: Dados da API em formato inesperado
        """
        try:
            self.logger.system(f"[PROD] Buscando clima para: Votorantim", "ACTIONS")
            
            # Configurações da API
            config = Config.WEATHER_CONFIG
            url = f"https://wttr.in/{config['fallback_city']}?format=j1"
            
            # Requisição HTTP com timeout
            response = requests.get(url, timeout=config['timeout'])
            
            if response.status_code == 200:
                data = response.json()
                
                # Extrai informações do clima atual com validação
                if 'current_condition' not in data or not data['current_condition']:
                    raise ValueError("Dados da API não contêm informações de clima atual")
                
                current = data['current_condition'][0]
                
                # Validação dos campos obrigatórios
                required_fields = ['temp_C', 'FeelsLikeC', 'humidity', 'weatherDesc']
                for field in required_fields:
                    if field not in current:
                        raise ValueError(f"Campo obrigatório '{field}' não encontrado nos dados")
                
                temp_c = int(current['temp_C'])
                feels_like_c = int(current['FeelsLikeC'])
                humidity = current['humidity']
                description = current['weatherDesc'][0]['value'] if current['weatherDesc'] else 'N/A'
                
                weather_info = f"""🌤️ **Clima Atual - Votorantim/Região**
                
🌡️ **Temperatura:** {temp_c}°C (sensação de {feels_like_c}°C)
💧 **Umidade:** {humidity}%
☁️ **Condição:** {description.title()}
🕐 **Atualizado:** {datetime.now().strftime('%H:%M:%S')}
📡 **Fonte:** wttr.in ({config['fallback_city']})"""
                
                self.logger.system(f"[PROD] Clima obtido: {temp_c}°C na região", "ACTIONS")
                return weather_info
            else:
                self.logger.warning(f"API retornou status {response.status_code}", "PROD")
                return self._get_weather_fallback()
            
        except requests.RequestException as e:
            self.logger.error(e, f"Erro de conexão com API wttr.in: {str(e)}", "PROD")
            return Config.ERROR_MESSAGES["network_error"]
        except (ValueError, KeyError) as e:
            self.logger.error(e, f"Erro ao processar dados do clima: {str(e)}", "PROD")
            return Config.ERROR_MESSAGES["parse_error"]
        except Exception as e:
            self.logger.error(e, "Erro inesperado ao obter clima", "PROD")
            return Config.ERROR_MESSAGES["weather_error"]
    
    def _get_weather_fallback(self) -> str:
        """Retorna mensagem de fallback quando o serviço de clima está indisponível.
        
        Returns:
            str: Mensagem informativa para o usuário
        """
        return f"""🌤️ **Clima - Votorantim**

📍 **Localização:** Votorantim, SP - Brasil
🌡️ **Informação:** Serviço de clima temporariamente indisponível
🔄 **Tente novamente em alguns minutos**
🕐 **Atualizado:** {datetime.now().strftime('%H:%M:%S')}"""
    
    def get_currency_final(self, currency: str) -> str:
        """Obtém cotação de moeda específica em relação ao Real Brasileiro.
        
        Consulta a API Yahoo Finance através da biblioteca yfinance para obter
        a cotação atual da moeda especificada em relação ao BRL.
        
        Args:
            currency (str): Nome da moeda (ex: 'dólar', 'euro', 'bitcoin')
            
        Returns:
            str: String formatada com a cotação atual ou mensagem de erro
            
        Raises:
            ImportError: Se a biblioteca yfinance não estiver disponível
            requests.RequestException: Erro de conexão com a API
            ValueError: Erro ao processar dados da API
            KeyError: Dados da API em formato inesperado
        """
        try:
            import yfinance as yf
            
            # Mapeamento de moedas com validação
            currency_map = {
                'dólar': 'USD',
                'dolar': 'USD',
                'euro': 'EUR',
                'bitcoin': 'BTC',
                'real': 'BRL',
                'peso': 'MXN',
                'libra': 'GBP'
            }
            
            # Normaliza o nome da moeda
            currency_lower = currency.lower()
            from_currency = currency_map.get(currency_lower, currency.upper())
            
            if self.logger:
                self.logger.system(f"[PROD] Buscando cotação: {from_currency}/BRL", "ACTIONS")
            
            # Configurações da API
            config = Config.CURRENCY_CONFIG
            ticker = f"{from_currency}BRL=X"
            
            # Obtém cotação com tratamento de erro
            try:
                data = yf.Ticker(ticker).history(period=config['period'], timeout=config['timeout'])
            except Exception as api_error:
                raise requests.RequestException(f"Erro na API yfinance: {str(api_error)}")
            
            if data.empty:
                self.logger.warning(f"Nenhum dado encontrado para {ticker}", "PROD")
                return Config.ERROR_MESSAGES["currency_error"]
            
            # Extrai e valida o valor da cotação
            if 'Close' not in data.columns:
                raise ValueError("Coluna 'Close' não encontrada nos dados da API")
            
            rate = data['Close'].iloc[-1]
            
            # Validação do valor
            if not isinstance(rate, (int, float)) or rate <= 0:
                raise ValueError(f"Valor de cotação inválido: {rate}")
            
            # Formatação brasileira
            formatted_rate = f"R$ {rate:.4f}"
            
            currency_info = f"""💱 **Cotação Atual - {from_currency.upper()}**

**1 {from_currency.upper()} = {formatted_rate}**

📊 **Atualizado:** {datetime.now().strftime('%H:%M:%S')}
📡 **Fonte:** Yahoo Finance"""
            
            self.logger.system(f"[PROD] Cotação obtida: {from_currency}/BRL = {formatted_rate}", "ACTIONS")
            return currency_info
            
        except ImportError:
            self.logger.error("Biblioteca yfinance não disponível", "PROD")
            return "❌ Biblioteca yfinance não disponível. Instale com: pip install yfinance"
        except requests.RequestException as e:
            self.logger.error(e, f"Erro de conexão com API de cotação: {str(e)}", "PROD")
            return Config.ERROR_MESSAGES["network_error"]
        except (ValueError, KeyError) as e:
            if self.logger:
                self.logger.error(e, f"Erro ao processar dados de cotação: {str(e)}", "PROD")
            return Config.ERROR_MESSAGES["parse_error"]
        except Exception as e:
            if self.logger:
                self.logger.error(e, "Erro inesperado ao obter cotação", "PROD")
            return Config.ERROR_MESSAGES["currency_error"]
    
    def get_news_headlines(self) -> str:
        """Obtém as principais manchetes do dia através de web scraping do portal G1.
        
        Esta função utiliza web scraping para extrair as 3 principais notícias
        do portal G1, fornecendo um resumo atualizado dos acontecimentos
        mais relevantes do dia.
        
        Returns:
            str: String formatada com as 3 principais manchetes ou mensagem de erro
            
        Raises:
            requests.RequestException: Erro de conexão com o site G1
            ValueError: Erro ao processar HTML da página
            Exception: Erro inesperado durante o scraping
        """
        try:
            self.logger.system("[PROD] Buscando notícias principais...", "ACTIONS")
            
            # Configurações da API
            config = Config.NEWS_CONFIG
            url = config['url']
            headers = {'User-Agent': config['user_agent']}
            
            # Requisição HTTP com timeout
            response = requests.get(url, headers=headers, timeout=config['timeout'])
            
            if response.status_code != 200:
                self.logger.warning(f"Portal G1 retornou status {response.status_code}", "PROD")
                return Config.ERROR_MESSAGES["news_error"]
            
            # Parse do HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Busca manchetes principais com múltiplos seletores
            headlines = []
            selectors = [
                '.feed-post-body-title',
                '.feed-post-link',
                'h2 a',
                '.title a',
                '[data-area="noticias"] h2 a'
            ]
            
            for selector in selectors:
                try:
                    elements = soup.select(selector)[:config['max_headlines']]
                    for element in elements:
                        title = element.get_text(strip=True)
                        # Validação do título
                        if title and len(title) > 10 and len(title) < 200:
                            # Remove caracteres problemáticos
                            clean_title = re.sub(r'[^\w\s\-.,!?;:]', '', title).strip()
                            if clean_title:
                                headlines.append(f"📰 {clean_title}")
                                if len(headlines) >= config['max_headlines']:
                                    break
                    if len(headlines) >= config['max_headlines']:
                        break
                except Exception as selector_error:
                    self.logger.warning(f"Erro no seletor {selector}: {str(selector_error)}", "PROD")
                    continue
            
            # Validação das manchetes encontradas
            if not headlines:
                self.logger.warning("Nenhuma manchete válida encontrada", "PROD")
                return Config.ERROR_MESSAGES["news_error"]
            
            # Formatação do resultado
            news_info = f"""📰 **Principais Notícias do Dia**
            
{chr(10).join(headlines[:config['max_headlines']])}

📊 **Fonte:** G1
🕐 **Atualizado:** {datetime.now().strftime('%H:%M:%S')}"""
            
            self.logger.system("[PROD] Notícias obtidas com sucesso", "ACTIONS")
            return news_info
            
        except requests.RequestException as e:
            self.logger.error(e, f"Erro de conexão com portal G1: {str(e)}", "PROD")
            return Config.ERROR_MESSAGES["network_error"]
        except ValueError as e:
            self.logger.error(e, f"Erro ao processar HTML do G1: {str(e)}", "PROD")
            return Config.ERROR_MESSAGES["parse_error"]
        except Exception as e:
            self.logger.error(e, "Erro inesperado ao buscar notícias", "PROD")
            return Config.ERROR_MESSAGES["news_error"]
    
    def empty_recycle_bin(self) -> str:
        """Esvazia a lixeira do Windows"""
        try:
            self.logger.system("[PROD] Esvaziando lixeira...", "ACTIONS")
            
            # Caminho da lixeira
            import os
            recycle_bin = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop', 'Recycle Bin')
            
            if os.path.exists(recycle_bin):
                # Limpa a lixeira
                import shutil
                shutil.rmtree(recycle_bin)
                
                self.logger.system("[PROD] Lixeira esvaziada com sucesso", "ACTIONS")
                return "🗑️ **Lixeira esvaziada** com sucesso!"
            else:
                return "❌ Lixeira não encontrada"
                
        except Exception as e:
            self.logger.error(e, "Erro ao esvaziar lixeira", "PROD")
            return f"❌ Erro ao esvaziar lixeira: {e}"
    
    def adjust_brightness(self, action: str) -> str:
        """Controla o brilho da tela"""
        try:
            self.logger.system(f"[PROD] Ajustando brilho: {action}", "ACTIONS")
            
            if action.lower() in ['aumentar', 'aumentar brilho', 'mais brilho', 'bright']:
                # Aumenta brilho
                current = sbc.get_brightness()
                new_brightness = min(100, current + 10)
                sbc.set_brightness(new_brightness)
                
                self.logger.system(f"[PROD] Brilho aumentado para {new_brightness}%", "ACTIONS")
                return f"💡 **Brilho aumentado** para {new_brightness}%"
                
            elif action.lower() in ['diminuir', 'diminuir brilho', 'menos brilho', 'dark']:
                # Diminui brilho
                current = sbc.get_brightness()
                new_brightness = max(0, current - 10)
                sbc.set_brightness(new_brightness)
                
                self.logger.system(f"[PROD] Brilho diminuído para {new_brightness}%", "ACTIONS")
                return f"🔅 **Brilho diminuído** para {new_brightness}%"
                
            else:
                return "❌ Comando inválido. Use 'aumentar brilho' ou 'diminuir brilho'"
                
        except Exception as e:
            self.logger.error(e, "Erro ao ajustar brilho", "PROD")
            return f"❌ Erro ao ajustar brilho: {e}"
    
    def get_top_processes(self) -> str:
        """Lista os 5 processos que mais consomem memória"""
        try:
            self.logger.system("[PROD] Listando processos mais consumidos...", "ACTIONS")
            
            # Obtém todos os processos
            processes = []
            
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    mem_info = proc.memory_info()
                    if mem_info:
                        memory_mb = mem_info.rss / (1024 * 1024)  # Convert to MB
                        processes.append({
                            'name': proc.info['name'],
                            'memory': memory_mb,
                            'pid': proc.info['pid']
                        })
                except:
                    continue
            
            # Ordena por consumo de memória (maior para menor)
            processes.sort(key=lambda x: x['memory'], reverse=True)
            
            # Pega os 5 maiores
            top_5 = processes[:5]
            
            process_info = f"""📊 **Top 5 Processos (Consumo de RAM)**
            
"""
            
            for i, proc in enumerate(top_5, 1):
                process_info += f"{i}. **{proc['name']}** - {proc['memory']:.1f} MB (PID: {proc['pid']})\n"
            
            process_info += f"""
📊 **Total RAM em uso:** {psutil.virtual_memory().percent:.1f}%
🕐 **Atualizado:** {datetime.now().strftime('%H:%M:%S')}"""
            
            self.logger.system("[PROD] Lista de processos obtida", "ACTIONS")
            return process_info
            
        except Exception as e:
            self.logger.error(e, "Erro ao listar processos", "PROD")
            return f"❌ Erro ao listar processos: {e}"
    
    def play_spotify(self, query: str) -> str:
        """Abre uma busca do Spotify sem exigir API do Spotify."""
        query = (query or "").strip()
        if not query:
            return "Qual música devo procurar no Spotify?"
        try:
            encoded = requests.utils.quote(query)
            try:
                os.startfile(f"spotify:search:{encoded}")
                return f"Abrindo a busca por {query} no Spotify."
            except Exception:
                return self.open_url_in_opera_gx(f"https://open.spotify.com/search/{encoded}")
        except Exception as e:
            return f"Não consegui abrir o Spotify: {e}"

    def _find_opera_gx(self):
        """Localiza o Opera GX com fast-cache antes de varrer o Windows."""
        cached_runtime = str(getattr(self, "_opera_gx_path_cache", "") or "").strip()
        if cached_runtime and (
            os.path.isfile(cached_runtime)
            or cached_runtime.lower().endswith((".lnk", ".url")) and os.path.exists(cached_runtime)
        ):
            return cached_runtime

        # Reaproveita o mesmo cache seguro de `open_application`. Isso evita
        # executar `where`/varrer o Menu Iniciar a cada comando "pesquisa no
        # Opera", que era um atraso desnecessário no caminho mais usado.
        for cache_name in ("opera gx", "opera"):
            try:
                cached = str(self.app_cache.get(self._normalize_app_name(cache_name)) or "").strip()
            except Exception:
                cached = ""
            if cached and os.path.exists(cached):
                self._opera_gx_path_cache = cached
                return cached

        def remember(path: str):
            self._opera_gx_path_cache = path
            try:
                self._cache_app("Opera GX", path)
                self._cache_app("Opera", path)
            except Exception:
                pass
            return path

        candidates = [
            os.path.join(
                os.getenv("LOCALAPPDATA", ""),
                "Programs",
                "Opera GX",
                "opera.exe"
            ),
            os.path.join(
                os.getenv("PROGRAMFILES", r"C:\Program Files"),
                "Opera GX",
                "opera.exe"
            ),
            os.path.join(
                os.getenv("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                "Opera GX",
                "opera.exe"
            ),
        ]

        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return remember(candidate)

        # Tenta localizar pelo PATH.
        try:
            result = subprocess.run(
                ["where", "opera.exe"],
                capture_output=True,
                text=True,
                timeout=3
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line and os.path.isfile(line):
                        return remember(line)
        except Exception:
            pass

        # Procura atalhos do Opera GX no Menu Iniciar.
        start_menu_paths = [
            os.path.join(
                os.getenv("APPDATA", ""),
                "Microsoft",
                "Windows",
                "Start Menu",
                "Programs"
            ),
            os.path.join(
                os.getenv("PROGRAMDATA", r"C:\ProgramData"),
                "Microsoft",
                "Windows",
                "Start Menu",
                "Programs"
            ),
        ]

        for start_path in start_menu_paths:
            if not os.path.isdir(start_path):
                continue

            for root, _, files in os.walk(start_path):
                for file in files:
                    name = file.lower()
                    if (
                        name.endswith(".lnk")
                        and "opera" in name
                        and "gx" in name
                    ):
                        return remember(os.path.join(root, file))

        return None

    def open_url_in_opera_gx(self, url: str) -> str:
        """Abre uma URL especificamente no Opera GX."""
        try:
            opera_path = self._find_opera_gx()

            if not opera_path:
                return (
                    "Não encontrei o Opera GX instalado neste computador."
                )

            self.logger.system(
                f"[MEDIA] Abrindo no Opera GX: {url}",
                "ACTIONS"
            )

            # O objetivo e abrir a URL no Opera, nao no navegador padrao. Se o
            # resolver encontrou um atalho .lnk, passa a URL como argumento ao
            # proprio atalho. Executavel recebe a URL diretamente.
            if opera_path.lower().endswith(".lnk"):
                subprocess.Popen(
                    ["cmd", "/d", "/c", "start", "", opera_path, url],
                    shell=False
                )
            else:
                subprocess.Popen([opera_path, url], shell=False)

            return "✓ URL aberta no Opera GX."

        except Exception as e:
            self.logger.error(
                e,
                "Erro ao abrir URL no Opera GX",
                "ACTIONS"
            )
            return f"Não consegui abrir o Opera GX: {e}"

    def open_youtube(self) -> str:
        """Abre o YouTube diretamente no Opera GX."""
        result = self.open_url_in_opera_gx("https://www.youtube.com/")

        if result.startswith("Não"):
            return result

        return "YouTube aberto no Opera GX."

    def _find_youtube_video(self, query: str):
        """Busca vários resultados e escolhe o mais compatível com a música pedida."""
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(
                "A biblioteca yt-dlp não está instalada. "
                "Execute: python -m pip install -U yt-dlp"
            )

        clean_query = " ".join(str(query or "").split()).strip()
        query_key = self._normalize_app_name(clean_query)
        query_tokens = set(query_key.split())
        options = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "noplaylist": True,
        }
        # "official" reduz reações/podcasts sem impedir faixas que não tenham clipe oficial.
        search_query = f"ytsearch8:{clean_query} official"
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(search_query, download=False)

        entries = (info or {}).get("entries") or []
        if not entries:
            return None, None

        bad_terms = {"reaction", "reacao", "reação", "karaoke", "cover", "podcast", "news", "shorts", "tutorial"}
        wanted_bad = bad_terms & query_tokens
        scored = []
        for index, item in enumerate(entries):
            item = item or {}
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            title_key = self._normalize_app_name(title)
            title_tokens = set(title_key.split())
            overlap = len(query_tokens & title_tokens) / max(1, len(query_tokens))
            ratio = difflib.SequenceMatcher(None, query_key, title_key).ratio()
            score = overlap * 0.68 + ratio * 0.32
            if "official" in title_key or "audio" in title_key or "video" in title_key:
                score += 0.08
            if not wanted_bad and any(term in title_key for term in bad_terms):
                score -= 0.32
            # Pequeno desempate a favor dos primeiros resultados do YouTube.
            score -= index * 0.004
            scored.append((score, item, title))

        if not scored:
            return None, None
        scored.sort(key=lambda x: x[0], reverse=True)
        score, first, title = scored[0]
        video_id = first.get("id")
        url = first.get("url")
        if video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
        elif url and str(url).startswith("http"):
            separator = "&" if "?" in str(url) else "?"
            video_url = f"{url}{separator}autoplay=1"
        else:
            return None, None

        self.logger.info(
            f"[MEDIA] Melhor resultado YouTube score={score:.2f}: {title}",
            "ACTIONS"
        )
        return title, video_url

    def play_music(self, query: str) -> str:
        """
        Pesquisa a música no YouTube e abre diretamente o primeiro
        resultado no Opera GX.
        """
        query = (query or "").strip()

        if not query:
            return "Qual música devo tocar?"

        try:
            self.logger.system(
                f"[MEDIA] Procurando no YouTube: {query}",
                "ACTIONS"
            )

            try:
                title, video_url = self._find_youtube_video(query)
            except Exception as search_exc:
                title, video_url = None, None
                self.logger.warning(
                    f"[MEDIA] yt-dlp falhou; usando busca direta: {search_exc}",
                    "ACTIONS"
                )

            if not video_url:
                encoded = requests.utils.quote(query)
                video_url = f"https://www.youtube.com/results?search_query={encoded}"
                title = query

            opera_path = self._find_opera_gx()

            if not opera_path:
                return (
                    "Encontrei a música no YouTube, mas não encontrei "
                    "o Opera GX instalado neste computador."
                )

            if opera_path.lower().endswith(".lnk"):
                # Tenta resolver o Opera instalado por caminhos comuns novamente.
                # Se só houver o atalho, abre a URL pelo shell após iniciar o Opera.
                os.startfile(opera_path)
                time.sleep(1.0)
                os.startfile(video_url)
            else:
                subprocess.Popen(
                    [opera_path, video_url],
                    shell=False
                )

            self.logger.info(
                f"[MEDIA] Reproduzindo no Opera GX: {title} - {video_url}",
                "ACTIONS"
            )

            return f"Reproduzindo {title} no YouTube pelo Opera GX."

        except Exception as e:
            self.logger.error(
                e,
                f"Erro ao reproduzir música: {query}",
                "ACTIONS"
            )

            return (
                f"Não consegui reproduzir '{query}' no YouTube: {e}"
            )


    def choose_music(self) -> str:
        """Escolha curada do JARVIS, evitando busca vaga/resultado aleatório."""
        choices = [
            ("Bon Jovi - Livin on a Prayer official video", "Bon Jovi - Livin' on a Prayer"),
            ("System of a Down - Chop Suey official video", "System of a Down - Chop Suey!"),
            ("Linkin Park - In the End official video", "Linkin Park - In the End"),
            ("Foo Fighters - The Pretender official video", "Foo Fighters - The Pretender"),
            ("Queen - Dont Stop Me Now official video", "Queen - Don't Stop Me Now"),
            ("a-ha - Take On Me official video", "a-ha - Take On Me"),
            ("The Killers - Mr Brightside official video", "The Killers - Mr. Brightside"),
            ("Guns N Roses - Sweet Child O Mine official video", "Guns N' Roses - Sweet Child O' Mine"),
        ]
        # Rotação previsível: o JARVIS escolhe uma faixa curada e não um termo aleatório.
        last = self._last_music_choice
        idx = 0
        if last:
            for i, (_, display) in enumerate(choices):
                if display == last:
                    idx = (i + 1) % len(choices)
                    break
        query, picked = choices[idx]
        self._last_music_choice = picked
        result = self.play_music(query)
        if result.lower().startswith(("nao", "não")):
            return result
        return f"Escolhi {picked}. {result}"

    def media_play_pause(self, target_hint: str = None) -> str:
        """Alterna play/pause, podendo direcionar a um player específico."""
        try:
            if target_hint and self._send_media_appcommand(14, target_hint):
                return f"Comando de play/pause enviado ao {target_hint}."

            VK_MEDIA_PLAY_PAUSE = 0xB3
            if self._send_windows_media_vk(VK_MEDIA_PLAY_PAUSE):
                self.logger.info("[MEDIA] VK_MEDIA_PLAY_PAUSE enviado ao Windows", "ACTIONS")
                return "Play/pause enviado ao player ativo do Windows."

            if self._send_opera_youtube_shortcut("k"):
                return "Play/pause enviado ao YouTube."

            pyautogui.press("playpause")
            return "Play/pause enviado ao player ativo."
        except Exception as e:
            self.logger.error(e, "Erro em play/pause", "MEDIA")
            return f"Não consegui pausar ou continuar a mídia: {e}"

    def media_pause(self, target_hint: str = None) -> str:
        """Pausa sem usar toggle quando há um player direcionado compatível."""
        try:
            if target_hint and self._send_media_appcommand(47, target_hint):
                return f"Comando de pausa enviado ao {target_hint}."
            # Sem alvo conhecido, a tecla multimídia global ainda é o fallback
            # mais compatível entre Spotify, navegadores e players desktop.
            return self.media_play_pause(target_hint=None)
        except Exception as e:
            self.logger.error(e, "Erro ao pausar mídia", "MEDIA")
            return f"Não consegui pausar a mídia: {e}"

    def media_play(self, target_hint: str = None) -> str:
        """Retoma reprodução sem usar toggle quando há alvo compatível."""
        try:
            if target_hint and self._send_media_appcommand(46, target_hint):
                return f"Comando de reprodução enviado ao {target_hint}."
            return self.media_play_pause(target_hint=None)
        except Exception as e:
            self.logger.error(e, "Erro ao continuar mídia", "MEDIA")
            return f"Não consegui continuar a mídia: {e}"

    def media_next_track(self, target_hint: str = None) -> str:
        try:
            if target_hint and self._send_media_appcommand(11, target_hint):
                return f"Comando de próxima faixa enviado ao {target_hint}."
            if self._send_windows_media_vk(0xB0):
                return "Comando de próxima faixa enviado ao player ativo."
            if self._send_opera_youtube_shortcut("shift", "n"):
                return "Indo para a próxima música no YouTube."
            pyautogui.press("nexttrack")
            return "Próxima faixa."
        except Exception as e:
            return f"Não consegui avançar a faixa: {e}"

    def media_previous_track(self, target_hint: str = None) -> str:
        try:
            if target_hint and self._send_media_appcommand(12, target_hint):
                return f"Comando de faixa anterior enviado ao {target_hint}."
            if self._send_windows_media_vk(0xB1):
                return "Comando de faixa anterior enviado ao player ativo."
            if self._send_opera_youtube_shortcut("shift", "p"):
                return "Voltando para a música anterior no YouTube."
            pyautogui.press("prevtrack")
            return "Faixa anterior."
        except Exception as e:
            return f"Não consegui voltar a faixa: {e}"

    def media_stop(self, target_hint: str = None) -> str:
        try:
            if target_hint and self._send_media_appcommand(13, target_hint):
                return f"Comando de parar enviado ao {target_hint}."
            if self._send_opera_youtube_shortcut("k"):
                return "Música pausada no YouTube."
            pyautogui.press("stop")
            return "Mídia interrompida."
        except Exception as e:
            return f"Não consegui interromper a mídia: {e}"

    def media_volume_up(self, steps: int = 2) -> str:
        """Aumenta o volume do Windows usando tecla multimídia."""
        try:
            steps = max(1, min(int(steps), 20))
            if not self._send_windows_media_vk(0xAF, presses=steps):
                pyautogui.press("volumeup", presses=steps, interval=0.05)
            self.logger.info(
                f"[MEDIA] Volume aumentado em {steps} passos",
                "ACTIONS"
            )
            return "Volume aumentado."
        except Exception as e:
            self.logger.error(
                e,
                "Erro ao aumentar volume",
                "ACTIONS"
            )
            return f"Não consegui aumentar o volume: {e}"

    def media_volume_down(self, steps: int = 2) -> str:
        """Diminui o volume do Windows usando tecla multimídia."""
        try:
            steps = max(1, min(int(steps), 20))
            if not self._send_windows_media_vk(0xAE, presses=steps):
                pyautogui.press("volumedown", presses=steps, interval=0.05)
            self.logger.info(
                f"[MEDIA] Volume reduzido em {steps} passos",
                "ACTIONS"
            )
            return "Volume reduzido."
        except Exception as e:
            self.logger.error(
                e,
                "Erro ao reduzir volume",
                "ACTIONS"
            )
            return f"Não consegui diminuir o volume: {e}"

    def media_mute(self) -> str:
        try:
            if self._send_windows_media_vk(0xAD):
                return "Mudo do Windows alternado."
            if self._send_opera_youtube_shortcut("m"):
                return "Mudo do YouTube alternado."
            pyautogui.press("volumemute")
            return "Mudo alternado."
        except Exception as e:
            return f"Não consegui alterar o mudo: {e}"

    def start_pomodoro_timer(self, task: str = "Estudo") -> str:
        """Inicia um timer Pomodoro de 25 minutos"""
        def pomodoro_thread():
            try:
                self.logger.system(f"[PROD] Iniciando Pomodoro: {task}", "ACTIONS")
                
                # Timer de 25 minutos
                minutes = 25
                seconds = minutes * 60
                
                # Aguarda o tempo
                time.sleep(seconds)
                
                # Dispara o alarme
                self.logger.warning(f"⏰ **POMODORO**: {task} - 25 minutos concluídos!", "PROD")
                
                # Alerta visual
                try:
                    import pyautogui
                    pyautogui.alert(f"⏰ Pomodoro Concluído!", f"{task} - 25 minutos")
                except:
                    pass
                
                return f"⏰ **Pomodoro concluído**: {task}"
                
            except Exception as e:
                self.logger.error(e, "Erro no Pomodoro", "PROD")
                return f"❌ Erro no Pomodoro: {e}"
        
        try:
            # Executa em thread
            thread = threading.Thread(target=pomodoro_thread)
            thread.start()
            
            return f"⏰ **Pomodoro iniciado**: {task} - 25 minutos"
            
        except Exception as e:
            self.logger.error(e, "Erro ao iniciar Pomodoro", "PROD")
            return f"❌ Erro ao iniciar Pomodoro: {e}"
    
    def get_final_commands(self) -> Dict[str, str]:
        """Retorna dicionário de comandos finais disponíveis"""
        return {
            # Web
            "tempo hoje": "Mostra clima de Votorantim",
            "notícias": "Mostra 3 principais manchetes do dia",
            
            # Moedas
            "dólar": "Mostra cotação do dólar",
            "euro": "Mostra cotação do euro",
            "bitcoin": "Mostra cotação do bitcoin",
            
            # Sistema Avançado
            "limpar lixeira": "Esvazia a lixeira do Windows",
            "aumentar brilho": "Aumenta o brilho da tela",
            "diminuir brilho": "Diminui o brilho da tela",
            "processos": "Lista os 5 apps que mais consomem RAM",
            
            # Entretenimento
            "tocar": "Busca e abre música no YouTube",
            "pomodoro": "Inicia timer de estudo de 25 minutos"
        }
