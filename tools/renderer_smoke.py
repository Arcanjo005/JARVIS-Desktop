#!/usr/bin/env python3
"""Exercise the exact production render process in a PyInstaller executable."""
from __future__ import annotations
import multiprocessing
import sys
import time
from pathlib import Path


def main():
    # Import after freeze_support so the child cannot enter the test/UI again.
    if not getattr(sys,"frozen",False):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from jarvis_ui_render import OrbWorker, RenderRequest
    worker=OrbWorker()
    started=time.monotonic()
    frames=[]
    try:
        worker.request(RenderRequest(200,"PENSANDO",.2,True))
        while time.monotonic()-started < 20 and len(frames)<3:
            frame=worker.take()
            if frame is not None:
                frames.append(frame[1].tobytes())
            if worker.error: raise RuntimeError(worker.error)
            time.sleep(.03)
        assert len(frames)==3, "Frozen renderer did not produce frames"
        assert len(set(frames))>1, "Frozen orb does not animate"
    finally:
        worker.close()
    assert not worker.process.is_alive(), "Frozen renderer leaked a child"
    print("JARVIS FROZEN RENDERER SMOKE: PASS (spawn, frames, animation, shutdown)")


if __name__=="__main__":
    multiprocessing.freeze_support()
    main()
