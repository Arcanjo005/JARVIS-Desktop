"""JARVIS Desktop 1.1.4 compatibility/reliability layer.

This module is imported by jarvis_version.py.  It keeps the known-good v1.1.2
startup path intact while applying narrowly-scoped, fail-open fixes discovered
from real 1.1.3/1.1.4 field diagnostics.

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

RELEASE_LAYER = "1.1.4-safe3"

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
                headers={"User-Agent": "JARVIS-Desktop/1.1.4"},
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

    # Small, low-risk UI finish: beginner quick actions above the composer and
    # a clearer placeholder. It is injected after the proven v1.1.2 UI builds.
    original_init = getattr(cls, "__init__", None)
    if callable(original_init):
        def __init__(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            try:
                self._composer_placeholder_text = "Digite uma mensagem ou comando. Ex.: abre o Opera, status do PC, ajuda..."
                if getattr(self, "_composer_placeholder_active", False):
                    try:
                        self.text_input.configure(state="normal")
                        self.text_input.delete("1.0", "end")
                        self.text_input.insert("1.0", self._composer_placeholder_text)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                import customtkinter as ctk
                shell = getattr(self, "input_shell", None)
                if shell is not None:
                    parent = shell.master
                    bar = ctk.CTkFrame(parent, fg_color="transparent", height=30)
                    bar.pack(fill="x", padx=16, pady=(0, 5), before=shell)
                    ctk.CTkLabel(
                        bar,
                        text="ATALHOS",
                        text_color="#737C8A",
                        font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
                    ).pack(side="left", padx=(2, 7))

                    def send_quick(text):
                        try:
                            self._composer_placeholder_active = False
                            self.text_input.configure(state="normal")
                            self.text_input.delete("1.0", "end")
                            self.text_input.insert("1.0", text)
                            self.send_message()
                        except Exception:
                            pass

                    for label, cmd in (
                        ("? AJUDA", "ajuda"),
                        ("STATUS", "status do pc"),
                        ("PRINT", "tira um print"),
                        ("VOZ", "reiniciar voz"),
                    ):
                        ctk.CTkButton(
                            bar,
                            text=label,
                            width=58 if label != "? AJUDA" else 72,
                            height=25,
                            corner_radius=9,
                            fg_color="#282C34",
                            hover_color="#343A46",
                            border_width=1,
                            border_color="#394253",
                            text_color="#B9C9E8",
                            font=ctk.CTkFont(family="Tahoma", size=8, weight="bold"),
                            command=lambda c=cmd: send_quick(c),
                        ).pack(side="left", padx=3)
                    ctk.CTkLabel(
                        bar,
                        text="Enter envia  •  Shift+Enter quebra linha",
                        text_color="#5E6673",
                        font=ctk.CTkFont(family="Tahoma", size=8),
                    ).pack(side="right", padx=(6, 2))
                    self._release_114_quick_bar = bar
            except Exception as exc:
                _safe_log(self, "warning", f"Atalhos visuais 1.1.4 não carregados: {exc}")
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
