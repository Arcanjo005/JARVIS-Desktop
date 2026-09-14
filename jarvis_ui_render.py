"""Procedural 3-D hero renderer. No Tk calls, assets, network or global patches.

An analytic sphere is shaded in view space; its surface mesh is rotated
in object space. Orbit segments and landmarks use depth-tested XYZ geometry.
Only the small orb is redrawn. The scene remains a separate cached image.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import multiprocessing as mp
import queue
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


PALETTES = {
    "REPOUSO": (30, 164, 246), "OUVINDO": (39, 204, 240),
    "PENSANDO": (100, 152, 255), "EXECUTANDO": (54, 179, 250),
    "FALANDO": (60, 208, 255), "RECONECTANDO": (226, 175, 79),
}


def rotation(angle: float, tilt: float = -0.20) -> np.ndarray:
    """Right-handed object-to-view rotation, preserving length and depth."""
    c, s, ct, st = math.cos(angle), math.sin(angle), math.cos(tilt), math.sin(tilt)
    return np.asarray(((c, 0, s), (st*s, ct, -st*c), (-ct*s, st, ct*c)), dtype=np.float32)


def project(points: np.ndarray, angle: float, radius: float, center: float) -> np.ndarray:
    view = np.asarray(points, dtype=np.float32) @ rotation(angle).T
    return np.column_stack((center + radius*view[:, 0], center - radius*view[:, 1], view[:, 2]))


class OrbRenderer:
    """One-size cache; memory does not grow with states, frames or resizes."""
    MAX_RENDER_SIZE = 960

    def __init__(self):
        self._size = 0
        self.frames = 0

    def _prepare(self, output_size: int):
        size = max(64, min(640, int(output_size)))
        internal = min(self.MAX_RENDER_SIZE, size*2)
        if (size, internal) == getattr(self, "_key", None):
            return
        self._key = size, internal
        self._size, self._internal = size, internal
        self._center = (internal-1)/2
        self._radius = internal*0.315
        y, x = np.mgrid[:internal, :internal].astype(np.float32)
        nx, ny = (x-self._center)/self._radius, -(y-self._center)/self._radius
        r2 = nx*nx + ny*ny
        self._mask = r2 <= 1
        self._nx, self._ny = nx, ny
        self._nz = np.sqrt(np.maximum(0, 1-r2))
        self._edge = np.clip((1-r2)*self._radius*0.6, 0, 1)
        self._light = np.clip(-0.40*nx+0.55*ny+0.73*self._nz, 0, 1)
        self._fresnel = (1-self._nz)**3
        # Static atmospheric bloom, not recalculated per frame.
        self._halo = Image.new("RGBA", (internal, internal))
        d = ImageDraw.Draw(self._halo)
        c, r = self._center, self._radius
        for mul, alpha in ((1.33, 14), (1.17, 20), (1.04, 40)):
            rr = r*mul
            d.ellipse((c-rr, c-rr, c+rr, c+rr), fill=(13, 125, 234, alpha))
        self._halo = self._halo.filter(ImageFilter.GaussianBlur(internal*0.023))
        self._angles = np.linspace(0, math.tau, 121, dtype=np.float32)

        self._curves = []
        latitudes = np.linspace(-math.pi/2, math.pi/2, 49, dtype=np.float32)
        longitudes = np.linspace(0, math.tau, 73, dtype=np.float32)
        for j in range(14):
            la, lo = latitudes, j*math.tau/14
            self._curves.append((np.column_stack((np.cos(la)*math.sin(lo), np.sin(la), np.cos(la)*math.cos(lo))), False))
        for la in (-1.0, -0.65, -0.32, 0, 0.32, 0.65, 1.0):
            self._curves.append((np.column_stack((math.cos(la)*np.sin(longitudes), np.full_like(longitudes, math.sin(la)), math.cos(la)*np.cos(longitudes))), False))
        for j in range(3):
            la = latitudes[4:-4]
            lo = j*2.1+la*1.1+0.2*np.sin(la*4+j)
            self._curves.append((np.column_stack((np.cos(la)*np.sin(lo), np.sin(la), np.cos(la)*np.cos(lo))), True))

    def _orbit(self, draw, angle, index, front):
        a = self._angles
        r = 1.22 + index*0.16
        tilt = 0.45 + index*0.20
        points = np.column_stack((r*np.cos(a), r*np.sin(a)*math.sin(tilt), r*np.sin(a)*math.cos(tilt)))
        projected = project(points, angle*(0.17+index*0.09)+index*1.8, self._radius, self._center)
        # Depth test against the front of the analytic unit sphere.
        view_x = (projected[:, 0]-self._center)/self._radius
        view_y = (projected[:, 1]-self._center)/self._radius
        r2 = view_x**2 + view_y**2
        visible = (r2 > 1) | (projected[:, 2] >= np.sqrt(np.maximum(0, 1-r2)))
        near = visible if front else ~visible
        phase = (a/math.tau - angle/math.tau*(.8+index*.2)) % 1
        bright = phase < .19
        stroke = max(1, round(self._internal/340))
        # Draw the dim track once and its energy segment over it.
        self._draw_runs(draw, projected[:, :2], near, (54, 196, 255, 35), stroke)
        self._draw_runs(draw, projected[:, :2], near & bright, (90, 220, 255, 210), stroke)

    def _body_for(self, state):
        key = self._key, state
        if key == getattr(self, "_body_key", None):
            return self._body
        base = np.asarray(PALETTES.get(state, PALETTES["REPOUSO"]), np.float32)
        intensity = 0.10 + 0.40*self._light + 0.12*self._fresnel
        rgb = base[None, None, :]*intensity[..., None]
        rgb += np.asarray((165, 226, 255), np.float32)*(self._light**36*0.7 + self._fresnel*0.12)[..., None]
        arr = np.empty((self._internal, self._internal, 4), dtype=np.uint8)
        arr[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        arr[..., 3] = (self._edge*250).astype(np.uint8)
        arr[~self._mask, 3] = 0
        self._body_key, self._body = key, Image.fromarray(arr)
        return self._body

    def _surface(self, draw, angle):
        stroke = max(1, round(self._internal/550))
        # Back-facing surface is culled, not painted on top of the front.
        for points, energy in self._curves:
            pp = project(points, angle, self._radius, self._center)
            self._draw_runs(draw, pp[:, :2], pp[:, 2] > 0,
                            (98, 218, 255, 180 if energy else 75), stroke*(2 if energy else 1))

    @staticmethod
    def _draw_runs(draw, coordinates, visible, color, width):
        # Batch contiguous visible polyline segments into a few C-level calls.
        # The boundary vertices are retained; no segment crosses the rear face.
        indices = np.flatnonzero(np.diff(np.r_[False, visible, False]))
        for start, end in indices.reshape(-1, 2):
            if end-start >= 2:
                draw.line([tuple(xy) for xy in coordinates[start:end]], fill=color, width=width,
                          joint="curve")

    def render(self, size: int, seconds: float, state: str = "REPOUSO", level: float = 0) -> Image.Image:
        self._prepare(size)
        angle = float(seconds)*0.48
        frame = self._halo.copy()
        draw = ImageDraw.Draw(frame)
        for i in range(2):
            self._orbit(draw, angle, i, False)
        frame.alpha_composite(self._body_for(state))
        surface = Image.new("RGBA", frame.size)
        self._surface(ImageDraw.Draw(surface), angle)
        frame.alpha_composite(surface)
        draw = ImageDraw.Draw(frame)
        for i in range(2):
            self._orbit(draw, angle, i, True)
        landmarks = []
        for j in range(22):
            la, lo = math.sin(j*2.399)*1.1, j*2.399
            landmarks.append((math.cos(la)*math.sin(lo), math.sin(la), math.cos(la)*math.cos(lo)))
        for x, y, z in project(np.asarray(landmarks), angle, self._radius, self._center):
            if z < 0.08:
                continue
            r = self._internal*(0.002+0.0015*z)
            draw.ellipse((x-r, y-r, x+r, y+r), fill=(164, 239, 255, int(120+130*z)))
        self.frames += 1
        return frame.resize((self._size, self._size), Image.Resampling.LANCZOS)


def render_scene(width: int, height: int) -> Image.Image:
    """Defocused architecture. No text is baked into a scaled bitmap."""
    width, height = max(1, min(3840, int(width))), max(1, min(2160, int(height)))
    # Low-frequency background only: render at half size and reconstruct smoothly.
    w, h = max(1, width//2), max(1, height//2)
    base = Image.new("RGB", (w, h), (3, 10, 19))
    d = ImageDraw.Draw(base)
    d.rectangle((w*.10, -h*.2, w*.16, h), fill=(14, 28, 43))
    d.rectangle((w*.83, -h*.2, w*.87, h*.9), fill=(12, 28, 41))
    d.ellipse((w*.25, -h*.85, w*.82, h*.45), fill=(18, 37, 58))
    d.line((w*.05, h*.53, w*.31, h*.83), fill=(9, 48, 85), width=max(2, h//25))
    d.line((w*.66, h*.90, w*.96, h*.60), fill=(8, 53, 92), width=max(2, h//30))
    d.ellipse((w*.85, h*.83, w*.93, h*.95), fill=(65, 41, 31))
    base = base.filter(ImageFilter.GaussianBlur(max(4, min(w, h)*.055)))
    return base.resize((width, height), Image.Resampling.LANCZOS)


@dataclass(frozen=True)
class RenderRequest:
    size: int = 300
    state: str = "REPOUSO"
    level: float = 0.0
    visible: bool = True


def _put_latest(channel, value):
    """Bounded transport: discard an old frame rather than building a backlog."""
    try:
        channel.put_nowait(value)
        return True
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            return False
        try:
            channel.put_nowait(value)
            return True
        except queue.Full:
            return False


def _render_worker(requests, frames, stop):
    """Spawned process, with no Tk interpreter or references to GUI objects.

    A thread is intentionally not used: cyclic GC in a Pillow worker can run
    Tk Variable/Font finalizers on the wrong thread during window destruction.
    Process isolation also keeps the geometry work out of the GUI's GIL.
    """
    frames.cancel_join_thread()
    renderer = OrbRenderer()
    request = RenderRequest(visible=False)
    origin = time.monotonic()
    try:
        while not stop.is_set():
            started = time.monotonic()
            try:
                while True:
                    request = requests.get_nowait()
            except queue.Empty:
                pass
            if not request.visible:
                stop.wait(.08)
                continue
            image = renderer.render(request.size, started-origin, request.state, request.level)
            elapsed = time.monotonic()-started
            _put_latest(frames, ("frame", request.size, image, elapsed*1000))
            # Yield to speech workloads; at most 45% of one core, 24fps cap.
            target = 1/18 if request.state == "REPOUSO" else 1/24
            stop.wait(max(.008, target-elapsed, elapsed*1.25))
    except Exception as exc:
        _put_latest(frames, ("error", f"{type(exc).__name__}: {exc}"))


class OrbWorker:
    """One isolated renderer process and two size-one queues; no Tk off-thread."""
    def __init__(self):
        context = mp.get_context("spawn")
        self._requests = self._frames = self._stop = None
        self.process = None
        self._started = False
        self._closed = False
        self._last_request = None
        self.error = None
        self.render_ms = 0.0
        try:
            self._requests = context.Queue(maxsize=1)
            self._frames = context.Queue(maxsize=1)
            self._stop = context.Event()
            self.process = context.Process(target=_render_worker,
                                           args=(self._requests, self._frames, self._stop),
                                           name="JARVIS-ORB-RENDER", daemon=True)
            self.process.start()
            self._started = True
        except (OSError, RuntimeError) as exc:
            self.error = f"Renderer startup: {exc}"

    def request(self, request: RenderRequest):
        if not self._closed and not self.error and request != self._last_request:
            try:
                if _put_latest(self._requests, request):
                    self._last_request = request
            except (OSError, ValueError) as exc:
                self.error = f"Renderer transport: {exc}"

    def take(self):
        if self._closed or not self._started:
            return None
        try:
            payload = self._frames.get_nowait()
        except queue.Empty:
            if self.process.exitcode is not None:
                self.error = self.error or f"Renderer exited unexpectedly ({self.process.exitcode})"
            return None
        except (EOFError, OSError, ValueError) as exc:
            self.error = f"Renderer transport: {exc}"
            return None
        if payload[0] == "error":
            self.error = payload[1]
            return None
        _, size, image, self.render_ms = payload
        return size, image

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._stop is not None:
            self._stop.set()
        if self._started:
            self.process.join(timeout=.5)
        if self._started and self.process.is_alive():
            # Only this disposable renderer is terminated, never voice or a
            # user process. A failed child must not keep the desktop app alive.
            self.process.terminate()
            self.process.join(timeout=.5)
        for channel in (self._requests, self._frames):
            if channel is not None:
                channel.cancel_join_thread()
                channel.close()
