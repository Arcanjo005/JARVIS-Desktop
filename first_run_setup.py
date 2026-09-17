"""First-run Gemini configuration UI using PySide6 only."""
from __future__ import annotations

import threading
import webbrowser

import requests
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from secure_settings import key_looks_plausible, load_gemini_api_key, save_gemini_api_key

GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
AI_STUDIO_URL = "https://aistudio.google.com/apikey"
_BOOTSTRAP_APP = None


def test_gemini_api_key(key: str, timeout: float = 8.0):
    clean = str(key or "").strip()
    if not key_looks_plausible(clean):
        return False, "A chave parece incompleta."
    try:
        response = requests.get(GEMINI_MODELS_URL, headers={"x-goog-api-key": clean, "x-goog-api-client": "jarvis-desktop/1.0", "Accept": "application/json"}, timeout=timeout)
    except requests.RequestException:
        return False, "Nao consegui acessar o Gemini. Verifique sua internet."
    if response.status_code == 200:
        return True, "Chave validada com sucesso."
    if response.status_code in (400, 401, 403):
        return False, "O Gemini recusou essa chave. Confira a chave no Google AI Studio."
    if response.status_code == 429:
        return True, "Chave reconhecida; a conta esta com limite temporario de uso."
    return False, f"O Gemini respondeu com codigo {response.status_code}. Tente novamente."


class _TestSignals(QObject):
    done = Signal(bool, str)


def _ensure_app() -> QApplication:
    global _BOOTSTRAP_APP
    app = QApplication.instance()
    if app is None:
        _BOOTSTRAP_APP = QApplication([])
        app = _BOOTSTRAP_APP
    return app


def show_api_key_dialog(parent=None, first_run: bool = False) -> bool:
    _ensure_app()
    dialog = QDialog(parent)
    dialog.setWindowTitle("JARVIS Desktop - Configurar Gemini")
    dialog.setFixedSize(590, 430)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dialog.setStyleSheet("QDialog{background:#17181c;color:#f5f7ff;}QLabel{color:#c8cdd6;font:12px 'Segoe UI';}QLabel#title{color:#f5f7ff;font:800 22px 'Segoe UI';}QLabel#subtitle{color:#a9afbc;font:14px 'Segoe UI';}QLineEdit{height:42px;background:#22242a;border:1px solid #3c414b;border-radius:8px;color:#f5f6f8;padding:0 12px;font:13px 'Segoe UI';}QPushButton{height:38px;background:#30343d;border:1px solid #404651;border-radius:8px;color:#f5f7ff;padding:0 14px;font:600 12px 'Segoe UI';}QPushButton:hover{background:#3c424e;}QPushButton#save{background:#5f91ff;color:#10131a;border-color:#5f91ff;}")
    result = {"saved": False}
    signals = _TestSignals(dialog)
    root = QVBoxLayout(dialog)
    root.setContentsMargins(30, 26, 30, 24)
    root.setSpacing(10)
    title = QLabel("JARVIS DESKTOP"); title.setObjectName("title")
    subtitle = QLabel("Conecte sua propria chave do Google Gemini"); subtitle.setObjectName("subtitle")
    root.addWidget(title); root.addWidget(subtitle); root.addSpacing(8)
    info = QLabel("A chave fica protegida pelo Windows para este usuario e nao e enviada ao GitHub, ao instalador ou a outros usuarios do JARVIS.")
    info.setWordWrap(True); root.addWidget(info); root.addSpacing(4)
    entry = QLineEdit(); entry.setEchoMode(QLineEdit.EchoMode.Password); entry.setPlaceholderText("Cole aqui sua API key do Gemini")
    existing = load_gemini_api_key()
    if existing: entry.setText(existing)
    root.addWidget(entry)
    status = QLabel(""); status.setWordWrap(True); root.addWidget(status); root.addStretch(1)
    row = QHBoxLayout(); test_button = QPushButton("Testar chave"); create_button = QPushButton("Criar/ver chave"); save_button = QPushButton("Salvar e continuar"); save_button.setObjectName("save")
    row.addWidget(test_button); row.addWidget(create_button); row.addStretch(1); row.addWidget(save_button); root.addLayout(row)
    if first_run:
        later = QPushButton("Configurar depois"); later.clicked.connect(dialog.reject); root.addWidget(later, 0, Qt.AlignmentFlag.AlignRight)
    def set_busy(busy: bool):
        test_button.setEnabled(not busy); save_button.setEnabled(not busy)
    def test_done(ok: bool, message: str):
        set_busy(False); status.setText(message); status.setStyleSheet(f"color:{'#69e3b1' if ok else '#ff8b8b'};")
    signals.done.connect(test_done)
    def do_test():
        key = entry.text().strip()
        if not key_looks_plausible(key): test_done(False, "A chave parece incompleta."); return
        set_busy(True); status.setText("Testando conexao com o Gemini..."); status.setStyleSheet("color:#a9afbc;")
        def worker():
            ok, message = test_gemini_api_key(key); signals.done.emit(bool(ok), str(message))
        threading.Thread(target=worker, name="JARVIS-GEMINI-KEY-TEST", daemon=True).start()
    def do_save():
        key = entry.text().strip()
        try: save_gemini_api_key(key)
        except ValueError as exc: test_done(False, str(exc)); return
        except Exception: test_done(False, "Nao consegui proteger a chave no Windows."); return
        result["saved"] = True; dialog.accept()
    test_button.clicked.connect(do_test); create_button.clicked.connect(lambda: webbrowser.open(AI_STUDIO_URL)); save_button.clicked.connect(do_save); entry.returnPressed.connect(do_save); entry.setFocus(); dialog.exec()
    return bool(result["saved"])


def ensure_gemini_configured() -> bool:
    if load_gemini_api_key(): return True
    return show_api_key_dialog(first_run=True)


__all__ = ["ensure_gemini_configured", "show_api_key_dialog", "test_gemini_api_key"]
