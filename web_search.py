"""JARVIS - pesquisa web aterrada no Gemini com fallback de compatibilidade.

Ordem:
1. Interactions API + google_search (SDK atual), quando disponível.
2. generate_content + types.GoogleSearch (compatibilidade).
3. Modelo sem web apenas se a busca realmente falhar em todos os caminhos.

Nunca expõe chave ou traceback ao usuário.
"""
from __future__ import annotations

import os
import re
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from dotenv import load_dotenv
from secure_settings import bootstrap_secrets_to_env
try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None


class WebSearch:
    # O Gemini rejeita deadlines manuais menores que 10 s. O Build 12 usava
    # 9000 ms e por isso a busca falhava com INVALID_ARGUMENT antes de pesquisar.
    TIMEOUT_MS = max(10500, min(int(os.getenv("JARVIS_WEB_TIMEOUT_MS", "12000")), 45000))
    SEARCH_MODELS = tuple(
        x.strip() for x in os.getenv(
            "JARVIS_WEB_MODELS", "gemini-2.5-flash"
        ).split(",") if x.strip()
    )
    FALLBACK_MODEL = os.getenv("JARVIS_WEB_FALLBACK_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
    HTTP_SEARCH_TIMEOUT_S = max(3.0, min(float(os.getenv("JARVIS_WEB_HTTP_TIMEOUT_S", "6.0")), 15.0))
    HTTP_USER_AGENT = os.getenv(
        "JARVIS_WEB_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    )

    def __init__(self, logger=None):
        self.logger = logger
        self.api_key = None
        self.client = None
        self.last_mode = ""
        self.last_sources = []
        self._load_api_key()
        self._configure_client()

    def _log(self, level: str, message: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "WEB")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    def _load_api_key(self):
        try:
            secure_key = bootstrap_secrets_to_env()
            if secure_key:
                self.api_key = secure_key
            else:
                env_path = os.path.join(os.getcwd(), ".env")
                load_dotenv(env_path if os.path.exists(env_path) else None, override=False)
                self.api_key = str(os.getenv("GEMINI_API_KEY") or "").strip().strip("\"'") or None
            self._log("info" if self.api_key else "warning", "WebSearch: API key carregada" if self.api_key else "WebSearch: GEMINI_API_KEY não configurada")
        except Exception as exc:
            self.api_key = None
            self._log("error", f"WebSearch: erro ao carregar configuração: {exc}")

    def reload_api_key(self) -> bool:
        old_client = self.client
        self.client = None
        self._load_api_key()
        self._configure_client()
        try:
            close = getattr(old_client, "close", None)
            if callable(close):
                close()
        except Exception:
            pass
        return self.client is not None

    def _configure_client(self):
        if not self.api_key:
            return
        if genai is None or types is None:
            self._log("error", "WebSearch: pacote google-genai nao esta instalado")
            return
        try:
            http_kwargs = {"timeout": self.TIMEOUT_MS}
            retry_cls = getattr(types, "HttpRetryOptions", None)
            if retry_cls is not None:
                try:
                    http_kwargs["retry_options"] = retry_cls(attempts=1)
                except Exception:
                    pass
            try:
                http_options = types.HttpOptions(**http_kwargs)
            except TypeError:
                http_options = types.HttpOptions(timeout=self.TIMEOUT_MS)
            self.client = genai.Client(api_key=self.api_key, http_options=http_options)
            self._log("info", f"WebSearch inicializado (timeout={self.TIMEOUT_MS}ms)")
        except Exception as exc:
            self.client = None
            self._log("error", f"WebSearch: erro ao configurar cliente: {exc}")

    @staticmethod
    def _clean_query(query: str) -> str:
        value = " ".join(str(query or "").split()).strip()
        value = re.sub(
            r"^(?:jarvis[, ]+)?(?:pesquise|pesquisa|pesquisar|procure|procura|procurar|busque|busca|buscar)\s+(?:na\s+internet|na\s+web|online|pela\s+internet)\s+(?:sobre\s+)?",
            "", value, flags=re.I,
        ).strip()
        return value

    def search(self, query: str) -> str:
        query = self._clean_query(query)
        self.last_mode = ""
        self.last_sources = []
        if not query:
            return "Diga o que deseja pesquisar, senhor."

        self._log("system", f"Pesquisa solicitada: {query[:180]}")
        errors = []

        # 1) Grounding oficial. Gemini 2.5 Flash continua sendo uma rota útil
        # para contas com cota de Search habilitada. Se houver 429, não gastamos
        # vários segundos repetindo em modelos 3.x: partimos para busca HTTP.
        if self.client:
            for model in self.SEARCH_MODELS or ("gemini-2.5-flash",):
                model_errors = []
                try:
                    return self._search_with_interactions(query, model)
                except Exception as exc:
                    errors.append(exc)
                    model_errors.append(exc)
                    self._log("warning", f"Interactions/google_search falhou em {model}: {self._safe_error(exc)}")
                try:
                    return self._search_with_generate_content(query, model)
                except Exception as exc:
                    errors.append(exc)
                    model_errors.append(exc)
                    self._log("warning", f"generate_content/google_search falhou em {model}: {self._safe_error(exc)}")
                if any(self._classify_failure(exc) == "quota" for exc in model_errors):
                    break

        reason = self._classify_failure(errors[-1] if errors else RuntimeError("grounding indisponível"))

        # 2) Rota independente da quota de Google Search do Gemini. DuckDuckGo
        # entrega resultados HTML; o Gemini comum, quando disponível, apenas
        # resume os snippets. Se o modelo também estiver indisponível, o JARVIS
        # ainda mostra os resultados encontrados em vez de fingir que pesquisou.
        try:
            return self._search_with_http_engine(query, reason=reason)
        except Exception as exc:
            errors.append(exc)
            self._log("warning", f"Busca HTTP independente falhou: {self._safe_error(exc)}")

        # 3) Último fallback: conhecimento do modelo, explicitamente sem web.
        if self.client:
            return self._fallback_without_web(query, reason=reason)
        return "Não consegui acessar a pesquisa online agora. Verifique a conexão e tente novamente."

    def _prompt(self, query: str) -> str:
        return (
            "Pesquise na internet e responda em português do Brasil.\n\n"
            f"Assunto: {query}\n\n"
            "Priorize informações atuais e fontes primárias/confiáveis. Não invente fatos. "
            "Quando datas forem importantes, use datas explícitas. Seja direto e útil."
        )

    def _search_with_interactions(self, query: str, model: str) -> str:
        interactions = getattr(self.client, "interactions", None)
        create = getattr(interactions, "create", None) if interactions is not None else None
        if not callable(create):
            raise RuntimeError("Interactions API indisponível neste google-genai")
        interaction = create(model=model, input=self._prompt(query), tools=[{"type": "google_search"}])
        text = str(getattr(interaction, "output_text", "") or "").strip()
        if not text:
            text = self._extract_interaction_text(interaction)
        if not text:
            raise RuntimeError("Interactions não retornou texto")
        sources = self._extract_interaction_sources(interaction)
        self.last_mode = "interactions_google_search"
        self.last_sources = sources
        self._log("info", f"Pesquisa web concluída via Interactions ({model})")
        return self._append_sources(self._clean_text(text), sources)

    def _search_with_generate_content(self, query: str, model: str) -> str:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            max_output_tokens=2048,
        )
        response = self.client.models.generate_content(model=model, contents=self._prompt(query), config=config)
        text = self._extract_text(response)
        if not text:
            raise RuntimeError("generate_content não retornou texto")
        sources = self._extract_grounding_sources(response)
        self.last_mode = "generate_content_google_search"
        self.last_sources = sources
        self._log("info", f"Pesquisa web concluída via generate_content ({model})")
        return self._append_sources(self._clean_text(text), sources)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = " ".join(str(exc or "").split())
        return text[:240]

    @staticmethod
    def _classify_failure(exc: Exception) -> str:
        key = str(exc or "").lower()
        if any(x in key for x in ("429", "resource_exhausted", "quota", "rate limit")):
            return "quota"
        if any(x in key for x in ("timeout", "deadline", "timed out")):
            return "timeout"
        return "generic"

    @staticmethod
    def _decode_ddg_url(href: str) -> str:
        href = str(href or "").strip()
        if not href:
            return ""
        if href.startswith("//"):
            href = "https:" + href
        try:
            parsed = urlparse(href)
            if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
                target = parse_qs(parsed.query).get("uddg", [""])[0]
                if target:
                    return unquote(target)
        except Exception:
            pass
        return href

    def _search_with_http_engine(self, query: str, reason: str = "generic") -> str:
        headers = {
            "User-Agent": self.HTTP_USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
        }
        endpoints = (
            "https://html.duckduckgo.com/html/",
            "https://lite.duckduckgo.com/lite/",
        )
        last_error = None
        results = []
        for endpoint in endpoints:
            try:
                response = requests.get(
                    endpoint,
                    params={"q": query, "kl": "br-pt"},
                    headers=headers,
                    timeout=self.HTTP_SEARCH_TIMEOUT_S,
                )
                response.raise_for_status()
                results = self._parse_duckduckgo_results(response.text)
                if results:
                    break
            except Exception as exc:
                last_error = exc
                continue
        if not results:
            raise RuntimeError(f"nenhum resultado HTTP: {last_error or 'resposta vazia'}")

        sources = [f"{item['title']}: {item['url']}" for item in results if item.get("url")]
        self.last_sources = self._dedupe(sources)[:8]
        self.last_mode = "duckduckgo_http"
        self._log("info", f"Pesquisa web concluída via busca HTTP ({len(results)} resultado(s))")

        # O modelo comum não consome cota de Search Grounding. Ele recebe apenas
        # títulos/snippets e é instruído a não extrapolar o material pesquisado.
        if self.client:
            context_lines = []
            for idx, item in enumerate(results[:6], start=1):
                context_lines.append(
                    f"[{idx}] {item['title']}\nURL: {item['url']}\nResumo do resultado: {item['snippet']}"
                )
            try:
                response = self.client.models.generate_content(
                    model=self.FALLBACK_MODEL,
                    contents=(
                        "Responda em português do Brasil usando SOMENTE os resultados de busca abaixo como evidência. "
                        "Não diga que usou Google Search. Se os snippets não forem suficientes, deixe isso claro. "
                        "Priorize o que for mais recente e confiável quando isso puder ser inferido.\n\n"
                        f"Pergunta: {query}\n\nResultados:\n" + "\n\n".join(context_lines)
                    ),
                    config=types.GenerateContentConfig(max_output_tokens=1600),
                )
                text = self._extract_text(response)
                if text:
                    return self._append_sources(self._clean_text(text), self.last_sources)
            except Exception as exc:
                self._log("warning", f"Resumo da busca HTTP falhou; mostrando resultados: {self._safe_error(exc)}")

        lines = ["Encontrei estes resultados na web:"]
        for idx, item in enumerate(results[:5], start=1):
            snippet = item.get("snippet") or "Sem resumo disponível."
            lines.append(f"{idx}. {item['title']} — {snippet}\n{item['url']}")
        return "\n\n".join(lines)

    def _parse_duckduckgo_results(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        out = []
        seen = set()

        # HTML clássico.
        for node in soup.select(".result"):
            anchor = node.select_one("a.result__a")
            if not anchor:
                continue
            title = " ".join(anchor.get_text(" ", strip=True).split())
            url = self._decode_ddg_url(anchor.get("href"))
            snippet_node = node.select_one(".result__snippet")
            snippet = " ".join(snippet_node.get_text(" ", strip=True).split()) if snippet_node else ""
            if title and url and url not in seen:
                seen.add(url)
                out.append({"title": title, "url": url, "snippet": snippet})
            if len(out) >= 8:
                return out

        # Lite muda a marcação com frequência; anchors externos são um fallback
        # mais tolerante. Evitamos links internos do próprio DuckDuckGo.
        if len(out) < 3:
            for anchor in soup.find_all("a", href=True):
                title = " ".join(anchor.get_text(" ", strip=True).split())
                url = self._decode_ddg_url(anchor.get("href"))
                if not title or not url or url in seen:
                    continue
                parsed = urlparse(url if "://" in url else "https://duckduckgo.com" + url)
                if not parsed.netloc or "duckduckgo.com" in parsed.netloc:
                    continue
                parent_text = " ".join(anchor.parent.get_text(" ", strip=True).split()) if anchor.parent else ""
                snippet = parent_text.replace(title, "", 1).strip(" -—|:")[:420]
                seen.add(url)
                out.append({"title": title, "url": url, "snippet": snippet})
                if len(out) >= 8:
                    break
        return out

    def _fallback_without_web(self, query: str, reason: str) -> str:
        prefix = {
            "quota": "A pesquisa online atingiu o limite da API neste momento. ",
            "timeout": "A pesquisa online não respondeu dentro do limite. ",
        }.get(reason, "Não consegui acessar a pesquisa online agora. ")
        prefix += "Vou responder com o conhecimento do modelo, sem consulta em tempo real.\n\n"
        try:
            response = self.client.models.generate_content(
                model=self.FALLBACK_MODEL,
                contents=(
                    "Responda em português do Brasil. Não afirme que pesquisou a internet. "
                    "Se depender de informação recente, diga que pode estar desatualizada.\n\n"
                    f"Pergunta: {query}"
                ),
                config=types.GenerateContentConfig(max_output_tokens=2048),
            )
            text = self._extract_text(response)
            if text:
                self.last_mode = "model_without_web"
                return prefix + self._clean_text(text)
        except Exception as exc:
            self._log("error", f"Fallback sem web falhou: {self._safe_error(exc)}")
        return "Não consegui realizar a pesquisa online nem gerar uma resposta alternativa agora."

    @staticmethod
    def _extract_text(response) -> str:
        try:
            text = getattr(response, "text", None)
            if text:
                return str(text).strip()
        except Exception:
            pass
        try:
            candidates = getattr(response, "candidates", None) or []
            parts = candidates[0].content.parts if candidates else []
            return "\n".join(str(getattr(part, "text", "") or "") for part in parts if getattr(part, "text", None)).strip()
        except Exception:
            return ""

    @staticmethod
    def _extract_interaction_text(interaction) -> str:
        texts = []
        try:
            for step in getattr(interaction, "steps", None) or []:
                if str(getattr(step, "type", "")) != "model_output":
                    continue
                for block in getattr(step, "content", None) or []:
                    if str(getattr(block, "type", "")) == "text" and getattr(block, "text", None):
                        texts.append(str(block.text))
        except Exception:
            pass
        return "\n".join(texts).strip()

    @staticmethod
    def _dedupe(values: Iterable[str]) -> list[str]:
        out = []
        seen = set()
        for value in values:
            value = str(value or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _extract_interaction_sources(self, interaction) -> list[str]:
        found = []
        try:
            for step in getattr(interaction, "steps", None) or []:
                if str(getattr(step, "type", "")) != "model_output":
                    continue
                for block in getattr(step, "content", None) or []:
                    for ann in getattr(block, "annotations", None) or []:
                        if str(getattr(ann, "type", "")) != "url_citation":
                            continue
                        url = str(getattr(ann, "url", "") or "").strip()
                        title = str(getattr(ann, "title", "") or "").strip()
                        if url:
                            found.append(f"{title}: {url}" if title else url)
        except Exception:
            pass
        return self._dedupe(found)[:8]

    def _extract_grounding_sources(self, response) -> list[str]:
        sources = []
        try:
            candidates = getattr(response, "candidates", None) or []
            metadata = getattr(candidates[0], "grounding_metadata", None) if candidates else None
            for chunk in getattr(metadata, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                uri = str(getattr(web, "uri", "") or "").strip() if web else ""
                title = str(getattr(web, "title", "") or "").strip() if web else ""
                if uri:
                    sources.append(f"{title}: {uri}" if title else uri)
        except Exception as exc:
            self._log("warning", f"Não foi possível extrair fontes: {self._safe_error(exc)}")
        return self._dedupe(sources)[:8]

    @staticmethod
    def _append_sources(text: str, sources: list[str]) -> str:
        if not sources or "\nfontes:" in text.lower():
            return text
        return text + "\n\nFontes:\n" + "\n".join(f"- {x}" for x in sources[:8])

    @staticmethod
    def _clean_text(text: str) -> str:
        text = str(text or "").replace("**", "")
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


WebSearchService = WebSearch
