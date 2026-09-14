"""Monitor-aware physical geometry with a portable fallback.

Win32 handles have explicit pointer-sized signatures. Work areas may start at
negative coordinates. CTk sizes are logical; native window positions are pixels.
"""
from __future__ import annotations
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class WorkArea:
    x: int
    y: int
    width: int
    height: int


def clamp_rect(x: int, y: int, width: int, height: int, area: WorkArea, margin: int = 12):
    w = max(1, min(width, area.width-2*margin))
    h = max(1, min(height, area.height-2*margin))
    return (max(area.x+margin, min(x, area.x+area.width-w-margin)),
            max(area.y+margin, min(y, area.y+area.height-h-margin)), w, h)


def monitor_work_area(widget) -> WorkArea:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = user32.MonitorFromWindow(widget.winfo_id(), 2)
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            return WorkArea(r.left, r.top, r.right-r.left, r.bottom-r.top)
    return WorkArea(0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight())


def popup_geometry(panel, anchor, width=420, height=650):
    area = monitor_work_area(anchor)
    scale = float(panel._get_window_scaling())
    x, y, w, h = clamp_rect(anchor.winfo_rootx(), anchor.winfo_rooty()-round(height*scale)-8,
                            round(width*scale), round(height*scale),
                            WorkArea(area.x, area.y, area.width, max(1, area.height-40)))
    return max(1, int(w/scale)), max(1, int(h/scale)), x, y


def fit_window(root, initial=False):
    """Shrink an oversized normal window on its current monitor, never enlarge it."""
    area = monitor_work_area(root)
    scale = float(root._get_window_scaling())
    root.minsize(max(240, min(620, int((area.width-32)/scale))),
                 max(220, min(440, int((area.height-72)/scale))))
    if initial:
        root.geometry(f"{min(1420, int((area.width-48)/scale))}x{min(900, int((area.height-100)/scale))}")
        return area
    if root.state() != "normal":
        return area
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        hwnd = user32.GetAncestor(root.winfo_id(), 2)
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            w, h = rect.right-rect.left, rect.bottom-rect.top
            if w > area.width-24 or h > area.height-24:
                x, y, w, h = clamp_rect(rect.left, rect.top, w, h, area)
                if not user32.SetWindowPos(hwnd, None, x, y, w, h, 0x0014):
                    raise ctypes.WinError(ctypes.get_last_error())
    elif root.winfo_width() > area.width or root.winfo_height() > area.height:
        root.geometry(f"{int((area.width-24)/scale)}x{int((area.height-60)/scale)}")
    return area


def place_popup(panel, anchor, width=420, height=650):
    """Place on the anchor monitor, including monitors left of the primary.

    Tk geometry's negative offsets mean distance from the right/bottom edge,
    not negative desktop coordinates. On Windows use SetWindowPos explicitly.
    """
    w, h, x, y = popup_geometry(panel, anchor, width, height)
    panel.geometry(f"{w}x{h}")
    panel.update_idletasks()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        hwnd = user32.GetAncestor(panel.winfo_id(), 2)
        if not user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0015):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        panel.geometry(f"{w}x{h}{x:+d}{y:+d}")
    return w, h, x, y
