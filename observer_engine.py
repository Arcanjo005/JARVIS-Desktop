"""Observador leve do JARVIS.

Nao grava tela e nao usa camera/microfone. Observa apenas metadados de janela ativa e
pasta Downloads para manter contexto e emitir eventos uteis.
"""
from __future__ import annotations

import threading
import time
import shutil
from pathlib import Path
from typing import Callable, Dict, Optional


class ObserverEngine:
    def __init__(self, context, windows=None, logger=None, on_event: Optional[Callable[[Dict], None]] = None, interval: float = 1.0):
        self.context = context
        self.windows = windows
        self.logger = logger
        self.on_event = on_event
        self.interval = max(0.5, float(interval))
        self.download_dir = Path.home() / "Downloads"
        self._stop = threading.Event()
        self._thread = None
        self._files: Dict[str, tuple[int, float]] = {}
        self._last_title = ""
        self._last_app = ""
        self._last_health_check = 0.0
        self._health_streaks = {"cpu": 0, "ram": 0}
        self._health_last_emit: Dict[str, float] = {}
        # 13.12.1: um alerta de saude fica latched enquanto a metrica
        # permanecer na zona critica. Isso evita repetir "RAM 96%" a cada
        # cooldown sem nenhuma recuperacao real entre os avisos.
        self._health_latched: Dict[str, bool] = {}
        try:
            import psutil  # type: ignore
            self._psutil = psutil
            self._psutil.cpu_percent(interval=None)
        except Exception:
            self._psutil = None

    def _log(self, level, message):
        if not self.logger:
            return
        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try: fn(message, "OBSERVER")
                except TypeError: fn(message)
        except Exception:
            pass

    def _emit(self, kind: str, **data):
        event = {"kind": kind, "ts": time.time(), **data}
        try:
            if self.on_event:
                self.on_event(event)
        except Exception as exc:
            self._log("warning", f"callback do observador falhou: {exc}")

    def _scan_downloads(self):
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            current = {}
            for p in self.download_dir.iterdir():
                if not p.is_file():
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                current[p.name] = (int(st.st_size), float(st.st_mtime))
            # novos arquivos concluidos; extensoes temporarias nao notificam.
            for name, meta in current.items():
                if name not in self._files and not name.lower().endswith((".crdownload", ".part", ".tmp")):
                    path = str(self.download_dir / name)
                    self.context.record_download(path, verified=True)
                    self._emit("download_complete", path=path, name=name, size=meta[0])
            self._files = current
        except Exception:
            pass

    def _health_rearm(self, key: str) -> None:
        self._health_latched[key] = False
        if key in self._health_streaks:
            self._health_streaks[key] = 0

    def _health_maybe_emit(self, key: str, active: bool, message: str, value: float, severity: str = "warning", streak: int = 3, cooldown: float = 900.0):
        if key in self._health_streaks:
            self._health_streaks[key] = self._health_streaks.get(key, 0) + 1 if active else 0
            ready = self._health_streaks[key] >= max(1, int(streak))
        else:
            ready = bool(active)
        if not ready or self._health_latched.get(key, False):
            return
        now = time.time()
        if now - float(self._health_last_emit.get(key, 0.0)) < float(cooldown):
            return
        self._health_last_emit[key] = now
        self._health_latched[key] = True
        self._emit("system_health", metric=key, value=float(value), severity=severity, message=message)

    def _scan_system_health(self):
        # Metricas leves, no maximo a cada 5 s. Sem processos, nomes de arquivos
        # ou conteudo privado; apenas percentuais globais.
        now_mono = time.monotonic()
        if now_mono - self._last_health_check < 5.0:
            return
        self._last_health_check = now_mono
        try:
            if self._psutil is not None:
                cpu = float(self._psutil.cpu_percent(interval=None))
                ram = float(self._psutil.virtual_memory().percent)
                # Evento silencioso para regras V2. Nao vira notificacao por si so.
                self._emit("system_metric", metric="cpu", cpu=cpu, ram=ram)
                self._emit("system_metric", metric="ram", cpu=cpu, ram=ram)
                # Histerese: o aviso so pode reaparecer depois de a metrica
                # sair de verdade da zona de pressao.
                if cpu <= 85.0:
                    self._health_rearm("cpu")
                if ram <= 88.0:
                    self._health_rearm("ram")
                self._health_maybe_emit("cpu", cpu >= 96.0, f"CPU permaneceu muito alta ({cpu:.0f}%).", cpu, streak=4, cooldown=1200.0)
                self._health_maybe_emit("ram", ram >= 93.0, f"Memoria RAM esta muito alta ({ram:.0f}%).", ram, streak=3, cooldown=1800.0)
        except Exception:
            pass
        try:
            usage = shutil.disk_usage(str(Path.home()))
            free_pct = (float(usage.free) / max(1.0, float(usage.total))) * 100.0
            self._emit("system_metric", metric="disk_free", disk_free=free_pct)
            if free_pct >= 8.0:
                self._health_rearm("disk")
            self._health_maybe_emit("disk", free_pct <= 5.0, f"Espaco livre no disco do usuario esta baixo ({free_pct:.1f}% livre).", free_pct, severity="critical" if free_pct <= 2.0 else "warning", streak=1, cooldown=21600.0)
        except Exception:
            pass

    def _tick(self):
        try:
            snap = self.context.refresh_from_windows(self.windows)
            title = str(snap.get("active_title") or "")
            if title and title != self._last_title:
                previous_app = self._last_app
                self._last_title = title
                self._last_app = str(snap.get("active_app", "") or "")
                self._emit(
                    "window_changed", title=title, app=self._last_app, previous_app=previous_app,
                    site=snap.get("active_site", ""), monitor=snap.get("active_monitor"),
                )
        except Exception:
            pass
        self._scan_downloads()
        self._scan_system_health()

    def _run(self):
        # baseline antes de emitir downloads para nao notificar arquivos antigos.
        self._scan_downloads()
        while not self._stop.wait(self.interval):
            self._tick()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-observer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0):
        self._stop.set()
        th = self._thread
        if th and th.is_alive():
            th.join(timeout=max(0.0, float(timeout)))

    def status(self):
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "interval": self.interval,
            "download_dir": str(self.download_dir),
        }
