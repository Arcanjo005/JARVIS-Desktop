from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional


@dataclass
class ContextRef:
    value: Any
    updated_at: float
    verified: bool = True
    confidence: float = 1.0
    ttl: float = 300.0
    source: str = "action"
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionRef:
    action: str
    target: str
    created_at: float
    verified: bool
    before: Dict[str, Any] = field(default_factory=dict)
    after: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)


class ContextEngine:
    VERSION = 3

    """Context Engine V3.

    Mantem referencias curtas de app/monitor/site/midia/topico sem confundir observacao
    com acao executada. V3 separa o fio operacional do fio conversacional e mantem
    uma pilha curta de referentes para resolver ele/ela/isso/o outro sem chutar.
    """

    TTL = 300.0
    TTL_BY_KIND = {
        "app": 300.0,
        "monitor": 300.0,
        "site": 180.0,
        "media": 180.0,
        "topic": 420.0,
        "object": 180.0,
        "result": 120.0,
        "conversation_subject": 420.0,
    }

    def __init__(self, ttl: float | None = None):
        self.ttl = float(ttl or self.TTL)
        self._lock = threading.RLock()
        self._entities: Dict[str, ContextRef] = {}
        self._actions: Deque[ActionRef] = deque(maxlen=64)
        self._last_feedback = ""
        self._pending: Dict[str, ContextRef] = {}
        self._referents: Deque[Dict[str, Any]] = deque(maxlen=24)

    def reset(self) -> None:
        with self._lock:
            self._entities.clear()
            self._actions.clear()
            self._last_feedback = ""
            self._pending.clear()
            self._referents.clear()

    def remember(
        self,
        kind: str,
        value: Any,
        *,
        verified: bool = True,
        confidence: float = 1.0,
        ttl: Optional[float] = None,
        source: str = "action",
        **meta,
    ) -> None:
        if value is None or value == "":
            return
        key = str(kind or "").strip()
        if not key:
            return
        life = float(ttl if ttl is not None else self.TTL_BY_KIND.get(key, self.ttl))
        ref = ContextRef(
            value=value,
            updated_at=time.monotonic(),
            verified=bool(verified),
            confidence=max(0.0, min(float(confidence), 1.0)),
            ttl=max(5.0, life),
            source=str(source or "unknown")[:32],
            meta=dict(meta),
        )
        with self._lock:
            old = self._entities.get(key)
            # Não substitui uma ação verificada recente por observação fraca.
            if old and old.verified and old.source == "action" and not ref.verified:
                age = time.monotonic() - old.updated_at
                if age < min(45.0, old.ttl) and ref.confidence < 0.95:
                    return
            self._entities[key] = ref
            if key in {"app", "site", "object", "topic", "conversation_subject"} and (ref.verified or ref.source == "conversation"):
                self._push_referent(key, value, ref.confidence, ref.source, verified=ref.verified)

    def _push_referent(self, kind: str, value: Any, confidence: float = 1.0, source: str = "action", verified: bool = True) -> None:
        text = str(value or "").strip()
        if not text:
            return
        now = time.monotonic()
        with self._lock:
            # Evita inundar a pilha com o mesmo alvo repetido em sequencia.
            if self._referents and str(self._referents[-1].get("value") or "").lower() == text.lower() and self._referents[-1].get("kind") == kind:
                self._referents[-1].update(ts=now, confidence=float(confidence), source=source, verified=bool(verified))
                return
            self._referents.append({
                "kind": str(kind), "value": text[:240], "confidence": max(0.0, min(float(confidence), 1.0)),
                "source": str(source or "unknown")[:32], "verified": bool(verified), "ts": now,
            })

    def _ref(self, kind: str, *, min_confidence: float = 0.0, allow_observed: bool = True) -> Optional[ContextRef]:
        key = str(kind or "").strip()
        with self._lock:
            ref = self._entities.get(key)
            if not ref:
                return None
            if time.monotonic() - ref.updated_at > ref.ttl:
                self._entities.pop(key, None)
                return None
            if ref.confidence < float(min_confidence):
                return None
            if not allow_observed and not ref.verified:
                return None
            return ref

    def get(self, kind: str, default=None, *, min_confidence: float = 0.0, allow_observed: bool = True):
        ref = self._ref(kind, min_confidence=min_confidence, allow_observed=allow_observed)
        return ref.value if ref is not None else default

    def remember_app(self, app: Optional[str], *, verified: bool = True, source: str = "action", confidence: float = 1.0) -> None:
        if app:
            self.remember("app", str(app), verified=verified, source=source, confidence=confidence)

    def remember_monitor(self, monitor: Optional[int], *, verified: bool = True, source: str = "action", confidence: float = 1.0) -> None:
        if monitor:
            self.remember("monitor", int(monitor), verified=verified, source=source, confidence=confidence)

    def remember_site(self, site: Optional[str], *, verified: bool = False, confidence: float = 0.9) -> None:
        if site:
            self.remember("site", str(site), verified=verified, source="observer", confidence=confidence)

    def remember_media(self, media: Any, *, verified: bool = False, confidence: float = 0.85) -> None:
        if media:
            self.remember("media", media, verified=verified, source="media", confidence=confidence)

    def remember_topic(self, topic: str, *, confidence: float = 0.8) -> None:
        topic = " ".join(str(topic or "").split()).strip()
        if topic:
            self.remember("topic", topic[:220], verified=True, source="conversation", confidence=confidence)
            self.remember("conversation_subject", topic[:220], verified=True, source="conversation", confidence=confidence, ttl=420.0)

    def remember_conversation_subject(self, subject: str, *, kind: str = "conversation_subject", confidence: float = 0.9) -> None:
        subject = " ".join(str(subject or "").split()).strip()
        if subject:
            self.remember(kind or "conversation_subject", subject[:240], verified=True, source="conversation", confidence=confidence, ttl=420.0)

    def observe_active(self, app: str = "", monitor: Optional[int] = None, site: str = "", title: str = "") -> None:
        if app:
            self.remember_app(app, verified=False, source="observer", confidence=0.86)
        if monitor:
            self.remember_monitor(monitor, verified=False, source="observer", confidence=0.9)
        if site:
            self.remember_site(site, verified=False, confidence=0.9)
        if title:
            self.remember("object", str(title)[:220], verified=False, source="observer", confidence=0.75, ttl=90.0)

    def current_app(self) -> Optional[str]:
        value = self.get("app", min_confidence=0.70)
        return str(value) if value else None

    def current_monitor(self) -> Optional[int]:
        value = self.get("monitor", min_confidence=0.70)
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def current_site(self) -> Optional[str]:
        value = self.get("site", min_confidence=0.65)
        return str(value) if value else None

    def current_topic(self) -> Optional[str]:
        value = self.get("topic", min_confidence=0.55)
        return str(value) if value else None

    def record_action(
        self,
        action: str,
        target: str = "",
        *,
        verified: bool = True,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        **meta,
    ) -> None:
        if not verified:
            return
        action = str(action or "").upper().strip()
        target = str(target or "").strip()
        if not action:
            return
        with self._lock:
            self._actions.append(
                ActionRef(
                    action=action,
                    target=target,
                    created_at=time.monotonic(),
                    verified=True,
                    before=dict(before or {}),
                    after=dict(after or {}),
                    meta=dict(meta),
                )
            )
        if target and action in {
            "OPEN_APP", "MINIMIZE_WINDOW", "MAXIMIZE_WINDOW", "RESTORE_WINDOW",
            "MOVE_WINDOW", "MOVE_OTHER", "BROWSER_SEARCH", "OPEN_SITE_IN_APP",
        }:
            self.remember_app(target, verified=True, source="action", confidence=1.0)
        monitor = (after or {}).get("monitor")
        if monitor:
            self.remember_monitor(int(monitor), verified=True, source="action", confidence=1.0)
        site = (after or {}).get("site") or meta.get("site")
        if site:
            self.remember_site(str(site), verified=True, confidence=1.0)
        self.remember("result", {"action": action, "target": target, "after": dict(after or {})}, verified=True, source="action", confidence=1.0, ttl=120.0)

    def last_action(self) -> Optional[ActionRef]:
        with self._lock:
            return self._actions[-1] if self._actions else None

    def last_target(self, allowed_actions: Optional[set[str]] = None) -> Optional[str]:
        with self._lock:
            for ref in reversed(self._actions):
                if not ref.target:
                    continue
                if allowed_actions and ref.action not in allowed_actions:
                    continue
                if time.monotonic() - ref.created_at <= self.ttl:
                    return ref.target
        return self.current_app()

    def previous_target(self, exclude: str = "") -> Optional[str]:
        exclude_key = str(exclude or "").strip().lower()
        seen = set()
        with self._lock:
            for ref in reversed(self._actions):
                target = str(ref.target or "").strip()
                if not target or time.monotonic() - ref.created_at > self.ttl:
                    continue
                key = target.lower()
                if key in seen:
                    continue
                seen.add(key)
                if exclude_key and key == exclude_key:
                    continue
                return target
        return None

    def resolve_reference(self, token: str, *, domain: str = "auto", exclude: str = "") -> Optional[Dict[str, Any]]:
        """Resolve referencias curtas sem escolher uma janela aleatoria.

        domain=app exige alvo operacional verificado. domain=conversation prefere o
        assunto conversacional. "o outro" devolve o alvo operacional distinto anterior.
        """
        key = " ".join(str(token or "").lower().split()).strip()
        domain = str(domain or "auto").lower()
        exclude_key = str(exclude or "").strip().lower()
        other = key in {"outro", "outra", "o outro", "a outra", "aquele outro", "aquela outra"}
        app_pronoun = key in {"ele", "ela", "isso", "isto", "esse", "essa", "esta janela", "essa janela", "aquele", "aquela"}
        conv_pronoun = key in {"isso", "isto", "esse", "essa", "ele", "ela", "esse assunto", "essa ideia", "aquilo"}

        if domain in {"app", "operational", "auto"} and (other or app_pronoun):
            if other:
                value = self.previous_target(exclude=exclude_key)
            else:
                value = self.last_target()
            if value and str(value).lower() != exclude_key:
                return {"kind": "app", "value": value, "confidence": 1.0, "source": "verified_action"}
            if domain != "auto":
                return None

        if domain in {"conversation", "auto"} and conv_pronoun:
            for kind in ("conversation_subject", "topic", "object"):
                ref = self._ref(kind, min_confidence=0.60)
                if ref and str(ref.value).lower() != exclude_key:
                    return {"kind": kind, "value": ref.value, "confidence": ref.confidence, "source": ref.source}

        # Fallback controlado para um referente recente e verificado.
        with self._lock:
            now = time.monotonic()
            for row in reversed(self._referents):
                if now - float(row.get("ts", 0.0)) > self.ttl:
                    continue
                if exclude_key and str(row.get("value") or "").lower() == exclude_key:
                    continue
                if domain in {"app", "operational"} and row.get("kind") != "app":
                    continue
                if domain == "conversation" and row.get("kind") not in {"topic", "conversation_subject", "object"}:
                    continue
                if float(row.get("confidence", 0.0)) < 0.70:
                    continue
                return dict(row)
        return None

    def reference_snapshot(self, limit: int = 8):
        with self._lock:
            now = time.monotonic()
            rows = [dict(x) for x in self._referents if now - float(x.get("ts", 0.0)) <= self.ttl]
        return rows[-max(1, min(int(limit), 24)):]

    def undo_command(self) -> Optional[str]:
        with self._lock:
            for ref in reversed(self._actions):
                target = ref.target
                if not target:
                    continue
                if ref.action in {"MOVE_WINDOW", "MOVE_OTHER"}:
                    monitor = ref.before.get("monitor")
                    if monitor:
                        return f"move {target} para monitor {int(monitor)}"
                elif ref.action == "MINIMIZE_WINDOW":
                    return f"restaura {target}"
                elif ref.action == "MAXIMIZE_WINDOW":
                    state = str(ref.before.get("state") or "normal")
                    return f"minimiza {target}" if state == "minimized" else f"restaura {target}"
                elif ref.action == "RESTORE_WINDOW":
                    state = str(ref.before.get("state") or "")
                    if state == "maximized":
                        return f"maximiza {target}"
                    if state == "minimized":
                        return f"minimiza {target}"
            return None

    def set_pending(self, kind: str, value: Any = "", *, ttl: float = 45.0, **meta) -> None:
        key = str(kind or "").strip()
        if not key:
            return
        payload = dict(meta)
        life = max(5.0, float(ttl or 45.0))
        with self._lock:
            self._pending[key] = ContextRef(value, time.monotonic(), True, 1.0, life, "dialog", payload)

    def pending(self, kind: str):
        key = str(kind or "").strip()
        with self._lock:
            ref = self._pending.get(key)
            if not ref:
                return None
            if time.monotonic() - ref.updated_at > ref.ttl:
                self._pending.pop(key, None)
                return None
            return {"value": ref.value, **dict(ref.meta)}

    def clear_pending(self, kind: Optional[str] = None) -> None:
        with self._lock:
            if kind is None:
                self._pending.clear()
            else:
                self._pending.pop(str(kind), None)

    def pending_kinds(self):
        with self._lock:
            now = time.monotonic()
            active = []
            for key, ref in list(self._pending.items()):
                if now - ref.updated_at > ref.ttl:
                    self._pending.pop(key, None)
                else:
                    active.append(key)
            return tuple(active)

    def mark_feedback(self, text: str) -> None:
        with self._lock:
            self._last_feedback = str(text or "")[:500]

    def status(self) -> Dict[str, Any]:
        with self._lock:
            entities = {}
            for key in list(self._entities):
                ref = self._ref(key)
                if ref:
                    entities[key] = {
                        "value": ref.value,
                        "confidence": round(ref.confidence, 2),
                        "source": ref.source,
                        "verified": ref.verified,
                    }
            return {
                "app": self.current_app(),
                "monitor": self.current_monitor(),
                "site": self.current_site(),
                "topic": self.current_topic(),
                "media": self.get("media"),
                "actions": len(self._actions),
                "last_action": self._actions[-1].action if self._actions else "",
                "last_feedback": self._last_feedback,
                "pending": list(self.pending_kinds()),
                "entities": entities,
                "references": self.reference_snapshot(8),
                "version": self.VERSION,
            }
