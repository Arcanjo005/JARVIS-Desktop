"""Pixel-anchored JARVIS interface based on the user-approved reference.

This shell intentionally does not reinterpret the concept.  It uses the approved
orb crop, a 1536x960 reference coordinate system, a blurred photographic-style
background, precomposited translucent/frosted panels, and lightweight animated
layers for the orb, waveform and voice states.  The existing JARVIS runtime,
voice engine, updater, memory and command handling remain inherited from gui.py.
"""
from __future__ import annotations

import math
import random
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance, ImageTk

from gui import JarvisGUI as BaseJarvisGUI
from jarvis_reference_orb import load_orb_image
from jarvis_version import PUBLIC_NAME, VERSION as JARVIS_VERSION

try:
    import psutil
except Exception:
    psutil = None


DESIGN_W = 1536
DESIGN_H = 960


def _font(size: int, bold: bool = False):
    candidates = []
    if __import__("os").name == "nt":
        candidates.extend([
            r"C:\Windows\Fonts\seguisb.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\bahnschrift.ttf",
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        ])
    candidates.extend(["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"])
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _rounded_panel(base: Image.Image, box, radius=18, fill=(3, 14, 24, 178), border=(13, 82, 124, 175), width=1):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=border, width=width)
    # A very soft halo makes the panel read as glass over a blurred scene.
    halo = Image.new("RGBA", base.size, (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.rounded_rectangle(box, radius=radius, outline=(23, 110, 161, 50), width=3)
    halo = halo.filter(ImageFilter.GaussianBlur(5))
    base.alpha_composite(halo)
    base.alpha_composite(layer)


def _draw_line_icon(draw: ImageDraw.ImageDraw, kind: str, x: int, y: int, s: int = 22, color=(117, 205, 255, 255), width=2):
    """Small line icons matching the thin cyan icon language of the reference."""
    x0, y0 = x, y
    if kind == "chat":
        draw.rounded_rectangle((x0, y0, x0+s, y0+s-4), radius=4, outline=color, width=width)
        draw.line((x0+5, y0+s-4, x0+5, y0+s+2, x0+10, y0+s-4), fill=color, width=width)
    elif kind == "camera":
        draw.rounded_rectangle((x0, y0+4, x0+s, y0+s-2), radius=4, outline=color, width=width)
        draw.ellipse((x0+7, y0+8, x0+15, y0+16), outline=color, width=width)
        draw.line((x0+5, y0+4, x0+8, y0, x0+15, y0, x0+18, y0+4), fill=color, width=width)
    elif kind == "grid":
        for yy in (0, 12):
            for xx in (0, 12):
                draw.rounded_rectangle((x0+xx, y0+yy, x0+xx+8, y0+yy+8), radius=1, outline=color, width=width)
    elif kind == "folder":
        draw.line((x0, y0+5, x0+8, y0+5, x0+11, y0+8, x0+s, y0+8, x0+s, y0+s, x0, y0+s, x0, y0+5), fill=color, width=width)
    elif kind == "globe":
        draw.ellipse((x0, y0, x0+s, y0+s), outline=color, width=width)
        draw.arc((x0+5, y0, x0+s-5, y0+s), 90, 270, fill=color, width=width)
        draw.arc((x0+5, y0, x0+s-5, y0+s), -90, 90, fill=color, width=width)
        draw.line((x0, y0+s//2, x0+s, y0+s//2), fill=color, width=width)
    elif kind == "nodes":
        cx, cy = x0+s//2, y0+s//2
        for a in range(0, 360, 60):
            px = int(cx + math.cos(math.radians(a))*9)
            py = int(cy + math.sin(math.radians(a))*9)
            draw.ellipse((px-2, py-2, px+2, py+2), outline=color, width=width)
            draw.line((cx, cy, px, py), fill=color, width=1)
        draw.ellipse((cx-3, cy-3, cx+3, cy+3), outline=color, width=width)
    elif kind == "memory":
        draw.arc((x0+2, y0+2, x0+s-2, y0+s-2), 70, 290, fill=color, width=width)
        draw.arc((x0+7, y0+5, x0+s+2, y0+s-5), 110, 250, fill=color, width=width)
        draw.line((x0+4, y0+7, x0, y0+5, x0, y0+14), fill=color, width=width)
    elif kind == "gear":
        cx, cy = x0+s//2, y0+s//2
        draw.ellipse((cx-7, cy-7, cx+7, cy+7), outline=color, width=width)
        draw.ellipse((cx-2, cy-2, cx+2, cy+2), outline=color, width=width)
        for a in range(0, 360, 45):
            px = int(cx + math.cos(math.radians(a))*11)
            py = int(cy + math.sin(math.radians(a))*11)
            qx = int(cx + math.cos(math.radians(a))*14)
            qy = int(cy + math.sin(math.radians(a))*14)
            draw.line((px, py, qx, qy), fill=color, width=width)
    elif kind == "user":
        draw.ellipse((x0+7, y0, x0+15, y0+8), outline=color, width=width)
        draw.arc((x0+2, y0+7, x0+20, y0+s+4), 190, 350, fill=color, width=width)
    elif kind == "wifi":
        draw.arc((x0, y0+3, x0+s, y0+s+9), 215, 325, fill=color, width=width)
        draw.arc((x0+5, y0+8, x0+s-5, y0+s+5), 215, 325, fill=color, width=width)
        draw.ellipse((x0+s//2-1, y0+s-2, x0+s//2+2, y0+s+1), fill=color)
    elif kind == "mic":
        draw.rounded_rectangle((x0+7, y0, x0+15, y0+14), radius=4, outline=color, width=width)
        draw.arc((x0+3, y0+7, x0+19, y0+20), 0, 180, fill=color, width=width)
        draw.line((x0+11, y0+19, x0+11, y0+s), fill=color, width=width)
    elif kind == "keyboard":
        draw.rounded_rectangle((x0, y0+4, x0+s+4, y0+s-2), radius=3, outline=color, width=width)
        for yy in (10, 15):
            for xx in range(5, s, 5):
                draw.rectangle((x0+xx, y0+yy, x0+xx+1, y0+yy+1), fill=color)
    elif kind == "send":
        draw.polygon([(x0, y0+9), (x0+s+2, y0), (x0+15, y0+s+2), (x0+10, y0+13)], outline=color)
        draw.line((x0+10, y0+13, x0+s+2, y0), fill=color, width=width)
    elif kind == "bulb":
        draw.ellipse((x0+4, y0, x0+s-4, y0+s-7), outline=color, width=width)
        draw.line((x0+8, y0+s-7, x0+8, y0+s-2, x0+s-8, y0+s-2, x0+s-8, y0+s-7), fill=color, width=width)
        draw.line((x0+9, y0+s+1, x0+s-9, y0+s+1), fill=color, width=width)


def _reference_scene() -> Image.Image:
    """Build the blurred background image and glass plates at exact reference positions."""
    W, H = DESIGN_W, DESIGN_H
    base = Image.new("RGBA", (W, H), (2, 7, 14, 255))
    d = ImageDraw.Draw(base)

    # Deep navy photographic gradient.
    for y in range(H):
        t = y / max(1, H-1)
        r = int(2 + 2*t)
        g = int(7 + 8*t)
        b = int(15 + 12*t)
        d.line((0, y, W, y), fill=(r, g, b, 255))

    photo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(photo)
    # Defocused architectural columns and central wall illumination.
    pd.rectangle((280, -50, 358, 900), fill=(21, 35, 49, 120))
    pd.rectangle((970, -80, 1042, 760), fill=(12, 26, 43, 105))
    pd.ellipse((520, -300, 1050, 460), fill=(31, 53, 80, 94))
    pd.ellipse((900, -280, 1420, 360), fill=(9, 32, 59, 70))
    # Blue light streaks matching the reference horizon.
    pd.line((205, 320, 410, 455, 590, 515), fill=(20, 116, 239, 160), width=20)
    pd.line((1000, 548, 1180, 520, 1310, 455), fill=(30, 126, 255, 145), width=17)
    pd.line((780, 575, 1010, 578, 1190, 542), fill=(11, 73, 159, 76), width=10)
    # Warm out-of-focus foreground practicals.
    for cx, cy, rx, ry, a in [
        (1165, 750, 58, 18, 145), (1260, 925, 95, 42, 110),
        (316, 780, 35, 18, 74), (1360, 520, 70, 40, 55),
    ]:
        pd.ellipse((cx-rx, cy-ry, cx+rx, cy+ry), fill=(217, 124, 69, a))
    pd.ellipse((1187, 180, 1240, 233), fill=(161, 189, 220, 80))
    photo = photo.filter(ImageFilter.GaussianBlur(28))
    base.alpha_composite(photo)

    # Dark cinematic wash: the source image is intentionally low-key.
    wash = Image.new("RGBA", (W, H), (0, 6, 13, 64))
    base.alpha_composite(wash)

    # Main frosted/glass panels anchored to the approved reference.
    _rounded_panel(base, (23, 124, 258, 879), 21, (2, 13, 23, 185), (11, 66, 101, 175), 1)
    _rounded_panel(base, (1275, 22, 1512, 114), 17, (2, 13, 22, 170), (9, 58, 89, 160), 1)
    _rounded_panel(base, (1275, 126, 1512, 315), 17, (2, 13, 22, 182), (10, 68, 104, 165), 1)
    _rounded_panel(base, (1275, 329, 1512, 407), 17, (2, 13, 22, 177), (10, 68, 104, 165), 1)
    _rounded_panel(base, (1275, 763, 1512, 873), 17, (2, 13, 22, 185), (10, 68, 104, 165), 1)
    _rounded_panel(base, (500, 435, 1033, 486), 14, (1, 8, 15, 205), (14, 76, 117, 180), 1)
    _rounded_panel(base, (396, 510, 1138, 701), 20, (1, 10, 19, 188), (11, 98, 148, 195), 1)
    _rounded_panel(base, (373, 811, 1162, 883), 34, (1, 10, 19, 202), (17, 128, 186, 220), 1)
    _rounded_panel(base, (38, 708, 242, 782), 13, (2, 13, 22, 192), (10, 70, 106, 180), 1)

    # Selected nav row glow and separator.
    select = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(select)
    sd.rounded_rectangle((24, 138, 244, 190), radius=11, fill=(3, 29, 48, 166))
    sd.rectangle((23, 140, 26, 187), fill=(0, 191, 255, 255))
    select = select.filter(ImageFilter.GaussianBlur(0.35))
    base.alpha_composite(select)
    d = ImageDraw.Draw(base)
    d.line((45, 549, 236, 549), fill=(11, 67, 101, 220), width=1)

    # Static line icons belong to the skin, not widget chrome.
    icon_color = (118, 204, 255, 255)
    nav = [
        ("chat", 50, 153), ("camera", 50, 210), ("grid", 51, 263),
        ("folder", 50, 318), ("globe", 50, 371), ("nodes", 50, 429),
        ("memory", 50, 485), ("gear", 50, 586),
    ]
    for kind, x, y in nav:
        _draw_line_icon(d, kind, x, y, 22, icon_color, 2)
    _draw_line_icon(d, "user", 430, 536, 22, icon_color, 2)
    _draw_line_icon(d, "mic", 399, 831, 22, (35, 195, 255, 255), 2)
    _draw_line_icon(d, "keyboard", 1037, 833, 21, (106, 177, 215, 255), 2)
    _draw_line_icon(d, "send", 1102, 832, 24, (0, 195, 255, 255), 2)
    _draw_line_icon(d, "bulb", 1296, 350, 25, (248, 248, 237, 255), 2)
    _draw_line_icon(d, "wifi", 1298, 274, 22, icon_color, 2)

    # Static typography embedded into the skin for the most faithful spacing.
    logo_font = _font(30, True)
    tiny_font = _font(11, False)
    nav_font = _font(16, False)
    d.text((37, 35), "J A R V I S", font=logo_font, fill=(170, 216, 250, 255))
    d.text((37, 79), "S E M P R E   A O   S E U   L A D O", font=tiny_font, fill=(105, 177, 218, 255))
    labels = [
        ("Conversar", 88, 156), ("Visão", 88, 212), ("Aplicativos", 88, 267),
        ("Arquivos", 88, 322), ("Internet", 88, 377), ("Automação", 88, 434),
        ("Memória", 88, 491), ("Configurações", 88, 592),
    ]
    for text, x, y in labels:
        d.text((x, y), text, font=nav_font, fill=(132, 205, 247, 255))

    d.text((82, 720), "Online", font=_font(14), fill=(63, 225, 182, 255))
    d.ellipse((56, 725, 66, 735), fill=(20, 225, 153, 255))
    d.text((82, 749), "Gemini 3.5 Flash", font=_font(13), fill=(116, 196, 239, 255))
    d.text((44, 815), '“Mais que um assistente,', font=_font(13), fill=(105, 166, 203, 255))
    d.text((44, 840), 'um verdadeiro aliado.”', font=_font(13), fill=(105, 166, 203, 255))

    # Static right-column labels; values are dynamic canvas text.
    d.text((1346, 149), "CPU", font=_font(15), fill=(116, 190, 234, 255))
    d.text((1346, 194), "RAM", font=_font(15), fill=(116, 190, 234, 255))
    d.text((1346, 239), "DISCO", font=_font(15), fill=(116, 190, 234, 255))
    d.text((1346, 284), "REDE", font=_font(15), fill=(116, 190, 234, 255))
    # Minimal telemetry glyphs.
    for cy in (155, 199):
        d.rounded_rectangle((1300, cy-10, 1322, cy+10), radius=2, outline=icon_color, width=2)
    d.rounded_rectangle((1299, 233, 1322, 253), radius=2, outline=icon_color, width=2)
    d.text((1338, 351), "Estou aqui para", font=_font(14), fill=(129, 190, 227, 255))
    d.text((1338, 373), "simplificar o seu dia.", font=_font(14), fill=(129, 190, 227, 255))
    d.text((1329, 786), "Modo contínuo", font=_font(14), fill=(123, 190, 229, 255))
    d.text((1329, 838), "Legendas", font=_font(14), fill=(123, 190, 229, 255))
    d.text((574, 922), "J A R V I S   |   I N T E L I G Ê N C I A   Q U E   T R A B A L H A   P O R   V O C Ê", font=_font(9), fill=(38, 135, 185, 255))

    return base


class _CanvasProxy:
    """Tiny compatibility shim for base code that calls .configure(text=...)."""
    def __init__(self, owner, item=None, command=None):
        self.owner = owner
        self.item = item
        self.command = command
        self.state = "normal"
        self._text = ""

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]
        if "text" in kwargs:
            self._text = str(kwargs["text"])
            if self.item is not None:
                try:
                    self.owner._ref_canvas.itemconfigure(self.item, text=self._text)
                except Exception:
                    pass
        if "text_color" in kwargs and self.item is not None:
            try:
                self.owner._ref_canvas.itemconfigure(self.item, fill=kwargs["text_color"])
            except Exception:
                pass

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "state":
            return self.state
        return None

    def invoke(self):
        if self.command and self.state != "disabled":
            return self.command()

    def pack(self, *a, **k):
        return None

    def pack_forget(self):
        return None

    def grid(self, *a, **k):
        return None

    def grid_remove(self):
        return None

    def winfo_exists(self):
        return 1


class JarvisGUI(BaseJarvisGUI):
    """Reference-locked visual shell; business/runtime logic stays in BaseJarvisGUI."""

    UI_BG = "#020812"
    UI_SURFACE = "#061421"
    UI_SURFACE_2 = "#081a2a"
    UI_SURFACE_3 = "#0c263a"
    UI_PANEL = "#03101b"
    UI_BORDER = "#0b4160"
    UI_BORDER_STRONG = "#147cac"
    UI_ACCENT = "#18bfff"
    UI_ACCENT_HOVER = "#50d0ff"
    UI_TEXT = "#eef8ff"
    UI_MUTED = "#7fa9c1"
    UI_MUTED_2 = "#4f7f9a"
    UI_SUCCESS = "#28dfa0"
    UI_WARNING = "#ffd44a"
    UI_DANGER = "#ff667a"

    def _create_main_layout(self):
        # Lock the composition to the approved reference coordinate system.
        try:
            self.root.geometry(f"{DESIGN_W}x{DESIGN_H}")
            self.root.minsize(1180, 738)
        except Exception:
            pass

        self._chat_tts_enabled = True
        self._chat_text_turn_should_speak = False
        self._ref_voice_state = "PENSANDO"
        self._ref_caption_enabled = True
        self._ref_conversation_mode = str(getattr(self, "interaction_mode", "auto") or "auto").lower() == "conversa"
        self._ref_orb_index = 0
        self._ref_orb_frames = []
        self._ref_wave_phase = 0.0
        self._ref_jobs = []
        self._ref_bg_source = _reference_scene()

        self._ref_canvas = tk.Canvas(self.root, width=DESIGN_W, height=DESIGN_H, highlightthickness=0, bd=0, bg="#020812")
        self._ref_canvas.pack(fill="both", expand=True)
        self.content_frame = self._ref_canvas
        self.side_panel = _CanvasProxy(self)
        self.sidebar_splitter = _CanvasProxy(self)

        self._ref_bg_photo = ImageTk.PhotoImage(self._ref_bg_source)
        self._ref_bg_item = self._ref_canvas.create_image(0, 0, image=self._ref_bg_photo, anchor="nw")

        # Exact approved orb crop, animated by gentle exposure/ring phases only.
        self._prepare_reference_orb_frames()
        self._ref_orb_item = self._ref_canvas.create_image(767, 322, image=self._ref_orb_frames[0], anchor="center")

        # Dynamic clock/date/telemetry.
        self._ref_clock_item = self._ref_canvas.create_text(1394, 57, text="--:--", fill="#b7ddff", font=("Segoe UI Semibold", 35), anchor="center")
        self._ref_date_item = self._ref_canvas.create_text(1394, 92, text="--", fill="#86b9d8", font=("Segoe UI", 13), anchor="center")
        self._ref_cpu_item = self._ref_canvas.create_text(1494, 155, text="--%", fill="#9bd3f5", font=("Segoe UI", 14), anchor="e")
        self._ref_ram_item = self._ref_canvas.create_text(1494, 200, text="--%", fill="#9bd3f5", font=("Segoe UI", 14), anchor="e")
        self._ref_disk_item = self._ref_canvas.create_text(1494, 245, text="--%", fill="#9bd3f5", font=("Segoe UI", 14), anchor="e")
        self._ref_net_item = self._ref_canvas.create_text(1494, 289, text="Online", fill="#9bd3f5", font=("Segoe UI", 14), anchor="e")

        # Subtitle exactly under the orb.
        self._ref_subtitle_item = self._ref_canvas.create_text(
            767, 460, text=f"{PUBLIC_NAME}: Pronto quando você estiver.", fill="#ffe100",
            font=("Segoe UI Semibold", 20), anchor="center", width=500,
        )

        # Conversation card: current exchange only, like the approved image.
        self._ref_user_prefix = self._ref_canvas.create_text(482, 550, text="Você:", fill="#17c8ff", font=("Segoe UI Semibold", 16), anchor="w")
        self._ref_user_item = self._ref_canvas.create_text(545, 550, text="", fill="#f4f7fb", font=("Segoe UI", 16), anchor="w", width=530)
        self._ref_jarvis_prefix = self._ref_canvas.create_text(482, 612, text="JARVIS:", fill="#16c8ff", font=("Segoe UI Semibold", 16), anchor="w")
        self._ref_jarvis_item = self._ref_canvas.create_text(568, 612, text="Pronto para conversar.", fill="#f4f7fb", font=("Segoe UI", 16), anchor="w", width=500)
        self._ref_canvas.create_line(430, 580, 1106, 580, fill="#0b2b3e", width=1)

        # Voice state row.
        self._ref_state_items = {}
        state_specs = [("OUVINDO", 548), ("PENSANDO", 674), ("EXECUTANDO", 825), ("FALANDO", 970)]
        for idx, (name, x) in enumerate(state_specs):
            self._ref_state_items[name] = self._ref_canvas.create_text(x, 734, text=name, fill="#738da0", font=("Segoe UI", 12), anchor="center")
            if idx < len(state_specs)-1:
                self._ref_canvas.create_text(x+66, 734, text="•", fill="#38c8ff", font=("Segoe UI", 11), anchor="center")
        self._sync_reference_state("PENSANDO")

        # Waveform is real animation; no static fake bars.
        self._ref_wave_items = []
        center_x, base_y = 766, 675
        bars = 72
        for i in range(bars):
            x = center_x - (bars-1)*5/2 + i*5
            item = self._ref_canvas.create_line(x, base_y-1, x, base_y+1, fill="#18bfff", width=3)
            self._ref_wave_items.append(item)

        # Composer uses a real text widget but is styled to disappear into the skin.
        self.input_shell = _CanvasProxy(self)
        self.text_input = tk.Text(
            self.root, height=1, bd=0, highlightthickness=0, relief="flat",
            bg="#061521", fg="#e8f6ff", insertbackground="#56cfff",
            font=("Segoe UI", 15), wrap="word", undo=True,
        )
        self.text_input.place(x=438, y=829, width=574, height=38)
        self.text_input.insert("1.0", f"Fale com o {PUBLIC_NAME}...")
        self._composer_placeholder_active = True
        self.text_input.configure(fg="#607c8e")
        self.text_input.bind("<FocusIn>", self._composer_focus_in, add="+")
        self.text_input.bind("<FocusOut>", self._composer_focus_out, add="+")
        self.text_input.bind("<Return>", self._on_composer_return, add="+")
        self.text_input.bind("<KeyRelease>", self._resize_composer, add="+")

        # Clickable canvas controls.
        self._ref_canvas.tag_bind(self._ref_bg_item, "<Button-1>", lambda e: None)
        self._bind_zone("send", 1088, 816, 1150, 875, self.send_message)
        self._bind_zone("voice", 386, 817, 432, 875, self._toggle_voice_visual_mode)
        self._bind_zone("continuous", 1436, 777, 1502, 811, self._toggle_reference_conversation)
        self._bind_zone("captions", 1436, 829, 1502, 863, self._toggle_reference_captions)
        self._bind_zone("settings", 40, 570, 238, 628, self._open_api_settings)
        self._bind_zone("update", 145, 744, 238, 777, self._update_now)

        # Switches and subtle visible update affordance.
        self._ref_cont_switch = self._draw_switch(1470, 793, self._ref_conversation_mode)
        self._ref_caption_switch = self._draw_switch(1470, 845, True)
        self._ref_update_bg = self._ref_canvas.create_rectangle(149, 746, 235, 774, fill="#082338", outline="#12638c", width=1)
        self._ref_update_text = self._ref_canvas.create_text(192, 760, text="ATUALIZAR", fill="#69d5ff", font=("Segoe UI Semibold", 10), anchor="center")

        # Compatibility proxies used by inherited updater/status routines.
        self.update_button = _CanvasProxy(self, self._ref_update_text, self._update_now)
        self.api_button = _CanvasProxy(self, command=self._open_api_settings)
        self.clock_label = _CanvasProxy(self, self._ref_clock_item)
        self.status_label = _CanvasProxy(self)
        self.status_dot = _CanvasProxy(self)
        self.activity_label = _CanvasProxy(self)
        self.current_conversation_label = _CanvasProxy(self)
        self.send_button = _CanvasProxy(self, command=self.send_message)
        self.voice_button = _CanvasProxy(self, command=self._toggle_voice_visual_mode)
        self.source_badge = _CanvasProxy(self)

        # Base chat/history renderer exists off-screen solely for compatibility;
        # the approved card above is the visible conversation surface.
        self._compat_shell = ctk.CTkFrame(self.root, width=2, height=2, fg_color="#020812")
        self._compat_shell.place(x=-5000, y=-5000)
        self.chat_scroll = ctk.CTkScrollableFrame(self._compat_shell, width=2, height=2, fg_color="#020812")
        self.chat_scroll.pack()
        self.chat_display = None
        self.conversation_list_frame = ctk.CTkScrollableFrame(self._compat_shell, width=2, height=2)
        self.conversation_list_frame.pack()
        self.system_log_frame = None
        self.system_log_text = None
        self.monitor_visible = False
        self.cpu_gauge = None
        self.ram_gauge = None
        self.network_gauge = None
        self.cpu_value_label = None
        self.ram_value_label = None
        self.network_value_label = None
        self.cpu_progress = None
        self.ram_progress = None
        self.network_progress = None
        self.media_value_label = None
        self.active_app_label = None
        self.context_app_label = None
        self.context_site_label = None
        self.context_goal_label = None
        self.context_download_label = None
        self.sidebar_state_button = None

        # Hidden agent widgets keep inherited agent runtime safe.
        self.agent_hud = ctk.CTkFrame(self._compat_shell)
        self.agent_hud_title = ctk.CTkLabel(self.agent_hud, text="")
        self.agent_hud_step = ctk.CTkLabel(self.agent_hud, text="")
        self.agent_hud_progress = ctk.CTkProgressBar(self.agent_hud)
        self.agent_stop_button = ctk.CTkButton(self.agent_hud, text="", command=self._stop_agent_goal)

        # Start all motion after the first frame.
        self.root.after(60, self._animate_reference_orb)
        self.root.after(70, self._animate_reference_wave)
        self.root.after(120, self._reference_clock_tick)
        self.root.after(500, self._reference_metrics_tick)

    def _bind_zone(self, name, x1, y1, x2, y2, callback):
        zone = self._ref_canvas.create_rectangle(x1, y1, x2, y2, outline="", fill="", tags=(f"zone_{name}",))
        self._ref_canvas.tag_bind(zone, "<Button-1>", lambda e, cb=callback: cb())
        self._ref_canvas.tag_bind(zone, "<Enter>", lambda e: self._ref_canvas.configure(cursor="hand2"))
        self._ref_canvas.tag_bind(zone, "<Leave>", lambda e: self._ref_canvas.configure(cursor=""))
        return zone

    def _draw_switch(self, cx, cy, enabled: bool):
        tag = f"switch_{cx}_{cy}"
        self._ref_canvas.delete(tag)
        x1, y1, x2, y2 = cx-21, cy-12, cx+21, cy+12
        fill = "#108bd3" if enabled else "#183445"
        outline = "#16aef8" if enabled else "#315266"
        self._ref_canvas.create_oval(x1, y1, x2, y2, fill=fill, outline=outline, width=1, tags=tag)
        knob_x = cx+9 if enabled else cx-9
        self._ref_canvas.create_oval(knob_x-9, cy-9, knob_x+9, cy+9, fill="#aee9ff" if enabled else "#6a8291", outline="", tags=tag)
        return tag

    def _prepare_reference_orb_frames(self):
        source = load_orb_image().convert("RGBA")
        # Keep the crop's proportions and exact artwork.  Only light/ring energy
        # is animated; the approved orb itself is never redrawn.
        target_w, target_h = 300, 230
        source.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        canvas_size = (330, 250)
        frames = []
        for i in range(24):
            phase = i / 24.0 * math.tau
            frame = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            pulse = 0.96 + 0.055 * (0.5 + 0.5*math.sin(phase))
            art = ImageEnhance.Brightness(source).enhance(pulse)
            x = (canvas_size[0]-art.width)//2
            y = (canvas_size[1]-art.height)//2

            glow = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            cx, cy = canvas_size[0]//2, canvas_size[1]//2
            for rr, a in ((78, 30), (96, 19), (116, 10)):
                gd.ellipse((cx-rr, cy-rr, cx+rr, cy+rr), outline=(0, 163, 255, a), width=5)
            glow = glow.filter(ImageFilter.GaussianBlur(8))
            frame.alpha_composite(glow)
            frame.alpha_composite(art, (x, y))

            # Thin rotating energy segments matching the reference rings.
            rd = ImageDraw.Draw(frame)
            start = math.degrees(phase)
            rd.arc((cx-111, cy-111, cx+111, cy+111), start, start+74, fill=(27, 179, 255, 170), width=2)
            rd.arc((cx-111, cy-111, cx+111, cy+111), start+185, start+233, fill=(18, 110, 215, 110), width=1)
            rd.arc((cx-92, cy-92, cx+92, cy+92), -start*0.55+20, -start*0.55+92, fill=(94, 215, 255, 120), width=1)
            frames.append(ImageTk.PhotoImage(frame))
        self._ref_orb_frames = frames

    def _animate_reference_orb(self):
        try:
            if not self.root or not self._ref_orb_frames:
                return
            idx = int(self._ref_orb_index) % len(self._ref_orb_frames)
            self._ref_canvas.itemconfigure(self._ref_orb_item, image=self._ref_orb_frames[idx])
            self._ref_orb_index = idx + 1
            self.root.after(92, self._animate_reference_orb)
        except Exception:
            pass

    def _animate_reference_wave(self):
        try:
            state = str(getattr(self, "_ref_voice_state", "REPOUSO") or "REPOUSO").upper()
            level = float(getattr(self, "voice_mic_level", 0.0) or 0.0)
            speaking = state == "FALANDO"
            listening = state == "OUVINDO"
            thinking = state in {"PENSANDO", "PROCESSANDO", "ENTENDENDO"}
            self._ref_wave_phase += 0.34 if speaking else (0.22 if listening else 0.12)
            center = (len(self._ref_wave_items)-1)/2.0
            for i, item in enumerate(self._ref_wave_items):
                envelope = math.exp(-((i-center)/(center*0.72))**2)
                if speaking:
                    amp = 4 + 14*envelope*(0.45+0.55*abs(math.sin(self._ref_wave_phase + i*0.43)))
                elif listening:
                    amp = 2 + 16*envelope*max(level, 0.10)*(0.6+0.4*abs(math.sin(self._ref_wave_phase+i*0.37)))
                elif thinking:
                    amp = 2 + 7*envelope*(0.45+0.55*abs(math.sin(self._ref_wave_phase+i*0.28)))
                else:
                    amp = 1.2 + 2.0*envelope*(0.5+0.5*math.sin(self._ref_wave_phase+i*0.22))
                x = 766 - (len(self._ref_wave_items)-1)*5/2 + i*5
                self._ref_canvas.coords(item, x, 675-amp, x, 675+amp)
                alpha_color = "#2ad0ff" if amp > 7 else "#1187bf"
                self._ref_canvas.itemconfigure(item, fill=alpha_color)
            self.root.after(72, self._animate_reference_wave)
        except Exception:
            pass

    def _reference_clock_tick(self):
        try:
            now = datetime.now()
            self._ref_canvas.itemconfigure(self._ref_clock_item, text=now.strftime("%H:%M"))
            days = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
            months = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
            self._ref_canvas.itemconfigure(self._ref_date_item, text=f"{days[now.weekday()]}, {now.day:02d} de {months[now.month-1]} de {now.year}")
            self.root.after(1000, self._reference_clock_tick)
        except Exception:
            pass

    def _reference_metrics_tick(self):
        try:
            if psutil:
                cpu = int(round(psutil.cpu_percent(interval=None)))
                ram = int(round(psutil.virtual_memory().percent))
                try:
                    disk = int(round(psutil.disk_usage(self.project_dir).percent))
                except Exception:
                    disk = 0
                self._ref_canvas.itemconfigure(self._ref_cpu_item, text=f"{cpu}%")
                self._ref_canvas.itemconfigure(self._ref_ram_item, text=f"{ram}%")
                self._ref_canvas.itemconfigure(self._ref_disk_item, text=f"{disk}%")
                online = any(getattr(v, "isup", False) for v in psutil.net_if_stats().values())
                self._ref_canvas.itemconfigure(self._ref_net_item, text="Online" if online else "Offline", fill="#9bd3f5" if online else "#e7b65b")
            self.root.after(1800, self._reference_metrics_tick)
        except Exception:
            try:
                self.root.after(3000, self._reference_metrics_tick)
            except Exception:
                pass

    # Base setup starts its own updaters.  Prevent duplicate clocks/metric loops.
    def _start_clock_updater(self):
        return None

    def _start_system_metrics_updater(self):
        return None

    def _set_input_focus(self, focused: bool):
        try:
            self.text_input.configure(insertbackground="#75ddff" if focused else "#56cfff")
        except Exception:
            pass

    def _composer_focus_in(self, event=None):
        try:
            if getattr(self, "_composer_placeholder_active", False):
                self.text_input.delete("1.0", "end")
                self.text_input.configure(fg="#eef8ff")
                self._composer_placeholder_active = False
        except Exception:
            pass
        self._set_input_focus(True)

    def _composer_focus_out(self, event=None):
        try:
            if not self.text_input.get("1.0", "end-1c").strip():
                self.text_input.delete("1.0", "end")
                self.text_input.insert("1.0", f"Fale com o {PUBLIC_NAME}...")
                self.text_input.configure(fg="#607c8e")
                self._composer_placeholder_active = True
        except Exception:
            pass
        self._set_input_focus(False)

    def _composer_text(self):
        try:
            if getattr(self, "_composer_placeholder_active", False):
                return ""
            return self.text_input.get("1.0", "end-1c")
        except Exception:
            return ""

    def _composer_set_placeholder(self):
        self._composer_focus_out()

    def _resize_composer(self, event=None):
        return None

    def _sync_reference_state(self, state: str):
        state = str(state or "REPOUSO").upper()
        mapping = {
            "ESCUTANDO": "OUVINDO", "ESPERANDO_RESPOSTA": "OUVINDO", "ACORDOU": "OUVINDO",
            "ENTENDENDO": "PENSANDO", "PROCESSANDO": "PENSANDO", "PREPARANDO": "OUVINDO",
            "AGUARDANDO": "OUVINDO" if self._ref_conversation_mode else "REPOUSO",
        }
        state = mapping.get(state, state)
        self._ref_voice_state = state
        for key, item in getattr(self, "_ref_state_items", {}).items():
            color = "#21caff" if key == state else "#71889a"
            try:
                self._ref_canvas.itemconfigure(item, fill=color)
            except Exception:
                pass

    def _toggle_reference_conversation(self):
        self._ref_conversation_mode = not bool(self._ref_conversation_mode)
        self._draw_switch(1470, 793, self._ref_conversation_mode)
        self.interaction_mode = "conversa" if self._ref_conversation_mode else "auto"
        try:
            if self.voice_engine:
                self.voice_engine.set_conversation_mode(self._ref_conversation_mode)
        except Exception:
            pass
        try:
            self._sync_conversation_overlay_lock(self._ref_conversation_mode)
        except Exception:
            pass

    def _toggle_reference_captions(self):
        self._ref_caption_enabled = not bool(self._ref_caption_enabled)
        self._draw_switch(1470, 845, self._ref_caption_enabled)
        if not self._ref_caption_enabled:
            try:
                self._ref_canvas.itemconfigure(self._ref_subtitle_item, text="")
                if self.qt_voice_overlay:
                    self.qt_voice_overlay.set_caption("")
            except Exception:
                pass

    def _apply_voice_engine_state(self, state, detail):
        result = super()._apply_voice_engine_state(state, detail)
        self._sync_reference_state(state)
        return result

    def _set_voice_overlay_text(self, text):
        result = super()._set_voice_overlay_text(text)
        if self._ref_caption_enabled:
            clean = " ".join(str(text or "").split()).strip()
            if clean:
                if not clean.lower().startswith(("jarvis:", "você:", "voce:")):
                    clean = f"{PUBLIC_NAME}: {clean}"
                try:
                    self._ref_canvas.itemconfigure(self._ref_subtitle_item, text=clean[:220])
                except Exception:
                    pass
        return result

    def _update_status(self, text, color=None):
        result = super()._update_status(text, color)
        key = str(text or "").upper()
        if any(t in key for t in ("PROCESS", "PENS", "GERANDO", "PESQUIS")):
            self._sync_reference_state("PENSANDO")
        elif "EXEC" in key:
            self._sync_reference_state("EXECUTANDO")
        elif "OUV" in key:
            self._sync_reference_state("OUVINDO")
        elif "FAL" in key:
            self._sync_reference_state("FALANDO")
        return result

    def send_message(self, event=None):
        try:
            has_text = bool(self._composer_text().replace("\x00", "").strip())
        except Exception:
            has_text = False
        if has_text:
            self._chat_text_turn_should_speak = True
            self._sync_reference_state("PENSANDO")
        return super().send_message(event=event)

    def _speak_reference_chat_response(self, text: str):
        if not bool(getattr(self, "_chat_text_turn_should_speak", False)):
            return
        self._chat_text_turn_should_speak = False
        if getattr(self, "_voice_command_active", False):
            return
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return

        def attempt(tries=0):
            engine = getattr(self, "voice_engine", None)
            if engine is None:
                if tries < 30 and self.root:
                    self.root.after(180, lambda: attempt(tries+1))
                return
            try:
                spoken = self._voice_spoken_summary(clean)
                engine.speak(spoken, wait=False, fast=True)
            except Exception:
                if tries < 3 and self.root:
                    self.root.after(350, lambda: attempt(tries+1))
        attempt()

    def add_message(self, sender: str, message: str, is_user: bool = False, is_jarvis: bool = False, is_system: bool = False, speak: bool = False):
        result = super().add_message(sender, message, is_user=is_user, is_jarvis=is_jarvis, is_system=is_system, speak=speak)
        clean = " ".join(str(message or "").split()).strip()
        try:
            if is_user:
                self._ref_canvas.itemconfigure(self._ref_user_item, text=clean[:185])
            elif is_jarvis and not is_system:
                self._ref_canvas.itemconfigure(self._ref_jarvis_item, text=clean[:185])
                if self._ref_caption_enabled and clean:
                    self._ref_canvas.itemconfigure(self._ref_subtitle_item, text=f"{PUBLIC_NAME}: {clean[:190]}")
                if not speak:
                    self._speak_reference_chat_response(clean)
        except Exception:
            pass
        return result

    def _finish_streaming_response(self, full_response: str, token: int = 0):
        pending = bool(getattr(self, "_chat_text_turn_should_speak", False))
        result = super()._finish_streaming_response(full_response, token=token)
        clean = " ".join(str(full_response or "").split()).strip()
        if clean:
            try:
                self._ref_canvas.itemconfigure(self._ref_jarvis_item, text=clean[:185])
                if self._ref_caption_enabled:
                    self._ref_canvas.itemconfigure(self._ref_subtitle_item, text=f"{PUBLIC_NAME}: {clean[:190]}")
            except Exception:
                pass
        if pending and bool(getattr(self, "_chat_text_turn_should_speak", False)):
            self._speak_reference_chat_response(clean)
        return result

    def _refresh_conversation_list(self, *args, **kwargs):
        # Exact reference keeps navigation, not a visible history column.
        # Memory is still preserved by MemoryStore and the base runtime.
        return None

    def _copy_everything(self):
        try:
            return super()._copy_everything()
        except Exception:
            return None


__all__ = ["JarvisGUI"]
