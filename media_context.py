"""JARVIS - Media Context Engine V2.

Unifica Spotify, players desktop e streaming em navegador sem capturar audio bruto.
Mantem apenas metadados de janelas/player e nunca declara uma acao como concluida
quando so conseguiu enviar uma tecla/comando.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass
class MediaSnapshot:
    player: str = ""
    service: str = ""
    title: str = ""
    item: str = ""
    artist: str = ""
    kind: str = ""
    monitor: Optional[int] = None
    foreground: bool = False
    confidence: float = 0.0
    source: str = "window"
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MediaContextEngine:
    TTL = 180.0
    VIDEO_SERVICES = {
        "crunchyroll", "youtube", "netflix", "prime video", "disney+", "max",
        "globoplay", "paramount+", "apple tv", "twitch", "plex", "jellyfin",
        "stremio", "kodi", "mubi", "claro tv+",
    }
    SERVICE_ALIASES = {
        "crunchyroll": ("crunchyroll", "crunchy roll"),
        "youtube": ("youtube", "youtu be"),
        "netflix": ("netflix",),
        "prime video": ("prime video", "amazon prime", "primevideo"),
        "disney+": ("disney+", "disney plus", "disneyplus"),
        "max": ("hbo max", "hbomax", "max"),
        "globoplay": ("globoplay", "globo play"),
        "paramount+": ("paramount+", "paramount plus", "paramountplus"),
        "apple tv": ("apple tv", "tv.apple"),
        "twitch": ("twitch",),
        "plex": ("plex",),
        "jellyfin": ("jellyfin",),
        "stremio": ("stremio",),
        "kodi": ("kodi",),
        "mubi": ("mubi",),
        "claro tv+": ("claro tv", "clarotv"),
        "spotify": ("spotify",),
        "vlc": ("vlc", "vlc media player"),
    }

    def __init__(self, actions, window_manager=None, browser_autonomy=None, operational_context=None, logger=None):
        self.actions = actions
        self.window_manager = window_manager
        self.browser = browser_autonomy
        self.operational_context = operational_context
        self.logger = logger
        self._lock = threading.RLock()
        self._last = MediaSnapshot(updated_at=0.0)
        self._preferred_target = ""
        self._preferred_until = 0.0

    @staticmethod
    def _norm(text: str) -> str:
        value = unicodedata.normalize("NFKD", str(text or ""))
        value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
        value = re.sub(r"[^a-z0-9+ ]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def _log(self, level: str, message: str):
        try:
            fn = getattr(self.logger, level, None) if self.logger else None
            if callable(fn):
                try:
                    fn(message, "MEDIA_CONTEXT")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    @classmethod
    def canonical_target(cls, text: str) -> str:
        key = cls._norm(text)
        if not key:
            return ""
        for service, aliases in cls.SERVICE_ALIASES.items():
            if any(cls._norm(alias) in key for alias in aliases):
                return service
        return key[:80]

    def set_preferred_target(self, target: str, ttl: float = 240.0) -> str:
        target = self.canonical_target(target)
        with self._lock:
            self._preferred_target = target
            self._preferred_until = time.monotonic() + max(15.0, float(ttl)) if target else 0.0
        return target

    def preferred_target(self) -> str:
        with self._lock:
            if self._preferred_target and time.monotonic() <= self._preferred_until:
                return self._preferred_target
            self._preferred_target = ""
            self._preferred_until = 0.0
            return ""

    def _windows(self):
        try:
            return list(self.window_manager.list_windows() or []) if self.window_manager else []
        except Exception:
            return []

    @classmethod
    def _service_from_window(cls, item: Dict[str, Any]) -> str:
        hay = cls._norm(f"{item.get('title','')} {item.get('process_name','')}")
        for service, aliases in cls.SERVICE_ALIASES.items():
            if any(cls._norm(alias) in hay for alias in aliases):
                return service
        return ""

    @staticmethod
    def _clean_window_title(title: str, service: str) -> str:
        title = " ".join(str(title or "").split()).strip()
        if not title:
            return ""
        # Remove sufixos de navegador/app, preservando o conteudo principal.
        suffixes = [
            " - Opera", " - Opera GX", " — Opera", " - Google Chrome", " - Microsoft Edge",
            " - Mozilla Firefox", " - VLC media player", " - Spotify",
        ]
        for suffix in suffixes:
            if title.lower().endswith(suffix.lower()):
                title = title[:-len(suffix)].strip()
        generic = {
            "spotify": ("spotify", "spotify premium", "spotify – web player: música para todas as pessoas", "spotify - web player"),
            "youtube": ("youtube",),
        }
        if title.lower() in {x.lower() for x in generic.get(service, ())}:
            return ""
        return title[:220]

    def refresh(self, force: bool = False) -> MediaSnapshot:
        now = time.time()
        with self._lock:
            if not force and self._last.updated_at and now - self._last.updated_at < 0.45:
                return MediaSnapshot(**self._last.to_dict())

        windows = self._windows()
        candidates = []
        for item in windows:
            service = self._service_from_window(item)
            if not service:
                continue
            title = str(item.get("title") or "")
            foreground = bool(item.get("foreground"))
            score = 1.0 + (2.0 if foreground else 0.0)
            if service in {"spotify", "vlc"}:
                score += 1.1
            if service in self.VIDEO_SERVICES:
                score += 0.6
            if title:
                score += 0.2
            candidates.append((score, service, item))

        if not candidates:
            snap = MediaSnapshot(updated_at=now)
        else:
            candidates.sort(key=lambda row: row[0], reverse=True)
            score, service, item = candidates[0]
            title = self._clean_window_title(str(item.get("title") or ""), service)
            player = "Spotify" if service == "spotify" else "VLC" if service == "vlc" else service
            kind = "music" if service in {"spotify", "vlc"} else "video"
            monitor = item.get("monitor")
            try:
                monitor = int(monitor) if monitor else None
            except Exception:
                monitor = None
            snap = MediaSnapshot(
                player=player,
                service=service,
                title=str(item.get("title") or "")[:260],
                item=title,
                kind=kind,
                monitor=monitor,
                foreground=bool(item.get("foreground")),
                confidence=min(0.98, 0.55 + score * 0.10),
                source="window",
                updated_at=now,
            )
        with self._lock:
            self._last = snap
        try:
            if self.operational_context is not None:
                self.operational_context.set_media_context(snap.to_dict())
        except Exception:
            pass
        return MediaSnapshot(**snap.to_dict())

    def current(self) -> Dict[str, Any]:
        return self.refresh().to_dict()

    def describe(self) -> str:
        snap = self.refresh(force=True)
        if not snap.service:
            return "Não identifiquei um player de mídia ativo com segurança agora."
        if snap.item:
            label = snap.player or snap.service
            return f"O player ativo é {label}. A janela indica: {snap.item}."
        label = snap.player or snap.service
        return f"Identifiquei {label} como player ativo, mas o título atual não informa a faixa ou episódio com segurança."

    @staticmethod
    def _changed(before: MediaSnapshot, after: MediaSnapshot, action: str) -> bool:
        if action in {"next", "previous"}:
            return bool(before.item and after.item and before.item != after.item)
        if action == "seek":
            return before.service == after.service and bool(after.service)
        return False

    def control(self, action: str, target_hint: str = "", seconds: int = 0) -> Dict[str, Any]:
        action = str(action or "").strip().lower()
        action = {"pause": "pause", "play": "play", "toggle": "toggle", "next_track": "next", "prev": "previous"}.get(action, action)
        before = self.refresh(force=True)
        explicit = self.canonical_target(target_hint)
        target = explicit or self.preferred_target() or before.service
        if target:
            self.set_preferred_target(target)

        success = False
        verified = False
        message = ""
        method = ""

        try:
            # Streaming/video: usa contexto + visao/atalho conservador.
            if target in self.VIDEO_SERVICES and self.browser is not None:
                stream_action = {"pause": "play_pause", "play": "play_pause", "toggle": "play_pause", "next": "next", "previous": "previous", "seek": "seek"}.get(action, action)
                if stream_action == "previous":
                    result = {"success": False, "verified": False, "message": "O player atual não tem um comando universal seguro para episódio anterior."}
                else:
                    result = self.browser.streaming_control(stream_action, seconds=int(seconds or 0), service_hint=target)
                success = bool(result.get("success"))
                verified = bool(result.get("verified"))
                message = str(result.get("message") or "")
                method = str((result.get("detail") or {}).get("method") or "stream")
            else:
                hint = target if target in {"spotify", "vlc"} else None
                handlers = {
                    "pause": self.actions.media_pause,
                    "play": self.actions.media_play,
                    "toggle": self.actions.media_play_pause,
                    "next": self.actions.media_next_track,
                    "previous": self.actions.media_previous_track,
                    "stop": self.actions.media_stop,
                }
                fn = handlers.get(action)
                if fn is None:
                    return {"success": False, "verified": False, "message": "Comando de mídia desconhecido.", "target": target}
                message = str(fn(target_hint=hint))
                failure = self._norm(message)
                success = not any(x in failure for x in ("nao consegui", "erro", "indisponivel", "falhou"))
                method = "targeted" if hint else "global-media"
        except Exception as exc:
            self._log("warning", f"controle de mídia falhou: {exc}")
            return {"success": False, "verified": False, "message": f"Não consegui controlar a mídia: {exc}", "target": target}

        if success:
            time.sleep(0.18 if action not in {"next", "previous"} else 0.45)
            after = self.refresh(force=True)
            verified = bool(verified or self._changed(before, after, action))
            if verified:
                label = after.player or after.service or target or "player"
                if action == "next":
                    message = f"✓ Próxima mídia confirmada no {label}."
                elif action == "previous":
                    message = f"✓ Mídia anterior confirmada no {label}."
                elif action == "seek":
                    message = message or f"✓ Navegação no {label} confirmada."
            elif not message:
                message = "Comando enviado ao player, mas ainda não consegui confirmar a mudança de estado."
            elif message.startswith("✓"):
                message = message.lstrip("✓ ") + " Não consegui confirmar o estado do player ainda."

        return {
            "success": bool(success),
            "verified": bool(verified),
            "message": message,
            "target": target,
            "method": method,
            "before": before.to_dict(),
            "after": self.refresh().to_dict(),
        }


__all__ = ["MediaContextEngine", "MediaSnapshot"]
