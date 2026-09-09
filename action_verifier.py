"""ZERO V7 - verificadores deterministas para acoes locais."""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import psutil
except Exception:
    psutil = None


@dataclass
class VerificationResult:
    verified: bool
    status: str
    detail: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ActionVerifier:
    def __init__(self, logger=None):
        self.logger = logger

    @staticmethod
    def _norm_path(value: str) -> str:
        try:
            return os.path.normcase(os.path.abspath(str(value or "").strip('"')))
        except Exception:
            return str(value or "").lower().strip()

    def verify_application_open(self, target: str, timeout: float = 2.8) -> VerificationResult:
        started = time.monotonic()
        target = str(target or "").strip().strip('"')
        if not target:
            return VerificationResult(False, "invalid_target", "alvo vazio", 0)

        # URI/UWP/atalho: a requisicao pode ser valida, mas o processo real pode
        # ter outro nome. Nao inventamos confirmacao.
        if target.startswith(("shell:AppsFolder\\", "steam://", "com.epicgames.launcher://", "http://", "https://", "ms-")):
            return VerificationResult(False, "requested_unverifiable", "alvo gerenciado pelo Shell/URI", int((time.monotonic() - started) * 1000))
        if target.lower().endswith((".lnk", ".url", ".bat", ".cmd")):
            return VerificationResult(False, "requested_unverifiable", "atalho/script pode iniciar outro processo", int((time.monotonic() - started) * 1000))
        if psutil is None:
            return VerificationResult(False, "verifier_unavailable", "psutil indisponivel", 0)

        target_path = self._norm_path(target)
        target_name = Path(target).name.lower()
        target_stem = Path(target).stem.lower()
        deadline = time.monotonic() + max(0.25, float(timeout))
        while time.monotonic() < deadline:
            for proc in psutil.process_iter(["name", "exe"]):
                try:
                    name = str(proc.info.get("name") or "").lower()
                    exe = str(proc.info.get("exe") or "")
                    if exe and self._norm_path(exe) == target_path:
                        return VerificationResult(True, "process_verified", exe, int((time.monotonic() - started) * 1000))
                    stem = Path(name).stem.lower() if name else ""
                    if (target_name and name == target_name) or (target_stem and stem == target_stem):
                        return VerificationResult(True, "process_name_verified", name, int((time.monotonic() - started) * 1000))
                except Exception:
                    continue
            time.sleep(0.08)
        return VerificationResult(False, "process_not_observed", target, int((time.monotonic() - started) * 1000))

# Build 13.11: verificadores pos-acao genericos. Mantidos fora do construtor para
# nao adicionar dependencias obrigatorias ao motor antigo.
def _verify_window_snapshot(self, window_manager, target: str, *, state: str = "", monitor: Optional[int] = None, timeout: float = 1.4) -> VerificationResult:
    started = time.monotonic()
    if window_manager is None or not str(target or "").strip():
        return VerificationResult(False, "window_verifier_unavailable", str(target or ""), 0)
    deadline = time.monotonic() + max(0.15, float(timeout))
    while time.monotonic() < deadline:
        try:
            snap = window_manager.inspect_window(str(target))
        except Exception:
            snap = None
        if snap:
            state_ok = not state or str(snap.get("state") or "").lower() == str(state).lower()
            mon_ok = monitor is None or int(snap.get("monitor") or 0) == int(monitor)
            if state_ok and mon_ok:
                detail = f"{snap.get('title') or target} | state={snap.get('state')} | monitor={snap.get('monitor')}"
                return VerificationResult(True, "window_verified", detail, int((time.monotonic() - started) * 1000))
        time.sleep(0.06)
    return VerificationResult(False, "window_state_not_observed", str(target), int((time.monotonic() - started) * 1000))


def _verify_file_exists(self, path: str) -> VerificationResult:
    started = time.monotonic()
    try:
        p = Path(str(path or "").strip().strip('"'))
        ok = p.exists()
        return VerificationResult(ok, "file_verified" if ok else "file_not_found", str(p), int((time.monotonic() - started) * 1000))
    except Exception as exc:
        return VerificationResult(False, "file_verify_error", str(exc), int((time.monotonic() - started) * 1000))


def _verify_command(self, command: str, result: Optional[Dict[str, Any]] = None, *, window_manager=None, media_context=None, timeout: float = 1.2) -> VerificationResult:
    """Tenta provar o efeito de um comando local sem inventar sucesso.

    Se o executor ja trouxe verified=True, respeita essa evidencia. Caso contrario,
    usa apenas sinais deterministas: snapshot de janela, arquivo existente ou estado
    de midia que realmente mudou.
    """
    started = time.monotonic()
    result = dict(result or {})
    if bool(result.get("verified")):
        return VerificationResult(True, "executor_verified", str(result.get("message") or ""), int((time.monotonic() - started) * 1000))
    raw = " ".join(str(command or "").split()).strip()
    low = raw.lower()

    import re
    m = re.match(r"^(?:abre|abra|abrir)\s+(?:o\s+|a\s+)?(.+)$", raw, re.I)
    if m and window_manager is not None:
        return _verify_window_snapshot(self, window_manager, m.group(1).strip(), timeout=timeout)
    m = re.match(r"^(?:minimiza|minimize|minimizar)\s+(.+)$", raw, re.I)
    if m:
        return _verify_window_snapshot(self, window_manager, m.group(1).strip(), state="minimized", timeout=timeout)
    m = re.match(r"^(?:maximiza|maximize|maximizar|expande|expanda)\s+(.+)$", raw, re.I)
    if m:
        return _verify_window_snapshot(self, window_manager, m.group(1).strip(), state="maximized", timeout=timeout)
    m = re.match(r"^(?:restaura|restaure|restaurar)\s+(.+)$", raw, re.I)
    if m:
        return _verify_window_snapshot(self, window_manager, m.group(1).strip(), state="normal", timeout=timeout)
    m = re.match(r"^(?:move|mova|mover|coloca|coloque|joga|jogue|leva|leve)\s+(.+?)\s+(?:para|pra|pro|na|no)\s+(?:o\s+|a\s+)?(?:monitor|tela|display)\s*(\d+)$", raw, re.I)
    if m:
        return _verify_window_snapshot(self, window_manager, m.group(1).strip(), monitor=int(m.group(2)), timeout=timeout)

    path = str(result.get("path") or (result.get("detail") or {}).get("path") if isinstance(result.get("detail"), dict) else "")
    if path:
        check = _verify_file_exists(self, path)
        if check.verified:
            return check

    # Midia: somente confirma se o proprio MediaContext consegue observar uma
    # mudanca/estado. Sem before/after confiavel, permanece nao verificado.
    if low.startswith("v8:media:") and media_context is not None:
        try:
            after = media_context.refresh(force=True).to_dict()
            before = dict(result.get("before") or {})
            if before and after and before != after:
                return VerificationResult(True, "media_changed", str(after.get("item") or after.get("title") or "midia mudou"), int((time.monotonic() - started) * 1000))
        except Exception:
            pass

    return VerificationResult(False, "effect_not_observed", str(result.get("message") or raw), int((time.monotonic() - started) * 1000))


ActionVerifier.verify_window_snapshot = _verify_window_snapshot
ActionVerifier.verify_file_exists = _verify_file_exists
ActionVerifier.verify_command = _verify_command
