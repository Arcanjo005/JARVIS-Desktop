"""First-run Gemini configuration UI for JARVIS Desktop."""
from __future__ import annotations

import queue
import threading
import webbrowser

import customtkinter as ctk
import requests

from secure_settings import key_looks_plausible, load_gemini_api_key, save_gemini_api_key

GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
AI_STUDIO_URL = "https://aistudio.google.com/apikey"


def test_gemini_api_key(key: str, timeout: float = 8.0):
    clean = str(key or "").strip()
    if not key_looks_plausible(clean):
        return False, "A chave parece incompleta."
    try:
        response = requests.get(
            GEMINI_MODELS_URL,
            headers={
                "x-goog-api-key": clean,
                "x-goog-api-client": "jarvis-desktop/1.0",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
    except requests.RequestException:
        return False, "Não consegui acessar o Gemini. Verifique sua internet."
    if response.status_code == 200:
        return True, "Chave validada com sucesso."
    if response.status_code in (400, 401, 403):
        return False, "O Gemini recusou essa chave. Confira a chave no Google AI Studio."
    if response.status_code == 429:
        # Authentication succeeded far enough to reach quota/rate limiting.
        return True, "Chave reconhecida; a conta está com limite temporário de uso."
    return False, f"O Gemini respondeu com código {response.status_code}. Tente novamente."


def show_api_key_dialog(parent=None, first_run: bool = False) -> bool:
    """Show a modal API-key dialog. Returns True when a key was saved."""
    owns_root = parent is None
    window = ctk.CTk() if owns_root else ctk.CTkToplevel(parent)
    window.title("JARVIS Desktop - Configurar Gemini")
    window.geometry("590x430")
    window.resizable(False, False)
    window.configure(fg_color="#17181C")
    try:
        window.iconbitmap("jarvis.ico")
    except Exception:
        pass

    result = {"saved": False}
    test_results = queue.Queue()

    if not owns_root:
        try:
            window.transient(parent)
            window.grab_set()
        except Exception:
            pass

    shell = ctk.CTkFrame(window, fg_color="#17181C", corner_radius=0)
    shell.pack(fill="both", expand=True, padx=30, pady=26)

    ctk.CTkLabel(
        shell,
        text="JARVIS DESKTOP",
        font=ctk.CTkFont(family="Bahnschrift", size=22, weight="bold"),
        text_color="#F5F7FF",
    ).pack(anchor="w")
    ctk.CTkLabel(
        shell,
        text="Conecte sua própria chave do Google Gemini",
        font=ctk.CTkFont(size=14),
        text_color="#A9AFBC",
    ).pack(anchor="w", pady=(3, 20))

    info = (
        "A chave fica protegida pelo Windows para este usuário e não é enviada ao GitHub, "
        "ao instalador ou a outros usuários do JARVIS."
    )
    ctk.CTkLabel(
        shell, text=info, justify="left", wraplength=520,
        font=ctk.CTkFont(size=12), text_color="#C8CDD6",
    ).pack(anchor="w", pady=(0, 14))

    entry = ctk.CTkEntry(
        shell,
        height=44,
        show="•",
        placeholder_text="Cole aqui sua API key do Gemini",
        fg_color="#22242A",
        border_color="#3C414B",
        text_color="#F5F6F8",
    )
    entry.pack(fill="x")
    existing = load_gemini_api_key()
    if existing:
        entry.insert(0, existing)

    status = ctk.CTkLabel(
        shell, text="", anchor="w", justify="left",
        font=ctk.CTkFont(size=11), text_color="#A9AFBC",
    )
    status.pack(fill="x", pady=(10, 6))

    buttons = ctk.CTkFrame(shell, fg_color="transparent")
    buttons.pack(fill="x", pady=(10, 0))

    test_button = ctk.CTkButton(
        buttons, text="Testar chave", width=120, height=38,
        fg_color="#30343D", hover_color="#3C424E",
    )
    test_button.pack(side="left")

    ctk.CTkButton(
        buttons, text="Criar/ver chave", width=120, height=38,
        fg_color="transparent", border_width=1, border_color="#404651",
        hover_color="#292D34",
        command=lambda: webbrowser.open(AI_STUDIO_URL),
    ).pack(side="left", padx=8)

    save_button = ctk.CTkButton(
        buttons, text="Salvar e continuar", width=150, height=38,
        fg_color="#5F91FF", hover_color="#78A3FF", text_color="#10131A",
    )
    save_button.pack(side="right")

    if first_run:
        ctk.CTkButton(
            shell, text="Configurar depois", height=30,
            fg_color="transparent", hover_color="#25282E", text_color="#8D94A0",
            command=window.destroy,
        ).pack(anchor="e", pady=(14, 0))

    def set_busy(busy: bool):
        state = "disabled" if busy else "normal"
        try:
            test_button.configure(state=state)
            save_button.configure(state=state)
        except Exception:
            pass

    def poll_test_results():
        try:
            ok, message = test_results.get_nowait()
        except queue.Empty:
            try:
                window.after(100, poll_test_results)
            except Exception:
                pass
            return
        set_busy(False)
        status.configure(text=message, text_color="#69E3B1" if ok else "#FF8B8B")

    def do_test():
        key = entry.get().strip()
        if not key_looks_plausible(key):
            status.configure(text="A chave parece incompleta.", text_color="#FF8B8B")
            return
        set_busy(True)
        status.configure(text="Testando conexão com o Gemini...", text_color="#A9AFBC")
        threading.Thread(
            target=lambda: test_results.put(test_gemini_api_key(key)),
            name="JARVIS-GEMINI-KEY-TEST",
            daemon=True,
        ).start()
        window.after(100, poll_test_results)

    def do_save():
        key = entry.get().strip()
        try:
            save_gemini_api_key(key)
        except ValueError as exc:
            status.configure(text=str(exc), text_color="#FF8B8B")
            return
        except Exception:
            status.configure(text="Não consegui proteger a chave no Windows.", text_color="#FF8B8B")
            return
        result["saved"] = True
        window.destroy()

    test_button.configure(command=do_test)
    save_button.configure(command=do_save)
    entry.bind("<Return>", lambda _event: do_save())
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    try:
        entry.focus_set()
    except Exception:
        pass

    if owns_root:
        window.mainloop()
    else:
        parent.wait_window(window)
    return bool(result["saved"])


def ensure_gemini_configured() -> bool:
    if load_gemini_api_key():
        return True
    return show_api_key_dialog(first_run=True)


__all__ = ["ensure_gemini_configured", "show_api_key_dialog", "test_gemini_api_key"]
