"""
JARVIS - Controle avançado de janelas e múltiplos monitores.

Sem dependência de pywin32:
- EnumWindows / ShowWindow / SetWindowPos via ctypes.
- Monitores via API nativa do Windows, com mss como fallback.
- Descobre o monitor do aplicativo em primeiro plano.
"""

from __future__ import annotations

import ctypes
import math
import os
import re
import time
import unicodedata
from ctypes import wintypes
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class AdvancedWindows:
    SW_HIDE = 0
    SW_SHOWNORMAL = 1
    SW_SHOWMINIMIZED = 2
    SW_SHOWMAXIMIZED = 3
    SW_RESTORE = 9
    SW_MINIMIZE = 6
    SW_MAXIMIZE = 3

    SWP_NOZORDER = 0x0004
    SWP_SHOWWINDOW = 0x0040

    WM_SYSCOMMAND = 0x0112
    SC_MINIMIZE = 0xF020
    SC_MAXIMIZE = 0xF030
    SC_RESTORE = 0xF120

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    GW_OWNER = 4

    def __init__(self, logger=None):
        self.logger = logger
        self.user32 = None
        self.kernel32 = None

        if os.name == "nt":
            self.user32 = ctypes.windll.user32
            self.kernel32 = ctypes.windll.kernel32

            # Protótipos explícitos evitam truncar HWND em Python/Windows 64-bit.
            try:
                self.user32.GetForegroundWindow.restype = wintypes.HWND
                self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
                self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
                self.user32.IsZoomed.argtypes = [wintypes.HWND]
                self.user32.IsZoomed.restype = wintypes.BOOL
                self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
                self.user32.SetForegroundWindow.restype = wintypes.BOOL

                self.user32.GetWindowRect.argtypes = [
                    wintypes.HWND,
                    ctypes.POINTER(RECT),
                ]
                self.user32.GetWindowRect.restype = wintypes.BOOL

                self.user32.GetWindowTextLengthW.argtypes = [
                    wintypes.HWND,
                ]
                self.user32.GetWindowTextLengthW.restype = ctypes.c_int

                self.user32.GetWindowTextW.argtypes = [
                    wintypes.HWND,
                    wintypes.LPWSTR,
                    ctypes.c_int,
                ]
                self.user32.GetWindowTextW.restype = ctypes.c_int

                self.user32.ShowWindow.argtypes = [
                    wintypes.HWND,
                    ctypes.c_int,
                ]
                self.user32.ShowWindow.restype = wintypes.BOOL
                self.user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
                self.user32.ShowWindowAsync.restype = wintypes.BOOL
                self.user32.IsIconic.argtypes = [wintypes.HWND]
                self.user32.IsIconic.restype = wintypes.BOOL
                self.user32.BringWindowToTop.argtypes = [wintypes.HWND]
                self.user32.BringWindowToTop.restype = wintypes.BOOL
                self.user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                self.user32.PostMessageW.restype = wintypes.BOOL
                self.user32.MoveWindow.argtypes = [
                    wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL
                ]
                self.user32.MoveWindow.restype = wintypes.BOOL
                self.user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
                self.user32.AttachThreadInput.restype = wintypes.BOOL
                if self.kernel32:
                    self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD

                self.user32.SetWindowPos.argtypes = [
                    wintypes.HWND,
                    wintypes.HWND,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    wintypes.UINT,
                ]
                self.user32.SetWindowPos.restype = wintypes.BOOL
                try:
                    self.user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
                    self.user32.GetWindow.restype = wintypes.HWND
                except Exception:
                    pass
                try:
                    get_long = getattr(self.user32, "GetWindowLongPtrW", None) or getattr(self.user32, "GetWindowLongW", None)
                    if get_long is not None:
                        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
                        get_long.restype = ctypes.c_ssize_t
                except Exception:
                    pass

            except Exception:
                pass

    def _log(self, level: str, message: str):
        if not self.logger:
            return

        try:
            fn = getattr(self.logger, level, None)
            if callable(fn):
                try:
                    fn(message, "WINDOWS")
                except TypeError:
                    fn(message)
        except Exception:
            pass

    @staticmethod
    def _normalize(value: str) -> str:
        value = unicodedata.normalize(
            "NFKD",
            str(value or "")
        )
        value = "".join(
            c for c in value
            if not unicodedata.combining(c)
        )
        value = value.lower()
        value = re.sub(
            r"[^a-z0-9]+",
            " ",
            value
        )
        return re.sub(
            r"\s+",
            " ",
            value
        ).strip()

    # --------------------------------------------------------
    # Monitores
    # --------------------------------------------------------
    def _native_windows_monitors(self) -> List[Dict]:
        """Enumera monitores por DISPLAYn e preserva coordenadas virtuais."""
        if os.name != "nt" or not self.user32:
            return []
        monitors: List[Dict] = []
        try:
            MonitorEnumProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL,
                wintypes.HANDLE,
                wintypes.HDC,
                ctypes.POINTER(RECT),
                wintypes.LPARAM,
            )

            def callback(hmonitor, hdc, rect_ptr, lparam):
                info = MONITORINFOEXW()
                info.cbSize = ctypes.sizeof(MONITORINFOEXW)
                if self.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                    device = str(info.szDevice or "")
                    match = re.search(r"DISPLAY(\d+)$", device, flags=re.I)
                    native_number = int(match.group(1)) if match else None
                    left = int(info.rcMonitor.left)
                    top = int(info.rcMonitor.top)
                    right = int(info.rcMonitor.right)
                    bottom = int(info.rcMonitor.bottom)
                    monitors.append({
                        "index": native_number,
                        "device": device,
                        "primary": bool(int(info.dwFlags) & 1),
                        "left": left,
                        "top": top,
                        "width": right - left,
                        "height": bottom - top,
                        "right": right,
                        "bottom": bottom,
                    })
                return True

            proc = MonitorEnumProc(callback)
            ok = self.user32.EnumDisplayMonitors(None, None, proc, 0)
            if not ok or not monitors:
                return []

            # Quando os device names possuem DISPLAYn únicos, esse n é o ID
            # exposto ao restante do JARVIS. Se a API devolver algo incomum,
            # numeramos de forma estável sem perder a geometria.
            native = [m.get("index") for m in monitors]
            if any(n is None for n in native) or len(set(native)) != len(native):
                monitors.sort(key=lambda m: (not m.get("primary", False), m["left"], m["top"]))
                for idx, item in enumerate(monitors, start=1):
                    item["index"] = idx
            else:
                monitors.sort(key=lambda m: int(m["index"]))
            return monitors
        except Exception as exc:
            self._log("warning", f"Enumeração nativa de monitores falhou: {exc}")
            return []

    def get_monitors(self) -> List[Dict]:
        native = self._native_windows_monitors()
        if native:
            return native

        try:
            import mss
            with mss.mss() as sct:
                raw = list(sct.monitors[1:])

            monitors = []
            for index, item in enumerate(raw, start=1):
                monitors.append({
                    "index": index,
                    "device": f"MSS{index}",
                    "primary": bool(index == 1),
                    "left": int(item["left"]),
                    "top": int(item["top"]),
                    "width": int(item["width"]),
                    "height": int(item["height"]),
                    "right": int(item["left"] + item["width"]),
                    "bottom": int(item["top"] + item["height"]),
                })
            return monitors

        except Exception as exc:
            self._log("warning", f"Não foi possível listar monitores: {exc}")
            return [{
                "index": 1,
                "device": "FALLBACK1",
                "primary": True,
                "left": 0,
                "top": 0,
                "width": 1920,
                "height": 1080,
                "right": 1920,
                "bottom": 1080,
            }]

    def _point_monitor(
        self,
        x: int,
        y: int
    ) -> Dict:
        monitors = self.get_monitors()

        for monitor in monitors:
            if (
                monitor["left"] <= x < monitor["right"]
                and monitor["top"] <= y < monitor["bottom"]
            ):
                return monitor

        # Mais próximo do ponto.
        def distance(m):
            cx = (
                m["left"]
                + m["right"]
            ) / 2
            cy = (
                m["top"]
                + m["bottom"]
            ) / 2
            return math.hypot(
                cx - x,
                cy - y
            )

        return min(
            monitors,
            key=distance
        )

    def get_cursor_position(self) -> Tuple[int, int]:
        if not self.user32:
            return (0, 0)

        point = POINT()

        if self.user32.GetCursorPos(
            ctypes.byref(point)
        ):
            return (
                int(point.x),
                int(point.y)
            )

        return (0, 0)

    def get_foreground_window_rect(
        self
    ) -> Optional[Tuple[int, int, int, int]]:
        if not self.user32:
            return None

        hwnd = self.user32.GetForegroundWindow()

        if not hwnd:
            return None

        rect = RECT()

        if not self.user32.GetWindowRect(
            hwnd,
            ctypes.byref(rect)
        ):
            return None

        if (
            rect.right <= rect.left
            or rect.bottom <= rect.top
        ):
            return None

        return (
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )

    def get_active_monitor(self) -> Dict:
        """
        Prioridade:
        1. centro da janela em primeiro plano;
        2. posição do mouse.
        """
        rect = self.get_foreground_window_rect()

        if rect:
            left, top, right, bottom = rect
            center_x = (
                left + right
            ) // 2
            center_y = (
                top + bottom
            ) // 2

            return self._point_monitor(
                center_x,
                center_y
            )

        x, y = self.get_cursor_position()
        return self._point_monitor(
            x,
            y
        )

    def get_monitor(
        self,
        index: int
    ) -> Optional[Dict]:
        for monitor in self.get_monitors():
            if monitor["index"] == int(index):
                return monitor

        return None

    def overlay_position(
        self,
        width: int,
        height: int,
        bottom_margin: int = 24
    ) -> Tuple[int, int]:
        monitor = self.get_active_monitor()

        x = int(
            monitor["left"]
            + (
                monitor["width"]
                - width
            ) / 2
        )

        y = int(
            monitor["bottom"]
            - height
            - bottom_margin
        )

        x = max(
            monitor["left"],
            min(
                x,
                monitor["right"] - width
            )
        )
        y = max(
            monitor["top"],
            min(
                y,
                monitor["bottom"] - height
            )
        )

        return (x, y)

    # --------------------------------------------------------
    # Janelas
    # --------------------------------------------------------
    def _window_title(
        self,
        hwnd
    ) -> str:
        if not self.user32:
            return ""

        length = self.user32.GetWindowTextLengthW(
            hwnd
        )

        if length <= 0:
            return ""

        buffer = ctypes.create_unicode_buffer(
            length + 1
        )
        self.user32.GetWindowTextW(
            hwnd,
            buffer,
            length + 1
        )
        return buffer.value.strip()

    def _process_name_for_hwnd(self, hwnd) -> str:
        if not self.user32:
            return ""
        try:
            pid_value = wintypes.DWORD(0)
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_value))
            pid = int(pid_value.value or 0)
            if not pid:
                return ""
            import psutil
            return str(psutil.Process(pid).name() or "").strip()
        except Exception:
            return ""

    def _window_owner(self, hwnd) -> int:
        try:
            return int(self.user32.GetWindow(hwnd, self.GW_OWNER) or 0)
        except Exception:
            return 0

    def _window_ex_style(self, hwnd) -> int:
        try:
            fn = getattr(self.user32, "GetWindowLongPtrW", None) or getattr(self.user32, "GetWindowLongW", None)
            return int(fn(hwnd, self.GWL_EXSTYLE) or 0) if fn else 0
        except Exception:
            return 0

    def _window_state(self, hwnd) -> str:
        try:
            if bool(self.user32.IsIconic(hwnd)):
                return "minimized"
            if bool(self.user32.IsZoomed(hwnd)):
                return "maximized"
        except Exception:
            pass
        return "normal"

    def _window_item(self, hwnd, require_visible: bool = True) -> Optional[Dict]:
        if not self.user32 or not hwnd:
            return None
        try:
            if require_visible and not self.user32.IsWindowVisible(hwnd):
                return None
            rect = RECT()
            if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            width, height = rect.right - rect.left, rect.bottom - rect.top
            # Janelas minimizadas costumam ir para coordenadas sentinela do Windows
            # e podem ficar com retângulo ~160x28. Elas continuam sendo janelas
            # válidas e precisam permanecer resolvíveis para "expande/restaura OBS".
            try:
                is_iconic = bool(self.user32.IsIconic(hwnd))
            except Exception:
                is_iconic = False
            if not is_iconic and (width < 40 or height < 30):
                return None
            if is_iconic and (width <= 0 or height <= 0):
                return None
            title = self._window_title(hwnd)
            pid_value = wintypes.DWORD(0)
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_value))
            pid = int(pid_value.value or 0)
            ex_style = self._window_ex_style(hwnd)
            owner = self._window_owner(hwnd)
            try:
                foreground = int(self.user32.GetForegroundWindow() or 0) == int(hwnd)
            except Exception:
                foreground = False
            return {
                "hwnd": int(hwnd),
                "title": title or self._process_name_for_hwnd(hwnd) or "janela atual",
                "pid": pid,
                "process_name": self._process_name_for_hwnd(hwnd),
                "left": int(rect.left), "top": int(rect.top),
                "right": int(rect.right), "bottom": int(rect.bottom),
                "width": int(width), "height": int(height),
                "area": max(0, int(width)) * max(0, int(height)),
                "owner_hwnd": owner,
                "ex_style": ex_style,
                "is_tool_window": bool(ex_style & self.WS_EX_TOOLWINDOW),
                "is_iconic": bool(is_iconic),
                "state": self._window_state(hwnd),
                "foreground": foreground,
            }
        except Exception:
            return None

    def list_windows(self) -> List[Dict]:
        if not self.user32:
            return []
        windows = []
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, lparam):
            try:
                item = self._window_item(hwnd, require_visible=True)
                if item and item.get("title"):
                    windows.append(item)
            except Exception:
                pass
            return True

        self.user32.EnumWindows(EnumProc(callback), 0)
        return windows

    def _foreground_item(self) -> Optional[Dict]:
        if not self.user32:
            return None
        try:
            hwnd = self.user32.GetForegroundWindow()
            return self._window_item(hwnd, require_visible=False)
        except Exception:
            return None

    def active_window_title(self) -> str:
        item = self._foreground_item()
        return str(item.get("title") or "") if item else ""

    def list_open_applications(self) -> List[Dict]:
        """Agrupa janelas visíveis por aplicativo, removendo shells/hosts óbvios."""
        skip_processes = {
            "dwm.exe", "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe",
            "shellexperiencehost.exe", "textinputhost.exe", "ctfmon.exe", "lockapp.exe",
        }
        skip_titles = {"program manager", "windows input experience"}
        aliases = {
            "opera.exe": "Opera",
            "obs64.exe": "OBS Studio", "obs32.exe": "OBS Studio",
            "discord.exe": "Discord", "spotify.exe": "Spotify",
            "code.exe": "Visual Studio Code", "chrome.exe": "Google Chrome",
            "msedge.exe": "Microsoft Edge", "firefox.exe": "Firefox", "brave.exe": "Brave",
            "explorer.exe": "Explorador de Arquivos",
            "winword.exe": "Microsoft Word", "excel.exe": "Microsoft Excel",
            "powerpnt.exe": "Microsoft PowerPoint",
            "photoshop.exe": "Adobe Photoshop", "illustrator.exe": "Adobe Illustrator",
        }
        active_title = self.active_window_title()
        grouped: Dict[str, Dict] = {}
        for item in self.list_windows():
            title = str(item.get("title") or "").strip()
            proc = str(item.get("process_name") or "").strip().lower()
            if not title or title.lower() in skip_titles or proc in skip_processes:
                continue
            title_norm = self._normalize(title)
            if "jarvis" in title_norm or "zero assistente" in title_norm:
                label = "JARVIS"
            else:
                label = aliases.get(proc)
                if not label:
                    stem = os.path.splitext(os.path.basename(proc))[0].replace("_", " ").strip()
                    label = stem.title() if stem else title.split(" - ")[-1].strip()
            if not label:
                continue
            row = grouped.setdefault(label, {"name": label, "titles": [], "window_count": 0, "active": False})
            row["titles"].append(title)
            row["window_count"] = len(row["titles"])
            if active_title and title == active_title:
                row["active"] = True
        return sorted(grouped.values(), key=lambda row: (not bool(row.get("active")), str(row.get("name", "")).lower()))

    def _clean_window_query(self, query: str) -> str:
        q = self._normalize(query)
        q = re.sub(r"^(?:a |o )?(?:janela|programa|aplicativo) (?:do|da|de) ", "", q)
        q = re.sub(r"^(?:o |a )?(?:programa|aplicativo) ", "", q)
        return q.strip()

    def _resolve_window(self, query: str, min_score: float = 0.72) -> Optional[Dict]:
        q = self._clean_window_query(query)
        generic = {
            "", "isso", "essa", "isto", "janela", "janela atual",
            "essa janela", "esta janela", "a janela", "tela", "essa tela", "tela atual",
            "janela aberta", "a janela aberta", "a janela que esta aberta",
            "o que esta aberto", "o que ta aberto",
            "programa", "programa atual", "aplicativo", "aplicativo atual",
            "janela ativa", "programa ativo", "aplicativo ativo",
        }
        if q in generic:
            return self._foreground_item()
        return self.find_window(q, min_score=min_score)

    def inspect_window(self, query: str) -> Optional[Dict]:
        """Snapshot verificavel usado pelo Context Engine/undo/performance."""
        item = self._resolve_window(query, min_score=0.60)
        if not item:
            return None
        result = dict(item)
        try:
            cx = (int(item["left"]) + int(item["right"])) // 2
            cy = (int(item["top"]) + int(item["bottom"])) // 2
            result["monitor"] = int(self._point_monitor(cx, cy).get("index", 1))
        except Exception:
            result["monitor"] = None
        result["state"] = self._window_state(item.get("hwnd"))
        return result

    def _force_foreground(self, hwnd) -> bool:
        """Tenta focar o HWND sem depender do título da janela."""
        if not self.user32 or not hwnd:
            return False
        try:
            if int(self.user32.GetForegroundWindow() or 0) == int(hwnd):
                return True
        except Exception:
            pass
        try:
            self.user32.BringWindowToTop(hwnd)
            self.user32.SetForegroundWindow(hwnd)
            time.sleep(0.04)
            if int(self.user32.GetForegroundWindow() or 0) == int(hwnd):
                return True
        except Exception:
            pass

        # Windows pode bloquear SetForegroundWindow entre threads. Anexa
        # temporariamente as filas de input e tenta de novo.
        attached = []
        try:
            current_tid = int(self.kernel32.GetCurrentThreadId()) if self.kernel32 else 0
            target_tid = int(self.user32.GetWindowThreadProcessId(hwnd, None) or 0)
            fg = self.user32.GetForegroundWindow()
            fg_tid = int(self.user32.GetWindowThreadProcessId(fg, None) or 0) if fg else 0
            for other in (target_tid, fg_tid):
                if current_tid and other and other != current_tid:
                    if self.user32.AttachThreadInput(current_tid, other, True):
                        attached.append((current_tid, other))
            self.user32.BringWindowToTop(hwnd)
            self.user32.SetForegroundWindow(hwnd)
            time.sleep(0.05)
            return int(self.user32.GetForegroundWindow() or 0) == int(hwnd)
        except Exception:
            return False
        finally:
            for a, b in reversed(attached):
                try:
                    self.user32.AttachThreadInput(a, b, False)
                except Exception:
                    pass

    def _window_state_matches(self, hwnd, command: int) -> bool:
        try:
            if command == self.SW_MINIMIZE:
                return bool(self.user32.IsIconic(hwnd))
            if command == self.SW_MAXIMIZE:
                return bool(self.user32.IsZoomed(hwnd))
            if command == self.SW_RESTORE:
                return not bool(self.user32.IsIconic(hwnd)) and not bool(self.user32.IsZoomed(hwnd))
        except Exception:
            pass
        return False

    def _apply_show_command(self, hwnd, command: int) -> bool:
        sys_command = {
            self.SW_MINIMIZE: self.SC_MINIMIZE,
            self.SW_MAXIMIZE: self.SC_MAXIMIZE,
            self.SW_RESTORE: self.SC_RESTORE,
        }.get(command)
        try:
            self.user32.ShowWindowAsync(hwnd, command)
        except Exception:
            try:
                self.user32.ShowWindow(hwnd, command)
            except Exception:
                pass
        if sys_command is not None:
            try:
                self.user32.PostMessageW(hwnd, self.WM_SYSCOMMAND, sys_command, 0)
            except Exception:
                pass
        time.sleep(0.12)
        if self._window_state_matches(hwnd, command):
            return True

        # Último fallback: atalhos do Windows somente se conseguimos garantir
        # que o HWND correto está em primeiro plano.
        if not self._force_foreground(hwnd):
            return False
        try:
            import pyautogui
            if command == self.SW_MAXIMIZE:
                pyautogui.hotkey("win", "up")
            elif command == self.SW_MINIMIZE:
                pyautogui.hotkey("win", "down")
                time.sleep(0.06)
                if not self.user32.IsIconic(hwnd):
                    pyautogui.hotkey("win", "down")
            elif command == self.SW_RESTORE:
                if self.user32.IsIconic(hwnd):
                    pyautogui.hotkey("win", "up")
                elif self.user32.IsZoomed(hwnd):
                    pyautogui.hotkey("win", "down")
            time.sleep(0.14)
        except Exception:
            return False
        return self._window_state_matches(hwnd, command)

    def _score_window(self, query: str, title: str, process_name: str = "") -> float:
        q = self._clean_window_query(query)
        t = self._normalize(title)
        p = self._normalize(process_name).replace(" exe", "")
        if not q:
            return 0.0
        aliases = {
            "opera gx": ("opera",), "opera": ("opera",),
            "photoshop": ("photoshop",), "illustrator": ("illustrator",),
            "spotify": ("spotify",), "obs": ("obs64", "obs32", "obs"),
            "revo": ("revounin", "revo"), "bloodstrike": ("bloodstrike",),
            "explorer": ("explorer",),
        }
        wanted = aliases.get(q, (q,))
        if p and any(token == p or token in p for token in wanted):
            return 0.98
        if not t:
            return 0.0
        if q == t:
            return 1.0
        if t.startswith(q):
            return 0.96
        if q in t:
            return 0.93
        q_tokens, t_tokens = set(q.split()), set(t.split())
        overlap = len(q_tokens & t_tokens) / max(1, len(q_tokens))
        ratio = SequenceMatcher(None, q, t).ratio()
        return max(ratio * 0.78, overlap * 0.90)

    def find_window(
        self,
        query: str,
        min_score: float = 0.72
    ) -> Optional[Dict]:
        candidates = []

        for item in self.list_windows():
            score = self._score_window(
                query,
                item["title"],
                item.get("process_name", "")
            )
            if score < min_score:
                continue

            # Programas como Photoshop/Illustrator possuem palettes e tool
            # windows no mesmo processo. O resolver prefere a janela principal:
            # top-level sem owner, nao-tool e com maior area util.
            owner = int(item.get("owner_hwnd") or 0)
            tool = bool(item.get("is_tool_window"))
            area = max(0, int(item.get("area") or (item.get("width", 0) * item.get("height", 0))))
            main_bonus = 0.0
            main_bonus += 0.055 if owner == 0 else -0.055
            main_bonus += 0.055 if not tool else -0.14
            if area >= 600_000:
                main_bonus += 0.055
            elif area >= 220_000:
                main_bonus += 0.025
            elif area < 60_000:
                main_bonus -= 0.08
            if item.get("foreground"):
                main_bonus += 0.015
            rank = score + main_bonus
            candidates.append((rank, score, area, item))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[2]), reverse=True)
        best_rank, best_score, _best_area, best = candidates[0]

        # Ambiguidade continua protegida quando nem a semantica nem a nocao de
        # janela principal conseguem separar candidatos.
        if len(candidates) > 1:
            second_rank, second_score, _second_area, _second = candidates[1]
            if best_score < 0.90 and (best_rank - second_rank) < 0.05:
                return None

        return best

    def _show_window(
        self,
        query: str,
        command: int,
        verb: str
    ) -> str:
        if not self.user32:
            return "Controle de janelas disponível apenas no Windows."

        item = None
        for _attempt in range(3):
            item = self._resolve_window(query, min_score=0.64)
            if item:
                break
            time.sleep(0.07)
        if not item:
            return f"Não encontrei uma janela de '{query}' com segurança."

        hwnd = item["hwnd"]
        ok = self._apply_show_command(hwnd, command)
        if not ok:
            return f"Encontrei '{item['title']}', mas o Windows não confirmou a ação de {verb.lower()}."

        self._log("info", f"{verb}: {item['title']} | processo={item.get('process_name','')}")
        return f"✓ {verb}: {item['title']}."

    def minimize(
        self,
        query: str
    ) -> str:
        return self._show_window(
            query,
            self.SW_MINIMIZE,
            "Minimizado"
        )

    def maximize(
        self,
        query: str
    ) -> str:
        return self._show_window(
            query,
            self.SW_MAXIMIZE,
            "Maximizado"
        )

    def restore(
        self,
        query: str
    ) -> str:
        return self._show_window(
            query,
            self.SW_RESTORE,
            "Restaurado"
        )

    def move_to_monitor(self, query: str, monitor_index: int) -> str:
        if not self.user32:
            return "Controle de monitores disponível apenas no Windows."
        item = self._resolve_window(query, min_score=0.60)
        monitor = self.get_monitor(monitor_index)
        if not item:
            return f"Não encontrei uma janela de '{query}' com segurança."
        if not monitor:
            return f"Não existe monitor {monitor_index}. Detectei {len(self.get_monitors())} monitor(es)."

        hwnd = item["hwnd"]
        was_maximized = False
        try:
            was_maximized = bool(self.user32.IsZoomed(hwnd))
        except Exception:
            pass
        try:
            self.user32.ShowWindow(hwnd, self.SW_RESTORE)
        except Exception:
            pass

        width = min(max(640, item["width"]), max(640, monitor["width"] - 80))
        height = min(max(420, item["height"]), max(420, monitor["height"] - 100))
        x = int(monitor["left"] + max(20, (monitor["width"] - width) / 2))
        y = int(monitor["top"] + max(20, (monitor["height"] - height) / 2))
        ok = bool(self.user32.SetWindowPos(
            hwnd, 0, x, y, int(width), int(height),
            self.SWP_NOZORDER | self.SWP_SHOWWINDOW
        ))

        # Confirma pelo centro real da janela; se falhar, tenta atalho Win+Shift.
        if ok:
            try:
                rect = RECT()
                if self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    cx, cy = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
                    actual = self._point_monitor(cx, cy).get("index")
                    ok = int(actual) == int(monitor_index)
            except Exception:
                pass

        if not ok:
            try:
                ok = bool(self.user32.MoveWindow(hwnd, x, y, int(width), int(height), True))
                time.sleep(0.10)
                if ok:
                    rect2 = RECT()
                    if self.user32.GetWindowRect(hwnd, ctypes.byref(rect2)):
                        cx2, cy2 = (rect2.left + rect2.right) // 2, (rect2.top + rect2.bottom) // 2
                        ok = int(self._point_monitor(cx2, cy2).get("index")) == int(monitor_index)
            except Exception:
                ok = False

        if not ok:
            try:
                if not self._force_foreground(hwnd):
                    raise RuntimeError("não foi possível focar a janela correta")
                import pyautogui
                current = self._point_monitor(
                    (item["left"] + item["right"]) // 2,
                    (item["top"] + item["bottom"]) // 2,
                ).get("index", 1)
                key = "right" if int(monitor_index) > int(current) else "left"
                for _ in range(max(1, abs(int(monitor_index) - int(current)))):
                    pyautogui.hotkey("win", "shift", key)
                    time.sleep(0.12)
                ok = True
            except Exception:
                ok = False

        if not ok:
            return f"Não consegui mover '{item['title']}' para o monitor {monitor_index}."
        if was_maximized:
            try:
                self.user32.ShowWindow(hwnd, self.SW_MAXIMIZE)
            except Exception:
                pass
        self._log("info", f"Movido para monitor {monitor_index}: {item['title']}")
        return f"✓ {item['title']} no monitor {monitor_index}."

    def move_to_other_monitor(self, query: str) -> str:
        monitors = self.get_monitors()
        if len(monitors) < 2:
            return "Só detectei um monitor."
        item = self._resolve_window(query, min_score=0.60)
        if not item:
            return f"Não encontrei uma janela de '{query}' com segurança."
        cx = (item["left"] + item["right"]) // 2
        cy = (item["top"] + item["bottom"]) // 2
        current = int(self._point_monitor(cx, cy).get("index", 1))
        target = next((m["index"] for m in monitors if int(m["index"]) != current), monitors[0]["index"])
        return self.move_to_monitor(query, int(target))

    def _foreground_and_next(
        self
    ) -> Tuple[Optional[Dict], Optional[Dict]]:
        windows = self.list_windows()

        if not windows:
            return (None, None)

        foreground = None

        if self.user32:
            hwnd = int(
                self.user32.GetForegroundWindow()
                or 0
            )

            for item in windows:
                if item["hwnd"] == hwnd:
                    foreground = item
                    break

        if foreground is None:
            foreground = windows[0]

        second = next(
            (
                item
                for item in windows
                if item["hwnd"]
                != foreground["hwnd"]
            ),
            None
        )

        return (
            foreground,
            second
        )

    def tile_side_by_side(
        self,
        first_query: Optional[str] = None,
        second_query: Optional[str] = None,
        monitor_index: Optional[int] = None
    ) -> str:
        if not self.user32:
            return "Controle de janelas disponível apenas no Windows."

        if first_query and second_query:
            first = self.find_window(
                first_query
            )
            second = self.find_window(
                second_query
            )
        else:
            first, second = (
                self._foreground_and_next()
            )

        if not first or not second:
            return (
                "Preciso de duas janelas visíveis para colocar lado a lado."
            )

        monitor = (
            self.get_monitor(
                monitor_index
            )
            if monitor_index
            else self.get_active_monitor()
        )

        if not monitor:
            monitor = self.get_active_monitor()

        # Reserva espaço aproximado para a barra de tarefas.
        usable_height = max(
            300,
            monitor["height"] - 48
        )
        half_width = (
            monitor["width"] // 2
        )

        self.user32.ShowWindow(
            first["hwnd"],
            self.SW_RESTORE
        )
        self.user32.ShowWindow(
            second["hwnd"],
            self.SW_RESTORE
        )

        common_flags = (
            self.SWP_NOZORDER
            | self.SWP_SHOWWINDOW
        )

        self.user32.SetWindowPos(
            first["hwnd"],
            0,
            monitor["left"],
            monitor["top"],
            half_width,
            usable_height,
            common_flags
        )

        self.user32.SetWindowPos(
            second["hwnd"],
            0,
            monitor["left"]
            + half_width,
            monitor["top"],
            monitor["width"]
            - half_width,
            usable_height,
            common_flags
        )

        return (
            f"✓ {first['title']} e {second['title']} lado a lado."
        )

    def status(self) -> Dict:
        monitors = self.get_monitors()
        active = self.get_active_monitor()

        return {
            "monitor_count": len(monitors),
            "active_monitor": active["index"],
            "active_window": self.active_window_title(),
            "windows": len(
                self.list_windows()
            ),
        }
