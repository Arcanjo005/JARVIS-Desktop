"""JARVIS Desktop 1.2.1 Chat Core / Blue Core UI polish layer.

This module is imported by jarvis_version.py.  It keeps the known-good v1.1.2
startup path intact while applying narrowly-scoped, fail-open fixes discovered
from real 1.1.3/1.1.4 field diagnostics and the 1.2.0 chat redesign.

Every patch is defensive: failure to apply an enhancement must never prevent
JARVIS from starting.
"""
from __future__ import annotations

import builtins
import hashlib
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

RELEASE_LAYER = "1.2.1-ui-polish2-compat"

_ORIGINAL_IMPORT = builtins.__import__
_IMPORT_WRAPPED = False
_APPLYING = False
_PATCHED = set()


_MACHINE_COMPAT = {}


def _apply_machine_compatibility() -> None:
    """Conservative cross-PC defaults for Windows.

    Public version remains 1.2.1. Explicit user settings always win.
    """
    global _MACHINE_COMPAT
    info = {
        "windows": os.name == "nt",
        "cpu_threads": max(1, int(os.cpu_count() or 1)),
        "cuda_driver": False,
        "whisper_device": "auto",
        "whisper_compute": "auto",
        "profile": "default",
    }
    if os.name != "nt":
        _MACHINE_COMPAT = info
        return

    cuda_driver = False
    try:
        import ctypes
        ctypes.WinDLL("nvcuda.dll")
        cuda_driver = True
    except Exception:
        cuda_driver = False

    cpu_count = max(1, int(os.cpu_count() or 1))
    safe_threads = max(2, min(6, cpu_count // 2 if cpu_count >= 4 else cpu_count))
    os.environ.setdefault("OMP_NUM_THREADS", str(safe_threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(safe_threads))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    if not cuda_driver:
        # Intel UHD / AMD integrated graphics are not CUDA devices.
        os.environ.setdefault("JARVIS_WHISPER_DEVICE", "cpu")
        os.environ.setdefault("JARVIS_WHISPER_COMPUTE_TYPE", "int8")
        os.environ.setdefault("JARVIS_WHISPER_MODEL", "base")
        os.environ.setdefault("JARVIS_WHISPER_SECOND_PASS", "0")
        profile = "windows-cpu-safe"
    else:
        profile = "windows-cuda-auto"

    # First connection on a different PC can be slower because of DNS/TLS.
    os.environ.setdefault("JARVIS_GEMINI_SOFT_FIRST_TOKEN_MS", "3000")
    os.environ.setdefault("JARVIS_GEMINI_FIRST_TOKEN_MS", "7500")
    os.environ.setdefault("JARVIS_GEMINI_TOTAL_MS", "14000")

    info.update(
        cuda_driver=bool(cuda_driver),
        whisper_device=os.environ.get("JARVIS_WHISPER_DEVICE", "auto"),
        whisper_compute=os.environ.get("JARVIS_WHISPER_COMPUTE_TYPE", "auto"),
        profile=profile,
        safe_threads=safe_threads,
    )
    _MACHINE_COMPAT = info


_apply_machine_compatibility()



def _pyinstaller_collect_dynamic_modules():
    """Static import hints for PyInstaller; this function is intentionally never called."""
    import advanced_windows  # noqa: F401
    import safety_manager  # noqa: F401
    import audio_device_manager  # noqa: F401
    import vision_system  # noqa: F401
    import diagnostics_manager  # noqa: F401
    import operational_context  # noqa: F401
    import workflow_engine  # noqa: F401
    import conditional_rules  # noqa: F401
    import browser_autonomy  # noqa: F401
    import media_context  # noqa: F401
    import goal_executor  # noqa: F401
    import observer_engine  # noqa: F401
    import experience_engine  # noqa: F401
    import behavior_memory  # noqa: F401
    import performance_tracer  # noqa: F401
    import voice_engine  # noqa: F401
    import context_engine  # noqa: F401
    import send2trash  # noqa: F401
    import yt_dlp  # noqa: F401


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _safe_log(instance, level: str, message: str, source: str = "RELEASE") -> None:
    try:
        logger = getattr(instance, "logger", None)
        fn = getattr(logger, level, None)
        if callable(fn):
            try:
                fn(message, source)
            except TypeError:
                fn(message)
    except Exception:
        pass


def _local_outcome(gui, message: str, success: bool = True, verified: bool | None = None):
    if verified is None:
        verified = success
    try:
        gui.add_message(getattr(sys.modules.get("gui"), "PUBLIC_NAME", "JARVIS"), message, is_jarvis=True)
    except Exception:
        pass
    return {
        "handled": True,
        "success": bool(success),
        "verified": bool(verified),
        "message": str(message),
    }


def _patch_router() -> None:
    mod = sys.modules.get("jarvis_router")
    if mod is None or "router" in _PATCHED:
        return
    original = getattr(mod, "route", None)
    route_cls = getattr(mod, "V8Route", None)
    router = getattr(mod, "_ROUTER", None)
    if not callable(original) or route_cls is None:
        return

    def local(command: str, intent: str):
        return route_cls("local", [command], intent=intent)

    def patched_route(text):
        raw = " ".join(str(text or "").split()).strip()
        key = _norm(raw)
        if not key:
            return original(text)

        # Conversa curta deve ser instantânea e local, não depender do Gemini.
        if key in {"eai", "eae", "eaee", "e ai", "oi jarvis", "fala jarvis"}:
            return local("v8:social_chat", "SOCIAL_CHAT")

        # Formas naturais que o parser antigo não reconhecia como telemetria.
        if key in {
            "qual sua latencia", "qual e sua latencia", "qual a sua latencia",
            "qual seu tempo de resposta", "quanto voce demora para responder",
            "quanto demora para responder", "como esta sua latencia",
        }:
            return local("v8:performance", "PERFORMANCE")

        # Ajuda amigável, em vez de lista interna de engenharia.
        if key in {
            "ajuda", "me ajuda", "como usar o jarvis", "como eu uso o jarvis",
            "comandos do jarvis", "guia do jarvis", "o que posso pedir",
        }:
            return local("v8:capabilities", "CAPABILITIES")

        # Uma referência curta de monitor agora seleciona contexto em vez de
        # presumir que o usuário pediu análise visual daquela tela.
        m = re.fullmatch(r"(?:monitor|tela|display)\s*(\d+)", key)
        if m:
            number = max(1, int(m.group(1)))
            try:
                if router is not None:
                    router._remember_monitor(number)
            except Exception:
                pass
            return local(f"v8:monitor_focus:{number}", "MONITOR_CONTEXT")
        ordinal = {
            "primeiro monitor": 1, "primeira tela": 1,
            "segundo monitor": 2, "segunda tela": 2,
            "terceiro monitor": 3, "terceira tela": 3,
            "quarto monitor": 4, "quarta tela": 4,
        }
        if key in ordinal:
            number = ordinal[key]
            try:
                if router is not None:
                    router._remember_monitor(number)
            except Exception:
                pass
            return local(f"v8:monitor_focus:{number}", "MONITOR_CONTEXT")

        # Pedido incompleto deve gerar uma pergunta, não cair no LEGACY e falhar.
        if key in {"faz uma pasta", "faca uma pasta", "cria uma pasta", "crie uma pasta", "criar uma pasta"}:
            return local("v8:clarify_folder_name", "CREATE_FOLDER_DIALOG")

        # Controles comuns de navegador/vídeo.
        media_phrases = {
            "pausa youtube": "pause|youtube", "pausa o youtube": "pause|youtube",
            "pause youtube": "pause|youtube", "pause o youtube": "pause|youtube",
            "pausa o video": "pause|", "pausa video": "pause|",
            "pause o video": "pause|", "pause video": "pause|",
            "continua youtube": "play|youtube", "continua o youtube": "play|youtube",
            "play youtube": "play|youtube", "play o youtube": "play|youtube",
            "continua o video": "play|", "continua video": "play|",
            "play o video": "play|", "play video": "play|",
        }
        if key in media_phrases:
            return local("v8:release_media:" + media_phrases[key], "PLAYER_CONTROL")

        return original(text)

    mod.route = patched_route
    # GUI may already have copied the old function reference.
    gui_mod = sys.modules.get("gui")
    if gui_mod is not None:
        try:
            gui_mod.route_v8 = patched_route
        except Exception:
            pass
    _PATCHED.add("router")


def _patch_context_engine() -> None:
    mod = sys.modules.get("context_engine")
    if mod is None or "context" in _PATCHED:
        return
    cls = getattr(mod, "ContextEngine", None)
    if cls is None:
        return
    original = getattr(cls, "undo_command", None)
    if not callable(original):
        return

    def undo_command(self):
        try:
            with self._lock:
                for ref in reversed(self._actions):
                    if ref.action in {"CREATE_TEXT", "CREATE_FOLDER"}:
                        path = str((ref.after or {}).get("path") or ref.target or "").strip()
                        if path:
                            return "v8:release_undo_created:" + path.replace("|", " ")
        except Exception:
            pass
        return original(self)

    cls.undo_command = undo_command
    _PATCHED.add("context")


def _patch_actions() -> None:
    mod = sys.modules.get("actions")
    if mod is None or "actions" in _PATCHED:
        return
    cls = getattr(mod, "SystemActions", None)
    if cls is None:
        return

    # Make the YouTube fallback honest.  If yt-dlp is unavailable, opening a
    # search page is useful but is not the same as confirmed playback.
    original_play_music = getattr(cls, "play_music", None)
    if callable(original_play_music):
        def play_music(self, query: str):
            query = (query or "").strip()
            if not query:
                return "Qual música devo tocar?"
            try:
                title = video_url = None
                search_error = ""
                try:
                    title, video_url = self._find_youtube_video(query)
                except Exception as exc:
                    search_error = str(exc)
                if not video_url:
                    try:
                        import requests
                        encoded = requests.utils.quote(query)
                    except Exception:
                        from urllib.parse import quote
                        encoded = quote(query)
                    search_url = f"https://www.youtube.com/results?search_query={encoded}"
                    result = self.open_url_in_opera_gx(search_url)
                    if str(result).lower().startswith(("nao", "não", "erro", "falha")):
                        return result
                    if search_error:
                        _safe_log(self, "warning", f"yt-dlp indisponível; abri busca do YouTube: {search_error}", "MEDIA")
                    return f"✓ Busca por {query} aberta no YouTube pelo Opera GX. Escolha um resultado para reproduzir."

                opera_path = self._find_opera_gx()
                if not opera_path:
                    return "Encontrei a música no YouTube, mas não encontrei o Opera GX instalado neste computador."
                if str(opera_path).lower().endswith(".lnk"):
                    os.startfile(opera_path)
                    time.sleep(0.8)
                    os.startfile(video_url)
                else:
                    import subprocess
                    subprocess.Popen([opera_path, video_url], shell=False)
                _safe_log(self, "info", f"YouTube direto: {title} - {video_url}", "MEDIA")
                return f"✓ Reproduzindo {title or query} no YouTube pelo Opera GX."
            except Exception as exc:
                return f"Não consegui abrir '{query}' no YouTube: {exc}"
        cls.play_music = play_music

    _PATCHED.add("actions")



def _patch_core() -> None:
    mod = sys.modules.get("core")
    if mod is None or "core" in _PATCHED:
        return
    cls = getattr(mod, "JarvisCore", None)
    if cls is None:
        return

    # Typed questions in the field occasionally hit a stuck Gemini stream. The
    # stable build retried only voice questions; text now gets one retry too.
    try:
        cls.FIRST_TOKEN_TIMEOUT_MS = max(int(getattr(cls, "FIRST_TOKEN_TIMEOUT_MS", 5600)), 7500)
        cls.TOTAL_RESPONSE_TIMEOUT_MS = max(int(getattr(cls, "TOTAL_RESPONSE_TIMEOUT_MS", 9000)), 14000)
    except Exception:
        pass

    original_prewarm = getattr(cls, "prewarm", None)
    if callable(original_prewarm):
        def prewarm(self):
            try:
                if not getattr(self, "api_key", None):
                    self._load_api_key()
            except Exception:
                pass
            return original_prewarm(self)
        cls.prewarm = prewarm

    original_status = getattr(cls, "get_api_status", None)
    if callable(original_status):
        def get_api_status(self):
            try:
                data = dict(original_status(self) or {})
            except Exception:
                data = {}
            data.update({
                "compatibility_profile": str(_MACHINE_COMPAT.get("profile") or "default"),
                "cuda_driver": bool(_MACHINE_COMPAT.get("cuda_driver")),
                "whisper_device": str(_MACHINE_COMPAT.get("whisper_device") or "auto"),
                "whisper_compute": str(_MACHINE_COMPAT.get("whisper_compute") or "auto"),
                "cpu_threads": int(_MACHINE_COMPAT.get("cpu_threads") or 1),
            })
            return data
        cls.get_api_status = get_api_status

    original_stream = getattr(cls, "process_message_stream", None)
    if callable(original_stream):
        def process_message_stream(
            self,
            message,
            conversation_history,
            memories,
            system_commands_info="",
            on_chunk=None,
            _remote_retry=False,
            speaker_name="",
            source="text",
        ):
            result = original_stream(
                self,
                message,
                conversation_history,
                memories,
                system_commands_info,
                on_chunk=on_chunk,
                _remote_retry=_remote_retry,
                speaker_name=speaker_name,
                source=source,
            )
            try:
                key = _norm(message)
                question_like = bool(
                    str(message or "").strip().endswith("?")
                    or re.match(
                        r"^(?:como|por que|porque|qual|quais|quem|quando|onde|o que|oque|me explica|me explique|explique|explica|quero saber|queria saber)\b",
                        key,
                    )
                )
                degraded = _norm(result)
                needs_retry = (
                    str(source or "text").lower() == "text"
                    and question_like
                    and not _remote_retry
                    and (
                        "nao consegui concluir a resposta neste turno" in degraded
                        or "resposta da ia nao chegou neste turno" in degraded
                    )
                )
                if needs_retry:
                    _safe_log(self, "warning", "Pergunta digitada sem resposta remota; tentando uma vez com transporte renovado.", "CORE")
                    second = original_stream(
                        self,
                        message,
                        conversation_history,
                        memories,
                        system_commands_info,
                        on_chunk=on_chunk,
                        _remote_retry=True,
                        speaker_name=speaker_name,
                        source=source,
                    )
                    return second
            except Exception:
                pass
            return result

        cls.process_message_stream = process_message_stream

    original_degraded = getattr(cls, "_local_degraded_response", None)
    if callable(original_degraded):
        def degraded_response(self, message, source="text"):
            # Secure settings on Windows are machine/user scoped. A copied
            # installation must not silently look frozen when no usable key
            # exists on the new PC.
            if not getattr(self, "api_key", None):
                return (
                    "A IA online ainda não está configurada neste computador. "
                    "Abra Configurações do JARVIS e configure a chave Gemini deste PC. "
                    "Os comandos locais continuam funcionando normalmente."
                )
            try:
                if callable(getattr(self, "has_auth_error", None)) and self.has_auth_error():
                    detail = str(getattr(self, "auth_error_message", "") or "").strip()
                    return detail or (
                        "A chave Gemini deste computador não foi aceita. "
                        "Abra Configurações e salve novamente a chave da IA."
                    )
            except Exception:
                pass

            result = original_degraded(self, message, source=source)
            key = _norm(result)
            if str(source or "text").lower() == "text" and (
                "entendi sua pergunta mas nao consegui concluir a resposta neste turno" in key
                or "entendi a mensagem mas nao consegui concluir a resposta neste turno" in key
            ):
                return (
                    "A IA online não respondeu a tempo neste turno. "
                    "Sua mensagem foi entendida. A conexão será renovada automaticamente; "
                    "tente novamente em alguns segundos."
                )
            return result
        cls._local_degraded_response = degraded_response

    _PATCHED.add("core")

def _patch_voice_engine() -> None:
    mod = sys.modules.get("voice_engine")
    if mod is None or "voice" in _PATCHED:
        return
    cls = getattr(mod, "VoiceEngine", None)
    error_cls = getattr(mod, "VoiceEngineError", RuntimeError)
    if cls is None:
        return

    def detect_microphone(self):
        """Prefer stable host APIs/native rates and prove the stream can open."""
        self._mic_available = False
        self._input_device_index = None
        self._capture_sample_rate = self.SAMPLE_RATE
        try:
            devices = list(self._sd.query_devices())
        except Exception as exc:
            self.last_error = f"PortAudio não conseguiu listar entradas: {exc}"
            self._log("warning", self.last_error)
            return

        try:
            hostapis = list(self._sd.query_hostapis())
        except Exception:
            hostapis = []
        try:
            default_input = int(self._sd.default.device[0])
        except Exception:
            default_input = -1

        candidates = []
        for index, device in enumerate(devices):
            try:
                if int(device.get("max_input_channels", 0) or 0) < 1:
                    continue
            except Exception:
                continue
            name = str(device.get("name", "") or f"Entrada {index}")
            lname = name.lower()
            try:
                api_index = int(device.get("hostapi", -1))
            except Exception:
                api_index = -1
            api_name = ""
            if 0 <= api_index < len(hostapis):
                try:
                    api_name = str(hostapis[api_index].get("name", "") or "")
                except Exception:
                    api_name = ""
            api_key = api_name.lower()
            score = 100
            if index == default_input:
                score -= 20
            if any(word in lname for word in ("microphone", "microfone", "mic ", "headset", "usb", "logitech")):
                score -= 22
            # WDM-KS was the host that repeatedly rejected 16 kHz in the field
            # diagnostics. Prefer WASAPI/MME/DirectSound copies when available.
            if "wdm-ks" in api_key or "wdm ks" in api_key:
                score += 95
            elif "wasapi" in api_key:
                score -= 12
            elif "directsound" in api_key:
                score -= 4
            elif "mme" in api_key:
                score += 6
            candidates.append((score, index, name, api_name, device))

        candidates.sort(key=lambda row: (row[0], row[1]))
        if not candidates:
            self.last_error = "Nenhum dispositivo de entrada de áudio foi encontrado."
            self._log("warning", self.last_error)
            return

        errors = []
        for _, index, name, api_name, device in candidates:
            try:
                native = int(round(float(device.get("default_samplerate") or 0)))
            except Exception:
                native = 0
            rates = []
            for rate in (native, 48000, 44100, self.SAMPLE_RATE):
                if rate > 0 and rate not in rates:
                    rates.append(rate)
            for rate in rates:
                try:
                    self._sd.check_input_settings(
                        device=index,
                        channels=self.CHANNELS,
                        dtype="int16",
                        samplerate=rate,
                    )
                    # check_input_settings can pass while PortAudio still fails
                    # to open the real endpoint. Prove an actual stream open.
                    stream = self._sd.RawInputStream(
                        samplerate=rate,
                        blocksize=max(160, int(rate * 0.02)),
                        dtype="int16",
                        channels=self.CHANNELS,
                        device=index,
                    )
                    try:
                        stream.start()
                        time.sleep(0.025)
                        stream.stop()
                    finally:
                        stream.close()
                except Exception as exc:
                    errors.append(f"#{index}@{rate}/{api_name or 'host'}: {exc}")
                    continue

                self._input_device_index = int(index)
                self._capture_sample_rate = int(rate)
                self.input_device_name = name
                try:
                    self._input_hostapi = api_name
                except Exception:
                    pass
                try:
                    self._load_mic_profile()
                except Exception:
                    pass
                self._mic_available = True
                self.last_error = ""
                self._capture_mode = (
                    "stable-direct-16k" if rate == self.SAMPLE_RATE
                    else f"stable-direct-{rate}-to-{self.SAMPLE_RATE}"
                )
                self._log(
                    "info",
                    f"Microfone validado: {name} (#{index}, {api_name or 'host'}, {rate} Hz).",
                )
                return

        detail = " | ".join(errors[-5:]) if errors else "nenhum stream pôde ser aberto"
        self.last_error = (
            "Nenhuma entrada de microfone utilizável pôde ser aberta. "
            "Conecte/ative um microfone ou headset; use 'reiniciar voz' após corrigir. "
            f"Detalhe: {detail}"
        )
        self._log("warning", self.last_error)

    def ensure_vosk_model(self):
        """Transactional Vosk model download with validation and isolated temp files."""
        target = Path(self._wake_model_path)
        required = ("final.mdl", "Gr.fst", "HCLr.fst", "phones.txt", "mfcc.conf")

        def ready(path: Path) -> bool:
            try:
                return path.is_dir() and all((path / name).is_file() for name in required)
            except Exception:
                return False

        if ready(target):
            return
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._state("PREPARANDO", "Preparando modelo leve de wake word")
        token = f"{os.getpid()}-{threading.get_ident()}-{int(time.time()*1000)}"
        temp_path = Path(self.models_dir) / f"{self.VOSK_MODEL_NAME}.{token}.download"
        zip_path = Path(self.models_dir) / f"{self.VOSK_MODEL_NAME}.{token}.zip"
        extract_dir = None
        try:
            request = urllib.request.Request(
                self.VOSK_MODEL_URL,
                headers={"User-Agent": "JARVIS-Desktop/1.2.0"},
            )
            with urllib.request.urlopen(request, timeout=60) as response, temp_path.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            if not temp_path.is_file() or temp_path.stat().st_size < 1024:
                raise error_cls("O download do modelo Vosk veio vazio ou incompleto.")

            digest = hashlib.md5()
            with temp_path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest().lower() != str(self.VOSK_MODEL_MD5).lower():
                raise error_cls("O modelo de wake word falhou na verificação MD5.")

            temp_path.replace(zip_path)
            extract_dir = Path(tempfile.mkdtemp(prefix=".jarvis-vosk-", dir=str(self.models_dir)))
            with zipfile.ZipFile(zip_path, "r") as archive:
                bad = archive.testzip()
                if bad:
                    raise error_cls(f"O ZIP do modelo Vosk está corrompido: {bad}")
                archive.extractall(extract_dir)

            extracted = extract_dir / self.VOSK_MODEL_NAME
            if not ready(extracted):
                matches = [p for p in extract_dir.rglob(self.VOSK_MODEL_NAME) if ready(p)]
                if matches:
                    extracted = matches[0]
            if not ready(extracted):
                raise error_cls("O modelo Vosk foi extraído, mas os arquivos obrigatórios não apareceram.")
            if ready(target):
                return
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink()
            shutil.move(str(extracted), str(target))
            if not ready(target):
                raise error_cls("O modelo Vosk não ficou íntegro após a instalação.")
            self._log("info", f"Modelo Vosk validado em: {target}")
        except Exception as exc:
            if ready(target):
                return
            if isinstance(exc, error_cls):
                raise
            raise error_cls(f"Não consegui preparar o modelo Vosk com segurança: {exc}") from exc
        finally:
            for path in (temp_path, zip_path):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
            try:
                if extract_dir and extract_dir.exists():
                    shutil.rmtree(extract_dir, ignore_errors=True)
            except Exception:
                pass

    cls._detect_microphone = detect_microphone
    cls._ensure_vosk_model = ensure_vosk_model
    _PATCHED.add("voice")


def _help_text() -> str:
    return """O que eu consigo fazer

Você não precisa decorar comandos. Pode escrever normalmente o que quer fazer. Aqui estão os principais exemplos:

1. PROGRAMAS
   Abrir e fechar aplicativos do computador.
   Exemplos: “abre o Opera”, “abre o OBS”, “fecha o Discord”.

2. JANELAS E MONITORES
   Minimizar, maximizar, restaurar e mover janelas entre telas.
   Exemplos: “minimiza o Opera”, “move o Discord para o monitor 2”, “quantos monitores eu tenho?”.

3. INTERNET E SITES
   Abrir sites e pesquisar no navegador.
   Exemplos: “abre o YouTube”, “pesquisa placas de vídeo”, “vai no Opera e pesquisa ChatGPT”.

4. MÚSICA E VÍDEOS
   Procurar músicas e controlar o player ativo.
   Exemplos: “toca Numb”, “pausa o YouTube”, “próxima música”, “pula 10 segundos”.

5. ARQUIVOS E PASTAS
   Criar, procurar, abrir, copiar e mover arquivos e pastas.
   Exemplos: “cria um arquivo chamado notas”, “cria uma pasta chamada Projetos”, “procura o arquivo contrato”.
   Quando for possível, exclusões e desfazer criação usam a Lixeira para evitar perda acidental.

6. VER E EXPLICAR A TELA
   Tirar prints e, quando o módulo de visão estiver disponível, explicar o que aparece na tela.
   Exemplos: “tira um print”, “descreve minha tela”, “o que é esse erro na tela?”.

7. INFORMAÇÕES DO COMPUTADOR
   Consultar CPU, RAM, disco, rede, volume, microfone, janelas e desempenho do próprio JARVIS.
   Exemplos: “status do PC”, “quanto de RAM estou usando?”, “qual microfone está sendo usado?”, “qual sua latência?”.

8. ROTINAS E REPETIÇÃO DE TAREFAS
   Quando o motor de rotinas estiver disponível, posso aprender uma sequência para repetir depois.
   Exemplo: “aprende rotina trabalho”, faça os passos e depois diga “terminar rotina”.

9. CONVERSAR E TIRAR DÚVIDAS
   Você também pode conversar normalmente e fazer perguntas.
   Exemplos: “qual a diferença entre SSD e HD?”, “me explica memória RAM”.
   Perguntas gerais usam a IA online; se o serviço estiver indisponível, eu aviso em vez de fingir que a pergunta não foi entendida.

10. VÁRIAS AÇÕES EM SEQUÊNCIA
   Posso encadear pedidos claros.
   Exemplo: “abre o Opera e depois pesquisa inteligência artificial”.

DICAS RÁPIDAS
• Digite “ajuda” quando quiser ver este guia novamente.
• Diga “reiniciar voz” se trocar ou reconectar o microfone.
• Diga apenas “monitor 2” para selecionar essa tela como contexto; depois peça a ação desejada.
• Ações sensíveis, como desligar ou reiniciar o computador, continuam exigindo confirmação quando necessário.
""".strip()


def _patch_gui() -> None:
    mod = sys.modules.get("gui")
    if mod is None or "gui" in _PATCHED:
        return
    cls = getattr(mod, "JarvisGUI", None)
    if cls is None:
        return

    # Replace developer-facing capability dump with an end-user guide.
    cls._get_system_commands_info = lambda self: _help_text()

    original_execute = getattr(cls, "_execute_v8_command_result", None)
    if callable(original_execute):
        def execute(self, command: str):
            command = " ".join(str(command or "").split()).strip()

            if command == "v8:clarify_folder_name":
                return _local_outcome(
                    self,
                    "Claro. Qual nome você quer dar para a pasta? Por exemplo: “cria uma pasta chamada Projetos”.",
                    success=False,
                    verified=False,
                )

            if command.startswith("v8:monitor_focus:"):
                try:
                    number = max(1, int(command.rsplit(":", 1)[1]))
                except Exception:
                    number = 1
                try:
                    router = sys.modules.get("jarvis_router")
                    if router is not None:
                        router._ROUTER._remember_monitor(number)
                except Exception:
                    pass
                return _local_outcome(
                    self,
                    f"Monitor {number} selecionado. Agora você pode dizer, por exemplo: “move o Opera para o monitor {number}”, “tira um print do monitor {number}” ou “descreve o monitor {number}”.",
                )

            if command.startswith("v8:release_media:"):
                payload = command.split(":", 2)[2]
                action, _, target = payload.partition("|")
                target = target.strip() or None
                try:
                    if action == "pause":
                        if target and hasattr(self.actions, "media_pause"):
                            msg = self.actions.media_pause(target)
                        elif hasattr(self.actions, "media_play_pause"):
                            msg = self.actions.media_play_pause(target)
                        else:
                            raise RuntimeError("controle de mídia indisponível")
                    else:
                        if target and hasattr(self.actions, "media_play"):
                            msg = self.actions.media_play(target)
                        elif hasattr(self.actions, "media_play_pause"):
                            msg = self.actions.media_play_pause(target)
                        else:
                            raise RuntimeError("controle de mídia indisponível")
                    failed = bool(getattr(self, "_v8_text_failed", lambda _x: False)(msg))
                    return _local_outcome(self, str(msg), not failed, not failed)
                except Exception as exc:
                    return _local_outcome(self, f"Não consegui controlar o vídeo agora: {exc}", False, False)

            if command == "v8:microphone":
                name = host = detail = ""
                ready = False
                try:
                    status = self.voice_engine.status() if self.voice_engine else {}
                    name = str(status.get("input_device") or status.get("input_device_name") or "").strip()
                    host = str(status.get("input_hostapi") or getattr(self.voice_engine, "_input_hostapi", "") or "").strip()
                    detail = str(status.get("last_error") or status.get("error") or "").strip()
                    ready = bool(status.get("ready") or status.get("microphone_available") or getattr(self.voice_engine, "_mic_available", False))
                except Exception:
                    pass
                if not name:
                    try:
                        import sounddevice as sd
                        index = int(sd.default.device[0])
                        if index >= 0:
                            device = sd.query_devices(index)
                            name = str(device.get("name") or f"Entrada {index}").strip()
                            try:
                                api_index = int(device.get("hostapi", -1))
                                if api_index >= 0:
                                    host = str(sd.query_hostapis(api_index).get("name") or "").strip()
                            except Exception:
                                pass
                    except Exception as exc:
                        if not detail:
                            detail = str(exc)
                if name and ready:
                    msg = f"Microfone atual: {name}" + (f" ({host})" if host else "") + "."
                    return _local_outcome(self, msg, True, True)
                if name:
                    msg = f"O Windows detecta o microfone {name}" + (f" ({host})" if host else "") + ", mas a escuta do JARVIS ainda não conseguiu abrir essa entrada."
                    if detail:
                        msg += f" Motivo: {detail[:240]}."
                    msg += " Você pode corrigir/conectar o dispositivo e digitar “reiniciar voz”."
                    return _local_outcome(self, msg, True, True)
                msg = "Não encontrei um microfone de entrada disponível no Windows agora."
                if detail:
                    msg += f" Detalhe: {detail[:240]}."
                return _local_outcome(self, msg, False, False)

            if command == "v8:voice_restart":
                try:
                    if not self.voice_engine:
                        raise RuntimeError("motor de voz indisponível")
                    if not getattr(self.voice_engine, "_started", False):
                        self.voice_engine.start()
                    ok = bool(self.voice_engine.restart_input_stream())
                    if ok:
                        return _local_outcome(
                            self,
                            "Solicitei uma nova detecção e abertura do microfone agora. Se o dispositivo estiver disponível, a escuta volta assim que a validação terminar.",
                            True,
                            True,
                        )
                    return _local_outcome(self, "Não consegui solicitar a reabertura do microfone agora.", False, False)
                except Exception as exc:
                    return _local_outcome(self, f"Não consegui reiniciar a escuta agora. Detalhe: {exc}", False, False)

            if command == "v8:monitors":
                monitors = []
                active_index = None
                source = ""
                try:
                    manager = getattr(self, "window_manager", None)
                    if manager:
                        monitors = list(manager.get_monitors() or [])
                        active = manager.get_active_monitor() or {}
                        active_index = active.get("index") or active.get("number")
                        source = "Windows"
                except Exception:
                    monitors = []
                if not monitors:
                    try:
                        import mss
                        with mss.mss() as sct:
                            monitors = list(sct.monitors[1:])
                        if monitors:
                            source = "captura de tela"
                    except Exception:
                        monitors = []
                if not monitors and os.name == "nt":
                    try:
                        import ctypes
                        count = int(ctypes.windll.user32.GetSystemMetrics(80))  # SM_CMONITORS
                        if count > 0:
                            monitors = [None] * count
                            source = "Windows"
                    except Exception:
                        pass
                if monitors:
                    msg = f"Detectei {len(monitors)} monitor(es)"
                    if source:
                        msg += f" pelo {source}"
                    msg += "."
                    if active_index:
                        msg += f" Monitor ativo: {active_index}."
                    else:
                        msg += " O monitor ativo ainda não foi identificado com segurança."
                    return _local_outcome(self, msg, True, True)
                return _local_outcome(self, "Não consegui detectar monitores agora.", False, False)

            if command == "v8:clipboard":
                try:
                    value = str(self.root.clipboard_get() or "")
                    clean = " ".join(value.split()).strip()
                    if len(clean) > 1200:
                        clean = clean[:1200].rstrip() + "…"
                    triggers = {"o que copiei", "o que esta copiado", "area de transferencia", "clipboard"}
                    if _norm(clean) in triggers:
                        msg = "A área de transferência contém o próprio comando que acabou de ser digitado. Copie outro texto e pergunte novamente."
                    elif clean:
                        msg = f"Na área de transferência: {clean}"
                    else:
                        msg = "A área de transferência está vazia ou não contém texto."
                    return _local_outcome(self, msg, True, True)
                except Exception:
                    return _local_outcome(self, "A área de transferência está vazia ou não contém texto.", True, True)

            if command.startswith("v8:release_undo_created:"):
                path = command.split(":", 2)[2].strip()
                try:
                    candidate = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
                    if not os.path.exists(candidate):
                        return _local_outcome(self, f"O item já não existe: {candidate}", False, False)
                    from send2trash import send2trash
                    send2trash(candidate)
                    return _local_outcome(self, f"✓ Desfeito com segurança: {candidate} foi movido para a Lixeira.", True, True)
                except Exception as exc:
                    return _local_outcome(self, f"Não consegui desfazer com segurança: {exc}", False, False)

            result = original_execute(self, command)

            # Record freshly-created paths so the next “desfaz” can move them
            # to the Recycle Bin. Existing v1.1.2 only recorded window actions.
            try:
                if bool((result or {}).get("success")):
                    action = None
                    if command.startswith("v8:create_text:"):
                        action = "CREATE_TEXT"
                    elif command.startswith("v8:create_folder:") or re.match(r"^crie pasta no desktop\s+", command, re.I):
                        action = "CREATE_FOLDER"
                    if action:
                        message = str((result or {}).get("message") or "")
                        match = re.search(r"(?:criado|criada|pasta|arquivo)\s*:\s*(.+)$", message, re.I)
                        if match:
                            path = match.group(1).strip().strip('"')
                            router_mod = sys.modules.get("jarvis_router")
                            context = getattr(getattr(router_mod, "_ROUTER", None), "context", None)
                            if context is not None and path:
                                context.record_action(action, path, verified=True, after={"path": path})
            except Exception:
                pass
            return result

        cls._execute_v8_command_result = execute

    # ------------------------------------------------------------------
    # JARVIS 1.2.1 - UI POLISH / HIGH-DPI CHAT
    # ------------------------------------------------------------------
    # Visual specification approved by the user: readable Chat-style layout,
    # crisp vector-like icons, larger typography, responsive scrolling and a
    # dedicated icon-only update button. No emoji is used as interface chrome.
    UI_BG = "#061019"
    UI_CHAT = "#08131D"
    UI_SIDEBAR = "#07121C"
    UI_SURFACE = "#101D29"
    UI_SURFACE_2 = "#142536"
    UI_SURFACE_3 = "#193047"
    UI_BORDER = "#1E3B53"
    UI_BORDER_SOFT = "#172C3E"
    UI_TEXT = "#F5F9FD"
    UI_MUTED = "#B1C0CE"
    UI_MUTED_2 = "#7890A3"
    UI_ACCENT = "#18A8FF"
    UI_ACCENT_HOVER = "#40BBFF"
    UI_ACCENT_SOFT = "#0B2B43"
    UI_USER = "#152433"
    UI_SUCCESS = "#19D887"
    UI_WARNING = "#F6B84A"
    UI_DANGER = "#FF6476"
    FONT_UI = "Segoe UI"

    try:
        cls.SIDEBAR_MIN = 78
        cls.SIDEBAR_DEFAULT = 306
        cls.SIDEBAR_MAX = 330
        cls.COMPOSER_MIN_HEIGHT = 58
        cls.COMPOSER_MAX_HEIGHT = 180
    except Exception:
        pass

    def _v121_rgb(color, fallback=(220, 232, 244)):
        try:
            from PIL import ImageColor
            return ImageColor.getrgb(str(color))
        except Exception:
            return fallback

    def _v121_icon(self, kind: str, size: int = 24, color: str = UI_TEXT):
        """Crisp icon rendered at 5x then downsampled by CTkImage.

        The source bitmap is deliberately much larger than the logical icon,
        preventing Windows DPI scaling from magnifying a low-res asset.
        """
        import customtkinter as ctk
        from PIL import Image, ImageDraw, ImageFilter
        cache = getattr(self, "_v121_icon_cache", None)
        if cache is None:
            cache = {}
            self._v121_icon_cache = cache
        key = (str(kind), int(size), str(color))
        if key in cache:
            return cache[key]

        scale = 5
        px = max(16, int(size))
        S = px * scale
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        fg = _v121_rgb(color)
        w = max(7, int(px * 0.095 * scale))
        def P(x, y): return (int(x * scale), int(y * scale))
        def line(points, width=w, fill=fg):
            d.line([P(x, y) for x, y in points], fill=fill, width=max(3, int(width)), joint="curve")
        def rr(box, radius=3, outline=fg, width=w, fill=None):
            d.rounded_rectangle(tuple(int(v * scale) for v in box), radius=int(radius*scale), outline=outline, width=max(3,int(width)), fill=fill)

        k = str(kind).lower()
        if k == "helmet":
            # Original futuristic assistant mask; intentionally generic, not a copied character asset.
            glow = Image.new("RGBA", (S, S), (0,0,0,0))
            gd = ImageDraw.Draw(glow)
            cyan = _v121_rgb(UI_ACCENT)
            pts = [P(6,4), P(px-6,4), P(px-3,px*0.34), P(px-5,px*0.78), P(px*0.50,px-2), P(5,px*0.78), P(3,px*0.34), P(6,4)]
            gd.line(pts, fill=cyan+(150,), width=max(8,int(w*1.6)), joint="curve")
            glow = glow.filter(ImageFilter.GaussianBlur(max(3,int(scale*1.4))))
            img = Image.alpha_composite(img, glow)
            d = ImageDraw.Draw(img)
            d.polygon([P(7,5), P(px-7,5), P(px-4,px*0.34), P(px-6,px*0.76), P(px*0.5,px-3), P(6,px*0.76), P(4,px*0.34)], fill=(8,22,35,255))
            line([(7,5),(px-7,5),(px-4,px*0.34),(px-6,px*0.76),(px*0.5,px-3),(6,px*0.76),(4,px*0.34),(7,5)], width=max(5,int(w*.70)), fill=cyan)
            line([(7,px*0.34),(px*0.43,px*0.39),(px*0.48,px*0.48)], width=max(4,int(w*.60)), fill=(116,212,255))
            line([(px-7,px*0.34),(px*0.57,px*0.39),(px*0.52,px*0.48)], width=max(4,int(w*.60)), fill=(116,212,255))
            line([(px*0.28,px*0.70),(px*0.5,px*0.80),(px*0.72,px*0.70)], width=max(4,int(w*.52)), fill=(70,153,210))
        elif k == "sidebar":
            rr((3,4,px-3,px-4), 3)
            line([(px*.34,5),(px*.34,px-5)], width=max(4,int(w*.72)))
        elif k == "chat":
            rr((3,4,px-3,px-6), 4)
            line([(7,px-6),(5,px-2),(11,px-6)], width=max(4,int(w*.72)))
            for y in (px*.39, px*.58): line([(8,y),(px-8,y)], width=max(3,int(w*.50)))
        elif k == "search":
            d.ellipse((4*scale,4*scale,int(px*.66*scale),int(px*.66*scale)), outline=fg, width=w)
            line([(px*.61,px*.61),(px-4,px-4)])
        elif k == "grid":
            q=4; s=px*.29
            for x,y in ((3,3),(px*.56,3),(3,px*.56),(px*.56,px*.56)):
                rr((x,y,x+s,y+s),2,width=max(3,int(w*.68)))
        elif k == "tools":
            d.ellipse((3*scale,3*scale,int(px*.42*scale),int(px*.42*scale)), outline=fg, width=w)
            line([(px*.35,px*.35),(px-4,px-4)])
            d.ellipse((int((px-6)*scale),int((px-6)*scale),int((px-2)*scale),int((px-2)*scale)), fill=fg)
        elif k == "folder":
            pts=[P(3,7),P(px*.36,7),P(px*.45,10),P(px-3,10),P(px-3,px-4),P(3,px-4),P(3,7)]
            d.line(pts, fill=fg, width=w, joint="curve")
        elif k == "pulse":
            line([(2,px*.56),(px*.25,px*.56),(px*.36,px*.25),(px*.48,px*.78),(px*.60,px*.43),(px*.69,px*.56),(px-2,px*.56)])
        elif k == "settings":
            c=px/2; r=px*.23
            d.ellipse((int((c-r)*scale),int((c-r)*scale),int((c+r)*scale),int((c+r)*scale)), outline=fg, width=w)
            for a in range(0,360,45):
                import math
                x1=c+math.cos(math.radians(a))*px*.31; y1=c+math.sin(math.radians(a))*px*.31
                x2=c+math.cos(math.radians(a))*px*.43; y2=c+math.sin(math.radians(a))*px*.43
                line([(x1,y1),(x2,y2)], width=max(4,int(w*.68)))
        elif k == "help":
            d.ellipse((3*scale,3*scale,(px-3)*scale,(px-3)*scale), outline=fg, width=w)
            # Question mark as strokes, not a font glyph.
            line([(px*.36,px*.38),(px*.42,px*.28),(px*.52,px*.25),(px*.62,px*.31),(px*.64,px*.42),(px*.58,px*.50),(px*.50,px*.55),(px*.50,px*.63)], width=max(4,int(w*.72)))
            d.ellipse((int(px*.47*scale),int(px*.73*scale),int(px*.53*scale),int(px*.79*scale)), fill=fg)
        elif k == "copy":
            rr((7,6,px-3,px-3),3,width=max(3,int(w*.7)))
            rr((3,3,px-7,px-7),3,width=max(3,int(w*.7)))
        elif k == "refresh":
            d.arc((3*scale,3*scale,(px-3)*scale,(px-3)*scale), 35, 300, fill=fg, width=w)
            line([(px*.72,3),(px-3,px*.23),(px*.67,px*.27)], width=max(4,int(w*.68)))
        elif k == "plus":
            line([(px*.5,4),(px*.5,px-4)])
            line([(4,px*.5),(px-4,px*.5)])
        elif k == "mic":
            rr((px*.36,3,px*.64,px*.58), px*.13, width=max(4,int(w*.70)))
            d.arc((int(px*.24*scale),int(px*.30*scale),int(px*.76*scale),int(px*.76*scale)), 0, 180, fill=fg, width=max(4,int(w*.68)))
            line([(px*.5,px*.74),(px*.5,px-3)], width=max(4,int(w*.68)))
            line([(px*.35,px-3),(px*.65,px-3)], width=max(4,int(w*.68)))
        elif k == "send":
            pts=[P(3,px*.52),P(px-3,3),P(px*.72,px-3),P(px*.51,px*.63),P(3,px*.52)]
            d.line(pts, fill=fg, width=w, joint="curve")
            line([(px*.51,px*.63),(px*.55,px*.48),(px-3,3)], width=max(4,int(w*.60)))
        elif k == "user":
            d.ellipse((int(px*.37*scale),3*scale,int(px*.63*scale),int(px*.29*scale)), outline=fg, width=max(4,int(w*.7)))
            d.arc((int(px*.22*scale),int(px*.34*scale),int(px*.78*scale),int((px-.5)*scale)), 185, 355, fill=fg, width=w)
        elif k == "check":
            d.ellipse((2*scale,2*scale,(px-2)*scale,(px-2)*scale), fill=_v121_rgb(UI_SUCCESS)+(255,))
            line([(px*.27,px*.52),(px*.43,px*.68),(px*.74,px*.34)], width=max(4,int(w*.65)), fill=(3,33,24))
        elif k == "file":
            rr((5,2,px-5,px-2),3,width=max(3,int(w*.70)))
            line([(px*.39,px*.39),(px*.65,px*.39)], width=max(3,int(w*.55)))
            line([(px*.39,px*.55),(px*.70,px*.55)], width=max(3,int(w*.55)))
            line([(px*.39,px*.71),(px*.62,px*.71)], width=max(3,int(w*.55)))
        elif k == "music":
            line([(px*.55,4),(px*.55,px*.70)], width=max(4,int(w*.70)))
            line([(px*.55,4),(px*.82,7)], width=max(4,int(w*.70)))
            d.ellipse((int(px*.25*scale),int(px*.63*scale),int(px*.57*scale),int(px*.91*scale)), fill=fg)
        elif k == "screen":
            rr((2,4,px-2,px*.72),3,width=max(3,int(w*.70)))
            line([(px*.5,px*.72),(px*.5,px*.88)], width=max(3,int(w*.65)))
            line([(px*.32,px*.89),(px*.68,px*.89)], width=max(3,int(w*.65)))
        elif k == "open":
            rr((3,7,px-3,px-4),3,width=max(3,int(w*.65)))
            line([(px*.48,px*.52),(px*.80,px*.20)], width=max(4,int(w*.65)))
            line([(px*.58,px*.20),(px*.80,px*.20),(px*.80,px*.42)], width=max(4,int(w*.65)))
        else:
            d.ellipse((4*scale,4*scale,(px-4)*scale,(px-4)*scale), outline=fg, width=w)

        icon = ctk.CTkImage(light_image=img, dark_image=img, size=(px, px))
        cache[key] = icon
        return icon

    def _v121_clean_visible_text(text: str) -> str:
        raw = str(text or "")
        prefixes = {
            "📸 ": "Captura: ", "✓ ": "", "✅ ": "", "♪ ": "",
            "🔌 ": "", "⚠️ ": "Atenção: ", "⚠ ": "Atenção: ",
        }
        for old, new in prefixes.items():
            if raw.startswith(old):
                raw = new + raw[len(old):]
                break
        return raw

    def _v121_prefill(self, text: str, *, send: bool = False):
        try:
            popup = getattr(self, "_v121_plus_popup", None)
            if popup is not None and popup.winfo_exists():
                popup.destroy()
        except Exception:
            pass
        self._v121_plus_popup = None
        try:
            self._composer_placeholder_active = False
            self.text_input.configure(state="normal", text_color=UI_TEXT)
            self.text_input.delete("1.0", "end")
            self.text_input.insert("1.0", str(text or ""))
            self.text_input.focus_set()
            self._resize_composer()
            if send:
                self.send_message()
        except Exception as exc:
            _safe_log(self, "warning", f"Ação rápida não pôde preencher o chat: {exc}", "GUI")

    def _v121_set_mode(self, mode: str):
        mode = str(mode or "auto").strip().lower()
        if mode not in {"auto", "conversa", "comando"}:
            mode = "auto"
        self.interaction_mode = mode
        try:
            if self.voice_engine:
                self.voice_engine.set_conversation_mode(mode == "conversa")
        except Exception:
            pass
        try:
            self._sync_conversation_overlay_lock(mode == "conversa")
            self._save_quick_preferences()
        except Exception:
            pass
        labels = {"auto": "Auto", "conversa": "Conversa", "comando": "Comando"}
        try:
            self._v121_mode_button.configure(text=labels[mode])
        except Exception:
            pass

    def _v121_show_mode_menu(self, widget):
        try:
            self._popup_dark_menu(widget, [
                ("Automático", lambda: _v121_set_mode(self, "auto")),
                ("Conversa", lambda: _v121_set_mode(self, "conversa")),
                ("Comando", lambda: _v121_set_mode(self, "comando")),
            ], upward=True)
        except Exception:
            pass

    def _v121_copy_diagnostic(self):
        try:
            self._copy_everything()
            self.add_message("JARVIS", "Relatório copiado: conversa, status e logs estão na área de transferência.", is_jarvis=True)
        except Exception as exc:
            try:
                self._copy_to_clipboard(self._conversation_as_text())
                self.add_message("JARVIS", "Conversa copiada para a área de transferência.", is_jarvis=True)
            except Exception:
                _safe_log(self, "warning", f"Falha ao copiar diagnóstico: {exc}", "GUI")

    def _v121_toggle_plus_panel(self, widget):
        import customtkinter as ctk
        try:
            old = getattr(self, "_v121_plus_popup", None)
            if old is not None and old.winfo_exists():
                old.destroy(); self._v121_plus_popup = None; return
        except Exception:
            self._v121_plus_popup = None

        popup = ctk.CTkToplevel(self.root)
        self._v121_plus_popup = popup
        popup.overrideredirect(True)
        popup.configure(fg_color=UI_BG)
        try: popup.attributes("-topmost", True)
        except Exception: pass
        width, height = 438, 536
        try:
            x = max(self.root.winfo_rootx()+8, widget.winfo_rootx()-10)
            y = max(self.root.winfo_rooty()+8, widget.winfo_rooty()-height-14)
        except Exception:
            x,y = 80,120
        popup.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

        shell = ctk.CTkFrame(popup, fg_color=UI_SURFACE, corner_radius=22, border_width=1, border_color=UI_BORDER)
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        head = ctk.CTkFrame(shell, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(18,8))
        ctk.CTkLabel(head, text="O que você quer fazer?", anchor="w", text_color=UI_TEXT,
                     font=ctk.CTkFont(family=FONT_UI, size=18, weight="bold")).pack(side="left", fill="x", expand=True)
        close = ctk.CTkButton(head, text="", image=_v121_icon(self,"plus",18,UI_MUTED), width=36,height=36,corner_radius=12,
                              fg_color="transparent", hover_color=UI_SURFACE_2,
                              command=lambda:(popup.destroy(),setattr(self,"_v121_plus_popup",None)))
        close.pack(side="right")
        try:
            # rotate-like visual is not needed; plus remains a neutral close target via Escape too.
            pass
        except Exception: pass
        ctk.CTkLabel(shell, text="Escolha uma ação ou continue escrevendo normalmente.", anchor="w",
                     text_color=UI_MUTED, font=ctk.CTkFont(family=FONT_UI,size=12)).pack(fill="x",padx=20,pady=(0,12))

        items = [
            ("search","Pesquisar na internet","Informações atuais e fontes","pesquise ",False),
            ("grid","Abrir um programa","Opera, Discord, OBS e outros","abre ",False),
            ("music","Tocar uma música","Pesquise e abra uma música","toca música ",False),
            ("file","Criar arquivo ou pasta","Crie e organize seus arquivos","cria ",False),
            ("screen","Capturar minha tela","Salvar um screenshot agora","tira um print",True),
            ("tools","Organizar janelas","Mover, minimizar ou maximizar","move ",False),
            ("pulse","Diagnóstico do JARVIS","Verificar módulos e serviços","diagnóstico completo",True),
            ("copy","Copiar relatório","Conversa, status e logs para suporte",None,False),
        ]
        body = ctk.CTkFrame(shell, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0,14))
        for icon_name,title,desc,prompt,send_now in items:
            def run(p=prompt,s=send_now,t=title):
                if t == "Copiar relatório":
                    try: popup.destroy()
                    except Exception: pass
                    self._v121_plus_popup=None
                    _v121_copy_diagnostic(self)
                else:
                    _v121_prefill(self,p,send=s)
            row = ctk.CTkButton(body, text=f"{title}\n{desc}", image=_v121_icon(self,icon_name,25,UI_ACCENT), compound="left",
                                height=54, anchor="w", corner_radius=14, fg_color="transparent", hover_color=UI_SURFACE_2,
                                text_color=UI_TEXT, font=ctk.CTkFont(family=FONT_UI,size=12), command=run)
            row.pack(fill="x", padx=3, pady=2)
        popup.bind("<Escape>", lambda _e: popup.destroy(), add="+")
        try: popup.after(30,popup.focus_force)
        except Exception: pass

    def _v121_nav_button(self, parent, icon_name, text, command, *, accent=False):
        import customtkinter as ctk
        btn = ctk.CTkButton(
            parent, text=text, image=_v121_icon(self,icon_name,24,UI_ACCENT if accent else UI_MUTED), compound="left",
            height=50, anchor="w", corner_radius=14,
            fg_color=UI_ACCENT_SOFT if accent else "transparent",
            hover_color=UI_SURFACE_2, border_width=1 if accent else 0,
            border_color="#0E628E" if accent else UI_BORDER_SOFT,
            text_color=UI_TEXT if accent else "#D6E1EA",
            font=ctk.CTkFont(family=FONT_UI,size=14,weight="bold" if accent else "normal"),
            command=command,
        )
        btn.pack(fill="x", pady=2)
        return btn

    def _v121_sidebar_full(self, parent):
        import customtkinter as ctk
        frame = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        self._v121_sidebar_full_frame = frame
        frame.pack(fill="both", expand=True, padx=18, pady=18)

        brand = ctk.CTkFrame(frame, fg_color="transparent", height=64)
        brand.pack(fill="x", pady=(0,18)); brand.pack_propagate(False)
        helmet = ctk.CTkLabel(brand, text="", image=_v121_icon(self,"helmet",46,UI_ACCENT), width=50,height=50)
        helmet.pack(side="left", padx=(0,13), pady=6)
        labels = ctk.CTkFrame(brand, fg_color="transparent")
        labels.pack(side="left", fill="y", expand=True)
        ctk.CTkLabel(labels,text="JARVIS",anchor="w",text_color=UI_TEXT,
                     font=ctk.CTkFont(family=FONT_UI,size=26,weight="bold")).pack(anchor="w",pady=(7,0))
        ctk.CTkLabel(labels,text="SEMPRE AO SEU LADO",anchor="w",text_color="#6E9CB9",
                     font=ctk.CTkFont(family=FONT_UI,size=9,weight="bold")).pack(anchor="w",pady=(0,4))
        self.sidebar_state_button = ctk.CTkButton(brand,text="",image=_v121_icon(self,"sidebar",22,UI_MUTED),width=42,height=42,
                                                  corner_radius=13,fg_color="transparent",hover_color=UI_SURFACE_2,
                                                  command=self._cycle_sidebar_state)
        self.sidebar_state_button.pack(side="right",pady=10)

        self._new_chat_button = _v121_nav_button(self, frame,"chat","Novo chat",self._new_conversation,accent=True)
        self._conversation_search_button = _v121_nav_button(self, frame,"search","Conversas",lambda: self._open_conversation_search_popover(self._conversation_search_button))
        _v121_nav_button(self, frame,"search","Pesquisar",lambda:_v121_prefill(self,"pesquise ",send=False))
        _v121_nav_button(self, frame,"grid","Assistentes",lambda:_v121_prefill(self,"o que você consegue fazer",send=True))
        self._v121_tools_button = _v121_nav_button(self, frame,"tools","Ferramentas",lambda:_v121_toggle_plus_panel(self,self._v121_tools_button))
        _v121_nav_button(self, frame,"folder","Arquivos",lambda:_v121_prefill(self,"procure o arquivo ",send=False))

        sep = ctk.CTkFrame(frame,height=1,fg_color=UI_BORDER_SOFT)
        sep.pack(fill="x",pady=(17,15))

        _v121_nav_button(self, frame,"pulse","Diagnóstico",self._open_diagnostic_panel)
        _v121_nav_button(self, frame,"copy","Copiar relatório",lambda:_v121_copy_diagnostic(self))
        self.api_button = _v121_nav_button(self, frame,"settings","Configurações",self._open_api_settings)
        _v121_nav_button(self, frame,"help","Ajuda",lambda:_v121_prefill(self,"ajuda",send=True))

        spacer = ctk.CTkFrame(frame,fg_color="transparent")
        spacer.pack(fill="both",expand=True)

        status_card = ctk.CTkFrame(frame,fg_color="#0B1A23",corner_radius=16,border_width=1,border_color="#163548",height=74)
        status_card.pack(fill="x",pady=(14,8)); status_card.pack_propagate(False)
        dot = ctk.CTkFrame(status_card,width=14,height=14,corner_radius=7,fg_color=UI_SUCCESS)
        dot.pack(side="left",padx=(16,12),pady=25)
        txt = ctk.CTkFrame(status_card,fg_color="transparent")
        txt.pack(side="left",fill="both",expand=True,pady=13)
        self.status_label = ctk.CTkLabel(txt,text="JARVIS ONLINE",anchor="w",text_color="#4DE8A8",
                                         font=ctk.CTkFont(family=FONT_UI,size=13,weight="bold"))
        self.status_label.pack(anchor="w")
        ctk.CTkLabel(txt,text="Sistema pronto para operar",anchor="w",text_color="#8EB0C5",
                     font=ctk.CTkFont(family=FONT_UI,size=11)).pack(anchor="w",pady=(2,0))
        ctk.CTkLabel(frame,text="v1.2.1",anchor="w",text_color="#6A8496",
                     font=ctk.CTkFont(family=FONT_UI,size=11)).pack(fill="x",padx=6,pady=(2,0))

    def _v121_sidebar_compact(self, parent):
        import customtkinter as ctk
        frame = ctk.CTkFrame(parent,fg_color="transparent",corner_radius=0)
        self._v121_sidebar_compact_frame=frame
        ctk.CTkLabel(frame,text="",image=_v121_icon(self,"helmet",42,UI_ACCENT),width=48,height=48).pack(padx=11,pady=(16,10))
        def b(kind,cmd,accent=False):
            btn=ctk.CTkButton(frame,text="",image=_v121_icon(self,kind,25,UI_ACCENT if accent else UI_MUTED),width=50,height=50,
                              corner_radius=15,fg_color=UI_ACCENT_SOFT if accent else "transparent",hover_color=UI_SURFACE_2,
                              border_width=1 if accent else 0,border_color="#0E628E",command=cmd)
            btn.pack(padx=11,pady=3); return btn
        self._v121_compact_sidebar_button=b("sidebar",self._cycle_sidebar_state)
        b("chat",self._new_conversation,True)
        self._v121_compact_search=b("search",lambda:self._open_conversation_search_popover(self._v121_compact_search))
        self._v121_compact_tools=b("tools",lambda:_v121_toggle_plus_panel(self,self._v121_compact_tools))
        spacer=ctk.CTkFrame(frame,fg_color="transparent");spacer.pack(fill="both",expand=True)
        b("pulse",self._open_diagnostic_panel)
        b("copy",lambda:_v121_copy_diagnostic(self))
        b("settings",self._open_api_settings)
        b("help",lambda:_v121_prefill(self,"ajuda",send=True))
        ctk.CTkFrame(frame,width=12,height=12,corner_radius=6,fg_color=UI_SUCCESS).pack(pady=(10,18))

    def _v121_update_tick(self):
        try:
            btn = getattr(self,"update_button",None)
            if btn is None or not btn.winfo_exists(): return
            available = getattr(self,"_pending_update_info",None) is not None
            active = bool(getattr(self,"_update_download_active",False))
            phase = bool(getattr(self,"_v121_update_phase",False))
            self._v121_update_phase = not phase
            if active:
                fg = "#145A7C"; border = "#268DB8"
            elif available:
                fg = "#28B5FF" if phase else "#0C6DA2"; border = "#7CD5FF" if phase else "#229ED8"
            else:
                fg = "#0D5A83"; border = "#16749F"
            btn.configure(text="", image=_v121_icon(self,"refresh",24,"#F6FBFF"), fg_color=fg,
                          hover_color=UI_ACCENT_HOVER, border_width=2 if available else 1,border_color=border)
            self.root.after(560 if available else 1200, self._v121_update_tick)
        except Exception:
            try: self.root.after(1500,self._v121_update_tick)
            except Exception: pass

    def create_main_layout(self):
        import customtkinter as ctk
        main=ctk.CTkFrame(self.root,fg_color=UI_BG,corner_radius=0)
        main.pack(fill="both",expand=True)
        self._v121_main_container=main
        content=ctk.CTkFrame(main,fg_color=UI_BG,corner_radius=0)
        self.content_frame=content;content.pack(fill="both",expand=True)
        content.grid_rowconfigure(0,weight=1);content.grid_columnconfigure(0,weight=0,minsize=306);content.grid_columnconfigure(1,weight=1)
        self._sidebar_state=str(getattr(self,"_sidebar_state","full") or "full")
        if self._sidebar_state not in {"full","compact"}:self._sidebar_state="full"
        self._sidebar_last_full_width=306;self._sidebar_width=306
        side=ctk.CTkFrame(content,width=306,fg_color=UI_SIDEBAR,corner_radius=0,border_width=1,border_color="#112737")
        self.side_panel=side;self.sidebar_splitter=None;side.grid(row=0,column=0,sticky="nsew");side.grid_propagate(False)
        _v121_sidebar_full(self,side);_v121_sidebar_compact(self,side)
        chat=ctk.CTkFrame(content,fg_color=UI_CHAT,corner_radius=0)
        self._v121_chat_panel=chat;chat.grid(row=0,column=1,sticky="nsew")
        self._create_chat_area(chat)
        self._apply_sidebar_state(self._sidebar_state)

    def apply_sidebar_state(self,state:str):
        state="compact" if str(state).lower() in {"compact","closed"} else "full";self._sidebar_state=state
        try:
            if state=="compact":
                self._v121_sidebar_full_frame.pack_forget();self._v121_sidebar_compact_frame.pack(fill="both",expand=True);width=78
            else:
                self._v121_sidebar_compact_frame.pack_forget();self._v121_sidebar_full_frame.pack(fill="both",expand=True,padx=18,pady=18);width=306
            self._sidebar_width=width;self.content_frame.grid_columnconfigure(0,minsize=width);self.side_panel.configure(width=width)
            try:self._save_sidebar_width()
            except Exception:pass
        except Exception as exc:_safe_log(self,"warning",f"Não foi possível alternar a barra lateral: {exc}","GUI")

    def cycle_sidebar_state(self):
        self._apply_sidebar_state("compact" if getattr(self,"_sidebar_state","full")=="full" else "full")

    def _v121_on_chat_mousewheel(self,event):
        """Faster wheel/touchpad handling without jumpy page-sized movement."""
        if not getattr(self,"chat_scroll",None): return None
        try:
            canvas=self.chat_scroll._parent_canvas
            under=self.root.winfo_containing(event.x_root,event.y_root)
            if not (self._widget_is_inside_chat(under) or under is canvas): return None
            num=getattr(event,"num",None)
            if num in (4,5): notches=-1 if num==4 else 1
            else:
                delta=int(getattr(event,"delta",0) or 0)
                if not delta:return "break"
                remainder=int(getattr(self,"_v121_wheel_remainder",0))+delta
                if abs(remainder)<60:
                    self._v121_wheel_remainder=remainder;return "break"
                raw=max(-5,min(5,int(round(remainder/120.0)) or (1 if remainder>0 else -1)))
                self._v121_wheel_remainder=0;notches=-raw
            steps=max(-36,min(36,int(notches)*8))
            if steps:canvas.yview_scroll(steps,"units")
            _f,last=canvas.yview();self._chat_auto_scroll=bool(last>=.992);self._chat_manual_scroll_until=time.monotonic()+.55
            return "break"
        except Exception:return None

    def create_chat_area(self,parent):
        import customtkinter as ctk
        wrapper=ctk.CTkFrame(parent,fg_color=UI_CHAT,corner_radius=0)
        wrapper.pack(fill="both",expand=True,padx=(28,28),pady=(18,16));self._v121_chat_wrapper=wrapper

        top=ctk.CTkFrame(wrapper,fg_color="transparent",height=64);top.pack(fill="x",padx=4,pady=(0,6));top.pack_propagate(False)
        titles=ctk.CTkFrame(top,fg_color="transparent");titles.pack(side="left",fill="both",expand=True)
        self.current_conversation_label=ctk.CTkLabel(titles,text="Como posso ajudar?",anchor="w",text_color=UI_TEXT,
                                                      font=ctk.CTkFont(family=FONT_UI,size=25,weight="bold"))
        self.current_conversation_label.pack(anchor="w")
        ctk.CTkLabel(titles,text="Pergunte, solicite, crie, analise ou apenas converse.",anchor="w",text_color=UI_MUTED,
                     font=ctk.CTkFont(family=FONT_UI,size=12)).pack(anchor="w",pady=(1,0))

        tools=ctk.CTkFrame(top,fg_color="transparent");tools.pack(side="right",fill="y")
        self.source_badge=ctk.CTkLabel(tools,text="LOCAL",width=56,height=26,corner_radius=10,fg_color="#0D3A2A",text_color="#64E7A8",
                                       font=ctk.CTkFont(family=FONT_UI,size=10,weight="bold"))
        self.source_badge.pack(side="left",padx=(0,10),pady=16)
        self.activity_label=ctk.CTkLabel(tools,text="Pronto",text_color=UI_MUTED_2,font=ctk.CTkFont(family=FONT_UI,size=11))
        self.activity_label.pack(side="left",padx=(0,16),pady=20)
        self.update_button=ctk.CTkButton(tools,text="",image=_v121_icon(self,"refresh",24,"#F6FBFF"),width=46,height=46,corner_radius=23,
                                         fg_color="#0D5A83",hover_color=UI_ACCENT_HOVER,border_width=1,border_color="#16749F",command=self._update_now)
        self.update_button.pack(side="right",pady=8)

        self.agent_hud=ctk.CTkFrame(wrapper,fg_color="#0C1B27",corner_radius=16,border_width=1,border_color="#21425C")
        hud_top=ctk.CTkFrame(self.agent_hud,fg_color="transparent");hud_top.pack(fill="x",padx=16,pady=(11,4))
        self.agent_hud_title=ctk.CTkLabel(hud_top,text="JARVIS está trabalhando",text_color="#73CFFF",font=ctk.CTkFont(family=FONT_UI,size=12,weight="bold"));self.agent_hud_title.pack(side="left")
        self.agent_stop_button=ctk.CTkButton(hud_top,text="Parar",width=72,height=30,corner_radius=10,fg_color="#49262D",hover_color="#66333C",text_color="#FFD1D6",font=ctk.CTkFont(family=FONT_UI,size=11,weight="bold"),command=self._stop_agent_goal);self.agent_stop_button.pack(side="right")
        self.agent_hud_step=ctk.CTkLabel(self.agent_hud,text="",anchor="w",justify="left",wraplength=850,text_color="#DCE9F3",font=ctk.CTkFont(family=FONT_UI,size=12));self.agent_hud_step.pack(fill="x",padx=16,pady=(0,7))
        self.agent_hud_progress=ctk.CTkProgressBar(self.agent_hud,height=5,corner_radius=3,fg_color="#1A3142",progress_color=UI_ACCENT);self.agent_hud_progress.pack(fill="x",padx=16,pady=(0,12));self.agent_hud_progress.set(0);self.agent_hud.pack_forget()

        self.chat_scroll=ctk.CTkScrollableFrame(wrapper,fg_color=UI_CHAT,corner_radius=0,border_width=0,
                                                 scrollbar_button_color="#244156",scrollbar_button_hover_color="#38637F")
        self.chat_scroll.pack(fill="both",expand=True,pady=(0,12));self.chat_display=None
        try:self.chat_scroll._scrollbar.configure(width=14)
        except Exception:pass
        self._install_chat_mousewheel()

        composer_zone=ctk.CTkFrame(wrapper,fg_color="transparent");composer_zone.pack(fill="x",side="bottom")
        input_shell=ctk.CTkFrame(composer_zone,fg_color="#0E1A24",corner_radius=28,border_width=1,border_color="#23516E")
        self.input_shell=input_shell;input_shell.pack(fill="x",padx=(20,20),pady=(0,5))
        self.quick_menu_button=ctk.CTkButton(input_shell,text="",image=_v121_icon(self,"plus",25,UI_TEXT),width=48,height=48,corner_radius=24,
                                             fg_color="transparent",hover_color=UI_SURFACE_2,command=lambda:_v121_toggle_plus_panel(self,self.quick_menu_button))
        self.quick_menu_button.pack(side="left",padx=(9,3),pady=7)
        self._composer_placeholder_text="Pergunte ao JARVIS..."
        self.text_input=ctk.CTkTextbox(input_shell,height=self.COMPOSER_MIN_HEIGHT,wrap="word",activate_scrollbars=False,
                                       font=ctk.CTkFont(family=FONT_UI,size=15),text_color=UI_TEXT,fg_color="transparent",border_width=0,corner_radius=0)
        self.text_input.pack(side="left",fill="x",expand=True,padx=(7,8),pady=7)
        try:self.text_input._textbox.configure(insertbackground="#EAF7FF",spacing1=2,spacing3=2)
        except Exception:pass
        self.text_input.bind("<FocusIn>",self._composer_focus_in,add="+");self.text_input.bind("<FocusOut>",self._composer_focus_out,add="+");self.text_input.bind("<Return>",self._on_composer_return,add="+");self.text_input.bind("<KeyRelease>",self._resize_composer,add="+");self._composer_set_placeholder()
        labels={"auto":"Auto","conversa":"Conversa","comando":"Comando"}
        self._v121_mode_button=ctk.CTkButton(input_shell,text=labels.get(getattr(self,"interaction_mode","auto"),"Auto"),width=86,height=42,corner_radius=17,
                                             fg_color="#122433",hover_color=UI_SURFACE_2,text_color="#D7E6F0",font=ctk.CTkFont(family=FONT_UI,size=12,weight="bold"))
        self._v121_mode_button.configure(command=lambda:_v121_show_mode_menu(self,self._v121_mode_button));self._v121_mode_button.pack(side="left",padx=(0,4),pady=10)
        self.voice_button=ctk.CTkButton(input_shell,text="",image=_v121_icon(self,"mic",23,UI_TEXT),width=46,height=46,corner_radius=23,fg_color="#122433",hover_color=UI_SURFACE_2,command=self._toggle_voice_visual_mode);self.voice_button.pack(side="left",padx=3,pady=8)
        self.send_button=ctk.CTkButton(input_shell,text="",image=_v121_icon(self,"send",23,"#052035"),width=48,height=48,corner_radius=24,fg_color=UI_ACCENT,hover_color=UI_ACCENT_HOVER,command=self.send_message);self.send_button.pack(side="left",padx=(3,9),pady=7)
        ctk.CTkLabel(composer_zone,text="Enter envia   ·   Shift+Enter quebra linha",text_color="#587489",font=ctk.CTkFont(family=FONT_UI,size=10)).pack(pady=(0,0))
        try:self.root.after(600,self._v121_update_tick)
        except Exception:pass

    @staticmethod
    def estimate_chat_height(text:str)->int:
        raw=str(text or "");lines=raw.splitlines() or [""];visual=0
        for line in lines:
            length=max(1,len(line.expandtabs(4)));visual+=max(1,(length+80)//81)
        return min(max(42,visual*25+16),3600)

    def create_chat_bubble(self,sender,message,is_user=False,is_jarvis=False,is_system=False,timestamp=None,suppress_autoscroll=False):
        import customtkinter as ctk
        if not self.chat_scroll:return None
        initial=_v121_clean_visible_text(message)
        row=ctk.CTkFrame(self.chat_scroll,fg_color=UI_CHAT,corner_radius=0);row.pack(fill="x",padx=30,pady=(9,11))
        if is_system:
            pill=ctk.CTkFrame(row,fg_color="#0C1A24",corner_radius=14,border_width=1,border_color=UI_BORDER_SOFT);pill.pack(anchor="center",padx=80,pady=3)
            label=ctk.CTkLabel(pill,text=initial,wraplength=760,justify="left",text_color=UI_MUTED,font=ctk.CTkFont(family=FONT_UI,size=12));label.pack(padx=16,pady=9)
            self._bind_chat_mousewheel_tree(row)
            if not suppress_autoscroll and not self._restoring_history:self._schedule_chat_scroll(force=False,delay=10)
            return label
        if is_user:
            holder=ctk.CTkFrame(row,fg_color="transparent");holder.pack(side="right",padx=(190,4))
            meta=ctk.CTkFrame(holder,fg_color="transparent");meta.pack(fill="x",pady=(0,4))
            ctk.CTkLabel(meta,text=self._format_message_time(timestamp),text_color="#668298",font=ctk.CTkFont(family=FONT_UI,size=10)).pack(side="right",padx=(0,6))
            bubble=ctk.CTkFrame(holder,fg_color=UI_USER,corner_radius=18,border_width=1,border_color="#263E50");bubble.pack(side="right")
            label=ctk.CTkLabel(bubble,text=initial,wraplength=580,justify="left",anchor="w",text_color=UI_TEXT,font=ctk.CTkFont(family=FONT_UI,size=14));label.pack(padx=16,pady=11)
            self._bind_chat_mousewheel_tree(row)
            if not suppress_autoscroll and not self._restoring_history:self._chat_auto_scroll=True;self._schedule_chat_scroll(force=True,delay=10)
            return label

        body=ctk.CTkFrame(row,fg_color="transparent",corner_radius=0);body.pack(fill="x",padx=(4,70))
        meta=ctk.CTkFrame(body,fg_color="transparent",height=36);meta.pack(fill="x",pady=(0,5));meta.pack_propagate(False)
        ctk.CTkLabel(meta,text="",image=_v121_icon(self,"helmet",30,UI_ACCENT),width=32,height=32).pack(side="left",padx=(0,9),pady=2)
        ctk.CTkLabel(meta,text="JARVIS",text_color=UI_ACCENT,font=ctk.CTkFont(family=FONT_UI,size=12,weight="bold")).pack(side="left",pady=8)
        ctk.CTkLabel(meta,text=self._format_message_time(timestamp),text_color="#668298",font=ctk.CTkFont(family=FONT_UI,size=10)).pack(side="left",padx=(9,0),pady=9)

        screenshot_match=re.search(r"(?:Screenshot(?: do monitor \d+)? salvo(?: em)?|Captura:)\s*:?\s*(.+?\.png)\s*$",initial,re.I)
        if screenshot_match:
            path=screenshot_match.group(1).strip().strip('"')
            card=ctk.CTkFrame(body,fg_color="#0D1A24",corner_radius=17,border_width=1,border_color="#24445C");card.pack(fill="x",pady=(0,5))
            topcard=ctk.CTkFrame(card,fg_color="transparent");topcard.pack(fill="x",padx=16,pady=(13,8))
            ctk.CTkLabel(topcard,text="",image=_v121_icon(self,"check",25,UI_SUCCESS),width=28).pack(side="left",padx=(0,9))
            ctk.CTkLabel(topcard,text="Screenshot salvo com sucesso",text_color=UI_TEXT,font=ctk.CTkFont(family=FONT_UI,size=14,weight="bold")).pack(side="left")
            detail=ctk.CTkFrame(card,fg_color="#101F2B",corner_radius=13,border_width=1,border_color="#203C50");detail.pack(fill="x",padx=14,pady=(0,10))
            name=os.path.basename(path);folder=os.path.dirname(path)
            ctk.CTkLabel(detail,text=name,anchor="w",text_color="#EAF5FD",font=ctk.CTkFont(family=FONT_UI,size=13,weight="bold")).pack(fill="x",padx=14,pady=(10,1))
            ctk.CTkLabel(detail,text=folder,anchor="w",text_color=UI_MUTED_2,font=ctk.CTkFont(family=FONT_UI,size=11)).pack(fill="x",padx=14,pady=(0,9))
            acts=ctk.CTkFrame(card,fg_color="transparent");acts.pack(fill="x",padx=14,pady=(0,13))
            def open_folder():
                try:os.startfile(folder)
                except Exception:pass
            def copy_path():
                try:self._copy_to_clipboard(path)
                except Exception:pass
            ctk.CTkButton(acts,text="Abrir pasta",image=_v121_icon(self,"folder",19,UI_ACCENT),compound="left",height=34,corner_radius=11,fg_color="#112738",hover_color=UI_SURFACE_2,text_color=UI_TEXT,font=ctk.CTkFont(family=FONT_UI,size=11),command=open_folder).pack(side="left",padx=(0,6))
            ctk.CTkButton(acts,text="Copiar caminho",image=_v121_icon(self,"copy",19,UI_ACCENT),compound="left",height=34,corner_radius=11,fg_color="#112738",hover_color=UI_SURFACE_2,text_color=UI_TEXT,font=ctk.CTkFont(family=FONT_UI,size=11),command=copy_path).pack(side="left")
            self._bind_chat_mousewheel_tree(row)
            if not suppress_autoscroll and not self._restoring_history:self._schedule_chat_scroll(force=False,delay=10)
            return ctk.CTkLabel(card,text="")

        msg=ctk.CTkTextbox(body,height=self._estimate_chat_textbox_height(initial),wrap="word",activate_scrollbars=False,
                           font=ctk.CTkFont(family=FONT_UI,size=15),text_color=UI_TEXT,fg_color="transparent",border_width=0,corner_radius=0)
        msg.pack(fill="x",expand=True,padx=0,pady=(0,3));msg.insert("1.0",initial);msg.configure(state="disabled")
        try:msg._textbox.configure(spacing1=2,spacing3=3,selectbackground="#17689B")
        except Exception:pass
        msg.bind("<Control-c>",lambda event,widget=msg:self._copy_text_selection(widget));msg.bind("<Control-C>",lambda event,widget=msg:self._copy_text_selection(widget))
        actions=ctk.CTkFrame(body,fg_color="transparent",height=34);actions.pack(fill="x",pady=(1,0));actions.pack_propagate(False)
        def copy_response():
            try:
                text=msg.get("1.0","end-1c");self._copy_to_clipboard(text);copy_btn.configure(text="Copiado")
                self.root.after(1100,lambda:copy_btn.configure(text="Copiar"))
            except Exception:pass
        def repeat_response():
            try:
                last=""
                for item in reversed(getattr(self,"chat_history",[]) or []):
                    if item.get("is_user"):last=str(item.get("message") or "").strip();break
                if last:_v121_prefill(self,last,send=True)
            except Exception:pass
        copy_btn=ctk.CTkButton(actions,text="Copiar",image=_v121_icon(self,"copy",17,UI_MUTED),compound="left",width=82,height=30,corner_radius=9,fg_color="transparent",hover_color=UI_SURFACE_2,text_color=UI_MUTED,font=ctk.CTkFont(family=FONT_UI,size=11),command=copy_response);copy_btn.pack(side="left",padx=(0,4))
        ctk.CTkButton(actions,text="Repetir",image=_v121_icon(self,"refresh",17,UI_MUTED),compound="left",width=88,height=30,corner_radius=9,fg_color="transparent",hover_color=UI_SURFACE_2,text_color=UI_MUTED,font=ctk.CTkFont(family=FONT_UI,size=11),command=repeat_response).pack(side="left")
        self._bind_chat_mousewheel_tree(row)
        if not suppress_autoscroll and not self._restoring_history:self._schedule_chat_scroll(force=False,delay=10)
        return msg

    def show_welcome_message(self):
        import customtkinter as ctk
        if not self.chat_scroll:return
        try:
            old=getattr(self,"_v121_welcome",None)
            if old is not None and old.winfo_exists():old.destroy()
        except Exception:pass
        welcome=ctk.CTkFrame(self.chat_scroll,fg_color="transparent",corner_radius=0);self._v121_welcome=welcome;welcome.pack(fill="both",expand=True,padx=34,pady=(72,22))
        ctk.CTkLabel(welcome,text="",image=_v121_icon(self,"helmet",72,UI_ACCENT),width=78,height=78).pack(pady=(0,15))
        ctk.CTkLabel(welcome,text="Como posso ajudar?",text_color=UI_TEXT,font=ctk.CTkFont(family=FONT_UI,size=30,weight="bold")).pack(pady=(0,7))
        ctk.CTkLabel(welcome,text="Converse normalmente ou peça uma ação no computador. Você não precisa decorar comandos.",wraplength=760,justify="center",text_color=UI_MUTED,font=ctk.CTkFont(family=FONT_UI,size=13)).pack(pady=(0,28))
        cards=ctk.CTkFrame(welcome,fg_color="transparent");cards.pack(fill="x",padx=10)
        suggestions=[
            ("search","Pesquisar na internet","Encontre informações atualizadas","pesquise ",False),
            ("grid","Abrir um programa","Execute seus aplicativos rapidamente","abre ",False),
            ("file","Criar arquivo ou pasta","Organize seus arquivos","cria ",False),
            ("music","Tocar uma música","Abra suas músicas favoritas","toca música ",False),
            ("screen","Capturar minha tela","Faça um print da tela","tira um print",True),
        ]
        for idx,(kind,title,desc,prompt,send_now) in enumerate(suggestions):
            card=ctk.CTkButton(cards,text=f"{title}\n{desc}",image=_v121_icon(self,kind,27,UI_ACCENT),compound="top",width=165,height=104,corner_radius=15,
                               fg_color="#0C1A24",hover_color="#102638",border_width=1,border_color="#1D4058",text_color=UI_TEXT,
                               font=ctk.CTkFont(family=FONT_UI,size=11),command=lambda p=prompt,s=send_now:_v121_prefill(self,p,send=s))
            card.grid(row=0,column=idx,padx=5,pady=5,sticky="nsew");cards.grid_columnconfigure(idx,weight=1)

    original_send_message=getattr(cls,"send_message",None)
    if callable(original_send_message):
        def send_message(self,event=None):
            try:
                welcome=getattr(self,"_v121_welcome",None)
                if welcome is not None and welcome.winfo_exists():welcome.destroy();self._v121_welcome=None
            except Exception:pass
            return original_send_message(self,event)
        cls.send_message=send_message

    original_focus_style=getattr(cls,"_set_input_focus",None)
    def set_input_focus(self,focused:bool):
        try:
            if self.input_shell:self.input_shell.configure(border_color=UI_ACCENT if focused else "#23516E",fg_color="#10212E" if focused else "#0E1A24")
        except Exception:
            if callable(original_focus_style):
                try:original_focus_style(self,focused)
                except Exception:pass
    cls._set_input_focus=set_input_focus

    cls._create_main_layout=create_main_layout
    cls._create_chat_area=create_chat_area
    cls._create_chat_bubble=create_chat_bubble
    cls._estimate_chat_textbox_height=estimate_chat_height
    cls._show_welcome_message=show_welcome_message
    cls._apply_sidebar_state=apply_sidebar_state
    cls._cycle_sidebar_state=cycle_sidebar_state
    cls._show_quick_actions_menu=lambda self,widget:_v121_toggle_plus_panel(self,widget)
    cls._on_chat_mousewheel=_v121_on_chat_mousewheel
    cls._v121_plus_popup=None

    original_init=getattr(cls,"__init__",None)
    if callable(original_init):
        def __init__(self,*args,**kwargs):
            original_init(self,*args,**kwargs)
            try:
                self.root.title("JARVIS")
                self.root.geometry("1440x900")
                self.root.minsize(1100,720)
                self.root.configure(fg_color=UI_BG)
            except Exception:pass
            try:
                self._composer_placeholder_text="Pergunte ao JARVIS..."
                if getattr(self,"_composer_placeholder_active",False):
                    self.text_input.configure(state="normal",text_color=UI_MUTED_2);self.text_input.delete("1.0","end");self.text_input.insert("1.0",self._composer_placeholder_text)
            except Exception:pass
        cls.__init__=__init__

    router_mod=sys.modules.get("jarvis_router")
    if router_mod is not None:
        try:mod.route_v8=router_mod.route
        except Exception:pass
    _PATCHED.add("gui")


def _apply_loaded_patches() -> None:
    global _APPLYING
    if _APPLYING:
        return
    _APPLYING = True
    try:
        _patch_context_engine()
        _patch_router()
        _patch_actions()
        _patch_core()
        _patch_voice_engine()
        _patch_gui()
    except Exception:
        # The release layer is explicitly fail-open; startup stability wins.
        pass
    finally:
        _APPLYING = False


def install() -> None:
    """Install import-time patch hooks once."""
    global _IMPORT_WRAPPED
    if _IMPORT_WRAPPED:
        _apply_loaded_patches()
        return

    def wrapped_import(name, globals=None, locals=None, fromlist=(), level=0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
        try:
            _apply_loaded_patches()
        except Exception:
            pass
        return module

    builtins.__import__ = wrapped_import
    _IMPORT_WRAPPED = True
    _apply_loaded_patches()


__all__ = ["RELEASE_LAYER", "install"]
