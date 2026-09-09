"""Rotinas pessoais do JARVIS.

Aprende somente comandos de alto nivel que o proprio JARVIS executou e verificou. Nunca
registra teclado/senha/audio bruto e nunca auto-modifica codigo.
"""
from __future__ import annotations

import json
import os
import re
import threading
import shutil
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional


class WorkflowEngine:
    MAX_STEPS = 24
    # Apenas alto impacto/irreversivel fica fora da aprendizagem automatica.
    BLOCK_RE = re.compile(r"\b(?:delete|deleta|apaga|exclui|shutdown|desliga|reinicia|format|executa arquivo|instala)\b", re.I)

    def __init__(self, project_dir: str | os.PathLike, logger=None):
        self.project_dir = Path(project_dir)
        self.logger = logger
        self.path = self.project_dir / "data" / "jarvis_workflows.json"
        legacy_path = self.project_dir / "data" / "zero_workflows.json"
        if not self.path.exists() and legacy_path.exists():
            try:
                shutil.copy2(legacy_path, self.path)
            except Exception:
                self.path = legacy_path
        self._lock = threading.RLock()
        self._data: Dict[str, Dict] = {}
        self._recording: Optional[Dict] = None
        self._load()

    @staticmethod
    def _key(name: str) -> str:
        """Chave tolerante a fala natural sem perder o nome exibido.

        "rotina de trabalho", "rotina trabalho" e "trabalho" viram a mesma
        chave. Isso evita o resolvedor tratar uma pequena variacao do nome como
        outro aplicativo/rotina.
        """
        text = unicodedata.normalize("NFKD", str(name or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
        text = re.sub(r"[^a-z0-9 ]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^(?:rotina|workflow)\s+", "", text).strip()
        words = [w for w in text.split() if w not in {"de", "da", "do", "das", "dos", "a", "o"}]
        return " ".join(words)[:80]

    def _find_key(self, name: str) -> Optional[str]:
        wanted = self._key(name)
        if not wanted:
            return None
        if wanted in self._data:
            return wanted
        # Compatibilidade com arquivos de rotinas gravados por builds anteriores,
        # cujas chaves eram apenas lower().
        for stored_key, item in self._data.items():
            if self._key(stored_key) == wanted or self._key((item or {}).get("name", "")) == wanted:
                return stored_key
        return None

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            items = raw.get("workflows") or {}
            if isinstance(items, dict):
                self._data = items
        except Exception:
            self._data = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "workflows": self._data}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def start_recording(self, name: str) -> str:
        name = " ".join(str(name or "").split()).strip()
        if not name:
            return "Diga um nome para a rotina."
        with self._lock:
            self._recording = {"name": name[:80], "key": self._key(name), "steps": [], "started_at": time.time()}
        return f"✓ Aprendizado da rotina '{name[:80]}' iniciado. Execute os passos pelo JARVIS e depois diga 'terminar rotina'."

    def is_recording(self) -> bool:
        with self._lock:
            return self._recording is not None

    def record_command(self, command: str, success: bool, verified: bool) -> bool:
        command = " ".join(str(command or "").split()).strip()
        if not command or not success or not verified or self.BLOCK_RE.search(command):
            return False
        if command.lower().startswith(("v8:workflow:", "v8:goal:", "v8:mode:", "v8:presence:", "v8:autonomy:", "v8:presence_percent:", "v8:autonomy_percent:", "v8:interrupt")):
            return False
        with self._lock:
            if not self._recording:
                return False
            steps = self._recording["steps"]
            if len(steps) >= self.MAX_STEPS:
                return False
            if not steps or steps[-1] != command:
                steps.append(command)
            return True

    def stop_recording(self) -> str:
        with self._lock:
            rec = self._recording
            self._recording = None
            if not rec:
                return "Não há uma rotina sendo aprendida."
            if not rec["steps"]:
                return f"A rotina '{rec['name']}' não foi salva porque nenhum passo válido foi verificado."
            self._data[rec["key"]] = {
                "name": rec["name"], "steps": list(rec["steps"]), "updated_at": time.time()
            }
            self._save()
            return f"✓ Rotina '{rec['name']}' salva com {len(rec['steps'])} passo(s)."

    def list_workflows(self) -> List[Dict]:
        with self._lock:
            return [dict(v) for _, v in sorted(self._data.items(), key=lambda kv: kv[1].get("name", "").lower())]

    def delete(self, name: str) -> bool:
        with self._lock:
            key = self._find_key(name)
            if key is None:
                return False
            self._data.pop(key, None)
            self._save()
            return True

    def get(self, name: str) -> Optional[Dict]:
        with self._lock:
            key = self._find_key(name)
            item = self._data.get(key) if key is not None else None
            return dict(item) if item else None

    def run(self, name: str, executor: Callable[[str], Dict], cancelled: Optional[Callable[[], bool]] = None, progress: Optional[Callable[[Dict], None]] = None) -> Dict:
        item = self.get(name)
        if not item:
            return {"success": False, "verified": False, "message": f"Não encontrei a rotina '{name}'.", "steps": []}
        results = []
        steps = list(item.get("steps") or [])[: self.MAX_STEPS]
        for idx, command in enumerate(steps, start=1):
            if cancelled and cancelled():
                return {"success": False, "verified": False, "message": "Rotina interrompida.", "steps": results}
            if progress:
                progress({"index": idx, "total": len(steps), "label": command, "status": "running"})
            result = dict(executor(command) or {})
            results.append(result)
            if not result.get("success"):
                return {"success": False, "verified": False, "message": f"A rotina parou no passo {idx}: {result.get('message') or command}", "steps": results}
        verified = bool(results) and all(bool(r.get("verified")) for r in results)
        return {"success": bool(results), "verified": verified, "message": f"✓ Rotina '{item.get('name', name)}' concluída em {len(results)} passo(s).", "steps": results}
