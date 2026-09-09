"""Regras condicionais V2 do JARVIS: QUANDO X -> FACA Y.

O motor persiste metadados e comandos locais validados. Regras criadas pelo usuário
podem executar ações comuns como abrir, fechar, mover janelas, mídia e suspender.
Energia irreversível, credenciais, finanças, terminal, instalação e publicação ficam
fora da execução silenciosa.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConditionalRuleEngine:
    VERSION = 2
    MAX_RULES = 200
    SAFE_ACTION_RE = re.compile(
        r"^(?:abre|abra|abrir|fecha|feche|fechar|encerra|encerre|minimiza|minimize|maximiza|maximize|"
        r"restaura|restaure|move|mova|coloca|coloque|pesquisa|pesquise|procura|procure|pausa|pause|"
        r"play|continua|proxima|próxima|volume|silencia|mute|desmuta|fullscreen|tela cheia|"
        r"suspende|suspenda|suspender|hiberna|hibernar)\b",
        re.I,
    )
    BLOCKED_RE = re.compile(
        r"\b(?:apaga|apague|exclui|excluir|deleta|delete|format|senha|password|pin|token|pix|pagar|pagamento|"
        r"comprar|compra|transfer|instala|instalar|desinstala|shutdown|desliga|reinicia|powershell|cmd|terminal|"
        r"envia|enviar|manda email|mensagem|publica|publicar|posta|postar|upload|executa arquivo|executar arquivo)\b",
        re.I,
    )

    def __init__(self, project_dir: str | os.PathLike, logger=None):
        self.project_dir = Path(project_dir)
        self.path = self.project_dir / "data" / "conditional_rules.json"
        self.logger = logger
        self._lock = threading.RLock()
        self._rules: List[Dict[str, Any]] = []
        self._last_fired: Dict[int, float] = {}
        self._recent_global: List[float] = []
        self._load()

    @staticmethod
    def _norm(text: str) -> str:
        value = unicodedata.normalize("NFKD", str(text or ""))
        value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
        value = re.sub(r"[^a-z0-9+% ]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def _log(self, level: str, message: str):
        try:
            fn = getattr(self.logger, level, None) if self.logger else None
            if callable(fn):
                try:
                    fn(message, "RULES")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            rows = data.get("rules") if isinstance(data, dict) else []
            if isinstance(rows, list):
                self._rules = [dict(x) for x in rows if isinstance(x, dict)][: self.MAX_RULES]
        except Exception:
            self._rules = []

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": self.VERSION, "rules": self._rules}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception as exc:
            self._log("warning", f"não consegui salvar regras: {exc}")

    @classmethod
    def parse_request(cls, text: str) -> Optional[Dict[str, Any]]:
        raw = " ".join(str(text or "").split()).strip(" .")
        key = cls._norm(raw)
        if not key.startswith("quando "):
            return None

        # Atalhos de streaming persistentes.
        if re.search(r"\b(?:aparecer|surgir|tiver)\b.*\b(?:abertura|intro|opening)\b", key) and re.search(r"\b(?:pula|pule|ignora|ignore)\b", key):
            return {"builtin": "auto_skip_intro"}
        if re.search(r"\b(?:acabar|terminar|finalizar)\b.*\b(?:episodio|episode)\b", key) and re.search(r"\b(?:proximo|seguinte|passa|avance)\b", key):
            return {"builtin": "auto_next_episode"}

        # Limiar de sistema: "quando CPU passar de 90% me avisa".
        metric_match = re.match(
            r"^quando\s+(?:a\s+|o\s+)?(cpu|processador|ram|memoria|memoria ram|disco|espaco livre)\s+"
            r"(passar de|ficar acima de|chegar a|cair abaixo de|ficar abaixo de)\s+(\d{1,3})(?:\s*%)?.*"
            r"(?:avisa|avise|me fala|notifica|notifique)$",
            key, re.I,
        )
        if metric_match:
            metric_raw = metric_match.group(1)
            metric = "cpu" if metric_raw in {"cpu", "processador"} else "ram" if metric_raw in {"ram", "memoria", "memoria ram"} else "disk_free"
            phrase = metric_match.group(2)
            op = "<=" if "abaixo" in phrase else ">="
            value = max(0, min(100, int(metric_match.group(3))))
            return {
                "trigger_kind": "system_metric", "match": metric, "action": "notify",
                "condition": {"field": metric, "op": op, "value": value},
                "label": f"avisar quando {metric} {op} {value}%", "cooldown": 300.0,
            }

        if "download" in key and re.search(r"\b(?:terminar|concluir|acabar|baixar)\b", key) and re.search(r"\b(?:avisa|avise|me fala|notifica)\b", key):
            return {"trigger_kind": "download_complete", "match": "", "action": "notify", "label": "avisar quando download terminar"}

        # "quando abrir X, abre Y" / "quando entrar no X, faca Y".
        match = re.match(
            r"^quando\s+(?:eu\s+)?(?:abrir|abro|entrar|entro|iniciar|inicio)\s+(?:o\s+|a\s+|no\s+|na\s+)?(.+?)[,;]?\s+"
            r"(?:ai\s+|aí\s+|entao\s+|então\s+)?"
            r"(abre|abra|abrir|fecha|feche|fechar|encerra|encerre|minimiza|minimize|minimizar|maximiza|maximize|move|mova|coloca|coloque|pausa|pause|play|continua|pesquisa|pesquise|procura|procure|suspende|suspenda|suspender|hiberna|hibernar)\s+(.+)$",
            raw, flags=re.I,
        )
        if match:
            trigger = match.group(1).strip(" ,.;:")
            verb = match.group(2).strip()
            tail = match.group(3).strip()
            action = f"{verb} {tail}".strip()
            return {"trigger_kind": "window_changed", "match": trigger, "action": action, "label": f"quando abrir {trigger}"}
        return None

    @classmethod
    def _validate_action(cls, action: str) -> None:
        action = " ".join(str(action or "").split()).strip()
        if action == "notify":
            return
        if cls.BLOCKED_RE.search(action) or not cls.SAFE_ACTION_RE.search(action):
            raise ValueError("essa ação não entra em execução silenciosa; use um comando direto")

    def add(self, trigger_kind: str, match: str, action: str, label: str = "", cooldown: float = 30.0, condition: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        trigger_kind = str(trigger_kind or "").strip()
        match = " ".join(str(match or "").split()).strip()
        action = " ".join(str(action or "").split()).strip()
        if not trigger_kind:
            raise ValueError("gatilho vazio")
        self._validate_action(action)
        cond = dict(condition or {})
        if cond:
            op = str(cond.get("op") or "").strip()
            if op not in {">=", "<=", ">", "<", "=="}:
                raise ValueError("operador de condição inválido")
            cond["value"] = float(cond.get("value", 0))
            cond["field"] = str(cond.get("field") or "").strip()[:40]
        with self._lock:
            if len(self._rules) >= self.MAX_RULES:
                raise ValueError("limite de regras atingido")
            rid = max([int(r.get("id", 0)) for r in self._rules] + [0]) + 1
            row = {
                "id": rid, "enabled": True, "trigger_kind": trigger_kind, "match": match,
                "action": action, "label": label or f"{trigger_kind}:{match}", "cooldown": max(5.0, float(cooldown)),
                "condition": cond, "created_at": time.time(), "fires": 0, "last_error": "",
            }
            self._rules.append(row)
            self._save()
            return dict(row)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._rules]

    def remove(self, rule_id: int) -> bool:
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if int(r.get("id", 0)) != int(rule_id)]
            changed = len(self._rules) != before
            if changed:
                self._save()
            return changed

    def set_enabled(self, rule_id: int, enabled: bool) -> bool:
        with self._lock:
            for row in self._rules:
                if int(row.get("id", 0)) == int(rule_id):
                    row["enabled"] = bool(enabled)
                    self._save()
                    return True
        return False

    def mark_result(self, rule_id: int, success: bool, message: str = "") -> None:
        with self._lock:
            for row in self._rules:
                if int(row.get("id", 0)) == int(rule_id):
                    row["last_result"] = "ok" if success else "failed"
                    row["last_error"] = "" if success else str(message or "falha")[:240]
                    row["last_result_at"] = time.time()
                    self._save()
                    return

    @staticmethod
    def _condition_matches(row: Dict[str, Any], event: Dict[str, Any]) -> bool:
        cond = dict(row.get("condition") or {})
        if not cond:
            return True
        field = str(cond.get("field") or "")
        try:
            actual = float(event.get(field))
            expected = float(cond.get("value"))
        except Exception:
            return False
        op = str(cond.get("op") or "==")
        return {">=": actual >= expected, "<=": actual <= expected, ">": actual > expected, "<": actual < expected, "==": actual == expected}.get(op, False)

    def evaluate(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        event = dict(event or {})
        kind = str(event.get("kind") or "")
        now = time.time()
        fired = []
        hay = self._norm(" ".join(str(event.get(k) or "") for k in ("app", "site", "title", "name", "path", "message", "metric")))
        with self._lock:
            # Limite global: no maximo 8 disparos em 60 s, evitando loops entre regras.
            self._recent_global = [ts for ts in self._recent_global if now - ts <= 60.0]
            if len(self._recent_global) >= 8:
                return []
            for row in self._rules:
                if not row.get("enabled", True) or str(row.get("trigger_kind")) != kind:
                    continue
                needle = self._norm(str(row.get("match") or ""))
                if needle and needle not in hay:
                    continue
                if not self._condition_matches(row, event):
                    continue
                rid = int(row.get("id", 0))
                cooldown = float(row.get("cooldown", 30.0))
                if now - self._last_fired.get(rid, 0.0) < cooldown:
                    continue
                self._last_fired[rid] = now
                self._recent_global.append(now)
                row["fires"] = int(row.get("fires", 0)) + 1
                row["last_fired"] = now
                fired.append(dict(row))
                if len(fired) >= 5:
                    break
            if fired:
                self._save()
        return fired

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": self.VERSION,
                "total": len(self._rules),
                "enabled": sum(1 for r in self._rules if r.get("enabled", True)),
                "fires": sum(int(r.get("fires", 0)) for r in self._rules),
            }


__all__ = ["ConditionalRuleEngine"]
