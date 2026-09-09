"""JARVIS - telemetria local de confiabilidade e latencia."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Deque, Dict, Optional


class ReliabilityTracker:
    def __init__(self, project_dir: str, max_events: int = 300):
        self.project_dir = Path(project_dir)
        self.data_dir = self.project_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "reliability_v7.json"
        self._lock = threading.RLock()
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max(100, int(max_events)))
        self._durations: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=100))
        self._counters: Dict[str, int] = defaultdict(int)
        self._last_persist_at = 0.0

    def event(self, name: str, **data: Any):
        row = {"at": time.time(), "name": str(name), **data}
        with self._lock:
            self._events.append(row)
            self._counters[str(name)] += 1
        self._maybe_persist()
        return row

    def duration(self, name: str, milliseconds: float, **data: Any):
        value = max(0.0, float(milliseconds))
        with self._lock:
            self._durations[str(name)].append(value)
        return self.event(str(name) + "_duration", ms=round(value, 3), **data)

    def count(self, name: str, amount: int = 1):
        """Incrementa contador sem criar um evento de log para cada ocorrência."""
        with self._lock:
            self._counters[str(name)] += max(0, int(amount))
            value = self._counters[str(name)]
        self._maybe_persist()
        return value

    def _maybe_persist(self, min_interval: float = 15.0):
        now = time.monotonic()
        if now - self._last_persist_at < float(min_interval):
            return
        self._last_persist_at = now
        try:
            self.persist()
        except Exception:
            pass

    @contextmanager
    def span(self, name: str, **data: Any):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.duration(name, (time.perf_counter() - started) * 1000.0, **data)

    @staticmethod
    def _percentile(values, p: float) -> Optional[float]:
        if not values:
            return None
        vals = sorted(float(x) for x in values)
        pos = (len(vals) - 1) * p
        lo = int(pos)
        hi = min(len(vals) - 1, lo + 1)
        frac = pos - lo
        return vals[lo] * (1.0 - frac) + vals[hi] * frac

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            timings = {}
            for name, values in self._durations.items():
                vals = list(values)
                if not vals:
                    continue
                timings[name] = {
                    "last_ms": round(vals[-1], 2),
                    "avg_ms": round(sum(vals) / len(vals), 2),
                    "p50_ms": round(self._percentile(vals, 0.50) or 0.0, 2),
                    "p95_ms": round(self._percentile(vals, 0.95) or 0.0, 2),
                    "samples": len(vals),
                }
            return {
                "counters": dict(self._counters),
                "timings": timings,
                "events": list(self._events)[-30:],
            }

    def persist(self):
        payload = self.snapshot()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
