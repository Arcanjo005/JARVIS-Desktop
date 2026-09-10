"""
JARVIS - GUI Module
Interface CustomTkinter profissional com System Monitor e tema Deep Charcoal & Electric Blue.
"""

# ==================== BIBLIOTECAS PADRÃO ====================
import os
import sys
import threading
import queue
import time
import re
import random
import math
import socket
import unicodedata
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Callable
from types import SimpleNamespace

def _enable_windows_crisp_dpi():
    """Ativa DPI por monitor antes do Tk criar a janela para evitar upscale borrado."""
    if os.name != "nt":
        return "non-windows"
    try:
        import ctypes
        # Windows 10+: PER_MONITOR_AWARE_V2. Valor especial documentado pela Win32 API.
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return "per-monitor"
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
        return "system-aware"
    except Exception:
        return "fallback"


JARVIS_DPI_MODE = _enable_windows_crisp_dpi()

# ==================== BIBLIOTECAS DE TERCEIROS ====================
import customtkinter as ctk
from tkinter import messagebox, scrolledtext, filedialog, simpledialog
from PIL import Image, ImageTk, ImageDraw, ImageFilter, ImageFont, ImageColor
import io
import base64
import json

try:
    import psutil
except Exception:
    psutil = None

# ==================== MÓDULOS PRÓPRIOS ====================
from config import Config
from web_search import WebSearch
from memory_store import MemoryStore
from jarvis_runtime import ensure_runtime_dirs, install_exception_hooks, foreground_window_title
from jarvis_plugins import PluginManager
from jarvis_version import VERSION as JARVIS_VERSION, BUILD as JARVIS_BUILD, PUBLIC_NAME
from jarvis_identity import env as jarvis_env, LEGACY_NAME
from text_sanitizer import sanitize_text
from github_updater import GitHubReleaseUpdater

# Build 15: componentes opcionais pesados sao carregados sob demanda depois
# que a janela principal ja pode aparecer. Isto encurta o caminho critico de boot.
OperationalContext = None
ObserverEngine = None
BrowserAutonomyEngine = None
GoalExecutor = None
WorkflowEngine = None
MediaContextEngine = None
ConditionalRuleEngine = None
ExperienceEngine = None
BehaviorMemory = None
PerformanceTracer = None

try:
    from jarvis_router import (
        route as route_v8,
        mark_app_success as v8_mark_app_success,
        mark_action_success as v8_mark_action_success,
        mark_feedback as v8_mark_feedback,
        observe_context as v8_observe_context,
        remember_topic as v8_remember_topic,
        remember_media as v8_remember_media,
        context_status as v8_context_status,
    )
except Exception:
    route_v8 = lambda text: None
    v8_mark_app_success = lambda app: None
    v8_mark_action_success = lambda action, target='', before=None, after=None: None
    v8_mark_feedback = lambda text: None
    v8_observe_context = lambda **kwargs: None
    v8_remember_topic = lambda topic: None
    v8_remember_media = lambda media: None
    v8_context_status = lambda: {}

try:
    from intent_parser import (
        normalize_command as normalize_local_intent,
        looks_like_local_command as looks_like_local_intent,
    )
except Exception:
    normalize_local_intent = lambda text: str(text or "").strip()
    looks_like_local_intent = lambda text: False

QtVoiceOverlayController = None
OVERLAY_FULL_WIDTH, OVERLAY_FULL_HEIGHT = 380, 360
DesktopIntegration = None
AdvancedWindows = None
SafetyManager = None
AudioDeviceManager = None
VisionSystem = None
DiagnosticsManager = None
VoiceEngine = None

class VoiceEngineError(RuntimeError):
    pass

def _ui_rgb(color: str, fallback=(120, 140, 255)):
    try:
        return ImageColor.getrgb(str(color))
    except Exception:
        return fallback


def _ui_mix(color: str, toward=(255, 255, 255), amount=0.25):
    base = _ui_rgb(color)
    amount = max(0.0, min(float(amount), 1.0))
    return tuple(int(round(a + (b - a) * amount)) for a, b in zip(base, toward))


def _ui_supersampled_icon(kind: str, size: int = 18, color: str = "#D9DDE7"):
    """Ícones leves desenhados em 4x e reduzidos com LANCZOS para bordas suaves."""
    scale = 4
    px = max(8, int(size))
    S = px * scale
    image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    fg = _ui_rgb(color)
    w = max(scale * 2, int(round(px * 0.105 * scale)))
    def line(points, width=w, fill=fg):
        draw.line([(int(x*scale), int(y*scale)) for x, y in points], fill=fill, width=max(scale, int(width)), joint="curve")
    if kind == "search":
        box = [3.0*scale, 3.0*scale, 12.1*scale, 12.1*scale]
        draw.ellipse(box, outline=fg, width=w)
        line([(10.5, 10.5), (15.6, 15.6)], width=w)
    elif kind == "new_chat":
        # Folha + lápis minimalista.
        r = [3.2*scale, 3.0*scale, 13.2*scale, 14.7*scale]
        draw.rounded_rectangle(r, radius=2.2*scale, outline=fg, width=w)
        line([(8.0, 11.8), (14.9, 4.9)], width=w)
        line([(13.6, 4.0), (15.8, 6.2)], width=w)
    elif kind == "sidebar":
        r = [2.5*scale, 3.0*scale, 15.5*scale, 15.0*scale]
        draw.rounded_rectangle(r, radius=2.2*scale, outline=fg, width=w)
        line([(7.0, 3.7), (7.0, 14.3)], width=max(scale, int(w*0.8)))
    elif kind == "dots":
        radius = 1.45 * scale
        for y in (4.0, 9.0, 14.0):
            draw.ellipse((9*scale-radius, y*scale-radius, 9*scale+radius, y*scale+radius), fill=fg)
    elif kind == "voice":
        draw.ellipse((5.2*scale, 2.0*scale, 12.8*scale, 11.5*scale), outline=fg, width=w)
        line([(3.8, 9.0), (3.8, 10.0), (4.5, 12.1), (6.3, 13.6), (9.0, 14.1), (11.7, 13.6), (13.5, 12.1), (14.2, 10.0), (14.2, 9.0)], width=max(scale, int(w*0.85)))
        line([(9.0, 14.2), (9.0, 16.0)], width=max(scale, int(w*0.85)))
    elif kind == "send":
        line([(4.0, 10.7), (9.0, 5.7), (14.0, 10.7)], width=w)
        line([(9.0, 5.9), (9.0, 15.3)], width=w)
    elif kind == "copy":
        draw.rounded_rectangle((5.0*scale, 4.0*scale, 14.3*scale, 14.5*scale), radius=1.8*scale, outline=fg, width=w)
        draw.rounded_rectangle((2.7*scale, 2.0*scale, 11.8*scale, 12.0*scale), radius=1.8*scale, outline=_ui_mix(color, amount=0.10), width=max(scale, int(w*0.78)))
    else:
        draw.ellipse((4*scale, 4*scale, 14*scale, 14*scale), outline=fg, width=w)
    # CTkImage recebe fonte 4x e escolhe a resolução física conforme o DPI.
    return image


def _render_tech_j_image(size: int = 36):
    """Emblema J com glow e antialiasing real, sem asset externo."""
    scale = 4
    px = max(24, int(size))
    S = px * scale
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    c = S / 2
    r = S * 0.415
    points = []
    for i in range(6):
        a = math.radians(30 + i * 60)
        points.append((c + r * math.cos(a), c + r * math.sin(a)))

    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line(points + [points[0]], fill=(88, 128, 255, 150), width=max(5, int(S*0.055)), joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(max(2, int(S*0.035))))
    base = Image.alpha_composite(base, glow)

    d = ImageDraw.Draw(base)
    d.polygon(points, fill=(22, 25, 34, 255))
    d.line(points + [points[0]], fill=(112, 147, 255, 255), width=max(3, int(S*0.022)), joint="curve")
    inner = r * 0.70
    d.ellipse((c-inner, c-inner, c+inner, c+inner), outline=(51, 78, 133, 255), width=max(2, int(S*0.013)))
    # Pequenos cortes HUD dão aparência de peça, não de emoji.
    for a0, a1 in ((210, 258), (282, 330), (28, 70)):
        d.arc((c-inner*0.88, c-inner*0.88, c+inner*0.88, c+inner*0.88), a0, a1, fill=(92, 151, 255, 230), width=max(2, int(S*0.016)))

    font = None
    font_size = max(13, int(px*0.49)) * scale
    candidates = []
    if os.name == "nt":
        candidates.extend([
            r"C:\Windows\Fonts\seguisb.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
        ])
    candidates.extend(["DejaVuSans-Bold.ttf", "Arial Bold.ttf"])
    for candidate in candidates:
        try:
            font = ImageFont.truetype(candidate, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    text = "J"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    tx = c - tw/2 - bbox[0]
    ty = c - th/2 - bbox[1] - S*0.035
    # Glow do J.
    tg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tgd = ImageDraw.Draw(tg)
    tgd.text((tx, ty), text, font=font, fill=(137, 184, 255, 150))
    tg = tg.filter(ImageFilter.GaussianBlur(max(1, int(S*0.018))))
    base = Image.alpha_composite(base, tg)
    d = ImageDraw.Draw(base)
    d.text((tx, ty), text, font=font, fill=(239, 244, 255, 255))
    y = c + r*0.53
    d.line((c-r*0.42, y, c+r*0.40, y), fill=(105, 144, 255, 255), width=max(3, int(S*0.022)))
    # Mantém a fonte 4x para CTkImage não precisar ampliar em telas HiDPI.
    return base


class CircularMetricGauge(ctk.CTkFrame):
    """Medidor circular antialiased com interpolação suave e cache de frames."""
    def __init__(self, master, title: str, accent: str, size: int = 62, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.size = int(size)
        self.accent = accent
        self._fraction = 0.0
        self._target_fraction = 0.0
        self._target_text = "--"
        self._animation_job = None
        self._frame_cache = {}
        self._ctk_image = None
        self.image_label = ctk.CTkLabel(
            self, text="", width=self.size, height=self.size, fg_color="transparent"
        )
        self.image_label.pack()
        self.value_label = ctk.CTkLabel(
            self, text="--", width=self.size, height=18,
            text_color="#F5F6F8", fg_color="transparent",
            font=ctk.CTkFont(family="Tahoma", size=10, weight="bold")
        )
        self.value_label.place(x=self.size/2, y=self.size/2-1, anchor="center")
        self.title_label = ctk.CTkLabel(
            self, text=title, text_color="#A0A7B2",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold")
        )
        self.title_label.pack(pady=(0, 0))
        self._render_fraction(0.0)

    def _ring_frame(self, fraction: float):
        key = max(0, min(100, int(round(float(fraction) * 100))))
        cached = self._frame_cache.get(key)
        if cached is not None:
            return cached
        scale = 2
        S = self.size * scale
        pad = int(6 * scale)
        box = (pad, pad, S-pad, S-pad)
        width = max(scale*4, int(round(4.6*scale)))
        image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.arc(box, start=-90, end=269.8, fill=(48, 52, 60, 255), width=width)
        if key > 0:
            end = -90 + 359.8 * (key/100.0)
            accent = _ui_rgb(self.accent)
            glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.arc(box, start=-90, end=end, fill=accent + (120,), width=width + int(2.5*scale))
            glow = glow.filter(ImageFilter.GaussianBlur(max(1, int(1.5*scale))))
            image = Image.alpha_composite(image, glow)
            draw = ImageDraw.Draw(image)
            draw.arc(box, start=-90, end=end, fill=accent + (255,), width=width)
            highlight = _ui_mix(self.accent, amount=0.30)
            draw.arc(box, start=-90, end=end, fill=highlight + (220,), width=max(scale, int(width*0.34)))
        # Fonte 2x: CTkImage mantém nitidez até escalas altas sem cache excessivo.
        frame = image
        self._frame_cache[key] = frame
        return frame

    def _render_fraction(self, fraction: float):
        self._fraction = max(0.0, min(float(fraction), 1.0))
        frame = self._ring_frame(self._fraction)
        self._ctk_image = ctk.CTkImage(light_image=frame, dark_image=frame, size=(self.size, self.size))
        try:
            self.image_label.configure(image=self._ctk_image)
        except Exception:
            pass

    def update_value(self, fraction: float, text: str):
        try:
            target = max(0.0, min(float(fraction), 1.0))
        except Exception:
            target = 0.0
        self._target_fraction = target
        self._target_text = str(text)
        try:
            self.value_label.configure(text=self._target_text)
        except Exception:
            pass
        try:
            if self._animation_job:
                self.after_cancel(self._animation_job)
        except Exception:
            pass
        self._animation_job = None
        start = float(self._fraction)
        delta = target - start
        if abs(delta) < 0.012:
            self._render_fraction(target)
            return
        frames = 7
        interval = 24
        def animate(step=1):
            if not self.winfo_exists():
                return
            t = min(1.0, step / frames)
            eased = 1.0 - (1.0 - t) ** 3
            self._render_fraction(start + delta * eased)
            if step < frames:
                self._animation_job = self.after(interval, lambda: animate(step + 1))
            else:
                self._animation_job = None
                self._render_fraction(target)
        animate(1)


class JarvisGUI:
    WINDOW_OPACITY = float(jarvis_env("WINDOW_OPACITY", "1.00"))
    UI_CRISP_RENDER = str(jarvis_env("UI_CRISP_RENDER", "1")).strip().lower() not in {"0", "false", "off", "nao", "não"}
    UI_MOTION_INTERVAL_MS = 12
    VOICE_ORB_OPACITY = max(0.60, min(float(jarvis_env("VOICE_ORB_OPACITY", "0.90")), 1.00))
    SIDEBAR_MIN = 176
    SIDEBAR_MAX = 286
    SIDEBAR_DEFAULT = 224
    COMPOSER_MIN_HEIGHT = 48
    COMPOSER_MAX_HEIGHT = 124
    COMPOSER_MAX_CHARS = 16000

    # Esfera do modo de voz.
    VOICE_ORB_WIDTH = 480
    VOICE_ORB_HEIGHT = 430

    # Efeito elétrico do logotipo JARVIS.
    JARVIS_LIGHTNING_ENABLED = True
    JARVIS_LIGHTNING_INTERVAL_MS = 135
    JARVIS_LIGHTNING_INTENSITY = 0.72

    """Interface principal do JARVIS.
    
    Esta classe implementa a interface gráfica do assistente JARVIS,
    incluindo chat em tempo real, system monitor, comandos de voz
    e integração com todas as funcionalidades do sistema.
    
    Attributes:
        logger: Instância do logger para registrar eventos
        actions: Instância do SystemActions para executar comandos
        core: Instância do Core para processamento de IA
        root: Janela principal da aplicação
        chat_display: Widget de exibição do chat
        text_input: Campo de entrada de texto do usuário
        voice_button: Botão de ativação de voz
        send_button: Botão de envio de mensagens
        system_log_text: Widget de exibição dos logs do sistema
        is_processing: Flag indicando processamento em andamento
        is_listening: Flag indicando modo de escuta ativo
        voice_enabled: Flag indicando disponibilidade de voz
        typing_active: Flag indicando efeito de digitação em andamento
        chat_history: Histórico de mensagens do chat
        current_response: Resposta atual sendo processada
        monitor_visible: Flag indicando visibilidade do System Monitor
    """
    
    def __init__(self, logger, actions, core):
        """Inicializa a interface gráfica do JARVIS.
        
        Configura todos os componentes da interface, incluindo:
        - Sistema de voz e reconhecimento
        - Layout principal com chat e system monitor
        - Cores e fontes do tema JARVIS
        - Componentes interativos
        
        Args:
            logger: Instância do logger para registrar eventos
            actions: Instância do SystemActions para executar comandos
            core: Instância do Core para processamento de IA
            
        Raises:
            Exception: Caso ocorra erro na inicialização da interface
        """
        self.logger = logger
        self.actions = actions
        self.core = core

        # Runtime enxuto: cria apenas as pastas ativas e instala o crash log.
        # Backups automáticos de código foram removidos da distribuição.
        self.project_dir = str(ensure_runtime_dirs(os.environ.get("JARVIS_APP_DIR") or os.path.dirname(os.path.abspath(__file__))))
        install_exception_hooks(self.project_dir)

        self.web_search = WebSearch(logger)
        self.plugin_manager = PluginManager(logger)

        # =====================================================
        # MEMÓRIA PERSISTENTE
        # =====================================================
        # Precisa existir ANTES de _setup_gui(), pois a interface
        # já monta a lista de conversas e restaura o último chat.
        try:
            self.memory_store = MemoryStore(logger)
        except Exception as exc:
            # V8 fail-open: memoria e auxiliar. Mesmo sem disco gravavel,
            # conversa/comandos/TTS continuam com uma base SQLite efemera.
            try:
                self.logger.error(exc, "Memoria persistente indisponivel; usando memoria efemera", "MEMORY")
            except Exception:
                pass
            self.memory_store = MemoryStore(logger, db_path=":memory:")
        self.active_conversation_id = (
            self.memory_store.get_or_create_active_conversation()
        )
        self._restoring_history = False

        self.logger.info(
            f"Memória persistente inicializada: {self.memory_store.db_path}",
            "MEMORY"
        )

        # Build 15: aprendizado/telemetria deixam de bloquear a abertura.
        # Os objetos entram em background logo apos o primeiro frame da GUI.
        self.performance_tracer = None
        self.experience_engine = None
        self.behavior_memory = None

        # Estado da interface
        self.is_processing = False
        self.is_listening = False
        self.voice_enabled = False
        self.typing_active = False
        # Geracao de trabalho: Priority Interrupt invalida planos/streaming em
        # andamento sem depender de matar a thread de rede à força.
        self._work_generation = 0
        self._work_generation_lock = threading.Lock()
        # Cada worker de conversa carrega o token do turno em thread-local.
        # Assim mensagens locais/plugins também são descartadas se o usuário
        # iniciar um turno novo antes de a fila Tk processar o resultado.
        self._work_thread_context = threading.local()
        
        # Histórico e mensagens
        self.chat_history = []
        self.current_response = ""
        # Identidade de tratamento da sessão. Não usa biometria/cadastro de voz:
        # o nome só muda por configuração explícita ou por comandos como
        # "me chama de Bruno" / "eu sou Bruno".
        env_user_name = self._normalize_session_user_name(str(jarvis_env("USER_NAME", "") or ""))
        self._session_user_name = env_user_name or self._load_persistent_user_name()
        
        # Componentes da interface
        self.root = None
        self._main_thread_id = threading.get_ident()
        self.chat_display = None
        self.text_input = None
        self.send_button = None
        self.voice_button = None
        self.status_label = None
        self.system_monitor = None
        self.system_log_text = None
        self.monitor_visible = False

        # Estado visual moderno
        self.chat_scroll = None
        self.streaming_label = None
        self.streaming_buffer = ""

        # Chat responsivo: respeita scroll manual e agrupa chunks do streaming.
        self._chat_auto_scroll = True
        self._chat_wheel_bound = False
        # Build 15: scroll de alta resolucao/touchpad com limite e anti-loop.
        self._chat_wheel_remainder = 0
        self._chat_manual_scroll_until = 0.0
        self._chat_scroll_job = None
        self._active_stream_token = 0
        self._stream_chunk_queue = queue.Queue()
        self._stream_flush_requested = threading.Event()
        self._log_update_job = None

        # Build 16: restauração visual em lotes e composer conversacional.
        self._history_restore_active = False
        self._history_restore_generation = 0
        self._history_restore_job = None
        self._deferred_visual_messages = []
        self._composer_placeholder_active = False
        self._composer_placeholder_text = f"Pergunte ou diga um comando ao {PUBLIC_NAME}..."

        # TTS progressivo: começa a falar antes da resposta terminar de gerar.
        self._voice_stream_tts_buffer = ""
        self._voice_stream_tts_started = False
        self._voice_stream_tts_queued_count = 0
        self.cpu_value_label = None
        self.ram_value_label = None
        self.network_value_label = None
        self.cpu_progress = None
        self.ram_progress = None
        self.network_progress = None
        self.media_value_label = None
        self.activity_label = None
        self.status_dot = None
        self.conversation_list_frame = None
        self.history_search_entry = None
        self.current_conversation_label = None
        self.quick_menu = None
        self.quick_panel = None
        self.quick_panel_is_open = False
        self.input_shell = None
        self._input_focus_job = None
        self._quick_panel_voice_value = None
        self._quick_panel_mic_value = None
        self._quick_panel_mode_value = None
        self._quick_panel_autonomy_value = None
        self._quick_panel_presence_value = None
        self._autonomy_percent = 60
        self._presence_percent = 60
        self._conversation_search_popup = None
        self._conversation_search_button = None
        self._new_chat_button = None
        self._ui_icon_cache = {}
        self._tech_j_image = None
        self._brand_logo_image = None
        self._stream_render_job = None
        self._stream_last_render_at = 0.0
        self.cpu_gauge = None
        self.ram_gauge = None
        self.network_gauge = None
        self.clock_label = None
        self.active_app_label = None
        self.side_panel = None
        self.content_frame = None
        self.sidebar_splitter = None
        self._sidebar_width = self.SIDEBAR_DEFAULT
        self._sidebar_drag_start_x = None
        self._sidebar_drag_start_width = self.SIDEBAR_DEFAULT
        self.compact_mode = False
        self.last_network_total = None
        self.last_network_time = None
        self.last_media_title = "Nenhuma mídia ativa"

        # Logo elétrico JARVIS
        self.jarvis_logo_canvas = None
        self._jarvis_lightning_job = None
        self._jarvis_lightning_frame = 0

        # Modo de voz visual
        self.voice_overlay = None
        self.voice_orb_canvas = None
        self.voice_overlay_text_label = None
        self.voice_overlay_state_label = None
        self.voice_orb_animation_job = None
        self.voice_orb_phase = 0.0
        self.voice_orb_speaking = False
        self.voice_visual_mode = False
        self.voice_orb_style = self._load_orb_style()
        self.voice_last_text = f"{PUBLIC_NAME} está pronto."
        self.qt_voice_overlay = None
        self._qt_overlay_active = False
        self._orb_context_compact = True
        self._orb_context_title = ""

        # Recursos de interface avançada
        self.volume_value_label = None
        self.volume_slider = None
        self._volume_apply_job = None
        self._volume_ui_updating = False
        self._last_volume_refresh = 0.0
        self.jarvis_status_color = "#31D47D"
        self.diagnostic_window = None
        self.memory_manager_window = None
        self.alias_manager_window = None

        # Movimento suave e modo de voz
        self._window_in_motion = False
        self._window_motion_job = None
        self._root_state_before_voice = "normal"
        self._voice_transparent_key = "#010203"

        # Renderização 3D + arraste suave da esfera
        self._orb_base_pil = None
        self._orb_base_color = None
        self._voice_orb_photo = None
        self.voice_engine = None
        self._voice_command_active = False
        self._voice_engine_state = "DESATIVADO"
        self._voice_engine_detail = ""
        self._voice_dragging = False
        self._voice_drag_offset_x = 0
        self._voice_drag_offset_y = 0
        self._voice_drag_target = None
        self._voice_drag_job = None
        self._voice_drag_start_root = None
        self._voice_close_pressed = False
        self._voice_font_cache = {}

        # Integração desktop / bandeja / hotkey
        self.desktop_integration = None
        self._exit_requested = False
        self._root_hidden_before_voice = False

        # Nível real do microfone para animar a esfera.
        self.voice_mic_level = 0.0
        self._voice_mic_smoothed = 0.0

        # Modo avançado
        self.window_manager = None
        self.safety_manager = None
        self.audio_device_manager = None
        self.vision_system = None
        self.diagnostics_manager = None

        # Build 11 - Agent Runtime / contexto operacional.
        self.operational_context = None
        self.browser_autonomy = None
        self.media_context = None
        self.conditional_rules = None
        self.goal_executor = None
        self.workflow_engine = None
        self.observer_engine = None
        self._last_rule_candidate = None
        self.agent_hud = None
        self.agent_hud_title = None
        self.agent_hud_step = None
        self.agent_hud_progress = None
        self.agent_stop_button = None
        self.source_badge = None
        self.context_app_label = None
        self.context_site_label = None
        self.context_goal_label = None
        self.context_download_label = None
        self.autonomy_segment = None
        self.presence_segment = None
        self.sidebar_state_button = None
        self._sidebar_state = "full"
        self._sidebar_last_full_width = self.SIDEBAR_DEFAULT
        self._agent_last_status = "idle"

        self.interaction_mode = "auto"
        self._voice_visual_state = "REPOUSO"

        self._pending_confirmation = None
        self._confirmation_voice_followup = False
        self._voice_followup_after_tts = False
        self._voice_followup_question_text = ""
        self._voice_followup_job = None
        self._last_auto_diagnostic_at = 0.0

        # JARVIS Desktop 1.0: configuração segura e atualização via GitHub Releases.
        self.update_manager = GitHubReleaseUpdater(self.project_dir, current_version=JARVIS_VERSION, logger=self.logger)
        self.update_button = None
        self.api_button = None
        self._pending_update_info = None
        self._update_download_active = False

        # Fila thread-safe: áudio/hotkey/tray nunca tocam Tk diretamente.
        self._ui_event_queue = queue.Queue()
        self._ui_event_job = None

        # Build 15: primeiro frame antes dos subsistemas pesados.
        # Preferencias puramente visuais podem ser lidas antes do motor de voz.
        self._apply_saved_quick_preferences()
        self._setup_gui()
        self._start_ui_event_pump()
        self._start_persistent_reminder_watcher()
        self._start_jarvis_player_watcher()

        # So depois que o mainloop comecar carregamos voz/agente/overlay/desktop.
        # O usuario ve e pode usar o chat imediatamente; os subsistemas entram
        # em paralelo e sinalizam a GUI via fila thread-safe.
        self.root.after(40, self._start_deferred_runtime)
        
        self.logger.info("GUI inicializada com sucesso (boot rapido)", "GUI")
        self.logger.system(f"Interface {PUBLIC_NAME} carregada", "GUI")
    
    def _start_deferred_runtime(self):
        """Carrega subsistemas fora do caminho critico do primeiro frame."""
        jobs = [
            ("JARVIS-BOOT-AI", getattr(self.core, "prewarm", lambda: None)),
            ("JARVIS-BOOT-VOICE", self._setup_voice),
            ("JARVIS-BOOT-LEARNING", self._setup_learning_runtime),
            ("JARVIS-BOOT-ADVANCED", self._setup_advanced_modules),
            ("JARVIS-BOOT-OVERLAY", self._setup_qt_voice_overlay),
            ("JARVIS-BOOT-DESKTOP", self._setup_desktop_integration),
            ("JARVIS-BOOT-APPINDEX", self.actions.rebuild_app_index),
            ("JARVIS-BOOT-UPDATER", self._background_update_check),
        ]
        for name, target in jobs:
            try:
                threading.Thread(target=target, name=name, daemon=True).start()
            except Exception as exc:
                try:
                    self.logger.warning(f"Boot diferido falhou em {name}: {exc}", "BOOT")
                except Exception:
                    pass

    def _setup_learning_runtime(self):
        """Inicializa telemetria/aprendizado sem atrasar a abertura da janela."""
        global PerformanceTracer, ExperienceEngine, BehaviorMemory
        if PerformanceTracer is None:
            try:
                from performance_tracer import PerformanceTracer as _PerformanceTracer
                PerformanceTracer = _PerformanceTracer
            except Exception:
                PerformanceTracer = None
        if ExperienceEngine is None:
            try:
                from experience_engine import ExperienceEngine as _ExperienceEngine
                ExperienceEngine = _ExperienceEngine
            except Exception:
                ExperienceEngine = None
        if BehaviorMemory is None:
            try:
                from behavior_memory import BehaviorMemory as _BehaviorMemory
                BehaviorMemory = _BehaviorMemory
            except Exception:
                BehaviorMemory = None

        if PerformanceTracer is not None and self.performance_tracer is None:
            try:
                self.performance_tracer = PerformanceTracer(self.project_dir, logger=self.logger)
            except Exception as exc:
                try:
                    self.logger.warning(f"Performance Tracer indisponivel: {exc}", "PERF")
                except Exception:
                    pass

        if ExperienceEngine is not None and self.experience_engine is None:
            try:
                self.experience_engine = ExperienceEngine(self.project_dir, logger=self.logger)
                stats = self.experience_engine.stats()
                self.logger.info(
                    f"Experience Engine: {stats.get('experiences', 0)} experiencias, "
                    f"{stats.get('trusted', 0)} frases confiaveis", "EXPERIENCE"
                )
            except Exception as exc:
                try:
                    self.logger.warning(f"Experience Engine indisponivel: {exc}", "EXPERIENCE")
                except Exception:
                    pass
                self.experience_engine = None

        if BehaviorMemory is not None and self.behavior_memory is None:
            try:
                self.behavior_memory = BehaviorMemory(self.project_dir, logger=self.logger)
                bstats = self.behavior_memory.stats()
                self.logger.info(
                    f"Behavior Memory: {bstats.get('patterns', 0)} padroes observados", "BEHAVIOR"
                )
            except Exception as exc:
                try:
                    self.logger.warning(f"Behavior Memory indisponivel: {exc}", "BEHAVIOR")
                except Exception:
                    pass
                self.behavior_memory = None

        self._post_ui_event("runtime_ready", "learning")

    def _setup_voice(self):
        """Inicializa wake word, STT e TTS em background apos o primeiro frame."""
        global VoiceEngine, VoiceEngineError
        self.recognizer = None
        self.microphone = None
        self.voice_enabled = False

        if VoiceEngine is None:
            try:
                from voice_engine import VoiceEngine as _VoiceEngine, VoiceEngineError as _VoiceEngineError
                VoiceEngine = _VoiceEngine
                VoiceEngineError = _VoiceEngineError
            except Exception as exc:
                self.logger.warning(f"voice_engine.py não pôde ser carregado: {exc}", "VOICE")
                return

        try:
            self.voice_engine = VoiceEngine(
                project_dir=self.project_dir,
                logger=self.logger,
                on_state=self._on_voice_engine_state,
                on_wake=self._on_voice_wake,
                on_command=self._on_voice_command,
                on_transcript_rejected=self._on_voice_rejected,
                on_tts_start=self._on_voice_tts_start,
                on_tts_end=self._on_voice_tts_end,
                on_level=self._on_voice_level,
                on_audio_metrics=self._on_voice_audio_metrics,
                on_interrupt=self._on_voice_interrupt,
                on_caption=self._on_voice_caption,
                on_live_transcript=self._on_voice_live_transcript,
            )
            # Restaura apenas preferencias de voz sem tocar widgets Tk.
            try:
                prefs_path = Path(self.project_dir) / "data" / "ui_layout.json"
                if prefs_path.exists():
                    prefs = json.loads(prefs_path.read_text(encoding="utf-8")) or {}
                    rate = str(prefs.get("tts_rate") or "").strip()
                    if rate:
                        self.voice_engine.set_tts_rate(rate)
                    if prefs.get("mic_sensitivity") is not None:
                        self.voice_engine.set_microphone_sensitivity(float(prefs.get("mic_sensitivity")))
                    self.voice_engine.set_conversation_mode(str(self.interaction_mode or "").lower() == "conversa")
            except Exception:
                pass
            self.voice_engine.start()
            # O engine inicia de forma assíncrona. `start()` apenas cria as
            # threads; microfone, PortAudio e Vosk ainda podem falhar alguns
            # instantes depois. Mantemos o recurso habilitado para permitir
            # auto-recuperação, mas só anunciamos VOZ PRONTA quando a captura
            # realmente abriu.
            self.voice_enabled = True
            self.logger.info(
                "Motor de voz iniciado; aguardando microfone/wake ficarem prontos.",
                "VOICE"
            )
            threading.Thread(
                target=self._monitor_voice_runtime,
                name="JARVIS-VOICE-SUPERVISION",
                daemon=True,
            ).start()
        except Exception as e:
            self.voice_enabled = False
            self.voice_engine = None
            self.logger.error(
                e,
                "Erro ao inicializar motor de voz",
                "VOICE"
            )

    def _monitor_voice_runtime(self):
        """Confirma boot real da voz e acompanha recuperação do microfone.

        Nunca toca widgets Tk diretamente. O VoiceEngine possui seu próprio
        supervisor e pode recuperar um microfone que apareceu após o boot.
        Esta rotina apenas publica telemetria/estado quando a escuta realmente
        fica operacional.
        """
        engine = self.voice_engine
        if engine is None:
            return

        announced_ready = False
        last_signature = None
        while self.voice_engine is engine:
            try:
                if engine.wait_until_ready(1.0):
                    if not announced_ready:
                        announced_ready = True
                        status = engine.status()
                        mic = str(status.get("input_device") or status.get("input_device_name") or "microfone padrão")
                        self.logger.info(f"Voz pronta para wake word no dispositivo: {mic}", "VOICE")
                        self._post_ui_event("runtime_ready", "voice")
                    # Continua monitorando: se o stream cair, o supervisor do
                    # engine tentará reabrir e o estado visual será atualizado.
                    continue

                status = engine.status()
                signature = (
                    str(status.get("state") or ""),
                    str(status.get("last_error") or "")[:180],
                    int(status.get("startup_attempts") or 0),
                )
                if signature != last_signature:
                    last_signature = signature
                    detail = signature[1] or "Aguardando dispositivo de entrada"
                    self.logger.warning(
                        f"Voz ainda não pronta (tentativa {signature[2]}): {detail}",
                        "VOICE",
                    )
            except Exception as exc:
                self.logger.warning(f"Monitor do motor de voz: {exc}", "VOICE")

            try:
                if getattr(engine, "_stop_event", None) is not None and engine._stop_event.wait(0.8):
                    return
            except Exception:
                import time
                time.sleep(0.8)

    def _setup_qt_voice_overlay(self):
        """Overlay Qt real-alpha; importado depois do primeiro frame."""
        global QtVoiceOverlayController, OVERLAY_FULL_WIDTH, OVERLAY_FULL_HEIGHT
        if QtVoiceOverlayController is None:
            try:
                from voice_overlay_qt import QtVoiceOverlayController as _QtVoiceOverlayController, OVERLAY_FULL_WIDTH as _OFW, OVERLAY_FULL_HEIGHT as _OFH
                QtVoiceOverlayController = _QtVoiceOverlayController
                OVERLAY_FULL_WIDTH, OVERLAY_FULL_HEIGHT = _OFW, _OFH
            except Exception:
                return
        try:
            controller = QtVoiceOverlayController(
                self.project_dir,
                logger=self.logger,
            )
            if controller.start():
                self.qt_voice_overlay = controller
                self._qt_overlay_active = True
                try:
                    controller.set_orb_style(self.voice_orb_style)
                    controller.set_conversation_lock(str(self.interaction_mode or "").lower() == "conversa")
                except Exception:
                    pass
                self.logger.info(
                    "Overlay de voz Qt ativo (transparente/click-through).",
                    "OVERLAY"
                )
                self._post_ui_event("runtime_ready", "overlay")
        except Exception as e:
            self.qt_voice_overlay = None
            self._qt_overlay_active = False
            self.logger.warning(
                f"Overlay Qt indisponível; fallback Tk: {e}",
                "OVERLAY"
            )

    def _on_voice_caption(self, text):
        clean = sanitize_text(text, limit=520)
        self._post_ui_event("voice_caption", clean)

    def _on_voice_live_transcript(self, text):
        """Transcricao parcial/final do usuario para o overlay, sem tocar no chat."""
        clean = sanitize_text(text, limit=360)
        if clean:
            self._post_ui_event("voice_user_caption", clean)

    def _clear_qt_caption_if_idle(self):
        try:
            if (
                self.qt_voice_overlay
                and not (self.voice_engine and self.voice_engine.speaking)
            ):
                self.qt_voice_overlay.set_caption("")
        except Exception:
            pass

    def _qt_overlay_position(self):
        """Retorna um ponto-alvo no canto do monitor ativo.

        A posição manual antiga não é restaurada automaticamente: o modo de voz
        13.10.3 fica ancorado no canto inferior direito por padrão.
        """
        width, height = OVERLAY_FULL_WIDTH, OVERLAY_FULL_HEIGHT
        if self.window_manager:
            try:
                monitor = self.window_manager.get_active_monitor()
                x = int(monitor["right"] - width - 12)
                y = int(monitor["bottom"] - height - 58)
                return x, y
            except Exception:
                pass
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            return sw - width - 12, sh - height - 58
        except Exception:
            return 20, 20

    def _conversation_visual_lock_active(self) -> bool:
        try:
            if self.voice_engine and self.voice_engine.conversation_mode:
                return True
        except Exception:
            pass
        return str(getattr(self, "interaction_mode", "") or "").lower() == "conversa"

    def _sync_conversation_overlay_lock(self, enabled=None):
        active = self._conversation_visual_lock_active() if enabled is None else bool(enabled)
        if not self.qt_voice_overlay:
            return active
        try:
            self.qt_voice_overlay.set_conversation_lock(active)
            if active:
                self._orb_context_compact = True
                self.qt_voice_overlay.set_compact(True)
                self.qt_voice_overlay.set_state("OUVINDO")
                self.qt_voice_overlay.set_opacity(0.78)
        except Exception:
            pass
        return active

    def _update_orb_context_mode(self, force_expand: bool = False):
        """Mantém a esfera mini em repouso e expande somente durante interação.

        REPOUSO/AGUARDANDO ficam sempre compactos, independentemente da janela
        em primeiro plano. Ao ouvir, entender, pensar, executar ou falar, a
        esfera expande; ao terminar, volta imediatamente ao tamanho mini.
        """
        if not self.qt_voice_overlay or not self.voice_visual_mode:
            return
        active_states = {
            "OUVINDO", "ESCUTANDO", "ESPERANDO_RESPOSTA", "ENTENDENDO",
            "PENSANDO", "PROCESSANDO", "EXECUTANDO", "FALANDO",
            "RECONECTANDO",
        }
        state = str(self._voice_visual_state or "REPOUSO").upper()
        conversation_lock = self._sync_conversation_overlay_lock()
        compact = True if conversation_lock else not (force_expand or state in active_states)
        try:
            changed = compact != self._orb_context_compact
            self._orb_context_compact = compact
            # Reenvia sempre. Isso impede o processo Qt de ficar grande por um
            # estado antigo mesmo quando o cache da GUI já dizia "compacto".
            self.qt_voice_overlay.set_compact(compact)
            if changed:
                self.qt_voice_overlay.set_opacity(0.70 if compact else self.VOICE_ORB_OPACITY)
            self._orb_context_title = ""
        except Exception:
            pass

    def _on_voice_engine_state(self, state, detail=""):
        self._voice_engine_state = str(
            state or ""
        ).upper()
        self._voice_engine_detail = str(
            detail or ""
        )

        self._post_ui_event(
            "voice_state",
            self._voice_engine_state,
            self._voice_engine_detail,
        )

    def _apply_voice_engine_state(self, state, detail):
        labels = {
            "PREPARANDO": "AGUARDANDO",
            "AGUARDANDO": "OCIOSO",
            "ACORDOU": "ACORDADO",
            "OUVINDO": "OUVINDO",
            "ESPERANDO_RESPOSTA": "ESPERANDO RESPOSTA",
            "ENTENDENDO": "ENTENDENDO",
            "PROCESSANDO": "PENSANDO",
            "PENSANDO": "PENSANDO",
            "RECONECTANDO": "RECONECTANDO",
            "EXECUTANDO": "EXECUTANDO",
            "FALANDO": "FALANDO",
            "SEM_MICROFONE": "SEM MICROFONE",
            "ERRO": "ERRO",
        }

        display = labels.get(state, state or "VOZ")

        # Estado único também para o botão/atalhos de captura manual. O
        # VoiceEngine é a fonte de verdade; a GUI não mantém mais um segundo
        # reconhecedor/stream legado em paralelo.
        if state in ("OUVINDO", "ESCUTANDO", "ESPERANDO_RESPOSTA", "ACORDOU"):
            self.is_listening = True
        elif state in ("AGUARDANDO", "PREPARANDO", "RECONECTANDO", "SEM_MICROFONE", "ERRO"):
            self.is_listening = False

        # PREPARANDO é apenas inicialização do motor. Visualmente nasce em
        # AGUARDANDO (mini); quando o engine sinaliza AGUARDANDO, entra em
        # REPOUSO/OCIOSO. PROCESSANDO/PENSANDO continuam reservados a trabalho
        # real solicitado pelo usuário.

        visual_map = {
            "PREPARANDO": "AGUARDANDO",
            "AGUARDANDO": "REPOUSO",
            "ACORDOU": "OUVINDO",
            "OUVINDO": "OUVINDO",
            "ESCUTANDO": "OUVINDO",
            "ESPERANDO_RESPOSTA": "OUVINDO",
            "ENTENDENDO": "ENTENDENDO",
            "PROCESSANDO": "PENSANDO",
            "PENSANDO": "PENSANDO",
            "RECONECTANDO": "RECONECTANDO",
            "EXECUTANDO": "EXECUTANDO",
            "FALANDO": "FALANDO",
            "SEM_MICROFONE": "ERRO",
            "ERRO": "ERRO",
        }

        self._voice_visual_state = visual_map.get(
            state,
            self._voice_visual_state
        )
        conversation_lock = self._conversation_visual_lock_active()
        if conversation_lock and state not in ("ERRO", "SEM_MICROFONE", "RECONECTANDO"):
            self._voice_visual_state = "OUVINDO"

        if self.qt_voice_overlay:
            try:
                self._sync_conversation_overlay_lock(conversation_lock)
                qt_state = (
                    "OUVINDO" if conversation_lock and state not in ("ERRO", "SEM_MICROFONE", "RECONECTANDO") else (
                        "ESPERANDO_RESPOSTA" if state == "ESPERANDO_RESPOSTA" else self._voice_visual_state
                    )
                )
                self.qt_voice_overlay.set_state(qt_state)
                if conversation_lock:
                    self._update_orb_context_mode(force_expand=False)
                elif qt_state in ("OUVINDO", "ENTENDENDO", "PENSANDO", "PROCESSANDO", "EXECUTANDO", "FALANDO", "RECONECTANDO", "ESPERANDO_RESPOSTA"):
                    self._update_orb_context_mode(force_expand=True)
                else:
                    self._update_orb_context_mode(force_expand=False)
                if state in (
                    "ACORDOU", "OUVINDO", "ENTENDENDO",
                    "PROCESSANDO", "EXECUTANDO", "AGUARDANDO", "PREPARANDO"
                ):
                    self.qt_voice_overlay.set_caption("")
            except Exception:
                pass

        if state in (
            "ERRO",
            "SEM_MICROFONE"
        ):
            self._schedule_auto_diagnostic(
                f"Voz: {state} - {detail}"
            )

        if state in ("OUVINDO", "ESCUTANDO", "ESPERANDO_RESPOSTA"):
            self._set_voice_overlay_speaking(True)
            self._set_voice_overlay_text("Estou ouvindo...")
        elif state == "ENTENDENDO":
            self._set_voice_overlay_speaking(True)
            self._set_voice_overlay_text("Entendendo...")
        elif state == "FALANDO":
            self._set_voice_overlay_speaking(True)
        elif state in ("AGUARDANDO", "ACORDOU", "PREPARANDO"):
            self._set_voice_overlay_speaking(False)

    def _on_voice_wake(self):
        self._post_ui_event(
            "voice_wake"
        )

    def _handle_voice_wake_ui(self):
        if not self.voice_visual_mode:
            self._open_voice_overlay()

        self._set_voice_overlay_text(
            "Sim?"
        )
        self._set_voice_overlay_speaking(
            True
        )

    def _on_voice_command(self, transcript):
        command = " ".join(
            str(transcript or "").split()
        ).strip()

        if not command:
            if self.voice_engine:
                self.voice_engine.set_assistant_busy(
                    False
                )
            return

        display_command = command
        try:
            literal = " ".join(str(getattr(self.voice_engine, "last_verbatim_transcript", "") or "").split()).strip()
            if literal:
                display_command = literal
        except Exception:
            pass

        self._post_ui_event(
            "voice_command",
            command,
            display_command
        )

    def _deliver_voice_command_ui(self, command, display_command=None):
        if self.is_processing:
            # Barge-in/preempção: uma fala nova vale mais que um turno remoto
            # antigo. Invalida chunks tardios e libera a UI imediatamente.
            self._invalidate_active_work()
            self.is_processing = False
            try:
                while True:
                    self._stream_chunk_queue.get_nowait()
            except queue.Empty:
                pass
            self._stream_flush_requested.clear()
            self.streaming_label = None
            self.streaming_buffer = ""
            if self._stream_render_job:
                try:
                    self.root.after_cancel(self._stream_render_job)
                except Exception:
                    pass
            self._stream_render_job = None
            self._stream_last_render_at = 0.0
            self._voice_stream_tts_buffer = ""
            self._voice_stream_tts_queued_count = 0
            try:
                if self.voice_engine:
                    self.voice_engine.stop_speaking(clear_queue=True)
                    self.voice_engine.set_assistant_busy(False)
            except Exception:
                pass
            self.logger.info("Novo comando de voz preemptou o processamento anterior.", "VOICE")

        self._voice_command_active = True
        self._set_voice_overlay_speaking(False)

        # Não mostre PENSANDO para comando local claro. A pessoa já deve ver
        # EXECUTANDO enquanto o roteador abre app, muda volume, move janela etc.
        if looks_like_local_intent(command):
            self._voice_visual_state = "EXECUTANDO"
            try:
                if self.qt_voice_overlay:
                    self.qt_voice_overlay.set_state("EXECUTANDO")
            except Exception:
                pass
        shown = " ".join(str(display_command or command or "").split()).strip() or command
        self._set_voice_overlay_text(f"Você: {shown}")

        self.add_message(
            "Você",
            shown,
            is_user=True
        )

        local_intent = looks_like_local_intent(command)
        if local_intent:
            self._update_status("EXECUTANDO", "#FF9D3D")
        else:
            self._update_status("PROCESSANDO", "#9B7BFF")

        self._process_message(command if local_intent else shown, source="voice")

    def _on_voice_rejected(self, reason):
        self._post_ui_event(
            "voice_rejected",
            str(reason or "Não entendi.")
        )

    def _on_voice_tts_start(self, text):
        self._post_ui_event(
            "tts_start",
            text
        )

    def _on_voice_tts_end(self):
        self._post_ui_event(
            "tts_end"
        )

    def _voice_response_needs_followup(self, text: str) -> bool:
        """Detecta se a resposta termina pedindo uma resposta do usuário."""
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return False

        # A última sentença é o que importa: evita perguntas retóricas no meio
        # de explicações longas.
        tail = clean[-320:].strip()
        if re.search(r"\?\s*$", tail):
            return True

        normalized = self._local_strip_accents(tail).lower()
        last_sentence = re.split(r"[.!]\s+", normalized)[-1].strip()

        prompts = (
            "quer que eu ",
            "voce quer ",
            "deseja que eu ",
            "prefere ",
            "posso ",
            "devo ",
            "qual ",
            "quais ",
            "como ",
            "onde ",
            "quando ",
            "por que ",
            "quer continuar",
            "quer que continue",
            "pode confirmar",
            "responda sim ou nao",
            "diga o que",
            "o que voce quer",
            "para qual monitor",
            "qual monitor",
            "qual aplicativo",
        )
        return any(last_sentence.startswith(item) for item in prompts)

    def _arm_voice_followup_if_question(self, text: str):
        # Build 10: modo conversa contínua já reabre o microfone após TODA
        # resposta; armar follow-up por pergunta criaria duas capturas concorrentes.
        try:
            if self.voice_engine and self.voice_engine.conversation_mode:
                self._voice_followup_after_tts = False
                self._voice_followup_question_text = ""
                return
        except Exception:
            pass
        if not self._voice_response_needs_followup(text):
            self._voice_followup_after_tts = False
            self._voice_followup_question_text = ""
            return

        self._voice_followup_after_tts = True
        self._voice_followup_question_text = str(text or "").strip()

    def _start_voice_followup_listen(self, attempt: int = 0):
        """Após uma pergunta do JARVIS, volta a escutar sem novo wake word."""
        self._voice_followup_job = None

        if not self._voice_followup_after_tts:
            return

        if self._pending_confirmation:
            return

        if not self.voice_engine:
            self._voice_followup_after_tts = False
            return

        try:
            status = self.voice_engine.status()
            busy = bool(status.get("assistant_busy"))
            speaking = bool(status.get("speaking"))
        except Exception:
            busy = bool(self.is_processing)
            speaking = False

        if busy or speaking or self.is_processing:
            if attempt < 30 and self.root:
                self._voice_followup_job = self.root.after(
                    80,
                    lambda: self._start_voice_followup_listen(attempt + 1)
                )
            return

        self._voice_followup_after_tts = False
        self._voice_followup_question_text = ""

        try:
            if not self.voice_visual_mode:
                self._open_voice_overlay()
        except Exception:
            pass

        try:
            if self.qt_voice_overlay:
                self.qt_voice_overlay.set_caption("")
                self.qt_voice_overlay.set_state("OUVINDO")
        except Exception:
            pass

        self._voice_visual_state = "OUVINDO"
        self._set_voice_overlay_speaking(True)
        self._set_voice_overlay_text("Estou ouvindo...")

        try:
            self.voice_engine.trigger_followup("followup")
        except Exception as e:
            self.logger.warning(
                f"Falha ao iniciar follow-up de voz: {e}",
                "VOICE"
            )

    def _voice_spoken_summary_base(self, text: str) -> str:
        """Respostas locais faladas curtas; o chat continua mostrando detalhes."""
        clean = " ".join(str(text or "").split()).strip()
        key = self._local_strip_accents(clean).lower()

        if re.search(
            r"\babrindo\b|\baberto\b|\bacessado\b|"
            r"\bsolicitei a abertura\b|\bsolicitei abrir\b",
            key,
        ):
            return "Abrindo."

        if any(token in key for token in (
            "pesquisa aberta", "pesquisa iniciada", "pesquisando por",
            "busca aberta", "busca iniciada",
        )):
            return "Pesquisando."

        vol = re.search(r"volume(?: do windows)?(?: ajustado)?(?: para| em)?\s+(\d{1,3})%", key)
        if vol:
            return f"Volume em {vol.group(1)} por cento."

        if key.startswith("para qual monitor"):
            return "Para qual monitor?"
        if key.startswith("qual aplicativo") or key.startswith("qual app"):
            return "Qual aplicativo?"
        if key.startswith("nao encontrei o aplicativo") or key.startswith("nao encontrei uma correspondencia segura"):
            return "Não encontrei esse aplicativo."

        if key.startswith("comandos locais do jarvis") or key.startswith("comandos locais do zero") or "consigo controlar aplicativos" in key:
            return "Consigo controlar aplicativos, janelas, mídia, navegador, arquivos e a tela. Os detalhes estão no chat."

        if "modo automatico ativado" in key:
            return "Modo automático."
        if "modo conversa ativado" in key:
            return "Modo conversa."
        if "modo comando ativado" in key:
            return "Modo comando."
        if "modo gamer ativado" in key:
            return "Modo gamer ativado."
        if "tela cheia" in key and any(token in key for token in ("alternei", "cliquei", "fullscreen")):
            return "Tela cheia."

        if "minimizado" in key:
            return "Minimizei."
        if "maximizado" in key:
            return "Maximizei."
        if "restaurado" in key:
            return "Voltei."
        if "reproduzindo" in key:
            return "Continuando."
        if any(token in key for token in ("pausado", "play/pause", "play pause")):
            return "Pausei."
        if any(token in key for token in ("pulei a abertura", "abertura pulada", "intro pulada")):
            return "Pronto."
        if "proximo episodio" in key and any(token in key for token in ("abri", "avancei", "seguindo", "proximo")):
            return "Próximo episódio."
        if "monitor" in key and (" no monitor " in key or " para o monitor " in key):
            return "Feito."
        if key.startswith("saida de audio") or key.startswith("microfone"):
            return "Feito."
        if clean.startswith("✓") and len(clean) > 85:
            return "Feito."

        return clean

    @staticmethod
    def _normalize_session_user_name(value: str) -> str:
        """Normaliza um nome declarado explicitamente, sem tentar reconhecer voz."""
        clean = re.sub(r"\s+", " ", str(value or "")).strip(" .,!?:;\t\r\n")
        clean = re.sub(r"^(?:o|a)\s+", "", clean, flags=re.I)
        if not clean or len(clean) > 48:
            return ""
        parts = clean.split()
        if not 1 <= len(parts) <= 4:
            return ""
        if not all(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", part) for part in parts):
            return ""
        # Evita interpretar estados/frases comuns como identidade em "eu sou X".
        blocked = {
            "bem", "mal", "feliz", "triste", "cansado", "cansada", "brasileiro",
            "brasileira", "homem", "mulher", "usuario", "usuário", "programador",
            "programadora", "estudante", "novo", "nova", "aqui", "eu",
        }
        if len(parts) == 1 and parts[0].lower() in blocked:
            return ""
        # STT geralmente entrega nomes em minúsculas; Title mantém a apresentação elegante.
        if clean.islower() or clean.isupper():
            clean = " ".join(part.capitalize() for part in parts)
        return clean

    def _user_profile_path(self) -> Path:
        return Path(self.project_dir) / "data" / "user_profile.json"

    def _load_persistent_user_name(self) -> str:
        """Carrega somente o nome preferido; independe da conversa/chat ativo."""
        try:
            path = self._user_profile_path()
            if not path.exists():
                return ""
            payload = json.loads(path.read_text(encoding="utf-8"))
            return self._normalize_session_user_name(str(payload.get("preferred_name") or ""))
        except Exception:
            return ""

    def _save_persistent_user_name(self, name: str) -> None:
        try:
            path = self._user_profile_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"preferred_name": str(name or "").strip()}
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            try:
                self.logger.warning(f"Nao consegui persistir nome do usuario: {exc}", "IDENTITY")
            except Exception:
                pass

    def _set_session_user_name(self, value: str) -> str:
        name = self._normalize_session_user_name(value)
        if name:
            self._session_user_name = name
            saver = getattr(self, "_save_persistent_user_name", None)
            if callable(saver):
                saver(name)
        return name

    def _clear_session_user_name(self) -> None:
        self._session_user_name = ""
        saver = getattr(self, "_save_persistent_user_name", None)
        if callable(saver):
            saver("")

    def _current_speaker_name(self, wait_ms: int = 0) -> str:
        """Nome de tratamento da sessão; deliberadamente sem biometria de voz."""
        return str(getattr(self, "_session_user_name", "") or "").strip()

    def _butler_vocative(self, wait_ms: int = 0) -> str:
        if str(jarvis_env("BUTLER_MODE", "1") or "1").strip().lower() in {"0", "false", "off", "nao", "não"}:
            return ""
        name = self._current_speaker_name(wait_ms=wait_ms)
        return f"senhor {name}" if name else "senhor"

    def _apply_butler_address(self, text: str, wait_ms: int = 0) -> str:
        clean = " ".join(str(text or "").split()).strip()
        if not clean:
            return clean
        vocative = self._butler_vocative(wait_ms=wait_ms)
        if not vocative or re.search(r"\bsenhor(?:a)?\b", clean, flags=re.I):
            return clean
        # Confirmações locais curtas soam naturais com um único vocativo no final.
        if clean.endswith("?"):
            return clean[:-1].rstrip() + f", {vocative}?"
        punctuation = "!" if clean.endswith("!") else "."
        clean = clean.rstrip(".!? ")
        return f"{clean}, {vocative}{punctuation}"

    def _voice_spoken_summary(self, text: str) -> str:
        """Resumo local + tratamento de mordomo, sem afetar o texto detalhado no chat."""
        base = self._voice_spoken_summary_base(text)
        return self._apply_butler_address(base, wait_ms=80)

    def _speak_voice_response_if_needed(self, text):
        if not self._voice_command_active:
            return

        clean = str(text or "").strip()
        if not clean:
            return

        self._voice_command_active = False
        self._arm_voice_followup_if_question(clean)

        if self.voice_engine:
            try:
                spoken = self._voice_spoken_summary(clean)
                self.voice_engine.speak(spoken, wait=False, fast=True)
            except Exception as e:
                self.logger.warning(
                    f"Não foi possível falar resposta: {e}",
                    "VOICE"
                )


    def _voice_processing_complete(self, attempt: int = 0):
        """Libera THINKING/EXECUTING só depois que a resposta entrou na fila de TTS."""
        if not self.voice_engine:
            return
        try:
            pending = bool(self.voice_engine.has_pending_speech)
        except Exception:
            pending = False

        # Em comandos de voz, add_message/stream_finish podem estar aguardando a
        # thread Tk. Não abra uma janela de autoescuta entre resposta e TTS.
        if self._voice_command_active and not pending and attempt < 60:
            try:
                self.root.after(25, lambda: self._voice_processing_complete(attempt + 1))
                return
            except Exception:
                pass
        try:
            self.voice_engine.set_assistant_busy(False)
        except Exception:
            pass

    def _post_ui_event(self, event_name, *args):
        """Pode ser chamado com segurança por qualquer thread."""
        try:
            self._ui_event_queue.put_nowait(
                (event_name, args)
            )
        except Exception:
            pass

    def _post_ui_call(self, callback, *args):
        """Agenda uma chamada Tk sem invocar métodos do Tcl a partir de worker threads."""
        if callable(callback):
            self._post_ui_event("ui_call", callback, *args)

    def _post_work_ui_call(self, token: int, callback, *args):
        """Agenda UI pertencente a um turno; turnos obsoletos são descartados."""
        if callable(callback):
            self._post_ui_event("work_ui_call", int(token), callback, *args)

    def _post_context_ui_call(self, callback, *args):
        """Usa automaticamente o token do worker atual quando existir."""
        token = int(getattr(self._work_thread_context, "token", 0) or 0)
        if token:
            self._post_work_ui_call(token, callback, *args)
        else:
            self._post_ui_call(callback, *args)

    def _start_ui_event_pump(self):
        if not self.root:
            return

        if self._ui_event_job:
            return

        self._ui_event_job = self.root.after(
            10,
            self._drain_ui_events
        )

    def _drain_ui_events(self):
        """Executa callbacks de áudio/tray/hotkey somente na thread Tk."""
        self._ui_event_job = None

        try:
            processed = 0

            while processed < 80:
                try:
                    event_name, args = (
                        self._ui_event_queue.get_nowait()
                    )
                except queue.Empty:
                    break

                processed += 1

                try:
                    if event_name == "ui_call":
                        callback = args[0] if args else None
                        if callable(callback):
                            callback(*args[1:])

                    elif event_name == "work_ui_call":
                        token = int(args[0]) if args else 0
                        callback = args[1] if len(args) > 1 else None
                        if self._work_is_current(token) and callable(callback):
                            callback(*args[2:])

                    elif event_name == "voice_state":
                        self._apply_voice_engine_state(
                            *args
                        )

                    elif event_name == "voice_wake":
                        self._handle_voice_wake_ui()

                    elif event_name == "voice_command":
                        self._deliver_voice_command_ui(
                            *args
                        )

                    elif event_name == "voice_rejected":
                        self._set_voice_overlay_text(
                            str(
                                args[0]
                                if args
                                else "Não entendi."
                            )
                        )

                    elif event_name == "voice_user_caption":
                        text = sanitize_text(args[0] if args else "", limit=220)
                        if self.qt_voice_overlay:
                            self.qt_voice_overlay.set_user_caption(text)
                        else:
                            self._set_voice_overlay_text(f"Você: {text}" if text else "Estou ouvindo...")

                    elif event_name == "voice_caption":
                        text = sanitize_text(args[0] if args else "", limit=240)
                        if self.qt_voice_overlay:
                            self.qt_voice_overlay.set_caption(text, speaker="assistant")
                        else:
                            self._set_voice_overlay_text(text)

                    elif event_name == "tts_start":
                        text = (
                            args[0]
                            if args
                            else ""
                        )
                        text = sanitize_text(text, limit=240)
                        self._set_voice_overlay_text(text)
                        if self.qt_voice_overlay:
                            try:
                                self.qt_voice_overlay.set_caption(text, speaker="assistant")
                            except Exception:
                                pass
                        self._set_voice_overlay_speaking(True)

                    elif event_name == "tts_end":
                        # V6: nunca entra em OUVINDO no meio de uma resposta longa.
                        # O streaming pode já ter terminado enquanto ainda há áudio
                        # pré-sintetizado na fila; nesse caso FALANDO continua vencendo.
                        if self.is_processing or self.streaming_label is not None:
                            continue
                        try:
                            if self.voice_engine and self.voice_engine.has_pending_speech:
                                continue
                        except Exception:
                            pass
                        self._set_voice_overlay_speaking(False)
                        try:
                            self.root.after(700, self._clear_qt_caption_if_idle)
                        except Exception:
                            pass

                        if (
                            self._confirmation_voice_followup
                            and self._pending_confirmation
                            and self.voice_engine
                        ):
                            self._confirmation_voice_followup = False
                            self._voice_followup_after_tts = False
                            self._voice_followup_question_text = ""

                            self._voice_visual_state = "OUVINDO"
                            try:
                                if self.qt_voice_overlay:
                                    self.qt_voice_overlay.set_state("OUVINDO")
                                    self.qt_voice_overlay.set_caption("")
                            except Exception:
                                pass
                            self.root.after(
                                10,
                                lambda: self.voice_engine.trigger_followup("confirmation")
                            )
                        elif (
                            self._voice_followup_after_tts
                            and self.voice_engine
                        ):
                            if self._voice_followup_job:
                                try:
                                    self.root.after_cancel(self._voice_followup_job)
                                except Exception:
                                    pass
                            self._voice_followup_job = self.root.after(
                                30,
                                self._start_voice_followup_listen
                            )
                        else:
                            self.root.after(180, self._settle_voice_idle)

                    elif event_name == "voice_interrupt":
                        self._pending_confirmation = None
                        self._confirmation_voice_followup = False
                        self._voice_followup_after_tts = False
                        self._voice_followup_question_text = ""
                        self._voice_command_active = False
                        self.is_processing = False
                        # Descarta chunks já enfileirados da resposta cancelada e
                        # libera o slot visual para uma nova interação.
                        self._clear_stream_chunk_queue()
                        self._discard_streaming_visual()
                        try:
                            cancel = getattr(self.core, "cancel_active_response", None)
                            if callable(cancel):
                                cancel("interrupção por voz")
                        except Exception:
                            pass
                        try:
                            if self.voice_engine:
                                self.voice_engine.stop_speaking(clear_queue=True)
                                self.voice_engine.set_assistant_busy(False)
                        except Exception:
                            pass
                        self._voice_visual_state = "REPOUSO"
                        self._set_voice_overlay_text("Interrompido.")
                        self._set_voice_overlay_speaking(False)
                        try:
                            if self.qt_voice_overlay:
                                self.qt_voice_overlay.set_caption("")
                                self.qt_voice_overlay.set_state("AGUARDANDO")
                        except Exception:
                            pass

                    elif event_name == "runtime_ready":
                        # Convergencia visual dos subsistemas carregados em background.
                        try:
                            self._refresh_operational_ui()
                        except Exception:
                            pass
                        try:
                            self._refresh_quick_panel_values()
                        except Exception:
                            pass

                    elif event_name == "desktop_toggle":
                        self._toggle_voice_visual_mode()

                    elif event_name == "desktop_show":
                        self._show_main_window()

                    elif event_name == "desktop_listen":
                        if not self.voice_visual_mode:
                            self._open_voice_overlay()

                        self.root.after(
                            180,
                            self._voice_visual_click
                        )

                    elif event_name == "desktop_move_orb":
                        self._enable_overlay_move_mode()

                    elif event_name == "stream_start":
                        token = int(args[0]) if args else 0
                        sender = args[1] if len(args) > 1 else PUBLIC_NAME
                        if self._work_is_current(token):
                            self._start_streaming_response(sender, token=token)

                    elif event_name == "stream_flush":
                        token = int(args[0]) if args else 0
                        self._flush_stream_chunks_ui(token=token)

                    elif event_name == "stream_finish":
                        token = int(args[0]) if args else 0
                        if self._work_is_current(token) and token == self._active_stream_token:
                            self._flush_stream_chunks_ui(token=token)
                            self._finish_streaming_response(args[1] if len(args) > 1 else "", token=token)

                    elif event_name == "desktop_exit":
                        self._exit_application()

                except Exception as e:
                    self.logger.warning(
                        f"Evento UI '{event_name}' falhou: {e}",
                        "GUI"
                    )

        finally:
            if self.root:
                try:
                    self._ui_event_job = (
                        self.root.after(
                            10,
                            self._drain_ui_events
                        )
                    )
                except Exception:
                    self._ui_event_job = None

    def _settle_voice_idle(self):
        """Volta a AGUARDANDO só quando realmente não há escuta/follow-up em andamento."""
        if self._pending_confirmation or self._voice_followup_after_tts:
            return
        try:
            if self.voice_engine:
                status = self.voice_engine.status()
                if status.get("speaking") or status.get("assistant_busy"):
                    return
                if status.get("conversation_mode"):
                    self._voice_visual_state = "OUVINDO"
                    self._voice_engine_state = "OUVINDO"
                    self._sync_conversation_overlay_lock(True)
                    if self.qt_voice_overlay:
                        self.qt_voice_overlay.set_state("OUVINDO")
                        self.qt_voice_overlay.set_compact(True)
                    return
        except Exception:
            pass
        if str(self._voice_engine_state).upper() in ("OUVINDO", "ESPERANDO_RESPOSTA", "ENTENDENDO", "PROCESSANDO"):
            return
        self._voice_visual_state = "REPOUSO"
        self._voice_engine_state = "AGUARDANDO"
        try:
            if self.qt_voice_overlay:
                self.qt_voice_overlay.set_state("REPOUSO")
        except Exception:
            pass

    def _on_voice_level(self, level):
        """Nível real do microfone; enviado ao overlay a ~20 FPS."""
        try:
            self.voice_mic_level = max(0.0, min(float(level), 1.0))
        except Exception:
            self.voice_mic_level = 0.0
        if self.qt_voice_overlay:
            try:
                self.qt_voice_overlay.set_level(self.voice_mic_level)
            except Exception:
                pass

    def _on_voice_audio_metrics(self, metrics):
        """Telemetria do mic vai direto ao processo Qt; não toca em widgets Tk."""
        try:
            if self.qt_voice_overlay:
                self.qt_voice_overlay.set_audio_metrics(dict(metrics or {}))
        except Exception:
            pass

    def _begin_work_generation(self) -> int:
        with self._work_generation_lock:
            self._work_generation += 1
            return self._work_generation

    def _invalidate_active_work(self) -> int:
        with self._work_generation_lock:
            self._work_generation += 1
            return self._work_generation

    def _work_is_current(self, token: int) -> bool:
        with self._work_generation_lock:
            return int(token) == self._work_generation

    def _processing_watchdog(self, token: int):
        """Fail-open visual: nunca deixa a interface presa em PENSANDO.

        Não mata threads do sistema; apenas invalida uma geração antiga e
        devolve o controle ao usuário. Comandos novos podem ser enviados logo
        em seguida.
        """
        try:
            if not self._work_is_current(token) or not self.is_processing:
                return
            self._invalidate_active_work()
            self.is_processing = False
            self._voice_command_active = False
            try:
                cancel = getattr(self.core, "cancel_active_response", None)
                if callable(cancel):
                    cancel("watchdog da interface")
            except Exception:
                pass
            self._clear_stream_chunk_queue()
            self._discard_streaming_visual()
            if self.voice_engine:
                self.voice_engine.stop_speaking(clear_queue=True)
                self.voice_engine.set_assistant_busy(False)
            self._update_status("ONLINE", Config.get_color("success"))
            self._set_voice_overlay_speaking(False)
            self._set_voice_overlay_text("Pronto.")
            try:
                if self.qt_voice_overlay:
                    self.qt_voice_overlay.set_caption("")
                    self.qt_voice_overlay.set_state("AGUARDANDO")
            except Exception:
                pass
            self.logger.warning("Watchdog liberou a interface após processamento prolongado.", "GUI")
            self.add_message(
                PUBLIC_NAME,
                "A resposta demorou mais que o esperado e foi interrompida. Você pode enviar a mensagem novamente.",
                is_jarvis=True,
            )
        except Exception:
            pass

    def _on_voice_interrupt(self):
        # Invalida o trabalho imediatamente na thread de voz. O evento de UI
        # apenas atualiza widgets/flags depois; chunks tardios serão ignorados.
        self._invalidate_active_work()
        self._post_ui_event(
            "voice_interrupt"
        )

    def _setup_advanced_modules(self):
        """Inicializa recursos avancados em background, fail-open."""
        global AdvancedWindows, SafetyManager, AudioDeviceManager, VisionSystem, DiagnosticsManager
        global OperationalContext, WorkflowEngine, ConditionalRuleEngine, BrowserAutonomyEngine
        global MediaContextEngine, GoalExecutor, ObserverEngine
        imports = (
            ("advanced_windows", "AdvancedWindows"),
            ("safety_manager", "SafetyManager"),
            ("audio_device_manager", "AudioDeviceManager"),
            ("vision_system", "VisionSystem"),
            ("diagnostics_manager", "DiagnosticsManager"),
            ("operational_context", "OperationalContext"),
            ("workflow_engine", "WorkflowEngine"),
            ("conditional_rules", "ConditionalRuleEngine"),
            ("browser_autonomy", "BrowserAutonomyEngine"),
            ("media_context", "MediaContextEngine"),
            ("goal_executor", "GoalExecutor"),
            ("observer_engine", "ObserverEngine"),
        )
        scope = globals()
        for module_name, symbol in imports:
            if scope.get(symbol) is not None:
                continue
            try:
                module = __import__(module_name, fromlist=[symbol])
                scope[symbol] = getattr(module, symbol)
            except Exception:
                scope[symbol] = None

        try:
            if AdvancedWindows:
                self.window_manager = AdvancedWindows(
                    logger=self.logger
                )
        except Exception as e:
            self.logger.warning(
                f"AdvancedWindows indisponível: {e}",
                "ADVANCED"
            )

        try:
            if SafetyManager:
                self.safety_manager = SafetyManager(
                    project_dir=self.project_dir,
                    logger=self.logger
                )
        except Exception as e:
            self.logger.warning(
                f"Controle local de impacto indisponível: {e}",
                "ADVANCED"
            )

        try:
            if AudioDeviceManager:
                self.audio_device_manager = AudioDeviceManager(
                    logger=self.logger
                )
        except Exception as e:
            self.logger.warning(
                f"AudioDeviceManager indisponível: {e}",
                "ADVANCED"
            )

        try:
            if VisionSystem:
                self.vision_system = VisionSystem(
                    project_dir=self.project_dir,
                    core=self.core,
                    window_manager=self.window_manager,
                    logger=self.logger,
                )
        except Exception as e:
            self.logger.warning(
                f"VisionSystem indisponível: {e}",
                "ADVANCED"
            )

        try:
            if DiagnosticsManager:
                self.diagnostics_manager = DiagnosticsManager(
                    project_dir=self.project_dir,
                    logger=self.logger
                )
        except Exception as e:
            self.logger.warning(
                f"DiagnosticsManager indisponível: {e}",
                "ADVANCED"
            )

        # Build 11: contexto operacional e agente autônomo são fail-open.
        try:
            if OperationalContext:
                self.operational_context = OperationalContext(self.project_dir, logger=self.logger)
                self.operational_context.set_mode(self.interaction_mode)
                self._apply_behavior_levels_from_percent(silent=True)
        except Exception as e:
            self.logger.warning(f"OperationalContext indisponível: {e}", "AGENT")

        try:
            if WorkflowEngine:
                self.workflow_engine = WorkflowEngine(self.project_dir, logger=self.logger)
        except Exception as e:
            self.logger.warning(f"WorkflowEngine indisponível: {e}", "AGENT")

        try:
            if ConditionalRuleEngine:
                self.conditional_rules = ConditionalRuleEngine(self.project_dir, logger=self.logger)
        except Exception as e:
            self.logger.warning(f"ConditionalRuleEngine indisponível: {e}", "AGENT")

        try:
            if BrowserAutonomyEngine:
                self.browser_autonomy = BrowserAutonomyEngine(
                    actions=self.actions, vision=self.vision_system, window_manager=self.window_manager,
                    logger=self.logger, operational_context=self.operational_context,
                )
        except Exception as e:
            self.logger.warning(f"BrowserAutonomy indisponível: {e}", "AGENT")

        try:
            if MediaContextEngine:
                self.media_context = MediaContextEngine(
                    actions=self.actions, window_manager=self.window_manager, browser_autonomy=self.browser_autonomy,
                    operational_context=self.operational_context, logger=self.logger,
                )
        except Exception as e:
            self.logger.warning(f"MediaContext indisponível: {e}", "AGENT")

        try:
            if GoalExecutor and self.browser_autonomy:
                self.goal_executor = GoalExecutor(
                    self.browser_autonomy, self._execute_v8_command_result,
                    context=self.operational_context, logger=self.logger,
                    window_manager=self.window_manager, media_context=self.media_context,
                )
        except Exception as e:
            self.logger.warning(f"GoalExecutor indisponível: {e}", "AGENT")

        try:
            if ObserverEngine and self.operational_context:
                self.observer_engine = ObserverEngine(
                    self.operational_context, windows=self.window_manager, logger=self.logger,
                    on_event=self._on_observer_event, interval=1.0,
                )
                self.observer_engine.start()
        except Exception as e:
            self.logger.warning(f"ObserverEngine indisponível: {e}", "AGENT")

        self._post_ui_event("runtime_ready", "advanced")
        self.logger.info(
            "Módulos do modo avançado + Agent Runtime inicializados.",
            "ADVANCED"
        )

    def _set_source_badge(self, source: str):
        if self.root and threading.get_ident() != self._main_thread_id:
            self._post_context_ui_call(self._set_source_badge, source)
            return
        label = str(source or "LOCAL").upper()[:12]
        palette = {
            "LOCAL": ("#1F3B2D", "#71E6A4"),
            "IA": ("#342B4F", "#B9A0FF"),
            "WEB": ("#243A52", "#7EC2FF"),
            "VISÃO": ("#4B3520", "#F8C879"),
            "VISAO": ("#4B3520", "#F8C879"),
            "AGENTE": ("#3C2F4F", "#D0A8FF"),
            "SISTEMA": ("#303030", "#BDBDBD"),
        }
        bg, fg = palette.get(label, ("#303030", "#D0D0D0"))
        try:
            if self.source_badge:
                self.source_badge.configure(text=label, fg_color=bg, text_color=fg)
        except Exception:
            pass

    def _execute_conditional_rule(self, rule, event=None):
        """Executa somente regras previamente validadas pelo ConditionalRuleEngine."""
        rid = int((rule or {}).get("id", 0) or 0)
        try:
            action = str((rule or {}).get("action") or "").strip()
            if action == "notify":
                event = dict(event or {})
                if event.get("kind") == "system_metric":
                    metric = str(event.get("metric") or (rule or {}).get("match") or "sistema")
                    value = event.get(metric)
                    name = f"{metric}: {float(value):.0f}%" if value is not None else metric
                else:
                    name = str(event.get("name") or event.get("app") or event.get("message") or "evento")
                self._show_agent_notice(f"Regra #{rid}: {name}.")
                if self.conditional_rules:
                    self.conditional_rules.mark_result(rid, True, name)
                return
            routed = route_v8(action) if route_v8 else None
            if not routed or getattr(routed, "kind", "") != "local" or not getattr(routed, "commands", None):
                msg = "ação deixou de ser segura/reconhecida"
                self._show_agent_notice(f"Regra #{rid} não foi executada: {msg}.")
                if self.conditional_rules:
                    self.conditional_rules.mark_result(rid, False, msg)
                return
            if len(routed.commands) > 4:
                msg = "sequência longa demais"
                self._show_agent_notice(f"Regra #{rid} ignorada: {msg}.")
                if self.conditional_rules:
                    self.conditional_rules.mark_result(rid, False, msg)
                return
            outcomes = [self._execute_v8_command_result(command) for command in routed.commands]
            ok = bool(outcomes) and all(bool(x.get("success")) for x in outcomes)
            verified = bool(outcomes) and all(bool(x.get("verified")) for x in outcomes)
            if ok:
                tail = "confirmada" if verified else "executada; efeito não totalmente observável"
                self._show_agent_notice(f"Regra #{rid} {tail}: {rule.get('label') or action}.")
            else:
                self._show_agent_notice(f"Regra #{rid} tentou agir, mas não conseguiu confirmar o resultado.")
            if self.conditional_rules:
                self.conditional_rules.mark_result(rid, ok, "" if ok else "ação falhou ou não pôde ser confirmada")
        except Exception as exc:
            try:
                if self.conditional_rules:
                    self.conditional_rules.mark_result(rid, False, str(exc))
                self.logger.warning(f"Regra condicional falhou: {exc}", "RULES")
            except Exception:
                pass

    def _evaluate_conditional_rules(self, event):
        if self.conditional_rules is None:
            return
        try:
            fired = self.conditional_rules.evaluate(dict(event or {}))
        except Exception as exc:
            try: self.logger.warning(f"Avaliação de regras falhou: {exc}", "RULES")
            except Exception: pass
            return
        for rule in fired[:5]:
            try:
                self._post_ui_call(self._execute_conditional_rule, rule, dict(event or {}))
            except Exception:
                pass

    def _on_observer_event(self, event):
        """Recebe somente metadados; nunca frames/audio/teclas."""
        try:
            event = dict(event or {})
            kind = str(event.get("kind") or "")

            if kind == "window_changed":
                current_app = str(event.get("app") or "")
                previous_app = str(event.get("previous_app") or "")
                site = str(event.get("site") or "")
                monitor = event.get("monitor")
                title = str(event.get("title") or "")
                try:
                    v8_observe_context(app=current_app, monitor=monitor, site=site, title=title)
                except Exception:
                    pass
                try:
                    if self.media_context is not None:
                        media = self.media_context.refresh(force=True).to_dict()
                        v8_remember_media(media)
                except Exception:
                    pass

                if self.behavior_memory is not None:
                    try:
                        learned = self.behavior_memory.observe_transition(previous_app, current_app)
                    except Exception:
                        learned = None
                    if learned:
                        allow_suggestion = True
                        try:
                            policy = self.operational_context.behavior_policy() if self.operational_context else None
                            if policy is not None:
                                allow_suggestion = bool(policy.allow_behavior_suggestions)
                        except Exception:
                            pass
                        if allow_suggestion:
                            if learned.get("kind") == "sequence":
                                apps = learned.get("apps") or []
                                text = f"Padrão aprendido: você costuma seguir {' → '.join(apps)} ({learned['count']} vezes). Posso transformar isso em rotina."
                            else:
                                text = (
                                    f"Padrão aprendido: depois de {learned['from_app']} você costuma abrir "
                                    f"{learned['to_app']} ({learned['count']} vezes). Posso transformar isso em rotina."
                                )
                            self._post_ui_call(self._show_agent_notice, text)

            if kind == "download_complete":
                name = str(event.get("name") or "arquivo")
                allow_notice = True
                try:
                    policy = self.operational_context.behavior_policy() if self.operational_context else None
                    if policy is not None:
                        allow_notice = bool(policy.allow_proactive_notices)
                except Exception:
                    pass
                if allow_notice:
                    self._post_ui_call(self._show_agent_notice, f"Download concluído: {name}")

            elif kind == "system_health":
                message = str(event.get("message") or "")
                severity = str(event.get("severity") or "warning")
                if message:
                    self._post_ui_call(self._handle_proactive_health_notice, message, severity)

            self._evaluate_conditional_rules(event)
            self._post_ui_call(self._refresh_operational_ui)
        except Exception:
            pass

    def _handle_proactive_health_notice(self, message: str, severity: str = "warning"):
        message = sanitize_text(message, limit=220)
        if not message:
            return
        allow_notice = True
        allow_speech = False
        min_severity = "warning"
        try:
            policy = self.operational_context.behavior_policy() if self.operational_context else None
            if policy is not None:
                allow_notice = bool(policy.allow_proactive_notices)
                allow_speech = bool(policy.allow_spoken_proactive)
                min_severity = str(policy.min_proactive_severity or "warning")
        except Exception:
            pass
        severity = str(severity or "warning").lower()
        rank = {"info": 0, "warning": 1, "critical": 2}
        if not allow_notice or rank.get(severity, 1) < rank.get(min_severity, 1):
            return
        self._show_agent_notice(message)
        if allow_speech and (severity == "critical" or min_severity == "warning"):
            try:
                self._show_jarvis_response(message, speak=True)
            except Exception:
                pass

    def _show_agent_notice(self, text: str):
        text = sanitize_text(text, limit=180)
        if not text:
            return
        try:
            if self.agent_hud:
                self.agent_hud.pack(fill="x", padx=14, pady=(0, 7))
                self.agent_hud_title.configure(text=f"{PUBLIC_NAME} • CONTEXTO")
                self.agent_hud_step.configure(text=text)
                self.agent_hud_progress.set(1.0)
                self.root.after(4500, self._hide_agent_hud_if_idle)
        except Exception:
            pass

    def _hide_agent_hud_if_idle(self):
        try:
            if self._agent_last_status in {"idle", "done", "notice"} and self.agent_hud:
                self.agent_hud.pack_forget()
        except Exception:
            pass

    def _update_agent_hud(self, update: dict):
        update = dict(update or {})
        status = str(update.get("status") or "running")
        self._agent_last_status = status
        label = sanitize_text(update.get("label") or update.get("message") or "Executando objetivo", limit=220)
        index = int(update.get("index") or 0)
        total = int(update.get("total") or 0)
        progress = float(update.get("progress") or (index / total if total else 0.0))
        try:
            if self.agent_hud:
                self.agent_hud.pack(fill="x", padx=14, pady=(0, 7))
                title = f"{PUBLIC_NAME} AGENT"
                if total:
                    title += f"  •  {index}/{total}"
                self.agent_hud_title.configure(text=title)
                self.agent_hud_step.configure(text=label or status.upper())
                self.agent_hud_progress.set(max(0.0, min(progress, 1.0)))
                if self.agent_stop_button:
                    self.agent_stop_button.configure(state="normal" if status in {"running", "retrying", "unverified_continue"} else "disabled")
        except Exception:
            pass
        self._set_source_badge("AGENTE")
        self._refresh_operational_ui()

    def _finish_agent_hud(self, success: bool, message: str):
        self._agent_last_status = "done" if success else "failed"
        try:
            if self.agent_hud:
                self.agent_hud.pack(fill="x", padx=14, pady=(0, 7))
                self.agent_hud_title.configure(text=f"{PUBLIC_NAME} AGENT • CONCLUÍDO" if success else f"{PUBLIC_NAME} AGENT • INTERROMPIDO")
                self.agent_hud_step.configure(text=sanitize_text(message, limit=220))
                self.agent_hud_progress.set(1.0 if success else 0.0)
                if self.agent_stop_button:
                    self.agent_stop_button.configure(state="disabled")
                self.root.after(5500, self._hide_agent_hud_if_idle)
        except Exception:
            pass
        self._refresh_operational_ui()

    def _stop_agent_goal(self):
        # Evita a mensagem fantasma "Objetivo interrompido" quando o botao/
        # comando de parada chega sem nenhum objetivo realmente em execucao.
        was_running = False
        try:
            was_running = bool(self.goal_executor and self.goal_executor.is_running())
            if self.goal_executor:
                self.goal_executor.cancel()
        except Exception:
            pass
        self._invalidate_active_work()
        try:
            if self.voice_engine:
                self.voice_engine.stop_speaking()
        except Exception:
            pass
        if not was_running:
            return
        if self.operational_context:
            try: self.operational_context.clear_goal(status="cancelled")
            except Exception: pass
        self._finish_agent_hud(False, "Objetivo interrompido pelo usuário.")
        self.add_message(PUBLIC_NAME, "Objetivo interrompido.", is_jarvis=True)

    def _refresh_operational_ui(self):
        if not self.operational_context:
            return
        try:
            snap = self.operational_context.snapshot()
            if self.context_app_label:
                app = snap.get("active_app") or "--"
                mon = snap.get("active_monitor")
                self.context_app_label.configure(text=f"APP: {app}" + (f"  •  M{mon}" if mon else ""))
            if self.context_site_label:
                self.context_site_label.configure(text=f"SITE: {snap.get('active_site') or '--'}")
            if self.context_goal_label:
                goal = str(snap.get("current_goal") or "").strip()
                self.context_goal_label.configure(text=f"OBJETIVO: {goal[:44] if goal else '--'}")
            if self.context_download_label:
                last = str(snap.get("last_download") or "")
                self.context_download_label.configure(text=f"DOWNLOAD: {Path(last).name[:38] if last else '--'}")
            if self.autonomy_segment:
                current = str(snap.get("autonomy_level") or "assistido").capitalize()
                if self.autonomy_segment.get() != current:
                    self.autonomy_segment.set(current)
            if self.presence_segment:
                current = str(snap.get("presence_level") or "assistente").capitalize()
                if self.presence_segment.get() != current:
                    self.presence_segment.set(current)
        except Exception:
            pass

    def _set_autonomy_from_ui(self, value):
        key = str(value or "Assistido").lower()
        if self.operational_context:
            try:
                self.operational_context.set_autonomy(key)
                self._show_agent_notice(f"Autonomia: {key}")
            except Exception:
                pass

    def _set_presence_from_ui(self, value):
        key = str(value or "Assistente").lower()
        if self.operational_context:
            try:
                self.operational_context.set_presence(key)
                self._show_agent_notice(f"Presença: {key}")
            except Exception:
                pass

    def _cycle_sidebar_state(self):
        order = ["full", "compact", "closed"]
        try:
            idx = order.index(self._sidebar_state)
        except ValueError:
            idx = 0
        self._apply_sidebar_state(order[(idx + 1) % len(order)])

    def _apply_sidebar_state(self, state: str):
        state = state if state in {"full", "compact", "closed"} else "full"
        self._sidebar_state = state
        try:
            if state == "closed":
                self.side_panel.grid_remove(); self.sidebar_splitter.grid_remove()
                self.content_frame.grid_columnconfigure(0, minsize=0)
            else:
                self.side_panel.grid(); self.sidebar_splitter.grid()
                width = self._sidebar_last_full_width if state == "full" else self.SIDEBAR_MIN
                width = max(self.SIDEBAR_MIN, min(self.SIDEBAR_MAX, int(width)))
                self._sidebar_width = width
                self.content_frame.grid_columnconfigure(0, minsize=width)
                self.side_panel.configure(width=width)
            if self.sidebar_state_button:
                self.sidebar_state_button.configure(text={"full":"◧", "compact":"▯", "closed":"▣"}.get(state, "◧"))
            self._save_sidebar_width()
        except Exception:
            pass

    def _schedule_auto_diagnostic(self, reason=""):
        """Gera diagnóstico em background com cooldown para não poluir logs."""
        now = time.monotonic()

        if (
            now
            - self._last_auto_diagnostic_at
            < 30.0
        ):
            return

        self._last_auto_diagnostic_at = now

        if not self.diagnostics_manager:
            return

        def worker():
            try:
                report = self.diagnostics_manager.run(
                    core=self.core,
                    memory_store=self.memory_store,
                    voice_engine=self.voice_engine,
                    desktop=self.desktop_integration,
                    windows=self.window_manager,
                    audio=self.audio_device_manager,
                    vision=self.vision_system,
                    actions=self.actions,
                    performance=self.performance_tracer,
                    context=v8_context_status,
                    media_context=self.media_context,
                    conditional_rules=self.conditional_rules,
                    behavior_memory=self.behavior_memory,
                )

                data_dir = Path(
                    self.project_dir
                ) / "data"
                data_dir.mkdir(
                    parents=True,
                    exist_ok=True
                )

                path = (
                    data_dir
                    / "last_diagnostic.txt"
                )

                header = (
                    f"Motivo: {reason}\n\n"
                    if reason
                    else ""
                )

                path.write_text(
                    header + report,
                    encoding="utf-8"
                )

                self.logger.info(
                    f"Diagnóstico automático salvo: {path}",
                    "DIAGNOSTIC"
                )

            except Exception as e:
                self.logger.warning(
                    f"Diagnóstico automático falhou: {e}",
                    "DIAGNOSTIC"
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def _request_confirmation(
        self,
        description,
        callback,
        source_command=""
    ):
        """
        Confirma somente ações de alto impacto que permanecem fora do modo direto.
        - Texto: diálogo Sim/Não.
        - Voz/esfera: pergunta em voz e escuta automaticamente Sim/Não.
        """
        self._pending_confirmation = {
            "description": str(description),
            "callback": callback,
            "source_command": str(source_command),
        }

        def show():
            prompt = (
                f"Confirma {description}? "
                "Responda sim ou não."
            )

            if (
                self.voice_visual_mode
                or self._voice_command_active
            ):
                self._confirmation_voice_followup = True
                self._voice_visual_state = "OUVINDO"
                try:
                    if self.qt_voice_overlay:
                        self.qt_voice_overlay.set_state("OUVINDO")
                        self.qt_voice_overlay.set_caption("")
                except Exception:
                    pass
                self.add_message(
                    PUBLIC_NAME,
                    prompt,
                    is_jarvis=True
                )
                return

            confirmed = messagebox.askyesno(
                f"{PUBLIC_NAME} - Confirmação",
                f"{description}\n\nDeseja continuar?",
                parent=self.root
            )

            self._execute_pending_confirmation(
                confirmed
            )

        if self.root:
            self._post_context_ui_call(show)

    def _execute_pending_confirmation(
        self,
        confirmed
    ):
        pending = self._pending_confirmation
        self._pending_confirmation = None
        self._confirmation_voice_followup = False

        if not pending:
            return

        if not confirmed:
            self.add_message(
                PUBLIC_NAME,
                "Cancelado.",
                is_jarvis=True
            )
            return

        callback = pending.get(
            "callback"
        )

        def worker():
            try:
                result = (
                    callback()
                    if callable(callback)
                    else "Feito."
                )

                if result is None:
                    result = "Feito."

                self._post_context_ui_call(
                    self.add_message, PUBLIC_NAME, str(result), False, True, False, False
                )

            except Exception as e:
                self.logger.error(
                    e,
                    "Erro em ação confirmada",
                    "SAFETY"
                )

                self._post_context_ui_call(
                    self.add_message, PUBLIC_NAME, f"Não consegui executar: {e}", False, True, False, False
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def _resolve_confirmation_text(
        self,
        message
    ):
        """Retorna True quando havia confirmação pendente e a fala foi tratada."""
        if not self._pending_confirmation:
            return False

        answer = None

        if self.safety_manager:
            try:
                answer = (
                    self.safety_manager.confirmation_answer(
                        message
                    )
                )
            except Exception:
                answer = None

        if answer is None:
            normalized = str(
                message or ""
            ).strip().lower()

            if normalized in (
                "s",
                "ss",
                "sim",
                "sim pode",
                "confirmo",
                "confirmado",
                "pode",
                "pode sim",
                "pode fechar",
            ):
                answer = True
            elif normalized in (
                "não",
                "nao",
                "cancela",
                "cancelar",
            ):
                answer = False

        if answer is None:
            self._post_context_ui_call(
                self.add_message, PUBLIC_NAME, "Preciso de um sim ou não para continuar.",
                False, True, False, False
            )
            return True

        self._post_context_ui_call(self._execute_pending_confirmation, bool(answer))

        return True

    def _setup_desktop_integration(self):
        """Liga bandeja/hotkey em background depois da abertura da GUI."""
        global DesktopIntegration
        if DesktopIntegration is None:
            try:
                from desktop_integration import DesktopIntegration as _DesktopIntegration
                DesktopIntegration = _DesktopIntegration
            except Exception as exc:
                self.logger.warning(f"desktop_integration.py não pôde ser carregado: {exc}", "DESKTOP")
                return

        try:
            self.desktop_integration = DesktopIntegration(
                project_dir=self.project_dir,
                logger=self.logger,
                on_toggle_orb=self._desktop_toggle_orb,
                on_show_chat=self._desktop_show_chat,
                on_listen_now=self._desktop_listen_now,
                on_move_orb=self._desktop_move_orb,
                on_exit=self._desktop_exit,
                # O instalador já oferece a opção "Iniciar com Windows" e o
                # menu da bandeja permite alterá-la depois. Não sobrescreva a
                # escolha do usuário na primeira execução.
                auto_enable_startup=False,
            )
            self.desktop_integration.start()
            self._post_ui_event("runtime_ready", "desktop")

        except Exception as e:
            self.desktop_integration = None
            self.logger.error(
                e,
                "Erro na integração com desktop",
                "DESKTOP"
            )

    def _desktop_toggle_orb(self):
        self._post_ui_event(
            "desktop_toggle"
        )

    def _desktop_show_chat(self):
        self._post_ui_event(
            "desktop_show"
        )

    def _desktop_listen_now(self):
        self._post_ui_event(
            "desktop_listen"
        )

    def _desktop_move_orb(self):
        self._post_ui_event("desktop_move_orb")

    def _enable_overlay_move_mode(self):
        try:
            if not self.voice_visual_mode:
                self._open_voice_overlay()
            if self.qt_voice_overlay:
                self.qt_voice_overlay.set_caption("")
                self.qt_voice_overlay.set_move_mode(True)
                return
        except Exception as e:
            self.logger.warning(f"Não foi possível ativar movimento da esfera: {e}", "OVERLAY")

    def _desktop_exit(self):
        self._post_ui_event(
            "desktop_exit"
        )

    def _show_main_window(self):
        """Restaura o chat principal a partir da bandeja."""
        self._root_hidden_before_voice = False

        if self.voice_visual_mode:
            self._close_voice_overlay()

        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

            if self._root_state_before_voice == "zoomed":
                try:
                    self.root.state("zoomed")
                except Exception:
                    pass
        except Exception:
            pass

    def _hide_to_tray(self):
        """Esconde o JARVIS sem encerrar wake word, lembretes ou tray."""
        try:
            if self.voice_visual_mode:
                self._close_voice_overlay()

            self.root.withdraw()

            self.logger.info(
                f"{PUBLIC_NAME} ocultado na bandeja.",
                "DESKTOP"
            )
        except Exception as e:
            self.logger.warning(
                f"Não foi possível ocultar na bandeja: {e}",
                "DESKTOP"
            )

    def _exit_application(self):
        self._exit_requested = True
        self._on_closing()

    def _setup_gui(self):
        """Configura a interface principal"""
        # Configuração do CustomTkinter
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        # Mantém escala lógica estável; o DPI físico é tratado pelo Windows/CTk.
        try:
            ctk.set_widget_scaling(1.0)
        except Exception:
            pass
        
        # Janela principal
        self.root = ctk.CTk()
        self.root.title(f"{PUBLIC_NAME} {JARVIS_VERSION} - Assistente de Sistema")
        self.root.geometry("1280x820")
        self.root.configure(fg_color="#212121")

        # Transparencia global da interface.
        # 1.00 = totalmente opaca | 0.80 = mais transparente.
        try:
            opacity = max(0.60, min(float(self.WINDOW_OPACITY), 1.00))
            if self.UI_CRISP_RENDER:
                opacity = 1.00
            self.root.attributes("-alpha", opacity)
        except Exception as e:
            self.logger.warning(
                f"Nao foi possivel aplicar transparencia: {e}",
                "GUI"
            )
        
        # Layout principal
        self._create_main_layout()
        self._apply_windows_acrylic()
        self._start_clock_updater()
        
        # Configurações finais
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        # Build 11: paleta instantanea sem precisar abrir o painel completo.
        self.root.bind("<Control-space>", self._open_command_palette, add="+")
        self.root.bind("<Control-Shift-space>", self._open_command_palette, add="+")
        self.root.bind(
            "<Configure>",
            self._note_window_motion,
            add="+"
        )
        
        # Build 15: historico pode conter dezenas de bolhas. Criar ate 120
        # widgets antes do primeiro frame fazia o programa parecer travado.
        # O restore comeca assim que o mainloop ganha controle.
        self.root.after(70, self._restore_or_welcome)
    
    def _get_ui_icon(self, kind: str, size: int = 18, color: str = "#D9DDE7"):
        """Retorna CTkImage nítida e em cache para os controles principais."""
        key = (str(kind), int(size), str(color))
        cached = self._ui_icon_cache.get(key)
        if cached is not None:
            return cached
        image = _ui_supersampled_icon(kind, size=size, color=color)
        icon = ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
        self._ui_icon_cache[key] = icon
        return icon

    def _background_update_check(self):
        """Consulta Releases fora da thread da interface; falha de rede é silenciosa."""
        try:
            if not self.update_manager or not self.update_manager.is_configured():
                return
            info = self.update_manager.check()
            if info is not None:
                self._post_ui_call(self._show_update_available, info)
        except Exception as exc:
            try:
                self.logger.warning(f"Verificação de atualização indisponível: {exc}", "UPDATE")
            except Exception:
                pass

    def _show_update_available(self, info):
        self._pending_update_info = info
        if not self.update_button:
            return
        try:
            self.update_button.configure(text=f"ATUALIZAR {info.version}", state="normal")
        except Exception:
            pass

    def _manual_update_check(self):
        """Botão Atualizar sempre visível: procura uma release nova sob demanda."""
        if self._update_download_active:
            return
        if not self.update_manager or not self.update_manager.is_configured():
            messagebox.showwarning(
                "Atualização do JARVIS",
                "O atualizador ainda não está configurado para um repositório de releases.",
            )
            return
        self._update_download_active = True
        try:
            self.update_button.configure(text="VERIFICANDO...", state="disabled")
        except Exception:
            pass

        def worker():
            try:
                info = self.update_manager.check()
                self._post_ui_call(self._finish_manual_update_check, info, "")
            except Exception as exc:
                self._post_ui_call(self._finish_manual_update_check, None, str(exc))

        threading.Thread(target=worker, name="JARVIS-MANUAL-UPDATE-CHECK", daemon=True).start()

    def _finish_manual_update_check(self, info, error=""):
        self._update_download_active = False
        if error:
            try:
                self.update_button.configure(text="ATUALIZAR", state="normal")
            except Exception:
                pass
            messagebox.showerror(
                "Atualização do JARVIS",
                "Não consegui consultar as atualizações agora.\n\n" + str(error),
            )
            return
        if info is None:
            self._pending_update_info = None
            try:
                self.update_button.configure(text="ATUALIZADO", state="normal")
                self.root.after(1800, lambda: self.update_button.configure(text="ATUALIZAR", state="normal"))
            except Exception:
                pass
            messagebox.showinfo(
                "Atualização do JARVIS",
                f"Você já está na versão mais recente ({JARVIS_VERSION}).",
            )
            return
        self._show_update_available(info)
        # O clique do usuário já expressou intenção de atualizar; depois da
        # consulta, abre imediatamente a confirmação da versão encontrada.
        self._update_now()

    def _set_update_progress(self, downloaded: int, total: int):
        if not self.update_button:
            return
        try:
            if total > 0:
                pct = max(0, min(100, int(downloaded * 100 / total)))
                self.update_button.configure(text=f"BAIXANDO {pct}%", state="disabled")
            else:
                mb = downloaded / (1024 * 1024)
                self.update_button.configure(text=f"BAIXANDO {mb:.0f} MB", state="disabled")
        except Exception:
            pass

    def _update_now(self):
        if self._update_download_active:
            return
        info = self._pending_update_info
        if info is None:
            self._manual_update_check()
            return
        notes = " ".join(str(getattr(info, "notes", "") or "").split())
        if len(notes) > 420:
            notes = notes[:417].rstrip() + "..."
        update_kind = "atualização rápida" if getattr(info, "is_hot", False) else "atualização completa"
        detail = f"Nova versão {info.version} disponível ({update_kind})."
        if notes:
            detail += f"\n\n{notes}"
        if getattr(info, "is_hot", False):
            detail += "\n\nBaixar e aplicar agora? Não será necessário reinstalar o JARVIS. Ele apenas reiniciará."
        else:
            detail += "\n\nBaixar e instalar agora? O JARVIS será reiniciado."
        if not messagebox.askyesno("Atualização do JARVIS", detail):
            return
        self._update_download_active = True
        try:
            self.update_button.configure(text="BAIXANDO 0%", state="disabled")
        except Exception:
            pass

        def worker():
            try:
                package = self.update_manager.download(
                    info,
                    progress=lambda done, total: self._post_ui_call(self._set_update_progress, done, total),
                )
                if getattr(info, "is_hot", False):
                    self.update_manager.apply_hot_update(package, info)
                    self.update_manager.launch_hot_restart()
                else:
                    self.update_manager.launch_installer(package, update=True)
                self._post_ui_call(self._begin_update_shutdown)
            except Exception as exc:
                self._post_ui_call(self._update_failed, str(exc))

        threading.Thread(target=worker, name="JARVIS-DESKTOP-UPDATE", daemon=True).start()

    def _begin_update_shutdown(self):
        try:
            hot = bool(self._pending_update_info and getattr(self._pending_update_info, "is_hot", False))
            self.update_button.configure(text="APLICANDO..." if hot else "INSTALANDO...", state="disabled")
        except Exception:
            pass
        self._update_status("ATUALIZANDO", "#5F91FF")
        self._exit_requested = True
        try:
            self.root.after(250, self._on_closing)
        except Exception:
            self._on_closing()

    def _update_failed(self, detail: str):
        self._update_download_active = False
        try:
            if self.update_button and self._pending_update_info:
                self.update_button.configure(text=f"ATUALIZAR {self._pending_update_info.version}", state="normal")
        except Exception:
            pass
        messagebox.showerror(
            "Atualização do JARVIS",
            "Não foi possível instalar a atualização com segurança.\n\n" + str(detail or "Erro desconhecido."),
        )

    def _open_api_settings(self):
        """Permite trocar a chave sem editar arquivos ou abrir terminal."""
        try:
            from first_run_setup import show_api_key_dialog
            changed = show_api_key_dialog(parent=self.root, first_run=False)
        except Exception as exc:
            messagebox.showerror("Configurar Gemini", f"Não consegui abrir a configuração.\n\n{exc}")
            return
        if not changed:
            return
        self._update_status("CONFIGURANDO IA", "#5F91FF")

        def reload_clients():
            ok = False
            try:
                ok = bool(self.core.reload_api_key())
            except Exception:
                ok = False
            try:
                self.web_search.reload_api_key()
            except Exception:
                pass
            self._post_ui_call(self._finish_api_reload, ok)

        threading.Thread(target=reload_clients, name="JARVIS-API-RELOAD", daemon=True).start()

    def _finish_api_reload(self, ok: bool):
        self._update_status("ONLINE" if ok else "API CONFIGURADA", Config.get_color("success") if ok else "#F5B942")
        if ok:
            messagebox.showinfo("Configurar Gemini", "Chave salva com segurança e Gemini reconectado.")
        else:
            messagebox.showwarning(
                "Configurar Gemini",
                "A chave foi salva. Se o Gemini ainda não responder, use 'Testar chave' e confira sua conexão/limites da conta.",
            )

    def _create_main_layout(self):
        """Interface principal com identidade visual e atualização sempre acessível."""
        main_container = ctk.CTkFrame(self.root, fg_color="#212121")
        main_container.pack(fill="both", expand=True)

        header = ctk.CTkFrame(main_container, fg_color="#212121", corner_radius=0, height=50)
        header.pack(fill="x", padx=14, pady=(6, 2))
        header.pack_propagate(False)
        header.bind("<ButtonPress-1>", lambda event: self._begin_native_window_drag(self.root))

        identity = ctk.CTkFrame(header, fg_color="transparent")
        identity.pack(side="left", fill="y", padx=(2, 10))

        # Usa o mesmo capacete/cabeça do ícone oficial do JARVIS no cabeçalho.
        # O asset já acompanha o instalador em jarvis.ico, então a troca também
        # funciona em Hot Update sem precisar recompilar o executável.
        try:
            logo_path = Path(self.project_dir) / "jarvis.ico"
            if logo_path.is_file():
                with Image.open(logo_path) as source_logo:
                    logo_image = source_logo.convert("RGBA").copy()
                self._brand_logo_image = ctk.CTkImage(
                    light_image=logo_image, dark_image=logo_image, size=(38, 38)
                )
                ctk.CTkLabel(
                    identity, text="", image=self._brand_logo_image,
                    width=40, height=40, fg_color="transparent"
                ).pack(side="left", padx=(0, 8), pady=3)
        except Exception as exc:
            try:
                self.logger.warning(f"Logo jarvis.ico indisponível na interface: {exc}", "GUI")
            except Exception:
                pass

        title_box = ctk.CTkFrame(identity, fg_color="transparent")
        title_box.pack(side="left", padx=(0, 0), pady=5)
        ctk.CTkLabel(
            title_box, text=PUBLIC_NAME,
            font=ctk.CTkFont(family="Bahnschrift", size=14, weight="bold"),
            text_color="#FAFAFC"
        ).pack(anchor="w")
        status_row = ctk.CTkFrame(title_box, fg_color="transparent")
        status_row.pack(anchor="w")
        self.status_dot = ctk.CTkLabel(status_row, text="●", font=ctk.CTkFont(size=10), text_color="#31D47D", width=12)
        self.status_dot.pack(side="left")
        self.status_label = ctk.CTkLabel(
            status_row, text="ONLINE", font=ctk.CTkFont(family="Tahoma", size=8, weight="bold"), text_color="#9EA3AD"
        )
        self.status_label.pack(side="left", padx=(1, 0))
        self.activity_label = ctk.CTkLabel(
            status_row, text="Pronto", font=ctk.CTkFont(family="Tahoma", size=8), text_color="#777D87"
        )
        self.activity_label.pack(side="left", padx=(8, 0))

        header_tools = ctk.CTkFrame(header, fg_color="transparent")
        header_tools.pack(side="right", fill="y", padx=(8, 2), pady=6)
        self.update_button = ctk.CTkButton(
            header_tools, text="ATUALIZAR", width=96, height=26, corner_radius=9,
            fg_color="#5F91FF", hover_color="#78A3FF", text_color="#11141A",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
            command=self._update_now,
        )
        # Fica sempre visível. Sem release pendente, o clique faz uma
        # verificação manual; quando há release, mostra a versão encontrada.
        self.update_button.pack(side="left", padx=(0, 7), pady=4)
        self.clock_label = ctk.CTkLabel(
            header_tools, text="--:--", font=ctk.CTkFont(family="Consolas", size=10), text_color="#8B9098"
        )
        self.clock_label.pack(side="left", padx=(0, 8), pady=7)
        self.source_badge = ctk.CTkLabel(
            header_tools, text="LOCAL", width=52, height=24, corner_radius=10,
            fg_color="#1E3028", text_color="#74DFA3", font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold")
        )
        self.source_badge.pack(side="left", padx=(0, 6), pady=4)
        self.api_button = ctk.CTkButton(
            header_tools, text="API", width=42, height=26, corner_radius=9,
            fg_color="transparent", border_width=1, border_color="#3B4048",
            hover_color="#303238", text_color="#AEB4BE",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"),
            command=self._open_api_settings,
        )
        self.api_button.pack(side="left", padx=(0, 6), pady=4)
        self.sidebar_state_button = ctk.CTkButton(
            header_tools, text="", image=self._get_ui_icon("sidebar", 17, "#B8BDC6"), width=30, height=30, corner_radius=10,
            fg_color="transparent", hover_color="#303238", text_color="#B8BDC6",
            command=self._cycle_sidebar_state
        )
        self.sidebar_state_button.pack(side="left", pady=1)

        content = ctk.CTkFrame(main_container, fg_color="#212121")
        self.content_frame = content
        content.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        content.grid_rowconfigure(0, weight=1)
        self._sidebar_width = self._load_sidebar_width()
        content.grid_columnconfigure(0, weight=0, minsize=self._sidebar_width)
        content.grid_columnconfigure(1, weight=0, minsize=5)
        content.grid_columnconfigure(2, weight=1)

        side_panel = ctk.CTkFrame(content, fg_color="#171717", corner_radius=12, width=self._sidebar_width)
        self.side_panel = side_panel
        side_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        side_panel.grid_propagate(False)
        self._create_system_monitor(side_panel)

        splitter = ctk.CTkFrame(content, width=5, corner_radius=3, fg_color="#27292D", cursor="sb_h_double_arrow")
        self.sidebar_splitter = splitter
        splitter.grid(row=0, column=1, sticky="ns", padx=1)
        splitter.bind("<ButtonPress-1>", self._sidebar_resize_start)
        splitter.bind("<B1-Motion>", self._sidebar_resize_drag)
        splitter.bind("<ButtonRelease-1>", self._sidebar_resize_end)
        try:
            layout_data = json.loads(self._ui_layout_path().read_text(encoding="utf-8"))
            self._sidebar_state = str(layout_data.get("sidebar_state") or "full")
            self._sidebar_last_full_width = self._sidebar_width
        except Exception:
            self._sidebar_state = "full"
        if self._sidebar_state != "full":
            self.root.after(20, self._apply_sidebar_state, self._sidebar_state)

        chat_panel = ctk.CTkFrame(content, fg_color="#212121", corner_radius=0)
        chat_panel.grid(row=0, column=2, sticky="nsew", padx=(3, 0))
        self._create_chat_area(chat_panel)

    def _create_tech_j_badge(self, parent, size=36, bg="#212121"):
        """Emblema J supersampled: nítido mesmo com escala de 125/150%."""
        image = _render_tech_j_image(size)
        self._tech_j_image = ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
        badge = ctk.CTkButton(
            parent, text="", image=self._tech_j_image, width=size, height=size,
            corner_radius=max(8, size // 3), fg_color="transparent", hover_color="#292D38",
            border_width=0, command=self._new_conversation
        )
        return badge

    def _ui_layout_path(self):
        return Path(self.project_dir) / "data" / "ui_layout.json"

    def _load_orb_style(self):
        try:
            data = json.loads(self._ui_layout_path().read_text(encoding="utf-8"))
            value = str(data.get("voice_orb_style") or "core").strip().lower()
        except Exception:
            value = "core"
        return value if value in {"crystal", "core", "rings", "pulse", "minimal"} else "core"

    def _save_orb_style(self):
        try:
            path = self._ui_layout_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data["voice_orb_style"] = str(self.voice_orb_style or "core")
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_sidebar_width(self):
        try:
            data = json.loads(self._ui_layout_path().read_text(encoding="utf-8"))
            value = int(data.get("sidebar_width", self.SIDEBAR_DEFAULT))
        except Exception:
            value = self.SIDEBAR_DEFAULT
        return max(self.SIDEBAR_MIN, min(self.SIDEBAR_MAX, value))

    def _save_sidebar_width(self):
        try:
            path = self._ui_layout_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            if self._sidebar_state == "full":
                self._sidebar_last_full_width = int(self._sidebar_width)
            data["sidebar_width"] = int(self._sidebar_last_full_width if self._sidebar_state != "full" else self._sidebar_width)
            data["sidebar_state"] = str(self._sidebar_state)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _sidebar_resize_start(self, event):
        self._sidebar_drag_start_x = int(event.x_root)
        self._sidebar_drag_start_width = int(self._sidebar_width)

    def _sidebar_resize_drag(self, event):
        if self._sidebar_drag_start_x is None:
            return
        width = self._sidebar_drag_start_width + int(event.x_root) - self._sidebar_drag_start_x
        width = max(self.SIDEBAR_MIN, min(self.SIDEBAR_MAX, width))
        # Arrastar o divisor sempre significa que o usuario quer o painel completo.
        self._sidebar_state = "full"
        self._sidebar_width = width
        self._sidebar_last_full_width = width
        try:
            self.side_panel.grid()
            self.sidebar_splitter.grid()
            self.content_frame.grid_columnconfigure(0, minsize=width)
            self.side_panel.configure(width=width)
            if self.sidebar_state_button:
                self.sidebar_state_button.configure(image=self._get_ui_icon("sidebar", 17, "#B8BDC6"), text="")
        except Exception:
            pass

    def _sidebar_resize_end(self, event=None):
        self._sidebar_drag_start_x = None
        self._save_sidebar_width()

    def _create_chat_area(self, parent):
        """Área de conversa da 1.0 Beta, com ações destrutivas fora do cabeçalho."""
        wrapper = ctk.CTkFrame(parent, fg_color="#212121")
        wrapper.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        chat_header = ctk.CTkFrame(wrapper, fg_color="transparent", height=38)
        chat_header.pack(fill="x", pady=(0, 6))
        self.current_conversation_label = ctk.CTkLabel(
            chat_header, text="Nova conversa",
            font=ctk.CTkFont(family="Bahnschrift", size=13, weight="bold"), text_color="#F5F6F8"
        )
        self.current_conversation_label.pack(side="left", padx=4)

        chat_actions = ctk.CTkFrame(chat_header, fg_color="transparent")
        chat_actions.pack(side="right")
        ctk.CTkButton(
            chat_actions, text="Copiar", image=self._get_ui_icon("copy", 14, "#D8DBE2"), width=76, height=28, corner_radius=9,
            fg_color="#2B2D31", hover_color="#373A40", text_color="#D8DBE2",
            compound="left", font=ctk.CTkFont(family="Tahoma", size=9, weight="bold"),
            command=self._copy_everything
        ).pack(side="left", padx=3)

        self.agent_hud = ctk.CTkFrame(
            wrapper, fg_color="#1B1E24", corner_radius=12, border_width=1, border_color="#3A4050"
        )
        hud_top = ctk.CTkFrame(self.agent_hud, fg_color="transparent")
        hud_top.pack(fill="x", padx=11, pady=(8, 2))
        self.agent_hud_title = ctk.CTkLabel(
            hud_top, text=f"{PUBLIC_NAME} AGENT", text_color="#C6A8FF",
            font=ctk.CTkFont(family="Tahoma", size=9, weight="bold")
        )
        self.agent_hud_title.pack(side="left")
        self.agent_stop_button = ctk.CTkButton(
            hud_top, text="■ PARAR", width=70, height=24, corner_radius=8,
            fg_color="#4A252A", hover_color="#653138", text_color="#FFB6BD",
            font=ctk.CTkFont(family="Tahoma", size=8, weight="bold"), command=self._stop_agent_goal
        )
        self.agent_stop_button.pack(side="right")
        self.agent_hud_step = ctk.CTkLabel(
            self.agent_hud, text="", anchor="w", justify="left", wraplength=760,
            text_color="#D7DCE4", font=ctk.CTkFont(family="Tahoma", size=10)
        )
        self.agent_hud_step.pack(fill="x", padx=11, pady=(0, 5))
        self.agent_hud_progress = ctk.CTkProgressBar(
            self.agent_hud, height=4, corner_radius=2, fg_color="#2B303A", progress_color="#9A74F5"
        )
        self.agent_hud_progress.pack(fill="x", padx=11, pady=(0, 9))
        self.agent_hud_progress.set(0.0)
        self.agent_hud.pack_forget()

        self.chat_scroll = ctk.CTkScrollableFrame(
            wrapper, fg_color="#212121", corner_radius=0, border_width=0,
            scrollbar_button_color="#4A4A4A", scrollbar_button_hover_color="#5A5A5A"
        )
        self.chat_scroll.pack(fill="both", expand=True, pady=(0, 10))
        self.chat_display = None
        self._install_chat_mousewheel()

        input_shell = ctk.CTkFrame(
            wrapper, fg_color="#292B31", corner_radius=24, border_width=1, border_color="#3F444E"
        )
        self.input_shell = input_shell
        input_shell.pack(fill="x", padx=14, pady=(2, 0))

        self.quick_menu_button = ctk.CTkButton(
            input_shell, text="", image=self._get_ui_icon("dots", 18, "#D8DCE7"), width=40, height=40, corner_radius=20,
            fg_color="#393C45", hover_color="#4B5060", text_color="#D8DCE7",
            command=lambda: self._show_quick_actions_menu(self.quick_menu_button)
        )
        self.quick_menu_button.pack(side="left", padx=(8, 4), pady=6)

        # Build 16: composer multilinha. Enter envia; Shift+Enter cria nova linha.
        # O bind fica somente no campo de mensagem, então Enter em busca/dialogos
        # nunca envia uma mensagem acidentalmente.
        self.text_input = ctk.CTkTextbox(
            input_shell, height=self.COMPOSER_MIN_HEIGHT, wrap="word", activate_scrollbars=False,
            font=ctk.CTkFont(family="Tahoma", size=13, weight="normal"), text_color="#FAFAFB",
            fg_color="transparent", border_width=0, corner_radius=0
        )
        self.text_input.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=6)
        self.text_input.bind("<FocusIn>", self._composer_focus_in, add="+")
        self.text_input.bind("<FocusOut>", self._composer_focus_out, add="+")
        self.text_input.bind("<Return>", self._on_composer_return, add="+")
        self.text_input.bind("<KeyRelease>", self._resize_composer, add="+")
        self._composer_set_placeholder()
        self.voice_button = ctk.CTkButton(
            input_shell, text="", image=self._get_ui_icon("voice", 18, "#D8DCE7"), width=40, height=40, corner_radius=20,
            fg_color="#393C45", hover_color="#4B5060",
            text_color="#D8DCE7", command=self._toggle_voice_visual_mode
        )
        self.voice_button.pack(side="left", padx=4, pady=6)
        self.send_button = ctk.CTkButton(
            input_shell, text="", image=self._get_ui_icon("send", 18, "#17181C"), width=40, height=40, corner_radius=20,
            fg_color="#F4F5F7", hover_color="#DDE1E8",
            text_color="#17181C", command=self.send_message
        )
        self.send_button.pack(side="left", padx=(4, 8), pady=6)

    def _create_system_monitor(self, parent):
        """Barra lateral 13.10.1: compacta, tipografica e com contraste reforcado."""
        side = ctk.CTkFrame(parent, fg_color="transparent")
        side.pack(fill="both", expand=True, padx=8, pady=9)

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", pady=(0, 8))
        # 13.10.1: sem emblema visual; marca tipografica limpa e mais legivel.
        ctk.CTkLabel(
            brand, text="JARVIS", text_color="#F4F6FA",
            font=ctk.CTkFont(family="Bahnschrift", size=11, weight="bold")
        ).pack(side="left", padx=(1, 0))
        ctk.CTkLabel(
            brand, text=JARVIS_VERSION.upper(), text_color="#69717E",
            font=ctk.CTkFont(family="Consolas", size=7)
        ).pack(side="left", padx=(5, 0), pady=(2, 0))

        actions = ctk.CTkFrame(side, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 8))
        self._conversation_search_button = ctk.CTkButton(
            actions, text="", image=self._get_ui_icon("search", 17, "#D4D7DD"), width=36, height=34, corner_radius=10,
            fg_color="transparent", hover_color="#292B30", text_color="#D4D7DD",
            command=lambda: self._open_conversation_search_popover(self._conversation_search_button)
        )
        self._conversation_search_button.pack(side="left", padx=(0, 4))
        self._new_chat_button = ctk.CTkButton(
            actions, text="", image=self._get_ui_icon("new_chat", 17, "#D4D7DD"), width=36, height=34, corner_radius=10,
            fg_color="transparent", hover_color="#292B30", text_color="#D4D7DD",
            command=self._new_conversation
        )
        self._new_chat_button.pack(side="left", padx=4)
        ctk.CTkLabel(
            actions, text="Conversas", text_color="#AAB0BA",
            font=ctk.CTkFont(family="Bahnschrift", size=9, weight="bold")
        ).pack(side="right", padx=(4, 3))

        self.conversation_list_frame = ctk.CTkScrollableFrame(
            side, height=295, fg_color="transparent", corner_radius=0, border_width=0,
            scrollbar_button_color="#34363B", scrollbar_button_hover_color="#44474E"
        )
        self.conversation_list_frame.pack(fill="both", expand=True, pady=(0, 8))
        # Lista historica fora do caminho critico do primeiro frame.
        self.root.after(110, self._refresh_conversation_list)

        separator = ctk.CTkFrame(side, height=1, fg_color="#292B30")
        separator.pack(fill="x", pady=(1, 8))

        system_head = ctk.CTkFrame(side, fg_color="transparent")
        system_head.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(
            system_head, text="SISTEMA", text_color="#A2A9B4",
            font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(
            system_head, text="↗", width=24, height=24, corner_radius=8,
            fg_color="transparent", hover_color="#292B30", text_color="#8C929C",
            font=ctk.CTkFont(size=11), command=self._open_diagnostic_panel
        ).pack(side="right")

        gauges = ctk.CTkFrame(side, fg_color="transparent")
        gauges.pack(fill="x", pady=(0, 6))
        self.cpu_gauge = CircularMetricGauge(gauges, "CPU", "#5F91FF", size=56)
        self.ram_gauge = CircularMetricGauge(gauges, "RAM", "#9876FF", size=56)
        self.network_gauge = CircularMetricGauge(gauges, "REDE", "#45D393", size=56)
        for gauge in (self.cpu_gauge, self.ram_gauge, self.network_gauge):
            gauge.pack(side="left", fill="x", expand=True, padx=1)

        self.active_app_label = ctk.CTkLabel(
            side, text="Ativo  •  --", anchor="w", justify="left",
            font=ctk.CTkFont(family="Tahoma", size=8, weight="normal"), text_color="#9CA4AF"
        )
        self.active_app_label.pack(fill="x", padx=3, pady=(1, 4))

        self.media_value_label = ctk.CTkLabel(
            side, text="♪  Nenhuma mídia ativa", anchor="w", justify="left", wraplength=210,
            font=ctk.CTkFont(family="Tahoma", size=8, weight="normal"), text_color="#A6ADB8"
        )
        self.media_value_label.pack(fill="x", padx=3, pady=(0, 4))

        # Contexto detalhado, autonomia e presença saíram da barra lateral.
        # Continuam disponíveis pelo painel ⋮ e pelo diagnóstico.
        self.context_app_label = None
        self.context_site_label = None
        self.context_goal_label = None
        self.context_download_label = None
        self.autonomy_segment = None
        self.presence_segment = None

        # Mantém o log ativo para o sistema, mas invisível na interface principal.
        self.system_log_frame = ctk.CTkFrame(side, fg_color="transparent")
        self.system_log_text = ctk.CTkTextbox(
            self.system_log_frame, height=120, font=ctk.CTkFont(family="Consolas", size=9),
            text_color="#7EE2A8", fg_color="#080C11", border_width=0, wrap="word"
        )
        self.system_log_text.pack(fill="both", expand=True)
        self.system_log_text.configure(state="disabled")
        self.monitor_visible = False

        ctk.CTkLabel(
            side, text=f"{JARVIS_BUILD}", text_color="#4F555E",
            font=ctk.CTkFont(family="Consolas", size=7)
        ).pack(anchor="e", padx=3, pady=(1, 0))

        self._start_log_updater()
        self._start_system_metrics_updater()

    def _open_conversation_search_popover(self, widget=None):
        """Busca de conversas em popover: na barra fica apenas a lupa."""
        try:
            if self._conversation_search_popup and self._conversation_search_popup.winfo_exists():
                self._conversation_search_popup.destroy()
                self._conversation_search_popup = None
                return
        except Exception:
            self._conversation_search_popup = None
        if not self.root:
            return
        popup = ctk.CTkToplevel(self.root)
        self._conversation_search_popup = popup
        popup.overrideredirect(True)
        popup.configure(fg_color="#17191E")
        try:
            popup.attributes("-topmost", True)
            x = (widget.winfo_rootx() if widget else self.root.winfo_rootx()+18)
            y = (widget.winfo_rooty()+widget.winfo_height()+5 if widget else self.root.winfo_rooty()+80)
        except Exception:
            x, y = 40, 80
        width, height = 290, 58
        popup.geometry(f"{width}x{height}+{int(x)}+{int(y)}")
        shell = ctk.CTkFrame(popup, fg_color="#1D1F25", corner_radius=13, border_width=1, border_color="#3B3E46")
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        self.history_search_entry = ctk.CTkEntry(
            shell, height=38, placeholder_text="Buscar conversas", fg_color="#25272D",
            border_color="#40434B", font=ctk.CTkFont(family="Tahoma", size=11)
        )
        self.history_search_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=9)
        go = ctk.CTkButton(
            shell, text="", image=self._get_ui_icon("search", 17, "#E6E8ED"), width=38, height=38, corner_radius=10,
            fg_color="#343740", hover_color="#454A56", command=self._search_history_ui
        )
        go.pack(side="left", padx=(0, 8), pady=9)
        self.history_search_entry.bind("<Return>", lambda _e: self._search_history_ui(), add="+")
        popup.bind("<Escape>", lambda _e: popup.destroy(), add="+")
        self.history_search_entry.focus_force()

    def _refresh_conversation_list(self):
        """Histórico compacto: uma linha por conversa, estilo ChatGPT."""
        if self.root and threading.get_ident() != self._main_thread_id:
            self._post_context_ui_call(self._refresh_conversation_list)
            return
        if not self.conversation_list_frame:
            return
        try:
            for child in self.conversation_list_frame.winfo_children():
                child.destroy()
            conversations = self.memory_store.list_conversations(limit=28)
            try:
                current_title = self.memory_store.get_conversation_title(self.active_conversation_id)
                if self.current_conversation_label:
                    self.current_conversation_label.configure(text=current_title or "Nova conversa")
            except Exception:
                pass
            if not conversations:
                ctk.CTkLabel(
                    self.conversation_list_frame, text="Nenhuma conversa",
                    font=ctk.CTkFont(family="Tahoma", size=9), text_color="#8F97A3"
                ).pack(anchor="w", padx=8, pady=8)
                return
            for conversation in conversations:
                conversation_id = int(conversation["id"])
                full_title = conversation.get("title") or "Nova conversa"
                title = full_title if len(full_title) <= 24 else full_title[:21].rstrip() + "..."
                active = conversation_id == self.active_conversation_id
                row = ctk.CTkFrame(
                    self.conversation_list_frame, fg_color="#292B30" if active else "transparent",
                    corner_radius=9, border_width=0
                )
                row.pack(fill="x", padx=1, pady=1)
                button = ctk.CTkButton(
                    row, text=title, height=34, anchor="w", corner_radius=8,
                    fg_color="transparent", hover_color="#2D3036", text_color="#E4E6EB",
                    font=ctk.CTkFont(family="Tahoma", size=10, weight="normal"),
                    command=lambda cid=conversation_id: self._switch_conversation(cid)
                )
                button.pack(side="left", fill="x", expand=True, padx=(2, 0), pady=1)
                more = ctk.CTkButton(
                    row, text="", image=self._get_ui_icon("dots", 15, "#939AA5"), width=28, height=28, corner_radius=8,
                    fg_color="transparent", hover_color="#3A3D44", text_color="#939AA5"
                )
                more.configure(command=lambda cid=conversation_id, t=full_title, w=more: self._show_conversation_actions(cid, t, w))
                more.pack(side="right", padx=(0, 3), pady=3)
        except Exception as e:
            self.logger.error(e, "Erro ao atualizar lista de conversas", "MEMORY")

    def _set_input_focus(self, focused: bool):
        """Realce discreto da caixa de entrada sem alterar o layout."""
        try:
            if self.input_shell:
                self.input_shell.configure(
                    border_color="#8A78FF" if focused else "#3F444E",
                    fg_color="#30333B" if focused else "#292B31",
                )
        except Exception:
            pass

    def _composer_set_placeholder(self):
        if not self.text_input or self._composer_placeholder_active:
            return
        try:
            current = self.text_input.get("1.0", "end-1c")
            if current.strip():
                return
            self.text_input.configure(state="normal", text_color="#A5ABB5")
            self.text_input.delete("1.0", "end")
            self.text_input.insert("1.0", self._composer_placeholder_text)
            self._composer_placeholder_active = True
        except Exception:
            pass

    def _composer_focus_in(self, event=None):
        self._set_input_focus(True)
        if self._composer_placeholder_active and self.text_input:
            try:
                self.text_input.configure(state="normal", text_color="#FAFAFB")
                self.text_input.delete("1.0", "end")
                self._composer_placeholder_active = False
            except Exception:
                pass
        return None

    def _composer_focus_out(self, event=None):
        self._set_input_focus(False)
        try:
            if self.text_input and not self.text_input.get("1.0", "end-1c").strip():
                self._composer_set_placeholder()
        except Exception:
            pass
        return None

    def _composer_text(self) -> str:
        if not self.text_input or self._composer_placeholder_active:
            return ""
        try:
            return self.text_input.get("1.0", "end-1c")
        except Exception:
            return ""

    def _clear_composer(self):
        if not self.text_input:
            return
        try:
            self.text_input.configure(state="normal", text_color="#FAFAFB")
            self.text_input.delete("1.0", "end")
            self._composer_placeholder_active = False
            self.text_input.configure(height=self.COMPOSER_MIN_HEIGHT)
        except Exception:
            pass

    def _resize_composer(self, event=None):
        if not self.text_input or self._composer_placeholder_active:
            return None
        try:
            text = self.text_input.get("1.0", "end-1c")
            visual_lines = 0
            for line in (text.splitlines() or [""]):
                visual_lines += max(1, (len(line.expandtabs(4)) + 87) // 88)
            height = self.COMPOSER_MIN_HEIGHT + max(0, min(4, visual_lines - 1)) * 19
            self.text_input.configure(height=min(self.COMPOSER_MAX_HEIGHT, height))
        except Exception:
            pass
        return None

    def _on_composer_return(self, event=None):
        # Shift+Enter preserva o comportamento nativo de nova linha.
        if event is not None and (int(getattr(event, "state", 0) or 0) & 0x0001):
            return None
        self.send_message(event=event)
        return "break"

    def _set_composer_enabled(self, enabled: bool):
        try:
            if self.text_input:
                self.text_input.configure(state="normal" if enabled else "disabled")
            if self.send_button:
                self.send_button.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def _popup_dark_menu(self, widget, entries, upward=False):
        """Menu contextual escuro; menus de reticencias podem abrir para cima."""
        menu = tk.Menu(
            self.root, tearoff=0, bg="#202228", fg="#F1F1F1",
            activebackground="#3B3F49", activeforeground="#FFFFFF",
            relief="flat", bd=0, font=("Tahoma", 10)
        )
        item_count = 0
        for label, command in entries:
            if label == "---":
                menu.add_separator()
            else:
                item_count += 1
                menu.add_command(label=label, command=command)
        try:
            x = widget.winfo_rootx()
            if upward:
                estimated_h = max(34, item_count * 27 + 18)
                y = max(4, widget.winfo_rooty() - estimated_h - 4)
            else:
                y = widget.winfo_rooty() + widget.winfo_height() + 2
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _show_conversation_actions(self, conversation_id: int, title: str, widget):
        self._popup_dark_menu(
            widget,
            [
                ("Renomear", lambda cid=conversation_id: self._rename_conversation(cid)),
                ("Apagar", lambda cid=conversation_id: self._delete_conversation(cid)),
            ],
            upward=True,
        )

    def _show_quick_actions_menu(self, widget):
        self._toggle_quick_control_panel(widget)

    def _quick_preferences_path(self):
        return self._ui_layout_path()

    def _save_quick_preferences(self):
        try:
            path = self._quick_preferences_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            if self.voice_engine:
                status = self.voice_engine.status()
                data["tts_rate"] = str(status.get("tts_rate") or "+10%")
                data["mic_sensitivity"] = float(status.get("mic_sensitivity") or 1.12)
            data["interaction_mode"] = str(self.interaction_mode or "auto")
            data["autonomy_percent"] = int(getattr(self, "_autonomy_percent", 60))
            data["presence_percent"] = int(getattr(self, "_presence_percent", 60))
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _apply_saved_quick_preferences(self):
        """Restaura apenas preferencias leves; nunca troca driver/VAD/STT."""
        try:
            path = Path(self.project_dir) / "data" / "ui_layout.json"
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            if self.voice_engine:
                rate = str(data.get("tts_rate") or "").strip()
                if rate:
                    self.voice_engine.set_tts_rate(rate)
                mic = data.get("mic_sensitivity")
                if mic is not None:
                    self.voice_engine.set_microphone_sensitivity(float(mic))
            mode = str(data.get("interaction_mode") or "").strip().lower()
            if mode in {"auto", "conversa", "comando"}:
                self.interaction_mode = mode
                if self.voice_engine:
                    self.voice_engine.set_conversation_mode(mode == "conversa")
                self._sync_conversation_overlay_lock(mode == "conversa")
            self._autonomy_percent = self._snap_behavior_percent(data.get("autonomy_percent", 60))
            self._presence_percent = self._snap_behavior_percent(data.get("presence_percent", 60))
        except Exception as exc:
            try:
                self.logger.warning(f"Preferencias visuais nao restauradas: {exc}", "GUI")
            except Exception:
                pass

    @staticmethod
    def _snap_behavior_percent(value) -> int:
        try:
            value = int(round(float(value) / 20.0) * 20)
        except Exception:
            value = 60
        return max(20, min(100, value))

    @staticmethod
    def _behavior_percent_label(value: int) -> str:
        value = JarvisGUI._snap_behavior_percent(value)
        return {20: "BÁSICO", 40: "BAIXO", 60: "MÉDIO", 80: "ALTO", 100: "EXTRA ALTO"}.get(value, "MÉDIO")

    def _apply_behavior_levels_from_percent(self, silent=False):
        autonomy = self._snap_behavior_percent(getattr(self, "_autonomy_percent", 60))
        presence = self._snap_behavior_percent(getattr(self, "_presence_percent", 60))
        autonomy_key = "manual" if autonomy <= 20 else ("assistido" if autonomy <= 60 else "autonomo")
        presence_key = "discreto" if presence <= 20 else ("assistente" if presence <= 60 else "jarvis")
        try:
            if self.operational_context:
                if hasattr(self.operational_context, "set_autonomy_percent"):
                    self.operational_context.set_autonomy_percent(autonomy)
                    self.operational_context.set_presence_percent(presence)
                else:
                    self.operational_context.set_autonomy(autonomy_key)
                    self.operational_context.set_presence(presence_key)
        except Exception:
            pass
        if not silent:
            self._save_quick_preferences()
        return autonomy_key, presence_key

    def _apply_autonomy_percent_ui(self, value):
        self._autonomy_percent = self._snap_behavior_percent(value)
        self._apply_behavior_levels_from_percent(silent=False)
        self._quick_feedback(f"Autonomia: {self._behavior_percent_label(self._autonomy_percent)} · {self._autonomy_percent}%")
        self._refresh_quick_panel_values()

    def _apply_presence_percent_ui(self, value):
        self._presence_percent = self._snap_behavior_percent(value)
        self._apply_behavior_levels_from_percent(silent=False)
        self._quick_feedback(f"Presença: {self._behavior_percent_label(self._presence_percent)} · {self._presence_percent}%")
        self._refresh_quick_panel_values()

    def _quick_feedback(self, text: str):
        try:
            if self.activity_label:
                self.activity_label.configure(text=str(text))
                self.root.after(1800, lambda: self.activity_label and self.activity_label.configure(text="Sistema pronto para operar"))
        except Exception:
            pass

    def _apply_voice_rate_ui(self, rate: str, label: str):
        try:
            if not self.voice_engine:
                raise RuntimeError("motor de voz indisponivel")
            applied = self.voice_engine.set_tts_rate(rate)
            self._save_quick_preferences()
            self._quick_feedback(f"Voz: {label} ({applied})")
            self._refresh_quick_panel_values()
        except Exception as exc:
            self._quick_feedback(f"Falha ao ajustar voz: {exc}")

    def _apply_mic_sensitivity_ui(self, factor: float, label: str):
        try:
            if not self.voice_engine:
                raise RuntimeError("motor de voz indisponivel")
            applied = self.voice_engine.set_microphone_sensitivity(float(factor))
            self._save_quick_preferences()
            self._quick_feedback(f"Microfone: {label} ({applied:.2f}x)")
            self._refresh_quick_panel_values()
        except Exception as exc:
            self._quick_feedback(f"Falha ao ajustar microfone: {exc}")

    def _apply_interaction_mode_ui(self, mode: str):
        selected = str(mode or "auto").strip().lower()
        if selected not in {"auto", "conversa", "comando"}:
            selected = "auto"
        self.interaction_mode = selected
        try:
            if self.voice_engine:
                self.voice_engine.set_conversation_mode(selected == "conversa")
        except Exception:
            pass
        self._sync_conversation_overlay_lock(selected == "conversa")
        try:
            if self.operational_context:
                self.operational_context.set_mode(selected)
        except Exception:
            pass
        self._save_quick_preferences()
        labels = {"auto": "Automatico", "conversa": "Conversa", "comando": "Comando"}
        self._quick_feedback(f"Modo: {labels.get(selected, selected)}")
        self._refresh_quick_panel_values()

    def _quick_control_values(self):
        status = {}
        try:
            status = self.voice_engine.status() if self.voice_engine else {}
        except Exception:
            status = {}
        return (
            str(status.get("tts_rate") or "+10%"),
            float(status.get("mic_sensitivity") or 1.12),
            str(self.interaction_mode or "auto"),
            int(getattr(self, "_autonomy_percent", 60)),
            int(getattr(self, "_presence_percent", 60)),
        )

    def _refresh_quick_panel_values(self):
        rate, mic, mode, autonomy, presence = self._quick_control_values()
        try:
            if self._quick_panel_voice_value:
                self._quick_panel_voice_value.configure(text=f"ATUAL  {rate}")
            if self._quick_panel_mic_value:
                self._quick_panel_mic_value.configure(text=f"ATUAL  {mic:.2f}x")
            if self._quick_panel_mode_value:
                labels = {"auto": "AUTO", "conversa": "CONVERSA", "comando": "COMANDO"}
                self._quick_panel_mode_value.configure(text=labels.get(mode, mode.upper()))
            if self._quick_panel_autonomy_value:
                self._quick_panel_autonomy_value.configure(text=f"{self._behavior_percent_label(autonomy)} · {autonomy}%")
            if self._quick_panel_presence_value:
                self._quick_panel_presence_value.configure(text=f"{self._behavior_percent_label(presence)} · {presence}%")
        except Exception:
            pass

    def _close_quick_control_panel(self):
        panel = self.quick_panel
        self.quick_panel = None
        self.quick_panel_is_open = False
        self._quick_panel_voice_value = None
        self._quick_panel_mic_value = None
        self._quick_panel_mode_value = None
        self._quick_panel_autonomy_value = None
        self._quick_panel_presence_value = None
        try:
            if self.quick_menu_button:
                self.quick_menu_button.configure(fg_color="#393C45", text_color="#D8DCE7", text="", image=self._get_ui_icon("dots", 18, "#D8DCE7"))
        except Exception:
            pass
        try:
            if panel and panel.winfo_exists():
                panel.destroy()
        except Exception:
            pass

    def _quick_action(self, callback, close=True):
        if close:
            self._close_quick_control_panel()
        try:
            callback()
        except Exception as exc:
            self._quick_feedback(f"Acao indisponivel: {exc}")

    def _quick_panel_button(self, parent, text, command, accent=False):
        button = ctk.CTkButton(
            parent, text=text, height=32, corner_radius=10,
            fg_color="#51448A" if accent else "#292C34",
            hover_color="#6556A8" if accent else "#383C47",
            border_width=1, border_color="#7464B5" if accent else "#3D424D",
            text_color="#F5F2FF" if accent else "#DDE1EA",
            font=ctk.CTkFont(family="Tahoma", size=9, weight="bold"),
            command=command,
        )
        return button

    def _toggle_quick_control_panel(self, widget=None):
        try:
            if self.quick_panel and self.quick_panel.winfo_exists():
                self._close_quick_control_panel()
                return
        except Exception:
            self.quick_panel = None
        self._open_quick_control_panel(widget or self.quick_menu_button)

    def _open_quick_control_panel(self, widget):
        if not self.root or not widget:
            return
        self._close_quick_control_panel()
        panel = ctk.CTkToplevel(self.root)
        self.quick_panel = panel
        self.quick_panel_is_open = True
        panel.overrideredirect(True)
        try:
            panel.transient(self.root)
            panel.attributes("-topmost", True)
            panel.attributes("-alpha", 0.70)
        except Exception:
            pass
        panel.configure(fg_color="#15171C")

        width, height = 420, 650
        try:
            self.root.update_idletasks()
            anchor_x = int(widget.winfo_rootx())
            anchor_y = int(widget.winfo_rooty())
            screen_w = int(self.root.winfo_screenwidth())
            screen_h = int(self.root.winfo_screenheight())
            x = max(8, min(anchor_x, screen_w - width - 8))
            final_y = max(8, min(anchor_y - height - 10, screen_h - height - 8))
        except Exception:
            x, final_y = 80, 40
        start_y = final_y + 14
        panel.geometry(f"{width}x{height}+{x}+{start_y}")

        shell = ctk.CTkFrame(panel, fg_color="#181A20", corner_radius=18, border_width=1, border_color="#3A3E49")
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        head = ctk.CTkFrame(shell, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(13, 5))
        ctk.CTkLabel(head, text="JARVIS", text_color="#F3F4F7", font=ctk.CTkFont(family="Bahnschrift", size=12, weight="bold")).pack(side="left")
        ctk.CTkLabel(head, text="CONTROLES", text_color="#777E89", font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold")).pack(side="left", padx=8)
        ctk.CTkButton(
            head, text="×", width=28, height=28, corner_radius=9, fg_color="transparent",
            hover_color="#343741", text_color="#AEB3BF", command=self._close_quick_control_panel
        ).pack(side="right")

        body = ctk.CTkScrollableFrame(shell, fg_color="transparent", corner_radius=0, scrollbar_button_color="#33363E")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        rate, mic, mode, autonomy, presence = self._quick_control_values()

        def section(title, value_text, accent="#BDAEFF"):
            box = ctk.CTkFrame(body, fg_color="#202229", corner_radius=13)
            box.pack(fill="x", padx=5, pady=4)
            top = ctk.CTkFrame(box, fg_color="transparent")
            top.pack(fill="x", padx=11, pady=(8, 4))
            ctk.CTkLabel(top, text=title, text_color="#8F96A5", font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold")).pack(side="left")
            val = ctk.CTkLabel(top, text=value_text, text_color=accent, font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold"))
            val.pack(side="right")
            return box, val

        mode_box, self._quick_panel_mode_value = section("MODO DO CHAT", mode.upper())
        row = ctk.CTkFrame(mode_box, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(0, 8))
        for label, key in (("Auto", "auto"), ("Conversa", "conversa"), ("Comando", "comando")):
            self._quick_panel_button(row, label, lambda k=key: self._apply_interaction_mode_ui(k), accent=(mode == key)).pack(side="left", fill="x", expand=True, padx=3)

        autonomy_box, self._quick_panel_autonomy_value = section(
            "AUTONOMIA", f"{self._behavior_percent_label(autonomy)} · {autonomy}%", "#D1B4FF"
        )
        ctk.CTkLabel(
            autonomy_box, text="Quanto o JARVIS pode decidir e executar dentro dos limites seguros.",
            text_color="#6F7682", font=ctk.CTkFont(family="Tahoma", size=8), anchor="w"
        ).pack(fill="x", padx=11, pady=(0, 2))
        autonomy_slider = ctk.CTkSlider(
            autonomy_box, from_=20, to=100, number_of_steps=4, height=18,
            progress_color="#8C63D8", button_color="#C9AEFF", button_hover_color="#E1D2FF",
            fg_color="#343740", command=self._apply_autonomy_percent_ui
        )
        autonomy_slider.pack(fill="x", padx=12, pady=(4, 2))
        autonomy_slider.set(autonomy)
        labels = ctk.CTkFrame(autonomy_box, fg_color="transparent")
        labels.pack(fill="x", padx=11, pady=(0, 8))
        ctk.CTkLabel(labels, text="Básico 20%", text_color="#676E79", font=ctk.CTkFont(family="Tahoma", size=7)).pack(side="left")
        ctk.CTkLabel(labels, text="Extra alto 100%", text_color="#676E79", font=ctk.CTkFont(family="Tahoma", size=7)).pack(side="right")

        presence_box, self._quick_panel_presence_value = section(
            "PRESENÇA", f"{self._behavior_percent_label(presence)} · {presence}%", "#69E3B1"
        )
        ctk.CTkLabel(
            presence_box, text="Quanto ele pode avisar, sugerir e participar sem ser chamado.",
            text_color="#6F7682", font=ctk.CTkFont(family="Tahoma", size=8), anchor="w"
        ).pack(fill="x", padx=11, pady=(0, 2))
        presence_slider = ctk.CTkSlider(
            presence_box, from_=20, to=100, number_of_steps=4, height=18,
            progress_color="#2F9B70", button_color="#79E6B9", button_hover_color="#9BF0CD",
            fg_color="#343740", command=self._apply_presence_percent_ui
        )
        presence_slider.pack(fill="x", padx=12, pady=(4, 2))
        presence_slider.set(presence)
        labels = ctk.CTkFrame(presence_box, fg_color="transparent")
        labels.pack(fill="x", padx=11, pady=(0, 8))
        ctk.CTkLabel(labels, text="Básico 20%", text_color="#676E79", font=ctk.CTkFont(family="Tahoma", size=7)).pack(side="left")
        ctk.CTkLabel(labels, text="Extra alto 100%", text_color="#676E79", font=ctk.CTkFont(family="Tahoma", size=7)).pack(side="right")

        voice_box, self._quick_panel_voice_value = section("VELOCIDADE DA VOZ", f"ATUAL · {rate}", "#61D6FF")
        row = ctk.CTkFrame(voice_box, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(0, 8))
        for label, value in (("Devagar", "+4%"), ("Normal", "+10%"), ("Rápida", "+14%")):
            self._quick_panel_button(row, label, lambda v=value, l=label: self._apply_voice_rate_ui(v, l), accent=(rate == value)).pack(side="left", fill="x", expand=True, padx=3)

        mic_box, self._quick_panel_mic_value = section("MICROFONE", f"ATUAL · {mic:.2f}x", "#69E3B1")
        row = ctk.CTkFrame(mic_box, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(0, 8))
        for label, value in (("Normal", 1.00), ("Sensível", 1.18), ("Muito", 1.28)):
            self._quick_panel_button(row, label, lambda v=value, l=label: self._apply_mic_sensitivity_ui(v, l), accent=(abs(mic - value) < 0.025)).pack(side="left", fill="x", expand=True, padx=3)

        ctk.CTkLabel(body, text="EXTRAS", text_color="#777E8C", font=ctk.CTkFont(family="Bahnschrift", size=8, weight="bold")).pack(anchor="w", padx=9, pady=(8, 3))
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x", padx=3, pady=(0, 8))
        actions = [
            ("Contexto atual", self._show_operational_context),
            ("Rotinas", self._show_workflows),
            ("Esfera", lambda: self._show_orb_style_menu(widget)),
            ("Memórias", self._open_memory_manager),
            ("Paleta", self._open_command_palette),
            ("Diagnóstico", self._open_diagnostic_panel),
            ("Logs", self._toggle_monitor),
        ]
        for index, (label, callback) in enumerate(actions):
            button = self._quick_panel_button(grid, label, lambda cb=callback: self._quick_action(cb))
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            body, text="Modo direto ativo: ações comuns executam sem confirmação; só alto impacto pede autorização.",
            text_color="#626975", font=ctk.CTkFont(family="Tahoma", size=8)
        ).pack(pady=(2, 8))

        try:
            self.quick_menu_button.configure(fg_color="#51448A", text_color="#FFFFFF", text="", image=self._get_ui_icon("dots", 18, "#FFFFFF"))
            panel.bind("<Escape>", lambda _e: self._close_quick_control_panel())
            panel.protocol("WM_DELETE_WINDOW", self._close_quick_control_panel)
            panel.focus_force()
        except Exception:
            pass

        def close_if_focus_left():
            if self.quick_panel is not panel:
                return
            try:
                focus = panel.focus_get()
                if focus is not None and str(focus).startswith(str(panel)):
                    return
            except Exception:
                pass
            self._close_quick_control_panel()
        try:
            panel.bind("<FocusOut>", lambda _e: self.root.after(160, close_if_focus_left), add="+")
        except Exception:
            pass

        def animate(step=0):
            if not self.quick_panel or self.quick_panel is not panel:
                return
            steps = 11
            ratio = min(1.0, step / steps)
            # Ease-out-quint: arranque rápido e aterrissagem macia, sem sensação de atraso.
            eased = 1.0 - (1.0 - ratio) ** 5
            y = int(round(start_y + (final_y - start_y) * eased))
            try:
                panel.geometry(f"{width}x{height}+{x}+{y}")
                panel.attributes("-alpha", 0.70 + 0.30 * eased)
            except Exception:
                pass
            if step < steps:
                self.root.after(self.UI_MOTION_INTERVAL_MS, lambda: animate(step + 1))
            else:
                try:
                    panel.attributes("-alpha", 1.0)
                except Exception:
                    pass
        animate(0)

    def _show_orb_style_menu(self, widget=None):
        """Escolhe a identidade visual da esfera de voz."""
        anchor = widget or self.quick_menu_button or self.voice_button
        labels = [
            ("Cristal  -  3D vítreo", "crystal"),
            ("Núcleo  -  reator/JARVIS", "core"),
            ("Anéis  -  holográfico/HUD", "rings"),
            ("Pulso  -  orgânico e responsivo", "pulse"),
            ("Minimal  -  discreto e limpo", "minimal"),
        ]
        entries = []
        for label, style in labels:
            prefix = "● " if style == self.voice_orb_style else "   "
            entries.append((prefix + label, lambda st=style: self._set_orb_style(st)))
        self._popup_dark_menu(anchor, entries, upward=True)

    def _set_orb_style(self, style: str, announce: bool = True):
        value = str(style or "core").strip().lower()
        if value not in {"crystal", "core", "rings", "pulse", "minimal"}:
            value = "core"
        self.voice_orb_style = value
        self._save_orb_style()
        # Invalida também o cache do renderer Tk para que a troca seja imediata
        # mesmo em máquinas sem PySide6.
        self._orb_base_pil = None
        self._orb_base_color = None
        self._orb_base_style = None
        try:
            if self.qt_voice_overlay:
                self.qt_voice_overlay.set_orb_style(value)
        except Exception as exc:
            self.logger.warning(f"Não foi possível trocar estilo da esfera Qt: {exc}", "OVERLAY")
        # O fallback Tk usa a mesma escolha no próximo frame; os detalhes
        # específicos são renderizados pelo método _render_orb_frame.
        try:
            if self.voice_visual_mode and not self._qt_overlay_active:
                self._start_voice_orb_animation()
        except Exception:
            pass
        if announce:
            names = {"crystal": "Cristal", "core": "Núcleo", "rings": "Anéis", "pulse": "Pulso", "minimal": "Minimal"}
            self.add_message(PUBLIC_NAME, f"Estilo da esfera: {names.get(value, 'Cristal')}.", is_jarvis=True)
        return value

    def _open_command_palette(self, event=None):
        """Spotlight minimo: pede uma frase e envia pelo mesmo pipeline do chat."""
        try:
            value = simpledialog.askstring(
                f"{PUBLIC_NAME} - Comando rápido",
                f"Pergunte ou peça algo ao {PUBLIC_NAME}:",
                parent=self.root,
            )
        except Exception:
            value = None
        value = " ".join(str(value or "").split()).strip()
        if not value:
            return "break" if event is not None else None
        if self.is_processing:
            messagebox.showinfo(PUBLIC_NAME, f"{PUBLIC_NAME} ainda está concluindo a tarefa atual.", parent=self.root)
            return "break" if event is not None else None
        self.add_message("Você", value, is_user=True)
        self._update_status("PROCESSANDO", "#F5B942")
        self._process_message(value, source="palette")
        return "break" if event is not None else None

    def _show_operational_context(self):
        if not self.operational_context:
            messagebox.showinfo(PUBLIC_NAME, "Contexto operacional indisponível nesta sessão.", parent=self.root)
            return
        try:
            self.operational_context.refresh_from_windows()
            snap = self.operational_context.snapshot()
            lines = [
                f"Aplicativo: {snap.get('active_app') or '-'}",
                f"Janela: {snap.get('active_title') or '-'}",
                f"Site: {snap.get('active_site') or '-'}",
                f"Monitor: {snap.get('active_monitor') or '-'}",
                f"Objetivo: {snap.get('current_goal') or '-'}",
                f"Progresso: {snap.get('goal_progress', 0)}%",
                f"Último download: {snap.get('last_download') or '-'}",
                f"Última ação: {snap.get('last_action') or '-'}",
                f"Modo: {snap.get('interaction_mode') or self.interaction_mode}",
                f"Autonomia: {snap.get('autonomy_level') or 'assistido'}",
                f"Presença: {snap.get('presence_level') or 'assistente'}",
            ]
            messagebox.showinfo(f"{PUBLIC_NAME} - O que sei agora", "\n".join(lines), parent=self.root)
        except Exception as exc:
            messagebox.showwarning(PUBLIC_NAME, f"Não consegui ler o contexto operacional: {exc}", parent=self.root)

    def _show_workflows(self):
        if not self.workflow_engine:
            messagebox.showinfo(PUBLIC_NAME, "Motor de rotinas indisponível nesta sessão.", parent=self.root)
            return
        try:
            items = self.workflow_engine.list_workflows()
            if not items:
                text = "Ainda não há rotinas aprendidas.\n\nDiga: 'aprende rotina trabalho', execute os passos e depois 'terminar rotina'."
            else:
                text = "\n".join(
                    f"• {item.get('name')} — {len(item.get('steps') or [])} passos"
                    for item in items
                )
            messagebox.showinfo(f"{PUBLIC_NAME} - Rotinas", text, parent=self.root)
        except Exception as exc:
            messagebox.showwarning(PUBLIC_NAME, f"Não consegui listar as rotinas: {exc}", parent=self.root)

    def _prompt_teach_application(self):
        alias = simpledialog.askstring(
            f"{PUBLIC_NAME} - Ensinar aplicativo",
            "Como você quer chamar o aplicativo?",
            parent=self.root,
        )
        if alias is None:
            return
        alias = alias.strip()
        if not alias:
            return
        try:
            result = self._teach_application(alias)
        except Exception as exc:
            result = f"Não consegui ensinar esse aplicativo: {exc}"
        self.add_message(PUBLIC_NAME, result, is_jarvis=True)

    def _show_experience_stats(self):
        if self.experience_engine is None:
            messagebox.showinfo(PUBLIC_NAME, "Experience Engine indisponível nesta sessão.")
            return
        try:
            stats = self.experience_engine.stats()
            messagebox.showinfo(
                f"{PUBLIC_NAME} {JARVIS_VERSION} - Experience Engine",
                "\n".join([
                    f"Experiências registradas: {stats.get('experiences', 0)}",
                    f"Frases observadas: {stats.get('phrases', 0)}",
                    f"Confiáveis: {stats.get('trusted', 0)}",
                    f"Candidatas: {stats.get('candidate', 0)}",
                    f"Conflitantes: {stats.get('conflicted', 0)}",
                    f"Correções do usuário: {stats.get('corrections', 0)}",
                    "",
                    f"O aprendizado altera dados locais, nunca o código do {PUBLIC_NAME}.",
                ]),
                parent=self.root,
            )
        except Exception as exc:
            messagebox.showwarning(PUBLIC_NAME, f"Não consegui ler as experiências: {exc}", parent=self.root)

    def _rename_conversation(self, conversation_id: int):
        if self.is_processing:
            return
        current_title = self.memory_store.get_conversation_title(conversation_id)
        new_title = simpledialog.askstring(
            PUBLIC_NAME,
            "Novo nome da conversa:",
            initialvalue=current_title,
            parent=self.root,
        )
        if new_title is None:
            return
        if self.memory_store.rename_conversation(conversation_id, new_title):
            self._refresh_conversation_list()

    def _delete_conversation(self, conversation_id: int):
        if self.is_processing:
            return
        title = self.memory_store.get_conversation_title(conversation_id)
        if not messagebox.askyesno(
            PUBLIC_NAME,
            f"Apagar a conversa '{title}'?\n\nEssa ação remove somente esta conversa.",
            parent=self.root,
        ):
            return
        try:
            was_active = int(conversation_id) == int(self.active_conversation_id)
            if was_active:
                self._cancel_history_restore(clear_deferred=True)
                self._invalidate_active_work()
                self._clear_stream_chunk_queue()
                self._discard_streaming_visual()
            self.memory_store.delete_conversation(conversation_id)
            if was_active:
                self.active_conversation_id = self.memory_store.get_or_create_active_conversation()
                self.chat_history = []
                self.streaming_label = None
                self.streaming_buffer = ""
                self._clear_chat_widgets()
                self._restore_or_welcome()
            self._refresh_conversation_list()
        except Exception as exc:
            self.logger.error(exc, "Erro ao apagar conversa", "MEMORY")

    def _switch_conversation(self, conversation_id: int):
        """Abre uma conversa antiga salva no banco."""
        if self.is_processing:
            messagebox.showinfo(
                PUBLIC_NAME,
                "Aguarde a resposta atual terminar antes de trocar de conversa."
            )
            return

        try:
            if conversation_id == self.active_conversation_id:
                return

            self._cancel_history_restore(clear_deferred=True)
            self._invalidate_active_work()
            self._clear_stream_chunk_queue()
            self._discard_streaming_visual()
            if not self.memory_store.switch_conversation(conversation_id):
                return

            self.active_conversation_id = int(conversation_id)
            self.chat_history = []
            self.streaming_label = None
            self.streaming_buffer = ""

            self._clear_chat_widgets()
            self._restore_or_welcome()
            self._refresh_conversation_list()

            self.logger.info(
                f"Conversa aberta: {self.active_conversation_id}",
                "MEMORY"
            )

        except Exception as e:
            self.logger.error(
                e,
                "Erro ao trocar de conversa",
                "MEMORY"
            )

    def _start_persistent_reminder_watcher(self):
        def tick():
            try:
                for item in self.memory_store.due_reminders():
                    self.memory_store.mark_reminder_done(item["id"])
                    self.add_message(
                        PUBLIC_NAME,
                        f"LEMBRETE: {item['task']}",
                        is_jarvis=True,
                        speak=self.voice_enabled
                    )
                self.root.after(10000, tick)
            except Exception as e:
                self.logger.error(e, "Erro no verificador de lembretes", "MEMORY")
                try:
                    self.root.after(30000, tick)
                except Exception:
                    pass
        self.root.after(1500, tick)

    def _start_jarvis_player_watcher(self):
        """Automação opt-in para players de streaming em sites ou apps.

        O watcher nunca usa um atalho cego para ações automáticas: exige contexto
        de streaming ativo e um botão visual único com confiança suficiente.
        Assim a mesma lógica funciona em Crunchyroll, Netflix, Prime Video,
        Disney+, Max, YouTube e outros players com controles visíveis.
        """
        self._player_watch_title = ""
        self._player_watch_title_since = time.monotonic()
        self._player_skip_scan_at = 0.0
        self._player_next_scan_at = 0.0
        self._player_skip_success_at = 0.0
        self._player_next_success_at = 0.0

        def tick():
            try:
                if not self.root:
                    return
                if not self.operational_context or not self.browser_autonomy or not self.window_manager:
                    self.root.after(7000, tick)
                    return

                try:
                    snap = self.operational_context.refresh_from_windows(self.window_manager)
                except Exception:
                    snap = self.operational_context.snapshot()
                try:
                    media_snap = self.media_context.refresh(force=True) if self.media_context else None
                    service_now = str(getattr(media_snap, "service", "") or self.browser_autonomy.detect_streaming_service() or "").lower()
                    if media_snap is not None:
                        v8_remember_media(media_snap.to_dict())
                except Exception:
                    service_now = str(self.browser_autonomy.detect_streaming_service() or "").lower()
                prefs = self.operational_context.player_automation(service=service_now)
                if not prefs.get("skip_intro") and not prefs.get("next_episode"):
                    self.root.after(7000, tick)
                    return

                title = str(snap.get("active_title") or "")
                try:
                    active_streaming = bool(self.browser_autonomy.is_streaming_active())
                except Exception:
                    active_streaming = False
                if not active_streaming:
                    self.root.after(7000, tick)
                    return

                now = time.monotonic()
                if title != self._player_watch_title:
                    self._player_watch_title = title
                    self._player_watch_title_since = now
                    self._player_skip_scan_at = 0.0
                    self._player_next_scan_at = 0.0
                age = max(0.0, now - self._player_watch_title_since)

                # Abertura: procura durante os primeiros 15 minutos. Players
                # curtos/longos variam bastante; o clique só ocorre se a visão
                # encontrar explicitamente um controle de pular abertura.
                if prefs.get("skip_intro") and 3.0 <= age <= 900.0 and now - self._player_skip_scan_at >= 12.0 and now - self._player_skip_success_at >= 75.0:
                    self._player_skip_scan_at = now
                    result = self.browser_autonomy.click_visible(
                        self.browser_autonomy._streaming_visual_description("skip_intro", service_now)
                    )
                    if result.get("success"):
                        self._player_skip_success_at = now
                        self.add_message(PUBLIC_NAME, "Pulei a abertura automaticamente.", is_jarvis=True)

                # Próximo episódio: pode aparecer cedo em episódios curtos. Não
                # usamos atalho aqui; somente o botão visual inequívoco.
                if prefs.get("next_episode") and age >= 300.0 and now - self._player_next_scan_at >= 20.0 and now - self._player_next_success_at >= 90.0:
                    self._player_next_scan_at = now
                    result = self.browser_autonomy.click_visible(
                        self.browser_autonomy._streaming_visual_description("next", service_now)
                    )
                    if result.get("success"):
                        self._player_next_success_at = now
                        self.add_message(PUBLIC_NAME, "Passei para o próximo episódio automaticamente.", is_jarvis=True)
            except Exception as exc:
                try:
                    self.logger.warning(f"Automação proativa do player: {exc}", "AGENT")
                except Exception:
                    pass
            try:
                if self.root:
                    self.root.after(7000, tick)
            except Exception:
                pass

        try:
            if self.root:
                self.root.after(4500, tick)
        except Exception:
            pass

    def _apply_windows_acrylic(self):
        """Material Win10 otimizado: borda escura nativa e blur só se solicitado."""
        if os.name != "nt":
            return
        try:
            self.root.update_idletasks()
            hwnd = self.root.winfo_id()
            import ctypes
            # Dark titlebar / frame. Falha silenciosamente em builds antigos.
            try:
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                enabled = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(enabled), ctypes.sizeof(enabled)
                )
            except Exception:
                pass

            want_blur = str(jarvis_env("UI_ACRYLIC_BLUR", "0")).strip().lower() in {"1", "true", "on", "sim"}
            if not want_blur:
                return

            class ACCENTPOLICY(ctypes.Structure):
                _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int), ("GradientColor", ctypes.c_int), ("AnimationId", ctypes.c_int)]
            class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
                _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]
            accent = ACCENTPOLICY()
            accent.AccentState = 4
            accent.GradientColor = 0xE010131B
            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = 19
            data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
            data.SizeOfData = ctypes.sizeof(accent)
            ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        except Exception as e:
            self.logger.warning(f"Material visual Windows indisponível: {e}", "GUI")

    def _start_clock_updater(self):
        def tick():
            try:
                if self.clock_label:
                    from datetime import datetime
                    self.clock_label.configure(text=datetime.now().strftime("%d/%m  %H:%M:%S"))
                self.root.after(1000, tick)
            except Exception:
                pass
        self.root.after(200, tick)

    def _toggle_compact_mode(self):
        try:
            self.compact_mode = not self.compact_mode
            if self.compact_mode:
                if self.side_panel:
                    self.side_panel.grid_remove()
                self.root.geometry("860x650")
            else:
                if self.side_panel:
                    self.side_panel.grid()
                self.root.geometry("1280x820")
        except Exception as e:
            self.logger.error(e, "Erro ao alternar modo compacto", "GUI")

    def _delete_current_conversation(self):
        self._delete_conversation(self.active_conversation_id)

    def _search_history_ui(self):
        query = self.history_search_entry.get().strip() if self.history_search_entry else ""
        if not query:
            return
        results = self.memory_store.search_messages(query, limit=12)
        if not results:
            self.add_message("Sistema", f"Nenhuma mensagem antiga encontrada para '{query}'.", is_system=True)
            return
        lines = [f"Resultados do histórico para '{query}':"]
        for item in results:
            title = item.get("conversation_title") or "Conversa"
            sender = item.get("sender") or ""
            msg = (item.get("message") or "").replace("\n", " ")
            if len(msg) > 160:
                msg = msg[:157] + "..."
            lines.append(f"- [{title}] {sender}: {msg}")
        self.add_message("Sistema", "\n".join(lines), is_system=True)

    def _teach_application(self, alias: str) -> str:
        """Ensina apps Win32 e Microsoft Store sem exigir .exe quando não existe."""
        alias = (alias or "").strip().rstrip(".?!,;:").strip()
        if not alias:
            return "Diga qual aplicativo devo aprender."

        # Primeiro tenta candidatos conhecidos pelo próprio Windows. Isso cobre
        # Microsoft Store/UWP, que aparecem como shell:AppsFolder\AppID.
        try:
            candidates = self.actions.find_application_candidates(alias, limit=8)
            alias_compact = self.actions._normalize_app_name(alias).replace(" ", "")

            for candidate in candidates:
                label = str(candidate.get("label") or "")
                target = str(candidate.get("target") or "")
                label_compact = self.actions._normalize_app_name(label).replace(" ", "")

                if (
                    target.startswith("shell:AppsFolder\\")
                    and alias_compact
                    and alias_compact == label_compact
                ):
                    return self.actions.learn_app_alias(
                        alias,
                        target,
                        display_name=label
                    )
        except Exception as e:
            self.logger.warning(
                f"Não foi possível autoensinar app da Store: {e}",
                "APP"
            )

        # Apps tradicionais: usuário escolhe .exe/atalho.
        # Build 5: quando o menu ⋯ chama esta funcao, ja estamos na thread Tk.
        # A versao anterior agendava root.after() e imediatamente fazia wait(),
        # bloqueando a propria mainloop: parecia que "Ensinar app" travava.
        result = {"path": ""}

        def choose():
            result["path"] = filedialog.askopenfilename(
                title=f"Escolha o aplicativo para '{alias}'",
                parent=self.root,
                filetypes=[
                    ("Aplicativos e atalhos", "*.exe *.lnk *.bat *.cmd"),
                    ("Executáveis", "*.exe"),
                    ("Todos os arquivos", "*.*"),
                ]
            )

        if threading.get_ident() == self._main_thread_id:
            choose()
        else:
            done = threading.Event()
            def choose_from_ui():
                try:
                    choose()
                finally:
                    done.set()
            self._post_context_ui_call(choose_from_ui)
            deadline = time.monotonic() + 300.0
            while not done.wait(timeout=0.10):
                token = int(getattr(self._work_thread_context, "token", 0) or 0)
                if token and not self._work_is_current(token):
                    return "Aprendizado cancelado porque uma nova solicitação começou."
                if time.monotonic() >= deadline:
                    return "A janela de seleção não respondeu. Tente novamente pelo menu ⋯ > Ensinar aplicativo."

        if not result["path"]:
            return (
                "Aprendizado cancelado. Se for um aplicativo da Microsoft Store, "
                "tente primeiro 'abra o aplicativo' para eu detectá-lo pelo Windows."
            )
        return self.actions.learn_app_alias(alias, result["path"])

    @staticmethod
    def _local_strip_accents(text: str) -> str:
        value = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(
            ch for ch in value
            if not unicodedata.combining(ch)
        )

    def _parse_pt_number(self, phrase: str):
        """Converte números falados comuns de 0 a 100 para inteiro."""
        clean = self._local_strip_accents(phrase).lower()
        clean = re.sub(r"[^a-z0-9 ]+", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()

        if clean.isdigit():
            return int(clean)

        direct = {
            "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2,
            "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
            "sete": 7, "oito": 8, "nove": 9, "dez": 10,
            "onze": 11, "doze": 12, "treze": 13, "catorze": 14,
            "quatorze": 14, "quinze": 15, "dezesseis": 16,
            "dezessete": 17, "dezoito": 18, "dezenove": 19,
            "vinte": 20, "trinta": 30, "quarenta": 40,
            "cinquenta": 50, "sessenta": 60, "setenta": 70,
            "oitenta": 80, "noventa": 90, "cem": 100,
        }

        if clean in direct:
            return direct[clean]

        tokens = [t for t in clean.split() if t != "e"]
        if len(tokens) == 2 and tokens[0] in direct and tokens[1] in direct:
            tens = direct[tokens[0]]
            unit = direct[tokens[1]]
            if tens in (20,30,40,50,60,70,80,90) and 0 <= unit <= 9:
                return tens + unit

        return None

    def _normalize_local_command(self, message: str) -> str:
        """Normalização compartilhada entre voz e roteador local."""
        try:
            return normalize_local_intent(message)
        except Exception:
            return " ".join(str(message or "").split()).strip()

    def _analyze_network_local(self) -> str:
        """Resumo rápido da rede sem inventar dados e sem depender de API web."""
        lines = []

        try:
            host = socket.gethostname()
            lines.append(f"Computador: {host}")
        except Exception:
            pass

        try:
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.settimeout(0.8)
            udp.connect(("8.8.8.8", 80))
            local_ip = udp.getsockname()[0]
            udp.close()
            lines.append(f"IPv4 local: {local_ip}")
        except Exception:
            local_ip = ""

        active_interfaces = []
        if psutil:
            try:
                stats = psutil.net_if_stats()
                addrs = psutil.net_if_addrs()
                for name, stat in stats.items():
                    if not stat.isup:
                        continue
                    ipv4s = []
                    for addr in addrs.get(name, []):
                        if getattr(addr.family, "name", "") == "AF_INET" or str(addr.family) == "2":
                            if addr.address and not addr.address.startswith("127."):
                                ipv4s.append(addr.address)
                    if ipv4s:
                        active_interfaces.append(f"{name} ({', '.join(ipv4s)})")
            except Exception:
                pass

        if active_interfaces:
            lines.append("Adaptadores ativos: " + "; ".join(active_interfaces[:4]))

        internet_ok = False
        latency_ms = None
        try:
            start = time.perf_counter()
            conn = socket.create_connection(("1.1.1.1", 53), timeout=1.4)
            latency_ms = (time.perf_counter() - start) * 1000.0
            conn.close()
            internet_ok = True
        except Exception:
            internet_ok = False

        lines.append(
            "Internet: " + ("conectada" if internet_ok else "sem resposta no teste rápido")
        )
        if latency_ms is not None:
            lines.append(f"Latência de conexão TCP: ~{latency_ms:.0f} ms")

        try:
            socket.gethostbyname("google.com")
            lines.append("DNS: respondendo")
        except Exception:
            lines.append("DNS: não respondeu ao teste")

        if psutil:
            try:
                counters = psutil.net_io_counters()
                lines.append(
                    f"Tráfego desde o boot: enviado {counters.bytes_sent / (1024**2):.1f} MB | "
                    f"recebido {counters.bytes_recv / (1024**2):.1f} MB"
                )
            except Exception:
                pass

        return "✓ Análise rápida da rede:\n" + "\n".join(f"- {line}" for line in lines)

    def _split_multi_actions(self, message: str) -> List[str]:
        """V6.3: divide listas reais de apps e acoes encadeadas."""
        original = " ".join(str(message or "").split()).strip()
        raw = self._normalize_local_command(message)

        explicit = re.split(
            r"\s+(?:e\s+depois|depois|e\s+entao|e\s+então|em\s+seguida)\s+",
            raw, flags=re.I,
        )
        if len(explicit) > 1:
            return [p.strip(" ,;") for p in explicit if p.strip(" ,;")]

        # Usa o texto original para preservar virgulas do Whisper/chat.
        listed_source = re.match(
            r"^(abra|abre|abrir|feche|fecha|fechar|minimize|minimiza|maximize|maximiza|restaure|restaura)\s+(.+)$",
            original, flags=re.I,
        )
        if listed_source:
            verb, tail = listed_source.group(1), listed_source.group(2)
            if "," in tail or ";" in tail:
                items = [x.strip(" ,;") for x in re.split(r"\s*[,;]\s*|\s+e\s+", tail, flags=re.I) if x.strip(" ,;")]
                if 2 <= len(items) <= 6 and all(1 <= len(x.split()) <= 5 for x in items):
                    return [self._normalize_local_command(f"{verb} {x}") for x in items]

        # Sem pontuacao, ainda cobre "abrir revo e explorer".
        listed = re.match(
            r"^(abra|abre|abrir|feche|fecha|fechar|minimize|minimiza|maximize|maximiza|restaure|restaura)\s+(.+)$",
            raw, flags=re.I,
        )
        if listed:
            verb, tail = listed.group(1), listed.group(2)
            items = [x.strip(" ,;") for x in re.split(r"\s+e\s+", tail, flags=re.I) if x.strip(" ,;")]
            if 2 <= len(items) <= 4 and all(1 <= len(x.split()) <= 5 for x in items):
                return [f"{verb} {x}" for x in items]

        parts = re.split(r"\s+e\s+", raw, flags=re.I)
        command_starts = (
            "abra", "abre", "abrir", "feche", "fecha", "fechar",
            "toque", "tocar", "coloca", "coloque", "colocar", "pause",
            "pausa", "continua", "aumente", "aumenta", "abaixe", "abaixa",
            "diminua", "diminui", "pesquise", "procure", "busque", "crie",
            "copie", "mova", "bloqueie", "mute", "minimize", "maximize",
        )
        if len(parts) > 1 and all(p.strip().lower().startswith(command_starts) for p in parts):
            return [p.strip(" ,;") for p in parts]
        return [raw]

    def _should_auto_search(self, message: str) -> bool:
        """Detecta perguntas dependentes de informação atual sem gastar busca em conhecimento estável."""
        m = message.lower().strip()
        local_now = (
            "programa aberto agora", "janela aberta agora", "janela ativa",
            "qual programa esta aberto", "qual programa está aberto",
            "qual janela esta aberta", "qual janela está aberta",
            "que horas sao", "que horas são", "quanto de ram", "quanto de cpu",
        )
        if any(x in m for x in local_now):
            return False
        explicit_web = (
            "pesquise na internet", "pesquisa na internet", "pesquisar na internet",
            "procure na internet", "procura na internet", "busque na internet",
            "pesquise na web", "procure na web", "busque na web", "pesquisa web",
            "pesquise online", "procure online", "busque online",
        )
        if any(m.startswith(prefix) for prefix in explicit_web):
            return True
        current_markers = (
            "hoje", "agora", "ontem", "amanhã", "esta semana", "esse mês", "este mês",
            "último", "ultima", "última", "mais recente", "atual", "atualmente",
            "notícias", "noticias", "novidades", "placar", "resultado do jogo", "quem ganhou",
            "preço", "preco", "cotação", "cotacao", "lançamento", "lancamento",
            "versão mais recente", "versao mais recente"
        )
        questionish = any(m.startswith(x) for x in ("quem ", "qual ", "quais ", "quanto ", "como está", "como esta", "tem ", "houve "))
        return any(marker in m for marker in current_markers) and (questionish or "?" in m or len(m.split()) > 2)

    def _start_jarvis_lightning(self):
        """Inicia o efeito elétrico do logotipo JARVIS."""
        if not self.JARVIS_LIGHTNING_ENABLED:
            return

        if not self.root or not self.jarvis_logo_canvas:
            return

        # Evita mais de um loop de animação ao reconstruir a interface.
        try:
            if self._jarvis_lightning_job:
                self.root.after_cancel(self._jarvis_lightning_job)
        except Exception:
            pass

        self._jarvis_lightning_job = self.root.after(
            120,
            self._animate_jarvis_lightning
        )

    def _make_lightning_points(
        self,
        start_x,
        start_y,
        end_x,
        end_y,
        segments=6,
        jitter=7
    ):
        """Cria uma linha quebrada com aparência de relâmpago."""
        points = [start_x, start_y]

        dx = end_x - start_x
        dy = end_y - start_y

        length = max(1.0, math.hypot(dx, dy))
        perp_x = -dy / length
        perp_y = dx / length

        for i in range(1, segments):
            t = i / segments
            base_x = start_x + dx * t
            base_y = start_y + dy * t

            # Menos tremor perto das pontas deixa o raio mais natural.
            envelope = math.sin(math.pi * t)
            offset = random.uniform(-jitter, jitter) * envelope

            points.extend([
                base_x + perp_x * offset,
                base_y + perp_y * offset
            ])

        points.extend([end_x, end_y])
        return points

    def _draw_lightning_bolt(
        self,
        start,
        end,
        color="#5EB2FF",
        width=2,
        branch=True
    ):
        """Desenha um raio principal e, às vezes, um pequeno galho."""
        if not self.jarvis_logo_canvas:
            return

        sx, sy = start
        ex, ey = end

        points = self._make_lightning_points(
            sx,
            sy,
            ex,
            ey,
            segments=random.randint(4, 7),
            jitter=random.randint(4, 8)
        )

        self.jarvis_logo_canvas.create_line(
            *points,
            fill=color,
            width=width,
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND,
            tags=("jarvis_lightning",)
        )

        # Pequeno brilho paralelo ao raio principal.
        if random.random() < 0.55:
            glow_points = self._make_lightning_points(
                sx,
                sy,
                ex,
                ey,
                segments=5,
                jitter=3
            )
            self.jarvis_logo_canvas.create_line(
                *glow_points,
                fill="#C9ECFF",
                width=1,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags=("jarvis_lightning",)
            )

        if branch and len(points) >= 8 and random.random() < 0.42:
            pair_count = len(points) // 2
            branch_index = random.randint(1, max(1, pair_count - 2)) * 2

            bx = points[branch_index]
            by = points[branch_index + 1]

            angle = random.uniform(-2.5, 2.5)
            distance = random.randint(10, 23)

            branch_end = (
                bx + math.cos(angle) * distance,
                by + math.sin(angle) * distance
            )

            branch_points = self._make_lightning_points(
                bx,
                by,
                branch_end[0],
                branch_end[1],
                segments=3,
                jitter=3
            )

            self.jarvis_logo_canvas.create_line(
                *branch_points,
                fill="#70BEFF",
                width=1,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags=("jarvis_lightning",)
            )

    def _animate_jarvis_lightning(self):
        """
        Atualiza os raios do JARVIS.

        O efeito usa poucos elementos e intervalos curtos para parecer elétrico,
        mas mantém períodos sem raio para não ficar visualmente cansativo.
        """
        try:
            if not self.root or not self.jarvis_logo_canvas:
                return

            if not self.jarvis_logo_canvas.winfo_exists():
                return

            if self._window_in_motion:
                self._jarvis_lightning_job = self.root.after(
                    220,
                    self._animate_jarvis_lightning
                )
                return

            self.jarvis_logo_canvas.delete("jarvis_lightning")
            self._jarvis_lightning_frame += 1

            # Âncoras aproximadas em volta da palavra JARVIS.
            anchors = [
                (24, 10),
                (45, 5),
                (75, 4),
                (108, 6),
                (132, 13),
                (24, 31),
                (47, 39),
                (78, 41),
                (108, 39),
                (132, 31),
            ]

            destinations = [
                (2, random.randint(5, 38)),
                (random.randint(12, 138), 0),
                (random.randint(12, 140), 44),
                (random.randint(146, 235), random.randint(5, 40)),
            ]

            # Alguns frames ficam quase limpos para o efeito "estalo".
            active = random.random() < self.JARVIS_LIGHTNING_INTENSITY

            if active:
                bolt_count = random.choice([1, 1, 2, 2, 3])

                for _ in range(bolt_count):
                    start = random.choice(anchors)
                    end = random.choice(destinations)

                    palette = random.choice([
                        (self.jarvis_status_color, 2),
                        ("#5EB2FF", 2),
                        ("#91D3FF", 1),
                        ("#D7F1FF", 1),
                    ])

                    self._draw_lightning_bolt(
                        start,
                        end,
                        color=palette[0],
                        width=palette[1],
                        branch=True
                    )

                # Pequenos pontos luminosos simulando faíscas.
                for _ in range(random.randint(0, 3)):
                    ax, ay = random.choice(anchors)
                    radius = random.choice([1, 1, 2])

                    self.jarvis_logo_canvas.create_oval(
                        ax - radius,
                        ay - radius,
                        ax + radius,
                        ay + radius,
                        fill="#BFE8FF",
                        outline="",
                        tags=("jarvis_lightning",)
                    )

            # Mantém o texto sempre acima dos raios.
            self.jarvis_logo_canvas.tag_raise("jarvis_text")

            # Pequena variação do sublinhado/glow.
            glow_colors = ["#16385F", "#1F4D7E", "#296AA5"]
            try:
                self.jarvis_logo_canvas.itemconfigure(
                    "jarvis_glow",
                    fill=glow_colors[self._jarvis_lightning_frame % len(glow_colors)]
                )
            except Exception:
                pass

            self._jarvis_lightning_job = self.root.after(
                self.JARVIS_LIGHTNING_INTERVAL_MS,
                self._animate_jarvis_lightning
            )

        except Exception as e:
            self.logger.warning(
                f"Efeito elétrico JARVIS desativado após erro: {e}",
                "GUI"
            )
            self._jarvis_lightning_job = None

    def _on_volume_slider_change(self, value):
        """Atualiza indicação e aplica volume com pequeno debounce."""
        if self._volume_ui_updating:
            return

        target = max(0, min(int(round(float(value))), 100))

        if self.volume_value_label:
            self.volume_value_label.configure(
                text=f"{target}%"
            )

        if self._volume_apply_job:
            try:
                self.root.after_cancel(self._volume_apply_job)
            except Exception:
                pass

        self._volume_apply_job = self.root.after(
            260,
            lambda v=target: self._apply_volume_from_slider(v)
        )

    def _apply_volume_from_slider(self, value):
        self._volume_apply_job = None

        def worker():
            try:
                result = self.actions.set_volume(str(value))

                # Slider é controle visual: não poluímos o chat a cada arrasto.
                self.logger.info(
                    f"Slider de volume: {result}",
                    "HARDWARE"
                )

                actual = self.actions.get_volume_percent()

                if actual is None:
                    actual = value

                self._post_context_ui_call(self._set_volume_ui, actual)

            except Exception as e:
                self.logger.error(
                    e,
                    "Erro no slider de volume",
                    "GUI"
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def _set_volume_ui(self, value):
        if value is None:
            return

        try:
            value = max(0, min(int(round(float(value))), 100))
        except Exception:
            return

        self._volume_ui_updating = True

        try:
            if self.volume_value_label:
                self.volume_value_label.configure(
                    text=f"{value}%"
                )

            if self.volume_slider:
                self.volume_slider.set(value)

        finally:
            self._volume_ui_updating = False

    def _rename_current_conversation(self):
        self._rename_conversation(self.active_conversation_id)

    def _open_memory_manager(self):
        """Mostra memórias persistentes e permite apagar individualmente."""
        try:
            if (
                self.memory_manager_window
                and self.memory_manager_window.winfo_exists()
            ):
                self.memory_manager_window.lift()
                return
        except Exception:
            pass

        win = ctk.CTkToplevel(self.root)
        self.memory_manager_window = win
        win.title(f"{PUBLIC_NAME} - Memórias")
        win.geometry("720x560")
        win.transient(self.root)

        header = ctk.CTkFrame(
            win,
            fg_color="#0E131B",
            corner_radius=14
        )
        header.pack(
            fill="x",
            padx=14,
            pady=(14, 8)
        )

        stats = self.memory_store.memory_stats()

        ctk.CTkLabel(
            header,
            text=f"MEMÓRIAS DO {PUBLIC_NAME}",
            font=ctk.CTkFont(
                family="Tahoma",
                size=17,
                weight="bold"
            ),
            text_color="#8E6BFF"
        ).pack(
            side="left",
            padx=14,
            pady=12
        )

        ctk.CTkLabel(
            header,
            text=f"{stats['memories']} memórias persistentes",
            font=ctk.CTkFont(
                family="Consolas",
                size=10
            ),
            text_color="#70839A"
        ).pack(
            side="right",
            padx=14
        )

        scroll = ctk.CTkScrollableFrame(
            win,
            fg_color="#090E15",
            corner_radius=14
        )
        scroll.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=8
        )

        def refresh():
            for child in scroll.winfo_children():
                child.destroy()

            items = self.memory_store.list_memories(
                limit=200
            )

            if not items:
                ctk.CTkLabel(
                    scroll,
                    text="Nenhuma memória persistente salva.",
                    text_color="#70839A"
                ).pack(pady=30)
                return

            for item in items:
                card = ctk.CTkFrame(
                    scroll,
                    fg_color="#222222",
                    corner_radius=12,
                    border_width=1,
                    border_color="#333333"
                )
                card.pack(
                    fill="x",
                    padx=4,
                    pady=5
                )

                ctk.CTkLabel(
                    card,
                    text=f"#{item['id']}",
                    width=44,
                    font=ctk.CTkFont(
                        family="Consolas",
                        size=10,
                        weight="bold"
                    ),
                    text_color="#8E6BFF"
                ).pack(
                    side="left",
                    padx=(10, 5),
                    pady=10
                )

                ctk.CTkLabel(
                    card,
                    text=item.get("content") or "",
                    wraplength=510,
                    justify="left",
                    anchor="w",
                    font=ctk.CTkFont(
                        family="Tahoma",
                        size=10
                    ),
                    text_color="#DCE6F1"
                ).pack(
                    side="left",
                    fill="x",
                    expand=True,
                    padx=5,
                    pady=10
                )

                ctk.CTkButton(
                    card,
                    text="APAGAR",
                    width=70,
                    height=28,
                    corner_radius=8,
                    fg_color="#321B22",
                    hover_color="#4A2530",
                    command=lambda mid=item["id"]: (
                        self.memory_store.delete_memory(mid),
                        refresh()
                    )
                ).pack(
                    side="right",
                    padx=10,
                    pady=10
                )

        refresh()

        footer = ctk.CTkFrame(
            win,
            fg_color="transparent"
        )
        footer.pack(
            fill="x",
            padx=14,
            pady=(0, 14)
        )

        ctk.CTkButton(
            footer,
            text="ATUALIZAR",
            command=refresh
        ).pack(side="left")

        ctk.CTkButton(
            footer,
            text="APAGAR TODAS",
            fg_color="#321B22",
            hover_color="#4A2530",
            command=lambda: self._clear_all_memories_ui(
                refresh
            )
        ).pack(side="right")

    def _clear_all_memories_ui(self, refresh_callback=None):
        if not messagebox.askyesno(
            PUBLIC_NAME,
            "Apagar todas as memórias persistentes? "
            "As conversas serão mantidas."
        ):
            return

        self.memory_store.clear_long_term_memories()

        if refresh_callback:
            refresh_callback()

    def _open_alias_manager(self):
        """Lista os nomes de aplicativos ensinados ao JARVIS."""
        try:
            if (
                self.alias_manager_window
                and self.alias_manager_window.winfo_exists()
            ):
                self.alias_manager_window.lift()
                return
        except Exception:
            pass

        win = ctk.CTkToplevel(self.root)
        self.alias_manager_window = win
        win.title(f"{PUBLIC_NAME} - Aliases de aplicativos")
        win.geometry("720x520")
        win.transient(self.root)

        ctk.CTkLabel(
            win,
            text="APLICATIVOS APRENDIDOS",
            font=ctk.CTkFont(
                family="Tahoma",
                size=17,
                weight="bold"
            ),
            text_color="#3C8DFF"
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 8)
        )

        scroll = ctk.CTkScrollableFrame(
            win,
            fg_color="#090E15",
            corner_radius=14
        )
        scroll.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 14)
        )

        def refresh():
            for child in scroll.winfo_children():
                child.destroy()

            aliases = self.actions.list_app_aliases()

            if not aliases:
                ctk.CTkLabel(
                    scroll,
                    text=(
                        "Nenhum alias ensinado ainda.\n"
                        "Use: ensine o aplicativo [nome]"
                    ),
                    text_color="#70839A"
                ).pack(pady=30)
                return

            for item in aliases:
                card = ctk.CTkFrame(
                    scroll,
                    fg_color="#222222",
                    corner_radius=12,
                    border_width=1,
                    border_color="#333333"
                )
                card.pack(
                    fill="x",
                    padx=4,
                    pady=5
                )

                info = (
                    f"{item['alias']}  →  "
                    f"{item['display_name']}\n"
                    f"{item['target']}"
                )

                ctk.CTkLabel(
                    card,
                    text=info,
                    wraplength=540,
                    justify="left",
                    anchor="w",
                    font=ctk.CTkFont(
                        family="Tahoma",
                        size=10
                    ),
                    text_color="#DCE6F1"
                ).pack(
                    side="left",
                    fill="x",
                    expand=True,
                    padx=12,
                    pady=10
                )

                ctk.CTkButton(
                    card,
                    text="ESQUECER",
                    width=82,
                    height=28,
                    corner_radius=8,
                    fg_color="#321B22",
                    hover_color="#4A2530",
                    command=lambda alias=item["alias"]: (
                        self.actions.forget_app_alias(alias),
                        refresh()
                    )
                ).pack(
                    side="right",
                    padx=10,
                    pady=10
                )

        refresh()

    def _collect_diagnostic_text(self):
        """Diagnóstico completo, incluindo módulos do modo avançado."""
        if self.diagnostics_manager:
            try:
                report = self.diagnostics_manager.run(
                    core=self.core,
                    memory_store=self.memory_store,
                    voice_engine=self.voice_engine,
                    desktop=self.desktop_integration,
                    windows=self.window_manager,
                    audio=self.audio_device_manager,
                    vision=self.vision_system,
                    actions=self.actions,
                    performance=self.performance_tracer,
                    context=v8_context_status,
                    media_context=self.media_context,
                    conditional_rules=self.conditional_rules,
                    behavior_memory=self.behavior_memory,
                )

                extras = [
                    "",
                    "=== ESTADO DA INTERFACE ===",
                    f"Conversa ativa: {self.active_conversation_id}",
                    f"Modo: {self.interaction_mode}",
                    (
                        "Esfera: "
                        + (
                            "ATIVA"
                            if self.voice_visual_mode
                            else "FECHADA"
                        )
                    ),
                    f"Estado visual: {'OCIOSO' if self._voice_visual_state == 'REPOUSO' else self._voice_visual_state}",
                    (
                        "Overlay: Qt/PySide6 ✓"
                        if (
                            self.qt_voice_overlay
                            and self.qt_voice_overlay.is_alive()
                        )
                        else "Overlay: fallback Tk/indisponível"
                    ),
                ]

                if self.operational_context:
                    try:
                        snap = self.operational_context.snapshot()
                        extras.extend([
                            "",
                            "=== CONTEXTO OPERACIONAL / AGENTE ===",
                            f"App: {snap.get('active_app') or '-'} | Site: {snap.get('active_site') or '-'} | Monitor: {snap.get('active_monitor') or '-'}",
                            f"Objetivo: {snap.get('current_goal') or '-'} | estado={snap.get('goal_status') or '-'} | progresso={snap.get('goal_progress', 0)}%",
                            f"Último download: {snap.get('last_download') or '-'}",
                            f"Autonomia: {snap.get('autonomy_level') or '-'} ({int(snap.get('autonomy_percent', 60))}%) | Presença: {snap.get('presence_level') or '-'} ({int(snap.get('presence_percent', 60))}%)",
                            f"Observer: {'ATIVO' if self.observer_engine and self.observer_engine.status().get('running') else 'INATIVO'}",
                        ])
                    except Exception:
                        pass

                if self.voice_engine:
                    try:
                        voice_status = (
                            self.voice_engine.status()
                        )

                        extras.extend([
                            (
                                "Passagens de reconhecimento: "
                                f"{voice_status.get('recognition_passes')}"
                            ),
                            (
                                "Consenso de voz: "
                                f"{voice_status.get('consensus_score')}"
                            ),
                            (
                                "Última transcrição: "
                                f"{voice_status.get('last_transcript') or '-'}"
                            ),
                            (
                                "Latência de voz: fala="
                                f"{voice_status.get('capture_ms') or '-'}ms | endpoint="
                                f"{voice_status.get('endpoint_ms') or '-'}ms | STT="
                                f"{voice_status.get('stt_ms') or '-'}ms | pós-fala="
                                f"{voice_status.get('post_speech_ms') or '-'}ms | até áudio="
                                f"{voice_status.get('tts_first_audio_ms') or '-'}ms"
                            ),
                            (
                                "Endpoint: "
                                f"{voice_status.get('endpoint_reason') or '-'} | Whisper="
                                f"{voice_status.get('whisper_model') or '-'}"
                            ),
                            (
                                "Microfone: ruído="
                                f"{voice_status.get('noise_percent', '-')}% | gate="
                                f"{voice_status.get('gate_percent', '-')}% | SNR="
                                f"{voice_status.get('snr_db', '-')} dB | "
                                f"{voice_status.get('mic_quality') or '-'}"
                            ),
                        ])
                    except Exception:
                        pass

                return (
                    report
                    + "\n"
                    + "\n".join(extras)
                )

            except Exception as e:
                self.logger.warning(
                    f"Diagnóstico avançado falhou: {e}",
                    "DIAGNOSTIC"
                )

        # Fallback mínimo.
        return (
            f"=== {PUBLIC_NAME} - DIAGNÓSTICO ===\n\n"
            f"Gemini: {'OK' if self.core and self.core.is_available() else 'ATENÇÃO'}\n"
            f"Memória: {'OK' if self.memory_store else 'ATENÇÃO'}\n"
            f"Voz: {'OK' if self.voice_engine else 'ATENÇÃO'}\n"
            f"Modo: {self.interaction_mode}"
        )

    def _open_diagnostic_panel(self):
        """Abre um painel simples com o estado dos principais módulos."""
        try:
            if (
                self.diagnostic_window
                and self.diagnostic_window.winfo_exists()
            ):
                self.diagnostic_window.destroy()
        except Exception:
            pass

        win = ctk.CTkToplevel(self.root)
        self.diagnostic_window = win
        win.title(f"{PUBLIC_NAME} - Diagnóstico")
        win.geometry("760x620")
        win.transient(self.root)

        ctk.CTkLabel(
            win,
            text="DIAGNÓSTICO",
            font=ctk.CTkFont(
                family="Tahoma",
                size=18,
                weight="bold"
            ),
            text_color="#31D47D"
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 8)
        )

        textbox = ctk.CTkTextbox(
            win,
            font=ctk.CTkFont(
                family="Consolas",
                size=11
            ),
            fg_color="#090E15",
            border_width=1,
            border_color="#333333"
        )
        textbox.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=8
        )

        def refresh():
            text = self._collect_diagnostic_text()
            textbox.configure(state="normal")
            textbox.delete("1.0", "end")
            textbox.insert("1.0", text)
            textbox.configure(state="disabled")

        refresh()

        buttons = ctk.CTkFrame(
            win,
            fg_color="transparent"
        )
        buttons.pack(
            fill="x",
            padx=14,
            pady=(0, 14)
        )

        ctk.CTkButton(
            buttons,
            text="ATUALIZAR",
            command=refresh
        ).pack(side="left")

        ctk.CTkButton(
            buttons,
            text="COPIAR",
            command=lambda: self._copy_to_clipboard(
                self._collect_diagnostic_text()
            )
        ).pack(side="right")

    def _shorten_local_response(
        self,
        message,
        is_user=False,
        is_system=False
    ):
        """
        Encurta somente respostas que têm formato típico de ação local.

        Respostas conversacionais longas do Gemini permanecem intactas.
        """
        text = str(message or "").strip()

        if is_user or is_system or not text:
            return text

        # Remove vocativo repetitivo em respostas de ação.
        local_markers = (
            "abrindo ",
            "reproduzindo ",
            "volume ",
            "play/pause",
            "próxima faixa",
            "faixa anterior",
            "mídia ",
            "youtube aberto",
            "opera gx aberto",
            "aprendi.",
            "esqueci ",
            "cache ",
        )

        lower = text.lower()

        if not any(marker in lower for marker in local_markers):
            return text

        text = re.sub(
            r",?\s*senhor[.!]?$",
            ".",
            text,
            flags=re.I
        )

        m = re.search(
            r"volume(?: do windows)? (?:ajustado para (?:aproximadamente )?|ajustado e verificado em )(\d+)%",
            text,
            flags=re.I
        )

        if m:
            return f"✓ Volume em {m.group(1)}%."

        if "play/pause enviado" in lower:
            return "✓ Play/pause."

        if "próxima faixa" in lower and "enviado" in lower:
            return "✓ Próxima faixa."

        if "faixa anterior" in lower and "enviado" in lower:
            return "✓ Faixa anterior."

        if lower.startswith("abrindo "):
            return "✓ " + text

        if lower.startswith("reproduzindo "):
            return "♪ " + text

        return text

    def _start_system_metrics_updater(self):
        """Atualiza CPU, RAM e tráfego de rede sem bloquear a interface."""
        def tick():
            try:
                if self._window_in_motion:
                    return
                try:
                    if not self.root.winfo_viewable():
                        return
                except Exception:
                    pass

                if psutil is not None:
                    cpu = psutil.cpu_percent(interval=None)
                    ram = psutil.virtual_memory().percent
                    net = psutil.net_io_counters()
                    now = time.time()
                    total = net.bytes_sent + net.bytes_recv

                    if self.cpu_gauge:
                        self.cpu_gauge.update_value(float(cpu) / 100.0, f"{cpu:.0f}%")
                    if self.ram_gauge:
                        self.ram_gauge.update_value(float(ram) / 100.0, f"{ram:.0f}%")

                    if self.last_network_total is not None and self.last_network_time:
                        elapsed = max(now - self.last_network_time, 0.1)
                        speed = max(total - self.last_network_total, 0) / elapsed
                        if speed >= 1024 * 1024:
                            net_text = f"{speed / (1024*1024):.1f}M"
                        elif speed >= 1024:
                            net_text = f"{speed / 1024:.0f}K"
                        else:
                            net_text = "ON"
                        if self.network_gauge:
                            self.network_gauge.update_value(max(0.0, min(speed / (5 * 1024 * 1024), 1.0)), net_text)

                    self.last_network_total = total
                    self.last_network_time = now

                    if self.active_app_label:
                        title = foreground_window_title()
                        if title:
                            if len(title) > 28:
                                title = title[:25] + "..."
                            self.active_app_label.configure(text=f"Ativo  •  {title}")
                    self._update_orb_context_mode()
                else:
                    if self.network_gauge:
                        self.network_gauge.update_value(0.15, "ON")
            except Exception:
                pass
            finally:
                try:
                    self.root.after(1000, tick)
                except Exception:
                    pass

        self.root.after(500, tick)

    def _toggle_monitor(self):
        """Abre o log em janela própria para manter a lateral limpa."""
        try:
            win = ctk.CTkToplevel(self.root)
            win.title("JARVIS - Logs")
            win.geometry("760x430")
            win.configure(fg_color="#15171B")
            box = ctk.CTkTextbox(
                win, font=ctk.CTkFont(family="Consolas", size=10), text_color="#8CE5AE",
                fg_color="#090C10", border_width=1, border_color="#343840", wrap="word"
            )
            box.pack(fill="both", expand=True, padx=10, pady=10)
            text = ""
            try:
                text = "\n".join(str(log) for log in self.logger.get_buffer_logs(80))
            except Exception:
                pass
            box.insert("1.0", text or "Nenhum log carregado nesta sessão.")
            box.configure(state="disabled")
        except Exception as exc:
            self._quick_feedback(f"Não consegui abrir os logs: {exc}")

    def _clear_system_logs(self):
        """Limpa os logs do sistema"""
        self.logger.clear_buffer()
        self.system_log_text.configure(state="normal")
        self.system_log_text.delete("1.0", "end")
        self.system_log_text.configure(state="disabled")
        self.logger.system("Logs do sistema limpos", "GUI")
    
    def _start_log_updater(self):
        """Atualiza logs somente na thread do Tk; evita travamentos e TclError."""
        if not self.root:
            return

        if self._log_update_job:
            return

        def tick():
            self._log_update_job = None

            try:
                if (
                    self.monitor_visible
                    and not self.typing_active
                    and self.system_log_text
                    and self.system_log_text.winfo_exists()
                ):
                    logs = self.logger.get_buffer_logs(24)
                    content = "\n".join(str(log) for log in logs)

                    self.system_log_text.configure(state="normal")
                    self.system_log_text.delete("1.0", "end")
                    if content:
                        self.system_log_text.insert("1.0", content + "\n")
                    self.system_log_text.see("end")
                    self.system_log_text.configure(state="disabled")

            except Exception as e:
                # Não chama logger.error repetidamente a cada segundo, evitando
                # uma cascata de logs causada pelo próprio painel de logs.
                try:
                    print(f"[JARVIS][GUI] Atualizador de logs: {e}")
                except Exception:
                    pass

            finally:
                if self.root:
                    try:
                        self._log_update_job = self.root.after(1200, tick)
                    except Exception:
                        self._log_update_job = None

        self._log_update_job = self.root.after(700, tick)

    def _cancel_history_restore(self, clear_deferred: bool = True):
        """Cancela uma restauração visual sem deixar callbacks antigos escreverem no chat."""
        self._history_restore_generation += 1
        job = self._history_restore_job
        self._history_restore_job = None
        if job is not None and self.root:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._history_restore_active = False
        self._restoring_history = False
        if clear_deferred:
            self._deferred_visual_messages.clear()
        self._set_composer_enabled(True)

    def _restore_or_welcome(self):
        """Restaura a conversa em lotes para nunca congelar a thread Tk."""
        self._cancel_history_restore(clear_deferred=True)
        conversation_id = int(self.active_conversation_id)
        try:
            saved_messages = list(self.memory_store.load_messages(conversation_id, limit=120) or [])
        except Exception as e:
            self.logger.error(e, "Erro ao carregar conversa persistente", "MEMORY")
            self._show_welcome_message()
            return

        if not saved_messages:
            self.chat_history = []
            self._show_welcome_message()
            return

        records = []
        for item in saved_messages:
            records.append({
                "sender": item["sender"],
                "message": item["message"],
                "timestamp": item.get("timestamp", time.time()),
                "is_user": item.get("is_user", False),
                "is_jarvis": item.get("is_jarvis", False),
                "is_system": item.get("is_system", False),
            })
        self.chat_history = records

        self._history_restore_generation += 1
        generation = self._history_restore_generation
        self._history_restore_active = True
        self._set_composer_enabled(False)
        self._update_status("CARREGANDO CONVERSA", "#8A78FF")
        batch_size = 10

        def render_batch(index=0):
            self._history_restore_job = None
            if (
                generation != self._history_restore_generation
                or conversation_id != int(self.active_conversation_id)
                or not self._history_restore_active
            ):
                return

            end = min(len(saved_messages), index + batch_size)
            for item in saved_messages[index:end]:
                self._create_chat_bubble(
                    item["sender"],
                    item["message"],
                    is_user=item.get("is_user", False),
                    is_jarvis=item.get("is_jarvis", False),
                    is_system=item.get("is_system", False),
                    timestamp=item.get("timestamp"),
                    suppress_autoscroll=True,
                )

            if end < len(saved_messages):
                self._history_restore_job = self.root.after(1, lambda: render_batch(end))
                return

            self._history_restore_active = False
            self._set_composer_enabled(True)

            # Mensagens que chegaram de watchers/voz durante a restauração já
            # foram persistidas; agora apenas criamos os widgets na ordem correta.
            deferred = list(self._deferred_visual_messages)
            self._deferred_visual_messages.clear()
            for (
                msg_conversation_id, sender, message, is_user,
                is_jarvis, is_system, message_timestamp
            ) in deferred:
                if int(msg_conversation_id) != conversation_id:
                    continue
                self._create_chat_bubble(
                    sender, message,
                    is_user=is_user,
                    is_jarvis=is_jarvis,
                    is_system=is_system,
                    timestamp=message_timestamp,
                    suppress_autoscroll=True,
                )

            self._schedule_chat_scroll(force=True, delay=24)
            self.root.after(80, self._refresh_conversation_list)
            if not self.is_processing:
                self._update_status("ONLINE", Config.get_color("success"))

            try:
                title = self.memory_store.get_conversation_title(conversation_id)
                self.logger.info(
                    f"Conversa restaurada: {title} ({len(saved_messages)} mensagens)",
                    "MEMORY",
                )
            except Exception:
                pass

        self._history_restore_job = self.root.after(1, render_batch)

    def _clear_chat_widgets(self):
        """Limpa somente os widgets visuais da conversa."""
        self._chat_auto_scroll = True
        try:
            if self.chat_scroll:
                for child in self.chat_scroll.winfo_children():
                    child.destroy()
        except Exception as e:
            self.logger.error(e, "Erro ao limpar chat visual", "GUI")

    def _new_conversation(self):
        """
        Cria uma nova sessão sem apagar conversas antigas.
        As memórias relevantes continuam podendo ser recuperadas.
        """
        if self.is_processing:
            messagebox.showinfo(
                PUBLIC_NAME,
                "Aguarde a resposta atual terminar antes de criar outra conversa."
            )
            return

        try:
            self._cancel_history_restore(clear_deferred=True)
            self._invalidate_active_work()
            self._clear_stream_chunk_queue()
            self._discard_streaming_visual()
            self.active_conversation_id = (
                self.memory_store.create_conversation()
            )

            self.chat_history = []
            self.streaming_label = None
            self.streaming_buffer = ""
            self._cancel_stream_render_job()
            self._clear_chat_widgets()

            self._show_welcome_message()
            self._refresh_conversation_list()

            self.logger.info(
                f"Nova conversa criada: {self.active_conversation_id}",
                "MEMORY"
            )

        except Exception as e:
            self.logger.error(e, "Erro ao criar nova conversa", "MEMORY")

    def _show_welcome_message(self):
        """Exibe uma apresentação curta do JARVIS."""
        welcome_msg = (
            f"{PUBLIC_NAME} {JARVIS_VERSION} inicializado. Posso abrir aplicativos, pesquisar, controlar mídia "
            "e conversar com você. O botão ◉ abre o modo de voz visual."
        )
        self.add_message(PUBLIC_NAME, welcome_msg, is_jarvis=True)

    def send_message(self, event=None):
        """Envia mensagem digitada.

        13.12.1: uma nova mensagem de texto nunca e descartada so porque um
        turno remoto anterior ainda esta processando. O novo turno preempta o
        antigo visualmente; o Core cancela/renova a geracao remota ao iniciar.
        """
        message = self._composer_text().replace("\x00", "").strip()
        if not message:
            return "break" if event is not None else None
        if len(message) > self.COMPOSER_MAX_CHARS:
            messagebox.showinfo(
                PUBLIC_NAME,
                f"Essa mensagem tem {len(message):,} caracteres. O limite desta interface é {self.COMPOSER_MAX_CHARS:,} por envio.",
                parent=self.root,
            )
            return "break" if event is not None else None

        # Texto novo é um Priority Interrupt também para áudio já enfileirado.
        # Sem isso a resposta anterior podia continuar falando por cima do novo turno.
        try:
            if self.voice_engine:
                self.voice_engine.stop_speaking(clear_queue=True)
                self.voice_engine.set_assistant_busy(False)
        except Exception:
            pass
        self._clear_stream_chunk_queue()

        if self.is_processing:
            self._invalidate_active_work()
            self.is_processing = False
            try:
                cancel = getattr(self.core, "cancel_active_response", None)
                if callable(cancel):
                    cancel("novo texto do usuário")
            except Exception:
                pass
            try:
                if self.goal_executor:
                    self.goal_executor.cancel()
            except Exception:
                pass
            self._discard_streaming_visual()
            try:
                self.logger.info("Novo texto preemptou o turno anterior.", "CHAT")
            except Exception:
                pass

        # Limpa campo, devolve foco ao composer e atualiza status.
        self._clear_composer()
        try:
            self.text_input.focus_set()
        except Exception:
            pass
        self._update_status("PROCESSANDO", "#F5B942")

        # Adiciona mensagem do usuário
        self.add_message("Você", message, is_user=True)

        # Processa mensagem com origem explicita.
        self._process_message(message, source="text")
        return "break" if event is not None else None
    
    @staticmethod
    def _v8_text_failed(text: str) -> bool:
        key = JarvisGUI._local_strip_accents(str(text or "")).lower()
        failures = (
            "nao encontrei", "nao consegui", "nao existe", "indisponivel",
            "falhou", "erro", "invalido", "nao confirmou", "nao consegui confirmar",
            "qual aplicativo", "qual nome",
        )
        return any(token in key for token in failures)

    def _v8_verify_window_target(self, target: str, timeout: float = 1.6) -> bool:
        if not target or not self.window_manager:
            return False
        deadline = time.monotonic() + max(0.15, float(timeout))
        while time.monotonic() < deadline:
            try:
                if self.window_manager.find_window(target, min_score=0.60):
                    return True
            except Exception:
                return False
            time.sleep(0.08)
        return False

    def _v8_window_snapshot(self, target: str) -> dict:
        if not target or not self.window_manager:
            return {}
        try:
            inspect = getattr(self.window_manager, "inspect_window", None)
            if callable(inspect):
                return dict(inspect(target) or {})
            item = self.window_manager.find_window(target, min_score=0.60)
            return dict(item or {})
        except Exception:
            return {}

    def _v8_open_windows_summary(self) -> tuple[str, bool]:
        """Lista apps com janela real visível, em vez de responder só a janela ativa."""
        if not self.window_manager:
            return "Controle de janelas não carregado.", False
        try:
            apps = list(self.window_manager.list_open_applications() or [])
        except Exception:
            return "Não consegui listar os programas abertos agora.", False
        if not apps:
            return "Não encontrei programas com janela visível agora.", False

        names = []
        for row in apps:
            label = str(row.get("name") or "").strip()
            if not label:
                continue
            count = int(row.get("window_count") or 0)
            suffix = f" ({count} janelas)" if count > 1 else ""
            marker = " [ativo]" if bool(row.get("active")) else ""
            names.append(f"{label}{suffix}{marker}")
        if not names:
            return "Não encontrei programas com janela visível agora.", False
        return f"Programas com janela visível ({len(names)}): " + "; ".join(names) + ".", True

    def _take_screenshot_local(self, monitor_index=None):
        """Captura screenshot respeitando o mapa real de monitores da visão."""
        if monitor_index and self.vision_system:
            try:
                shot = self.vision_system.capture(monitor_index=int(monitor_index), save=False)
                capturas_dir = Path(os.getcwd()) / "capturas"
                capturas_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = capturas_dir / f"captura_monitor_{int(monitor_index)}_{stamp}.jpg"
                path.write_bytes(shot["bytes"])
                return f"📸 Screenshot do monitor {int(monitor_index)} salvo em: {path}"
            except Exception as exc:
                self.logger.warning(f"Captura via VisionSystem falhou; tentando MSS: {exc}", "VISION")
        return self.actions.take_screenshot(monitor_index=monitor_index)

    def _remember_media_target(self, target: str, ttl: float = 240.0):
        target = " ".join(str(target or "").split()).strip().lower()
        if not target:
            return
        try:
            if self.media_context is not None:
                target = self.media_context.set_preferred_target(target, ttl=ttl) or target
        except Exception:
            pass
        self._preferred_media_target = target
        self._preferred_media_target_until = time.monotonic() + max(10.0, float(ttl))

    def _current_media_target(self):
        try:
            if self.media_context is not None:
                target = self.media_context.preferred_target()
                if target:
                    return target
        except Exception:
            pass
        target = str(getattr(self, "_preferred_media_target", "") or "").strip()
        until = float(getattr(self, "_preferred_media_target_until", 0.0) or 0.0)
        if target and time.monotonic() <= until:
            return target
        self._preferred_media_target = ""
        self._preferred_media_target_until = 0.0
        return None

    def _execute_v8_command_result(self, command: str) -> dict:
        """Executa um passo V8 e devolve resultado verificável para o planner."""
        command = " ".join(str(command or "").split()).strip()
        outcome = {"handled": True, "success": True, "verified": True, "message": ""}
        self._set_source_badge("LOCAL")

        if command.startswith("v8:mode:"):
            mode_key = command.split(":", 2)[2].strip().lower()
            mode_map = {"conversation": "conversa", "auto": "auto", "command": "comando"}
            selected = mode_map.get(mode_key)
            if selected is None:
                msg = "Modo desconhecido."
                self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
                outcome.update(message=msg, success=False, verified=False)
                return outcome
            self.interaction_mode = selected
            continuous = selected == "conversa"
            try:
                if self.voice_engine:
                    self.voice_engine.set_conversation_mode(continuous)
            except Exception as exc:
                self.logger.warning(f"Falha ao alternar modo conversa contínua: {exc}", "VOICE")
            self._sync_conversation_overlay_lock(continuous)
            if continuous:
                try:
                    if self.root and not self.voice_visual_mode:
                        self._post_ui_call(self._open_voice_overlay)
                except Exception:
                    pass
                msg = f"Modo conversa ativado. Pode falar sem repetir '{PUBLIC_NAME.title()}'."
            elif selected == "comando":
                msg = f"Modo comando ativado. Diga '{PUBLIC_NAME.title()}' a cada turno."
            else:
                msg = f"Modo automático ativado. Diga '{PUBLIC_NAME.title()}' a cada turno."
            if self.operational_context:
                try: self.operational_context.set_mode(selected)
                except Exception: pass
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command == "v8:media:status":
            try:
                if self.media_context is None:
                    raise RuntimeError("contexto de mídia indisponível")
                media = self.media_context.refresh(force=True).to_dict()
                v8_remember_media(media)
                msg = self.media_context.describe()
                ok = bool(media.get("service"))
            except Exception as exc:
                msg, ok = f"Não consegui identificar a mídia atual: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:rules:add:"):
            try:
                from urllib.parse import unquote
                payload = command.split(":", 3)[3]
                data = json.loads(unquote(payload))
                if self.conditional_rules is None:
                    raise RuntimeError("motor de regras indisponível")
                row = self.conditional_rules.add(
                    data.get("trigger_kind", ""), data.get("match", ""), data.get("action", ""),
                    label=data.get("label", ""), cooldown=float(data.get("cooldown", 30.0)),
                    condition=data.get("condition") or None,
                )
                msg = f"✓ Regra #{row['id']} criada: {row['label']}."
                ok = True
            except Exception as exc:
                msg, ok = f"Não criei essa regra: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:rules:list":
            try:
                rows = self.conditional_rules.list() if self.conditional_rules else []
                if not rows:
                    msg = "Você ainda não tem regras condicionais salvas."
                else:
                    lines = ["Regras condicionais:"]
                    for row in rows[:20]:
                        state = "ON" if row.get("enabled", True) else "OFF"
                        cond = row.get("condition") or {}
                        cond_text = f" · {cond.get('field')} {cond.get('op')} {cond.get('value')}%" if cond else ""
                        lines.append(f"• #{row.get('id')} [{state}] {row.get('label')} → {row.get('action')} ({row.get('fires', 0)} execuções){cond_text}")
                    msg = "\n".join(lines)
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui listar as regras: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:rules:delete:"):
            try:
                rid = int(command.rsplit(":", 1)[1])
                ok = bool(self.conditional_rules and self.conditional_rules.remove(rid))
                msg = f"✓ Regra #{rid} removida." if ok else f"Não encontrei a regra #{rid}."
            except Exception as exc:
                msg, ok = f"Não consegui remover a regra: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:rules:enable:") or command.startswith("v8:rules:disable:"):
            try:
                enabled = command.startswith("v8:rules:enable:")
                rid = int(command.rsplit(":", 1)[1])
                ok = bool(self.conditional_rules and self.conditional_rules.set_enabled(rid, enabled))
                state = "ativada" if enabled else "desativada"
                msg = f"✓ Regra #{rid} {state}." if ok else f"Não encontrei a regra #{rid}."
            except Exception as exc:
                msg, ok = f"Não consegui alterar a regra: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:rules:promote_last":
            candidate = dict(getattr(self, "_last_rule_candidate", None) or {})
            try:
                if not candidate:
                    raise RuntimeError("não há uma ação contextual recente que eu possa transformar em regra")
                if candidate.get("kind") == "player_auto":
                    service = str(candidate.get("service") or "").lower()
                    action = str(candidate.get("action") or "")
                    if not self.operational_context:
                        raise RuntimeError("contexto operacional indisponível")
                    self.operational_context.set_player_automation(action, True, service=service)
                    label = "pular abertura" if action == "skip" else "próximo episódio"
                    msg = f"✓ Certo. Vou {label} automaticamente" + (f" no {service}." if service else ".")
                    ok = True
                else:
                    raise RuntimeError("essa ação ainda não suporta modo permanente")
            except Exception as exc:
                msg, ok = f"Não consegui tornar isso permanente: {exc}.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:media_target:"):
            target = command.split(":", 2)[2].strip().lower()
            self._remember_media_target(target)
            label = "Spotify" if target == "spotify" else target.upper() if target == "vlc" else target
            msg = f"Certo. Os próximos comandos de mídia vão para o {label}."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command.startswith("v8:media:"):
            payload = command.split(":", 2)[2]
            action, _, target = payload.partition("|")
            target = target.strip().lower() or self._current_media_target() or ""
            if target:
                self._remember_media_target(target)
            try:
                if self.media_context is not None:
                    result = self.media_context.control(action.strip().lower(), target_hint=target)
                    msg = str(result.get("message") or "Comando de mídia enviado.")
                    ok = bool(result.get("success"))
                    verified = bool(result.get("verified"))
                    try:
                        v8_remember_media(result.get("after") or self.media_context.current())
                    except Exception:
                        pass
                else:
                    handlers = {
                        "pause": self.actions.media_pause, "play": self.actions.media_play,
                        "toggle": self.actions.media_play_pause, "next": self.actions.media_next_track,
                        "previous": self.actions.media_previous_track, "stop": self.actions.media_stop,
                    }
                    fn = handlers.get(action.strip().lower())
                    if not fn:
                        raise RuntimeError("comando de mídia desconhecido")
                    msg = fn(target_hint=target or None)
                    ok = not self._v8_text_failed(msg)
                    verified = False
            except Exception as exc:
                msg, ok, verified = f"Não consegui controlar a mídia: {exc}", False, False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=verified)
            return outcome

        if command.startswith("v8:player:"):
            payload, _, service_hint = command.partition("|")
            parts = payload.split(":")
            action = parts[2].strip().lower() if len(parts) > 2 else ""
            seconds = 0
            monitor = 0
            try:
                if action == "seek":
                    seconds = int(parts[3]) if len(parts) > 3 else 0
                    monitor = int(parts[4]) if len(parts) > 4 else 0
                else:
                    monitor = int(parts[3]) if len(parts) > 3 else 0
            except Exception:
                monitor = 0
            try:
                if not self.browser_autonomy:
                    raise RuntimeError("controle de streaming indisponível")
                result = self.browser_autonomy.streaming_control(
                    action, seconds=seconds, monitor_index=(monitor or None), service_hint=service_hint
                )
            except Exception as exc:
                result = {"success": False, "verified": False, "message": f"Não consegui controlar o streaming: {exc}"}
            msg = str(result.get("message") or "Ação no player finalizada.")
            ok = bool(result.get("success"))
            if ok and action in {"skip", "skip_intro", "next"}:
                try:
                    service_now = str((self.media_context.refresh(force=True).service if self.media_context else service_hint) or "").lower()
                except Exception:
                    service_now = str(service_hint or "").lower()
                self._last_rule_candidate = {"kind": "player_auto", "action": "skip" if action in {"skip", "skip_intro"} else "next", "service": service_now}
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=bool(result.get("verified", False)))
            return outcome

        if command.startswith("v8:crunchy:"):
            parts = command.split(":")
            action = parts[2].strip().lower() if len(parts) > 2 else ""
            try:
                monitor = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            except Exception:
                monitor = 0
            monitor_index = monitor or None
            try:
                if not self.browser_autonomy:
                    raise RuntimeError("controle do navegador indisponível")
                if action == "skip":
                    # Caminho comum: se a aba ja esta identificada como Crunchyroll,
                    # o atalho oficial e muito mais rapido que abrir visao/screenshot.
                    result = self.browser_autonomy.streaming_control("skip_intro", monitor_index=monitor_index)
                elif action == "next":
                    # Verificacao curta: a acao acontece imediatamente; nao segure
                    # a resposta por ate 3.5 s esperando o titulo da aba.
                    result = self.browser_autonomy.streaming_control("next", monitor_index=monitor_index)
                elif action == "seek":
                    try:
                        seconds = int(parts[3]) if len(parts) > 3 else 0
                    except Exception:
                        seconds = 0
                    try:
                        monitor = int(parts[4]) if len(parts) > 4 and str(parts[4]).lstrip("-").isdigit() else 0
                    except Exception:
                        monitor = 0
                    if monitor:
                        result = {"success": False, "verified": False, "message": "Avanco por monitor especifico ainda nao esta disponivel."}
                    else:
                        result = self.browser_autonomy.streaming_control("seek", seconds=seconds)
                else:
                    result = {"success": False, "verified": False, "message": "Controle do player desconhecido."}
            except Exception as exc:
                result = {"success": False, "verified": False, "message": f"Não consegui controlar o player: {exc}"}
            msg = str(result.get("message") or "Ação no player finalizada.")
            ok = bool(result.get("success"))
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=bool(result.get("verified", ok)))
            return outcome

        if command == "v8:gamer:on":
            # Reintroduz o Modo Gamer clássico do projeto usando somente
            # aberturas de app (ação reversível/não destrutiva).
            opened = []
            failed = []
            for app in ("Discord", "Opera", "Steam"):
                try:
                    raw = str(self.actions.open_application(app))
                    if not self._v8_text_failed(raw):
                        opened.append(app)
                    else:
                        failed.append(app)
                except Exception:
                    failed.append(app)
            if opened:
                msg = "✓ Modo gamer ativado. Abri " + ", ".join(opened) + "."
                if failed:
                    msg += " Não encontrei: " + ", ".join(failed) + "."
                ok = True
            else:
                msg, ok = "Não consegui abrir os aplicativos do modo gamer.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=False)
            return outcome

        if command.startswith("v8:presence_percent:"):
            try:
                value = self._snap_behavior_percent(int(command.rsplit(":", 1)[1]))
                if not self.operational_context:
                    raise RuntimeError("contexto operacional indisponível")
                if hasattr(self.operational_context, "set_presence_percent"):
                    self.operational_context.set_presence_percent(value)
                self._presence_percent = value
                self._save_quick_preferences()
                msg = f"✓ Presença ajustada para {self._behavior_percent_label(value)} · {value}%."
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui alterar a presença: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            self._refresh_quick_panel_values()
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:autonomy_percent:"):
            try:
                value = self._snap_behavior_percent(int(command.rsplit(":", 1)[1]))
                if not self.operational_context:
                    raise RuntimeError("contexto operacional indisponível")
                if hasattr(self.operational_context, "set_autonomy_percent"):
                    self.operational_context.set_autonomy_percent(value)
                self._autonomy_percent = value
                self._save_quick_preferences()
                msg = f"✓ Autonomia ajustada para {self._behavior_percent_label(value)} · {value}%."
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui alterar a autonomia: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            self._refresh_quick_panel_values()
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:presence:"):
            level = command.split(":", 2)[2].strip().lower()
            try:
                if not self.operational_context:
                    raise RuntimeError("contexto operacional indisponível")
                self.operational_context.set_presence(level)
                msg = f"Presença do {PUBLIC_NAME} ajustada para {level}."
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui alterar o nível de presença: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            self._refresh_operational_ui()
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:autonomy:"):
            level = command.split(":", 2)[2].strip().lower()
            try:
                if not self.operational_context:
                    raise RuntimeError("contexto operacional indisponível")
                self.operational_context.set_autonomy(level)
                msg = f"✓ Autonomia ajustada para {level}."
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui alterar o nível de autonomia: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            self._refresh_operational_ui()
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:player_auto:"):
            parts = command.split(":")
            kind = parts[2].strip().lower() if len(parts) > 2 else ""
            value = parts[3].strip().lower() if len(parts) > 3 else "status"
            try:
                if not self.operational_context:
                    raise RuntimeError("contexto operacional indisponível")
                if kind == "status" or value == "status":
                    prefs = self.operational_context.player_automation()
                    msg = (
                        "Automação de streaming: "
                        f"pular abertura {'ligado' if prefs.get('skip_intro') else 'desligado'}; "
                        f"próximo episódio {'ligado' if prefs.get('next_episode') else 'desligado'}."
                    )
                else:
                    enabled = value == "on"
                    self.operational_context.set_player_automation(kind, enabled)
                    if kind == "skip":
                        msg = "Vou pular aberturas automaticamente em players compatíveis quando o botão correto estiver visível." if enabled else "Pulo automático de abertura desligado."
                    elif kind == "next":
                        msg = "Vou avançar para o próximo episódio automaticamente quando o botão correto estiver visível." if enabled else "Próximo episódio automático desligado."
                    else:
                        raise ValueError("automação desconhecida")
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui alterar a automação do player: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:fullscreen":
            self._set_source_badge("AGENTE")
            try:
                result = self.browser_autonomy.smart_fullscreen() if self.browser_autonomy else None
            except Exception as exc:
                self.logger.warning(f"Tela cheia contextual falhou: {exc}", "AGENT")
                result = None
            if result and result.get("success"):
                msg = str(result.get("message") or "Tela cheia alternada.")
                ok = True
                verified = bool(result.get("verified"))
            else:
                msg = str((result or {}).get("message") or "Não encontrei um alvo seguro para tela cheia.")
                ok = False
                verified = False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=verified)
            return outcome

        if command == "v8:smart_skip":
            self._set_source_badge("AGENTE")
            result = None
            try:
                if self.browser_autonomy:
                    result = self.browser_autonomy.smart_skip()
            except Exception as exc:
                self.logger.warning(f"Smart skip visual falhou: {exc}", "AGENT")
            if result and result.get("success"):
                msg = str(result.get("message") or "Controle de pulo enviado ao player.")
                ok = True
                verified = bool(result.get("verified"))
                try:
                    service_now = str((self.media_context.refresh(force=True).service if self.media_context else "") or "").lower()
                except Exception:
                    service_now = ""
                self._last_rule_candidate = {"kind": "player_auto", "action": "skip", "service": service_now}
            else:
                try:
                    msg = str(self.actions.media_next_track())
                    ok = not self._v8_text_failed(msg)
                except Exception as exc:
                    msg = f"Não consegui pular agora: {exc}"
                    ok = False
                verified = False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=verified)
            return outcome

        if command.startswith("v8:workflow:start:"):
            name = command.split(":", 3)[3].strip()
            msg = self.workflow_engine.start_recording(name) if self.workflow_engine else "Motor de rotinas indisponível."
            ok = str(msg).startswith("✓")
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:workflow:stop":
            msg = self.workflow_engine.stop_recording() if self.workflow_engine else "Motor de rotinas indisponível."
            ok = str(msg).startswith("✓")
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:workflow:list":
            items = self.workflow_engine.list_workflows() if self.workflow_engine else []
            if items:
                msg = "Rotinas: " + "; ".join(f"{x.get('name')} ({len(x.get('steps') or [])} passos)" for x in items) + "."
            else:
                msg = "Ainda não há rotinas aprendidas."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command.startswith("v8:workflow:delete:"):
            name = command.split(":", 3)[3].strip()
            ok = bool(self.workflow_engine and self.workflow_engine.delete(name))
            msg = f"✓ Rotina '{name}' esquecida." if ok else f"Não encontrei a rotina '{name}'."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:workflow:run:"):
            self._set_source_badge("AGENTE")
            name = command.split(":", 3)[3].strip()
            if not self.workflow_engine:
                result = {"success": False, "verified": False, "message": "Motor de rotinas indisponível."}
            else:
                result = self.workflow_engine.run(
                    name, self._execute_v8_command_result,
                    cancelled=lambda: bool(self.goal_executor and self.goal_executor.is_cancelled()),
                    progress=lambda data: self._post_context_ui_call(self._update_agent_hud, data),
                )
            msg = str(result.get("message") or "Rotina finalizada.")
            self._post_context_ui_call(self._finish_agent_hud, bool(result.get("success")), msg)
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=bool(result.get("success")), verified=bool(result.get("verified")))
            return outcome

        if command.startswith("v8:goal:"):
            self._set_source_badge("AGENTE")
            goal = command.split(":", 2)[2].strip()
            if not self.goal_executor:
                result = {"success": False, "verified": False, "message": f"{PUBLIC_NAME} Agent indisponível nesta sessão."}
            else:
                autonomy = "assistido"
                autonomy_percent = int(getattr(self, "_autonomy_percent", 60))
                presence_percent = int(getattr(self, "_presence_percent", 60))
                if self.operational_context:
                    snap = self.operational_context.snapshot()
                    autonomy = snap.get("autonomy_level", "assistido")
                    autonomy_percent = int(snap.get("autonomy_percent", autonomy_percent))
                    presence_percent = int(snap.get("presence_percent", presence_percent))
                result = self.goal_executor.execute(
                    goal,
                    progress=lambda data: self._post_context_ui_call(self._update_agent_hud, data),
                    autonomy_level=autonomy, autonomy_percent=autonomy_percent, presence_percent=presence_percent,
                )
            msg = str(result.get("message") or "Objetivo finalizado.")
            self._post_context_ui_call(self._finish_agent_hud, bool(result.get("success")), msg)
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=bool(result.get("success")), verified=bool(result.get("verified")))
            return outcome

        if command == "v8:interrupt":
            try:
                if self.goal_executor:
                    self.goal_executor.cancel()
            except Exception:
                pass
            self._invalidate_active_work()
            self._voice_command_active = False
            self.is_processing = False
            try:
                if self.voice_engine:
                    self.voice_engine.stop_speaking(clear_queue=True)
                    self.voice_engine.set_assistant_busy(False)
            except Exception:
                pass
            try:
                if self.root:
                    self._post_ui_call(self._update_status, "ONLINE", Config.get_color("success"))
            except Exception:
                pass
            outcome["message"] = "Interrompido."
            return outcome

        if command == "v8:operational_context":
            try:
                if not self.operational_context:
                    raise RuntimeError("contexto operacional indisponível")
                self.operational_context.refresh_from_windows()
                msg = self.operational_context.compact_text()
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui ler o contexto operacional: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:last_download":
            try:
                snap = self.operational_context.snapshot() if self.operational_context else {}
                last = str(snap.get("last_download") or "").strip()
                msg = f"Último download observado: {last}" if last else "Ainda não observei um download concluído nesta sessão."
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui consultar o último download: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:clipboard":
            try:
                value = str(self.root.clipboard_get() or "")
                clean = " ".join(value.split()).strip()
                if len(clean) > 1200:
                    clean = clean[:1200].rstrip() + "…"
                msg = f"Na área de transferência: {clean}" if clean else "A área de transferência está vazia ou não contém texto."
                ok = True
            except Exception:
                msg, ok = "A área de transferência está vazia ou não contém texto.", True
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=True)
            return outcome

        if command == "v8:social_chat":
            vocative = self._butler_vocative()
            msg = f"Tudo em ordem, {vocative}." if vocative else "Tudo em ordem."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command.startswith("v8:user_name:") and command not in {"v8:user_name:clear", "v8:user_name:status"}:
            raw_name = command.split(":", 2)[2].strip()
            name = self._set_session_user_name(raw_name)
            if name:
                msg = f"Entendido, senhor {name}."
                ok = True
            else:
                msg = "Não consegui identificar um nome com segurança. Diga, por exemplo: me chama de Bruno."
                ok = False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:user_name:clear":
            self._clear_session_user_name()
            msg = "Como preferir, senhor."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command == "v8:user_name:status":
            name = self._current_speaker_name()
            msg = f"O senhor é {name}. Vou manter esse nome mesmo se esta conversa for apagada." if name else "Ainda não tenho um nome preferido salvo para o senhor."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command == "v8:no_action:negated":
            msg = "Certo. Não vou executar essa ação."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command == "v8:positive_feedback":
            choices = [
                "Perfeito. Então ficou certo.",
                "Ótimo. Funcionou como deveria.",
                "Excelente. Vou considerar essa rota válida daqui pra frente.",
            ]
            msg = random.choice(choices)
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command == "v8:correction_feedback":
            msg = "Entendi. Registrei que a última ação não funcionou como esperado."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command == "v8:time":
            now = datetime.now()
            msg = f"São {now.strftime('%H:%M')}."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome["message"] = msg
            return outcome

        if command == "v8:date":
            now = datetime.now()
            weekdays = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
            months = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
            msg = f"Hoje é {weekdays[now.weekday()]}, {now.day} de {months[now.month - 1]} de {now.year}."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome["message"] = msg
            return outcome

        if command == "v8:ram":
            if psutil:
                m = psutil.virtual_memory()
                used = (m.total - m.available) / (1024**3)
                total = m.total / (1024**3)
                msg = f"RAM em uso: {used:.1f} de {total:.1f} GB ({m.percent:.0f}%)."
            else:
                msg = "Não consegui consultar a RAM agora."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=not self._v8_text_failed(msg), verified=bool(psutil))
            return outcome

        if command == "v8:cpu":
            if psutil:
                # O monitor da interface ja amostra CPU continuamente; uma nova
                # leitura nao-bloqueante evita adicionar 80 ms a um comando instantaneo.
                msg = f"CPU em uso: {psutil.cpu_percent(interval=None):.0f}%."
            else:
                msg = "Não consegui consultar a CPU agora."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=not self._v8_text_failed(msg), verified=bool(psutil))
            return outcome

        if command == "v8:disk":
            try:
                drive = (os.environ.get("SystemDrive") or "C:") + "\\"
                d = psutil.disk_usage(drive) if psutil else None
                if d:
                    free = d.free / (1024**3)
                    total = d.total / (1024**3)
                    msg = f"Disco {drive[:2]}: {d.percent:.0f}% usado; {free:.1f} GB livres de {total:.1f} GB."
                    ok = True
                else:
                    msg, ok = "Não consegui consultar o disco agora.", False
            except Exception:
                msg, ok = "Não consegui consultar o disco agora.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:network":
            try:
                stats = psutil.net_if_stats() if psutil else {}
                active = [name for name, st in stats.items() if getattr(st, "isup", False)]
                io = psutil.net_io_counters() if psutil else None
                if active:
                    detail = ""
                    if io:
                        detail = f" Recebidos {io.bytes_recv/(1024**2):.0f} MB e enviados {io.bytes_sent/(1024**2):.0f} MB desde a inicialização."
                    msg = f"Rede ativa: {len(active)} interface(s) online.{detail}"
                    ok = True
                else:
                    msg, ok = "Não detectei interface de rede ativa agora.", False
            except Exception:
                msg, ok = "Não consegui consultar a rede agora.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:battery":
            try:
                b = psutil.sensors_battery() if psutil and hasattr(psutil, "sensors_battery") else None
                if b is None:
                    msg, ok = "Este computador não reporta bateria ao Windows.", True
                else:
                    state = "carregando" if b.power_plugged else "na bateria"
                    msg, ok = f"Bateria: {b.percent:.0f}% ({state}).", True
            except Exception:
                msg, ok = "Não consegui consultar a bateria agora.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:pc_opinion":
            try:
                if not psutil:
                    raise RuntimeError("psutil indisponível")
                cpu = float(psutil.cpu_percent(interval=0.05))
                ram = psutil.virtual_memory()
                drive = (os.environ.get("SystemDrive") or "C:") + "\\"
                disk = psutil.disk_usage(drive)
                if cpu < 65 and ram.percent < 75 and disk.percent < 90:
                    lead = "Pelo uso agora, seu PC está tranquilo."
                elif cpu < 85 and ram.percent < 88 and disk.percent < 94:
                    lead = "Seu PC está trabalhando mais, mas nada parece crítico agora."
                else:
                    lead = "Seu PC está bem carregado agora; vale olhar o que está consumindo recursos."
                msg = (f"{lead} CPU {cpu:.0f}%, RAM {ram.percent:.0f}% "
                       f"e disco {disk.percent:.0f}% usado.")
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui avaliar o PC agora: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "status do pc":
            try:
                if not psutil:
                    raise RuntimeError("psutil indisponível")
                cpu = psutil.cpu_percent(interval=0.05)
                ram = psutil.virtual_memory()
                drive = (os.environ.get("SystemDrive") or "C:") + "\\"
                disk = psutil.disk_usage(drive)
                process_count = len(psutil.pids())
                parts = [
                    f"CPU {cpu:.0f}%",
                    f"RAM {ram.percent:.0f}% ({(ram.total-ram.available)/(1024**3):.1f}/{ram.total/(1024**3):.1f} GB)",
                    f"disco {disk.percent:.0f}% usado",
                    f"{process_count} processos ativos",
                ]
                temp_text = ""
                try:
                    sensors = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
                    readings = []
                    for group in (sensors or {}).values():
                        for entry in group or []:
                            value = getattr(entry, "current", None)
                            if value is not None and -20 <= float(value) <= 130:
                                readings.append(float(value))
                    if readings:
                        temp_text = f"; temperatura reportada {max(readings):.0f}°C"
                except Exception:
                    temp_text = ""
                msg = "Status local verificado: " + ", ".join(parts) + temp_text + "."
                if not temp_text:
                    msg += f" O Windows não expôs temperatura confiável ao {PUBLIC_NAME} nesta leitura."
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui montar o diagnóstico local agora: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:performance":
            try:
                summary = self.performance_tracer.summary(50) if self.performance_tracer else {}
                if summary.get("count"):
                    msg = (f"Latência das últimas {summary['count']} interações: "
                           f"p50 {summary.get('p50_ms')} ms, p95 {summary.get('p95_ms')} ms; "
                           f"local p50 {summary.get('local_p50_ms') or '-'} ms, "
                           f"Gemini p50 {summary.get('gemini_p50_ms') or '-'} ms.")
                    stages = summary.get("stages") or {}
                    ttfv = stages.get("voice_ttfv") or {}
                    endpoint = stages.get("voice_endpoint") or {}
                    if ttfv.get("p50_ms") is not None:
                        msg += (f" Voz: TTFV p50 {ttfv.get('p50_ms')} ms / p95 {ttfv.get('p95_ms')} ms; "
                                f"endpoint p50 {endpoint.get('p50_ms') or '-'} ms.")
                    try:
                        voice_status = self.voice_engine.status() if self.voice_engine else {}
                        if voice_status.get("end_of_speech_to_audio_ms") is not None:
                            msg += (f" Última voz: pós-fala {voice_status.get('post_speech_ms') or '-'} ms; "
                                    f"fim da fala até primeiro áudio {voice_status.get('end_of_speech_to_audio_ms')} ms.")
                    except Exception:
                        pass
                    ok = True
                else:
                    msg, ok = "Ainda não há amostras suficientes de latência nesta instalação.", True
            except Exception:
                msg, ok = "Não consegui consultar a telemetria de desempenho agora.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:active_window":
            try:
                title = self.window_manager.active_window_title() if self.window_manager else foreground_window_title()
            except Exception:
                title = foreground_window_title()
            msg = f"Janela ativa: {title or 'não identificada'}."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=bool(title), verified=bool(title))
            return outcome

        if command == "v8:open_windows":
            msg, ok = self._v8_open_windows_summary()
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        # V8 visão semântica preserva a pergunta original. Assim "me explica
        # a imagem da carne na tela 1" não vira uma descrição genérica da tela.
        if command.startswith("v8:vision:"):
            self._set_source_badge("VISÃO")
            payload = command.split(":", 2)[2]
            monitor_raw, sep, question = payload.partition("|")
            question = question.strip() if sep else "Descreva a tela atual."
            monitor_index = None if monitor_raw.strip().lower() == "active" else int(monitor_raw)
            if self.vision_system:
                prompt = question or (
                    f"Descreva somente o monitor {monitor_index}." if monitor_index else "Descreva minha tela atual."
                )
                msg = self.vision_system.analyze(prompt, monitor_index=monitor_index)
                ok = not self._v8_text_failed(msg)
            else:
                msg, ok = "Módulo de visão não carregado.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        # V8 visão: executa diretamente com o índice solicitado. O parser legado
        # não recebe mais "descreve monitor 2" sem o monitor_index.
        m = re.match(r"^descreve\s+monitor\s+(\d+)\s*$", command, flags=re.I)
        if m:
            monitor_index = int(m.group(1))
            if self.vision_system:
                msg = self.vision_system.analyze(
                    f"Descreva somente o monitor {monitor_index}.",
                    monitor_index=monitor_index,
                )
                ok = not self._v8_text_failed(msg)
            else:
                msg, ok = "Módulo de visão não carregado.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "descreve minha tela":
            if self.vision_system:
                msg = self.vision_system.analyze("Descreva minha tela atual.", monitor_index=None)
                ok = not self._v8_text_failed(msg)
            else:
                msg, ok = "Módulo de visão não carregado.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:screenshot" or command.startswith("v8:screenshot:"):
            monitor_index = None
            if command.startswith("v8:screenshot:"):
                try:
                    monitor_index = int(command.split(":", 2)[2])
                except Exception:
                    monitor_index = None
            try:
                msg = self._take_screenshot_local(monitor_index=monitor_index)
            except Exception as exc:
                msg = f"Não consegui tirar o print: {exc}"
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            ok = not self._v8_text_failed(msg)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:volume":
            try:
                value = self.actions.get_volume_percent()
                msg = f"Volume atual: {int(round(float(value)))}%."
                ok = True
            except Exception:
                msg, ok = "Não consegui consultar o volume agora.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:microphone":
            try:
                status = self.voice_engine.status() if self.voice_engine else {}
                name = str(status.get("input_device") or status.get("input_device_name") or "").strip()
            except Exception:
                name = ""
            msg = f"Microfone atual: {name}." if name else "Não consegui identificar o microfone atual."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=bool(name), verified=bool(name))
            return outcome

        if command == "v8:voice_restart":
            ok = False
            detail = ""
            try:
                if self.voice_engine:
                    # Hotfix 13.6.5: o motor voltou ao pipeline estavel anterior
                    # aos watchdogs/supervisores. Reiniciar voz significa apenas
                    # pedir a reabertura do stream antigo; nao cria supervisor.
                    if not getattr(self.voice_engine, "_started", False):
                        self.voice_engine.start()
                    self.voice_engine.restart_input_stream()
                    ok = True
                    detail = "modo estavel classico"
            except Exception as exc:
                detail = str(exc)
            if ok:
                msg = "Reiniciei a escuta no modo estável. Pode me chamar novamente em alguns segundos."
            else:
                msg = "Não consegui reiniciar a escuta agora."
                if detail:
                    msg += f" Detalhe: {detail}."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:mic_sensitivity:"):
            try:
                factor = float(command.rsplit(":", 1)[1])
                if not self.voice_engine:
                    raise RuntimeError("motor de voz indisponível")
                applied = self.voice_engine.set_microphone_sensitivity(factor)
                label = "sensível" if applied > 1.05 else "normal"
                msg = f"✓ Sensibilidade do microfone ajustada para {label} ({applied:.2f}x), sem trocar driver ou STT."
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui ajustar a sensibilidade: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:tts_rate:"):
            try:
                rate = command.split(":", 2)[2]
                if not self.voice_engine:
                    raise RuntimeError("motor de voz indisponível")
                applied = self.voice_engine.set_tts_rate(rate)
                msg = f"✓ Velocidade da voz ajustada para {applied}."
                ok = True
            except Exception as exc:
                msg, ok = f"Não consegui ajustar a velocidade da voz: {exc}", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:monitors":
            try:
                monitors = self.window_manager.get_monitors() if self.window_manager else []
                active = self.window_manager.get_active_monitor() if self.window_manager else {}
                active_index = active.get("index") or active.get("number") or "?"
                msg = f"Detectei {len(monitors)} monitor(es). Monitor ativo: {active_index}."
                ok = bool(monitors)
            except Exception:
                msg, ok = "Não consegui consultar os monitores agora.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command == "v8:capabilities":
            msg = self._get_system_commands_info().strip()
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome["message"] = msg
            return outcome

        if command == "v8:slot_cancelled":
            msg = "Certo, cancelei essa pergunta."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=True, verified=True)
            return outcome

        if command == "v8:clarify_monitor":
            msg = "Qual monitor você quer que eu descreva?"
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=False, verified=False)
            return outcome

        if command == "v8:clarify_app":
            msg = "Qual aplicativo ou janela você quer usar?"
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=False, verified=False)
            return outcome

        if command.startswith("v8:clarify_move:"):
            target = command.split(":", 2)[2].strip()
            msg = f"Para qual monitor você quer mover {target}?" if target else "Para qual monitor você quer mover a janela?"
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=False, verified=False)
            return outcome

        if command == "v8:clarify_undo":
            msg = "Não há uma ação local recente que eu consiga desfazer com segurança."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=False, verified=False)
            return outcome

        if command.startswith("v8:browser_search:"):
            self._set_source_badge("WEB")
            payload = command.split(":", 2)[2]
            browser, sep, query = payload.partition("|")
            browser = browser.strip() or "Opera"
            query = query.strip() if sep else ""
            if not query:
                msg, ok = "O que você quer pesquisar?", False
            elif "opera" in self._local_strip_accents(browser).lower():
                raw_msg = self.actions.search_web_in_opera(query)
                ok = not self._v8_text_failed(raw_msg)
                msg = raw_msg if ok else raw_msg
            else:
                msg, ok = "Não consegui manter o contexto desse navegador.", False
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:open_site_in_app:"):
            payload = command.split(":", 2)[2]
            browser, sep, address = payload.partition("|")
            browser = browser.strip()
            address = address.strip() if sep else ""
            aliases = {
                "youtube.com": "https://www.youtube.com/",
                "youtube": "https://www.youtube.com/",
                "accounts.mlabs.io": "https://accounts.mlabs.io/",
                "mlabs": "https://accounts.mlabs.io/",
                "open.spotify.com": "https://open.spotify.com/",
                "crunchyroll.com": "https://www.crunchyroll.com/",
                "crunchyroll": "https://www.crunchyroll.com/",
                "spotify": "https://open.spotify.com/",
                "instagram.com": "https://www.instagram.com/",
                "facebook.com": "https://www.facebook.com/",
                "mail.google.com": "https://mail.google.com/",
                "google.com": "https://www.google.com/",
                "linkedin.com": "https://www.linkedin.com/",
                "web.whatsapp.com": "https://web.whatsapp.com/",
                "adsmanager.facebook.com": "https://adsmanager.facebook.com/",
            }
            url = aliases.get(address.lower(), address)
            if url and not re.match(r"^https?://", url, flags=re.I):
                url = "https://" + url
            if "opera" in self._local_strip_accents(browser).lower() and url:
                raw_msg = self.actions.open_url_in_opera_gx(url)
            else:
                raw_msg = "Não consegui manter o contexto desse navegador."
            ok = bool(url) and not self._v8_text_failed(raw_msg)
            if ok:
                site_names = {
                    "youtube.com": "YouTube",
                    "accounts.mlabs.io": "mLabs",
                    "open.spotify.com": "Spotify",
                    "crunchyroll.com": "Crunchyroll",
                    "crunchyroll": "Crunchyroll",
                    "instagram.com": "Instagram",
                    "facebook.com": "Facebook",
                    "mail.google.com": "Gmail",
                    "google.com": "Google",
                    "linkedin.com": "LinkedIn",
                    "web.whatsapp.com": "WhatsApp Web",
                    "adsmanager.facebook.com": "Gerenciador de Anúncios",
                }
                site_label = site_names.get(address.lower(), address)
                msg = f"✓ Abri {site_label} no {browser}."
            else:
                msg = raw_msg
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:create_folder:"):
            payload = command.split(":", 2)[2]
            destination, sep, name = payload.partition("|")
            destination = destination.strip().lower()
            name = name.strip() if sep else ""
            if not name:
                msg = "Informe o nome da pasta."
            else:
                try:
                    base = self.actions._known_user_directory(destination)
                    msg = self.actions.create_folder(os.path.join(base, name))
                except Exception as exc:
                    msg = f"Não consegui criar a pasta: {exc}"
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            ok = not self._v8_text_failed(msg) and str(msg).lstrip().startswith("✓")
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        if command.startswith("v8:create_text:"):
            name = command.split(":", 2)[2].strip() or "Novo arquivo"
            if hasattr(self.actions, "create_text_file"):
                msg = self.actions.create_text_file(name, desktop=True)
            else:
                msg = "Criação de arquivo de texto não está disponível."
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            ok = not self._v8_text_failed(msg) and str(msg).lstrip().startswith("✓")
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        # Criação de pasta passa direto pela ferramenta blindada.
        m = re.match(r"^crie pasta no desktop\s+(.+)$", command, flags=re.I)
        if m:
            msg = self.actions.create_folder(f"desktop {m.group(1).strip()}")
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            ok = not self._v8_text_failed(msg) and str(msg).lstrip().startswith("✓")
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        # Sites não passam pelo App Resolver.
        m = re.match(r"^(?:abre|abra|abrir)\s+(?:o\s+)?site\s+(.+)$", command, flags=re.I)
        if m:
            msg = self.actions.open_website(m.group(1).strip())
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            ok = not self._v8_text_failed(msg)
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        # Abrir app: usa resolver atual e, para dependências, confirma janela real.
        m = re.match(r"^(?:abre|abra|abrir)\s+(?:o\s+|a\s+)?(.+)$", command, flags=re.I)
        if m:
            target = m.group(1).strip().rstrip(".?!,;:")
            if target.lower() in {"youtube", "o youtube"}:
                msg = self.actions.open_youtube()
                verified = not self._v8_text_failed(msg)
            else:
                msg = self.actions.open_application(target)
                verified = ("aberto e verificado" in self._local_strip_accents(str(msg)).lower())
                if not verified and not self._v8_text_failed(msg):
                    verified = self._v8_verify_window_target(target, timeout=1.5)
            requested = not self._v8_text_failed(msg)
            display_msg = msg
            if requested and verified:
                norm_msg = self._local_strip_accents(str(msg)).lower()
                if "verificado" not in norm_msg and not str(msg).lstrip().startswith("✓"):
                    display_msg = f"✓ {target} disponível e verificado."
            self.add_message(PUBLIC_NAME, display_msg, is_jarvis=True)
            outcome.update(message=display_msg, success=bool(requested and verified), verified=bool(verified))
            return outcome

        # Janelas: alvo explícito; nunca usa a janela atual como fallback.
        window_specs = (
            (r"^(?:minimize|minimiza|minimizar)\s+(?:o\s+|a\s+)?(.+)$", "minimize"),
            (r"^(?:maximize|maximiza|maximizar|expande|expanda|expandir)\s+(?:o\s+|a\s+)?(.+)$", "maximize"),
            (r"^(?:restaure|restaura|restaurar)\s+(?:o\s+|a\s+)?(.+)$", "restore"),
        )
        for pattern, method_name in window_specs:
            m = re.match(pattern, command, flags=re.I)
            if m:
                if not self.window_manager:
                    msg = "Controle de janelas não carregado."
                else:
                    msg = getattr(self.window_manager, method_name)(m.group(1).strip())
                self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
                ok = not self._v8_text_failed(msg) and str(msg).lstrip().startswith("✓")
                outcome.update(message=msg, success=ok, verified=ok)
                return outcome

        if command.startswith("v8:move_other:"):
            target = command.split(":", 2)[2].strip()
            if not target:
                msg = "Qual aplicativo ou janela você quer mover?"
            elif not self.window_manager:
                msg = "Controle de monitores não carregado."
            else:
                msg = self.window_manager.move_to_other_monitor(target)
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            ok = not self._v8_text_failed(msg) and str(msg).lstrip().startswith("✓")
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        m = re.match(
            r"^(?:mova|move|mover|coloca|coloque|joga|jogue|leva|leve)\s+(.+?)\s+para\s+monitor\s+(\d+)\s*$",
            command, flags=re.I,
        )
        if m:
            if not self.window_manager:
                msg = "Controle de monitores não carregado."
            else:
                msg = self.window_manager.move_to_monitor(m.group(1).strip(), int(m.group(2)))
            self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
            ok = not self._v8_text_failed(msg) and str(msg).lstrip().startswith("✓")
            outcome.update(message=msg, success=ok, verified=ok)
            return outcome

        # Comandos de mídia legados passam pelo Media Context V2 sem alterar o
        # contrato histórico do Router/testes.
        media_key = self._local_strip_accents(command).lower().strip(" .!?;:")
        legacy_media = {
            "pausa": "pause", "pause": "pause", "continua": "play", "play": "play",
            "proxima musica": "next", "proxima faixa": "next", "proximo": "next", "proxima": "next",
            "musica anterior": "previous", "faixa anterior": "previous",
        }
        if media_key in legacy_media and self.media_context is not None:
            try:
                result = self.media_context.control(legacy_media[media_key], target_hint=self._current_media_target() or "")
                msg = str(result.get("message") or "Comando de mídia enviado.")
                ok = bool(result.get("success"))
                verified = bool(result.get("verified"))
                self.add_message(PUBLIC_NAME, msg, is_jarvis=True)
                outcome.update(message=msg, success=ok, verified=verified)
                return outcome
            except Exception as exc:
                try: self.logger.warning(f"Media Context fallback falhou: {exc}", "MEDIA")
                except Exception: pass

        handled = self._detect_system_command(command)
        outcome.update(handled=bool(handled), success=bool(handled), verified=False)
        return outcome

    def _execute_v8_command(self, command: str) -> bool:
        """Compatibilidade com chamadas antigas: retorna apenas se foi tratado."""
        return bool(self._execute_v8_command_result(command).get("handled"))

    def _process_message(self, message: str, source: str = "text"):
        """Processa a entrada e registra a experiência operacional da 1.0 Beta."""
        work_token = self._begin_work_generation()
        self.is_processing = True
        try:
            watchdog_ms = 12000 if str(source or "text").lower() == "text" else 8500
            self.root.after(watchdog_ms, lambda token=work_token: self._processing_watchdog(token))
        except Exception:
            pass
        trace = self.performance_tracer.start(source=source) if self.performance_tracer else None

        def cancelled() -> bool:
            return not self._work_is_current(work_token)

        def process_in_thread():
            self._work_thread_context.token = work_token
            # Identidade de sessão é explícita e não depende de reconhecimento de voz.
            speaker_name = self._current_speaker_name(wait_ms=0)
            experience_id = None
            experience_finished = False
            experience_started = time.perf_counter()
            trace_intent = ""
            trace_kind = ""
            trace_success = None
            if trace is not None:
                trace.lap("thread_queue")

            def finish_experience(success, verified, error_reason=""):
                nonlocal experience_finished
                if experience_finished or not experience_id or self.experience_engine is None:
                    return
                try:
                    self.experience_engine.finish(
                        experience_id,
                        success=success,
                        verified=verified,
                        duration_ms=(time.perf_counter() - experience_started) * 1000.0,
                        error_reason=error_reason,
                    )
                    experience_finished = True
                except Exception:
                    pass

            try:
                if cancelled():
                    return

                # Confirmação é um estado de diálogo de prioridade máxima. Ela
                # precisa ser resolvida ANTES do Router; caso contrário "sim"
                # pode virar conversa local e a ação pendente nunca executa.
                if self._pending_confirmation and self._resolve_confirmation_text(message):
                    trace_intent = "CONFIRMATION"
                    trace_kind = "local"
                    trace_success = True
                    return

                if self.experience_engine is not None:
                    try:
                        self.experience_engine.maybe_record_correction(
                            message, conversation_id=self.active_conversation_id
                        )
                    except Exception:
                        pass

                route_started = time.perf_counter()
                v8 = route_v8(message) if route_v8 else None
                if trace is not None:
                    trace.add("router", (time.perf_counter() - route_started) * 1000.0)
                trace_intent = str(getattr(v8, "intent", "") or "") if v8 is not None else ""
                trace_kind = str(getattr(v8, "kind", "") or "") if v8 is not None else ""

                # Aprendizado conservador: somente uma frase exata previamente
                # confirmada pode recuperar uma rota que o Router tratou como conversa.
                if (
                    self.experience_engine is not None
                    and v8 is not None
                    and getattr(v8, "kind", "") == "conversation"
                    and getattr(v8, "intent", "") not in {"NEGATED_COMMAND", "ACTION_ASSERTION"}
                ):
                    lookup_started = time.perf_counter()
                    try:
                        learned = self.experience_engine.lookup(message)
                    except Exception:
                        learned = None
                    if trace is not None:
                        trace.add("experience_lookup", (time.perf_counter() - lookup_started) * 1000.0)
                    if learned is not None:
                        v8 = SimpleNamespace(
                            kind=learned.kind,
                            commands=list(learned.commands),
                            intent=learned.intent,
                            steps=[],
                            learned_confidence=learned.confidence,
                        )
                        trace_intent = str(learned.intent or "")
                        trace_kind = str(learned.kind or "")
                        try:
                            self.logger.info(
                                f"Rota recuperada pelo Experience Engine: {learned.intent} "
                                f"conf={learned.confidence:.2f}",
                                "EXPERIENCE",
                            )
                        except Exception:
                            pass

                if self.experience_engine is not None and v8 is not None:
                    exp_begin_started = time.perf_counter()
                    try:
                        experience_id = self.experience_engine.begin(
                            message,
                            source=source,
                            conversation_id=self.active_conversation_id,
                            route_kind=getattr(v8, "kind", ""),
                            intent=getattr(v8, "intent", ""),
                            commands=getattr(v8, "commands", None) or [],
                        )
                    except Exception:
                        experience_id = None
                    if trace is not None:
                        trace.add("experience_begin", (time.perf_counter() - exp_begin_started) * 1000.0)
                if (
                    v8 is not None
                    and getattr(v8, "kind", "") == "conversation"
                    and getattr(v8, "intent", "") == "NEGATED_COMMAND"
                ):
                    msg = "Certo. Não vou executar essa ação."
                    self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, msg, False, True, False, False)
                    finish_experience(True, True)
                    trace_success = True
                    return

                if v8 is not None and getattr(v8, "kind", "") == "conversation":
                    try:
                        if len(str(message).split()) >= 2:
                            v8_remember_topic(message)
                    except Exception:
                        pass
                    # Conversa V8 tambem usa streaming: a UI mostra o primeiro trecho
                    # assim que chega e, em voz, o TTS progressivo pode comecar antes
                    # de o Gemini terminar toda a resposta. Isso reduz muito o tempo
                    # percebido sem mudar o modelo nem sacrificar o texto completo.
                    context = self._get_conversation_history()
                    # Contexto completo permanece no SQLite. O prompt recebe
                    # somente uma janela curta para reduzir serializacao e
                    # impedir que conversas com centenas de mensagens pesem.
                    context = context[-5:] if source == "voice" else context[-10:]
                    memories = self._safe_relevant_memories(message, limit=6)
                    received_chunks = []
                    first_chunk_seen = [False]
                    core_started = time.perf_counter()
                    self._post_ui_event("stream_start", work_token, PUBLIC_NAME)

                    def on_v8_conversation_chunk(chunk):
                        if cancelled():
                            return
                        if not first_chunk_seen[0]:
                            first_chunk_seen[0] = True
                            if trace is not None:
                                trace.add("gemini_first_token", (time.perf_counter() - core_started) * 1000.0)
                        received_chunks.append(chunk)
                        self._queue_stream_chunk_threadsafe(work_token, chunk)

                    self._post_work_ui_call(work_token, self._set_source_badge, "IA")
                    result = self.core.process_message_stream(
                        message, context, memories, self._get_live_context_info(), on_chunk=on_v8_conversation_chunk,
                        speaker_name=speaker_name, source=source
                    )
                    if trace is not None:
                        trace.add("gemini_total", (time.perf_counter() - core_started) * 1000.0)
                    if cancelled():
                        return
                    if not received_chunks and result:
                        self._queue_stream_chunk_threadsafe(work_token, result)
                    self._post_ui_event("stream_finish", work_token, result)
                    finish_experience(True, False)
                    trace_success = True
                    return
                if v8 is not None and getattr(v8, "kind", "") == "local" and getattr(v8, "commands", None):
                    steps = list(getattr(v8, "steps", None) or [])
                    if len(steps) != len(v8.commands):
                        steps = [None] * len(v8.commands)
                    # Modo direto: fechamentos explícitos são executados imediatamente,
                    # inclusive quando o Router agrupou vários aplicativos no mesmo pedido.
                    close_targets = []
                    if steps and all(getattr(step, "action", "") == "CLOSE_APP" for step in steps):
                        for command in v8.commands:
                            m_close = re.match(r"^(?:fecha|feche|fechar)\s+(?:o\s+|a\s+)?(.+)$", command, flags=re.I)
                            if m_close:
                                close_targets.append(m_close.group(1).strip())
                    if len(close_targets) >= 2:
                        messages = []
                        for target in close_targets:
                            try:
                                messages.append(str(self.actions.close_application(target)))
                            except Exception as exc:
                                messages.append(f"Não consegui fechar {target}: {exc}")
                        raw_msg = "\n".join(messages)
                        ok = bool(messages) and all(not self._v8_text_failed(item) for item in messages)
                        self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, raw_msg, False, True, False, False)
                        finish_experience(ok, ok)
                        trace_success = ok
                        return

                    outcomes = []
                    for index, command in enumerate(v8.commands, start=1):
                        if cancelled():
                            return
                        self._post_work_ui_call(work_token, self._update_status, f"EXECUTANDO {index}/{len(v8.commands)}", "#8E6BFF")
                        step = steps[index - 1] if index - 1 < len(steps) else None
                        dep = getattr(step, "depends_on", None) if step is not None else None
                        require_success = bool(getattr(step, "require_success", False)) if step is not None else False
                        if require_success and dep is not None:
                            dependency_ok = (
                                0 <= int(dep) < len(outcomes)
                                and bool(outcomes[int(dep)].get("success"))
                            )
                            if not dependency_ok:
                                target = getattr(step, "target", None) or command
                                msg = (
                                    f"Não executei o passo dependente '{target}' porque a ação anterior "
                                    "não foi confirmada com sucesso."
                                )
                                self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, msg, False, True, False, False)
                                outcomes.append({"handled": True, "success": False, "verified": False, "skipped": True})
                                continue

                        step_started = time.perf_counter()
                        before_window = {}
                        if step is not None and getattr(step, "target", None) and getattr(step, "action", "") in {
                            "OPEN_APP", "MINIMIZE_WINDOW", "MAXIMIZE_WINDOW", "RESTORE_WINDOW", "MOVE_WINDOW", "MOVE_OTHER"
                        }:
                            before_window = self._v8_window_snapshot(getattr(step, "target"))
                        outcome = self._execute_v8_command_result(command)
                        if trace is not None:
                            trace.add("execute", (time.perf_counter() - step_started) * 1000.0)
                        outcomes.append(outcome)
                        try:
                            if self.workflow_engine:
                                self.workflow_engine.record_command(
                                    command, bool(outcome.get("success")), bool(outcome.get("verified"))
                                )
                            if self.operational_context:
                                self.operational_context.record_action(
                                    getattr(step, "action", "LOCAL") if step is not None else "LOCAL",
                                    outcome.get("message") or command, bool(outcome.get("verified")),
                                    {"target": getattr(step, "target", "") if step is not None else ""},
                                )
                            if self.behavior_memory is not None and bool(outcome.get("success")):
                                snap = self.operational_context.snapshot() if self.operational_context else {}
                                learned_action = self.behavior_memory.observe_action(
                                    getattr(step, "action", "LOCAL") if step is not None else trace_intent or "LOCAL",
                                    getattr(step, "target", "") if step is not None else "",
                                    str(snap.get("active_app") or ""),
                                )
                                if learned_action:
                                    target_label = learned_action.get("target") or learned_action.get("action")
                                    self._post_work_ui_call(work_token, self._show_agent_notice, f"Padrão aprendido: você repete {target_label} nesse contexto ({learned_action['count']} vezes). Posso transformar isso em rotina/regra.")
                        except Exception:
                            pass
                        if cancelled():
                            return
                        if (
                            outcome.get("success")
                            and step is not None
                            and getattr(step, "target", None)
                            and getattr(step, "action", "") in {
                                "OPEN_APP", "MINIMIZE_WINDOW", "MAXIMIZE_WINDOW",
                                "RESTORE_WINDOW", "MOVE_WINDOW", "MOVE_OTHER",
                                "OPEN_SITE_IN_APP", "BROWSER_SEARCH",
                            }
                        ):
                            # Contexto operacional so muda depois de sucesso real.
                            # Assim "maximiza Photoshop" -> "manda para outra tela"
                            # funciona mesmo sem um OPEN_APP imediatamente anterior.
                            try:
                                target_value = getattr(step, "target")
                                v8_mark_app_success(target_value)
                                after_window = self._v8_window_snapshot(target_value)
                                v8_mark_action_success(
                                    getattr(step, "action", ""),
                                    target_value,
                                    before=before_window,
                                    after=after_window,
                                )
                            except Exception:
                                pass
                        if not outcome.get("handled"):
                            self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, f"Não consegui executar este passo: {command}", False, True, False, False)
                    local_success = bool(outcomes) and all(bool(item.get("success")) for item in outcomes)
                    local_verified = bool(outcomes) and all(bool(item.get("verified")) for item in outcomes)
                    finish_experience(local_success, local_verified)
                    trace_success = local_success
                    return

                parts = self._split_multi_actions(message)

                # Múltiplas ações: executa em sequência e só manda ao Gemini os trechos que não são ações.
                if len(parts) > 1:
                    for index, part in enumerate(parts, start=1):
                        if cancelled():
                            return
                        self._post_work_ui_call(work_token, self._update_status, f"EXECUTANDO {index}/{len(parts)}", "#8E6BFF")
                        handled = self._detect_system_command(part)
                        if not handled:
                            if self.interaction_mode == "comando":
                                self._post_work_ui_call(
                                    work_token, self.add_message, PUBLIC_NAME,
                                    f"Não reconheci como comando local: {part}",
                                    False, True, False, False
                                )
                                continue

                            plugin_result = self.plugin_manager.try_handle(
                                part,
                                {"actions": self.actions, "memory": self.memory_store, "gui": self}
                            )
                            if plugin_result is not None:
                                if cancelled():
                                    return
                                self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, str(plugin_result), False, True, False, False)
                                continue
                            if (
                                self.interaction_mode != "conversa"
                                and self._should_auto_search(part)
                            ):
                                result = self.web_search.search(part)
                                if cancelled():
                                    return
                                self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, result, False, True, False, False)
                            else:
                                context = self._get_conversation_history()
                                memories = self._safe_relevant_memories(part, limit=6)
                                result = self.core.process_message(
                                    part,
                                    context,
                                    memories,
                                    self._get_live_context_info() or self._get_system_commands_info(),
                                    speaker_name=speaker_name,
                                    source=source
                                )
                                if cancelled():
                                    return
                                self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, result, False, True, False, False)
                    return

                if self._detect_system_command(message):
                    return

                if self.interaction_mode == "comando":
                    self._post_work_ui_call(
                        work_token, self.add_message, PUBLIC_NAME,
                        "Não reconheci isso como um comando local.",
                        False, True, False, False
                    )
                    return

                plugin_result = self.plugin_manager.try_handle(
                    message,
                    {"actions": self.actions, "memory": self.memory_store, "gui": self}
                )
                if plugin_result is not None:
                    if cancelled():
                        return
                    self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, str(plugin_result), False, True, False, False)
                    return

                # No modo conversa, prioriza conversa natural.
                # Pesquisa automática continua no modo auto.
                if (
                    self.interaction_mode != "conversa"
                    and self._should_auto_search(message)
                ):
                    self._post_work_ui_call(work_token, self._update_status, "PESQUISANDO", "#3C8DFF")
                    self._post_work_ui_call(work_token, self._set_source_badge, "WEB")
                    result = self.web_search.search(message)
                    if cancelled():
                        return
                    self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, result, False, True, False, False)
                    return

                if self.core.is_available():
                    conversation_history = self._get_conversation_history()
                    # O historico completo continua no SQLite; nenhuma chamada
                    # remota precisa receber centenas de mensagens antigas.
                    conversation_history = conversation_history[-8:] if source == "voice" else conversation_history[-12:]
                    memories = self._safe_relevant_memories(message, limit=(3 if source == "voice" else 6))
                    system_commands_info = self._get_live_context_info() if source == "voice" else self._get_system_commands_info()
                    if not system_commands_info:
                        system_commands_info = self._get_system_commands_info()
                    received_chunks = []
                    if cancelled():
                        return
                    self._post_ui_event("stream_start", work_token, PUBLIC_NAME)

                    def on_chunk(chunk):
                        if cancelled():
                            return
                        received_chunks.append(chunk)
                        self._queue_stream_chunk_threadsafe(work_token, chunk)

                    self._post_work_ui_call(work_token, self._set_source_badge, "IA")
                    response = self.core.process_message_stream(
                        message,
                        conversation_history,
                        memories,
                        system_commands_info,
                        on_chunk=on_chunk,
                        speaker_name=speaker_name,
                        source=source
                    )
                    if cancelled():
                        return
                    if not received_chunks and response:
                        self._queue_stream_chunk_threadsafe(work_token, response)
                    self._post_ui_event("stream_finish", work_token, response)
                else:
                    if self.core.has_auth_error():
                        error_msg = self.core.get_auth_error_message()
                        self._post_work_ui_call(work_token, self._show_jarvis_response, error_msg, False)
                    else:
                        self._post_work_ui_call(work_token, self.add_message, PUBLIC_NAME, "API Gemini não está disponível. Use o botão API no topo para configurar sua chave.", False, True, False, False)
            except Exception as e:
                if cancelled():
                    return
                finish_experience(False, False, str(e))
                self.logger.error(
                    e,
                    "Erro ao processar mensagem",
                    "GUI"
                )
                self._schedule_auto_diagnostic(
                    f"Erro ao processar mensagem: {e}"
                )
                self._post_work_ui_call(
                    work_token, self.add_message, PUBLIC_NAME,
                    "Tive um erro interno ao concluir esse turno. Tente novamente; o detalhe ficou registrado no diagnóstico.",
                    False, True, False, False
                )
            finally:
                if experience_id and not experience_finished:
                    finish_experience(None, None)
                if trace is not None and self.performance_tracer is not None:
                    try:
                        if source == "voice" and self.voice_engine is not None:
                            voice_perf = self.voice_engine.status() or {}
                            for metric, stage in (
                                ("endpoint_ms", "voice_endpoint"),
                                ("stt_ms", "voice_stt"),
                                ("tts_first_audio_ms", "voice_tts_first_audio"),
                                ("end_of_speech_to_audio_ms", "voice_ttfv"),
                            ):
                                value = voice_perf.get(metric)
                                if value is not None:
                                    trace.add(stage, float(value))
                        self.performance_tracer.finish(
                            trace, intent=trace_intent, route_kind=trace_kind, success=trace_success
                        )
                    except Exception:
                        pass
                # Uma thread antiga não pode liberar o estado de uma interação
                # nova iniciada depois de um Priority Interrupt.
                if self._work_is_current(work_token):
                    self.is_processing = False
                    self._post_work_ui_call(work_token, self._voice_processing_complete)
                    self._post_work_ui_call(
                        work_token, self._update_status, "ONLINE", Config.get_color("success")
                    )
                self._work_thread_context.token = 0

        threading.Thread(target=process_in_thread, daemon=True).start()

    def _detect_system_command(self, message: str) -> bool:
        """Roteia apenas comandos explicitos; perguntas normais seguem para o Gemini."""
        original_message = str(message or "").strip()
        message = self._normalize_local_command(original_message)
        message_lower = message.lower().strip()

        def starts_with_any(prefixes):
            return any(
                message_lower == prefix
                or message_lower.startswith(prefix + " ")
                for prefix in prefixes
            )

        def remove_prefix(prefixes):
            for prefix in sorted(prefixes, key=len, reverse=True):
                if message_lower == prefix:
                    return ""
                if message_lower.startswith(prefix + " "):
                    return message[len(prefix):].strip()
            return message.strip()

        # -----------------------------------------------------
        # CONFIRMAÇÃO PENDENTE
        # -----------------------------------------------------
        if self._resolve_confirmation_text(message):
            return True

        # -----------------------------------------------------
        # IDENTIDADE VISUAL DA ESFERA
        # -----------------------------------------------------
        # Permite trocar o orb pela voz ou pelo chat, sem abrir menus:
        # "bola nucleo", "muda a esfera para aneis", "orb minimal".
        # A normalizacao compartilhada remove variacoes de acento/STT.
        orb_key = self._local_strip_accents(message_lower).lower()
        orb_subject = bool(re.search(r"\b(?:esfera|bola|orb|orbe)\b", orb_key))
        if orb_subject:
            style = None
            if re.search(r"\b(?:cristal|crystal|vidro|vitreo)\b", orb_key):
                style = "crystal"
            elif re.search(r"\b(?:nucleo|reator|jarvis|core)\b", orb_key):
                style = "core"
            elif re.search(r"\b(?:aneis|anel|rings?|holografico|holograma|hud)\b", orb_key):
                style = "rings"
            elif re.search(r"\b(?:pulso|pulse|organico|respirando|respira)\b", orb_key):
                style = "pulse"
            elif re.search(r"\b(?:minimal|minimalista|discreto|limpo)\b", orb_key):
                style = "minimal"

            if style is not None:
                self._post_context_ui_call(self._set_orb_style, style)
                return True

            if any(token in orb_key for token in (
                "opcoes", "opcao", "estilos", "estilo", "modelos", "modelo",
                "quais", "mostrar", "mostra", "trocar", "mudar",
            )):
                self.add_message(
                    PUBLIC_NAME,
                    "Tenho cinco estilos de esfera: Cristal, Núcleo, Anéis, Pulso e Minimal. "
                    "Você pode dizer, por exemplo, 'esfera Núcleo'.",
                    is_jarvis=True,
                )
                return True

        # -----------------------------------------------------
        # CONTROLES DE VOZ / STATUS RÁPIDO
        # -----------------------------------------------------
        if message_lower in (
            "zero para", "para zero", "zero pare", "pare zero",
            "zero cancela", "cancela zero", "pare de falar"
        ):
            if self.voice_engine:
                self.voice_engine.stop_speaking()
            self.add_message(PUBLIC_NAME, "Certo.", is_jarvis=True)
            return True

        if message_lower in (
            "calibre microfone", "calibre o microfone", "calibrar microfone",
            "recalibre o microfone", "recalibrar microfone", "calibrar mic",
            "calibre mic", "calibrar microfono", "calibre microfono", "calipro",
        ):
            if self.voice_engine:
                try:
                    self.voice_engine.request_microphone_calibration(delay=1.35)
                    self.add_message(
                        PUBLIC_NAME,
                        "Certo. Fique em silêncio por um segundo para eu calibrar o microfone.",
                        is_jarvis=True,
                    )
                except Exception as e:
                    self.add_message(PUBLIC_NAME, f"Não consegui calibrar o microfone: {e}", is_jarvis=True)
            else:
                self.add_message(PUBLIC_NAME, "O motor de voz não está disponível.", is_jarvis=True)
            return True

        if message_lower in (
            "como esta o pc", "como está o pc", "como ta o pc",
            "como tá o pc", "status do pc", "status do computador",
            "me diz como esta o pc", "me diz como está o pc"
        ):
            try:
                result = self.actions.get_system_status()
            except Exception as e:
                result = f"Não consegui ler o status do PC: {e}"
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # CAPACIDADES REAIS DO JARVIS
        # -----------------------------------------------------
        capability_phrases = (
            "o que voce consegue fazer",
            "o que você consegue fazer",
            "me diz o que voce consegue fazer",
            "me diz o que você consegue fazer",
            "me diga o que voce consegue fazer",
            "me diga o que você consegue fazer",
            "detalhadamente o que voce consegue fazer",
            "detalhadamente o que você consegue fazer",
            "quais sao suas funcoes",
            "quais são suas funções",
        )
        if any(phrase in message_lower for phrase in capability_phrases):
            self.add_message(
                PUBLIC_NAME,
                self._get_system_commands_info().strip(),
                is_jarvis=True
            )
            return True

        # -----------------------------------------------------
        # REDE LOCAL
        # -----------------------------------------------------
        if message_lower in (
            "analisar minha rede", "analise minha rede", "analisa minha rede",
            "diagnostico de rede", "diagnóstico de rede", "status da rede",
            "verificar minha rede", "verifique minha rede"
        ):
            self._post_context_ui_call(self._update_status, "EXECUTANDO", "#3C8DFF")
            self.add_message(
                PUBLIC_NAME,
                self._analyze_network_local(),
                is_jarvis=True
            )
            return True

        # -----------------------------------------------------
        # MODO CONVERSA / COMANDO / AUTO
        # -----------------------------------------------------
        mode_map = {
            "modo conversa": "conversa",
            "entre no modo conversa": "conversa",
            "ativar modo conversa": "conversa",
            "ativa modo conversa": "conversa",
            "conversar": "conversa",
            "vamos conversar": "conversa",
            "sair do modo conversa": "auto",
            "desativar modo conversa": "auto",
            "modo comando": "comando",
            "entre no modo comando": "comando",
            "ativar modo comando": "comando",
            "modo automatico": "auto",
            "modo automático": "auto",
            "modo auto": "auto",
            "modo avancado": "auto",
            "modo avançado": "auto",
        }

        if message_lower in mode_map:
            self.interaction_mode = (
                mode_map[
                    message_lower
                ]
            )

            labels = {
                "auto": "Automático",
                "conversa": "Conversa",
                "comando": "Comando",
            }

            try:
                if self.voice_engine:
                    self.voice_engine.set_conversation_mode(self.interaction_mode == "conversa")
            except Exception:
                pass
            self._post_context_ui_call(self._sync_conversation_overlay_lock, self.interaction_mode == "conversa")
            self.add_message(
                PUBLIC_NAME,
                (f"Modo Conversa contínua. Pode falar sem repetir '{PUBLIC_NAME.title()}'."
                 if self.interaction_mode == "conversa" else
                 f"✓ Modo {labels[self.interaction_mode]}.") ,
                is_jarvis=True
            )
            return True

        if message_lower in [
            "qual modo esta ativo",
            "qual modo está ativo",
            "modo atual",
        ]:
            self.add_message(
                PUBLIC_NAME,
                f"Modo atual: {self.interaction_mode}.",
                is_jarvis=True
            )
            return True

        # -----------------------------------------------------
        # DIAGNÓSTICO AUTOMÁTICO
        # -----------------------------------------------------
        if message_lower in [
            "diagnostico",
            "diagnóstico",
            "diagnostico completo",
            "diagnóstico completo",
            "verifique o jarvis",
            "verificar o jarvis",
            "verifique o zero",
            "verificar o zero",
        ]:
            if self.diagnostics_manager:
                result = self.diagnostics_manager.run(
                    core=self.core,
                    memory_store=self.memory_store,
                    voice_engine=self.voice_engine,
                    desktop=self.desktop_integration,
                    windows=self.window_manager,
                    audio=self.audio_device_manager,
                    vision=self.vision_system,
                    actions=self.actions,
                    performance=self.performance_tracer,
                    context=v8_context_status,
                    media_context=self.media_context,
                    conditional_rules=self.conditional_rules,
                    behavior_memory=self.behavior_memory,
                )
            else:
                result = "Módulo de diagnóstico não carregado."

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        if message_lower in ["mover esfera", "mova a esfera", "quero mover a esfera", "reposicionar esfera"]:
            self._post_context_ui_call(self._enable_overlay_move_mode)
            self.add_message(PUBLIC_NAME, "Modo de movimento ativado. Arraste a esfera e solte onde quiser.", is_jarvis=True)
            return True

        # -----------------------------------------------------
        # MÚLTIPLOS MONITORES / CONTROLE DE JANELAS
        # -----------------------------------------------------
        if message_lower in [
            "quantos monitores",
            "quantos monitores tenho",
            "qual monitor estou usando",
            "em qual monitor estou",
            "monitor ativo",
        ]:
            if self.window_manager:
                status = self.window_manager.status()

                result = (
                    f"✓ {status['monitor_count']} monitor(es). "
                    f"Você está trabalhando no monitor "
                    f"{status['active_monitor']}. "
                    f"Janela ativa: "
                    f"{status['active_window'] or 'não identificada'}."
                )
            else:
                result = "Controle de monitores não carregado."

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        minimize_match = re.match(
            r"^(?:minimize|minimiza|minimizar)\s+(?:o\s+|a\s+)?(.+)$",
            message,
            flags=re.I
        )

        if minimize_match:
            app = minimize_match.group(1).strip()

            result = (
                self.window_manager.minimize(app)
                if self.window_manager
                else "Controle de janelas não carregado."
            )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        maximize_match = re.match(
            r"^(?:maximize|maximiza|maximizar)\s+(?:o\s+|a\s+)?(.+)$",
            message,
            flags=re.I
        )

        if maximize_match:
            app = maximize_match.group(1).strip()

            result = (
                self.window_manager.maximize(app)
                if self.window_manager
                else "Controle de janelas não carregado."
            )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        restore_match = re.match(
            r"^(?:restaure|restaura|restaurar)\s+(?:o\s+|a\s+)?(.+)$",
            message,
            flags=re.I
        )

        if restore_match:
            app = restore_match.group(1).strip()

            result = (
                self.window_manager.restore(app)
                if self.window_manager
                else "Controle de janelas não carregado."
            )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        other_monitor_match = re.match(
            r"^(?:joga|jogue|mova|move|manda|mande|passa|passe|coloca|coloque)\s+"
            r"(?:o\s+|a\s+)?(.+?)\s+(?:pro|para|pra|no)\s+(?:o\s+)?outro\s+monitor$",
            message, flags=re.I
        )
        if other_monitor_match:
            app = other_monitor_match.group(1).strip()
            result = (
                self.window_manager.move_to_other_monitor(app)
                if self.window_manager else "Controle de monitores não carregado."
            )
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        move_monitor_match = re.match(
            r"^(?:joga|jogue|mova|move|manda|mande|passa|passe|coloca|coloque|leva|leve)\s+"
            r"(?:o\s+|a\s+)?(.+?)\s+"
            r"(?:pro|para|para o)\s+"
            r"(?:monitor\s*(\d+)|"
            r"(primeiro|segundo|terceiro)\s+monitor)$",
            message,
            flags=re.I
        )

        if move_monitor_match:
            app = move_monitor_match.group(1).strip()

            if move_monitor_match.group(2):
                monitor_index = int(
                    move_monitor_match.group(2)
                )
            else:
                ordinal = (
                    move_monitor_match.group(3)
                    or ""
                ).lower()

                monitor_index = {
                    "primeiro": 1,
                    "segundo": 2,
                    "terceiro": 3,
                }.get(
                    ordinal,
                    1
                )

            result = (
                self.window_manager.move_to_monitor(
                    app,
                    monitor_index
                )
                if self.window_manager
                else "Controle de monitores não carregado."
            )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        side_match = re.match(
            r"^(?:coloque|coloca|põe|poe)\s+"
            r"(?:o\s+|a\s+)?(.+?)\s+e\s+"
            r"(?:o\s+|a\s+)?(.+?)\s+lado\s+a\s+lado$",
            message,
            flags=re.I
        )

        if side_match:
            result = (
                self.window_manager.tile_side_by_side(
                    side_match.group(1).strip(),
                    side_match.group(2).strip(),
                )
                if self.window_manager
                else "Controle de janelas não carregado."
            )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        if message_lower in [
            "coloca lado a lado",
            "coloque lado a lado",
            "janelas lado a lado",
        ]:
            result = (
                self.window_manager.tile_side_by_side()
                if self.window_manager
                else "Controle de janelas não carregado."
            )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        # -----------------------------------------------------
        # VISÃO DA TELA
        # -----------------------------------------------------
        vision_patterns = [
            "o que tem na minha tela",
            "o que esta na minha tela",
            "o que está na minha tela",
            "analise minha tela",
            "analisa minha tela",
            "olhe minha tela",
            "olha minha tela",
            "onde esta o botao",
            "onde está o botão",
            "onde fica o botao",
            "onde fica o botão",
            "por que apareceu esse erro",
            "porque apareceu esse erro",
            "o que significa esse erro na tela",
            "descreva minha tela",
            "descreve minha tela",
            "descrever minha tela",
            "descreva o que tem na tela",
            "descreve o que tem na tela",
            "o que voce ve na minha tela",
            "o que você vê na minha tela",
            "veja minha tela",
            "ve minha tela",
            "vê minha tela",
            "descreve monitor",
            "descreva monitor",
            "descreve minha tela monitor",
            "o que tem no monitor",
            "o que aparece no monitor",
        ]

        if any(
            message_lower.startswith(pattern)
            for pattern in vision_patterns
        ):
            if self.vision_system:
                self._post_context_ui_call(self._update_status, 
                    "PENSANDO",
                    "#3C8DFF"
                )

                result = self.vision_system.analyze(
                    message
                )
            else:
                result = "Módulo de visão não carregado."

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        # -----------------------------------------------------
        # DISPOSITIVOS DE ÁUDIO
        # -----------------------------------------------------
        if message_lower in [
            "listar dispositivos de audio",
            "listar dispositivos de áudio",
            "dispositivos de audio",
            "dispositivos de áudio",
        ]:
            if not self.audio_device_manager:
                result = "Gerenciador de áudio não carregado."
            else:
                status = self.audio_device_manager.status()

                outputs = [
                    item["name"]
                    for item in status.get(
                        "outputs",
                        []
                    )
                ]
                inputs = [
                    item["name"]
                    for item in status.get(
                        "inputs",
                        []
                    )
                ]

                result = (
                    "Saídas:\n- "
                    + (
                        "\n- ".join(outputs)
                        if outputs
                        else "nenhuma"
                    )
                    + "\n\nEntradas:\n- "
                    + (
                        "\n- ".join(inputs)
                        if inputs
                        else "nenhuma"
                    )
                )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        output_match = re.match(
            r"^(?:manda|mande|joga|jogue)\s+(?:o\s+)?som\s+(?:para|pro|pra)\s+(.+)$",
            message,
            flags=re.I
        )

        # Ex.: "trocar do fone de ouvido para alto falante".
        if not output_match and re.search(
            r"\b(?:fone|headset|alto\s*falante|caixas?|speaker|saida|saída|som)\b",
            message,
            flags=re.I,
        ):
            output_match = re.match(
                r"^(?:troque|troca|trocar|mude|muda|mudar)\s+"
                r"(?:(?:do|de|da|o|a)\s+)?(?:.+?)\s+(?:para|pro|pra)\s+(.+)$",
                message,
                flags=re.I,
            )

        if not output_match and message_lower in [
            "volta para as caixas",
            "volte para as caixas",
            "som nas caixas",
        ]:
            output_query = "caixas"
        elif output_match:
            output_query = output_match.group(1).strip()
        else:
            output_query = ""

        if output_query:
            if self.audio_device_manager:
                changed = (
                    self.audio_device_manager.switch_output(
                        output_query
                    )
                )

                if (
                    changed.get("ok")
                    and self.voice_engine
                ):
                    self.voice_engine.refresh_output_device()

                result = changed.get(
                    "message",
                    "Não consegui trocar a saída."
                )
            else:
                result = "Gerenciador de áudio não carregado."

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        input_match = re.match(
            r"^(?:use|usa|usar|troque|mude)\s+"
            r"(?:o\s+)?(?:microfone|mic)\s+(.+)$",
            message,
            flags=re.I
        )

        if input_match:
            query = input_match.group(1).strip()

            if self.audio_device_manager:
                changed = (
                    self.audio_device_manager.switch_input(
                        query
                    )
                )

                if (
                    changed.get("ok")
                    and self.voice_engine
                ):
                    self.voice_engine.set_input_device_by_name(
                        changed.get(
                            "name",
                            query
                        )
                    )

                result = changed.get(
                    "message",
                    "Não consegui trocar o microfone."
                )
            else:
                result = "Gerenciador de áudio não carregado."

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        # -----------------------------------------------------
        # MOVER ARQUIVO/PASTA PARA A LIXEIRA - MODO DIRETO
        # -----------------------------------------------------
        delete_path_match = re.match(
            r"^(?:apague|apagar|delete|deletar|exclua|excluir|remova|remover)\s+"
            r"(?:a\s+|o\s+)?(?:pasta|arquivo)\s+(.+)$",
            message,
            flags=re.I
        )

        if delete_path_match:
            raw_path = (
                delete_path_match.group(1).strip()
            )

            if not self.safety_manager:
                self.add_message(
                    PUBLIC_NAME,
                    "Não consegui carregar o recurso da Lixeira.",
                    is_jarvis=True
                )
                return True

            result = self.safety_manager.safe_delete_to_recycle_bin(raw_path)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # MEMÓRIA / HISTÓRICO / PERSONALIZAÇÃO
        # -----------------------------------------------------
        teach_prefixes = ["ensine o aplicativo", "ensinar aplicativo", "aprenda o aplicativo", "aprenda aplicativo"]
        if starts_with_any(teach_prefixes):
            alias = remove_prefix(teach_prefixes).strip()
            result = self._teach_application(alias) if alias else "Diga qual nome devo aprender."
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        forget_prefixes = ["esqueça o aplicativo", "esqueca o aplicativo", "esqueça aplicativo", "esqueca aplicativo"]
        if starts_with_any(forget_prefixes):
            alias = remove_prefix(forget_prefixes).strip()
            self.add_message(PUBLIC_NAME, self.actions.forget_app_alias(alias), is_jarvis=True)
            return True

        if message_lower in [
            "listar aliases",
            "liste os aliases",
            "aplicativos aprendidos",
            "listar aplicativos aprendidos"
        ]:
            aliases = self.actions.list_app_aliases()

            if not aliases:
                result = "Nenhum aplicativo ensinado ainda."
            else:
                result = "Aliases aprendidos:\n" + "\n".join(
                    f"- {item['alias']} → {item['display_name']}"
                    for item in aliases
                )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        if message_lower in [
            "listar memorias",
            "listar memórias",
            "o que voce lembra",
            "o que você lembra",
            "o que voce lembra de mim",
            "o que você lembra de mim"
        ]:
            memories = self.memory_store.list_memories(
                limit=30
            )

            if not memories:
                result = "Ainda não tenho memórias persistentes salvas."
            else:
                result = "Memórias persistentes:\n" + "\n".join(
                    f"#{item['id']} - {item['content']}"
                    for item in memories
                )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        memory_delete_match = re.fullmatch(
            r"(?:apague|apagar|esqueça|esqueca)\s+(?:a\s+)?mem[oó]ria\s+#?(\d+)",
            message_lower
        )

        if memory_delete_match:
            memory_id = int(
                memory_delete_match.group(1)
            )
            deleted = self.memory_store.delete_memory(
                memory_id
            )

            result = (
                f"✓ Memória #{memory_id} apagada."
                if deleted
                else f"Não encontrei a memória #{memory_id}."
            )

            self.add_message(
                PUBLIC_NAME,
                result,
                is_jarvis=True
            )
            return True

        rename_match = re.match(
            r"^(?:renomeie|renomear)\s+(?:a\s+)?conversa\s+(?:para\s+)?(.+)$",
            message,
            flags=re.I
        )

        if rename_match:
            title = rename_match.group(1).strip()

            if self.memory_store.rename_conversation(
                self.active_conversation_id,
                title
            ):
                self._post_context_ui_call(self._refresh_conversation_list)
                self.add_message(
                    PUBLIC_NAME,
                    f"✓ Conversa renomeada para '{title}'.",
                    is_jarvis=True
                )
            return True

        if message_lower in ["reindexe aplicativos", "reindexar aplicativos", "atualize indice de aplicativos", "atualize o indice de aplicativos"]:
            self._post_context_ui_call(self._update_status, "INDEXANDO", "#8E6BFF")
            self.add_message(PUBLIC_NAME, self.actions.rebuild_app_index(), is_jarvis=True)
            return True

        history_prefixes = ["buscar no historico", "buscar no histórico", "procure no historico", "procure no histórico"]
        if starts_with_any(history_prefixes):
            query = remove_prefix(history_prefixes).strip()
            results = self.memory_store.search_messages(query, limit=12)
            if not results:
                result = f"Não encontrei '{query}' no histórico."
            else:
                lines = [f"Encontrei {len(results)} resultado(s) no histórico:"]
                for item in results:
                    msg = (item.get("message") or "").replace("\n", " ")
                    if len(msg) > 180:
                        msg = msg[:177] + "..."
                    lines.append(f"- [{item.get('conversation_title')}] {item.get('sender')}: {msg}")
                result = "\n".join(lines)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if message_lower in ["estatisticas da memoria", "estatísticas da memória", "status da memoria", "status da memória"]:
            stats = self.memory_store.memory_stats()
            result = (
                f"Memória local: {stats['conversations']} conversas, "
                f"{stats['messages']} mensagens e {stats['memories']} memórias persistentes."
            )
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if message_lower in ["limpar memoria persistente", "limpar memória persistente"]:
            count = self.memory_store.clear_long_term_memories()
            self.add_message(PUBLIC_NAME, f"Apaguei {count} memórias persistentes. O histórico das conversas foi mantido.", is_jarvis=True)
            return True

        # -----------------------------------------------------
        # ARQUIVOS / PASTAS / WINDOWS
        # -----------------------------------------------------
        if message_lower in ["bloqueie o computador", "bloquear computador", "bloqueie o pc", "bloquear pc"]:
            self.add_message(PUBLIC_NAME, self.actions.lock_pc(), is_jarvis=True)
            return True

        if starts_with_any(["abra a pasta", "abra pasta", "abrir pasta"]):
            path = remove_prefix(["abra a pasta", "abra pasta", "abrir pasta"])
            self.add_message(PUBLIC_NAME, self.actions.open_path(path), is_jarvis=True)
            return True

        if message_lower in {"crie pasta no desktop", "crie pasta na area de trabalho", "criar pasta na area de trabalho"}:
            self.add_message(PUBLIC_NAME, "Qual nome voce quer dar para a pasta?", is_jarvis=True)
            return True

        desktop_folder = re.match(r"^crie\s+pasta\s+no\s+desktop\s+(.+)$", message, flags=re.I)
        if desktop_folder:
            name = desktop_folder.group(1).strip().strip('"')
            self.add_message(PUBLIC_NAME, self.actions.create_folder(f"desktop {name}"), is_jarvis=True)
            return True

        if starts_with_any(["crie a pasta", "crie pasta", "criar pasta", "cria pasta"]):
            path = remove_prefix(["crie a pasta", "crie pasta", "criar pasta", "cria pasta"])
            self.add_message(PUBLIC_NAME, self.actions.create_folder(path), is_jarvis=True)
            return True

        if starts_with_any(["procure arquivo", "procurar arquivo", "busque arquivo", "buscar arquivo", "ache arquivo"]):
            query = remove_prefix(["procure arquivo", "procurar arquivo", "busque arquivo", "buscar arquivo", "ache arquivo"])
            self.add_message(PUBLIC_NAME, self.actions.find_files(query), is_jarvis=True)
            return True

        copy_match = re.match(r"^(?:copie|copiar)\s+(.+?)\s+(?:para|pra)\s+(.+)$", message, flags=re.I)
        if copy_match:
            self.add_message(PUBLIC_NAME, self.actions.copy_path(copy_match.group(1), copy_match.group(2)), is_jarvis=True)
            return True

        move_match = re.match(r"^(?:mova|mover)\s+(.+?)\s+(?:para|pra)\s+(.+)$", message, flags=re.I)
        if move_match:
            self.add_message(PUBLIC_NAME, self.actions.move_path(move_match.group(1), move_match.group(2)), is_jarvis=True)
            return True

        if starts_with_any(["abra o site", "abra site", "abrir site", "acesse", "acessar"]):
            address = remove_prefix(["abra o site", "abra site", "abrir site", "acesse", "acessar"])
            self.add_message(PUBLIC_NAME, self.actions.open_website(address), is_jarvis=True)
            return True

        # -----------------------------------------------------
        # LEMBRETES PERSISTENTES / PLUGINS / SPOTIFY
        # -----------------------------------------------------
        reminder_match = re.match(
            r"^(?:me lembre|lembre-me|crie um lembrete)\s+em\s+(\d+)\s*(minutos?|mins?|horas?)\s+(?:de|para)\s+(.+)$",
            message,
            flags=re.I
        )
        if reminder_match:
            from datetime import datetime, timedelta
            amount = int(reminder_match.group(1))
            unit = reminder_match.group(2).lower()
            task = reminder_match.group(3).strip()
            delta = timedelta(hours=amount) if "hora" in unit else timedelta(minutes=amount)
            due = datetime.now() + delta
            rid = self.memory_store.create_reminder(task, due)
            self.add_message(PUBLIC_NAME, f"Lembrete #{rid} salvo para {due.strftime('%d/%m às %H:%M')}: {task}", is_jarvis=True)
            return True

        if message_lower in ["meus lembretes", "listar lembretes", "liste meus lembretes"]:
            items = self.memory_store.list_pending_reminders()
            if not items:
                result = "Você não tem lembretes pendentes."
            else:
                lines = ["Lembretes pendentes:"]
                for item in items:
                    lines.append(f"- #{item['id']} {item['due_at']}: {item['task']}")
                result = "\n".join(lines)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if message_lower in [
            "escolha uma musica", "escolhe uma musica",
            "escolha uma música", "escolhe uma música",
        ]:
            self._post_context_ui_call(self._update_status, "REPRODUZINDO", "#31D47D")
            result = self.actions.choose_music()
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        spotify_prefixes = ["toque no spotify", "tocar no spotify", "spotify"]
        if starts_with_any(spotify_prefixes):
            query = remove_prefix(spotify_prefixes).strip()
            self.add_message(PUBLIC_NAME, self.actions.play_spotify(query), is_jarvis=True)
            return True

        if message_lower in ["recarregue plugins", "recarregar plugins", "atualize plugins"]:
            count = self.plugin_manager.reload()
            self.add_message(PUBLIC_NAME, f"Plugins recarregados: {count}.", is_jarvis=True)
            return True

        if message_lower in ["listar plugins", "meus plugins", "plugins"]:
            names = self.plugin_manager.list_plugins()
            result = "Plugins: " + (", ".join(names) if names else "nenhum")
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if message_lower in ["meus habitos", "meus hábitos", "habitos aprendidos", "hábitos aprendidos", "padroes aprendidos", "padrões aprendidos"]:
            if self.behavior_memory is None:
                result = "A memória comportamental não está disponível nesta sessão."
            else:
                patterns = self.behavior_memory.top_patterns(limit=6)
                sequences = self.behavior_memory.top_sequences(limit=4) if hasattr(self.behavior_memory, "top_sequences") else []
                actions = self.behavior_memory.top_actions(limit=5) if hasattr(self.behavior_memory, "top_actions") else []
                if not patterns and not sequences and not actions:
                    result = "Ainda não observei um padrão forte o bastante. Continuo aprendendo apenas metadados locais de uso."
                else:
                    lines = ["Padrões que aprendi localmente:"]
                    for item in patterns:
                        lines.append(f"• Apps: {item['from_app']} → {item['to_app']} ({item['count']} vezes)")
                    for item in sequences:
                        lines.append(f"• Sequência: {item['app_a']} → {item['app_b']} → {item['app_c']} ({item['count']} vezes)")
                    for item in actions:
                        target = f" {item['target']}" if item.get('target') else ""
                        ctx = f" enquanto {item['context_app']} está ativo" if item.get('context_app') else ""
                        lines.append(f"• Ação: {item['action']}{target}{ctx} ({item['count']} vezes)")
                    result = "\n".join(lines)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # PESQUISA WEB EXPLICITA
        # -----------------------------------------------------
        search_prefixes = [
            "pesquise", "pesquisar", "pesquisa", "procure", "procurar",
            "busque", "buscar", "search", "pesquise na internet",
            "procure na internet", "busque na internet"
        ]
        if starts_with_any(search_prefixes):
            self._post_context_ui_call(self._update_status, "PESQUISANDO", "#3C8DFF")
            query = remove_prefix(search_prefixes)
            # Remove "sobre" quando usado naturalmente: "pesquise sobre X"
            if query.lower().startswith("sobre "):
                query = query[6:].strip()

            result = self.web_search.search(query)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # FECHAR APLICATIVO - MODO DIRETO
        # -----------------------------------------------------
        close_prefixes = [
            "feche", "fecha", "fechar", "encerre", "encerrar",
            "finalize", "finalizar", "close"
        ]
        if starts_with_any(close_prefixes):
            app_name = remove_prefix(
                close_prefixes
            )

            if not app_name:
                self.add_message(
                    PUBLIC_NAME,
                    "Qual aplicativo devo fechar?",
                    is_jarvis=True
                )
                return True

            result = self.actions.close_application(app_name)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # ABRIR APLICATIVO
        # -----------------------------------------------------
        open_prefixes = [
            "abra", "abrir", "abre", "inicie", "iniciar",
            "execute", "executar", "open", "start"
        ]
        if starts_with_any(open_prefixes):
            self._post_context_ui_call(self._update_status, "EXECUTANDO", "#8E6BFF")
            app_name = remove_prefix(open_prefixes)

            if app_name:
                # Linguagem natural: "abra o Opera" / "abra a Calculadora".
                app_name = re.sub(
                    r"^(?:o|a|os|as)\s+",
                    "",
                    app_name,
                    flags=re.I,
                ).strip()
                app_name_lower = app_name.lower().strip()

                app_aliases = {
                    "gerenciador de arquivos": "explorer",
                    "gerenciador de arquivo": "explorer",
                    "explorador de arquivos": "explorer",
                    "explorador de arquivo": "explorer",
                    "meus arquivos": "explorer",
                    "paint": "paint",
                }
                app_name = app_aliases.get(app_name_lower, app_name)
                app_name_lower = app_name.lower().strip()

                # YouTube é um site/serviço, não um programa instalado.
                if app_name_lower in [
                    "youtube",
                    "o youtube",
                    "site youtube",
                    "site do youtube"
                ]:
                    result = self.actions.open_youtube()
                else:
                    result = self.actions.open_application(app_name)
            else:
                result = "Qual aplicativo devo abrir?"

            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # ENERGIA AGENDADA - CONFIRMA E USA TIMER NATIVO WINDOWS
        # -----------------------------------------------------
        cancel_power_key = self._local_strip_accents(message_lower).lower()
        if re.fullmatch(r"(?:cancela|cancelar|cancele|aborta|abortar) (?:o )?(?:desligamento|reinicio|reiniciamento)(?: agendado)?", cancel_power_key):
            result = self.actions.cancel_scheduled_power()
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        power_timer = re.match(
            r"^(desligar|desligue|desliga|reiniciar|reinicie|reinicia|restart|shutdown)"
            r"(?:\s+(?:o|meu))?(?:\s+(?:pc|computador|sistema))?"
            r"\s+(?:daqui\s+a|em)\s+(\d{1,5})\s*(segundos?|secs?|s|minutos?|mins?|m|horas?|hrs?|h)$",
            cancel_power_key, flags=re.I,
        )
        if power_timer:
            verb = power_timer.group(1).lower()
            amount = max(1, int(power_timer.group(2)))
            unit = power_timer.group(3).lower()
            multiplier = 3600 if unit.startswith(("h", "hora")) else 60 if unit.startswith(("m", "min")) else 1
            seconds = min(amount * multiplier, 7 * 24 * 3600)
            action = "restart" if verb.startswith(("rein", "restart")) else "shutdown"
            label = "reiniciar" if action == "restart" else "desligar"
            self._request_confirmation(
                f"{label} o computador daqui a {amount} {unit}",
                lambda a=action, sec=seconds: self.actions.schedule_power_action(a, sec),
                source_command=message,
            )
            return True

        # -----------------------------------------------------
        # ENERGIA - SEMPRE CONFIRMA
        # -----------------------------------------------------
        if starts_with_any(
            ["desligar", "desligue", "desliga", "shutdown"]
        ):
            self._request_confirmation(
                "desligar o computador",
                lambda: self.actions.confirm_power_action(
                    "shutdown"
                ),
                source_command=message
            )
            return True

        if starts_with_any(
            ["reiniciar", "reinicie", "restart", "reboot"]
        ):
            self._request_confirmation(
                "reiniciar o computador",
                lambda: self.actions.confirm_power_action(
                    "restart"
                ),
                source_command=message
            )
            return True

        if starts_with_any(
            ["suspender", "suspenda", "hibernar", "dormir", "sleep"]
        ):
            result = self.actions.execute_power_command("suspend")
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # VOLUME - NAO CONFUNDE PERGUNTAS SOBRE AUDIO
        # -----------------------------------------------------
        volume_patterns = [
            r"^(?:volume(?:\s+do\s+sistema)?\s+(?:em|para|a)\s+)(\d{1,3})%?$",
            r"^(?:coloque|coloca|ajuste|ajusta|defina|define)\s+(?:o\s+)?volume\s+(?:em|para|a)\s+(\d{1,3})%?$",
            r"^(?:abaixe|abaixa|baixe|baixa|diminua|diminui)\s+(?:o\s+)?volume\s+(?:para|em)\s+(\d{1,3})%?$",
            r"^(?:aumente|aumenta|suba|sobe)\s+(?:o\s+)?volume\s+(?:para|em)\s+(\d{1,3})%?$",
        ]

        for volume_pattern in volume_patterns:
            volume_match = re.match(volume_pattern, message_lower, flags=re.I)
            if volume_match:
                self._post_context_ui_call(self._update_status, "EXECUTANDO", "#8E6BFF")
                result = self.actions.set_volume(volume_match.group(1))
                try:
                    actual = self.actions.get_volume_percent()
                    if actual is not None:
                        self._post_context_ui_call(self._set_volume_ui, actual)
                except Exception:
                    pass
                self.add_message(PUBLIC_NAME, result, is_jarvis=True)
                return True

        # -----------------------------------------------------
        # FUNCOES LOCAIS EXPLICITAS
        # -----------------------------------------------------
        if starts_with_any(["verificar atualizacoes", "verifique atualizacoes", "checar atualizacoes"]):
            result = self.actions.open_application("atualizacoes")
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if message_lower in ["status do sistema", "sistema status", "status sistema", "uso do sistema"]:
            result = self.actions.get_system_status()
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if starts_with_any(["tire um print", "tirar print", "capture a tela", "capturar tela", "screenshot", "print screen"]):
            monitor_match = re.search(r"(?:monitor|monito|tela|display)\s*(\d+)", message_lower, flags=re.I)
            monitor_index = int(monitor_match.group(1)) if monitor_match else None
            result = self._take_screenshot_local(monitor_index=monitor_index)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if starts_with_any(["gerar senha", "criar senha", "gere uma senha", "crie uma senha"]):
            match = re.search(r"\d+", message_lower)
            length = int(match.group()) if match else 16
            result = self.actions.generate_password(length)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if starts_with_any(["me lembre", "crie um lembrete", "criar lembrete"]):
            time_match = re.search(r"(\d+)\s*(?:minuto| minutos|min|mins)", message_lower)
            time_str = time_match.group() if time_match else "30"
            task_match = re.search(r"(?:de|para)\s+(.+)", message_lower)
            task = task_match.group(1) if task_match else "tarefa nao especificada"
            result = self.actions.set_reminder(time_str, task)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # Informacoes que envelhecem rapido usam o Gemini com Google Search
        # grounding. As rotas antigas de clima/noticias ficam apenas como
        # fallback de compatibilidade dentro de Actions.
        if message_lower in ["tempo hoje", "clima hoje", "previsao do tempo", "tempo agora", "clima agora"]:
            self._post_context_ui_call(self._update_status, "PESQUISANDO", "#3C8DFF")
            self._post_context_ui_call(self._set_source_badge, "WEB")
            result = self.web_search.search(f"{message}. Responda com informacao atual e diga a localidade usada se ela puder ser inferida pelo contexto.")
            self._post_context_ui_call(self._show_jarvis_response, result, True)
            return True

        if message_lower in ["noticias", "manchetes", "noticia do dia", "jornal"]:
            self._post_context_ui_call(self._update_status, "PESQUISANDO", "#3C8DFF")
            self._post_context_ui_call(self._set_source_badge, "WEB")
            result = self.web_search.search("principais noticias de hoje, priorizando fatos recentes e fontes confiaveis")
            self._post_context_ui_call(self._show_jarvis_response, result, True)
            return True

        current_info_match = re.fullmatch(
            r"(?:qual (?:e|é) (?:a )?|me diga (?:a )?)?(?:cotacao|cotação|preco|preço|valor) (?:do |da )?(dolar|dólar|euro|bitcoin|libra)(?: hoje| agora)?",
            message_lower,
            flags=re.I,
        )
        if current_info_match:
            asset = current_info_match.group(1)
            self._post_context_ui_call(self._update_status, "PESQUISANDO", "#3C8DFF")
            self._post_context_ui_call(self._set_source_badge, "WEB")
            result = self.web_search.search(f"cotacao atual de {asset} em reais brasileiros BRL hoje")
            self._post_context_ui_call(self._show_jarvis_response, result, True)
            return True

        if starts_with_any(
            ["limpar lixeira", "esvaziar lixeira"]
        ):
            self._request_confirmation(
                "esvaziar a Lixeira",
                (
                    lambda: self.safety_manager.empty_recycle_bin()
                    if self.safety_manager
                    else self.actions.empty_recycle_bin()
                ),
                source_command=message
            )
            return True

        if starts_with_any(["aumentar brilho", "aumente o brilho", "mais brilho"]):
            result = self.actions.adjust_brightness("aumentar")
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if starts_with_any(["diminuir brilho", "diminua o brilho", "menos brilho", "escurecer"]):
            result = self.actions.adjust_brightness("diminuir")
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        if message_lower in ["processos", "processos ativos", "top processos", "uso de memoria"]:
            result = self.actions.get_top_processes()
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # CONTROLE DE MIDIA
        # -----------------------------------------------------
        pause_commands = {
            "pause", "pausa", "pause a musica", "pause a música",
            "pausar musica", "pausar música",
        }
        play_commands = {
            "play", "resume", "retomar", "continuar", "continue", "continua",
            "continue a musica", "continue a música", "retome",
            "retomar musica", "retomar música",
        }
        next_commands = {
            "proxima", "próxima", "proxima musica", "próxima música",
            "proximo", "próximo", "proxima faixa", "próxima faixa",
        }
        previous_commands = {
            "volta", "anterior", "musica anterior", "música anterior", "faixa anterior",
        }
        stop_commands = {"pare a musica", "pare a música", "parar musica", "parar música"}

        target_hint = self._current_media_target()
        if message_lower in pause_commands:
            result = self.actions.media_pause(target_hint=target_hint)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True
        if message_lower in play_commands:
            result = self.actions.media_play(target_hint=target_hint)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True
        if message_lower in next_commands:
            result = self.actions.media_next_track(target_hint=target_hint)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True
        if message_lower in previous_commands:
            result = self.actions.media_previous_track(target_hint=target_hint)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True
        if message_lower in stop_commands:
            result = self.actions.media_stop(target_hint=target_hint)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        media_exact_commands = {
            "mute": self.actions.media_mute,
            "mudo": self.actions.media_mute,
            "silencie": self.actions.media_mute,
            "tire o som": self.actions.media_mute,
            "aumente o volume": self.actions.media_volume_up,
            "aumenta o volume": self.actions.media_volume_up,
            "abaixe o volume": self.actions.media_volume_down,
            "abaixa o volume": self.actions.media_volume_down,
            "diminua o volume": self.actions.media_volume_down,
            "diminui o volume": self.actions.media_volume_down,
        }
        if message_lower in media_exact_commands:
            result = media_exact_commands[message_lower]()
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # MUSICA / YOUTUBE
        # -----------------------------------------------------
        # Aceita frases naturais como:
        # "toque Livin' on a Prayer"
        # "coloca musica Livin' on a Prayer"
        # "colocar música Livin' on a Prayer"
        # "bota Livin' on a Prayer no youtube"
        music_prefixes = [
            "toque",
            "tocar",
            "reproduza",
            "reproduzir",
            "coloque para tocar",
            "coloca para tocar",
            "colocar para tocar",
            "coloque musica",
            "coloque música",
            "coloque a musica",
            "coloque a música",
            "coloca musica",
            "coloca música",
            "coloca a musica",
            "coloca a música",
            "colocar musica",
            "colocar música",
            "colocar a musica",
            "colocar a música",
            "bota musica",
            "bota música",
            "bota a musica",
            "bota a música",
            "bote musica",
            "bote música",
            "bote a musica",
            "bote a música",
            "ponha musica",
            "ponha música",
            "ponha a musica",
            "ponha a música"
        ]

        if starts_with_any(music_prefixes):
            query = remove_prefix(music_prefixes).strip(" \t,;:-")

            # Limpa complementos naturais.
            suffixes = [
                " no youtube",
                " no youtube music",
                " no opera",
                " no opera gx"
            ]

            query_lower = query.lower()

            for suffix in suffixes:
                if query_lower.endswith(suffix):
                    query = query[:len(query) - len(suffix)].strip()
                    query_lower = query.lower()
                    break

            if query:
                self._post_context_ui_call(self._update_status, "REPRODUZINDO", "#31D47D")
                self.last_media_title = query
                if self.media_value_label:
                    self.media_value_label.configure(text=query)
                result = self.actions.play_music(query)
            else:
                result = "Qual música devo tocar?"

            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # -----------------------------------------------------
        # APELIDOS DE APLICATIVOS ENSINADOS
        # -----------------------------------------------------
        # Permite dizer apenas "chat gpt" ou "comercial" depois que o
        # aplicativo foi ensinado, sem exigir "abra" toda vez.
        try:
            alias_key = self.actions._normalize_app_name(
                message_lower.rstrip(".?!,;:")
            )
            if alias_key and alias_key in self.actions.app_aliases:
                self._post_context_ui_call(self._update_status, "EXECUTANDO", "#8E6BFF")
                result = self.actions.open_application(alias_key)
                self.add_message(PUBLIC_NAME, result, is_jarvis=True)
                return True
        except Exception:
            pass

        # Pomodoro somente quando o usuario realmente pedir um timer/pomodoro.
        if starts_with_any(["inicie pomodoro", "iniciar pomodoro", "pomodoro", "inicie timer", "timer", "cronometro"]):
            result = self.actions.start_pomodoro_timer("Foco")
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # Atalhos diretos somente quando a mensagem inteira for o nome do app.
        direct_apps = [
            "notepad", "bloco de notas", "calculadora", "calc", "calculator",
            "configuracoes", "settings", "painel de controle", "cmd", "prompt",
            "terminal", "powershell", "explorer", "task manager",
            "gerenciador de tarefas", "defender", "windows defender", "antivirus"
        ]

        if message_lower in direct_apps:
            result = self.actions.open_application(message_lower)
            self.add_message(PUBLIC_NAME, result, is_jarvis=True)
            return True

        # Qualquer outra mensagem vai para o Gemini.
        return False

    def _show_power_confirmation(self, action: str):
        """Mostra diálogo de confirmação para comandos de energia"""
        # Cria janela de confirmação
        confirm_window = ctk.CTkToplevel(self.root)
        confirm_window.title("🔌 Confirmação de Energia")
        confirm_window.geometry("400x200")
        confirm_window.configure(fg_color=Config.get_color("surface"))
        confirm_window.transient(self.root)
        confirm_window.grab_set()
        
        # Centraliza
        confirm_window.update_idletasks()
        x = (confirm_window.winfo_screenwidth() // 2) - 200
        y = (confirm_window.winfo_screenheight() // 2) - 100
        confirm_window.geometry(f"400x200+{x}+{y}")
        
        # Frame principal
        main_frame = ctk.CTkFrame(confirm_window, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Mensagem
        action_names = {"shutdown": "Desligamento", "restart": "Reinicialização"}
        action_name = action_names.get(action, action.title())
        
        message_label = ctk.CTkLabel(
            main_frame,
            text=f"🔌 {action_name} do Sistema\n\nos sistemas serão encerrados.\nConfirma o protocolo?",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=Config.get_color("ia_text"),
            wraplength=350
        )
        message_label.pack(pady=(20, 10))
        
        # Frame dos botões
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=10)
        
        # Botão Não
        no_button = ctk.CTkButton(
            button_frame,
            text="❌ Não",
            width=80,
            height=35,
            font=ctk.CTkFont(family="Bahnschrift", size=12, weight="bold"),
            fg_color="#FF4444",
            hover_color="#CC0000",
            command=lambda: self._cancel_power_action(confirm_window)
        )
        no_button.pack(side="left", padx=(50, 10), expand=True)
        
        # Botão Sim
        yes_button = ctk.CTkButton(
            button_frame,
            text="✅ Sim",
            width=80,
            height=35,
            font=ctk.CTkFont(family="Bahnschrift", size=12, weight="bold"),
            fg_color="#44FF44",
            hover_color="#00CC00",
            command=lambda: self._confirm_power_action(confirm_window, action)
        )
        yes_button.pack(side="right", padx=(10, 50), expand=True)
        
        confirm_window.focus_set()
    
    def _cancel_power_action(self, window):
        """Cancela ação de energia"""
        window.destroy()
        self.add_message(PUBLIC_NAME, "🔌 Ação de energia cancelada.", is_jarvis=True)
    
    def _confirm_power_action(self, window, action: str):
        """Confirma e executa ação de energia"""
        window.destroy()
        result = self.actions.confirm_power_action(action)
        self.add_message(PUBLIC_NAME, result, is_jarvis=True)
    
    def _format_message_time(self, timestamp=None):
        """Normaliza timestamps antigos e novos para HH:MM."""
        try:
            if timestamp is None:
                dt = datetime.now()
            elif isinstance(timestamp, (int, float)):
                dt = datetime.fromtimestamp(timestamp)
            else:
                raw = str(timestamp).strip()
                try:
                    dt = datetime.fromisoformat(raw)
                except Exception:
                    dt = datetime.fromtimestamp(float(raw))

            return dt.strftime("%H:%M")
        except Exception:
            return datetime.now().strftime("%H:%M")

    def _install_chat_mousewheel(self):
        """Instala scroll somente no chat, sem duplicar o bind global do CTk."""
        if self._chat_wheel_bound or not self.chat_scroll:
            return
        try:
            canvas = self.chat_scroll._parent_canvas
            self._bind_chat_mousewheel_tree(canvas)
            self._bind_chat_mousewheel_tree(self.chat_scroll)
            self._chat_wheel_bound = True
        except Exception:
            pass

    def _bind_chat_mousewheel_tree(self, widget):
        """Intercepta roda antes do bind_all do CTk apenas dentro da arvore do chat."""
        if widget is None:
            return
        try:
            widget.bind("<MouseWheel>", self._on_chat_mousewheel)
            widget.bind("<Button-4>", self._on_chat_mousewheel)
            widget.bind("<Button-5>", self._on_chat_mousewheel)
        except Exception:
            pass
        try:
            children = list(widget.winfo_children())
        except Exception:
            children = []
        for child in children:
            self._bind_chat_mousewheel_tree(child)

    def _widget_is_inside_chat(self, widget):
        target = self.chat_scroll
        if not widget or not target:
            return False

        current = widget
        for _ in range(20):
            if current is target:
                return True
            try:
                current = current.master
            except Exception:
                break
            if current is None:
                break
        return False

    def _on_chat_mousewheel(self, event):
        """Build 15: rolagem limitada, suave e resistente a touchpad/eventos duplicados."""
        if not self.chat_scroll:
            return None
        try:
            under_pointer = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            under_pointer = getattr(event, "widget", None)
        try:
            canvas = self.chat_scroll._parent_canvas
        except Exception:
            return None
        if not (self._widget_is_inside_chat(under_pointer) or under_pointer is canvas):
            return None

        try:
            num = getattr(event, "num", None)
            if num in (4, 5):
                notches = 1 if num == 5 else -1
            else:
                delta = int(getattr(event, "delta", 0) or 0)
                if delta == 0:
                    return "break"

                # Windows costuma mandar +/-120 por notch; touchpads podem mandar
                # deltas menores em rajadas. Acumulamos os menores em vez de
                # transformar cada microevento em dezenas de linhas.
                if abs(delta) < 120:
                    self._chat_wheel_remainder += delta
                    if abs(self._chat_wheel_remainder) < 120:
                        return "break"
                    delta = self._chat_wheel_remainder
                    self._chat_wheel_remainder = 0
                else:
                    self._chat_wheel_remainder = 0

                raw_notches = int(round(delta / 120.0))
                raw_notches = max(-3, min(3, raw_notches or (1 if delta > 0 else -1)))
                # Positivo = roda para cima; yview negativo sobe.
                notches = -raw_notches

            # Antes eram ate 168 unidades por evento. Agora o teto e 12,
            # suficiente para ser rapido sem "disparar" ate o fim do historico.
            steps = max(-12, min(12, int(notches) * 4))
            if steps:
                canvas.yview_scroll(steps, "units")

            _first, last = canvas.yview()
            self._chat_auto_scroll = bool(last >= 0.992)
            # Um gesto manual vence o auto-scroll do streaming por um curto
            # intervalo; isso impede a disputa visual "sobe/desce".
            self._chat_manual_scroll_until = time.monotonic() + 0.85
            return "break"
        except Exception:
            return None

    def _clear_stream_chunk_queue(self):
        """Descarta chunks pendentes e libera a trava de flush entre turnos."""
        try:
            while True:
                self._stream_chunk_queue.get_nowait()
        except queue.Empty:
            pass
        except Exception:
            pass
        self._stream_flush_requested.clear()

    def _queue_stream_chunk_threadsafe(self, token, chunk):
        if not chunk:
            return
        try:
            self._stream_chunk_queue.put_nowait((int(token), str(chunk)))
        except Exception:
            return
        if not self._stream_flush_requested.is_set():
            self._stream_flush_requested.set()
            self._post_ui_event("stream_flush", int(token))

    def _flush_stream_chunks_ui(self, token: int = 0):
        """Agrupa tokens e descarta qualquer chunk pertencente a um turno antigo."""
        chunks = []
        deferred = []
        active = int(token or self._active_stream_token or 0)
        while True:
            try:
                item_token, chunk = self._stream_chunk_queue.get_nowait()
            except queue.Empty:
                break
            if int(item_token) == active and self._work_is_current(active):
                chunks.append(chunk)
            elif int(item_token) > active:
                deferred.append((item_token, chunk))
        for item in deferred:
            try:
                self._stream_chunk_queue.put_nowait(item)
            except Exception:
                pass

        self._stream_flush_requested.clear()
        if chunks and active == self._active_stream_token and self._work_is_current(active):
            self._append_streaming_chunk("".join(chunks))

        if not self._stream_chunk_queue.empty() and not self._stream_flush_requested.is_set():
            self._stream_flush_requested.set()
            next_token = self._active_stream_token or active
            self._post_ui_event("stream_flush", int(next_token))

    @staticmethod
    def _estimate_chat_textbox_height(text: str) -> int:
        """Estima altura com margem para linhas realmente quebradas no CTkTextbox."""
        raw = str(text or "")
        logical_lines = raw.splitlines() or [""]
        visual_lines = 0
        # Em 420 px com Tahoma 13, ~52 caracteres por linha é uma margem
        # conservadora. A estimativa antiga usava 82-88 e cortava frases.
        for line in logical_lines:
            length = max(1, len(line.expandtabs(4)))
            visual_lines += max(1, (length + 51) // 52)
        return min(max(40, visual_lines * 24 + 18), 3200)

    def _create_chat_bubble(
        self, sender, message, is_user=False, is_jarvis=False, is_system=False, timestamp=None, suppress_autoscroll=False
    ):
        """V6: mensagens clean; resposta do JARVIS sem balão pesado, usuário em pill discreta."""
        if not self.chat_scroll:
            return None
        row = ctk.CTkFrame(self.chat_scroll, fg_color="#212121")
        row.pack(fill="x", padx=18, pady=8)

        if is_user:
            bubble_color, border, text_color, anchor_side = "#303030", "#3E3E3E", "#F4F4F4", "right"
            sender_color = "#BDBDBD"
        elif is_system:
            bubble_color, border, text_color, anchor_side = "#252525", "#353535", "#BDBDBD", "left"
            sender_color = "#888888"
        else:
            bubble_color, border, text_color, anchor_side = "#212121", "#212121", "#ECECEC", "left"
            sender_color = "#7AB7FF"

        bubble = ctk.CTkFrame(row, fg_color=bubble_color, corner_radius=14 if is_user else 0, border_width=1 if is_user or is_system else 0, border_color=border)
        if is_user:
            bubble.pack(side="right", padx=(70, 4), ipadx=2, ipady=1)
        else:
            bubble.pack(fill="x", padx=(4, 34), ipadx=2, ipady=1)

        meta_row = ctk.CTkFrame(bubble, fg_color="transparent")
        meta_row.pack(fill="x", padx=12, pady=(7, 1))
        display_sender = PUBLIC_NAME if is_jarvis else sender
        ctk.CTkLabel(
            meta_row, text=("VOCÊ" if is_user else str(display_sender).upper()),
            font=ctk.CTkFont(family="Tahoma", size=9, weight="bold"), text_color=sender_color
        ).pack(side="left")
        ctk.CTkLabel(
            meta_row, text=self._format_message_time(timestamp),
            font=ctk.CTkFont(family="Consolas", size=8), text_color="#888E98"
        ).pack(side="right", padx=(12, 0))

        initial_text = message or ""
        textbox_height = self._estimate_chat_textbox_height(initial_text)
        msg_label = ctk.CTkTextbox(
            bubble, width=420, height=textbox_height, wrap="word", activate_scrollbars=False,
            font=ctk.CTkFont(family="Tahoma", size=13), text_color=text_color,
            fg_color="transparent", border_width=0, corner_radius=0
        )
        msg_label.pack(fill="x", expand=True, padx=8, pady=(0, 8))
        msg_label.insert("1.0", initial_text)
        msg_label.configure(state="disabled")

        # Cada bolha e seus filhos interceptam o wheel antes do bind_all interno
        # do CustomTkinter. Assim o evento e processado exatamente uma vez.
        self._bind_chat_mousewheel_tree(row)
        msg_label.bind("<Control-c>", lambda event, widget=msg_label: self._copy_text_selection(widget))
        msg_label.bind("<Control-C>", lambda event, widget=msg_label: self._copy_text_selection(widget))

        if not suppress_autoscroll and not self._restoring_history:
            if is_user:
                self._chat_auto_scroll = True
                self._schedule_chat_scroll(force=True, delay=10)
            else:
                self._schedule_chat_scroll(force=False, delay=10)
        return msg_label

    def _set_message_text(self, widget, text: str):
        """Atualiza uma bolha CTkTextbox mantendo-a somente leitura."""
        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text or "")

            target_height = self._estimate_chat_textbox_height(text or "")
            try:
                current_height = int(float(widget.cget("height")))
            except Exception:
                current_height = -1
            if current_height != target_height:
                widget.configure(height=target_height)
            widget.configure(state="disabled")
        except Exception as e:
            self.logger.error(e, "Erro ao atualizar bolha de texto", "GUI")

    def _copy_text_selection(self, widget):
        """Copia a seleção atual de uma mensagem."""
        try:
            selected = widget.selection_get()
            if selected:
                self.root.clipboard_clear()
                self.root.clipboard_append(selected)
                self.root.update()
                return "break"
        except Exception:
            pass
        return None

    def _conversation_as_text(self):
        """Converte o histórico do chat para texto simples copiável."""
        parts = [f"=== {PUBLIC_NAME} - CONVERSA ===", ""]

        for item in self.chat_history:
            sender = item.get("sender", "")
            if item.get("is_jarvis"):
                sender = PUBLIC_NAME
            message = item.get("message", "")
            parts.append(f"{sender}:")
            parts.append(str(message))
            parts.append("")

        return "\n".join(parts).strip()

    def _logs_as_text(self):
        """Obtém os logs atualmente disponíveis."""
        try:
            logs = self.logger.get_buffer_logs(100)
            if logs:
                return "\n".join(str(log) for log in logs)
        except Exception:
            pass

        try:
            if self.system_log_text:
                return self.system_log_text.get("1.0", "end").strip()
        except Exception:
            pass

        return "(sem logs disponíveis)"

    def _copy_to_clipboard(self, text: str):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
            self._update_status("COPIADO", "#31D47D")
            self.root.after(
                1200,
                self._update_status,
                "ONLINE",
                Config.get_color("success")
            )
        except Exception as e:
            self.logger.error(e, "Erro ao copiar para área de transferência", "GUI")

    def _copy_conversation(self):
        """Copia toda a conversa para a área de transferência."""
        self._copy_to_clipboard(self._conversation_as_text())

    def _copy_everything(self):
        """Copia conversa, status e logs para facilitar diagnóstico."""
        try:
            status = self.status_label.cget("text") if self.status_label else "?"
        except Exception:
            status = "?"

        content = (
            self._conversation_as_text()
            + "\n\n=== STATUS ===\n"
            + str(status)
            + "\n\n=== MEMÓRIA LOCAL ===\n"
            + f"Conversa ativa: {self.active_conversation_id}\n"
            + f"Banco: {self.memory_store.db_path}\n"
            + "\n=== LOGS ===\n"
            + self._logs_as_text()
        )
        self._copy_to_clipboard(content)

    def _schedule_chat_scroll(self, force: bool = False, delay: int = 12):
        """Agrupa pedidos de auto-scroll para nunca criar uma fila infinita de after()."""
        if not self.root:
            return
        try:
            if self._chat_scroll_job is not None:
                self.root.after_cancel(self._chat_scroll_job)
        except Exception:
            pass
        try:
            self._chat_scroll_job = self.root.after(
                max(0, int(delay)), lambda: self._scroll_chat_to_bottom(force=force)
            )
        except Exception:
            self._chat_scroll_job = None

    def _scroll_chat_to_bottom(self, force: bool = False):
        self._chat_scroll_job = None
        try:
            if not self.chat_scroll:
                return
            if not force:
                if not self._chat_auto_scroll:
                    return
                if time.monotonic() < float(self._chat_manual_scroll_until or 0.0):
                    return

            canvas = self.chat_scroll._parent_canvas
            # update_idletasks() em cada token podia realimentar a fila de layout.
            # yview_moveto e idempotente e o Tk atualiza no proprio ciclo.
            canvas.yview_moveto(1.0)
            self._chat_auto_scroll = True
        except Exception:
            pass

    def _queue_voice_stream_tts_ready(self, force: bool = False):
        """V6: primeiro áudio cedo, próximos blocos já enfileirados para fala contínua."""
        if not self._voice_command_active or not self.voice_engine:
            return
        buffer = self._voice_stream_tts_buffer
        if not buffer:
            return
        chunks = []
        count = int(getattr(self, "_voice_stream_tts_queued_count", 0))

        if count == 0:
            # Prioridade: uma frase curta deve sair INTEIRA. Cortar cedo por
            # contagem de caracteres gerava exatamente "mais alguma" ... "coisa".
            # Só iniciamos antes do ponto final quando existe uma pausa sintática
            # natural e o trecho já tem corpo suficiente.
            window = buffer[:320]
            # 13.11.6: frases iniciais curtas ("Certo, senhor.") nao precisam
            # esperar um segundo paragrafo para iniciar o TTS.
            boundaries = [m.end() for m in re.finditer(r"[.!?]\s+|\n+", window) if m.end() >= 18]
            if boundaries:
                cut = boundaries[0]
            elif len(buffer) >= 170:
                natural = max(
                    buffer.rfind(", ", 105, min(len(buffer), 205)),
                    buffer.rfind("; ", 105, min(len(buffer), 205)),
                    buffer.rfind(": ", 105, min(len(buffer), 205)),
                )
                if natural >= 0:
                    cut = natural + 1
                elif len(buffer) >= 260:
                    cut = buffer.rfind(" ", 190, 245)
                    if cut < 0:
                        cut = min(230, len(buffer))
                elif force:
                    cut = len(buffer)
                else:
                    return
            elif force:
                cut = len(buffer)
            else:
                return
            chunk = buffer[:cut].strip()
            buffer = buffer[cut:].lstrip()
            if chunk:
                chunks.append(chunk); count += 1

        # Próximos blocos também respeitam fronteiras naturais. É melhor alguns
        # milissegundos a mais de buffer do que uma pausa audível no meio da ideia.
        while not force and len(buffer) >= 300 and len(chunks) < 2:
            window = buffer[:500]
            boundaries = [m.end() for m in re.finditer(r"[.!?]\s+|\n+", window) if 140 <= m.end() <= 460]
            if boundaries:
                cut = boundaries[-1]
            else:
                natural = max(
                    buffer.rfind(", ", 210, min(len(buffer), 390)),
                    buffer.rfind("; ", 210, min(len(buffer), 390)),
                    buffer.rfind(": ", 210, min(len(buffer), 390)),
                )
                if natural >= 0:
                    cut = natural + 1
                elif len(buffer) >= 460:
                    cut = buffer.rfind(" ", 300, 430)
                    if cut < 0:
                        cut = min(390, len(buffer))
                else:
                    break
            chunk = buffer[:cut].strip()
            buffer = buffer[cut:].lstrip()
            if not chunk:
                break
            chunks.append(chunk); count += 1

        if force and buffer:
            # O engine/edge-tts sabe dividir internamente textos grandes; manter o
            # restante unido dá prosódia mais natural que parágrafo por parágrafo.
            chunks.append(buffer.strip())
            buffer = ""
            count += 1

        self._voice_stream_tts_buffer = buffer
        self._voice_stream_tts_queued_count = count
        for chunk in chunks:
            if chunk:
                try:
                    self.voice_engine.speak(chunk, wait=False, post_delay=0.0)
                    self._voice_stream_tts_started = True
                except Exception as e:
                    self.logger.warning(f"Falha no TTS progressivo: {e}", "VOICE")

    def _cancel_stream_render_job(self):
        job = self._stream_render_job
        self._stream_render_job = None
        self._stream_last_render_at = 0.0
        if job and self.root:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

    def _discard_streaming_visual(self):
        """Remove bolha parcial/orfã e zera o estado visual de streaming."""
        self._cancel_stream_render_job()
        label = self.streaming_label
        self.streaming_label = None
        self.streaming_buffer = ""
        self._active_stream_token = 0
        self._voice_stream_tts_buffer = ""
        self._voice_stream_tts_queued_count = 0
        if label is not None:
            try:
                bubble = label.master
                row = getattr(bubble, "master", None)
                (row or bubble).destroy()
            except Exception:
                try:
                    label.destroy()
                except Exception:
                    pass

    def _start_streaming_response(self, sender: str = PUBLIC_NAME, token: int = 0):
        """Cria bolha somente para o turno atualmente válido."""
        try:
            token = int(token or self._work_generation)
            if not self._work_is_current(token):
                return
            self._discard_streaming_visual()
            self._active_stream_token = token
            self._cancel_stream_render_job()
            self.streaming_buffer = ""
            self._voice_stream_tts_buffer = ""
            self._voice_stream_tts_started = False
            self._voice_stream_tts_queued_count = 0
            self.streaming_label = self._create_chat_bubble(
                sender, "", is_jarvis=(str(sender).upper() in {LEGACY_NAME, PUBLIC_NAME})
            )
            self._update_status("RESPONDENDO", "#3C8DFF")
            self._set_voice_overlay_speaking(True)
            self._set_voice_overlay_text(f"{PUBLIC_NAME} está respondendo...")
        except Exception as e:
            self.logger.error(e, "Erro ao iniciar streaming visual", "GUI")

    def _render_streaming_buffer_ui(self):
        """Redesenha o streaming em lotes: menos churn de Textbox, mesma latência percebida."""
        self._stream_render_job = None
        self._stream_last_render_at = time.perf_counter()
        try:
            self._set_voice_overlay_text(self.streaming_buffer)
            if self.streaming_label:
                self._set_message_text(self.streaming_label, self.streaming_buffer)
            self._scroll_chat_to_bottom()
        except Exception as e:
            self.logger.error(e, "Erro ao renderizar streaming", "GUI")

    def _append_streaming_chunk(self, chunk: str):
        if not chunk:
            return
        try:
            self.streaming_buffer += chunk

            if self._voice_command_active:
                self._voice_stream_tts_buffer += chunk
                self._queue_voice_stream_tts_ready(force=False)

            # No máximo ~30 redesenhos/s; tokens continuam chegando sem bloqueio.
            now = time.perf_counter()
            elapsed_ms = (now - float(self._stream_last_render_at or 0.0)) * 1000.0
            if elapsed_ms >= 32.0 and self._stream_render_job is None:
                self._render_streaming_buffer_ui()
            elif self._stream_render_job is None:
                delay = max(1, int(round(32.0 - elapsed_ms)))
                self._stream_render_job = self.root.after(delay, self._render_streaming_buffer_ui)
        except Exception as e:
            self.logger.error(e, "Erro ao exibir trecho do streaming", "GUI")

    def _finish_streaming_response(self, full_response: str, token: int = 0):
        try:
            token = int(token or self._active_stream_token or 0)
            if token != self._active_stream_token or not self._work_is_current(token):
                return
            self._cancel_stream_render_job()
            final_text = full_response or self.streaming_buffer
            if self.streaming_label and final_text:
                self._set_message_text(
                    self.streaming_label,
                    final_text
                )

            if final_text:
                self.chat_history.append({
                    'sender': PUBLIC_NAME,
                    'message': final_text,
                    'timestamp': time.time(),
                    'is_jarvis': True
                })

                if not self._restoring_history:
                    try:
                        self.memory_store.save_message(
                            self.active_conversation_id,
                            PUBLIC_NAME,
                            final_text,
                            is_jarvis=True
                        )
                        if self.root:
                            self._post_ui_call(self._refresh_conversation_list)
                    except Exception as e:
                        # Memória é auxiliar: jamais pode abortar TTS/streaming.
                        self.logger.error(e, "Erro ao persistir streaming", "MEMORY")

            self._set_voice_overlay_text(
                final_text or "Pronto."
            )
            self._set_voice_overlay_speaking(False)

            if self._voice_command_active and self.voice_engine:
                # V6: primeiro garante que TODO o restante entrou na fila de voz.
                # Só depois arma follow-up; isso impede entrar em OUVINDO no meio
                # de uma resposta longa por uma corrida entre streaming e TTS_END.
                self._queue_voice_stream_tts_ready(force=True)
                self._arm_voice_followup_if_question(final_text)
                self._voice_command_active = False
            elif final_text:
                self._speak_voice_response_if_needed(final_text)

            self.streaming_label = None
            self.streaming_buffer = ""
            self._active_stream_token = 0
            self._voice_stream_tts_buffer = ""
            self._voice_stream_tts_queued_count = 0
        except Exception as e:
            self.logger.error(e, "Erro ao finalizar streaming visual", "GUI")

    def _display_with_typing(self, sender: str, message: str):
        """Compatibilidade: usa bolha normal em vez do textbox antigo."""
        self.add_message(sender, message, is_jarvis=(str(sender).upper() in {LEGACY_NAME, PUBLIC_NAME}))

    def _typing_callback(self, text: str, is_complete: bool):
        """Mantido por compatibilidade com versões antigas do core."""
        return

    def add_message(self, sender: str, message: str, is_user: bool = False, is_jarvis: bool = False, is_system: bool = False, speak: bool = False):
        """Adiciona mensagem ao histórico e ao chat em bolhas, sempre na thread Tk."""
        if (
            self.root
            and threading.get_ident() != self._main_thread_id
        ):
            self._post_context_ui_call(
                self.add_message, sender, message, is_user, is_jarvis, is_system, speak
            )
            return
        message = self._shorten_local_response(
            message,
            is_user=is_user,
            is_system=is_system
        )
        if is_jarvis:
            sender = PUBLIC_NAME

        message_timestamp = time.time()

        self.chat_history.append({
            'sender': sender,
            'message': message,
            'timestamp': message_timestamp,
            'is_user': is_user,
            'is_jarvis': is_jarvis,
            'is_system': is_system
        })

        message_conversation_id = int(self.active_conversation_id)
        if self._history_restore_active:
            self._deferred_visual_messages.append((
                message_conversation_id, sender, message, is_user, is_jarvis, is_system, message_timestamp
            ))
        else:
            self._create_chat_bubble(
                sender, message,
                is_user=is_user,
                is_jarvis=is_jarvis,
                is_system=is_system,
                timestamp=message_timestamp
            )

        # Persistência imediata: se o programa fechar inesperadamente,
        # as mensagens já enviadas continuam no banco.
        if not self._restoring_history:
            try:
                self.memory_store.save_message(
                    message_conversation_id,
                    sender,
                    message,
                    is_user=is_user,
                    is_jarvis=is_jarvis,
                    is_system=is_system
                )

                if is_user and self.root:
                    self._post_ui_call(self._refresh_conversation_list)
            except Exception as e:
                self.logger.error(
                    e,
                    "Erro ao persistir mensagem",
                    "MEMORY"
                )

        if is_jarvis:
            self._set_voice_overlay_text(message)
            voice_turn = bool(self._voice_command_active)
            if voice_turn:
                # Uma única rota decide a fala; evita TTS duplicado/sobreposto.
                self._speak_voice_response_if_needed(message)
            elif speak:
                self._speak(message)
            else:
                self._pulse_voice_overlay_briefly()

    def _speak(self, text: str):
        """Fala usando a identidade vocal do VoiceEngine.

        Não troca silenciosamente para a voz padrão do Windows: isso era uma
        das causas da impressão de que o JARVIS "mudava de pessoa" entre turnos.
        """
        if self.voice_engine:
            try:
                self.voice_engine.speak(text, wait=False)
                return
            except Exception as e:
                self.logger.warning(
                    f"VoiceEngine TTS falhou: {e}",
                    "VOICE"
                )

        # A resposta continua visível no chat. Preferimos silêncio temporário a
        # tocar uma voz diferente sem autorização do usuário.
        self.logger.warning(
            "VoiceEngine indisponível; TTS local alternativo bloqueado para preservar a identidade vocal.",
            "VOICE",
        )

    def _show_jarvis_response(self, message: str, speak: bool = True):
        """Exibe mensagem do JARVIS e opcionalmente fala
        
        Args:
            message (str): Mensagem do JARVIS
            speak (bool): Se deve falar a mensagem
        """
        self.add_message(PUBLIC_NAME, message, is_jarvis=True, speak=speak)
    
    def _note_window_motion(self, event=None):
        """Pausa efeitos durante movimento/redimensionamento."""
        if self.voice_visual_mode:
            return

        self._window_in_motion = True

        try:
            if self._window_motion_job:
                self.root.after_cancel(
                    self._window_motion_job
                )
        except Exception:
            pass

        try:
            self._window_motion_job = self.root.after(
                180,
                self._finish_window_motion
            )
        except Exception:
            self._window_motion_job = None

    def _finish_window_motion(self):
        self._window_in_motion = False
        self._window_motion_job = None

    def _begin_native_window_drag(self, window):
        """Usa o arraste nativo do Windows para ficar fluido."""
        if window is None:
            return

        self._window_in_motion = True

        try:
            if sys.platform.startswith("win"):
                import ctypes

                hwnd = int(window.winfo_id())
                user32 = ctypes.windll.user32
                user32.ReleaseCapture()
                user32.SendMessageW(
                    hwnd,
                    0x00A1,  # WM_NCLBUTTONDOWN
                    0x0002,  # HTCAPTION
                    0
                )
            else:
                window.focus_force()
        except Exception:
            pass
        finally:
            try:
                self.root.after(
                    220,
                    self._finish_window_motion
                )
            except Exception:
                self._window_in_motion = False

    def _mix_hex(self, color_a, color_b, amount):
        """Interpola duas cores hex para a esfera 3D."""
        amount = max(0.0, min(float(amount), 1.0))

        def rgb(value):
            value = value.lstrip("#")
            return tuple(
                int(value[i:i + 2], 16)
                for i in (0, 2, 4)
            )

        a = rgb(color_a)
        b = rgb(color_b)

        mixed = tuple(
            int(a[i] + (b[i] - a[i]) * amount)
            for i in range(3)
        )

        return "#{:02x}{:02x}{:02x}".format(*mixed)

    def _voice_font(self, size=18, bold=False):
        """Carrega uma fonte limpa para o overlay de voz."""
        key = (int(size), bool(bold))

        if key in self._voice_font_cache:
            return self._voice_font_cache[key]

        candidates = []

        try:
            windows_dir = os.environ.get("WINDIR", r"C:\Windows")
            fonts_dir = os.path.join(windows_dir, "Fonts")

            if bold:
                candidates.extend([
                    os.path.join(fonts_dir, "seguisb.ttf"),
                    os.path.join(fonts_dir, "segoeuib.ttf"),
                    os.path.join(fonts_dir, "arialbd.ttf"),
                ])
            else:
                candidates.extend([
                    os.path.join(fonts_dir, "segoeui.ttf"),
                    os.path.join(fonts_dir, "arial.ttf"),
                ])
        except Exception:
            pass

        font = None

        for candidate in candidates:
            try:
                if os.path.exists(candidate):
                    font = ImageFont.truetype(candidate, int(size))
                    break
            except Exception:
                continue

        if font is None:
            try:
                font = ImageFont.truetype(
                    "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
                    int(size)
                )
            except Exception:
                font = ImageFont.load_default()

        self._voice_font_cache[key] = font
        return font

    def _wrap_voice_text(self, draw, text, font, max_width, max_lines=2):
        """Quebra o texto pelo tamanho real renderizado."""
        clean = " ".join(str(text or "").split()).strip()

        if not clean:
            return [f"{PUBLIC_NAME} está pronto."]

        words = clean.split()
        lines = []
        current = ""

        for word in words:
            trial = f"{current} {word}".strip() if current else word
            box = draw.textbbox((0, 0), trial, font=font)
            width = box[2] - box[0]

            if width <= max_width:
                current = trial
                continue

            if current:
                lines.append(current)

            current = word

            if len(lines) >= max_lines:
                break

        if current and len(lines) < max_lines:
            lines.append(current)

        original = clean
        rendered = " ".join(lines)

        if len(rendered) < len(original) and lines:
            last = lines[-1].rstrip(" .") + "..."

            while len(last) > 4:
                box = draw.textbbox((0, 0), last, font=font)

                if box[2] - box[0] <= max_width:
                    break

                last = last[:-4].rstrip() + "..."

            lines[-1] = last

        return lines[:max_lines]

    def _voice_pointer_down(self, event):
        """Diferencia clique no X de início de arraste."""
        cx = self.VOICE_ORB_WIDTH // 2
        close_x = cx + 126
        close_y = 24

        try:
            self._voice_close_pressed = (
                abs(event.x - close_x) <= 24
                and abs(event.y - close_y) <= 24
            )
        except Exception:
            self._voice_close_pressed = False

        if not self._voice_close_pressed:
            self._voice_drag_start(event)

    def _voice_pointer_motion(self, event):
        if self._voice_close_pressed:
            return

        self._voice_drag_motion(event)

    def _voice_pointer_up(self, event):
        if self._voice_close_pressed:
            self._voice_close_pressed = False

            cx = self.VOICE_ORB_WIDTH // 2
            close_x = cx + 126
            close_y = 24

            try:
                still_on_close = (
                    abs(event.x - close_x) <= 28
                    and abs(event.y - close_y) <= 28
                )
            except Exception:
                still_on_close = False

            if still_on_close:
                self._close_voice_overlay()

            return

        self._voice_drag_end(event)

    def _voice_drag_start(self, event):
        """Inicia o arraste da esfera sem disputar com a animação."""
        if not self.voice_overlay:
            return

        try:
            self._voice_dragging = True
            self._voice_drag_offset_x = (
                event.x_root - self.voice_overlay.winfo_x()
            )
            self._voice_drag_offset_y = (
                event.y_root - self.voice_overlay.winfo_y()
            )
            self._voice_drag_target = None
            self._voice_drag_start_root = (
                event.x_root,
                event.y_root
            )
        except Exception:
            self._voice_dragging = False

    def _voice_drag_motion(self, event):
        """
        Arraste suave em toda a área virtual dos monitores, inclusive
        monitores posicionados à esquerda (coordenadas negativas).
        """
        if not self._voice_dragging:
            return

        try:
            x = int(
                event.x_root
                - self._voice_drag_offset_x
            )
            y = int(
                event.y_root
                - self._voice_drag_offset_y
            )

            if self.window_manager:
                monitors = (
                    self.window_manager.get_monitors()
                )

                min_x = min(
                    monitor["left"]
                    for monitor in monitors
                )
                min_y = min(
                    monitor["top"]
                    for monitor in monitors
                )
                max_x = max(
                    monitor["right"]
                    for monitor in monitors
                )
                max_y = max(
                    monitor["bottom"]
                    for monitor in monitors
                )
            else:
                min_x = 0
                min_y = 0
                max_x = (
                    self.voice_overlay.winfo_screenwidth()
                )
                max_y = (
                    self.voice_overlay.winfo_screenheight()
                )

            x = max(
                min_x,
                min(
                    x,
                    max_x
                    - self.VOICE_ORB_WIDTH
                )
            )
            y = max(
                min_y,
                min(
                    y,
                    max_y
                    - self.VOICE_ORB_HEIGHT
                )
            )

            self._voice_drag_target = (
                x,
                y
            )

            if not self._voice_drag_job:
                self._voice_drag_job = (
                    self.root.after(
                        16,
                        self._apply_voice_drag
                    )
                )

        except Exception:
            pass

    def _apply_voice_drag(self):
        """Aplica a última posição solicitada do arraste."""
        self._voice_drag_job = None

        if (
            not self._voice_dragging
            or not self.voice_overlay
            or not self._voice_drag_target
        ):
            return

        try:
            x, y = self._voice_drag_target
            self.voice_overlay.geometry(
                f"{self.VOICE_ORB_WIDTH}x{self.VOICE_ORB_HEIGHT}"
                f"{int(x):+d}{int(y):+d}"
            )
            self._voice_drag_target = None
        except Exception:
            pass

        if self._voice_dragging:
            self._voice_drag_job = self.root.after(
                16,
                self._apply_voice_drag
            )

    def _voice_drag_end(self, event=None):
        """Finaliza arraste; clique curto ativa escuta manual."""
        was_click = False

        try:
            if event is not None and self._voice_drag_start_root:
                dx = event.x_root - self._voice_drag_start_root[0]
                dy = event.y_root - self._voice_drag_start_root[1]
                was_click = math.hypot(dx, dy) < 7.0
        except Exception:
            was_click = False

        self._voice_dragging = False
        self._voice_drag_target = None
        self._voice_drag_start_root = None

        if self._voice_drag_job:
            try:
                self.root.after_cancel(self._voice_drag_job)
            except Exception:
                pass

        self._voice_drag_job = None

        if was_click:
            try:
                self._post_ui_call(self._voice_visual_click)
            except Exception:
                pass

    def _hex_to_rgb(self, color):
        value = str(color or "#3C8DFF").lstrip("#")

        try:
            return tuple(
                int(value[i:i + 2], 16)
                for i in (0, 2, 4)
            )
        except Exception:
            return (60, 141, 255)

    def _build_orb_surface(self, color):
        """Esfera azul base; respeita o estilo escolhido também no fallback Tk."""
        size = 220
        style = str(getattr(self, "voice_orb_style", "core") or "core").lower()
        body_radius = {
            "crystal": 79,
            "core": 68,
            "rings": 50,
            "pulse": 70,
            "minimal": 64,
        }.get(style, 79)
        center = size // 2
        base_rgb = self._hex_to_rgb(color)

        image = Image.new(
            "RGBA",
            (size, size),
            (0, 0, 0, 0)
        )
        pixels = image.load()

        lx, ly, lz = (-0.48, -0.55, 0.68)
        light_len = math.sqrt(lx * lx + ly * ly + lz * lz)
        lx, ly, lz = lx / light_len, ly / light_len, lz / light_len

        hx, hy, hz = (lx, ly, lz + 1.0)
        half_len = math.sqrt(hx * hx + hy * hy + hz * hz)
        hx, hy, hz = hx / half_len, hy / half_len, hz / half_len

        for py in range(size):
            ny = (py - center) / body_radius
            for px in range(size):
                nx = (px - center) / body_radius
                rr = nx * nx + ny * ny
                if rr > 1.0:
                    continue

                nz = math.sqrt(max(0.0, 1.0 - rr))
                diffuse = max(0.0, nx * lx + ny * ly + nz * lz)
                specular = max(0.0, nx * hx + ny * hy + nz * hz) ** 48
                rim = (1.0 - nz) ** 1.55
                inner = max(0.0, 1.0 - math.sqrt(rr)) ** 2.0

                # Nunca cai para quase preto: mantém a identidade azul mesmo no lado escuro.
                if style == "minimal":
                    shade = 0.44 + 0.44 * diffuse + 0.16 * nz
                elif style == "pulse":
                    shade = 0.38 + 0.50 * diffuse + 0.22 * nz
                elif style == "core":
                    shade = 0.22 + 0.48 * diffuse + 0.25 * nz
                else:
                    shade = 0.30 + 0.55 * diffuse + 0.20 * nz

                r = base_rgb[0] * shade + 24 * inner + 235 * specular * 0.82 + 22 * rim
                g = base_rgb[1] * shade + 78 * inner + 248 * specular * 0.92 + 92 * rim
                b = base_rgb[2] * shade + 118 * inner + 255 * specular + 150 * rim

                pixels[px, py] = (
                    max(0, min(int(r), 255)),
                    max(0, min(int(g), 255)),
                    max(0, min(int(b), 255)),
                    255,
                )

        draw = ImageDraw.Draw(image)

        if style == "core":
            # Núcleo compacto com sensação de reator, sem transformar a esfera
            # em um desenho pesado quando o overlay Qt não estiver disponível.
            for radius, alpha, width in ((48, 95, 2), (35, 130, 2), (19, 215, 3)):
                draw.ellipse(
                    (center - radius, center - radius, center + radius, center + radius),
                    outline=(105, 214, 255, alpha),
                    width=width,
                )
            draw.ellipse(
                (center - 10, center - 10, center + 10, center + 10),
                fill=(205, 244, 255, 235),
            )
        elif style == "rings":
            # HUD holográfico: centro menor com anéis técnicos ao redor.
            for radius, start, end, alpha in (
                (66, 12, 168, 185), (78, 188, 336, 135), (91, 36, 132, 95),
            ):
                draw.arc(
                    (center - radius, center - radius, center + radius, center + radius),
                    start=start,
                    end=end,
                    fill=(95, 205, 255, alpha),
                    width=2,
                )
        elif style == "pulse":
            # Pulso orgânico: menos HUD, mais sensação de presença viva.
            for radius, alpha, width in ((58, 105, 2), (76, 72, 2), (91, 42, 1)):
                draw.ellipse(
                    (center - radius, center - radius, center + radius, center + radius),
                    outline=(126, 224, 255, alpha),
                    width=width,
                )
            draw.ellipse(
                (center - 18, center - 18, center + 18, center + 18),
                fill=(190, 240, 255, 118),
            )
        elif style == "minimal":
            draw.ellipse(
                (center - body_radius + 1, center - body_radius + 1,
                 center + body_radius - 1, center + body_radius - 1),
                outline=(105, 205, 255, 150),
                width=2,
            )

        # Rim interno nítido; não cria pixels semitransparentes fora da esfera.
        draw.arc(
            (
                center - body_radius + 2,
                center - body_radius + 2,
                center + body_radius - 2,
                center + body_radius - 2,
            ),
            start=198,
            end=340,
            fill=(76, 191, 255, 190),
            width=3,
        )

        # Dois reflexos compactos, sempre dentro da superfície.
        glass = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glass)
        if style == "crystal":
            gd.ellipse(
                (center - 46, center - 57, center - 9, center - 34),
                fill=(255, 255, 255, 112),
            )
            gd.ellipse(
                (center - 37, center - 50, center - 20, center - 39),
                fill=(255, 255, 255, 170),
            )
        else:
            gd.ellipse(
                (center - body_radius * 0.52, center - body_radius * 0.64,
                 center - body_radius * 0.10, center - body_radius * 0.36),
                fill=(255, 255, 255, 82 if style != "minimal" else 58),
            )
        glass = glass.filter(ImageFilter.GaussianBlur(4))

        # Recorta novamente pelo círculo para o blur não vazar para fora.
        mask = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse(
            (
                center - body_radius,
                center - body_radius,
                center + body_radius,
                center + body_radius,
            ),
            fill=255,
        )
        glass.putalpha(Image.composite(glass.getchannel("A"), Image.new("L", (size, size), 0), mask))
        return Image.alpha_composite(image, glass)

    def _get_orb_surface(self):
        color = "#168CFF"
        style = str(getattr(self, "voice_orb_style", "core") or "core").lower()

        if (
            self._orb_base_pil is None
            or self._orb_base_color != color
            or getattr(self, "_orb_base_style", None) != style
        ):
            self._orb_base_pil = self._build_orb_surface(
                color
            )
            self._orb_base_color = color
            self._orb_base_style = style

        return self._orb_base_pil

    def _render_orb_frame(self):
        """
        Modo avançado da esfera.

        A esfera permanece AZUL, mas o comportamento muda:
        - REPOUSO: flutuação suave;
        - OUVINDO: pulsa pelo nível REAL do microfone + ondas de entrada;
        - PENSANDO: energia circula dentro da esfera;
        - FALANDO: pulsação e ondas externas;
        - EXECUTANDO: anel holográfico rotativo;
        - ERRO: pequena vibração + detalhes vermelhos.

        O chat recente é renderizado abaixo da esfera no mesmo Canvas.
        """
        width = self.VOICE_ORB_WIDTH
        height = self.VOICE_ORB_HEIGHT

        key_rgb = self._hex_to_rgb(
            self._voice_transparent_key
        )

        frame = Image.new(
            "RGBA",
            (width, height),
            (
                key_rgb[0],
                key_rgb[1],
                key_rgb[2],
                255
            )
        )

        state = str(
            getattr(
                self,
                "_voice_visual_state",
                "REPOUSO"
            )
            or "REPOUSO"
        ).upper()

        speaking = (
            self.voice_orb_speaking
            or state == "FALANDO"
        )
        listening = (
            state == "OUVINDO"
        )
        thinking = (
            state == "PENSANDO"
        )
        executing = (
            state == "EXECUTANDO"
        )
        error_state = (
            state == "ERRO"
        )

        # -----------------------------------------------------
        # Nível real do microfone
        # -----------------------------------------------------
        mic_target = max(
            0.0,
            min(
                float(
                    getattr(
                        self,
                        "voice_mic_level",
                        0.0
                    )
                ),
                1.0
            )
        )

        smoothing = (
            0.48
            if mic_target
            > self._voice_mic_smoothed
            else 0.16
        )

        self._voice_mic_smoothed += (
            mic_target
            - self._voice_mic_smoothed
        ) * smoothing

        mic_level = max(
            0.0,
            min(
                self._voice_mic_smoothed,
                1.0
            )
        )

        # -----------------------------------------------------
        # Movimento base
        # -----------------------------------------------------
        float_strength = {
            "REPOUSO": 7.0,
            "OUVINDO": 5.0,
            "PENSANDO": 4.0,
            "FALANDO": 8.0,
            "EXECUTANDO": 5.0,
            "ERRO": 2.0,
        }.get(
            state,
            6.0
        )

        float_y = math.sin(
            self.voice_orb_phase * 0.72
        ) * float_strength

        error_jitter = (
            math.sin(
                self.voice_orb_phase * 12.0
            ) * 3.5
            if error_state
            else 0.0
        )

        pulse = math.sin(
            self.voice_orb_phase * 2.3
        )

        scale = (
            1.0
            + (
                0.045 * pulse
                if speaking
                else 0.012 * pulse
            )
            + (
                mic_level * 0.105
                if listening
                else 0.0
            )
        )

        base = self._get_orb_surface()

        orb_size = max(
            170,
            int(
                round(
                    220 * scale
                )
            )
        )

        orb = base.resize(
            (
                orb_size,
                orb_size
            ),
            Image.Resampling.LANCZOS
        )

        angle = (
            math.sin(
                self.voice_orb_phase * 0.43
            )
            * (
                2.2
                if speaking
                else 0.9
            )
        )

        orb = orb.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=False
        )

        # Tk/Windows usa color-key, não alpha por pixel. Removemos o halo
        # semitransparente para não aparecer aquela borda/fundo preto.
        try:
            alpha = orb.getchannel("A")
            alpha = alpha.point(lambda value: 255 if value >= 105 else 0)
            orb.putalpha(alpha)
        except Exception:
            pass

        cx = int(
            width // 2
            + error_jitter
        )
        orb_center_y = (
            112
            + float_y
        )

        orb_left = int(
            cx
            - orb_size / 2
        )
        orb_top = int(
            orb_center_y
            - orb_size / 2
        )

        # -----------------------------------------------------
        # Sem sombra preta: o color-key do Tk não suporta alpha parcial bem.
        # A profundidade fica por conta da iluminação interna da própria esfera.
        # -----------------------------------------------------

        # -----------------------------------------------------
        # OUVINDO: ondas que entram / reagem ao mic
        # -----------------------------------------------------
        if listening:
            waves = Image.new(
                "RGBA",
                (width, height),
                (0, 0, 0, 0)
            )
            wd = ImageDraw.Draw(
                waves
            )
            blue = self._hex_to_rgb(
                "#168CFF"
            )

            for ring in range(3):
                phase = (
                    self.voice_orb_phase
                    * 1.9
                    + ring * 0.8
                ) % 1.0

                # Começa longe e "entra" na esfera.
                rr = (
                    118
                    - phase * 28
                    + ring * 7
                    + mic_level * 14
                )

                alpha = int(
                    55
                    + mic_level * 150
                    - ring * 10
                )

                wd.ellipse(
                    (
                        cx - rr,
                        orb_center_y - rr,
                        cx + rr,
                        orb_center_y + rr
                    ),
                    outline=(
                        blue[0],
                        blue[1],
                        blue[2],
                        max(
                            25,
                            min(
                                alpha,
                                215
                            )
                        )
                    ),
                    width=(
                        3
                        if (
                            mic_level > 0.55
                            and ring == 0
                        )
                        else 2
                    )
                )

            frame = Image.alpha_composite(
                frame,
                waves
            )

        # -----------------------------------------------------
        # FALANDO: ondas externas
        # -----------------------------------------------------
        if speaking:
            waves = Image.new(
                "RGBA",
                (width, height),
                (0, 0, 0, 0)
            )
            wd = ImageDraw.Draw(
                waves
            )
            blue = self._hex_to_rgb(
                "#48B8FF"
            )

            for ring in range(3):
                phase = abs(
                    math.sin(
                        self.voice_orb_phase * 2.5
                        + ring
                    )
                )

                rr = (
                    92
                    + ring * 14
                    + phase * 10
                )

                wd.ellipse(
                    (
                        cx - rr,
                        orb_center_y - rr,
                        cx + rr,
                        orb_center_y + rr
                    ),
                    outline=(
                        blue[0],
                        blue[1],
                        blue[2],
                        max(
                            30,
                            110
                            - ring * 25
                        )
                    ),
                    width=2
                )

            frame = Image.alpha_composite(
                frame,
                waves
            )

        # -----------------------------------------------------
        # EXECUTANDO: anel holográfico
        # -----------------------------------------------------
        if executing:
            ring_layer = Image.new(
                "RGBA",
                (width, height),
                (0, 0, 0, 0)
            )
            rd = ImageDraw.Draw(
                ring_layer
            )

            rotation = int(
                (
                    self.voice_orb_phase
                    * 90
                )
                % 360
            )

            ring_box = (
                cx - 105,
                orb_center_y - 47,
                cx + 105,
                orb_center_y + 47
            )

            for offset in (
                0,
                120,
                240
            ):
                rd.arc(
                    ring_box,
                    start=(
                        rotation
                        + offset
                    ),
                    end=(
                        rotation
                        + offset
                        + 58
                    ),
                    fill=(
                        72,
                        195,
                        255,
                        210
                    ),
                    width=3
                )

            frame = Image.alpha_composite(
                frame,
                ring_layer
            )

        # -----------------------------------------------------
        # Esfera
        # -----------------------------------------------------
        frame.alpha_composite(
            orb,
            (
                orb_left,
                orb_top
            )
        )

        draw = ImageDraw.Draw(
            frame
        )

        # -----------------------------------------------------
        # PENSANDO: energia interna
        # -----------------------------------------------------
        if thinking:
            rotation = (
                self.voice_orb_phase
                * 1.7
            )

            for index in range(8):
                angle_p = (
                    rotation
                    + (
                        math.pi * 2
                        * index / 8
                    )
                )

                radius_p = (
                    34
                    + (
                        index % 3
                    ) * 9
                )

                px = (
                    cx
                    + math.cos(
                        angle_p
                    ) * radius_p
                )
                py = (
                    orb_center_y
                    + math.sin(
                        angle_p
                    ) * radius_p * 0.62
                )

                dot = (
                    3
                    if index % 3 == 0
                    else 2
                )

                draw.ellipse(
                    (
                        px - dot,
                        py - dot,
                        px + dot,
                        py + dot
                    ),
                    fill=(
                        185,
                        238,
                        255,
                        220
                    )
                )

            # Arco interno em rotação contrária.
            inner_box = (
                cx - 52,
                orb_center_y - 31,
                cx + 52,
                orb_center_y + 31
            )

            draw.arc(
                inner_box,
                start=int(
                    -self.voice_orb_phase
                    * 80
                ) % 360,
                end=(
                    int(
                        -self.voice_orb_phase
                        * 80
                    )
                    + 115
                ) % 360,
                fill=(
                    100,
                    205,
                    255,
                    205
                ),
                width=3
            )

        # Partícula orbital normal.
        orbit_angle = (
            self.voice_orb_phase
            * 0.90
        )

        ox = (
            cx
            + math.cos(
                orbit_angle
            ) * 76
        )
        oy = (
            orb_center_y
            + math.sin(
                orbit_angle
            ) * 28
        )

        draw.ellipse(
            (
                ox - 2,
                oy - 2,
                ox + 2,
                oy + 2
            ),
            fill=(
                225,
                248,
                255,
                235
            )
        )

        # -----------------------------------------------------
        # ERRO: azul continua dominante; vermelho só em detalhes
        # -----------------------------------------------------
        if error_state:
            red_box = (
                cx - 87,
                orb_center_y - 87,
                cx + 87,
                orb_center_y + 87
            )

            start_angle = int(
                self.voice_orb_phase
                * 100
            ) % 360

            draw.arc(
                red_box,
                start=start_angle,
                end=start_angle + 32,
                fill=(
                    255,
                    82,
                    96,
                    235
                ),
                width=4
            )

            for index in range(3):
                angle_r = (
                    self.voice_orb_phase * 3
                    + index * 2.1
                )

                rx = (
                    cx
                    + math.cos(
                        angle_r
                    ) * 92
                )
                ry = (
                    orb_center_y
                    + math.sin(
                        angle_r
                    ) * 60
                )

                draw.ellipse(
                    (
                        rx - 2,
                        ry - 2,
                        rx + 2,
                        ry + 2
                    ),
                    fill=(
                        255,
                        88,
                        102,
                        240
                    )
                )

        # -----------------------------------------------------
        # Estado e texto curto
        # -----------------------------------------------------
        state_font = self._voice_font(
            13,
            bold=True
        )
        detail_font = self._voice_font(
            14,
            bold=False
        )
        chat_font = self._voice_font(
            12,
            bold=False
        )
        chat_meta_font = self._voice_font(
            10,
            bold=True
        )
        close_font = self._voice_font(
            22,
            bold=True
        )

        state_labels = {
            "REPOUSO": "OCIOSO",
            "OUVINDO": "OUVINDO",
            "ESCUTANDO": "OUVINDO",
            "ESPERANDO_RESPOSTA": "OUVINDO",
            "PENSANDO": "PENSANDO",
            "FALANDO": "FALANDO",
            "EXECUTANDO": "EXECUTANDO",
            "ERRO": "ERRO",
        }

        state_text = state_labels.get(
            state,
            state
        )

        state_box = draw.textbbox(
            (0, 0),
            state_text,
            font=state_font
        )

        state_w = (
            state_box[2]
            - state_box[0]
        )

        state_y = 222

        draw.text(
            (
                width / 2
                - state_w / 2,
                state_y
            ),
            state_text,
            font=state_font,
            fill=(
                67,
                167,
                255,
                255
            )
        )

        detail = self._voice_overlay_preview(
            self.voice_last_text,
            limit=92
        )

        detail_lines = self._wrap_voice_text(
            draw,
            detail,
            detail_font,
            max_width=420,
            max_lines=2
        )

        detail_y = 246

        for line in detail_lines:
            box = draw.textbbox(
                (0, 0),
                line,
                font=detail_font
            )

            line_w = (
                box[2]
                - box[0]
            )

            draw.text(
                (
                    width / 2
                    - line_w / 2,
                    detail_y
                ),
                line,
                font=detail_font,
                fill=(
                    235,
                    247,
                    255,
                    255
                )
            )

            detail_y += 19

        # -----------------------------------------------------
        # TRANSCRIÇÃO COMPACTA DO MODO DE VOZ
        # -----------------------------------------------------
        # Sem painel preto e sem bolhas: três linhas recentes, com o texto mais
        # novo em destaque. Isso deixa a esfera visualmente mais limpa.
        transcript_top = 292
        draw = ImageDraw.Draw(frame)

        recent = []
        try:
            for item in reversed(self.chat_history):
                sender = str(item.get("sender", "")).strip()
                if sender.lower() not in ("zero", "jarvis", "você", "voce", "user"):
                    continue

                message = " ".join(str(item.get("message", "")).split()).strip()
                if not message:
                    continue

                recent.append((sender, message))
                if len(recent) >= 3:
                    break
            recent.reverse()
        except Exception:
            recent = []

        if not recent:
            recent = [(PUBLIC_NAME, f"Diga “{PUBLIC_NAME.title()}” para começar.")]

        # Linha holográfica central, sem fundo escuro.
        draw.line(
            (70, transcript_top - 10, width - 70, transcript_top - 10),
            fill=(42, 139, 220, 180),
            width=1,
        )

        y = transcript_top
        total = len(recent)

        for index, (sender, message) in enumerate(recent):
            is_user = sender.lower() in ("você", "voce", "user")
            age = total - 1 - index

            label = "VOCÊ" if is_user else PUBLIC_NAME
            label_color = (
                (137, 205, 255, 255)
                if is_user
                else (67, 167, 255, 255)
            )

            # Itens mais antigos ficam discretos, sem alpha problemático no fundo.
            text_color = (
                (232, 246, 255, 255)
                if age == 0
                else (158, 190, 215, 255)
            )

            preview = message if len(message) <= 105 else message[:102].rstrip() + "..."
            lines = self._wrap_voice_text(
                draw,
                preview,
                chat_font,
                max_width=360,
                max_lines=1,
            )
            line = lines[0] if lines else preview

            # pequeno ponto/traço em vez de caixa
            draw.ellipse(
                (42, y + 7, 46, y + 11),
                fill=label_color,
            )
            draw.text(
                (54, y + 1),
                label,
                font=chat_meta_font,
                fill=label_color,
            )
            draw.text(
                (105, y),
                line,
                font=chat_font,
                fill=text_color,
            )

            y += 29

        # X discreto próximo da esfera.
        close_x = (
            width // 2
            + 126
        )
        close_y = 12

        draw.text(
            (
                close_x - 7,
                close_y
            ),
            "×",
            font=close_font,
            fill=(
                94,
                135,
                166,
                255
            )
        )

        # -----------------------------------------------------
        # Converte alpha para color-key estável do Windows.
        # -----------------------------------------------------
        key_background = Image.new(
            "RGBA",
            (width, height),
            (
                key_rgb[0],
                key_rgb[1],
                key_rgb[2],
                255
            )
        )

        return Image.alpha_composite(
            key_background,
            frame
        ).convert(
            "RGB"
        )

    def _toggle_voice_visual_mode(self):
        """Abre ou fecha o painel flutuante do modo de voz."""
        if self.voice_visual_mode:
            self._close_voice_overlay()
        else:
            self._open_voice_overlay()

    def _open_voice_overlay(self):
        """Abre a esfera no canto; Qt é preferido por transparência real."""
        if self._qt_overlay_active and self.qt_voice_overlay:
            try:
                self.voice_visual_mode = True
                try:
                    current_state = self.root.state()
                    self._root_hidden_before_voice = current_state == "withdrawn"
                    self._root_state_before_voice = current_state if current_state != "withdrawn" else "normal"
                except Exception:
                    self._root_hidden_before_voice = False
                    self._root_state_before_voice = "normal"

                self.root.withdraw()
                self.qt_voice_overlay.set_caption("")
                self.qt_voice_overlay.set_state(self._voice_visual_state)
                shown = self.qt_voice_overlay.show(self._qt_overlay_position())
                self._update_orb_context_mode(force_expand=False)
                if shown is False:
                    raise RuntimeError("processo Qt não respondeu ao comando show")

                if self.voice_button:
                    self.voice_button.configure(
                        fg_color="#215FA8",
                        hover_color="#2E73C7"
                    )
                return
            except Exception as e:
                self.logger.warning(
                    f"Overlay Qt falhou; usando fallback Tk: {e}",
                    "OVERLAY"
                )
                self._qt_overlay_active = False

        return self._open_voice_overlay_tk()

    def _open_voice_overlay_tk(self):
        """Esconde o chat e deixa somente a esfera sobre a área de trabalho."""
        try:
            if (
                self.voice_overlay
                and self.voice_overlay.winfo_exists()
            ):
                self.voice_overlay.deiconify()
                self.voice_overlay.lift()
                self.voice_visual_mode = True
                self.root.withdraw()
                self._start_voice_orb_animation()
                return

            self.voice_visual_mode = True

            try:
                current_state = self.root.state()
                self._root_hidden_before_voice = (
                    current_state == "withdrawn"
                )
                self._root_state_before_voice = (
                    current_state
                    if current_state != "withdrawn"
                    else "normal"
                )
            except Exception:
                self._root_hidden_before_voice = False
                self._root_state_before_voice = "normal"

            overlay = tk.Toplevel(self.root)
            self.voice_overlay = overlay

            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)

            transparent = self._voice_transparent_key
            overlay.configure(bg=transparent)

            try:
                if sys.platform.startswith("win"):
                    overlay.wm_attributes("-transparentcolor", transparent)
                    overlay.attributes("-alpha", self.VOICE_ORB_OPACITY)
                else:
                    overlay.attributes("-alpha", self.VOICE_ORB_OPACITY)
            except Exception as e:
                self.logger.warning(
                    f"Transparência do modo de voz: {e}",
                    "GUI"
                )

            width = self.VOICE_ORB_WIDTH
            height = self.VOICE_ORB_HEIGHT

            if self.window_manager:
                try:
                    x, y = (
                        self.window_manager.overlay_position(
                            width,
                            height,
                            bottom_margin=20
                        )
                    )
                except Exception:
                    x = int(
                        (
                            overlay.winfo_screenwidth()
                            - width
                        )
                        / 2
                    )
                    y = int(
                        overlay.winfo_screenheight()
                        - height
                        - 32
                    )
            else:
                x = int(
                    (
                        overlay.winfo_screenwidth()
                        - width
                    )
                    / 2
                )
                y = int(
                    overlay.winfo_screenheight()
                    - height
                    - 32
                )

            overlay.geometry(
                f"{width}x{height}"
                f"{int(x):+d}{int(y):+d}"
            )

            # Um único Canvas. Sem Labels/Tk widgets soltos.
            self.voice_orb_canvas = tk.Canvas(
                overlay,
                width=width,
                height=height,
                bg=transparent,
                highlightthickness=0,
                bd=0,
                relief="flat",
                cursor="hand2"
            )
            self.voice_orb_canvas.pack(
                fill="both",
                expand=True
            )

            self.voice_overlay_state_label = None
            self.voice_overlay_text_label = None

            self.voice_orb_canvas.bind(
                "<ButtonPress-1>",
                self._voice_pointer_down
            )
            self.voice_orb_canvas.bind(
                "<B1-Motion>",
                self._voice_pointer_motion
            )
            self.voice_orb_canvas.bind(
                "<ButtonRelease-1>",
                self._voice_pointer_up
            )

            self.voice_orb_canvas.bind(
                "<Double-Button-1>",
                lambda event: self._close_voice_overlay(),
                add="+"
            )

            overlay.bind(
                "<Escape>",
                lambda event: self._close_voice_overlay()
            )

            if self.voice_button:
                self.voice_button.configure(
                    fg_color="#215FA8",
                    hover_color="#2E73C7"
                )

            overlay.update_idletasks()

            self.root.withdraw()

            overlay.deiconify()
            overlay.lift()
            overlay.focus_force()

            self._start_voice_orb_animation()

        except Exception as e:
            self.voice_visual_mode = False

            try:
                self.root.deiconify()
            except Exception:
                pass

            self.logger.error(
                e,
                "Erro ao abrir modo de voz visual",
                "GUI"
            )

    def _voice_visual_click(self):
        """Clique curto na esfera inicia captura sem exigir wake word."""
        self._pulse_voice_overlay_briefly()

        if self.voice_engine:
            try:
                self.voice_engine.trigger_manual()
            except Exception as e:
                self.logger.warning(
                    f"Falha ao ativar voz manualmente: {e}",
                    "VOICE"
                )
        else:
            self._set_voice_overlay_text(
                "Motor de voz indisponível. Execute INSTALAR_VOZ.bat."
            )

    def _close_voice_overlay(self):
        if self._qt_overlay_active and self.qt_voice_overlay:
            try:
                self.voice_visual_mode = False
                self.voice_orb_speaking = False
                self.qt_voice_overlay.hide()
                self.qt_voice_overlay.set_caption("")

                if self.root and self.root.winfo_exists():
                    if self._root_hidden_before_voice:
                        self.root.withdraw()
                    else:
                        self.root.deiconify()
                        if self._root_state_before_voice == "zoomed":
                            try:
                                self.root.state("zoomed")
                            except Exception:
                                pass
                        self.root.lift()
                        self.root.focus_force()

                if self.voice_button:
                    self.voice_button.configure(
                        fg_color="#182536",
                        hover_color="#223853"
                    )
                return
            except Exception as e:
                self.logger.warning(
                    f"Falha ao fechar overlay Qt: {e}",
                    "OVERLAY"
                )

        return self._close_voice_overlay_tk()

    def _close_voice_overlay_tk(self):
        """Fecha a esfera e devolve a interface principal."""
        try:
            self.voice_visual_mode = False
            self.voice_orb_speaking = False

            if self.voice_orb_animation_job and self.root:
                try:
                    self.root.after_cancel(
                        self.voice_orb_animation_job
                    )
                except Exception:
                    pass

            self.voice_orb_animation_job = None
            self._voice_drag_end()
            self._voice_orb_photo = None

            if (
                self.voice_overlay
                and self.voice_overlay.winfo_exists()
            ):
                self.voice_overlay.destroy()

            self.voice_overlay = None
            self.voice_orb_canvas = None
            self.voice_overlay_text_label = None
            self.voice_overlay_state_label = None

            if self.root and self.root.winfo_exists():
                if self._root_hidden_before_voice:
                    self.root.withdraw()
                else:
                    self.root.deiconify()

                    if self._root_state_before_voice == "zoomed":
                        try:
                            self.root.state("zoomed")
                        except Exception:
                            pass

                    self.root.lift()
                    self.root.focus_force()

            if self.voice_button:
                self.voice_button.configure(
                    fg_color="#182536",
                    hover_color="#223853"
                )

        except Exception as e:
            self.logger.warning(
                f"Não foi possível fechar o modo de voz: {e}",
                "GUI"
            )

    def _voice_overlay_preview(self, text, limit=155):
        clean = " ".join(str(text or "").split()).strip()

        if not clean:
            return f"{PUBLIC_NAME} está pronto."

        if len(clean) <= limit:
            return clean

        return clean[:limit - 3].rstrip() + "..."

    def _set_voice_overlay_text(self, text):
        """Atualiza o texto desenhado no próximo frame da esfera."""
        self.voice_last_text = sanitize_text(text, limit=520) or f"{PUBLIC_NAME} está pronto."

    def _set_voice_overlay_speaking(self, speaking: bool):
        """
        Liga/desliga a animação de energia sem confundir ESCUTANDO com FALANDO.
        No overlay Qt o estado vem do VoiceEngine; no fallback Tk mantemos o
        pulso legado para não perder feedback visual.
        """
        self.voice_orb_speaking = bool(speaking)
        if self.qt_voice_overlay:
            try:
                actual_state = str(
                    getattr(self, "_voice_engine_state", "") or ""
                ).upper()
                if speaking and actual_state == "FALANDO":
                    self.qt_voice_overlay.set_state("FALANDO")
                else:
                    self.qt_voice_overlay.set_state(self._voice_visual_state)
            except Exception:
                pass
        if self.voice_visual_mode and not self._qt_overlay_active:
            self._start_voice_orb_animation()

    def _pulse_voice_overlay_briefly(self):
        """Anima brevemente a esfera para respostas escritas."""
        if not self.voice_visual_mode:
            return

        self._set_voice_overlay_speaking(True)

        try:
            self.root.after(
                950,
                lambda: self._set_voice_overlay_speaking(False)
            )
        except Exception:
            pass

    def _start_voice_orb_animation(self):
        if (
            not self.voice_visual_mode
            or not self.root
            or not self.voice_orb_canvas
        ):
            return

        if self.voice_orb_animation_job:
            return

        self.voice_orb_animation_job = self.root.after(
            20,
            self._animate_voice_orb
        )

    def _animate_voice_orb(self):
        """Atualiza esfera, estado e texto como um único frame."""
        self.voice_orb_animation_job = None

        if not self.voice_visual_mode:
            return

        canvas = self.voice_orb_canvas

        try:
            if not canvas or not canvas.winfo_exists():
                return

            self.voice_orb_phase += (
                0.115
                if self.voice_orb_speaking
                else 0.052
            )

            frame = self._render_orb_frame()

            photo = ImageTk.PhotoImage(
                frame
            )
            self._voice_orb_photo = photo

            canvas.delete("all")
            canvas.create_image(
                0,
                0,
                image=photo,
                anchor="nw"
            )

            self.voice_orb_animation_job = self.root.after(
                33,
                self._animate_voice_orb
            )

        except Exception as e:
            self.voice_orb_animation_job = None
            self.logger.warning(
                f"Animação da esfera interrompida: {e}",
                "GUI"
            )

    def _toggle_listening(self):
        """Captura manual usando o mesmo VoiceEngine do wake word.

        O caminho legado SpeechRecognition dependia de `self.microphone` e
        `self.recognizer`, que não existem no runtime moderno. Um único motor
        agora é dono do dispositivo de áudio, evitando disputa e botões mortos.
        """
        if not self.voice_engine:
            self.add_message("Sistema", "❌ Motor de voz ainda não está disponível.", is_system=True)
            return
        if self.is_listening:
            self._stop_listening()
            return
        self._start_listening()

    def _start_listening(self):
        """Solicita um turno manual sem abrir um segundo stream de microfone."""
        engine = self.voice_engine
        if engine is None:
            self.add_message("Sistema", "❌ Motor de voz ainda não está disponível.", is_system=True)
            return
        self.is_listening = True
        try:
            if self.voice_button:
                self.voice_button.configure(fg_color="#215FA8", hover_color="#2E73C7")
        except Exception:
            pass
        try:
            engine.trigger_manual()
            self._set_voice_overlay_text("Estou ouvindo...")
            self.logger.info("Escuta manual enviada ao VoiceEngine.", "VOICE")
        except Exception as exc:
            self.is_listening = False
            self.logger.error(exc, "Falha ao ativar escuta manual", "VOICE")
            self.add_message("Sistema", "❌ Não consegui ativar o microfone agora.", is_system=True)

    def _stop_listening(self):
        """Atualiza apenas o estado visual; o VoiceEngine controla o stream."""
        self.is_listening = False
        try:
            if self.voice_button and not self.voice_visual_mode:
                self.voice_button.configure(fg_color="#393C45", hover_color="#4B5060")
        except Exception:
            pass

    def _process_voice_command(self, text: str):
        """Processa comando de voz"""
        self.add_message("Voz", text, is_user=True)
        self._process_message(text)
    
    def _update_status(self, text: str, color: str):
        """Atualiza status, nome JARVIS e esfera de voz com a mesma identidade."""
        if (
            self.root
            and threading.get_ident() != self._main_thread_id
        ):
            try:
                self._post_ui_call(self._update_status, text, color)
            except Exception:
                pass
            return
        clean = str(text).replace("🟢", "").replace("🟡", "").strip().upper()

        status_key = clean.split()[0] if clean else "ONLINE"

        status_colors = {
            "ONLINE": "#31D47D",
            "PROCESSANDO": "#9B7BFF",
            "PENSANDO": "#9B7BFF",
            "RESPONDENDO": "#39C6FF",
            "FALANDO": "#39C6FF",
            "PESQUISANDO": "#3C8DFF",
            "EXECUTANDO": "#F5B942",
            "REPRODUZINDO": "#38D6B0",
            "INDEXANDO": "#8E6BFF",
            "COPIADO": "#31D47D",
            "ERRO": "#FF5C6C",
        }

        effective_color = status_colors.get(status_key, color or "#3C8DFF")
        self.jarvis_status_color = effective_color

        visual_state_map = {
            "ONLINE": "REPOUSO",
            "PROCESSANDO": "PENSANDO",
            "PENSANDO": "PENSANDO",
            "RESPONDENDO": "PENSANDO",
            "FALANDO": "FALANDO",
            "PESQUISANDO": "EXECUTANDO",
            "EXECUTANDO": "EXECUTANDO",
            "REPRODUZINDO": "EXECUTANDO",
            "INDEXANDO": "EXECUTANDO",
            "ERRO": "ERRO",
        }

        if status_key in visual_state_map:
            self._voice_visual_state = (
                visual_state_map[
                    status_key
                ]
            )

        if status_key == "ERRO":
            self._schedule_auto_diagnostic(
                f"Interface: {clean}"
            )

        if self.status_label:
            self.status_label.configure(
                text=clean,
                text_color=effective_color
            )

        if self.status_dot:
            self.status_dot.configure(text_color=effective_color)

        try:
            if self.jarvis_logo_canvas:
                self.jarvis_logo_canvas.itemconfigure(
                    "jarvis_text",
                    fill=effective_color
                )
                self.jarvis_logo_canvas.itemconfigure(
                    "jarvis_glow",
                    fill=effective_color
                )
        except Exception:
            pass

        try:
            if self.voice_overlay_state_label:
                self.voice_overlay_state_label.configure(
                    fg=effective_color
                )
        except Exception:
            pass

        activity_map = {
            "ONLINE": "Sistema pronto para operar",
            "PROCESSANDO": "Interpretando seu comando...",
            "PESQUISANDO": "Consultando fontes online...",
            "EXECUTANDO": "Executando ação no Windows...",
            "RESPONDENDO": "Gerando resposta...",
            "REPRODUZINDO": "Controlando mídia...",
        }
        if self.activity_label:
            self.activity_label.configure(
                text=activity_map.get(clean, clean.title())
            )

    def _safe_relevant_memories(self, text: str, limit: int = 6):
        """Memória é auxiliar: falha/corrupção nunca interrompe resposta/TTS."""
        try:
            return self.memory_store.get_relevant_memories(
                text,
                current_conversation_id=self.active_conversation_id,
                limit=limit,
            )
        except Exception as exc:
            try:
                self.logger.warning(f"Memória contextual indisponível: {exc}", "MEMORY")
            except Exception:
                pass
            return []

    def _get_conversation_history(self) -> List[Dict]:
        """Retorna histórico da conversa"""
        # O histórico completo está no SQLite. Para a chamada atual,
        # enviamos uma janela recente maior; memórias antigas relevantes
        # entram separadamente via MemoryStore.
        return self.chat_history[-24:]
    
    def _get_live_context_info(self) -> str:
        bits = []
        try:
            if self.operational_context:
                compact = self.operational_context.compact_text()
                if compact:
                    bits.append(compact)
        except Exception:
            pass
        try:
            status = v8_context_status() or {}
            for key in ("app", "monitor", "site", "topic"):
                value = status.get(key)
                if value:
                    bits.append(f"{key}={value}")
        except Exception:
            pass
        try:
            if self.media_context:
                media = self.media_context.refresh().to_dict()
                if media.get("service"):
                    bits.append(f"media_service={media.get('service')}")
                if media.get("item"):
                    bits.append(f"media_item={str(media.get('item'))[:120]}")
        except Exception:
            pass
        unique = []
        seen = set()
        for bit in bits:
            if bit and bit not in seen:
                seen.add(bit); unique.append(bit)
        return "CTX:" + " | ".join(unique) if unique else ""

    def _get_system_commands_info(self) -> str:
        return """
Comandos locais do JARVIS disponíveis:
- Aplicativos: abrir [app], fechar [app] (com confirmação), ensinar alias, reindexar.
- Janelas: minimizar/maximizar/restaurar [app ou janela atual], mover [app] para monitor 2/outro monitor, lado a lado.
- Monitores: monitor ativo, quantidade de monitores.
- Mídia V2: identifica Spotify/VLC/YouTube/streaming atual; pause/continua/próxima/anterior e "que música/episódio está tocando?" usam contexto do player.
- Modo gamer: abre Discord, Opera GX e Steam em conjunto.
- Áudio: mandar som para headset/caixas, usar microfone USB, listar dispositivos.
- Visão: o que tem na minha tela, onde está o botão X, por que apareceu esse erro.
- Web: pesquise [assunto], abra site [endereço].
- Arquivos: abrir/criar/procurar/copiar/mover; apagar pasta/arquivo vai para Lixeira após confirmação.
- Windows: screenshot, brilho, status, processos, bloquear, desligar/reiniciar/suspender com confirmação.
- Memória: histórico, memórias persistentes, conversas.
- Modos: modo auto, modo conversa, modo comando; presença discreto/assistente/JARVIS.
- Autonomia: manual, assistida ou autônoma dentro da lista segura do Agent Runtime.
- Agente: objetivos por etapas, navegador, streaming universal, download verificado e cancelamento com 'Jarvis, para'.
- Rotinas: 'aprende rotina X', execute passos verificados, 'terminar rotina', 'executa rotina X'; 'meus hábitos' mostra padrões locais.
- Contexto V2: acompanha app/site/monitor/player/tópico com validade e confiança; entende "ele", "isso" e "o outro" quando há referência segura.
- Regras: "quando o download terminar me avisa", "quando eu abrir OBS, abre Opera", "faz isso sempre", listar/apagar regras; ações sensíveis não são automatizadas.
- Preferências: "fala mais rápido/normal/devagar" e "microfone sensível/normal" ajustam apenas TTS/limiar em runtime, sem trocar driver ou STT.
- Diagnóstico: diagnóstico completo, sempre factual para estado do PC.
- Ações podem ser encadeadas com 'e depois'.
"""

    def _on_closing(self):
        """
        X da janela = ocultar na bandeja.
        Sair de verdade = menu da bandeja f"Sair do {PUBLIC_NAME}".
        """
        can_hide = False

        try:
            if self.desktop_integration:
                desktop_status = (
                    self.desktop_integration.status()
                )
                # Nunca esconda uma janela sem existir um caminho visual para
                # recuperá-la/encerrá-la. Hotkey não substitui ícone de bandeja:
                # se o tray falhou, X fecha de verdade em vez de criar um
                # processo invisível que só o Gerenciador de Tarefas consegue matar.
                can_hide = bool(desktop_status.get("tray_ready"))
        except Exception:
            can_hide = False

        if (
            not self._exit_requested
            and can_hide
        ):
            self._hide_to_tray()
            return

        if self.is_processing:
            if not messagebox.askyesno(
                "Confirmação",
                f"{PUBLIC_NAME} está processando. Deseja encerrar mesmo assim?"
            ):
                self._exit_requested = False
                return

        self.logger.info(
            "Interface encerrada pelo usuário",
            "GUI"
        )

        try:
            if self._voice_followup_job and self.root:
                self.root.after_cancel(self._voice_followup_job)
                self._voice_followup_job = None
        except Exception:
            pass

        try:
            if self._ui_event_job and self.root:
                self.root.after_cancel(
                    self._ui_event_job
                )
                self._ui_event_job = None
        except Exception:
            pass

        try:
            if self._log_update_job and self.root:
                self.root.after_cancel(self._log_update_job)
                self._log_update_job = None
        except Exception:
            pass

        try:
            if self.qt_voice_overlay:
                self.qt_voice_overlay.stop()
        except Exception:
            pass

        try:
            if self.desktop_integration:
                self.desktop_integration.stop()
        except Exception:
            pass

        try:
            if self.goal_executor:
                self.goal_executor.cancel()
        except Exception:
            pass

        try:
            if self.observer_engine:
                self.observer_engine.stop()
        except Exception:
            pass

        try:
            if self.voice_engine:
                self.voice_engine.stop()
        except Exception:
            pass

        try:
            self._root_hidden_before_voice = True
            self._close_voice_overlay()
        except Exception:
            pass

        try:
            if self._jarvis_lightning_job and self.root:
                self.root.after_cancel(
                    self._jarvis_lightning_job
                )
                self._jarvis_lightning_job = None
        except Exception:
            pass

        try:
            if self.experience_engine is not None:
                self.experience_engine.close()
        except Exception:
            pass

        try:
            if self.behavior_memory is not None:
                self.behavior_memory.close()
        except Exception:
            pass

        try:
            if (
                hasattr(self, "memory_store")
                and self.memory_store
            ):
                self.memory_store.close()
        except Exception:
            pass

        self.root.destroy()

    def run(self):
        """Inicia a interface"""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.logger.info("Programa interrompido", "GUI")
            self.root.destroy()
