"""JARVIS diagnostics compatibility layer.

Keeps the established diagnostic implementation while adding information that
makes installed-version/hot-runtime conflicts visible immediately.
"""
from __future__ import annotations

import os
from pathlib import Path

import diagnostics_manager_core as _core
from jarvis_version import PUBLIC_NAME, VERSION as JARVIS_VERSION


class DiagnosticsManager(_core.DiagnosticsManager):
    def run(self, *args, **kwargs) -> str:
        report = super().run(*args, **kwargs)
        lines = report.splitlines()

        effective = str(os.environ.get("JARVIS_EFFECTIVE_VERSION") or JARVIS_VERSION).strip()
        bundled = str(os.environ.get("JARVIS_BUNDLED_VERSION") or JARVIS_VERSION).strip()
        hot_dir = str(os.environ.get("JARVIS_HOT_RUNTIME_DIR") or "").strip()
        runtime_state = (
            f"ATIVO  versão={effective}  pasta={hot_dir}"
            if hot_dir
            else f"INATIVO  usando instalador={bundled}"
        )
        version_lines = [
            f"Versão instalada: {bundled}",
            f"Versão efetiva: {effective}",
            f"Hot Runtime: {runtime_state}",
        ]

        # Put version/runtime identity immediately below the header so copied
        # diagnostics explain which Python layer is actually executing.
        insert_at = 2 if len(lines) >= 2 else len(lines)
        lines[insert_at:insert_at] = version_lines + [""]

        # Voice is intentionally lazy in current desktop builds. Not being
        # loaded before first use is healthy state, not a failure.
        lines = [
            "Voz -  motor sob demanda; ainda não carregado nesta sessão"
            if line.strip() == "Voz ✗  motor não carregado"
            else line
            for line in lines
        ]

        # An audio subsystem may be available even when Windows did not expose
        # a friendly device name. Avoid reporting a misleading green check.
        lines = [
            line.replace("Saída de áudio ✓  não identificada", "Saída de áudio ?  disponível, dispositivo não identificado")
                .replace("Entrada de áudio ✓  não identificada", "Entrada de áudio ?  disponível, dispositivo não identificado")
            for line in lines
        ]
        return "\n".join(lines)


__all__ = ["DiagnosticsManager"]
