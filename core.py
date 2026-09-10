"""
JARVIS - Core otimizado para baixa latência.

Compatível com a GUI atual do projeto:
- is_available()
- has_auth_error()
- get_auth_error_message()
- process_message()
- process_message_stream(..., on_chunk=...)
- register_typing_callback()
- start_typing_effect()
- stop_typing()
- get_api_status()

Usa o SDK atual google-genai e o modelo rápido gemini-3.5-flash-lite.
"""

import os
import time
import sys
import re
import unicodedata
import threading
import queue
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv
genai = None
types = None

from jarvis_version import PUBLIC_NAME
from secure_settings import bootstrap_secrets_to_env, load_gemini_api_key


class JarvisCore:
    """Núcleo de IA do JARVIS com foco em baixa latência."""

    FAST_MODEL = "gemini-3.5-flash-lite"
    # Não use timeout curto no HttpOptions do SDK: algumas versões do
    # google-genai podem transformar esse timeout em HTTP 500. O watchdog
    # abaixo limita o tempo do *turno* sem quebrar o transporte/conexão.
    # Compatibilidade: instalações Build 12 antigas usam
    # JARVIS_GEMINI_TIMEOUT_MS. Hoje ele funciona apenas como teto total; o
    # primeiro token possui watchdog próprio bem menor.
    LEGACY_GEMINI_TIMEOUT_MS = max(0, int(os.getenv("JARVIS_GEMINI_TIMEOUT_MS", "0") or 0))
    # 13.12.1: no chat digitado o primeiro token pode chegar depois de 2,6-3,8 s
    # sem significar falha. Mantemos um aviso "soft" cedo, mas só abandonamos
    # o turno no limite "hard". Voz conserva o endpoint agressivo próprio.
    FIRST_TOKEN_SOFT_MS = max(1800, min(int(os.getenv("JARVIS_GEMINI_SOFT_FIRST_TOKEN_MS", "2600")), 5000))
    FIRST_TOKEN_TIMEOUT_MS = max(4200, min(int(os.getenv("JARVIS_GEMINI_FIRST_TOKEN_MS", "5600")), 9000))
    TOTAL_RESPONSE_TIMEOUT_MS = max(4500, min(int(os.getenv("JARVIS_GEMINI_TOTAL_MS", str(LEGACY_GEMINI_TIMEOUT_MS or 9000))), 20000))
    GEMINI_COOLDOWN_S = max(2.0, min(float(os.getenv("JARVIS_GEMINI_COOLDOWN_S", "8.0")), 30.0))
    # 13.11.6: microturnos puramente sociais podem ser resolvidos localmente.
    # Isso evita uma ida ao Gemini para respostas deterministicas de 1 linha.
    INSTANT_LOCAL_ENABLED = os.getenv("JARVIS_INSTANT_LOCAL", "1").strip().lower() in ("1", "true", "on", "yes")
    # 13.12.0: conservative semantic cache. Only stable explanatory phrasings
    # share a key; current/live/personal state never gets a long cache TTL.
    SEMANTIC_CACHE_ENABLED = os.getenv("JARVIS_SEMANTIC_CACHE", "1").strip().lower() in ("1", "true", "on", "yes")

    def __init__(self, logger):
        self.logger = logger
        self.api_key = None
        self.client = None

        self.vision_enabled = False
        self.auth_error_message = None

        self.typing_active = False
        self.typing_callbacks = []

        self._gemini_disabled_until = 0.0
        # Estado remoto por geração. Um watchdog pode abandonar uma chamada sem
        # deixar a próxima pergunta bloqueada por uma thread antiga presa no SDK.
        self._gemini_inflight = threading.Event()  # compatibilidade/diagnóstico
        self._gemini_state_lock = threading.RLock()
        self._gemini_generation = 0
        self._gemini_active_generation = 0
        self._gemini_active_stop = None
        self._gemini_active_client = None
        self._gemini_active_started = 0.0
        self._response_cache = {}
        self._response_cache_lock = threading.Lock()
        self._client_init_lock = threading.RLock()
        # Saúde remota separada de "chave configurada". Diagnóstico não deve
        # declarar o serviço online só porque o Client existe.
        self.last_remote_success_at = None
        self.last_remote_error_at = None
        self.last_remote_error = ""
        self._load_api_key()
        # Build 15: importar/inicializar o SDK remoto nao bloqueia mais o boot.
        # A GUI o preaquece em background; o primeiro turno tambem possui fallback
        # lazy caso o usuario fale antes do prewarm terminar.

    # =========================================================
    # CONFIGURAÇÃO DA API
    # =========================================================

    def _load_api_key(self):
        """Carrega GEMINI_API_KEY priorizando o cofre DPAPI do JARVIS Desktop."""
        try:
            secure_key = bootstrap_secrets_to_env() or load_gemini_api_key()
            if secure_key:
                self.api_key = secure_key.strip().strip("\"'")
                self.logger.info("API Gemini carregada da configuração segura do Windows", "CORE")
                return

            # Compatibilidade com instalações antigas e ambiente de desenvolvimento.
            current_dir = os.environ.get("JARVIS_APP_DIR") or os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(current_dir, ".env")
            if os.path.exists(env_path):
                load_dotenv(env_path, override=False)
            self.api_key = str(os.getenv("GEMINI_API_KEY") or "").strip().strip("\"'") or None
            if self.api_key and len(self.api_key) > 10:
                self.logger.info("API Gemini carregada da configuração de compatibilidade", "CORE")
            else:
                self.api_key = None
                self.logger.warning("API Gemini ainda não foi configurada", "CORE")
        except Exception as e:
            self.logger.error(e, "Erro ao carregar API key", "CORE")
            self.api_key = None

    def reload_api_key(self) -> bool:
        """Recarrega a credencial após o usuário alterá-la na interface."""
        old_client = self.client
        self.client = None
        self.auth_error_message = None
        self.vision_enabled = False
        self._load_api_key()
        if old_client is not None:
            self._close_gemini_client_async(old_client)
        if not self.api_key:
            return False
        try:
            self._configure_client()
            return self.client is not None and not self.has_auth_error()
        except Exception:
            return False

    @staticmethod
    def _load_genai_sdk():
        global genai, types
        if genai is not None and types is not None:
            return genai, types
        from google import genai as _genai
        from google.genai import types as _types
        genai, types = _genai, _types
        return genai, types

    def _ensure_client(self) -> bool:
        if self.client is not None and self.api_key is not None and not self.has_auth_error():
            return True
        if not self.api_key:
            return False
        with self._client_init_lock:
            if self.client is not None and not self.has_auth_error():
                return True
            self._configure_client()
            return self.client is not None and not self.has_auth_error()

    def prewarm(self) -> bool:
        """Preaquece SDK/cliente remoto fora da thread de UI."""
        try:
            return self._ensure_client()
        except Exception:
            return False

    def _configure_client(self):
        """Inicializa o cliente google-genai."""
        if not self.api_key:
            self.auth_error_message = (
                "Não encontrei uma chave válida do Gemini. "
                "Use o botão API para configurar sua chave."
            )
            self.vision_enabled = False
            return

        try:
            # O Client mantém conexões HTTP persistentes. Deixamos o transporte
            # usar seus timeouts normais e controlamos latência do turno fora dele.
            # Isso evita a classe de 500 INTERNAL observada com HttpOptions.timeout
            # em algumas versões do SDK.
            self.client = self._make_gemini_client()

            self.vision_enabled = True
            self.auth_error_message = None

            self.logger.info(
                f"API Gemini configurada com sucesso - "
                f"modelo rápido: {self.FAST_MODEL}",
                "CORE"
            )

        except Exception as e:
            error_text = str(e).lower()

            if any(
                word in error_text
                for word in [
                    "permission",
                    "forbidden",
                    "unauthorized",
                    "invalid",
                    "blocked",
                    "api key"
                ]
            ):
                self.auth_error_message = (
                    "Houve um erro de autenticação com "
                    "o Gemini. Verifique sua chave de API."
                )
            else:
                self.auth_error_message = None

            self.vision_enabled = False

            self.logger.error(
                e,
                "Erro ao configurar API Gemini",
                "CORE"
            )

    def _make_gemini_client(self):
        """Cria um cliente isolado com retries do SDK desativados na prática."""
        self._load_genai_sdk()
        http_options = types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1)
        )
        return genai.Client(api_key=self.api_key, http_options=http_options)

    def _close_gemini_client_async(self, client) -> None:
        """Fecha transporte antigo fora da thread de UI/decisão.

        O SDK atual expõe Client.close(). Fechar o cliente libera conexões HTTP e
        normalmente desbloqueia um stream preso. A thread é daemon para que uma
        implementação específica do transporte nunca congele a interface.
        """
        if client is None:
            return

        def _closer():
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            except Exception as exc:
                try:
                    self.logger.warning(f"Falha ao fechar transporte Gemini antigo: {exc}", "CORE")
                except Exception:
                    pass

        threading.Thread(
            target=_closer,
            name="JARVIS-GEMINI-CLOSE",
            daemon=True,
        ).start()

    def _refresh_gemini_client(self, old_client=None) -> bool:
        """Troca o transporte remoto sem bloquear o próximo turno."""
        if not self.api_key:
            return False
        if old_client is None:
            old_client = self.client
        try:
            fresh = self._make_gemini_client()
            self.client = fresh
            self.vision_enabled = True
            self.auth_error_message = None
            if old_client is not None and old_client is not fresh:
                self._close_gemini_client_async(old_client)
            return True
        except Exception as exc:
            self.logger.error(exc, "Falha ao recriar cliente Gemini", "CORE")
            if old_client is not None:
                self.client = old_client
            return False

    def _begin_gemini_generation(self, stop_event, request_client) -> int:
        """Registra um turno remoto novo e invalida qualquer geração anterior."""
        old_stop = None
        old_client = None
        with self._gemini_state_lock:
            if self._gemini_active_generation:
                old_stop = self._gemini_active_stop
                old_client = self._gemini_active_client
            self._gemini_generation += 1
            generation = self._gemini_generation
            self._gemini_active_generation = generation
            self._gemini_active_stop = stop_event
            self._gemini_active_client = request_client
            self._gemini_active_started = time.monotonic()
            self._gemini_inflight.set()

        if old_stop is not None:
            try:
                old_stop.set()
            except Exception:
                pass
        # Se um novo comando preemptou uma chamada antiga, interrompa o
        # transporte antigo; a nova geração usa cliente fresco quando necessário.
        if old_client is not None and old_client is not request_client:
            self._close_gemini_client_async(old_client)
        return generation

    def _finish_gemini_generation(self, generation: int) -> None:
        """Finaliza somente a geração correspondente; threads antigas não limpam a nova."""
        with self._gemini_state_lock:
            if self._gemini_active_generation != generation:
                return
            self._gemini_active_generation = 0
            self._gemini_active_stop = None
            self._gemini_active_client = None
            self._gemini_active_started = 0.0
            self._gemini_inflight.clear()

    def _abandon_gemini_generation(self, generation: int, request_client, reason: str) -> None:
        """Abandona de verdade um stream preso e prepara conexão limpa para o próximo turno."""
        should_refresh = False
        with self._gemini_state_lock:
            if self._gemini_active_generation == generation:
                self._gemini_active_generation = 0
                self._gemini_active_stop = None
                self._gemini_active_client = None
                self._gemini_active_started = 0.0
                self._gemini_inflight.clear()
                should_refresh = True
        if should_refresh:
            self.logger.warning(f"Gemini remoto abandonado ({reason}); transporte sera renovado.", "CORE")
            # Cria primeiro o cliente novo e fecha o antigo em background. Assim
            # a próxima pergunta não herda a conexão presa.
            self._refresh_gemini_client(old_client=request_client)

    def _preempt_active_gemini(self) -> None:
        """Um turno novo sempre pode substituir uma resposta remota antiga."""
        with self._gemini_state_lock:
            active = self._gemini_active_generation
            stop = self._gemini_active_stop
            client = self._gemini_active_client
        if not active:
            return
        try:
            if stop is not None:
                stop.set()
        except Exception:
            pass
        self._abandon_gemini_generation(active, client, "novo turno")

    def cancel_active_response(self, reason: str = "cancelado pela interface") -> bool:
        """Cancela o stream remoto ativo sem expor detalhes do transporte à GUI."""
        with self._gemini_state_lock:
            active = self._gemini_active_generation
            stop = self._gemini_active_stop
            client = self._gemini_active_client
        if not active:
            return False
        try:
            if stop is not None:
                stop.set()
        except Exception:
            pass
        self._abandon_gemini_generation(active, client, str(reason or "cancelado"))
        return True

    # =========================================================
    # STATUS
    # =========================================================

    def has_auth_error(self) -> bool:
        return self.auth_error_message is not None

    def get_auth_error_message(self) -> Optional[str]:
        return self.auth_error_message

    def is_available(self) -> bool:
        return (
            self.client is not None
            and self.api_key is not None
            and self.vision_enabled
            and not self.has_auth_error()
        )

    # =========================================================
    # CONTEXTO
    # =========================================================

    def _prepare_context(
        self,
        message: str,
        conversation_history: List[Dict],
        memories: List[str],
        system_commands_info: str = "",
        speaker_name: str = "",
    ) -> str:
        """
        Monta um prompt pequeno para reduzir latência.
        Mantém somente parte do histórico recente.
        """
        history_lines = []

        if conversation_history:
            # 13.12.0: short standalone questions use less prompt; pronouns and
            # follow-ups keep a larger window so "e a CPU?" / "fecha ele" do
            # not lose the referent. Full history remains in SQLite.
            message_key = unicodedata.normalize("NFKD", str(message or "").lower())
            message_key = "".join(ch for ch in message_key if not unicodedata.combining(ch))
            followup = bool(
                len(message_key.split()) <= 18
                and (
                    re.search(r"\b(?:ele|ela|eles|elas|isso|isto|esse|essa|este|esta|aquele|aquela|tambem|depois|agora|nisso|nele|nela|mesmo|mesma|primeiro|segundo|terceiro|anterior|proximo)\b", message_key)
                    or re.match(r"^(?:e|mas|entao|ai|certo|beleza|sim|nao|pode ser|isso mesmo|exato|por que|porque|como assim|e se|e quando|e onde|sobre isso|continua|continue|explica melhor|explique melhor)\b", message_key)
                )
            )
            history_limit = 10 if followup else 6
            for msg in conversation_history[-history_limit:]:
                text = (
                    msg.get("message")
                    or msg.get("text")
                    or msg.get("content")
                    or ""
                )

                if not text:
                    continue
                text = " ".join(str(text).split())
                if len(text) > 480:
                    text = text[:480].rstrip() + "..."

                if msg.get("is_user"):
                    history_lines.append(f"Usuário: {text}")
                elif msg.get("is_jarvis"):
                    history_lines.append(f"{PUBLIC_NAME}: {text}")

        history = "\n".join(history_lines)

        memory_lines = []
        if memories:
            # Trechos antigos relevantes recuperados do banco persistente.
            for memory in memories[-2:]:
                memory_lines.append(f"- {memory}")

        memory_context = "\n".join(memory_lines)

        detail_keywords = [
            "mais detalhes",
            "explique melhor",
            "detalhe",
            "continue",
            "aprofund",
            "análise completa",
            "analise profundamente"
        ]

        wants_detail = any(
            keyword in message.lower()
            for keyword in detail_keywords
        )

        if wants_detail:
            style = (
                "Responda com detalhes suficientes para resolver a dúvida, sem repetição desnecessária."
            )
        else:
            style = (
                "Seja rápido, claro e objetivo. Para perguntas comuns, prefira 1 a 3 parágrafos curtos. "
                "Evite começar toda resposta com 'Claro', 'Certamente' ou 'Com certeza'. "
                "Se a resposta curta bastar, responda como conversa, não como relatório."
            )

        voice_style = (
            "PERSONALIDADE E FALA: aja como um mordomo tecnológico elegante, discreto, seguro e competente. "
            "Use 'senhor' naturalmente, sobretudo em saudações e confirmações, sem repetir o vocativo em toda oração. "
            "Use frases fluidas e pontuação que soe natural em voz alta. Não use reticências para dramatizar pausas. "
            "Não termine automaticamente com 'se precisar de mais alguma coisa, pode falar', 'estou à disposição', "
            "'é só chamar', 'como posso ajudar' ou equivalentes. Não force humor, teatralidade ou bordões. "
            "Não seja hostil, provocativo ou paternalista. Em ordens curtas, confirme de forma curta."
        )
        understanding_style = (
            "ENTENDIMENTO: trate a mensagem como fala humana, que pode conter erro de digitação, palavra cortada ou transcrição fonética. "
            "Quando o contexto tornar a palavra pretendida óbvia, entenda a intenção correta sem corrigir o usuário em voz alta nem discutir o erro. "
            "Use o histórico recente para resolver pronomes, elipses e continuações como 'e ele?', 'faz o mesmo', 'e depois?'. "
            "Preserve nomes próprios, marcas, jogos, aplicativos e termos em inglês. "
            "Se duas interpretações plausíveis mudarem materialmente o sentido, faça UMA pergunta curta de esclarecimento em vez de adivinhar. "
            "Não repita a pergunta apenas para confirmar que ouviu; responda ao objetivo real do usuário."
        )

        sections = [
            f"Você é {PUBLIC_NAME}, um assistente pessoal inteligente para Windows.",
            style,
            voice_style,
            understanding_style,
            (
                "Responda em português do Brasil, salvo se o usuário "
                "pedir outro idioma."
            ),
        ]

        session_name = " ".join(str(speaker_name or "").split()).strip()
        if session_name:
            sections.append(
                f"IDENTIDADE DE TRATAMENTO DESTA SESSÃO: o usuário informou explicitamente que deve ser chamado de {session_name}. "
                f"Quando usar vocativo, prefira 'senhor {session_name}'. Não invente outro nome e não diga que reconheceu a voz."
            )
        else:
            sections.append(
                "TRATAMENTO: quando um vocativo combinar com a frase, use 'senhor'. Não invente um nome para o usuário."
            )

        sections.extend([
            (
                f"VERDADE SOBRE O {PUBLIC_NAME}: ele possui ferramentas locais reais para abrir aplicativos, "
                "controlar mídia e janelas, pesquisar no navegador, lidar com arquivos e observar a tela. "
                "Se perguntarem sobre capacidades, não diga que ele é incapaz de mexer no computador. "
                f"O wake word principal é '{PUBLIC_NAME.title()}' sozinho, além de 'Ei {PUBLIC_NAME.title()}' e 'Oi {PUBLIC_NAME.title()}'. "
                "Não diga que trocar de idioma 'buga' o sistema."
            ),
            (
                "REGRA CRÍTICA DE AÇÕES LOCAIS: você é a parte conversacional. "
                "Nunca afirme que abriu, fechou, tocou, pausou, alterou volume, "
                "moveu arquivo ou executou ação no Windows sem confirmação local. "
                "Se um pedido imperativo de ação local chegou até você, ele não foi "
                "reconhecido pelo roteador. Responda em UMA frase curta, por exemplo: "
                "'Não consegui executar esse comando local.' Não fale em 'ferramenta', "
                "não diga que está processando, não invente sucesso e não dê tutorial "
                "manual do Windows a menos que o usuário peça ajuda manual."
            ),
        ])

        if history:
            sections.append(
                "Contexto recente da conversa:\n" + history
            )

        if memory_context:
            sections.append(
                "Memória persistente relevante recuperada de conversas anteriores (pode estar desatualizada; "
                "o contexto desta conversa e a mensagem atual sempre têm prioridade):\n"
                + memory_context
            )

        # Contexto operacional compacto pode ser injetado sem mandar listas
        # gigantes de comandos. Ele contém apenas metadados locais (app/site/
        # monitor/player/topico), nunca tela, audio ou teclas.
        if system_commands_info:
            info = str(system_commands_info or "")
            if info.startswith("CTX:"):
                live = " ".join(info[4:].split())[:900]
                if live:
                    sections.append(
                        "CONTEXTO OPERACIONAL ATUAL (pode expirar; use apenas para referências como ele/isso/o outro):\n" + live
                    )
            else:
                sections.append(
                    f"O {PUBLIC_NAME} possui ferramentas locais para executar "
                    "comandos no Windows quando a interface detectar explicitamente uma ação."
                )

        sections.append(f"Mensagem atual do usuário:\n{message}")

        return "\n\n".join(sections)

    # =========================================================
    # CONFIGURAÇÃO DE GERAÇÃO
    # =========================================================

    def _generation_config(self, message: str):
        """
        Configuração rápida para conversa normal.

        gemini-3.5-flash-lite + thinking minimal deu baixa latência
        nos testes realizados no ambiente do usuário.
        """
        detail_keywords = [
            "mais detalhes",
            "explique melhor",
            "detalhe",
            "continue",
            "aprofund",
            "analise profundamente",
            "análise completa",
            "resposta longa",
            "resposta mais longa",
            "resposta maior",
            "mais longa",
            "mais completo",
            "mais completa",
            "explique bastante",
            "fale mais",
            "um pouco mais longa"
        ]

        wants_detail = any(
            keyword in message.lower()
            for keyword in detail_keywords
        )

        # Respostas normais terminam mais cedo e entram no streaming/TTS com
        # menos cauda. Pedidos explicitamente detalhados continuam amplos.
        # 13.11.6: conversa comum raramente precisa de 384 tokens. Um teto menor
        # reduz cauda e deixa o TTS terminar mais cedo sem encurtar pedidos detalhados.
        max_tokens = 4096 if wants_detail else 320
        self._load_genai_sdk()

        return types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level="minimal"
            ),
            max_output_tokens=max_tokens
        )

    # =========================================================
    # PROCESSAMENTO SEM STREAMING
    # =========================================================

    def process_message(
        self,
        message: str,
        conversation_history: List[Dict],
        memories: List[str],
        system_commands_info: str = "",
        speaker_name: str = "",
        source: str = "text",
    ) -> str:
        """
        Compatibilidade com partes antigas do projeto.

        Internamente usa streaming e junta os chunks.
        """
        chunks = []

        result = self.process_message_stream(
            message,
            conversation_history,
            memories,
            system_commands_info,
            on_chunk=chunks.append,
            speaker_name=speaker_name,
            source=source,
        )

        if chunks:
            return self._clean_response("".join(chunks))

        return result

    # =========================================================
    # PROCESSAMENTO COM STREAMING
    # =========================================================

    def _instant_conversation_response(
        self, message: str, speaker_name: str = "", conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """Microturnos locais apenas quando a frase realmente fecha o assunto.

        Build 16: respostas curtas como "isso", "pode ser" e "sim" podem ser
        continuação de uma pergunta anterior. Nesses casos o histórico precisa
        chegar ao modelo; uma resposta local genérica destruiria o contexto.
        """
        if not self.INSTANT_LOCAL_ENABLED:
            return ""
        raw = " ".join(str(message or "").split()).strip()
        if not raw or len(raw) > 72:
            return ""
        key = unicodedata.normalize("NFKD", raw.lower())
        key = "".join(ch for ch in key if not unicodedata.combining(ch))
        key = re.sub(r"[^a-z0-9 ]+", " ", key)
        key = re.sub(r"\s+", " ", key).strip()

        # Se o ultimo turno do assistente pediu uma escolha/confirmação
        # conversacional, qualquer resposta curta deve continuar com histórico.
        # Confirmações de ações locais são resolvidas antes, na GUI.
        last_assistant = ""
        for item in reversed(list(conversation_history or [])[-6:]):
            if item.get("is_jarvis"):
                last_assistant = " ".join(str(item.get("message") or item.get("content") or "").split())
                break
        if last_assistant and (
            last_assistant.rstrip().endswith("?")
            or re.search(
                r"\b(?:quer que eu|voce quer|você quer|prefere|posso|devo|qual|quais|confirma|pode confirmar)\b",
                last_assistant.lower(),
            )
        ) and key in {
            "sim", "nao", "não", "isso", "isso mesmo", "exato", "pode ser",
            "sim pode ser", "certo", "ok", "okay", "beleza", "blz",
        }:
            return ""

        # Nao intercepte enunciados que parecem conter uma acao/alvo.
        if re.search(
            r"\b(?:abre|abra|abrir|fecha|feche|fechar|minimiza|maximiza|move|mova|"
            r"pesquisa|pesquise|procura|busca|clica|clique|pausa|pause|continua|"
            r"toque|toca|cria|crie|faz|faca|arquivo|pasta|app|aplicativo|site|monitor|tela)\b",
            key,
        ):
            return ""
        vocative = f", senhor {speaker_name.strip()}" if speaker_name.strip() else ", senhor"
        if key in {
            "oi", "ola", "opa", "e ai", "fala", "oi jarvis", "ola jarvis", "opa jarvis",
            "e ai jarvis", "fala jarvis", "e ai mano", "eai mano", "fala mano", "opa mano",
            "salve", "salve jarvis", "bom dia", "boa tarde", "boa noite",
        }:
            if key == "bom dia":
                return f"Bom dia{vocative}."
            if key == "boa tarde":
                return f"Boa tarde{vocative}."
            if key == "boa noite":
                return f"Boa noite{vocative}."
            return f"Pois não{vocative}."
        if key in {"tudo bem", "tudo bom", "como voce ta", "como voce esta", "ta tudo bem", "esta tudo bem"}:
            return f"Tudo em ordem{vocative}."
        if key in {
            "valeu", "obrigado", "obrigada", "brigado", "brigada", "show", "perfeito",
            "excelente", "top", "boa", "fechou", "beleza", "deu certo", "agora foi",
            "massa", "arretado", "show de bola", "pronto deu certo",
        }:
            return f"Perfeito{vocative}."
        if key in {
            "entendi", "saquei", "certo", "ok", "okay", "blz", "ta certo", "esta certo",
        }:
            return f"Certo{vocative}."
        if key in {"qual seu nome", "qual e seu nome", "quem e voce", "quem e o jarvis"}:
            return f"Sou {PUBLIC_NAME}, seu assistente pessoal{vocative}."
        return ""

    def _local_degraded_response(self, message: str, source: str = "text") -> str:
        """Resposta local curta quando a IA remota está oscilando.

        Nunca mostra erro técnico/timeout ao usuário. O objetivo é manter o
        JARVIS responsivo e útil enquanto o circuito externo se recupera.
        """
        raw = " ".join(str(message or "").split()).strip()
        key = re.sub(r"[^a-z0-9áàâãéêíóôõúç ]+", " ", raw.lower())
        key = re.sub(r"\s+", " ", key).strip()
        if not key:
            return "Pode falar."
        if re.search(r"\b(?:tudo bom|tudo bem|como voce esta|como você está|e ai|e aí)\b", key):
            return "Tudo certo por aqui. O que manda?"
        if re.search(r"\b(?:como que faz|como eu faco|como eu faço)\s*$", key):
            return "Me diz o que você quer fazer e eu te explico direto."
        if "memoria ram" in key or re.search(r"\bo que e ram\b", key):
            return "RAM é a memória rápida que o PC usa enquanto programas estão abertos. Mais RAM ajuda a manter mais coisas ativas sem recorrer ao disco."
        if re.search(r"\bo que e (?:cpu|processador)\b", key):
            return "A CPU é o processador principal: executa instruções, lógica e boa parte das tarefas gerais do computador."
        if re.search(r"\bo que e gpu\b", key):
            return "A GPU é especializada em processamento paralelo, principalmente gráficos e cargas de IA. Ela acelera tarefas compatíveis, mas não substitui rede, STT ou o modelo remoto."
        if re.search(r"\bo que e (?:ssd|nvme)\b", key):
            return "SSD é o armazenamento rápido do PC. NVMe é um tipo de SSD que usa PCIe e costuma ter latência e taxa de transferência maiores."
        if re.search(r"\b(?:ping|latencia da internet|latência da internet)\b", key):
            return "Velocidade em megabits e latência são coisas diferentes. Para voz e IA, ping, rota até o servidor e tempo do serviço pesam mais que a banda máxima."
        if re.search(r"\b(?:como funciona|como que funciona|o que é|o que e|me explica|explique)\s+(?:o|a|um|uma|do|da)?\s*$", key):
            return "Pode terminar a pergunta."
        if re.search(r"\b(?:funcionou|agora foi|deu certo|resolveu|perfeito|excelente)\b", key):
            return "Perfeito."
        # Texto digitado nao depende de STT/confianca fonetica. Se o modelo
        # remoto estiver lento, nunca culpe a interpretacao da mensagem.
        typed_input = str(source or "text").lower() == "text"

        knowledge_like = bool(re.match(
            r"^(?:como|por que|porque|qual|quais|quem|quando|onde|o que|oque|"
            r"me explica|me explique|explique|explica|fale mais sobre|fala mais sobre|"
            r"me fale sobre|me fala sobre|o que voce sabe|oque voce sabe|"
            r"quero saber|queria saber|quero aprender|me conte sobre|conta mais sobre)\b",
            key,
        ))
        if raw.endswith("?") or knowledge_like:
            if typed_input:
                return "Entendi sua pergunta, mas não consegui concluir a resposta neste turno. Pode enviar novamente."
            return "A resposta da IA não chegou neste turno. Tente a mesma pergunta novamente."
        if re.match(
            r"^(?:abre|abra|fecha|feche|minimiza|maximiza|move|mova|pesquisa|procura|busca|"
            r"entra|entre|play|plei|pause|pausa|continua|toque|toca|faz|faca)\b",
            key,
        ):
            return "Não reconheci esse comando com segurança. Reformule dizendo a ação e o alvo."
        if typed_input:
            return "Entendi a mensagem, mas não consegui concluir a resposta neste turno. Pode mandar de novo."
        return "Não interpretei essa frase com segurança. Pode reformular?"

    @staticmethod
    def _cache_normalize(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9 ]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _semantic_cache_topic(cls, message: str) -> str:
        """Return a shared key only for stable definition/explanation queries."""
        key = cls._cache_normalize(message)
        patterns = (
            r"^(?:o que e|oque e|o que significa|qual o significado de)\s+(.+)$",
            r"^(?:me explica|me explique|explique|explica)\s+(?:o que e\s+)?(.+)$",
            r"^(?:como funciona|como que funciona)\s+(.+)$",
        )
        for index, pattern in enumerate(patterns):
            match = re.match(pattern, key)
            if match:
                topic = re.sub(r"^(?:o|a|os|as|um|uma)\s+", "", match.group(1)).strip()
                context_dependent = bool(
                    re.fullmatch(
                        r"(?:isso|isto|aquilo|ele|ela|eles|elas|esse|essa|este|esta|aquele|aquela|"
                        r"isso ai|isso aí|essa parte|esse ponto|o anterior|a anterior|o primeiro|o segundo|"
                        r"melhor|mais|de novo|novamente)",
                        topic,
                    )
                )
                if 2 <= len(topic) <= 96 and len(topic.split()) <= 12 and not context_dependent:
                    family = "define" if index < 2 else "howworks"
                    return f"{family}:{topic}"
        return ""

    @classmethod
    def _cache_key(cls, message: str, speaker_name: str = "") -> str:
        key = cls._cache_normalize(message)
        who = cls._cache_normalize(speaker_name)
        semantic = cls._semantic_cache_topic(message)
        if semantic:
            key = semantic
        return f"{who}::{key}" if who else f"anon::{key}"

    @classmethod
    def _cache_ttl_for(cls, message: str) -> float:
        key = cls._cache_normalize(message)
        # Never cache volatile/current-state questions here. Local commands have
        # their own fresh data path; this protects conversational fall-through.
        if re.search(
            r"\b(?:agora|hoje|ontem|amanha|hora|horas|data|tempo|clima|noticia|noticias|"
            r"cotacao|preco|quanto esta|uso da cpu|uso de cpu|ram usando|memoria usando|temperatura|"
            r"janela ativa|processo|processos|internet|ping|status)\b", key,
        ):
            return 0.0
        if cls._semantic_cache_topic(message):
            return 1800.0
        # Build 16: nunca reutiliza uma resposta conversacional apenas porque o
        # texto se repetiu. Frases iguais podem pertencer a contextos diferentes.
        return 0.0

    def _cache_get(self, message: str, speaker_name: str = "") -> str:
        if not self.SEMANTIC_CACHE_ENABLED:
            return ""
        ttl = self._cache_ttl_for(message)
        if ttl <= 0:
            return ""
        key = self._cache_key(message, speaker_name)
        if not key:
            return ""
        with self._response_cache_lock:
            item = self._response_cache.get(key)
            if not item:
                return ""
            created, response = item
            if time.monotonic() - float(created) > ttl:
                self._response_cache.pop(key, None)
                return ""
            return str(response or "")

    def _cache_put(self, message: str, response: str, speaker_name: str = "") -> None:
        if not self.SEMANTIC_CACHE_ENABLED or self._cache_ttl_for(message) <= 0:
            return
        key = self._cache_key(message, speaker_name)
        if not key or not response:
            return
        with self._response_cache_lock:
            self._response_cache[key] = (time.monotonic(), str(response))
            if len(self._response_cache) > 160:
                oldest = sorted(self._response_cache.items(), key=lambda kv: kv[1][0])[:40]
                for old_key, _ in oldest:
                    self._response_cache.pop(old_key, None)

    def _stream_worker(self, request_client, generation: int, prompt, config, out_queue: queue.Queue, stop_event: threading.Event):
        """Executa o stream fora da thread de decisão para permitir watchdog real."""
        try:
            stream = request_client.models.generate_content_stream(
                model=self.FAST_MODEL, contents=prompt, config=config
            )
            for chunk in stream:
                if stop_event.is_set():
                    return
                text = getattr(chunk, "text", None)
                if text:
                    out_queue.put(("chunk", text))
            out_queue.put(("done", None))
        except Exception as exc:
            out_queue.put(("error", exc))
        finally:
            self._finish_gemini_generation(generation)

    def process_message_stream(
        self,
        message: str,
        conversation_history: List[Dict],
        memories: List[str],
        system_commands_info: str = "",
        on_chunk=None,
        _remote_retry: bool = False,
        speaker_name: str = "",
        source: str = "text",
    ) -> str:
        """Streaming com watchdog de primeiro token e circuit breaker.

        O transporte do SDK fica sem timeout curto; esta camada decide quando
        abandonar visualmente um turno, sem congelar a GUI nem expor mensagens
        técnicas como "Gemini demorou".
        """
        instant = self._instant_conversation_response(
            message, speaker_name=speaker_name, conversation_history=conversation_history
        )
        if instant:
            self.logger.system("Microturno conversacional resolvido localmente.", "CORE")
            if callable(on_chunk):
                try:
                    on_chunk(instant)
                except Exception:
                    pass
            return instant

        cached = self._cache_get(message, speaker_name=speaker_name)
        if cached:
            self.logger.system("Resposta semântica reutilizada do cache local.", "CORE")
            if callable(on_chunk):
                try:
                    on_chunk(cached)
                except Exception:
                    pass
            return cached

        if self.client is None and self.api_key is not None:
            self._ensure_client()
        if not self.is_available():
            return self._local_degraded_response(message, source=source)

        now = time.monotonic()
        if now < float(self._gemini_disabled_until or 0.0):
            return self._local_degraded_response(message, source=source)

        # Um comando/pergunta novo não fica refém de uma thread remota antiga.
        # Se ainda houver uma geração ativa, ela é invalidada e o transporte é
        # renovado antes de iniciar o novo turno.
        self._preempt_active_gemini()

        request_started = time.monotonic()
        self.logger.system("Enviando requisição rápida para API Gemini...", "CORE")
        prompt = self._prepare_context(
            message, conversation_history, memories, system_commands_info, speaker_name=speaker_name
        )
        config = self._generation_config(message)

        events: queue.Queue = queue.Queue()
        stop_event = threading.Event()
        request_client = self.client
        generation = self._begin_gemini_generation(stop_event, request_client)
        worker = threading.Thread(
            target=self._stream_worker,
            args=(request_client, generation, prompt, config, events, stop_event),
            name=f"JARVIS-GEMINI-STREAM-{generation}",
            daemon=True,
        )
        worker.start()

        full_response = []
        first_chunk_received = False
        raw_message = str(message or "").strip()
        short_turn = len(raw_message.split()) <= 10 and len(raw_message) <= 90
        normalized_prompt = unicodedata.normalize("NFKD", raw_message.lower())
        normalized_prompt = "".join(ch for ch in normalized_prompt if not unicodedata.combining(ch))
        normalized_prompt = re.sub(r"[^a-z0-9 ?]+", " ", normalized_prompt)
        normalized_prompt = re.sub(r"\s+", " ", normalized_prompt).strip()
        question_like = bool(
            raw_message.endswith("?")
            or re.match(
                r"^(?:como|por que|porque|qual|quais|quem|quando|onde|o que|oque|me explica|me explique|"
                r"explique|explica|queria saber|quero saber|quero aprender|fale mais sobre|fala mais sobre|"
                r"me fale sobre|me fala sobre|o que voce sabe|oque voce sabe|me conte sobre|conta mais sobre)\b",
                normalized_prompt,
            )
        )

        input_source = str(source or "text").strip().lower()
        if input_source == "text":
            # 13.12.1: digitacao nao deve ser punida por um watchdog criado
            # para voz. O soft timeout apenas registra lentidao; nao cancela.
            first_timeout_ms = self.FIRST_TOKEN_TIMEOUT_MS
            if _remote_retry:
                first_timeout_ms = min(first_timeout_ms, 4200)
            soft_timeout_ms = min(self.FIRST_TOKEN_SOFT_MS, max(1800, first_timeout_ms - 1000))
        else:
            # Mantem a politica responsiva da voz da 13.12.0.
            if question_like:
                first_timeout_ms = max(3800, min(self.FIRST_TOKEN_TIMEOUT_MS, 4600))
                if _remote_retry:
                    first_timeout_ms = min(first_timeout_ms, 3000)
            elif short_turn:
                first_timeout_ms = min(self.FIRST_TOKEN_TIMEOUT_MS, 2600)
            else:
                first_timeout_ms = min(self.FIRST_TOKEN_TIMEOUT_MS, 4200)
            soft_timeout_ms = 0

        first_deadline = request_started + first_timeout_ms / 1000.0
        soft_deadline = request_started + soft_timeout_ms / 1000.0 if soft_timeout_ms else None
        soft_logged = False
        total_deadline = request_started + self.TOTAL_RESPONSE_TIMEOUT_MS / 1000.0
        error = None

        while True:
            now = time.monotonic()
            if (
                not first_chunk_received
                and soft_deadline is not None
                and not soft_logged
                and now >= soft_deadline
            ):
                soft_logged = True
                self.logger.warning(
                    f"Gemini ainda sem primeiro token em {soft_timeout_ms} ms; mantendo o turno aberto ate {first_timeout_ms} ms.",
                    "CORE",
                )
            deadline = total_deadline if first_chunk_received else first_deadline
            remaining = deadline - now
            if remaining <= 0:
                stop_event.set()
                if first_chunk_received and full_response:
                    self.logger.warning("Gemini excedeu a cauda máxima; usando resposta parcial já recebida.", "CORE")
                    self._abandon_gemini_generation(generation, request_client, "cauda excedida")
                    break
                self.logger.warning(
                    f"Gemini sem primeiro token em {first_timeout_ms} ms; conexao sera reciclada.",
                    "CORE",
                )
                # Não aplique cooldown por um simples stream preso: isso foi o que
                # fazia TODAS as perguntas seguintes caírem no fallback local.
                self._abandon_gemini_generation(generation, request_client, "sem primeiro token")
                # Pergunta completa: tente UMA vez com conexão recém-criada. Isso
                # recupera streams presos sem obrigar o usuário a repetir a pergunta.
                if input_source != "text" and question_like and not _remote_retry and len(raw_message.split()) >= 4:
                    self.logger.warning("Repetindo pergunta uma vez com transporte Gemini novo.", "CORE")
                    return self.process_message_stream(
                        message,
                        conversation_history,
                        memories,
                        system_commands_info,
                        on_chunk=on_chunk,
                        _remote_retry=True,
                        speaker_name=speaker_name,
                        source=source,
                    )
                return self._local_degraded_response(message, source=source)
            try:
                kind, payload = events.get(timeout=min(0.20, max(0.01, remaining)))
            except queue.Empty:
                continue

            if kind == "chunk":
                text = str(payload or "")
                if not text:
                    continue
                if not first_chunk_received:
                    first_chunk_received = True
                    self.last_first_chunk_ms = int(round((time.monotonic() - request_started) * 1000))
                    self.logger.system(
                        f"Primeiro trecho recebido do Gemini em {self.last_first_chunk_ms} ms.", "CORE"
                    )
                full_response.append(text)
                if callable(on_chunk):
                    try:
                        on_chunk(text)
                    except Exception as callback_error:
                        self.logger.error(callback_error, "Erro no callback de streaming", "CORE")
            elif kind == "done":
                break
            elif kind == "error":
                error = payload
                break

        if error is not None:
            error_text = str(error or "")
            # Log útil para diagnóstico, sem transformar a exceção em fala do JARVIS.
            self.last_remote_error = f"{type(error).__name__}: {error_text[:240]}"
            self.last_remote_error_at = datetime.now().isoformat(timespec="seconds")
            self.logger.error(error, f"Falha Gemini ({type(error).__name__}): {error_text[:240]}", "CORE")
            self._abandon_gemini_generation(generation, request_client, "erro de transporte")
            transient_busy = bool(
                re.search(r"(?:\b503\b|UNAVAILABLE|high demand|temporar(?:y|ily)|overloaded)", error_text, re.I)
            )
            if transient_busy and not _remote_retry and not full_response:
                # Picos 503 do Gemini são transitórios. Uma única nova conexão
                # evita obrigar o usuário a repetir a pergunta sem criar loop.
                self.logger.warning("Gemini temporariamente ocupado; tentando novamente uma vez.", "CORE")
                time.sleep(0.45)
                return self.process_message_stream(
                    message, conversation_history, memories, system_commands_info,
                    on_chunk=on_chunk, _remote_retry=True, speaker_name=speaker_name, source=source,
                )
            # Cooldown curto apenas para falha explícita; uma chamada seguinte
            # ainda pode usar o cliente renovado quase imediatamente.
            self._gemini_disabled_until = time.monotonic() + min(self.GEMINI_COOLDOWN_S, 1.2)
            if full_response:
                response_text = "".join(full_response).strip()
            else:
                return self._local_degraded_response(message, source=source)
        else:
            self._finish_gemini_generation(generation)
            response_text = "".join(full_response).strip()

        if not response_text:
            return self._local_degraded_response(message, source=source)

        cleaned = self._clean_response(response_text)
        self.last_total_response_ms = int(round((time.monotonic() - request_started) * 1000))
        self.last_remote_success_at = datetime.now().isoformat(timespec="seconds")
        self.last_remote_error = ""
        self.logger.system(
            f"Resposta concluída: {len(cleaned)} caracteres em {self.last_total_response_ms} ms", "CORE"
        )
        self._cache_put(message, cleaned, speaker_name=speaker_name)
        self._save_to_memory(message, cleaned)
        return cleaned

    # =========================================================
    # LIMPEZA DE RESPOSTA
    # =========================================================

    def _clean_response(self, response: str) -> str:
        """
        Faz limpeza leve.

        Não destrói quebras de linha para a interface continuar
        mostrando parágrafos corretamente.
        """
        if not response:
            return ""

        try:
            cleaned = response

            # Remove markdown mais agressivo sem achatar parágrafos
            cleaned = re.sub(
                r"^#{1,6}\s+",
                "",
                cleaned,
                flags=re.MULTILINE
            )

            cleaned = cleaned.replace("**", "")
            cleaned = cleaned.replace("`", "")

            # Remove espaços excessivos dentro das linhas
            cleaned = re.sub(r"[ \t]+", " ", cleaned)

            # Evita mais de duas linhas vazias seguidas
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

            return cleaned.strip()

        except Exception as e:
            self.logger.error(
                e,
                "Erro ao limpar resposta",
                "CORE"
            )
            return response

    def _extract_response_text(self, response) -> str:
        """Mantido por compatibilidade."""
        try:
            return response.text or ""
        except Exception:
            return str(response)

    # =========================================================
    # MEMÓRIA
    # =========================================================

    def _save_to_memory(
        self,
        user_message: str,
        jarvis_response: str
    ):
        """Por enquanto registra a interação no log."""
        try:
            self.logger.info(
                "Memória: "
                f"User='{user_message[:50]}...', "
                f"{PUBLIC_NAME}='{jarvis_response[:50]}...'",
                "CORE"
            )
        except Exception as e:
            self.logger.error(
                e,
                "Erro ao registrar memória",
                "CORE"
            )

    # =========================================================
    # EFEITO DE DIGITAÇÃO - COMPATIBILIDADE
    # =========================================================

    def register_typing_callback(self, callback):
        self.typing_callbacks.append(callback)

    def start_typing_effect(self, message: str, callback):
        """
        Mantido para compatibilidade com partes antigas da GUI.
        O streaming real já substitui esse efeito em respostas Gemini.
        """
        if not message or not isinstance(message, str):
            callback("❌ Mensagem inválida para exibição")
            return

        self.typing_active = True

        def typing_thread():
            try:
                displayed_text = ""

                for i, char in enumerate(message):
                    if not self.typing_active:
                        break

                    displayed_text += char

                    if callable(callback):
                        callback(
                            displayed_text + "█",
                            i == len(message) - 1
                        )

                    import time
                    time.sleep(0.01)

                if self.typing_active and callable(callback):
                    callback(displayed_text, True)

            except Exception as e:
                self.logger.error(
                    e,
                    "Erro no efeito de digitação",
                    "CORE"
                )
            finally:
                self.typing_active = False

        threading.Thread(
            target=typing_thread,
            daemon=True
        ).start()

    def stop_typing(self):
        self.typing_active = False

    # =========================================================
    # STATUS DA API
    # =========================================================

    def get_api_status(self) -> Dict[str, object]:
        return {
            "available": self.is_available(),
            "key_configured": self.api_key is not None,
            "model": self.FAST_MODEL if self.is_available() else None,
            "last_success": self.last_remote_success_at,
            "last_error_at": self.last_remote_error_at,
            "last_error": self.last_remote_error,
            "cooldown_active": time.monotonic() < float(self._gemini_disabled_until or 0.0),
            "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
