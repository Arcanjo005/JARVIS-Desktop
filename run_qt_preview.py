#!/usr/bin/env python3
"""Launch the rebuilt Qt shell without changing the production entry point."""
from __future__ import annotations

import multiprocessing


def main() -> int:
    from actions import SystemActions
    from core import JarvisCore
    from gui_qt_reference_v2 import JarvisGUI
    from logger import JarvisLogger

    logger = JarvisLogger()
    actions = SystemActions(logger)
    core = JarvisCore(logger)
    window = JarvisGUI(logger, actions, core)
    return int(window.run() or 0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
