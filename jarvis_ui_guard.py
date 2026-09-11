"""JARVIS 1.2.3 - UI responsiveness guard.

This module deliberately does not know anything about Gemini, routing or voice
internals.  It protects the Tk main thread from queue bursts and records a
useful thread dump if the Windows GUI stops pumping events.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path


class BudgetQueueProxy:
    """Proxy around Queue with a per-drain item/time budget.

    GUI._drain_ui_events() believes it is reading a regular Queue. During each
    main-loop turn this proxy intentionally raises queue.Empty once the budget
    is exhausted, so background subsystems cannot monopolize Tk for hundreds
    of callbacks at once.
    """

    LOW_PRIORITY = {
        "voice_caption",
        "voice_user_caption",
        "runtime_ready",
    }

    def __init__(self, inner):
        self.inner = inner
        self._budget_active = False
        self._budget_items = 16
        self._budget_deadline = 0.0
        self._taken = 0

    def begin_budget(self, max_items=16, max_seconds=0.009):
        self._budget_active = True
        self._budget_items = max(1, int(max_items))
        self._budget_deadline = time.monotonic() + max(0.002, float(max_seconds))
        self._taken = 0

    def end_budget(self):
        self._budget_active = False
        self._taken = 0
        self._budget_deadline = 0.0

    def put_nowait(self, item):
        # Keep the queue bounded under noisy audio/overlay conditions.
        try:
            event_name = item[0] if isinstance(item, tuple) and item else ""
            backlog = self.inner.qsize()
            if backlog >= 160 and event_name in self.LOW_PRIORITY:
                return
        except Exception:
            pass
        return self.inner.put_nowait(item)

    def put(self, item, *args, **kwargs):
        try:
            event_name = item[0] if isinstance(item, tuple) and item else ""
            backlog = self.inner.qsize()
            if backlog >= 160 and event_name in self.LOW_PRIORITY:
                return
        except Exception:
            pass
        return self.inner.put(item, *args, **kwargs)

    def get_nowait(self):
        if self._budget_active:
            if self._taken >= self._budget_items:
                raise queue.Empty
            if time.monotonic() >= self._budget_deadline:
                raise queue.Empty
        item = self.inner.get_nowait()
        if self._budget_active:
            self._taken += 1
        return item

    def qsize(self):
        return self.inner.qsize()

    def empty(self):
        return self.inner.empty()

    def __getattr__(self, name):
        return getattr(self.inner, name)


class UIFreezeGuard:
    """Heartbeat + freeze stack dump for the Tk thread."""

    def __init__(self, gui, interval_ms=250, freeze_after=2.75):
        self.gui = gui
        self.root = getattr(gui, "root", None)
        self.interval_ms = max(100, int(interval_ms))
        self.freeze_after = max(1.5, float(freeze_after))
        self.last_beat = time.monotonic()
        self.last_beat_wall = time.time()
        self.last_callback = "startup"
        self.freeze_count = 0
        self._stopped = threading.Event()
        self._dump_lock = threading.Lock()
        project_dir = Path(str(getattr(gui, "project_dir", "") or "."))
        log_dir = Path(os.environ.get("LOCALAPPDATA", project_dir)) / "JARVIS" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            log_dir = project_dir / "data"
            log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / "UI_FREEZE_DIAGNOSTIC.txt"

    def start(self):
        if not self.root:
            return
        try:
            self.root.after(self.interval_ms, self._beat)
        except Exception:
            return
        threading.Thread(
            target=self._watch,
            name="JARVIS-UI-FREEZE-GUARD",
            daemon=True,
        ).start()

    def stop(self):
        self._stopped.set()

    def mark(self, callback_name):
        self.last_callback = str(callback_name or "unknown")

    def _beat(self):
        if self._stopped.is_set():
            return
        self.last_beat = time.monotonic()
        self.last_beat_wall = time.time()
        self.last_callback = "mainloop-idle"
        try:
            if self.root and self.root.winfo_exists():
                self.root.after(self.interval_ms, self._beat)
        except Exception:
            self._stopped.set()

    def _watch(self):
        reported_for_beat = None
        while not self._stopped.wait(0.55):
            lag = time.monotonic() - self.last_beat
            if lag < self.freeze_after:
                reported_for_beat = None
                continue
            beat_key = round(self.last_beat, 3)
            if reported_for_beat == beat_key:
                continue
            reported_for_beat = beat_key
            self.freeze_count += 1
            self._write_dump(lag)

    def _write_dump(self, lag):
        if not self._dump_lock.acquire(blocking=False):
            return
        try:
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            lines = [
                "",
                "=" * 78,
                f"JARVIS UI FREEZE #{self.freeze_count} - {now}",
                "=" * 78,
                f"Heartbeat atrasado: {lag:.2f}s",
                f"Ultimo callback marcado: {self.last_callback}",
                f"PID: {os.getpid()}",
                f"Python: {sys.version}",
                "",
            ]
            try:
                q = getattr(self.gui, "_ui_event_queue", None)
                lines.append(f"Fila UI aproximada: {q.qsize() if q is not None else '-'}")
            except Exception:
                pass

            frames = sys._current_frames()
            threads = list(threading.enumerate())
            lines.append(f"Threads ativas: {len(threads)}")
            for th in threads:
                lines.append("")
                lines.append(f"--- THREAD {th.name} ident={th.ident} daemon={th.daemon} ---")
                frame = frames.get(th.ident)
                if frame is None:
                    lines.append("(sem frame Python)")
                    continue
                try:
                    lines.extend(line.rstrip("\n") for line in traceback.format_stack(frame))
                except Exception as exc:
                    lines.append(f"(falha ao formatar stack: {exc})")

            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except Exception:
            pass
        finally:
            self._dump_lock.release()


def install_gui_responsiveness_guard(gui):
    """Attach queue budgeting and heartbeat to an already-created GUI."""
    try:
        q = getattr(gui, "_ui_event_queue", None)
        if q is not None and not isinstance(q, BudgetQueueProxy):
            gui._ui_event_queue = BudgetQueueProxy(q)
    except Exception:
        pass

    try:
        guard = UIFreezeGuard(gui)
        gui._v123_ui_freeze_guard = guard
        guard.start()
        return guard
    except Exception:
        return None


__all__ = [
    "BudgetQueueProxy",
    "UIFreezeGuard",
    "install_gui_responsiveness_guard",
]
