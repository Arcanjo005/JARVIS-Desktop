"""JARVIS Agent - planejamento e execucao conservadora de objetivos.

O planner e local/deterministico. Ele nao transforma texto arbitrario do modelo em
comandos do Windows. Cada etapa passa por uma whitelist e por verificacao explicita.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

try:
    from autonomy_policy import make_policy, percent_from_legacy_autonomy
except Exception:
    make_policy = None
    percent_from_legacy_autonomy = lambda level, default=60: {"manual":20,"assistido":60,"autonomo":80}.get(str(level or "").lower(), default)

try:
    from action_verifier import ActionVerifier
except Exception:
    ActionVerifier = None

try:
    from intent_parser import looks_like_local_command
except Exception:
    def looks_like_local_command(_text: str) -> bool:
        return False


@dataclass
class GoalStep:
    action: str
    value: str = ""
    label: str = ""
    risk: str = "low"
    require_verified: bool = True
    monitor_index: Optional[int] = None


@dataclass
class GoalPlan:
    goal: str
    steps: List[GoalStep] = field(default_factory=list)
    needs_clarification: str = ""


class GoalExecutor:
    MAX_STEPS = 8
    # O planner só barra categorias que não devem ser encadeadas silenciosamente.
    # Fechar apps, suspender e mover arquivos/pastas para a Lixeira são comandos
    # locais explícitos e podem seguir para o Router no modo direto.
    HIGH_RISK_RE = re.compile(
        r"\b(?:compr\w*|pag\w*|pix|transfer\w*(?:\s+dinheiro)?|senha|password|login|cart(?:ao|ão)|"
        r"exclu\w*\s+conta|format\w*|deslig\w*|shutdown|reinici\w*|restart|reboot|instal\w*|desinstal\w*|"
        r"execut\w*\s+(?:o\s+)?arquivo|apag\w*\s+(?:arquivo|pasta).*\b(?:permanentemente|definitivamente|sem\s+lixeira)\b|"
        r"delet\w*\s+(?:arquivo|pasta).*\b(?:permanentemente|definitivamente|sem\s+lixeira)\b|"
        r"sobrescrev\w*|substitu\w*\s+(?:o\s+)?arquivo|envi\w*\s+(?:email|mensagem|formulario|formulário)|"
        r"mand\w*\s+(?:email|mensagem)|public\w*|post\w*)\b", re.I
    )

    def __init__(self, browser, command_executor: Callable[[str], Dict], context=None, logger=None, verifier=None, window_manager=None, media_context=None):
        self.browser = browser
        self.command_executor = command_executor
        self.context = context
        self.logger = logger
        self.verifier = verifier or (ActionVerifier(logger=logger) if ActionVerifier is not None else None)
        self.window_manager = window_manager
        self.media_context = media_context
        self._cancel = threading.Event()
        self._running = threading.Lock()
        self._last_plan: Optional[GoalPlan] = None

    @staticmethod
    def _norm(text: str) -> str:
        text = unicodedata.normalize("NFKD", str(text or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
        text = re.sub(r"[^a-z0-9 ]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _monitor_from_text(cls, text: str) -> Optional[int]:
        key = cls._norm(text)
        m = re.search(
            r"\b(?:tela|monitor|display)\s*(?:numero\s*)?"
            r"(\d+|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|"
            r"primeiro|primeira|segundo|segunda|terceiro|terceira|quarto|quarta)\b",
            key, re.I,
        )
        if not m:
            return None
        token = m.group(1).lower()
        if token.isdigit():
            value = int(token)
            return value if 1 <= value <= 16 else None
        words = {
            "um": 1, "uma": 1, "primeiro": 1, "primeira": 1,
            "dois": 2, "duas": 2, "segundo": 2, "segunda": 2,
            "tres": 3, "terceiro": 3, "terceira": 3,
            "quatro": 4, "quarto": 4, "quarta": 4,
            "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
        }
        return words.get(token)

    def cancel(self):
        self._cancel.set()

    def reset_cancel(self):
        self._cancel.clear()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def is_running(self) -> bool:
        """True somente enquanto um objetivo esta efetivamente em execucao."""
        return self._running.locked()

    def plan(self, goal: str) -> GoalPlan:
        raw = " ".join(str(goal or "").split()).strip()
        key = self._norm(raw)
        plan = GoalPlan(raw)
        if not raw:
            plan.needs_clarification = "Qual objetivo você quer que eu execute?"
            return plan
        if self.HIGH_RISK_RE.search(key):
            plan.needs_clarification = "Esse objetivo inclui uma etapa de alto impacto que não vou encadear silenciosamente. Diga essa etapa como um comando separado."
            return plan
        if re.match(r"^(?:nao|nunca)\b", key):
            plan.needs_clarification = "Entendi como uma negação; não executei nenhuma ação."
            return plan
        if re.match(
            r"^(?:como|por que|porque|quando|onde|qual|quais|quem|o que|"
            r"(?:voce\s+)?consegue|da pra|daria pra|quero saber|me explica|explique|vamos conversar sobre)\b",
            key, re.I,
        ):
            plan.needs_clarification = "Isso parece uma pergunta ou conversa sobre a ação, não uma ordem para executá-la."
            return plan

        # Adaptador universal de streaming. A BrowserAutonomy detecta o servico
        # ativo por contexto e usa visao primeiro; atalhos so entram quando o
        # servico e conhecido. Mantemos compatibilidade com frases Crunchyroll.
        monitor_index = self._monitor_from_text(key)
        streaming_services = (
            "crunchyroll", "netflix", "prime video", "amazon prime", "disney",
            "disney plus", "max", "hbo max", "globoplay", "paramount",
            "apple tv", "youtube", "twitch"
        )
        service_hint = next((name for name in streaming_services if name in key), "")
        player_prefix = (
            r"(?:(?:(?:na|no)\s+)?(?:tela|monitor|display)\s*(?:numero\s*)?"
            r"(?:\d+|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|"
            r"primeiro|primeira|segundo|segunda|terceiro|terceira|quarto|quarta)\s+)?"
            r"(?:(?:no|na)\s+(?:crunchyroll|netflix|prime video|amazon prime|disney(?: plus)?|"
            r"max|hbo max|globoplay|paramount(?: plus)?|apple tv|youtube|twitch)\s+)?"
        )
        skip_intent = bool(re.match(player_prefix + r"(?:pula|pular|skip) (?:a )?(?:abertura|intro|introducao|recap|resumo)\b", key, re.I))
        next_intent = bool(re.match(player_prefix + r"(?:proximo episodio|proximo ep|passa pro proximo|passa para o proximo|next episode)\b", key, re.I))
        player_context = bool(service_hint)
        player_intent = skip_intent or next_intent or bool(re.match(player_prefix + r"(?:pausa|pause|continua|play|reproduz|tela cheia|fullscreen)\b", key, re.I))
        if player_context or player_intent:
            if skip_intent:
                plan.steps.append(GoalStep(
                    "stream_skip", value=service_hint, label="Pular abertura no player",
                    require_verified=False, monitor_index=monitor_index,
                ))
            if next_intent:
                plan.steps.append(GoalStep(
                    "stream_next", value=service_hint, label="Abrir proximo episodio",
                    require_verified=False, monitor_index=monitor_index,
                ))
            if re.search(r"\b(?:pausa|pause|continua|continue|play|reproduz)\b", key):
                plan.steps.append(GoalStep("stream_play_pause", value=service_hint, label="Alternar reproducao", require_verified=False))
            if re.search(r"\b(?:liga|ativa|coloca|tira|desliga).*(?:legenda|legendas|caption|captions)\b", key):
                plan.steps.append(GoalStep("stream_captions", value=service_hint, label="Alternar legendas", require_verified=False))
            if re.search(r"\b(?:tela cheia|fullscreen|full screen)\b", key):
                plan.steps.append(GoalStep("stream_fullscreen", value=service_hint, label="Alternar tela cheia", require_verified=False))
            m_seek = re.search(r"\b(?:avanca|adianta|pula)\s+(\d+)\s*(?:segundos?|s)\b", key)
            if m_seek:
                plan.steps.append(GoalStep("stream_seek", value=f"{m_seek.group(1)}|{service_hint}", label=f"Avancar {m_seek.group(1)} segundos", require_verified=False))
            m_back = re.search(r"\b(?:volta|retrocede)\s+(\d+)\s*(?:segundos?|s)\b", key)
            if m_back:
                plan.steps.append(GoalStep("stream_seek", value=f"-{m_back.group(1)}|{service_hint}", label=f"Voltar {m_back.group(1)} segundos", require_verified=False))
            if plan.steps:
                self._last_plan = plan
                return plan

        # Objetivos web compostos. Procura a consulta ate o proximo verbo de etapa.
        m = re.search(
            r"\b(?:pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar)\b\s+"
            r"(?:(?:no|na)\s+opera(?:\s+gx)?\s+)?"
            r"(.+?)(?="
            r"\s+(?:(?:e\s+)?(?:depois|agora|entao)\s+|e\s+)"
            r"(?:abre|abra|entra|entre|baixa|baixe|baixar|download|faz|faca|clica|clique)\b"
            r"|[,;]|$)",
            raw, flags=re.I,
        )
        query = ""
        if m:
            query = m.group(1).strip(" ,;.")
            query = re.sub(r"^(?:por|sobre)\s+", "", query, flags=re.I).strip()
            # Em fala natural o navegador costuma vir depois da consulta:
            # "pesquisa OBS no Opera e depois...". O browser nao faz parte da busca.
            query = re.sub(r"\s+(?:no|na)\s+opera(?:\s+gx)?\s*$", "", query, flags=re.I).strip()
            if query:
                plan.steps.append(GoalStep("search", value=query, label=f"Pesquisar no Opera: {query}"))
        official = bool(re.search(r"\b(?:site|pagina) oficial\b", key))
        first = bool(re.search(r"\b(?:primeiro resultado|primeiro site|primeiro link)\b", key))
        enter = bool(re.search(r"\b(?:entra|entre|abre|abra)\s+(?:no|o)?\s*(?:site|resultado|primeiro)\b", key))
        if official:
            plan.steps.append(GoalStep("official_result", value=query, label="Abrir o site oficial"))
        elif first or enter:
            plan.steps.append(GoalStep("first_result", label="Abrir o primeiro resultado orgânico"))
        wants_download = bool(re.search(r"\b(?:baixa|baixe|baixar|download|faz download|fazer download)\b", key))
        if wants_download:
            # Se so pediu pesquisa + download, nao adivinha qual resultado abrir.
            if query and len(plan.steps) == 1:
                plan.needs_clarification = "O objetivo inclui pesquisa e download; para baixar com segurança preciso saber qual resultado/site abrir (por exemplo: 'site oficial' ou 'primeiro resultado')."
            else:
                plan.steps.append(GoalStep("download", value=query, label="Baixar o arquivo visível e verificar em Downloads", risk="medium"))

        # Controle visual explicito, de baixa ambiguidade.
        m_click = re.search(r"\b(?:clica|clique|aperta|pressiona)\s+(?:no|na|em)?\s*(.+)$", raw, flags=re.I)
        if m_click and not plan.steps:
            desc = m_click.group(1).strip()
            click_monitor = self._monitor_from_text(desc)
            if click_monitor is not None:
                desc = re.sub(
                    r"\s+(?:na|no)?\s*(?:tela|monitor|display)\s*(?:numero\s*)?"
                    r"(?:\d+|um|uma|dois|duas|tres|três|quatro|cinco|seis|sete|oito|"
                    r"primeiro|primeira|segundo|segunda|terceiro|terceira|quarto|quarta)\s*$",
                    "", desc, flags=re.I,
                ).strip()
            plan.steps.append(GoalStep(
                "visual_click", value=desc, label=f"Localizar e clicar: {desc}",
                require_verified=False, monitor_index=click_monitor,
            ))

        # Layout de apps em uma frase: "abre OBS e Opera no monitor 2".
        # So aceita dois nomes simples e destino de monitor explicito/opcional;
        # nenhum texto vira shell ou automacao generica.
        m_multi_open = re.match(
            r"^(?:abre|abra|abrir)\s+(?:o\s+|a\s+)?([\w .+\-]{1,60}?)\s+e\s+(?:o\s+|a\s+)?([\w .+\-]{1,60}?)"
            r"(?:\s+(?:no|na|pro|pra|para o|para a)\s+(?:monitor|tela|display)\s*(\d+))?\s*$",
            raw, flags=re.I,
        )
        if m_multi_open and not plan.steps:
            app_a = m_multi_open.group(1).strip()
            app_b = m_multi_open.group(2).strip()
            mon = int(m_multi_open.group(3)) if m_multi_open.group(3) else None
            blocked_tail = re.compile(r"\b(?:abre|fecha|minimiza|maximiza|move|pesquisa|baixa|clica|desliga|apaga)\b", re.I)
            if not blocked_tail.search(app_a) and not blocked_tail.search(app_b):
                plan.steps.append(GoalStep("command", value=f"abre {app_a}", label=f"Abrir {app_a}", require_verified=True))
                plan.steps.append(GoalStep("command", value=f"abre {app_b}", label=f"Abrir {app_b}", require_verified=True))
                if mon is not None:
                    plan.steps.append(GoalStep("command", value=f"move {app_a} para monitor {mon}", label=f"Mover {app_a} para monitor {mon}", require_verified=True))
                    plan.steps.append(GoalStep("command", value=f"move {app_b} para monitor {mon}", label=f"Mover {app_b} para monitor {mon}", require_verified=True))

        # Comando de app simples dentro de um objetivo maior.
        m_open = re.match(r"^(?:vai no|abre|abra|abrir)\s+(?:o|a)?\s*([\w .+\-]+)$", raw, flags=re.I)
        if m_open and not plan.steps and not re.search(r"\b(?:e\s+depois|depois|em\s+seguida|e\s+entao|entao)\b", key):
            app = m_open.group(1).strip()
            plan.steps.append(GoalStep("command", value=f"abre {app}", label=f"Abrir {app}"))

        # Objetivos gerais do Windows podem reutilizar qualquer comando local
        # seguro ja entendido pelo Router. Ex.: "abre Discord e depois minimiza
        # o Opera". Nao interpretamos texto livre como shell; comandos locais explícitos seguem para o Router.
        if not plan.steps and not plan.needs_clarification:
            clauses = [
                part.strip(" ,;.") for part in re.split(
                    r"(?:\s+(?:e\s+depois|depois|em\s+seguida|e\s+entao|entao)\s+|\s*[;,]\s*)",
                    raw, flags=re.I,
                ) if part.strip(" ,;.")
            ]
            if 1 < len(clauses) <= self.MAX_STEPS and all(looks_like_local_command(part) for part in clauses):
                for part in clauses:
                    plan.steps.append(GoalStep(
                        "command", value=part, label=f"Executar: {part}",
                        risk="low", require_verified=False,
                    ))

        if not plan.steps and not plan.needs_clarification:
            plan.needs_clarification = "Ainda não consigo transformar esse objetivo em um plano autônomo seguro. Tente dizer as etapas principais ou indicar o elemento visível."
        plan.steps = plan.steps[: self.MAX_STEPS]
        self._last_plan = plan
        return plan

    def _run_step(self, step: GoalStep) -> Dict:
        started = time.perf_counter()
        if step.action == "search":
            msg = self.browser.actions.search_web_in_opera(step.value)
            ok = not str(msg).lower().startswith(("não", "nao", "erro"))
            result = {"success": ok, "verified": ok, "message": str(msg), "action": "BROWSER_SEARCH", "risk": "low"}
        elif step.action == "official_result":
            result = self.browser.open_official_result(step.value)
        elif step.action == "first_result":
            result = self.browser.open_first_result()
        elif step.action == "download":
            result = self.browser.download_visible(step.value)
        elif step.action == "visual_click":
            result = self.browser.click_visible(step.value, monitor_index=step.monitor_index)
        elif step.action == "stream_skip":
            result = self.browser.streaming_control("skip_intro", monitor_index=step.monitor_index, service_hint=step.value)
        elif step.action == "stream_next":
            result = self.browser.streaming_control("next", monitor_index=step.monitor_index, service_hint=step.value)
        elif step.action == "stream_play_pause":
            result = self.browser.streaming_control("play_pause", service_hint=step.value)
        elif step.action == "stream_captions":
            result = self.browser.streaming_control("captions", service_hint=step.value)
        elif step.action == "stream_fullscreen":
            result = self.browser.streaming_control("fullscreen", service_hint=step.value)
        elif step.action == "stream_seek":
            seconds_text, _, service = str(step.value or "0").partition("|")
            result = self.browser.streaming_control("seek", seconds=int(seconds_text or 0), service_hint=service)
        elif step.action == "crunchy_skip":
            result = self.browser.streaming_control("skip_intro", monitor_index=step.monitor_index, service_hint="crunchyroll")
        elif step.action == "crunchy_next":
            result = self.browser.streaming_control("next", monitor_index=step.monitor_index, service_hint="crunchyroll")
        elif step.action == "crunchy_play_pause":
            result = self.browser.streaming_control("play_pause", service_hint="crunchyroll")
        elif step.action == "crunchy_captions":
            result = self.browser.streaming_control("captions", service_hint="crunchyroll")
        elif step.action == "crunchy_seek":
            result = self.browser.streaming_control("seek", seconds=int(step.value or 0), service_hint="crunchyroll")
        elif step.action == "command":
            result = dict(self.command_executor(step.value) or {})
        else:
            result = {"success": False, "verified": False, "message": f"Etapa não suportada: {step.action}"}
        result = dict(result or {})
        result.setdefault("success", False)
        result.setdefault("verified", False)
        result.setdefault("risk", step.risk)
        result["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        result["label"] = step.label
        return result

    def _post_verify(self, step: GoalStep, result: Dict) -> Dict:
        if bool(result.get("verified")) or not self.verifier:
            return result
        command = step.value if step.action == "command" else ""
        if not command:
            return result
        try:
            check = self.verifier.verify_command(
                command, result, window_manager=self.window_manager,
                media_context=self.media_context, timeout=1.15,
            )
            result["verification"] = check.to_dict()
            if check.verified:
                result["verified"] = True
                result["verification_status"] = check.status
        except Exception as exc:
            result["verification_error"] = str(exc)[:180]
        return result

    def execute(
        self, goal: str, progress: Optional[Callable[[Dict], None]] = None,
        autonomy_level: str = "assistido", autonomy_percent: Optional[int] = None,
        presence_percent: int = 60,
    ) -> Dict:
        if not self._running.acquire(blocking=False):
            return {"success": False, "verified": False, "message": "Já existe um objetivo em execução.", "steps": []}
        self.reset_cancel()
        try:
            plan = self.plan(goal)
            if plan.needs_clarification:
                return {"success": False, "verified": False, "message": plan.needs_clarification, "plan": plan, "steps": []}

            if autonomy_percent is None:
                autonomy_percent = percent_from_legacy_autonomy(autonomy_level, 60)
            policy = make_policy(autonomy_percent, presence_percent) if make_policy else None
            max_steps = int(getattr(policy, "max_steps", self.MAX_STEPS))
            retry_budget = int(getattr(policy, "retry_budget", 0))
            allow_goal = bool(getattr(policy, "allow_goal_execution", str(autonomy_level).lower() != "manual"))
            allow_unverified = bool(getattr(policy, "allow_low_risk_unverified_continue", str(autonomy_level).lower() == "autonomo"))

            if not allow_goal:
                labels = " → ".join(step.label or step.action for step in plan.steps)
                return {
                    "success": False, "verified": False, "needs_confirmation": True,
                    "message": f"Plano preparado: {labels}. Com autonomia {int(autonomy_percent)}% eu não executo objetivos em cadeia automaticamente.",
                    "plan": plan, "steps": [], "policy": policy.to_dict() if policy else {},
                }
            if len(plan.steps) > max_steps:
                labels = " → ".join(step.label or step.action for step in plan.steps[:max_steps])
                return {
                    "success": False, "verified": False, "needs_confirmation": True,
                    "message": f"Esse objetivo tem {len(plan.steps)} etapas; autonomia {int(autonomy_percent)}% permite até {max_steps}. Primeiras etapas: {labels}.",
                    "plan": plan, "steps": [], "policy": policy.to_dict() if policy else {},
                }

            results = []
            total = len(plan.steps)
            if self.context:
                self.context.set_goal(goal, status="running", progress=0.0)

            for idx, step in enumerate(plan.steps, start=1):
                if self.is_cancelled():
                    if self.context:
                        self.context.clear_goal(status="cancelled")
                    return {"success": False, "verified": False, "message": "Objetivo interrompido.", "plan": plan, "steps": results}

                if progress:
                    progress({"index": idx, "total": total, "label": step.label or step.action, "status": "running", "progress": (idx - 1) / max(1, total)})
                if self.context:
                    self.context.set_goal(goal, status="running", step=step.label, progress=(idx - 1) / max(1, total))

                attempts = 0
                result = {}
                while True:
                    attempts += 1
                    result = self._post_verify(step, self._run_step(step))
                    result["attempt"] = attempts
                    low_risk = str(step.risk or result.get("risk") or "low").lower() == "low"
                    needs_retry = low_risk and (not result.get("success") or (step.require_verified and not result.get("verified")))
                    if not needs_retry or attempts > retry_budget:
                        break
                    if self.is_cancelled():
                        break
                    if progress:
                        progress({
                            "index": idx, "total": total, "label": step.label or step.action,
                            "status": "retrying", "progress": (idx - 1) / max(1, total),
                            "message": f"Tentativa alternativa {attempts}/{retry_budget + 1}",
                        })
                    time.sleep(0.10)

                result["attempts"] = attempts
                results.append(result)
                if self.context:
                    try:
                        self.context.record_action(result.get("action", step.action), result.get("message", ""), bool(result.get("verified")), result.get("detail"))
                    except Exception:
                        pass

                if not result.get("success"):
                    if self.context:
                        self.context.clear_goal(status="failed")
                    if progress:
                        progress({"index": idx, "total": total, "label": step.label, "status": "failed", "progress": idx / max(1, total), "message": result.get("message", "")})
                    return {
                        "success": False, "verified": False,
                        "message": f"Parei no passo {idx}/{total}: {result.get('message') or step.label}",
                        "plan": plan, "steps": results, "policy": policy.to_dict() if policy else {},
                    }

                if step.require_verified and not result.get("verified"):
                    low_risk_success = bool(result.get("success")) and str(step.risk or result.get("risk") or "low").lower() == "low"
                    if allow_unverified and low_risk_success:
                        if progress:
                            progress({"index": idx, "total": total, "label": step.label, "status": "unverified_continue", "progress": idx / max(1, total), "message": result.get("message", "")})
                    else:
                        if self.context:
                            self.context.clear_goal(status="unverified")
                        return {
                            "success": False, "verified": False,
                            "message": f"Executei o passo {idx}, mas não consegui verificar o efeito; não continuei automaticamente. {result.get('message','')}",
                            "plan": plan, "steps": results, "policy": policy.to_dict() if policy else {},
                        }
                if progress:
                    progress({"index": idx, "total": total, "label": step.label, "status": "done", "progress": idx / max(1, total), "message": result.get("message", "")})

            if self.is_cancelled():
                if self.context:
                    self.context.clear_goal(status="cancelled")
                return {"success": False, "verified": False, "message": "Objetivo interrompido.", "plan": plan, "steps": results}
            verified = bool(results) and all(bool(r.get("verified")) or not plan.steps[i].require_verified for i, r in enumerate(results))
            if self.context:
                self.context.clear_goal(status="done")
            suffix = " e verificado" if verified else "; concluído com etapas de baixo risco não verificáveis"
            return {
                "success": True, "verified": verified,
                "message": f"✓ Objetivo concluído em {len(results)} passo(s){suffix}.",
                "plan": plan, "steps": results, "policy": policy.to_dict() if policy else {},
            }
        finally:
            self._running.release()
