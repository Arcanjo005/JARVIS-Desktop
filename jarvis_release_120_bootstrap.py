"""JARVIS Desktop 1.2.0 Chat Core / Blue Core compatibility layer.

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

RELEASE_LAYER = "1.2.0-chatcore1"

_ORIGINAL_IMPORT = builtins.__import__
_IMPORT_WRAPPED = False
_APPLYING = False
_PATCHED = set()


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
        cls.FIRST_TOKEN_TIMEOUT_MS = max(int(getattr(cls, "FIRST_TOKEN_TIMEOUT_MS", 5600)), 7000)
        cls.TOTAL_RESPONSE_TIMEOUT_MS = max(int(getattr(cls, "TOTAL_RESPONSE_TIMEOUT_MS", 9000)), 12000)
    except Exception:
        pass

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
            result = original_degraded(self, message, source=source)
            key = _norm(result)
            if str(source or "text").lower() == "text" and (
                "entendi sua pergunta mas nao consegui concluir a resposta neste turno" in key
                or "entendi a mensagem mas nao consegui concluir a resposta neste turno" in key
            ):
                return "A IA online não respondeu a tempo neste turno. Sua mensagem foi entendida; tente novamente em alguns segundos."
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
    # JARVIS 1.2.0 CHAT CORE UI
    # ------------------------------------------------------------------
    # The stable v1.1.2 GUI class remains the implementation base.  Only the
    # layout/rendering methods are replaced after import, keeping command,
    # memory, streaming, voice and updater logic untouched.
    UI_BG = "#0E0F10"
    UI_SIDEBAR = "#171819"
    UI_SURFACE = "#202124"
    UI_SURFACE_2 = "#292B30"
    UI_BORDER = "#36383D"
    UI_TEXT = "#F2F3F5"
    UI_MUTED = "#9AA0AA"
    UI_MUTED_2 = "#6F7680"
    UI_ACCENT = "#3FA9FF"
    UI_ACCENT_HOVER = "#64BAFF"
    UI_USER = "#2B2D31"
    UI_SUCCESS = "#43D79A"

    try:
        cls.SIDEBAR_MIN = 64
        cls.SIDEBAR_DEFAULT = 258
        cls.SIDEBAR_MAX = 300
        cls.COMPOSER_MIN_HEIGHT = 54
        cls.COMPOSER_MAX_HEIGHT = 160
    except Exception:
        pass

    def _v120_prefill(self, text: str, *, send: bool = False):
        try:
            popup = getattr(self, "_v120_plus_popup", None)
            if popup is not None and popup.winfo_exists():
                popup.destroy()
        except Exception:
            pass
        try:
            self._v120_plus_popup = None
        except Exception:
            pass
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

    def _v120_set_mode(self, mode: str):
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
        except Exception:
            pass
        try:
            self._save_quick_preferences()
        except Exception:
            pass
        labels = {"auto": "Auto", "conversa": "Conversa", "comando": "Comando"}
        try:
            self._v120_mode_button.configure(text=labels[mode] + "  ▾")
        except Exception:
            pass

    def _v120_show_mode_menu(self, widget):
        try:
            self._popup_dark_menu(
                widget,
                [
                    ("Automático", lambda: _v120_set_mode(self, "auto")),
                    ("Conversa", lambda: _v120_set_mode(self, "conversa")),
                    ("Comando", lambda: _v120_set_mode(self, "comando")),
                ],
                upward=True,
            )
        except Exception:
            pass

    def _v120_send_help(self):
        _v120_prefill(self, "ajuda", send=True)

    def _v120_open_settings_menu(self, widget):
        entries = [
            ("Configurar IA", self._open_api_settings),
            ("Diagnóstico", self._open_diagnostic_panel),
            ("Reiniciar voz", lambda: _v120_prefill(self, "reiniciar voz", send=True)),
            ("---", None),
            ("Verificar atualização", self._update_now),
        ]
        try:
            self._popup_dark_menu(widget, entries, upward=True)
        except Exception:
            pass

    def _v120_toggle_plus_panel(self, widget):
        import customtkinter as ctk
        try:
            old = getattr(self, "_v120_plus_popup", None)
            if old is not None and old.winfo_exists():
                old.destroy()
                self._v120_plus_popup = None
                return
        except Exception:
            self._v120_plus_popup = None

        popup = ctk.CTkToplevel(self.root)
        self._v120_plus_popup = popup
        popup.overrideredirect(True)
        popup.configure(fg_color=UI_BG)
        try:
            popup.attributes("-topmost", True)
        except Exception:
            pass

        width, height = 372, 446
        try:
            x = max(self.root.winfo_rootx() + 8, widget.winfo_rootx() - 8)
            y = max(self.root.winfo_rooty() + 8, widget.winfo_rooty() - height - 12)
        except Exception:
            x, y = 60, 120
        popup.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

        shell = ctk.CTkFrame(
            popup, fg_color=UI_SURFACE, corner_radius=18,
            border_width=1, border_color=UI_BORDER,
        )
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        top = ctk.CTkFrame(shell, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(
            top, text="O que você quer fazer?", anchor="w",
            text_color=UI_TEXT,
            font=ctk.CTkFont(family="Bahnschrift", size=15, weight="bold"),
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            top, text="×", width=30, height=30, corner_radius=10,
            fg_color="transparent", hover_color=UI_SURFACE_2, text_color=UI_MUTED,
            font=ctk.CTkFont(size=18),
            command=lambda: (popup.destroy(), setattr(self, "_v120_plus_popup", None)),
        ).pack(side="right")

        ctk.CTkLabel(
            shell,
            text="Escolha uma opção ou continue digitando normalmente no chat.",
            anchor="w", justify="left", wraplength=330,
            text_color=UI_MUTED,
            font=ctk.CTkFont(family="Tahoma", size=10),
        ).pack(fill="x", padx=16, pady=(0, 10))

        items = [
            ("⌕", "Pesquisar na internet", "Encontrar informações atuais", "pesquise ", False),
            ("▣", "Abrir um programa", "Opera, Discord, OBS e outros", "abre ", False),
            ("♫", "Tocar uma música", "Procurar e abrir uma música", "toca música ", False),
            ("＋", "Criar arquivo ou pasta", "Criar algo no computador", "cria ", False),
            ("◉", "Capturar minha tela", "Salvar um print agora", "tira um print", True),
            ("▤", "Organizar janelas", "Mover, minimizar ou maximizar", "move ", False),
            ("◇", "Diagnóstico do JARVIS", "Verificar se está tudo funcionando", "diagnóstico completo", True),
            ("?", "Ajuda", "Ver exemplos do que você pode pedir", "ajuda", True),
        ]
        body = ctk.CTkFrame(shell, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        for symbol, title, desc, prompt, send_now in items:
            row = ctk.CTkButton(
                body,
                text=f"{symbol}   {title}\n      {desc}",
                height=45, anchor="w", corner_radius=12,
                fg_color="transparent", hover_color=UI_SURFACE_2,
                text_color=UI_TEXT,
                font=ctk.CTkFont(family="Tahoma", size=10),
                command=lambda p=prompt, s=send_now: _v120_prefill(self, p, send=s),
            )
            row.pack(fill="x", padx=2, pady=1)
        popup.bind("<Escape>", lambda _e: popup.destroy(), add="+")
        try:
            popup.after(30, popup.focus_force)
        except Exception:
            pass

    def _v120_sidebar_full(self, parent):
        import customtkinter as ctk
        frame = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        self._v120_sidebar_full_frame = frame
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        brand = ctk.CTkFrame(frame, fg_color="transparent", height=42)
        brand.pack(fill="x", pady=(0, 10))
        brand.pack_propagate(False)
        self.sidebar_state_button = ctk.CTkButton(
            brand, text="", image=self._get_ui_icon("sidebar", 18, UI_MUTED),
            width=36, height=36, corner_radius=11,
            fg_color="transparent", hover_color=UI_SURFACE_2,
            command=self._cycle_sidebar_state,
        )
        self.sidebar_state_button.pack(side="left", padx=(0, 8), pady=3)
        ctk.CTkLabel(
            brand, text="JARVIS", text_color=UI_TEXT,
            font=ctk.CTkFont(family="Bahnschrift", size=15, weight="bold"),
        ).pack(side="left", pady=7)

        self._new_chat_button = ctk.CTkButton(
            frame, text="＋   Novo chat", height=42, anchor="w", corner_radius=12,
            fg_color=UI_SURFACE_2, hover_color="#34363C", text_color=UI_TEXT,
            font=ctk.CTkFont(family="Tahoma", size=11, weight="bold"),
            command=self._new_conversation,
        )
        self._new_chat_button.pack(fill="x", pady=(0, 5))

        self._conversation_search_button = ctk.CTkButton(
            frame, text="⌕   Buscar conversas", height=38, anchor="w", corner_radius=11,
            fg_color="transparent", hover_color=UI_SURFACE_2, text_color=UI_MUTED,
            font=ctk.CTkFont(family="Tahoma", size=10),
        )
        self._conversation_search_button.configure(
            command=lambda: self._open_conversation_search_popover(self._conversation_search_button)
        )
        self._conversation_search_button.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            frame, text="CHATS", anchor="w", text_color=UI_MUTED_2,
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
        ).pack(fill="x", padx=5, pady=(0, 5))

        self.conversation_list_frame = ctk.CTkScrollableFrame(
            frame, fg_color="transparent", corner_radius=0, border_width=0,
            scrollbar_button_color="#37393E", scrollbar_button_hover_color="#484B52",
        )
        self.conversation_list_frame.pack(fill="both", expand=True, pady=(0, 8))
        self.root.after(100, self._refresh_conversation_list)

        bottom = ctk.CTkFrame(frame, fg_color="transparent")
        bottom.pack(fill="x", side="bottom")

        def nav_button(text, command):
            button = ctk.CTkButton(
                bottom, text=text, height=36, anchor="w", corner_radius=10,
                fg_color="transparent", hover_color=UI_SURFACE_2,
                text_color=UI_MUTED, font=ctk.CTkFont(family="Tahoma", size=10),
                command=command,
            )
            button.pack(fill="x", pady=1)
            return button

        nav_button("?   Ajuda", _v120_send_help.__get__(self, type(self)))
        nav_button("◇   Diagnóstico", self._open_diagnostic_panel)
        self.api_button = nav_button("⚙   Configurar IA", self._open_api_settings)
        self.update_button = nav_button("↻   Atualizações", self._update_now)

        status = ctk.CTkFrame(bottom, fg_color="transparent", height=35)
        status.pack(fill="x", pady=(7, 0))
        status.pack_propagate(False)
        self.status_dot = ctk.CTkLabel(
            status, text="●", width=16, text_color=UI_SUCCESS,
            font=ctk.CTkFont(size=10),
        )
        self.status_dot.pack(side="left", padx=(5, 2))
        self.status_label = ctk.CTkLabel(
            status, text="ONLINE", text_color=UI_MUTED,
            font=ctk.CTkFont(family="Tahoma", size=9, weight="bold"),
        )
        self.status_label.pack(side="left")
        ctk.CTkLabel(
            status, text="1.2.0", text_color=UI_MUTED_2,
            font=ctk.CTkFont(family="Consolas", size=8),
        ).pack(side="right", padx=5)

    def _v120_sidebar_compact(self, parent):
        import customtkinter as ctk
        frame = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        self._v120_sidebar_compact_frame = frame

        def compact_button(text, command, *, accent=False):
            btn = ctk.CTkButton(
                frame, text=text, width=42, height=42, corner_radius=13,
                fg_color=UI_SURFACE_2 if accent else "transparent",
                hover_color="#35373D", text_color=UI_TEXT if accent else UI_MUTED,
                font=ctk.CTkFont(family="Bahnschrift", size=17, weight="bold"),
                command=command,
            )
            btn.pack(padx=7, pady=3)
            return btn

        self._v120_compact_sidebar_button = ctk.CTkButton(
            frame, text="", image=self._get_ui_icon("sidebar", 18, UI_MUTED),
            width=42, height=42, corner_radius=13,
            fg_color="transparent", hover_color=UI_SURFACE_2,
            command=self._cycle_sidebar_state,
        )
        self._v120_compact_sidebar_button.pack(padx=7, pady=(10, 6))
        compact_button("+", self._new_conversation, accent=True)
        compact_button("⌕", lambda: self._open_conversation_search_popover(self._v120_compact_search))
        self._v120_compact_search = frame.winfo_children()[-1]
        spacer = ctk.CTkFrame(frame, fg_color="transparent")
        spacer.pack(fill="both", expand=True)
        compact_button("?", _v120_send_help.__get__(self, type(self)))
        compact_button("◇", self._open_diagnostic_panel)
        compact_button("⚙", lambda: _v120_open_settings_menu(self, self._v120_compact_settings))
        self._v120_compact_settings = frame.winfo_children()[-1]
        ctk.CTkLabel(frame, text="●", text_color=UI_SUCCESS, font=ctk.CTkFont(size=10)).pack(pady=(8, 14))

    def create_main_layout(self):
        import customtkinter as ctk
        main_container = ctk.CTkFrame(self.root, fg_color=UI_BG, corner_radius=0)
        main_container.pack(fill="both", expand=True)
        self._v120_main_container = main_container

        content = ctk.CTkFrame(main_container, fg_color=UI_BG, corner_radius=0)
        self.content_frame = content
        content.pack(fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=0, minsize=258)
        content.grid_columnconfigure(1, weight=1)

        self._sidebar_state = str(getattr(self, "_sidebar_state", "full") or "full")
        if self._sidebar_state not in {"full", "compact"}:
            self._sidebar_state = "full"
        self._sidebar_last_full_width = 258
        self._sidebar_width = 258

        side_panel = ctk.CTkFrame(
            content, width=258, fg_color=UI_SIDEBAR, corner_radius=0,
            border_width=0,
        )
        self.side_panel = side_panel
        self.sidebar_splitter = None
        side_panel.grid(row=0, column=0, sticky="nsew")
        side_panel.grid_propagate(False)
        _v120_sidebar_full(self, side_panel)
        _v120_sidebar_compact(self, side_panel)

        chat_panel = ctk.CTkFrame(content, fg_color=UI_BG, corner_radius=0)
        self._v120_chat_panel = chat_panel
        chat_panel.grid(row=0, column=1, sticky="nsew")
        self._create_chat_area(chat_panel)

        self._apply_sidebar_state(self._sidebar_state)

    def apply_sidebar_state(self, state: str):
        state = "compact" if str(state).lower() in {"compact", "closed"} else "full"
        self._sidebar_state = state
        try:
            if state == "compact":
                self._v120_sidebar_full_frame.pack_forget()
                self._v120_sidebar_compact_frame.pack(fill="both", expand=True)
                width = 64
            else:
                self._v120_sidebar_compact_frame.pack_forget()
                self._v120_sidebar_full_frame.pack(fill="both", expand=True, padx=10, pady=10)
                width = 258
            self._sidebar_width = width
            self.content_frame.grid_columnconfigure(0, minsize=width)
            self.side_panel.configure(width=width)
            try:
                self._save_sidebar_width()
            except Exception:
                pass
        except Exception as exc:
            _safe_log(self, "warning", f"Não foi possível alternar a barra lateral: {exc}", "GUI")

    def cycle_sidebar_state(self):
        self._apply_sidebar_state("compact" if getattr(self, "_sidebar_state", "full") == "full" else "full")

    def create_chat_area(self, parent):
        import customtkinter as ctk
        wrapper = ctk.CTkFrame(parent, fg_color=UI_BG, corner_radius=0)
        wrapper.pack(fill="both", expand=True, padx=(24, 24), pady=(12, 14))
        self._v120_chat_wrapper = wrapper

        # Minimal top row: no application header, logo, system gauges or command center.
        top = ctk.CTkFrame(wrapper, fg_color="transparent", height=34)
        top.pack(fill="x", padx=4, pady=(0, 5))
        top.pack_propagate(False)
        self.current_conversation_label = ctk.CTkLabel(
            top, text="Nova conversa", anchor="w",
            text_color=UI_MUTED,
            font=ctk.CTkFont(family="Tahoma", size=10, weight="bold"),
        )
        self.current_conversation_label.pack(side="left", padx=(6, 0), pady=7)

        # Keep source/activity targets available for the existing core, but subtle.
        self.activity_label = ctk.CTkLabel(
            top, text="Pronto", text_color=UI_MUTED_2,
            font=ctk.CTkFont(family="Tahoma", size=9),
        )
        self.activity_label.pack(side="right", padx=(8, 5), pady=7)
        self.source_badge = ctk.CTkLabel(
            top, text="LOCAL", width=48, height=22, corner_radius=9,
            fg_color="#173227", text_color="#78E2AE",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
        )
        self.source_badge.pack(side="right", padx=3, pady=5)

        # Agent progress remains available but is hidden until an agent task starts.
        self.agent_hud = ctk.CTkFrame(
            wrapper, fg_color="#171B20", corner_radius=14,
            border_width=1, border_color="#2D465B",
        )
        hud_top = ctk.CTkFrame(self.agent_hud, fg_color="transparent")
        hud_top.pack(fill="x", padx=14, pady=(9, 3))
        self.agent_hud_title = ctk.CTkLabel(
            hud_top, text="JARVIS está trabalhando", text_color="#8ED0FF",
            font=ctk.CTkFont(family="Tahoma", size=9, weight="bold"),
        )
        self.agent_hud_title.pack(side="left")
        self.agent_stop_button = ctk.CTkButton(
            hud_top, text="Parar", width=62, height=24, corner_radius=8,
            fg_color="#47272B", hover_color="#623238", text_color="#FFBBC2",
            font=ctk.CTkFont(family="Tahoma", size=8, weight="bold"),
            command=self._stop_agent_goal,
        )
        self.agent_stop_button.pack(side="right")
        self.agent_hud_step = ctk.CTkLabel(
            self.agent_hud, text="", anchor="w", justify="left", wraplength=780,
            text_color="#D8DEE7", font=ctk.CTkFont(family="Tahoma", size=10),
        )
        self.agent_hud_step.pack(fill="x", padx=14, pady=(0, 5))
        self.agent_hud_progress = ctk.CTkProgressBar(
            self.agent_hud, height=4, corner_radius=2,
            fg_color="#27313B", progress_color=UI_ACCENT,
        )
        self.agent_hud_progress.pack(fill="x", padx=14, pady=(0, 10))
        self.agent_hud_progress.set(0.0)
        self.agent_hud.pack_forget()

        self.chat_scroll = ctk.CTkScrollableFrame(
            wrapper, fg_color=UI_BG, corner_radius=0, border_width=0,
            scrollbar_button_color="#393B40", scrollbar_button_hover_color="#50535A",
        )
        self.chat_scroll.pack(fill="both", expand=True, pady=(0, 12))
        self.chat_display = None
        self._install_chat_mousewheel()

        composer_zone = ctk.CTkFrame(wrapper, fg_color="transparent")
        composer_zone.pack(fill="x", side="bottom")
        input_shell = ctk.CTkFrame(
            composer_zone, fg_color=UI_SURFACE, corner_radius=25,
            border_width=1, border_color=UI_BORDER,
        )
        self.input_shell = input_shell
        input_shell.pack(fill="x", padx=(52, 52), pady=(0, 4))

        self.quick_menu_button = ctk.CTkButton(
            input_shell, text="+", width=40, height=40, corner_radius=20,
            fg_color="transparent", hover_color="#34363C", text_color=UI_TEXT,
            font=ctk.CTkFont(family="Arial", size=22),
            command=lambda: _v120_toggle_plus_panel(self, self.quick_menu_button),
        )
        self.quick_menu_button.pack(side="left", padx=(8, 2), pady=7)

        self._composer_placeholder_text = "Pergunte ao JARVIS"
        self.text_input = ctk.CTkTextbox(
            input_shell, height=self.COMPOSER_MIN_HEIGHT, wrap="word", activate_scrollbars=False,
            font=ctk.CTkFont(family="Tahoma", size=13), text_color=UI_TEXT,
            fg_color="transparent", border_width=0, corner_radius=0,
        )
        self.text_input.pack(side="left", fill="x", expand=True, padx=(5, 6), pady=6)
        self.text_input.bind("<FocusIn>", self._composer_focus_in, add="+")
        self.text_input.bind("<FocusOut>", self._composer_focus_out, add="+")
        self.text_input.bind("<Return>", self._on_composer_return, add="+")
        self.text_input.bind("<KeyRelease>", self._resize_composer, add="+")
        self._composer_set_placeholder()

        labels = {"auto": "Auto", "conversa": "Conversa", "comando": "Comando"}
        self._v120_mode_button = ctk.CTkButton(
            input_shell, text=labels.get(getattr(self, "interaction_mode", "auto"), "Auto") + "  ▾",
            width=78, height=36, corner_radius=18,
            fg_color="transparent", hover_color="#34363C", text_color=UI_MUTED,
            font=ctk.CTkFont(family="Tahoma", size=9, weight="bold"),
        )
        self._v120_mode_button.configure(command=lambda: _v120_show_mode_menu(self, self._v120_mode_button))
        self._v120_mode_button.pack(side="left", padx=(0, 1), pady=9)

        self.voice_button = ctk.CTkButton(
            input_shell, text="", image=self._get_ui_icon("voice", 18, UI_TEXT),
            width=40, height=40, corner_radius=20,
            fg_color="transparent", hover_color="#34363C", text_color=UI_TEXT,
            command=self._toggle_voice_visual_mode,
        )
        self.voice_button.pack(side="left", padx=2, pady=7)

        self.send_button = ctk.CTkButton(
            input_shell, text="", image=self._get_ui_icon("send", 18, "#071018"),
            width=40, height=40, corner_radius=20,
            fg_color=UI_ACCENT, hover_color=UI_ACCENT_HOVER, text_color="#071018",
            command=self.send_message,
        )
        self.send_button.pack(side="left", padx=(2, 8), pady=7)

        ctk.CTkLabel(
            composer_zone,
            text="Enter envia  •  Shift+Enter quebra linha  •  O JARVIS pode errar; confira informações importantes.",
            text_color="#5E646D", font=ctk.CTkFont(family="Tahoma", size=8),
        ).pack(pady=(0, 0))

    @staticmethod
    def estimate_chat_height(text: str) -> int:
        raw = str(text or "")
        lines = raw.splitlines() or [""]
        visual = 0
        for line in lines:
            length = max(1, len(line.expandtabs(4)))
            visual += max(1, (length + 73) // 74)
        return min(max(34, visual * 22 + 12), 3200)

    def create_chat_bubble(self, sender, message, is_user=False, is_jarvis=False, is_system=False, timestamp=None, suppress_autoscroll=False):
        import customtkinter as ctk
        if not self.chat_scroll:
            return None
        row = ctk.CTkFrame(self.chat_scroll, fg_color=UI_BG, corner_radius=0)
        row.pack(fill="x", padx=38, pady=(7, 8))
        initial_text = str(message or "")

        if is_system:
            pill = ctk.CTkFrame(row, fg_color="#1A1C1F", corner_radius=12, border_width=1, border_color="#2A2D32")
            pill.pack(anchor="center", padx=80, pady=2)
            label = ctk.CTkLabel(
                pill, text=initial_text, wraplength=700, justify="left",
                text_color=UI_MUTED, font=ctk.CTkFont(family="Tahoma", size=10),
            )
            label.pack(padx=12, pady=7)
            self._bind_chat_mousewheel_tree(row)
            if not suppress_autoscroll and not self._restoring_history:
                self._schedule_chat_scroll(force=False, delay=10)
            return label

        if is_user:
            bubble = ctk.CTkFrame(row, fg_color=UI_USER, corner_radius=18, border_width=0)
            bubble.pack(side="right", padx=(160, 4))
            label = ctk.CTkLabel(
                bubble, text=initial_text, wraplength=560, justify="left", anchor="w",
                text_color=UI_TEXT, font=ctk.CTkFont(family="Tahoma", size=12),
            )
            label.pack(padx=14, pady=10)
            self._bind_chat_mousewheel_tree(row)
            if not suppress_autoscroll and not self._restoring_history:
                self._chat_auto_scroll = True
                self._schedule_chat_scroll(force=True, delay=10)
            return label

        # JARVIS: plain response on the canvas, similar to a document instead of a card.
        body = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
        body.pack(fill="x", padx=(8, 82))
        ctk.CTkLabel(
            body, text="JARVIS", anchor="w", text_color=UI_ACCENT,
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold"),
        ).pack(fill="x", padx=(3, 0), pady=(0, 2))
        msg = ctk.CTkTextbox(
            body, height=self._estimate_chat_textbox_height(initial_text), wrap="word",
            activate_scrollbars=False, font=ctk.CTkFont(family="Tahoma", size=13),
            text_color=UI_TEXT, fg_color="transparent", border_width=0, corner_radius=0,
        )
        msg.pack(fill="x", expand=True, padx=0, pady=(0, 1))
        msg.insert("1.0", initial_text)
        msg.configure(state="disabled")
        msg.bind("<Control-c>", lambda event, widget=msg: self._copy_text_selection(widget))
        msg.bind("<Control-C>", lambda event, widget=msg: self._copy_text_selection(widget))

        actions = ctk.CTkFrame(body, fg_color="transparent", height=28)
        actions.pack(fill="x", pady=(0, 1))
        actions.pack_propagate(False)

        def copy_response():
            try:
                text = msg.get("1.0", "end-1c")
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self.root.update_idletasks()
                copy_btn.configure(text="Copiado")
                self.root.after(1100, lambda: copy_btn.configure(text="Copiar"))
            except Exception:
                pass

        def repeat_response():
            try:
                last = ""
                for item in reversed(getattr(self, "chat_history", []) or []):
                    if item.get("is_user"):
                        last = str(item.get("message") or "").strip()
                        break
                if last:
                    _v120_prefill(self, last, send=True)
            except Exception:
                pass

        copy_btn = ctk.CTkButton(
            actions, text="Copiar", width=55, height=24, corner_radius=8,
            fg_color="transparent", hover_color=UI_SURFACE_2, text_color=UI_MUTED_2,
            font=ctk.CTkFont(family="Tahoma", size=8), command=copy_response,
        )
        copy_btn.pack(side="left", padx=(0, 3))
        ctk.CTkButton(
            actions, text="↻ Repetir", width=66, height=24, corner_radius=8,
            fg_color="transparent", hover_color=UI_SURFACE_2, text_color=UI_MUTED_2,
            font=ctk.CTkFont(family="Tahoma", size=8), command=repeat_response,
        ).pack(side="left")

        self._bind_chat_mousewheel_tree(row)
        if not suppress_autoscroll and not self._restoring_history:
            self._schedule_chat_scroll(force=False, delay=10)
        return msg

    def show_welcome_message(self):
        import customtkinter as ctk
        if not self.chat_scroll:
            return
        try:
            old = getattr(self, "_v120_welcome", None)
            if old is not None and old.winfo_exists():
                old.destroy()
        except Exception:
            pass
        welcome = ctk.CTkFrame(self.chat_scroll, fg_color="transparent", corner_radius=0)
        self._v120_welcome = welcome
        welcome.pack(fill="both", expand=True, padx=44, pady=(78, 20))
        ctk.CTkLabel(
            welcome, text="Como posso ajudar?", text_color=UI_TEXT,
            font=ctk.CTkFont(family="Bahnschrift", size=27, weight="bold"),
        ).pack(pady=(0, 8))
        ctk.CTkLabel(
            welcome,
            text="Converse normalmente ou peça uma ação no computador. Você não precisa decorar comandos.",
            wraplength=650, justify="center", text_color=UI_MUTED,
            font=ctk.CTkFont(family="Tahoma", size=11),
        ).pack(pady=(0, 24))

        cards = ctk.CTkFrame(welcome, fg_color="transparent")
        cards.pack()
        suggestions = [
            ("Abrir um programa", "Ex.: abre o Opera", "abre "),
            ("Pesquisar na internet", "Ex.: pesquise placas de vídeo", "pesquise "),
            ("Controlar meu PC", "Status, janelas, monitores e arquivos", "status do pc"),
            ("Ver o que posso fazer", "Guia simples com exemplos", "ajuda"),
        ]
        for index, (title, desc, prompt) in enumerate(suggestions):
            btn = ctk.CTkButton(
                cards, text=f"{title}\n{desc}", width=275, height=68, anchor="w",
                corner_radius=15, fg_color="#17191C", hover_color=UI_SURFACE,
                border_width=1, border_color="#2C2F34", text_color=UI_TEXT,
                font=ctk.CTkFont(family="Tahoma", size=10),
                command=lambda p=prompt: _v120_prefill(self, p, send=(p in {"status do pc", "ajuda"})),
            )
            btn.grid(row=index // 2, column=index % 2, padx=5, pady=5, sticky="nsew")

    original_send_message = getattr(cls, "send_message", None)
    if callable(original_send_message):
        def send_message(self, event=None):
            try:
                welcome = getattr(self, "_v120_welcome", None)
                if welcome is not None and welcome.winfo_exists():
                    welcome.destroy()
                    self._v120_welcome = None
            except Exception:
                pass
            return original_send_message(self, event)
        cls.send_message = send_message

    original_focus_style = getattr(cls, "_set_input_focus", None)
    def set_input_focus(self, focused: bool):
        try:
            if self.input_shell:
                self.input_shell.configure(
                    border_color=UI_ACCENT if focused else UI_BORDER,
                    fg_color="#222428" if focused else UI_SURFACE,
                )
        except Exception:
            if callable(original_focus_style):
                try:
                    original_focus_style(self, focused)
                except Exception:
                    pass
    cls._set_input_focus = set_input_focus

    cls._create_main_layout = create_main_layout
    cls._create_chat_area = create_chat_area
    cls._create_chat_bubble = create_chat_bubble
    cls._estimate_chat_textbox_height = estimate_chat_height
    cls._show_welcome_message = show_welcome_message
    cls._apply_sidebar_state = apply_sidebar_state
    cls._cycle_sidebar_state = cycle_sidebar_state
    cls._show_quick_actions_menu = lambda self, widget: _v120_toggle_plus_panel(self, widget)

    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        def __init__(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            try:
                self.root.title("JARVIS")
                self.root.geometry("1360x860")
                self.root.minsize(980, 660)
                self.root.configure(fg_color=UI_BG)
            except Exception:
                pass
            try:
                self._composer_placeholder_text = "Pergunte ao JARVIS"
                if getattr(self, "_composer_placeholder_active", False):
                    self.text_input.configure(state="normal", text_color=UI_MUTED)
                    self.text_input.delete("1.0", "end")
                    self.text_input.insert("1.0", self._composer_placeholder_text)
            except Exception:
                pass
        cls.__init__ = __init__

    # Ensure GUI uses the patched router even if it cached a function reference.
    router_mod = sys.modules.get("jarvis_router")
    if router_mod is not None:
        try:
            mod.route_v8 = router_mod.route
        except Exception:
            pass
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
