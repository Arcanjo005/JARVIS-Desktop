"""High-fidelity visual runtime for the cinematic JARVIS shell.

The main UI remains CustomTkinter for reliability, but the hero orb is rendered
as a supersampled physically-inspired glass sphere instead of stacked flat
ellipses. The renderer uses per-pixel normals, studio reflections, Fresnel,
GGX-like specular response, internal volumetric light, depth-aware orbital rings
and multi-pass bloom. Frames are cached per state so animation never performs
heavy math inside the normal Tk tick after the first render.
"""
from __future__ import annotations

import math
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter

try:
    import numpy as np
except Exception:
    np = None


def _norm3(x: float, y: float, z: float):
    length = math.sqrt(x*x + y*y + z*z) or 1.0
    return x/length, y/length, z/length


def _draw_projected_ring(layer, center, radius, tilt, yaw, phase, color, *, front: bool, width: int, alpha: int):
    """Draw half of a 3D ring so the sphere can occlude its back side."""
    cx, cy = center
    points = []
    segments = []
    cos_tilt, sin_tilt = math.cos(tilt), math.sin(tilt)
    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    samples = 220
    for index in range(samples + 1):
        t = (index / samples) * math.tau + phase
        x = radius * math.cos(t)
        y = radius * math.sin(t)
        z = 0.0
        # Tilt around X.
        yt = y * cos_tilt - z * sin_tilt
        zt = y * sin_tilt + z * cos_tilt
        xt = x
        # Turn the ellipse in screen space for a true orbital plane.
        xs = xt * cos_yaw - yt * sin_yaw
        ys = xt * sin_yaw + yt * cos_yaw
        is_front = zt >= 0.0
        if is_front == front:
            points.append((cx + xs, cy + ys))
        else:
            if len(points) >= 2:
                segments.append(points)
            points = []
    if len(points) >= 2:
        segments.append(points)

    draw = ImageDraw.Draw(layer)
    rgba = tuple(color) + (int(alpha),)
    for segment in segments:
        draw.line(segment, fill=rgba, width=max(1, int(width)), joint="curve")


def _studio_sphere(main, bright, dark, phase: float, S: int, radius: float):
    """Return a high-resolution RGBA PBR-like glass sphere."""
    if np is None:
        return None

    c = (S - 1) * 0.5
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    nx = (xx - c) / radius
    ny = (c - yy) / radius
    r2 = nx*nx + ny*ny
    inside = r2 <= 1.0
    nz = np.sqrt(np.clip(1.0-r2, 0.0, 1.0)).astype(np.float32)

    # Rotate coordinates used by the luminous material inside the glass. The
    # external normal stays spherical, so the orb reads as a solid 3D object.
    rot = phase * 0.56
    cr, sr = math.cos(rot), math.sin(rot)
    tx = nx*cr + nz*sr
    tz = -nx*sr + nz*cr
    ty = ny

    main_c = np.asarray(main, dtype=np.float32) / 255.0
    bright_c = np.asarray(bright, dtype=np.float32) / 255.0
    dark_c = np.asarray(dark, dtype=np.float32) / 255.0

    # Viewer always faces +Z.
    ndotv = np.clip(nz, 0.001, 1.0)

    def light_term(light, intensity, roughness):
        lx, ly, lz = _norm3(*light)
        ndotl = np.clip(nx*lx + ny*ly + nz*lz, 0.0, 1.0)
        hx, hy, hz = _norm3(lx, ly, lz + 1.0)
        ndoth = np.clip(nx*hx + ny*hy + nz*hz, 0.0, 1.0)
        vdoth = max(0.001, hz)
        a = max(0.035, roughness*roughness)
        a2 = a*a
        denom = ndoth*ndoth*(a2-1.0)+1.0
        distribution = a2 / np.maximum(math.pi*denom*denom, 1e-5)
        k = ((roughness+1.0)**2)/8.0
        g_v = ndotv / np.maximum(ndotv*(1.0-k)+k, 1e-5)
        g_l = ndotl / np.maximum(ndotl*(1.0-k)+k, 1e-5)
        geometry = g_v*g_l
        f0 = 0.085
        fres = f0 + (1.0-f0)*((1.0-vdoth)**5)
        spec = distribution*geometry*fres / np.maximum(4.0*ndotv*ndotl, 1e-4)
        spec = np.clip(spec, 0.0, 2.8)
        return ndotl*float(intensity), spec*float(intensity)

    diff1, spec1 = light_term((-0.52, 0.66, 0.88), 1.00, 0.18)
    diff2, spec2 = light_term((0.78, 0.12, 0.58), 0.52, 0.25)
    diff3, spec3 = light_term((-0.18, -0.92, 0.38), 0.24, 0.34)

    # Studio environment reflected in the glass. Broad + narrow strips make the
    # object look photographed rather than painted.
    refl_x = 2.0*nz*nx
    refl_y = 2.0*nz*ny
    refl_z = 2.0*nz*nz - 1.0
    studio_left = np.exp(-((refl_x + 0.63)/0.10)**2) * np.exp(-((refl_y - 0.08)/0.78)**2)
    studio_top = np.exp(-((refl_y - 0.72)/0.11)**2) * np.exp(-((refl_x + 0.05)/0.70)**2)
    studio_right = np.exp(-((refl_x - 0.76)/0.065)**2) * np.exp(-((refl_y + 0.10)/0.58)**2)
    env_horizon = np.clip(0.42 + 0.58*(refl_y*0.5+0.5), 0.0, 1.0)

    # Fresnel gives the characteristic glass rim. The stronger 5th-power term
    # stays thin and clean, while the 2nd-power term softly tints the silhouette.
    fresnel5 = np.clip(1.0-ndotv, 0.0, 1.0)**5
    fresnel2 = np.clip(1.0-ndotv, 0.0, 1.0)**2

    # Volumetric interior: slow, coherent structures seen through the surface.
    longitude = np.arctan2(tx, np.maximum(tz, 1e-5))
    latitude = np.arcsin(np.clip(ty, -1.0, 1.0))
    cloud_a = 0.5 + 0.5*np.sin(longitude*3.4 + latitude*2.2 + phase*1.15 + np.sin(latitude*4.0-phase)*0.9)
    cloud_b = 0.5 + 0.5*np.sin(longitude*5.8 - latitude*3.6 - phase*0.76 + np.sin(longitude*2.0+phase)*0.65)
    caustic = np.clip((cloud_a*0.58 + cloud_b*0.42)-0.48, 0.0, 1.0)**1.55
    depth = np.clip(nz, 0.0, 1.0)
    inner_core = np.exp(-r2*2.65) * (0.68 + caustic*0.42)
    inner_shell = np.exp(-((np.sqrt(np.clip(r2,0,1))-0.52)/0.22)**2) * (0.25+caustic*0.55)

    # Base transmission/absorption: deep color through thick center, brighter
    # turquoise at grazing angles and around the inner energy body.
    diffuse = 0.07 + diff1*0.41 + diff2*0.16 + diff3*0.06
    body_mix = np.clip(0.14 + diffuse + inner_core*0.42 + inner_shell*0.16, 0.0, 1.18)
    rgb = dark_c[None,None,:] + (main_c-dark_c)[None,None,:]*body_mix[...,None]

    # Cooler sky fill from the reflected environment.
    sky = bright_c[None,None,:] * (0.035 + env_horizon[...,None]*0.065)
    rgb += sky

    # Specular BRDF + photographic strip reflections.
    spec_total = spec1*0.46 + spec2*0.23 + spec3*0.10
    strips = studio_left*0.34 + studio_top*0.22 + studio_right*0.15
    rgb += bright_c[None,None,:] * (spec_total[...,None] + strips[...,None])

    # Volumetric light under the glass, deliberately softer than the reflections.
    rgb += bright_c[None,None,:] * ((inner_core*0.18 + caustic*depth*0.11)[...,None])

    # Glass edge and a slight lower-right absorption shadow add dimensionality.
    rgb += bright_c[None,None,:] * (fresnel5[...,None]*0.72 + fresnel2[...,None]*0.10)
    occlusion = np.clip((nx*0.42 - ny*0.33 + 0.18), 0.0, 1.0) * (1.0-depth)*0.16
    rgb *= (1.0-occlusion[...,None])

    # Thin white key highlight near the upper-left, blurred by the material but
    # still spatially anchored like a real light source.
    key = np.exp(-(((nx+0.33)/0.20)**2 + ((ny-0.36)/0.16)**2)) * (depth**1.6)
    rgb += key[...,None]*0.62

    # Gentle filmic shoulder instead of hard clipping.
    rgb = rgb / (1.0 + np.maximum(rgb-0.78, 0.0)*0.56)
    rgb = np.clip(rgb, 0.0, 1.0)
    # Gamma encode after lighting.
    rgb = np.power(rgb, 1.0/2.15)

    alpha = np.clip((1.0-r2)*34.0, 0.0, 1.0)
    arr = np.zeros((S,S,4), dtype=np.uint8)
    arr[...,:3] = (rgb*255.0).astype(np.uint8)
    arr[...,3] = (alpha*255.0).astype(np.uint8)
    arr[~inside,3] = 0
    return Image.fromarray(arr, "RGBA")


def _render_frame(self, state, phase, size=198, _fallback=None):
    if np is None:
        return _fallback(self, state, phase, size=size) if callable(_fallback) else None

    main, bright, dark = self._orb_palette(state)
    scale = 3
    S = int(size*scale)
    c = (S-1)*0.5
    radius = S*0.252
    canvas = Image.new("RGBA", (S,S), (0,0,0,0))

    # Bloom behind everything, built from the actual silhouette rather than flat
    # oversized discs. Multiple blur radii produce a lens-like falloff.
    silhouette = Image.new("RGBA", (S,S), (0,0,0,0))
    sd = ImageDraw.Draw(silhouette)
    sd.ellipse((c-radius,c-radius,c+radius,c+radius), fill=tuple(main)+(115,))
    for blur_radius, gain in ((S*0.065, 0.26), (S*0.035, 0.34), (S*0.018, 0.40)):
        layer = silhouette.filter(ImageFilter.GaussianBlur(max(1,int(blur_radius))))
        if gain < 0.99:
            alpha = layer.getchannel("A").point(lambda value, g=gain: int(value*g))
            layer.putalpha(alpha)
        canvas = Image.alpha_composite(canvas, layer)

    # Draw orbital backs before the sphere for real occlusion.
    ring_back = Image.new("RGBA", (S,S), (0,0,0,0))
    _draw_projected_ring(ring_back,(c,c),radius*1.39,math.radians(67),math.radians(17),phase*0.52,bright,front=False,width=max(4,int(S*0.006)),alpha=122)
    _draw_projected_ring(ring_back,(c,c),radius*1.58,math.radians(-54),math.radians(-28),-phase*0.31,main,front=False,width=max(3,int(S*0.0045)),alpha=72)
    ring_back_glow = ring_back.filter(ImageFilter.GaussianBlur(max(1,int(S*0.009))))
    canvas = Image.alpha_composite(canvas, ring_back_glow)
    canvas = Image.alpha_composite(canvas, ring_back)

    sphere = _studio_sphere(main, bright, dark, float(phase), S, radius)
    if sphere is None:
        return _fallback(self, state, phase, size=size) if callable(_fallback) else None
    canvas = Image.alpha_composite(canvas, sphere)

    # A subtle refractive rim is added as a separate optical pass.
    rim = Image.new("RGBA", (S,S), (0,0,0,0))
    rd = ImageDraw.Draw(rim)
    w = max(2,int(S*0.004))
    rd.ellipse((c-radius,c-radius,c+radius,c+radius), outline=tuple(bright)+(118,), width=w)
    rim_glow = rim.filter(ImageFilter.GaussianBlur(max(1,int(S*0.006))))
    canvas = Image.alpha_composite(canvas, rim_glow)
    canvas = Image.alpha_composite(canvas, rim)

    # Foreground halves of the same rings complete the 3D orbit around the ball.
    ring_front = Image.new("RGBA", (S,S), (0,0,0,0))
    _draw_projected_ring(ring_front,(c,c),radius*1.39,math.radians(67),math.radians(17),phase*0.52,bright,front=True,width=max(4,int(S*0.006)),alpha=205)
    _draw_projected_ring(ring_front,(c,c),radius*1.58,math.radians(-54),math.radians(-28),-phase*0.31,main,front=True,width=max(3,int(S*0.0045)),alpha=105)
    ring_front_glow = ring_front.filter(ImageFilter.GaussianBlur(max(1,int(S*0.008))))
    canvas = Image.alpha_composite(canvas, ring_front_glow)
    canvas = Image.alpha_composite(canvas, ring_front)

    # Tiny orbital light with bloom.
    px = c + math.cos(phase*0.88)*radius*1.47
    py = c + math.sin(phase*0.88)*radius*1.47*0.37
    particle = Image.new("RGBA",(S,S),(0,0,0,0))
    pd = ImageDraw.Draw(particle)
    pr = max(4,int(S*0.007))
    pd.ellipse((px-pr*3,py-pr*3,px+pr*3,py+pr*3),fill=tuple(bright)+(84,))
    particle = particle.filter(ImageFilter.GaussianBlur(pr*2))
    canvas = Image.alpha_composite(canvas,particle)
    pd = ImageDraw.Draw(canvas)
    pd.ellipse((px-pr*0.55,py-pr*0.55,px+pr*0.55,py+pr*0.55),fill=(248,253,255,245))

    # Supersampled output remains 2x the logical CTk size for HiDPI displays.
    final = canvas.resize((size*2,size*2),Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=final,dark_image=final,size=(size,size))


def install(gui_cls: Any) -> bool:
    """Install the renderer into gui_conversation_shell.JarvisGUI."""
    if gui_cls is None or getattr(gui_cls,"_jarvis_pbr_visual_installed",False):
        return bool(gui_cls is not None)
    original_build = getattr(gui_cls,"_build_orb_frame",None)

    def build(self,state,phase,size=198):
        return _render_frame(self,state,phase,size=size,_fallback=original_build)

    def frames(self,state):
        key = "PBR:"+str(state or "REPOUSO").upper()
        cached = self._cinematic_orb_cache.get(key)
        if cached:
            return cached
        # 24 frames gives a slower, continuous rotation without overloading Tk.
        result = [build(self,str(state or "REPOUSO").upper(),i/24.0*math.tau,size=198) for i in range(24)]
        self._cinematic_orb_cache[key]=result
        return result

    def animate(self):
        self._cinematic_orb_job=None
        try:
            label=getattr(self,"_cinematic_orb_label",None)
            if not label or not label.winfo_exists():
                return
            items=frames(self,getattr(self,"_cinematic_orb_state","REPOUSO"))
            index=int(getattr(self,"_cinematic_orb_frame",0))%len(items)
            label.configure(image=items[index],width=198,height=198)
            self._cinematic_orb_frame=(index+1)%len(items)
            self._cinematic_orb_job=self.root.after(88,self._animate_cinematic_orb)
        except Exception as exc:
            try:
                logger=getattr(self,"logger",None)
                if logger:
                    logger.warning(f"Renderer PBR da esfera: {exc}","GUI")
            except Exception:
                pass
            try:
                self._cinematic_orb_job=self.root.after(180,self._animate_cinematic_orb)
            except Exception:
                pass

    gui_cls._build_orb_frame=build
    gui_cls._orb_frames=frames
    gui_cls._animate_cinematic_orb=animate
    gui_cls._jarvis_pbr_visual_installed=True
    return True


__all__=["install"]
