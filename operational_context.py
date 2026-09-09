"""JARVIS - contexto operacional V2 e persistencia leve.

Mantem apenas metadados operacionais: app/site/monitor/player/eventos e preferencias.
Nunca persiste captura de tela, audio bruto ou teclas.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from autonomy_policy import (
        make_policy, snap_percent, LEGACY_AUTONOMY, LEGACY_PRESENCE,
        percent_from_legacy_autonomy, percent_from_legacy_presence,
    )
except Exception:
    make_policy = None
    snap_percent = lambda value, default=60: max(20, min(100, int(value or default)))
    LEGACY_AUTONOMY = {20: "manual", 40: "assistido", 60: "assistido", 80: "autonomo", 100: "autonomo"}
    LEGACY_PRESENCE = {20: "discreto", 40: "assistente", 60: "assistente", 80: "jarvis", 100: "jarvis"}
    percent_from_legacy_autonomy = lambda level, default=60: {"manual":20,"assistido":60,"autonomo":80}.get(str(level or "").lower(), default)
    percent_from_legacy_presence = lambda level, default=60: {"discreto":20,"assistente":60,"jarvis":80}.get(str(level or "").lower(), default)


class OperationalContext:
    VERSION = 3

    def __init__(self, project_dir: str | os.PathLike, logger=None, max_events: int = 60):
        self.project_dir = Path(project_dir)
        self.logger = logger
        self.path = self.project_dir / "data" / "operational_context.json"
        self._lock = threading.RLock()
        self._events = deque(maxlen=max(20, int(max_events)))
        self._state: Dict[str, Any] = {
            "active_title": "", "active_app": "", "active_site": "", "active_monitor": None,
            "last_download": "", "last_action": "", "last_action_verified": False,
            "current_goal": "", "goal_status": "idle", "goal_step": "", "goal_progress": 0.0,
            "interaction_mode": "auto", "presence_level": "assistente", "autonomy_level": "assistido",
            "presence_percent": 60, "autonomy_percent": 60,
            "auto_skip_intro": False, "auto_next_episode": False,
            "player_profiles": {},
            "media": {},
            "updated_at": time.time(),
        }
        self._load_preferences()

    def _log(self, level: str, message: str):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try: fn(message, "CONTEXT")
                except TypeError: fn(message)
        except Exception:
            pass

    @staticmethod
    def _site_from_title(title: str) -> str:
        t = str(title or "").lower()
        known = (
            ("crunchyroll", "Crunchyroll"), ("netflix", "Netflix"), ("prime video", "Prime Video"),
            ("amazon prime", "Prime Video"), ("disney+", "Disney+"), ("disney plus", "Disney+"),
            ("hbo max", "Max"), ("hbomax", "Max"), ("globoplay", "Globoplay"),
            ("paramount+", "Paramount+"), ("paramount plus", "Paramount+"), ("apple tv", "Apple TV"),
            ("twitch", "Twitch"), ("youtube", "YouTube"), ("mercado livre", "Mercado Livre"),
            ("github", "GitHub"), ("chatgpt", "ChatGPT"), ("spotify", "Spotify"), ("google", "Google"),
            ("plex", "Plex"), ("jellyfin", "Jellyfin"), ("stremio", "Stremio"),
        )
        for needle, label in known:
            if needle in t:
                return label
        return ""

    @staticmethod
    def _app_from_item(item: Optional[Dict[str, Any]]) -> str:
        if not item:
            return ""
        proc = str(item.get("process_name") or "").lower()
        title = str(item.get("title") or "")
        aliases = {
            "opera.exe": "Opera", "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox",
            "brave.exe": "Brave", "discord.exe": "Discord", "spotify.exe": "Spotify", "steam.exe": "Steam",
            "obs64.exe": "OBS", "photoshop.exe": "Photoshop", "explorer.exe": "Explorador", "vlc.exe": "VLC",
        }
        if proc in aliases:
            return aliases[proc]
        stem = Path(proc).stem.strip() if proc else ""
        return (stem or title.split(" - ")[-1].strip())[:48]

    def _load_preferences(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            prefs = data.get("preferences") or {}
            for key in ("presence_level", "autonomy_level"):
                if prefs.get(key):
                    self._state[key] = str(prefs[key])
            if "presence_percent" in prefs:
                self._state["presence_percent"] = snap_percent(prefs.get("presence_percent", 60))
            else:
                self._state["presence_percent"] = percent_from_legacy_presence(self._state.get("presence_level"), 60)
            if "autonomy_percent" in prefs:
                self._state["autonomy_percent"] = snap_percent(prefs.get("autonomy_percent", 60))
            else:
                self._state["autonomy_percent"] = percent_from_legacy_autonomy(self._state.get("autonomy_level"), 60)
            self._state["presence_level"] = LEGACY_PRESENCE[snap_percent(self._state["presence_percent"])]
            self._state["autonomy_level"] = LEGACY_AUTONOMY[snap_percent(self._state["autonomy_percent"])]
            for key in ("auto_skip_intro", "auto_next_episode"):
                if key in prefs:
                    self._state[key] = bool(prefs[key])
            profiles = prefs.get("player_profiles")
            if isinstance(profiles, dict):
                self._state["player_profiles"] = profiles
        except Exception:
            pass

    def _save_preferences(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": self.VERSION,
                "preferences": {
                    "presence_level": self._state.get("presence_level", "assistente"),
                    "autonomy_level": self._state.get("autonomy_level", "assistido"),
                    "presence_percent": int(self._state.get("presence_percent", 60)),
                    "autonomy_percent": int(self._state.get("autonomy_percent", 60)),
                    "auto_skip_intro": bool(self._state.get("auto_skip_intro", False)),
                    "auto_next_episode": bool(self._state.get("auto_next_episode", False)),
                    "player_profiles": dict(self._state.get("player_profiles") or {}),
                },
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception as exc:
            self._log("warning", f"Nao consegui persistir preferencias operacionais: {exc}")

    def refresh_from_windows(self, windows=None) -> Dict[str, Any]:
        if windows is None:
            return self.snapshot()
        item = None
        try:
            getter = getattr(windows, "_foreground_item", None)
            if callable(getter):
                item = getter()
            if not item:
                item = {"title": windows.active_window_title()}
        except Exception:
            item = None
        if item:
            title = str(item.get("title") or "")
            app = self._app_from_item(item)
            site = self._site_from_title(title)
            monitor = item.get("monitor")
            if monitor is None:
                try:
                    inspect = windows.inspect_window(title) if title else None
                    monitor = (inspect or {}).get("monitor")
                except Exception:
                    monitor = None
            with self._lock:
                changed = title != self._state.get("active_title")
                self._state.update(active_title=title, active_app=app, active_site=site, active_monitor=monitor, updated_at=time.time())
                if changed and title:
                    self._events.appendleft({"ts": time.time(), "kind": "window", "text": title[:180], "app": app, "site": site, "monitor": monitor, "verified": True})
        return self.snapshot()

    def set_mode(self, mode: str):
        with self._lock:
            self._state["interaction_mode"] = str(mode or "auto")
            self._state["updated_at"] = time.time()

    def set_presence_percent(self, value: int):
        percent = snap_percent(value)
        with self._lock:
            self._state["presence_percent"] = percent
            self._state["presence_level"] = LEGACY_PRESENCE[percent]
            self._state["updated_at"] = time.time()
        self._save_preferences()
        return percent

    def set_autonomy_percent(self, value: int):
        percent = snap_percent(value)
        with self._lock:
            self._state["autonomy_percent"] = percent
            self._state["autonomy_level"] = LEGACY_AUTONOMY[percent]
            self._state["updated_at"] = time.time()
        self._save_preferences()
        return percent

    def set_presence(self, level: str):
        level = str(level or "assistente").strip().lower()
        if level not in {"discreto", "assistente", "jarvis"}:
            raise ValueError("nivel de presenca invalido")
        percent = percent_from_legacy_presence(level, 60)
        with self._lock:
            self._state["presence_level"] = level
            self._state["presence_percent"] = percent
            self._state["updated_at"] = time.time()
        self._save_preferences()

    def set_autonomy(self, level: str):
        level = str(level or "assistido").strip().lower()
        if level not in {"manual", "assistido", "autonomo"}:
            raise ValueError("nivel de autonomia invalido")
        percent = percent_from_legacy_autonomy(level, 60)
        with self._lock:
            self._state["autonomy_level"] = level
            self._state["autonomy_percent"] = percent
            self._state["updated_at"] = time.time()
        self._save_preferences()

    def behavior_policy(self):
        with self._lock:
            autonomy = int(self._state.get("autonomy_percent", 60))
            presence = int(self._state.get("presence_percent", 60))
        return make_policy(autonomy, presence) if make_policy else None

    def set_player_automation(self, kind: str, enabled: bool, service: str = ""):
        kind = str(kind or "").strip().lower()
        mapping = {"skip": "skip_intro", "intro": "skip_intro", "next": "next_episode", "episode": "next_episode"}
        canonical = mapping.get(kind)
        if not canonical:
            raise ValueError("automacao de player invalida")
        service = " ".join(str(service or "").split()).strip().lower()
        with self._lock:
            if service:
                profiles = self._state.setdefault("player_profiles", {})
                row = dict(profiles.get(service) or {})
                row[canonical] = bool(enabled)
                profiles[service] = row
            else:
                self._state["auto_skip_intro" if canonical == "skip_intro" else "auto_next_episode"] = bool(enabled)
            self._state["updated_at"] = time.time()
        self._save_preferences()

    def player_automation(self, service: str = "") -> Dict[str, bool]:
        service = " ".join(str(service or "").split()).strip().lower()
        with self._lock:
            result = {
                "skip_intro": bool(self._state.get("auto_skip_intro", False)),
                "next_episode": bool(self._state.get("auto_next_episode", False)),
            }
            if service:
                row = dict((self._state.get("player_profiles") or {}).get(service) or {})
                for key in ("skip_intro", "next_episode"):
                    if key in row:
                        result[key] = bool(row[key])
            return result

    def set_media_context(self, media: Dict[str, Any]):
        safe = {}
        for key in ("player", "service", "title", "item", "artist", "kind", "monitor", "foreground", "confidence", "source"):
            if key in (media or {}):
                safe[key] = media.get(key)
        safe["updated_at"] = time.time()
        with self._lock:
            self._state["media"] = safe
            self._state["updated_at"] = time.time()

    def media_context(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state.get("media") or {})

    def set_goal(self, goal: str, status: str = "planning", step: str = "", progress: float = 0.0):
        with self._lock:
            self._state.update(current_goal=str(goal or "")[:400], goal_status=str(status or "idle"), goal_step=str(step or "")[:220], goal_progress=max(0.0, min(float(progress or 0.0), 1.0)), updated_at=time.time())

    def clear_goal(self, status: str = "idle"):
        with self._lock:
            self._state.update(current_goal="", goal_status=status, goal_step="", goal_progress=0.0, updated_at=time.time())

    def record_action(self, action: str, message: str = "", verified: bool = False, detail: Optional[Dict[str, Any]] = None):
        event = {"ts": time.time(), "kind": "action", "action": str(action or "")[:80], "text": str(message or action or "")[:260], "verified": bool(verified)}
        if detail:
            event["detail"] = {k: v for k, v in detail.items() if k in {"target", "monitor", "path", "site", "service", "method"}}
        with self._lock:
            self._state["last_action"] = event["text"]
            self._state["last_action_verified"] = bool(verified)
            self._state["updated_at"] = time.time()
            self._events.appendleft(event)

    def record_download(self, path: str, verified: bool = True):
        path = str(path or "")
        if not path:
            return
        with self._lock:
            self._state["last_download"] = path
            self._state["updated_at"] = time.time()
            self._events.appendleft({"ts": time.time(), "kind": "download", "text": path[:260], "verified": bool(verified)})

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            data = dict(self._state)
            data["media"] = dict(self._state.get("media") or {})
            data["events"] = list(self._events)[:10]
            return data

    def compact_text(self) -> str:
        s = self.snapshot()
        bits = []
        if s.get("active_app"): bits.append(f"app={s['active_app']}")
        if s.get("active_site"): bits.append(f"site={s['active_site']}")
        if s.get("active_monitor"): bits.append(f"monitor={s['active_monitor']}")
        media = s.get("media") or {}
        if media.get("service"): bits.append(f"player={media.get('service')}")
        if media.get("item"): bits.append(f"midia={str(media.get('item'))[:80]}")
        if s.get("interaction_mode"): bits.append(f"modo={s['interaction_mode']}")
        bits.append(f"autonomia={int(s.get('autonomy_percent', 60))}%")
        bits.append(f"presenca={int(s.get('presence_percent', 60))}%")
        if s.get("last_download"): bits.append(f"ultimo_download={Path(s['last_download']).name}")
        return " | ".join(bits) if bits else "sem contexto operacional verificado"
