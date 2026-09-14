"""High-DPI reference shell with a real rotating 3D JARVIS orb.

The layout remains inherited from gui_reference_exact_v2. Only the visual orb
renderer and DPI setup are upgraded so the approved composition is preserved.
"""
from __future__ import annotations

import ctypes
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageTk

from gui_reference_exact_v2 import JarvisGUI as ReferenceJarvisGUI


def _enable_high_dpi() -> None:
    """Enable crisp Windows rendering before Tk creates the application window."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_high_dpi()


class JarvisGUI(ReferenceJarvisGUI):
    """Reference UI with a supersampled, CPU-friendly rotating 3D orb."""

    ORB_FRAME_COUNT = 48
    ORB_SUPERSAMPLE = 2
    ORB_OUTPUT_SIZE = (360, 280)
    ORB_FRAME_DELAY_MS = 68

    @staticmethod
    def _project_point(lat: float, lon: float, phase: float, radius: float, cx: float, cy: float):
        """Project a rotating point from a unit sphere into 2D screen space."""
        clat = math.cos(lat)
        x = clat * math.sin(lon)
        y = math.sin(lat)
        z = clat * math.cos(lon)

        cp = math.cos(phase)
        sp = math.sin(phase)
        xr = x * cp + z * sp
        zr = -x * sp + z * cp

        tilt = math.radians(-12.0)
        ct = math.cos(tilt)
        st = math.sin(tilt)
        yr = y * ct - zr * st
        zr2 = y * st + zr * ct

        return cx + xr * radius, cy - yr * radius, zr2

    @staticmethod
    def _draw_projected_curve(draw, points, *, front_color, back_color, width):
        """Draw a projected 3D polyline with front/back depth separation."""
        if len(points) < 2:
            return
        for index in range(1, len(points)):
            x1, y1, z1 = points[index - 1]
            x2, y2, z2 = points[index]
            color = front_color if (z1 + z2) >= 0 else back_color
            draw.line((x1, y1, x2, y2), fill=color, width=width)

    def _prepare_reference_orb_frames(self):
        """Build a true rotating spherical mesh instead of animating one flat image."""
        ss = max(1, int(self.ORB_SUPERSAMPLE))
        out_w, out_h = self.ORB_OUTPUT_SIZE
        width, height = out_w * ss, out_h * ss
        cx, cy = width / 2.0, height / 2.0
        radius = 92.0 * ss
        line_w = max(1, 1 * ss)
        strong_w = max(2, 2 * ss)
        frames = []

        for frame_index in range(self.ORB_FRAME_COUNT):
            phase = (frame_index / float(self.ORB_FRAME_COUNT)) * math.tau
            frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))

            glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            pulse = 0.86 + 0.14 * (0.5 + 0.5 * math.sin(phase * 2.0))
            for mul, alpha, stroke in ((1.02, 105, 4), (1.16, 58, 8), (1.34, 26, 13)):
                rr = radius * mul
                gd.ellipse(
                    (cx - rr, cy - rr, cx + rr, cy + rr),
                    outline=(0, 177, 255, int(alpha * pulse)),
                    width=max(1, stroke * ss),
                )
            glow = glow.filter(ImageFilter.GaussianBlur(8 * ss))
            frame.alpha_composite(glow)

            body = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            bd = ImageDraw.Draw(body)
            bd.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=(3, 17, 30, 242),
                outline=(40, 190, 255, 220),
                width=strong_w,
            )
            for step in range(22, 0, -1):
                t = step / 22.0
                rr = radius * (0.20 + 0.72 * t)
                ox = -radius * 0.24 * (1.0 - t)
                oy = -radius * 0.18 * (1.0 - t)
                alpha = int(5 + 19 * (1.0 - t))
                bd.ellipse(
                    (cx + ox - rr, cy + oy - rr, cx + ox + rr, cy + oy + rr),
                    fill=(7, 72, 111, alpha),
                )
            core_r = radius * (0.34 + 0.02 * math.sin(phase * 2.0))
            bd.ellipse(
                (cx - core_r, cy - core_r, cx + core_r, cy + core_r),
                fill=(4, 42, 67, 205),
                outline=(73, 219, 255, 170),
                width=line_w,
            )
            body = body.filter(ImageFilter.GaussianBlur(0.35 * ss))
            frame.alpha_composite(body)

            mesh = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            md = ImageDraw.Draw(mesh)

            meridians = 12
            samples = 44
            for meridian in range(meridians):
                lon = (meridian / meridians) * math.tau
                points = []
                for sample in range(samples + 1):
                    lat = -math.pi / 2 + (sample / samples) * math.pi
                    points.append(self._project_point(lat, lon, phase, radius, cx, cy))
                self._draw_projected_curve(
                    md,
                    points,
                    front_color=(47, 205, 255, 122),
                    back_color=(8, 92, 145, 34),
                    width=line_w,
                )

            for lat_deg in (-60, -40, -20, 0, 20, 40, 60):
                lat = math.radians(lat_deg)
                points = []
                for sample in range(73):
                    lon = (sample / 72.0) * math.tau
                    points.append(self._project_point(lat, lon, phase, radius, cx, cy))
                self._draw_projected_curve(
                    md,
                    points,
                    front_color=(30, 166, 230, 88 if lat_deg else 126),
                    back_color=(5, 66, 110, 24),
                    width=line_w,
                )

            for stream_index, base_lon in enumerate((0.25, 1.75, 3.30, 4.85)):
                points = []
                for sample in range(50):
                    lat = -1.05 + sample / 49.0 * 2.10
                    wobble = 0.16 * math.sin(lat * 4.0 + stream_index * 1.7)
                    points.append(self._project_point(lat, base_lon + wobble, phase, radius, cx, cy))
                self._draw_projected_curve(
                    md,
                    points,
                    front_color=(105, 231, 255, 190),
                    back_color=(16, 91, 145, 28),
                    width=strong_w,
                )

            nodes = (
                (-0.62, 0.18), (-0.31, 1.02), (0.18, 1.65), (0.55, 2.30),
                (-0.44, 3.22), (0.04, 3.95), (0.46, 4.65), (0.72, 5.38),
                (0.00, 0.62), (0.30, 5.88),
            )
            for lat, lon in nodes:
                px, py, pz = self._project_point(lat, lon, phase, radius * 0.985, cx, cy)
                if pz <= -0.05:
                    continue
                depth = min(1.0, max(0.0, (pz + 0.05) / 1.05))
                rr = (2.2 + 2.1 * depth) * ss
                alpha = int(85 + 155 * depth)
                md.ellipse((px - rr, py - rr, px + rr, py + rr), fill=(117, 239, 255, alpha))

            mask = Image.new("L", (width, height), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
            mesh.putalpha(Image.composite(mesh.getchannel("A"), Image.new("L", (width, height), 0), mask))
            frame.alpha_composite(mesh)

            fd = ImageDraw.Draw(frame)
            fd.arc(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                198,
                342,
                fill=(131, 236, 255, 235),
                width=strong_w,
            )
            fd.arc(
                (cx - radius * 0.91, cy - radius * 0.91, cx + radius * 0.91, cy + radius * 0.91),
                205,
                305,
                fill=(80, 210, 255, 125),
                width=line_w,
            )

            ring_phase = math.degrees(phase)
            for ring_radius, start_offset, arc_len, alpha, stroke in (
                (1.18, ring_phase, 74, 215, 2),
                (1.27, -ring_phase * 0.64 + 120, 54, 150, 1),
                (1.38, ring_phase * 0.38 + 210, 42, 95, 1),
            ):
                rr = radius * ring_radius
                fd.arc(
                    (cx - rr, cy - rr * 0.58, cx + rr, cy + rr * 0.58),
                    start_offset,
                    start_offset + arc_len,
                    fill=(41, 190, 255, alpha),
                    width=max(1, stroke * ss),
                )

            final = frame.resize((out_w, out_h), Image.Resampling.LANCZOS)
            frames.append(ImageTk.PhotoImage(final))

        self._ref_orb_frames = frames

    def _animate_reference_orb(self):
        """Swap pre-rendered 3D frames smoothly without doing heavy work per tick."""
        try:
            if not self.root or not self._ref_orb_frames:
                return
            idx = int(self._ref_orb_index) % len(self._ref_orb_frames)
            self._ref_canvas.itemconfigure(self._ref_orb_item, image=self._ref_orb_frames[idx])
            self._ref_orb_index = idx + 1
            self.root.after(self.ORB_FRAME_DELAY_MS, self._animate_reference_orb)
        except Exception:
            pass


__all__ = ["JarvisGUI"]
