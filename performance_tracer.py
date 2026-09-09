from __future__ import annotations

import json
import statistics
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class Trace:
    source: str
    started: float = field(default_factory=time.perf_counter)
    last: float = field(default_factory=time.perf_counter)
    stages: Dict[str, float] = field(default_factory=dict)
    intent: str = ""
    route_kind: str = ""
    success: Optional[bool] = None

    def lap(self, name: str) -> float:
        now = time.perf_counter()
        value = (now - self.last) * 1000.0
        self.last = now
        self.stages[str(name)] = self.stages.get(str(name), 0.0) + value
        return value

    def add(self, name: str, ms: float) -> None:
        self.stages[str(name)] = self.stages.get(str(name), 0.0) + float(ms)

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0


class PerformanceTracer:
    """Telemetria local leve; nao salva audio nem conteudo de conversa."""

    def __init__(self, project_dir: str | Path, logger=None, max_records: int = 240):
        self.project_dir = Path(project_dir)
        self.logger = logger
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "jarvis_performance.jsonl"
        legacy_path = self.data_dir / "zero_performance.jsonl"
        if not self.path.exists() and legacy_path.exists():
            try:
                shutil.copy2(legacy_path, self.path)
            except Exception:
                self.path = legacy_path
        self._lock = threading.RLock()
        self._records = deque(maxlen=max(40, int(max_records)))
        self._writes_since_rotate = 0
        self._load_tail()

    def _load_tail(self) -> None:
        if not self.path.is_file():
            return
        try:
            lines = self.path.read_text(encoding="utf-8", errors="ignore").splitlines()[-240:]
            for line in lines:
                try:
                    self._records.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass

    def start(self, source: str = "text") -> Trace:
        return Trace(source=str(source or "text"))

    def _rotate_file_if_needed(self) -> None:
        """Keep telemetry useful without allowing the JSONL file to grow forever."""
        self._writes_since_rotate += 1
        if self._writes_since_rotate < 24:
            return
        self._writes_since_rotate = 0
        try:
            if not self.path.is_file() or self.path.stat().st_size <= 1024 * 1024:
                return
            lines = self.path.read_text(encoding="utf-8", errors="ignore").splitlines()[-600:]
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    def finish(self, trace: Trace, *, intent: str = "", route_kind: str = "", success: Optional[bool] = None) -> dict:
        record = {
            "ts": time.time(),
            "source": trace.source,
            "intent": str(intent or trace.intent or ""),
            "route_kind": str(route_kind or trace.route_kind or ""),
            "success": success,
            "total_ms": round(trace.total_ms, 2),
            "stages": {k: round(float(v), 2) for k, v in trace.stages.items()},
        }
        with self._lock:
            self._records.append(record)
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._rotate_file_if_needed()
            except Exception:
                pass
        try:
            if self.logger:
                self.logger.info(
                    f"PERF total={record['total_ms']:.0f}ms route={record['route_kind'] or '-'} "
                    f"intent={record['intent'] or '-'} stages={record['stages']}",
                    "PERF",
                )
        except Exception:
            pass
        return record

    @staticmethod
    def _percentile(values, p: float):
        if not values:
            return None
        vals = sorted(float(x) for x in values)
        idx = min(len(vals) - 1, max(0, int(round((len(vals) - 1) * p))))
        return vals[idx]

    def summary(self, limit: int = 50) -> dict:
        with self._lock:
            records = list(self._records)[-max(1, int(limit)):]
        if not records:
            return {"count": 0, "p50_ms": None, "p95_ms": None, "local_p50_ms": None, "gemini_p50_ms": None, "voice_p50_ms": None, "text_p50_ms": None, "stages": {}, "last": None, "slowest": []}
        totals = [float(r.get("total_ms") or 0.0) for r in records]
        local = [float(r.get("total_ms") or 0.0) for r in records if r.get("route_kind") == "local"]
        gemini = [float(r.get("total_ms") or 0.0) for r in records if r.get("route_kind") == "conversation"]
        voice = [float(r.get("total_ms") or 0.0) for r in records if r.get("source") == "voice"]
        text = [float(r.get("total_ms") or 0.0) for r in records if r.get("source") == "text"]
        slowest = sorted(records, key=lambda r: float(r.get("total_ms") or 0.0), reverse=True)[:5]
        stage_values = {}
        for record in records:
            for name, value in (record.get("stages") or {}).items():
                try:
                    stage_values.setdefault(str(name), []).append(float(value))
                except Exception:
                    pass
        stage_summary = {}
        for name, values in stage_values.items():
            stage_summary[name] = {
                "count": len(values),
                "p50_ms": round(self._percentile(values, 0.50), 1),
                "p95_ms": round(self._percentile(values, 0.95), 1),
            }
        return {
            "count": len(records),
            "p50_ms": round(self._percentile(totals, 0.50), 1),
            "p95_ms": round(self._percentile(totals, 0.95), 1),
            "local_p50_ms": round(self._percentile(local, 0.50), 1) if local else None,
            "gemini_p50_ms": round(self._percentile(gemini, 0.50), 1) if gemini else None,
            "voice_p50_ms": round(self._percentile(voice, 0.50), 1) if voice else None,
            "text_p50_ms": round(self._percentile(text, 0.50), 1) if text else None,
            "stages": stage_summary,
            "last": records[-1] if records else None,
            "slowest": slowest,
        }
