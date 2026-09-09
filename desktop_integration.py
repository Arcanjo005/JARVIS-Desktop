"""
JARVIS - Integração com Desktop do Windows

Recursos:
- Ctrl + Espaço: mostra/oculta a esfera.
- Bandeja do Windows com menu do JARVIS.
- Inicialização automática via HKCU / Windows Run.
- Não exige privilégios de administrador.
"""

from __future__ import annotations

import os
import sys
import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

try:
    from PIL import Image, ImageDraw, ImageFilter
except Exception:
    Image = None
    ImageDraw = None
    ImageFilter = None

try:
    import pystray
except Exception:
    pystray = None


class DesktopIntegration:
    APP_NAME = "JARVIS Assistant"
    STARTUP_VALUE_NAME = "JARVIS Assistant"

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000

    VK_SPACE = 0x20

    HOTKEY_ID = 0x5A10

    def __init__(
        self,
        project_dir: str,
        logger=None,
        on_toggle_orb: Optional[Callable[[], None]] = None,
        on_show_chat: Optional[Callable[[], None]] = None,
        on_listen_now: Optional[Callable[[], None]] = None,
        on_move_orb: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        auto_enable_startup: bool = True,
    ):
        self.project_dir = Path(project_dir)
        self.logger = logger

        self.on_toggle_orb = on_toggle_orb
        self.on_show_chat = on_show_chat
        self.on_listen_now = on_listen_now
        self.on_move_orb = on_move_orb
        self.on_exit = on_exit

        self.auto_enable_startup = bool(auto_enable_startup)

        self.settings_path = (
            self.project_dir
            / "data"
            / "desktop_settings.json"
        )
        self.settings_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.tray_icon = None
        self.tray_ready = False
        self.hotkey_ready = False
        self.hotkey_name = "Ctrl + Espaço"

        self._hotkey_thread = None
        self._hotkey_thread_id = None
        self._stop_event = threading.Event()

    # --------------------------------------------------------
    # Log
    # --------------------------------------------------------
    def _log(self, level: str, message: str):
        if not self.logger:
            return

        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "DESKTOP")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------
    def start(self):
        self._stop_event.clear()

        # Só ativa automaticamente na PRIMEIRA vez.
        # Se o usuário desligar depois no menu, a preferência é respeitada.
        settings = self._load_settings()

        if (
            self.auto_enable_startup
            and not settings.get(
                "startup_initialized",
                False
            )
        ):
            try:
                enabled = self.enable_startup()

                settings[
                    "startup_initialized"
                ] = True
                settings[
                    "startup_enabled"
                ] = bool(enabled)

                self._save_settings(
                    settings
                )

            except Exception as exc:
                self._log(
                    "warning",
                    f"Não foi possível registrar inicialização automática: {exc}"
                )

        self._start_hotkey()
        self._start_tray()

    def stop(self):
        self._stop_event.set()

        self._stop_hotkey()

        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception:
            pass

        self.tray_icon = None
        self.tray_ready = False

    def status(self) -> dict:
        return {
            "tray_ready": self.tray_ready,
            "hotkey_ready": self.hotkey_ready,
            "hotkey": self.hotkey_name,
            "startup_enabled": self.is_startup_enabled(),
        }

    def _load_settings(self) -> dict:
        try:
            if self.settings_path.exists():
                data = json.loads(
                    self.settings_path.read_text(
                        encoding="utf-8"
                    )
                )

                if isinstance(data, dict):
                    return data
        except Exception:
            pass

        return {}

    def _save_settings(self, data: dict):
        try:
            self.settings_path.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf-8"
            )
        except Exception as exc:
            self._log(
                "warning",
                f"Não foi possível salvar preferências do desktop: {exc}"
            )

    # --------------------------------------------------------
    # Startup with Windows
    # --------------------------------------------------------
    def _startup_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'

        main_py = self.project_dir / "main.py"

        python_exe = Path(sys.executable)
        pythonw = python_exe.with_name("pythonw.exe")

        runner = (
            pythonw
            if pythonw.exists()
            else python_exe
        )

        return f'"{runner}" "{main_py}"'

    def enable_startup(self) -> bool:
        if os.name != "nt":
            return False

        import winreg

        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion\Run"
        )

        command = self._startup_command()

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                self.STARTUP_VALUE_NAME,
                0,
                winreg.REG_SZ,
                command,
            )

        self._log(
            "info",
            f"Iniciar com Windows: ATIVO | {command}"
        )
        return True

    def disable_startup(self) -> bool:
        if os.name != "nt":
            return False

        import winreg

        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion\Run"
        )

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(
                    key,
                    self.STARTUP_VALUE_NAME,
                )
        except FileNotFoundError:
            pass

        self._log(
            "info",
            "Iniciar com Windows: DESATIVADO"
        )
        return True

    def is_startup_enabled(self) -> bool:
        if os.name != "nt":
            return False

        import winreg

        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion\Run"
        )

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_QUERY_VALUE,
            ) as key:
                value, _ = winreg.QueryValueEx(
                    key,
                    self.STARTUP_VALUE_NAME,
                )

            return bool(str(value).strip())

        except Exception:
            return False

    def toggle_startup(self):
        try:
            if self.is_startup_enabled():
                self.disable_startup()
            else:
                enabled = bool(
                    self.enable_startup()
                )

            settings = self._load_settings()
            settings["startup_initialized"] = True
            settings["startup_enabled"] = bool(
                self.is_startup_enabled()
            )
            self._save_settings(settings)

            if self.tray_icon:
                try:
                    self.tray_icon.update_menu()
                except Exception:
                    pass

        except Exception as exc:
            self._log(
                "error",
                f"Erro ao alternar inicialização automática: {exc}"
            )

    # --------------------------------------------------------
    # System tray
    # --------------------------------------------------------
    def _create_tray_image(self):
        if Image is None:
            return None

        size = 128

        image = Image.new(
            "RGBA",
            (size, size),
            (0, 0, 0, 0),
        )

        # Halo.
        if ImageDraw is not None and ImageFilter is not None:
            halo = Image.new(
                "RGBA",
                (size, size),
                (0, 0, 0, 0),
            )
            hd = ImageDraw.Draw(halo)
            hd.ellipse(
                (22, 22, 106, 106),
                fill=(22, 140, 255, 130),
            )
            halo = halo.filter(
                ImageFilter.GaussianBlur(14)
            )
            image = Image.alpha_composite(
                image,
                halo
            )

        draw = ImageDraw.Draw(image)

        # Esfera azul simples e legível em ícone pequeno.
        for radius in range(43, 8, -1):
            t = (
                (43 - radius)
                / max(1, (43 - 8))
            )

            r = int(
                8 + 38 * t
            )
            g = int(
                62 + 120 * t
            )
            b = int(
                120 + 135 * t
            )

            draw.ellipse(
                (
                    64 - radius,
                    64 - radius,
                    64 + radius,
                    64 + radius,
                ),
                fill=(r, g, b, 255),
            )

        draw.ellipse(
            (40, 34, 58, 48),
            fill=(230, 248, 255, 230),
        )

        return image

    def _start_tray(self):
        if pystray is None:
            self._log(
                "warning",
                "pystray não instalado; bandeja desativada."
            )
            return

        try:
            image = self._create_tray_image()

            menu = pystray.Menu(
                pystray.MenuItem(
                    "Abrir JARVIS",
                    lambda icon, item: self._safe_call(
                        self.on_show_chat
                    ),
                    default=True,
                ),
                pystray.MenuItem(
                    "Mostrar / ocultar esfera",
                    lambda icon, item: self._safe_call(
                        self.on_toggle_orb
                    ),
                ),
                pystray.MenuItem(
                    "Ouvir agora",
                    lambda icon, item: self._safe_call(
                        self.on_listen_now
                    ),
                ),
                pystray.MenuItem(
                    "Mover esfera",
                    lambda icon, item: self._safe_call(
                        self.on_move_orb
                    ),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Iniciar com Windows",
                    lambda icon, item: self.toggle_startup(),
                    checked=lambda item: self.is_startup_enabled(),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Sair do JARVIS",
                    lambda icon, item: self._safe_call(
                        self.on_exit
                    ),
                ),
            )

            self.tray_icon = pystray.Icon(
                "JARVIS",
                image,
                "JARVIS - Assistente",
                menu,
            )

            # run_detached integra o tray sem bloquear o mainloop do Tk.
            self.tray_icon.run_detached()
            self.tray_ready = True

            self._log(
                "info",
                "Ícone da bandeja iniciado."
            )

        except Exception as exc:
            self.tray_ready = False
            self._log(
                "error",
                f"Falha ao iniciar bandeja: {exc}"
            )

    def _safe_call(self, callback):
        if not callable(callback):
            return

        try:
            callback()
        except Exception as exc:
            self._log(
                "error",
                f"Callback de desktop falhou: {exc}"
            )

    # --------------------------------------------------------
    # Global hotkey
    # --------------------------------------------------------
    def _start_hotkey(self):
        if os.name != "nt":
            return

        if (
            self._hotkey_thread
            and self._hotkey_thread.is_alive()
        ):
            return

        self._hotkey_thread = threading.Thread(
            target=self._hotkey_loop,
            name="JARVIS-HOTKEY",
            daemon=True,
        )
        self._hotkey_thread.start()

    def _hotkey_loop(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._hotkey_thread_id = (
            kernel32.GetCurrentThreadId()
        )

        modifiers = (
            self.MOD_CONTROL
            | self.MOD_NOREPEAT
        )

        registered = bool(
            user32.RegisterHotKey(
                None,
                self.HOTKEY_ID,
                modifiers,
                self.VK_SPACE,
            )
        )

        if not registered:
            # Fallback: Ctrl + Alt + Espaço.
            modifiers = (
                self.MOD_CONTROL
                | self.MOD_ALT
                | self.MOD_NOREPEAT
            )

            registered = bool(
                user32.RegisterHotKey(
                    None,
                    self.HOTKEY_ID,
                    modifiers,
                    self.VK_SPACE,
                )
            )

            if registered:
                self.hotkey_name = (
                    "Ctrl + Alt + Espaço"
                )

        self.hotkey_ready = registered

        if not registered:
            self._log(
                "warning",
                "Não foi possível registrar o atalho global."
            )
            return

        self._log(
            "info",
            f"Atalho global ativo: {self.hotkey_name}"
        )

        message = wintypes.MSG()

        try:
            while not self._stop_event.is_set():
                result = user32.GetMessageW(
                    ctypes.byref(message),
                    None,
                    0,
                    0,
                )

                if result <= 0:
                    break

                if (
                    message.message == self.WM_HOTKEY
                    and message.wParam == self.HOTKEY_ID
                ):
                    self._safe_call(
                        self.on_toggle_orb
                    )

        finally:
            try:
                user32.UnregisterHotKey(
                    None,
                    self.HOTKEY_ID,
                )
            except Exception:
                pass

            self.hotkey_ready = False

    def _stop_hotkey(self):
        if os.name != "nt":
            return

        thread_id = self._hotkey_thread_id

        if not thread_id:
            return

        try:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(
                int(thread_id),
                self.WM_QUIT,
                0,
                0,
            )
        except Exception:
            pass

        self._hotkey_thread_id = None
