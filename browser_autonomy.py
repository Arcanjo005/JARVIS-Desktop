"""JARVIS - Browser Autonomy Engine.

Camada local para objetivos web de baixa/media complexidade. Executa navegação e
controles comuns diretamente, prefere atalhos oficiais de sites conhecidos e usa
visão quando não existe caminho determinístico.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, Optional

try:
    import pyautogui
except Exception:
    pyautogui = None


class BrowserAutonomyEngine:
    DANGEROUS_UI_RE = re.compile(
        r"\b(?:comprar|pagar|pagamento|finalizar compra|confirmar compra|enviar senha|senha|pix|transferencia|"
        r"excluir|apagar conta|deletar|formatar|instalar|executar|abrir instalador|permitir administrador|uac)\b",
        re.I,
    )
    EXECUTABLE_EXTENSIONS = {".exe", ".msi", ".msix", ".bat", ".cmd", ".ps1", ".scr", ".com", ".jar"}

    # Perfis conhecidos aceleram atalhos somente quando o contexto identifica
    # inequivocamente o serviço. Plataformas desconhecidas continuam funcionando
    # pela visão, sem depender de seletores HTML frágeis ou extensões do navegador.
    STREAMING_PROFILES = {
        "crunchyroll": {"aliases": ("crunchyroll", "crunchy roll"), "seek_step": 10, "seek_back": "j", "seek_forward": "l", "fullscreen": "f", "play_pause": "k", "next": ("shift", "n"), "skip": ("s",)},
        "youtube": {"aliases": ("youtube", "youtu be"), "seek_step": 10, "seek_back": "j", "seek_forward": "l", "fullscreen": "f", "play_pause": "k", "next": ("shift", "n")},
        "netflix": {"aliases": ("netflix",), "seek_step": 10, "seek_back": "left", "seek_forward": "right", "play_pause": "space"},
        "prime video": {"aliases": ("prime video", "amazon prime", "primevideo"), "seek_step": 10, "seek_back": "left", "seek_forward": "right", "play_pause": "space"},
        "disney+": {"aliases": ("disney+", "disney plus", "disneyplus"), "seek_step": 10, "seek_back": "left", "seek_forward": "right", "play_pause": "space"},
        "max": {"aliases": ("hbo max", "hbomax", "max"), "seek_step": 10, "seek_back": "left", "seek_forward": "right", "play_pause": "space"},
        "globoplay": {"aliases": ("globoplay", "globo play"), "seek_step": 10, "seek_back": "left", "seek_forward": "right", "play_pause": "space"},
        "paramount+": {"aliases": ("paramount+", "paramount plus", "paramountplus"), "seek_step": 10, "seek_back": "left", "seek_forward": "right", "play_pause": "space"},
        "apple tv": {"aliases": ("apple tv", "tv.apple", "apple television"), "seek_step": 10, "seek_back": "left", "seek_forward": "right", "play_pause": "space"},
        "twitch": {"aliases": ("twitch",), "play_pause": "space", "fullscreen": "f"},
        # Players/servicos adicionais: sem atalhos presumidos; usam visao.
        "plex": {"aliases": ("plex",)},
        "jellyfin": {"aliases": ("jellyfin",)},
        "stremio": {"aliases": ("stremio",)},
        "kodi": {"aliases": ("kodi",)},
        "mubi": {"aliases": ("mubi",)},
        "claro tv+": {"aliases": ("claro tv", "claro tv+", "clarotv")},
    }

    def __init__(self, actions, vision=None, window_manager=None, logger=None, operational_context=None):
        self.actions = actions
        self.vision = vision
        self.window_manager = window_manager
        self.logger = logger
        self.context = operational_context
        self.download_dir = Path.home() / "Downloads"
        self.last_result: Dict = {}

    @staticmethod
    def _norm(text: str) -> str:
        text = unicodedata.normalize("NFKD", str(text or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
        text = re.sub(r"[^a-z0-9 ]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _log(self, level: str, message: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try: fn(message, "AUTONOMY")
                except TypeError: fn(message)
        except Exception:
            pass

    def _record(self, result: Dict):
        self.last_result = result
        if self.context is not None:
            try:
                self.context.record_action(result.get("action", "WEB"), result.get("message", ""), bool(result.get("verified")), result.get("detail"))
                path = (result.get("detail") or {}).get("path")
                if path:
                    self.context.record_download(path, bool(result.get("verified")))
            except Exception:
                pass
        return result

    def _result(self, success: bool, verified: bool, message: str, action: str = "", detail=None, risk: str = "low") -> Dict:
        return self._record({
            "success": bool(success), "verified": bool(verified), "message": str(message or ""),
            "action": action, "detail": detail or {}, "risk": risk,
        })

    def _opera_candidates(self):
        if not self.window_manager:
            return []
        try:
            windows = list(self.window_manager.list_windows() or [])
        except Exception:
            return []
        out = []
        for item in windows:
            title = self._norm(item.get("title", ""))
            process = self._norm(item.get("process_name", ""))
            if "opera" in title or "opera" in process:
                out.append(item)
        return out

    def _focus_item(self, item: Dict) -> bool:
        if not item or not self.window_manager:
            return False
        try:
            focus = getattr(self.window_manager, "focus_window", None)
            if callable(focus):
                return bool(focus(item.get("hwnd")))
            return bool(self.window_manager._force_foreground(item.get("hwnd")))
        except Exception:
            return False

    def _focus_opera(self, require_crunchyroll: bool = False) -> tuple[Optional[Dict], str]:
        candidates = self._opera_candidates()
        if not candidates:
            return None, "Não encontrei uma janela do Opera aberta."
        item = None
        if require_crunchyroll:
            item = next((x for x in candidates if "crunchyroll" in self._norm(x.get("title", ""))), None)
            if item is None:
                return None, "Não identifiquei uma aba do Crunchyroll aberta no Opera com segurança."
        else:
            foreground = next((x for x in candidates if x.get("foreground")), None)
            if foreground is not None:
                item = foreground
            elif len(candidates) == 1:
                item = candidates[0]
            else:
                return None, "Há mais de uma janela do Opera e nenhuma está ativa; não escolhi uma delas por adivinhação."
        if not self._focus_item(item):
            return None, "Encontrei o Opera, mas não consegui colocar a janela correta em foco."
        return item, ""

    def _press(self, key: str = "", hotkey: tuple[str, ...] = ()) -> bool:
        if pyautogui is None:
            return False
        try:
            if hotkey:
                pyautogui.hotkey(*hotkey)
            else:
                pyautogui.press(key)
            return True
        except Exception:
            return False

    def _streaming_context(self) -> Dict:
        try:
            if self.context is not None and self.window_manager is not None:
                refresh = getattr(self.context, "refresh_from_windows", None)
                if callable(refresh):
                    return dict(refresh(self.window_manager) or {})
            if self.context is not None:
                return dict(self.context.snapshot() or {})
        except Exception:
            pass
        title = ""
        try:
            if self.window_manager is not None:
                title = str(self.window_manager.active_window_title() or "")
        except Exception:
            pass
        return {"active_title": title, "active_site": "", "active_app": ""}

    def _canonical_streaming_service(self, text: str = "") -> str:
        key = self._norm(text)
        if not key:
            return ""
        for service, profile in self.STREAMING_PROFILES.items():
            aliases = tuple(profile.get("aliases") or ())
            if any(self._norm(alias) in key for alias in aliases if alias):
                return service
        return ""

    def _focus_streaming_service(self, service: str) -> bool:
        """Foca uma unica janela que identifique claramente o servico."""
        service = self._canonical_streaming_service(service)
        if not service or self.window_manager is None:
            return False
        aliases = tuple(self.STREAMING_PROFILES.get(service, {}).get("aliases") or ())
        try:
            windows = list(self.window_manager.list_windows() or [])
        except Exception:
            return False
        matches = []
        for item in windows:
            hay = self._norm(f"{item.get('title','')} {item.get('process_name','')}")
            if any(self._norm(alias) in hay for alias in aliases if alias):
                matches.append(item)
        if len(matches) != 1:
            foreground = [item for item in matches if item.get("foreground")]
            if len(foreground) == 1:
                matches = foreground
            else:
                return False
        return self._focus_item(matches[0])

    def detect_streaming_service(self, service_hint: str = "") -> str:
        # Primeiro prova o servico pelo contexto REAL. O hint nunca basta para
        # autorizar um atalho de teclado.
        snap = self._streaming_context()
        haystack = self._norm(" ".join(str(snap.get(k) or "") for k in ("active_site", "active_title", "active_app")))
        for service, profile in self.STREAMING_PROFILES.items():
            aliases = tuple(profile.get("aliases") or ())
            if any(self._norm(alias) in haystack for alias in aliases if alias):
                return service

        hinted = self._canonical_streaming_service(service_hint)
        if hinted and self._focus_streaming_service(hinted):
            # Rele o contexto depois de focar. Se o titulo/processo ainda nao
            # confirmar, nao inventamos identidade de plataforma.
            snap = self._streaming_context()
            haystack = self._norm(" ".join(str(snap.get(k) or "") for k in ("active_site", "active_title", "active_app")))
            aliases = tuple(self.STREAMING_PROFILES.get(hinted, {}).get("aliases") or ())
            if any(self._norm(alias) in haystack for alias in aliases if alias):
                return hinted
        return ""

    def is_streaming_active(self) -> bool:
        if self.detect_streaming_service():
            return True
        snap = self._streaming_context()
        key = self._norm(" ".join(str(snap.get(k) or "") for k in ("active_site", "active_title", "active_app")))
        return bool(re.search(r"\b(?:video|player|episodio|episode|filme|movie|serie|stream|watch)\b", key))

    def _streaming_visual_description(self, action: str, service: str = "") -> str:
        platform = f" do {service}" if service else " do player de vídeo atual"
        descriptions = {
            "skip_intro": f"botao visivel{platform} para Pular abertura, Pular introducao, Pular intro, Skip Intro, Skip Opening ou Ignorar abertura; nao clique em anuncios, recomendacoes, trailers ou controles do navegador",
            "next": f"botao visivel{platform} para Proximo episodio, Episodio seguinte, Next Episode, Play Next ou Assistir proximo; nao clique em recomendacoes, anuncios ou outro titulo",
            "play_pause": f"controle visivel{platform} de Reproduzir, Pausar, Play ou Pause",
            "fullscreen": f"controle visivel{platform} de Tela cheia, Full screen, Fullscreen ou Expandir player",
            "mute": f"controle visivel{platform} de Som, Mudo, Mutar, Mute ou Unmute",
            "captions": f"controle visivel{platform} de Legendas, Subtitles, Closed Captions, CC ou Audio e legendas",
        }
        return descriptions.get(action, f"controle visivel{platform} correspondente a {action}")

    def streaming_control(self, action: str, seconds: int = 0, monitor_index: Optional[int] = None, service_hint: str = "") -> Dict:
        """Controle universal de streaming por contexto + visão + atalhos seguros.

        Não depende de DOM/HTML e portanto funciona tanto em sites quanto em apps
        quando o controle está visível. Atalhos só são usados em serviços conhecidos
        e com contexto ativo; em serviço desconhecido, a visão é o caminho principal.
        """
        action = str(action or "").strip().lower()
        aliases = {"skip": "skip_intro", "intro": "skip_intro", "episode": "next", "next_episode": "next", "pause": "play_pause", "play": "play_pause", "full": "fullscreen", "subtitles": "captions"}
        action = aliases.get(action, action)
        requested_service = self._canonical_streaming_service(service_hint)
        service = self.detect_streaming_service(service_hint)
        profile = dict(self.STREAMING_PROFILES.get(service) or {})

        if action not in {"skip_intro", "next", "seek", "play_pause", "fullscreen", "mute", "captions"}:
            return self._result(False, False, "Controle de streaming desconhecido.", action="STREAMING_CONTROL")

        if requested_service and service != requested_service:
            return self._result(
                False, False,
                f"Não confirmei uma janela ativa do {requested_service}; não enviei teclas nem cliques.",
                action=f"STREAMING_{action.upper()}",
            )

        # Para ações de botão, visão é universal e evita assumir atalhos iguais em
        # plataformas diferentes. Um alvo visual precisa passar a confiança mínima.
        if action != "seek":
            visual = self.click_visible(self._streaming_visual_description(action, service), monitor_index=monitor_index)
            if visual.get("success"):
                label = {
                    "skip_intro": "Acionei o controle de pular abertura.",
                    "next": "Acionei o controle de próximo episódio.",
                    "play_pause": "Acionei o controle de reprodução.",
                    "fullscreen": "Acionei o controle de tela cheia.",
                    "mute": "Acionei o controle de áudio.",
                    "captions": "Acionei o controle de legendas.",
                }.get(action, "Controle acionado.")
                detail = dict(visual.get("detail") or {})
                detail.update({"service": service or "generic", "method": "vision"})
                # Um clique visual confirma o alvo e o input, não o efeito final
                # do player. O chamador pode verificar título/estado depois.
                return self._result(True, False, label + " Ainda não confirmei a mudança de estado do player.", action=f"STREAMING_{action.upper()}", detail=detail)

        # Se a visão não encontrou o botão, atalhos só entram quando sabemos qual
        # serviço está ativo. Isso impede digitar teclas em uma janela aleatória.
        if not service or monitor_index is not None:
            if action == "seek":
                return self._result(False, False, "Não identifiquei com segurança um player compatível para avançar ou voltar.", action="STREAMING_SEEK")
            return self._result(False, False, "Não encontrei o controle do player com confiança suficiente.", action=f"STREAMING_{action.upper()}")

        if action == "skip_intro":
            hot = tuple(profile.get("skip") or ())
            if hot and self._press(key=hot[0] if len(hot) == 1 else "", hotkey=hot if len(hot) > 1 else ()):
                return self._result(True, False, "Comando de pular abertura enviado; ainda não confirmei que a abertura foi pulada.", action="STREAMING_SKIP_INTRO", detail={"service": service, "method": "shortcut"})
            return self._result(False, False, "A plataforma não oferece um atalho seguro conhecido e o botão não foi localizado.", action="STREAMING_SKIP_INTRO")

        if action == "next":
            hot = tuple(profile.get("next") or ())
            before_title = str(self._streaming_context().get("active_title") or "")
            if hot and self._press(key=hot[0] if len(hot) == 1 else "", hotkey=hot if len(hot) > 1 else ()):
                verified = False
                deadline = time.monotonic() + 2.2
                while time.monotonic() < deadline:
                    time.sleep(0.18)
                    after_title = str(self._streaming_context().get("active_title") or "")
                    if before_title and after_title and after_title != before_title:
                        verified = True
                        break
                msg = "✓ Próximo episódio confirmado." if verified else "Comando de próximo episódio enviado; ainda não confirmei a troca do episódio."
                return self._result(True, verified, msg, action="STREAMING_NEXT", detail={"service": service, "method": "shortcut"})
            return self._result(False, False, "Não encontrei o botão de próximo episódio e não há atalho seguro conhecido para esta plataforma.", action="STREAMING_NEXT")

        if action == "seek":
            seconds = int(seconds or 0)
            if not seconds:
                return self._result(True, True, "Nada para avançar.", action="STREAMING_SEEK")
            step = max(1, int(profile.get("seek_step") or 10))
            key = profile.get("seek_forward") if seconds > 0 else profile.get("seek_back")
            if not key or pyautogui is None:
                return self._result(False, False, "Este player não tem atalho de avanço/retrocesso conhecido.", action="STREAMING_SEEK")
            presses = max(1, min(int(round(abs(seconds) / step)), 36))
            try:
                pyautogui.press(str(key), presses=presses, interval=0.035)
            except Exception as exc:
                return self._result(False, False, f"Não consegui controlar o player: {exc}", action="STREAMING_SEEK")
            moved = presses * step * (1 if seconds > 0 else -1)
            return self._result(True, False, f"Comando para {'avançar' if moved > 0 else 'voltar'} {abs(moved)} segundos enviado ao player.", action="STREAMING_SEEK", detail={"service": service, "seconds": moved, "method": "shortcut"})

        shortcut = profile.get(action)
        if shortcut:
            hot = tuple(shortcut) if isinstance(shortcut, (tuple, list)) else ()
            ok = self._press(key=str(shortcut) if not hot else (hot[0] if len(hot) == 1 else ""), hotkey=hot if len(hot) > 1 else ())
            if ok:
                return self._result(True, False, "✓ Controle do player acionado.", action=f"STREAMING_{action.upper()}", detail={"service": service, "method": "shortcut"})

        if action == "play_pause":
            try:
                result = self.actions.media_play_pause()
                return self._result(True, False, str(result), action="STREAMING_PLAY_PAUSE", detail={"service": service, "method": "media_key"})
            except Exception:
                pass
        return self._result(False, False, "Não consegui localizar nem acionar esse controle no player atual.", action=f"STREAMING_{action.upper()}")

    def crunchyroll_control(self, action: str, seconds: int = 0, verify_timeout: float = 3.5) -> Dict:
        """Usa atalhos oficiais do player Crunchyroll.

        O envio do atalho e verificavel como evento de input, mas skip intro/play/pause
        nao sao declarados como concluidos sem telemetria do player. Next episode tenta
        verificar pela mudanca de titulo da aba.
        """
        item, error = self._focus_opera(require_crunchyroll=True)
        if error:
            # O titulo da aba pode ser apenas o nome do episodio. Para um comando
            # explicito do Crunchyroll, ainda e seguro focar o Opera se houver uma
            # unica janela candidata ou uma janela Opera ja em primeiro plano.
            item, fallback_error = self._focus_opera(require_crunchyroll=False)
            if fallback_error:
                return self._result(False, False, error, action=f"CRUNCHYROLL_{action.upper()}")
        action = str(action or "").lower()
        before_title = str(item.get("title") or "")
        mapping = {
            "skip_intro": ("", ("s",), "pular a abertura"),
            "next": ("", ("shift", "n"), "ir para o próximo episódio"),
            "play_pause": ("k", (), "alternar reprodução"),
            "captions": ("c", (), "alternar legendas"),
            "fullscreen": ("f", (), "alternar tela cheia"),
            "mute": ("m", (), "alternar mudo"),
        }
        if action == "seek":
            seconds = int(seconds or 0)
            if not seconds:
                return self._result(True, True, "Nada para avançar.", action="CRUNCHYROLL_SEEK")
            key = "l" if seconds > 0 else "j"
            presses = max(1, min(abs(seconds) // 10 or 1, 18))
            if pyautogui is None:
                return self._result(False, False, "Automação de teclado indisponível.", action="CRUNCHYROLL_SEEK")
            try:
                pyautogui.press(key, presses=presses, interval=0.035)
            except Exception as exc:
                return self._result(False, False, f"Não consegui controlar o player: {exc}", action="CRUNCHYROLL_SEEK")
            moved = presses * 10 * (1 if seconds > 0 else -1)
            msg = f"✓ {'Avancei' if moved > 0 else 'Voltei'} {abs(moved)} segundos."
            return self._result(True, False, msg, action="CRUNCHYROLL_SEEK", detail={"seconds": moved})
        if action not in mapping:
            return self._result(False, False, "Controle do Crunchyroll desconhecido.", action="CRUNCHYROLL")
        key, hotkey, label = mapping[action]
        ok = self._press(key=key, hotkey=hotkey)
        if not ok:
            return self._result(False, False, f"Não consegui enviar o atalho para {label}.", action=f"CRUNCHYROLL_{action.upper()}")
        if action == "next":
            deadline = time.monotonic() + max(0.0, float(verify_timeout or 0.0))
            while time.monotonic() < deadline:
                try:
                    cands = self._opera_candidates()
                    current = next((x for x in cands if "crunchyroll" in self._norm(x.get("title", ""))), None)
                    after_title = str((current or {}).get("title") or "")
                    if after_title and after_title != before_title:
                        return self._result(True, True, "✓ Próximo episódio aberto e verificado pelo título da aba.", action="CRUNCHYROLL_NEXT", detail={"before_title": before_title, "after_title": after_title})
                except Exception:
                    pass
                time.sleep(0.18)
        # A plataforma nao expoe estado do player ao JARVIS; mantemos verified=False
        # internamente, mas a resposta falada deve ser curta e confiante.
        short_messages = {
            "skip_intro": "✓ Comando para pular a abertura enviado.",
            "next": "✓ Próximo episódio acionado.",
            "play_pause": "✓ Reprodução alternada.",
            "captions": "✓ Legendas alternadas.",
            "fullscreen": "✓ Tela cheia alternada.",
            "mute": "✓ Áudio alternado.",
        }
        return self._result(True, False, short_messages.get(action, f"✓ {label.capitalize()} acionado."), action=f"CRUNCHYROLL_{action.upper()}")

    def _focus_opera_for_visual_player(self) -> tuple[Optional[Dict], str]:
        """Foca o Opera sem exigir que o titulo da aba contenha Crunchyroll.

        O titulo pode ser apenas o nome do episodio. A confirmacao de que existe
        um controle do Crunchyroll vem da visao, antes de qualquer clique.
        """
        return self._focus_opera(require_crunchyroll=False)

    def smart_fullscreen(self, monitor_index: Optional[int] = None) -> Dict:
        """Alterna tela cheia usando contexto do player antes de atalhos genéricos.

        No Crunchyroll conhecido, `f` é o caminho mais rápido. Sem evidência de
        player, tenta o botão visual. F11 só é usado como fallback quando o Opera
        em primeiro plano é inequivocamente a janela alvo.
        """
        item = None
        if monitor_index is None:
            try:
                item, _ = self._focus_opera_for_visual_player()
            except Exception:
                item = None

            # Contexto operacional pode reconhecer Crunchyroll mesmo quando o
            # título da aba contém apenas o nome do episódio.
            context_key = ""
            try:
                snap = self.context.snapshot() if self.context is not None else {}
                context_key = self._norm(
                    f"{snap.get('active_site','')} {snap.get('active_title','')} {snap.get('active_app','')}"
                )
            except Exception:
                context_key = ""
            title_key = self._norm((item or {}).get("title", ""))
            if item and ("crunchyroll" in context_key or "crunchyroll" in title_key):
                if self._press(key="f"):
                    return self._result(
                        True, False, "Alternei a tela cheia do player.",
                        action="SMART_FULLSCREEN", detail={"method": "crunchyroll_f"},
                    )

        visual = self.click_visible(
            "botao visivel do player para Tela cheia, Fullscreen ou Expandir; "
            "nao clique em recomendacoes, anuncios ou controles de fechar janela",
            monitor_index=monitor_index,
        )
        if visual.get("success"):
            return self._result(
                True, False, "Cliquei no controle de tela cheia do player.",
                action="SMART_FULLSCREEN", detail=dict(visual.get("detail") or {}),
            )

        # Fora de um player reconhecido, F11 é aceitável apenas se o Opera
        # correto já estiver em foreground. Isso evita mandar teclas a outra app.
        if monitor_index is None and item and bool(item.get("foreground")):
            if self._press(key="f11"):
                return self._result(
                    True, False, "Alternei a tela cheia do Opera.",
                    action="SMART_FULLSCREEN", detail={"method": "opera_f11"},
                )

        return self._result(
            False, False, "Não encontrei um alvo seguro para tela cheia.",
            action="SMART_FULLSCREEN",
        )

    def smart_skip(self, monitor_index: Optional[int] = None) -> Dict:
        """Tenta resolver um "pula" curto pelo contexto visual do player.

        Nao envia teclas arbitrarias. Se nenhum botao de pular estiver visivel,
        devolve falha para o caller decidir um fallback de midia global.
        """
        if monitor_index is None:
            try:
                self._focus_opera_for_visual_player()
            except Exception:
                pass
        visual = self.click_visible(
            "botao visivel do player para Pular abertura, Pular introducao, Skip Intro, "
            "Pular anuncio ou Skip Ad; ignore recomendacoes, resultados e controles do navegador",
            monitor_index=monitor_index,
        )
        if visual.get("success"):
            return self._result(
                True, False, "Cliquei no controle de pular que estava visível no player.",
                action="SMART_SKIP", detail=dict(visual.get("detail") or {}),
            )
        return {
            "success": False, "verified": False,
            "message": "Não encontrei um controle de pular visível no navegador.",
            "action": "SMART_SKIP", "detail": dict(visual.get("detail") or {}), "risk": "low",
        }

    def crunchyroll_skip_intro(self, monitor_index: Optional[int] = None) -> Dict:
        # Se o usuario indicou a tela, a propria localizacao visual e a ancora.
        # Sem monitor explicito, focamos o Opera para a captura cair no lugar certo.
        if monitor_index is None:
            _item, focus_error = self._focus_opera_for_visual_player()
            if focus_error:
                # Ainda tentamos o fallback antigo, que exige titulo Crunchyroll.
                return self.crunchyroll_control("skip_intro")
        visual = self.click_visible(
            "botao visivel do player Crunchyroll para Pular abertura, Pular introducao ou Skip Intro; "
            "nao clique em anuncios, recomendacoes ou controles do navegador",
            monitor_index=monitor_index,
        )
        if visual.get("success"):
            detail = dict(visual.get("detail") or {})
            return self._result(
                True, False, "Cliquei no controle visivel para pular a abertura do Crunchyroll.",
                action="CRUNCHYROLL_SKIP_INTRO", detail=detail,
            )
        # O botao pode nao estar visivel apesar de o player aceitar o atalho.
        # Nesse caso o fallback so dispara se uma aba Crunchyroll for identificada
        # pelo Window Manager, evitando digitar 's' em uma pagina qualquer.
        return self.crunchyroll_control("skip_intro")

    def crunchyroll_next_episode(self, monitor_index: Optional[int] = None) -> Dict:
        before_title = ""
        if monitor_index is None:
            item, _error = self._focus_opera_for_visual_player()
            before_title = str((item or {}).get("title") or "")
        visual = self.click_visible(
            "botao visivel do player Crunchyroll para Proximo episodio, Next Episode ou episodio seguinte; "
            "nao clique em recomendacoes, anuncios ou outro titulo",
            monitor_index=monitor_index,
        )
        if visual.get("success"):
            deadline = time.monotonic() + 3.5
            while before_title and time.monotonic() < deadline:
                try:
                    cands = self._opera_candidates()
                    current = next((x for x in cands if x.get("foreground")), None) or (cands[0] if cands else None)
                    after_title = str((current or {}).get("title") or "")
                    if after_title and after_title != before_title:
                        return self._result(
                            True, True, "✓ Próximo episódio aberto e verificado pela mudança da aba.",
                            action="CRUNCHYROLL_NEXT",
                            detail={"before_title": before_title, "after_title": after_title},
                        )
                except Exception:
                    pass
                time.sleep(0.16)
            return self._result(
                True, False, "Cliquei no controle visível para ir ao próximo episódio do Crunchyroll.",
                action="CRUNCHYROLL_NEXT", detail=dict(visual.get("detail") or {}),
            )
        return self.crunchyroll_control("next")

    def crunchyroll_seek(self, seconds: int) -> Dict:
        return self.crunchyroll_control("seek", seconds=seconds)

    def _download_snapshot(self) -> Dict[str, tuple[int, float]]:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        result = {}
        try:
            for p in self.download_dir.iterdir():
                if p.is_file():
                    try:
                        st = p.stat(); result[p.name] = (int(st.st_size), float(st.st_mtime))
                    except OSError:
                        pass
        except Exception:
            pass
        return result

    def _new_downloads(self, before: Dict[str, tuple[int, float]]) -> list[Path]:
        found = []
        try:
            for p in self.download_dir.iterdir():
                if not p.is_file():
                    continue
                try: st = p.stat()
                except OSError: continue
                old = before.get(p.name)
                if old is None or st.st_mtime > old[1] + 0.01 or st.st_size != old[0]:
                    found.append(p)
        except Exception:
            pass
        return sorted(found, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    def click_visible(self, description: str, monitor_index: Optional[int] = None, allow_sensitive: bool = False) -> Dict:
        description = str(description or "").strip()
        if self.DANGEROUS_UI_RE.search(description) and not allow_sensitive:
            return self._result(False, False, "Esse botão parece envolver compra, credencial, instalação ou exclusão de conta. Diga o comando específico para essa etapa.", action="WEB_CLICK", risk="high")
        if not self.vision or not hasattr(self.vision, "locate_ui_target"):
            return self._result(False, False, "A visão de interface não está disponível para localizar esse elemento.", action="WEB_CLICK")
        try:
            target = self.vision.locate_ui_target(description, monitor_index=monitor_index)
        except Exception as exc:
            return self._result(False, False, f"Não consegui localizar o elemento na tela: {exc}", action="WEB_CLICK")
        if not target.get("found") or float(target.get("confidence") or 0.0) < 0.76:
            return self._result(False, False, "Não encontrei um único botão ou link visível com confiança suficiente.", action="WEB_CLICK", detail=target)
        if pyautogui is None:
            return self._result(False, False, "Automação de mouse indisponível.", action="WEB_CLICK", detail=target)
        try:
            x, y = int(target["x"]), int(target["y"])
            pyautogui.click(x=x, y=y)
            time.sleep(0.22)
            label = str(target.get("label") or description).strip()
            # Clique foi enviado ao alvo localizado, mas efeito da pagina precisa de verificacao separada.
            return self._result(True, False, f"Clique enviado em {label}.", action="WEB_CLICK", detail=target)
        except Exception as exc:
            return self._result(False, False, f"Localizei o elemento, mas não consegui clicar: {exc}", action="WEB_CLICK", detail=target)

    def open_result(self, description: str = "primeiro resultado organico da pesquisa") -> Dict:
        item, error = self._focus_opera(require_crunchyroll=False)
        if error:
            return self._result(False, False, error, action="OPEN_SEARCH_RESULT")
        before_title = str(item.get("title") or "")
        click = self.click_visible(
            f"resultado principal da pesquisa que corresponda a: {description}; ignore anuncios patrocinados, menus e a barra do navegador"
        )
        if not click.get("success"):
            click["action"] = "OPEN_SEARCH_RESULT"; return click
        deadline = time.monotonic() + 3.5
        after_title = ""
        while time.monotonic() < deadline:
            try:
                cands = self._opera_candidates()
                current = next((x for x in cands if x.get("foreground")), None) or (cands[0] if cands else None)
                after_title = str((current or {}).get("title") or "")
                if after_title and after_title != before_title:
                    return self._result(True, True, "✓ Resultado aberto e verificado pela mudança da aba.", action="OPEN_SEARCH_RESULT", detail={"before_title": before_title, "after_title": after_title})
            except Exception:
                pass
            time.sleep(0.16)
        return self._result(True, False, "Cliquei no resultado localizado, mas não consegui confirmar a navegação pela janela.", action="OPEN_SEARCH_RESULT", detail={"before_title": before_title, "after_title": after_title})

    def open_first_result(self) -> Dict:
        return self.open_result("o primeiro resultado organico")

    def open_official_result(self, subject: str = "") -> Dict:
        label = f"site oficial de {subject}" if subject else "site oficial relacionado a pesquisa atual"
        return self.open_result(label)

    def download_visible(self, expected: str = "") -> Dict:
        item, error = self._focus_opera(require_crunchyroll=False)
        if error:
            return self._result(False, False, error, action="DOWNLOAD_VISIBLE")
        before = self._download_snapshot()
        expected_clause = f" referente a {expected}" if expected else ""
        click = self.click_visible(
            "o botao ou link principal visivel para baixar/fazer download do arquivo" + expected_clause + "; ignore anuncios, banners e qualquer acao que nao seja o download do arquivo"
        )
        if not click.get("success"):
            click["action"] = "DOWNLOAD_VISIBLE"; return click
        deadline = time.monotonic() + 12.0
        candidate = None
        stable_ticks = 0
        last_size = None
        while time.monotonic() < deadline:
            files = self._new_downloads(before)
            if files:
                candidate = files[0]
                try:
                    size = candidate.stat().st_size
                    if size == last_size: stable_ticks += 1
                    else: stable_ticks = 0
                    last_size = size
                except OSError:
                    pass
                # arquivo final ou temporario ja prova que download iniciou.
                if candidate.suffix.lower() in {".crdownload", ".part", ".tmp"} or stable_ticks >= 2:
                    break
            time.sleep(0.25)
        if not candidate:
            return self._result(False, False, "Cliquei no download, mas nenhum arquivo novo apareceu em Downloads para verificar.", action="DOWNLOAD_VISIBLE")
        suffix = candidate.suffix.lower()
        in_progress = suffix in {".crdownload", ".part", ".tmp"}
        executable = suffix in self.EXECUTABLE_EXTENSIONS
        if in_progress:
            msg = f"✓ Download iniciado e verificado em Downloads: {candidate.name}."
        else:
            msg = f"✓ Arquivo novo verificado em Downloads: {candidate.name}."
        if executable:
            msg += " É um executável/instalador; o JARVIS não vai abri-lo automaticamente."
        return self._result(True, True, msg, action="DOWNLOAD_VISIBLE", detail={"path": str(candidate), "in_progress": in_progress, "executable": executable}, risk="medium" if executable else "low")
