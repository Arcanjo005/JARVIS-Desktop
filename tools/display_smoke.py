#!/usr/bin/env python3
"""Validate native monitor fitting, not only child-widget bounds within a window."""
from __future__ import annotations
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    root_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root_dir))
    from jarvis_ui_selftest import TestApplication, CaptureLogger, SimpleNamespace, pump
    from jarvis_display import monitor_work_area
    import customtkinter as ctk
    from PIL import ImageGrab
    evidence = root_dir / "validation"
    evidence.mkdir(exist_ok=True)
    snapshots, failures = [], []
    with tempfile.TemporaryDirectory(prefix="jarvis-display-") as td:
        os.environ["JARVIS_APP_DIR"] = td
        os.environ["LOCALAPPDATA"] = td
        os.environ.pop("GEMINI_API_KEY", None)
        app = TestApplication(CaptureLogger(), SimpleNamespace(), SimpleNamespace())
        app.requests = []
        window = app.root
        def record(label):
            area = monitor_work_area(window)
            controls = {}
            for name in ("update_button", "history_button", "quick_menu_button", "text_input", "send_button"):
                item = getattr(app, name)
                controls[name] = [item.winfo_rootx(), item.winfo_rooty(), item.winfo_width(), item.winfo_height()]
            data = {"label": label, "area": vars(area), "state": window.state(),
                    "geometry": window.geometry(), "root": [window.winfo_rootx(), window.winfo_rooty(), window.winfo_width(), window.winfo_height()],
                    "controls": controls, "jobs": list(app._ui_jobs)}
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                u = ctypes.WinDLL("user32", use_last_error=True)
                u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                u.GetAncestor.restype = wintypes.HWND
                u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
                u.GetWindowRect.restype = wintypes.BOOL
                h = u.GetAncestor(window.winfo_id(), 2)
                rect = wintypes.RECT()
                if u.GetWindowRect(h, ctypes.byref(rect)):
                    data["native_outer"] = [rect.left, rect.top, rect.right, rect.bottom]
            snapshots.append(data)
            return data
        def check_bounds(data):
            area = data["area"]
            for name, (x,y,w,h) in data["controls"].items():
                if not (area["x"] <= x and area["y"] <= y and x+w <= area["x"]+area["width"] and y+h <= area["y"]+area["height"]):
                    failures.append(data["label"] + ": " + name + " outside monitor work area")
        try:
            pump(app, 1.3)
            check_bounds(record("initial"))
            for size, scale in (("1420x900",1), ("800x600",1), ("620x440",1), ("1000x700",1.5), ("1000x700",2), ("620x440",1)):
                if ctk.ScalingTracker.widget_scaling != scale:
                    ctk.set_widget_scaling(scale)
                    ctk.set_window_scaling(scale)
                label = f"{size}-scale-{scale}"
                window.geometry(size)
                pump(app, .45)
                record(label + " automatic")
                # The production Configure binding must do the fitting; calling
                # fit_window here would mask a broken event handler.
                pump(app, 1.4)
                data = record(label + " settled")
                check_bounds(data)
                x,y,w,h = data["root"]
                ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(evidence / ("display-"+label+".png"))
        finally:
            window.destroy()
            app.memory_store.close()
    result = {"ok": not failures, "platform": sys.platform, "snapshots": snapshots, "failures": failures}
    (evidence/"display-test-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if failures:
        raise SystemExit(1)
    print("JARVIS NATIVE DISPLAY SMOKE: PASS")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
