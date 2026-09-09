"""
JARVIS - Visão da tela.

Captura apenas o monitor solicitado (por padrão, monitor ativo) e envia a
imagem inline para o cliente google-genai já configurado no core do JARVIS.
"""

from __future__ import annotations

import io
import os
import time
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from PIL import Image
from google.genai import types


class VisionSystem:
    MODEL = "gemini-3.5-flash-lite"

    def __init__(
        self,
        project_dir: str,
        core,
        window_manager=None,
        logger=None,
    ):
        self.project_dir = Path(
            project_dir
        )
        self.core = core
        self.model = str(
            getattr(core, "FAST_MODEL", self.MODEL)
            or self.MODEL
        )
        self.window_manager = (
            window_manager
        )
        self.logger = logger

        self.screenshot_dir = (
            self.project_dir
            / "data"
            / "screenshots"
        )
        self.screenshot_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        self.last_screenshot = None
        self.last_error = ""

    def _log(
        self,
        level: str,
        message: str
    ):
        if not self.logger:
            return

        try:
            fn = getattr(
                self.logger,
                level,
                None
            )
            if callable(fn):
                try:
                    fn(
                        message,
                        "VISION"
                    )
                except TypeError:
                    fn(
                        message
                    )
        except Exception:
            pass

    def _monitor(
        self,
        monitor_index: Optional[int]
    ) -> Dict:
        import mss

        # Usa o mesmo mapa geométrico do Window Manager para mover e capturar
        # janelas. Isso elimina divergência entre "monitor 2" do Router e o
        # índice escolhido pelo módulo de visão.
        wm_monitors = []
        if self.window_manager:
            try:
                wm_monitors = list(self.window_manager.get_monitors() or [])
            except Exception:
                wm_monitors = []

        with mss.mss() as sct:
            raw_monitors = list(sct.monitors[1:])

        if not raw_monitors:
            raise RuntimeError("Nenhum monitor detectado.")

        monitors = wm_monitors or [
            {
                "index": idx,
                "left": int(item["left"]),
                "top": int(item["top"]),
                "width": int(item["width"]),
                "height": int(item["height"]),
            }
            for idx, item in enumerate(raw_monitors, start=1)
        ]

        if monitor_index is None:
            if self.window_manager:
                active = self.window_manager.get_active_monitor()
                monitor_index = int(active["index"])
            else:
                monitor_index = 1

        requested = int(monitor_index)
        selected = next((m for m in monitors if int(m.get("index", 0)) == requested), None)
        if selected is None:
            raise RuntimeError(
                f"Monitor {requested} não existe. Detectei {len(monitors)} monitor(es)."
            )

        return {
            "index": requested,
            "left": int(selected["left"]),
            "top": int(selected["top"]),
            "width": int(selected["width"]),
            "height": int(selected["height"]),
        }

    def capture(
        self,
        monitor_index: Optional[int] = None,
        save: bool = True,
    ) -> Dict:
        import mss

        monitor = self._monitor(
            monitor_index
        )
        captured_dt = datetime.now().astimezone()
        captured_at = captured_dt.isoformat(timespec="seconds")

        with mss.mss() as sct:
            shot = sct.grab({
                "left": monitor["left"],
                "top": monitor["top"],
                "width": monitor["width"],
                "height": monitor["height"],
            })

        image = Image.frombytes(
            "RGB",
            shot.size,
            shot.rgb
        )

        # Reduz custo de visão sem perder legibilidade na maioria das telas.
        max_width = 1920

        if image.width > max_width:
            ratio = (
                max_width
                / image.width
            )
            image = image.resize(
                (
                    max_width,
                    int(
                        image.height
                        * ratio
                    )
                ),
                Image.Resampling.LANCZOS
            )

        buffer = io.BytesIO()

        image.save(
            buffer,
            format="JPEG",
            quality=88,
            optimize=True
        )

        data = buffer.getvalue()
        path = None

        if save:
            stamp = captured_dt.strftime(
                "%Y%m%d_%H%M%S_%f"
            )
            path = (
                self.screenshot_dir
                / (
                    f"monitor_{monitor['index']}_"
                    f"{stamp}.jpg"
                )
            )
            path.write_bytes(
                data
            )
            self.last_screenshot = str(
                path
            )

        return {
            "bytes": data,
            "mime_type": "image/jpeg",
            "monitor": monitor,
            "path": str(path) if path else "",
            "captured_at": captured_at,
            "capture_id": hashlib.sha1(data).hexdigest()[:12],
            "captured_monotonic": time.monotonic(),
        }


    def locate_ui_target(
        self,
        description: str,
        monitor_index: Optional[int] = None,
    ) -> Dict:
        """Localiza um elemento VISIVEL e devolve coordenadas absolutas seguras.

        Coordenadas sao pedidas em escala 0..1000 para ficarem independentes
        do redimensionamento JPEG usado na analise. O caller decide se clica.
        """
        if not self.core or not getattr(self.core, "client", None):
            return {"found": False, "confidence": 0.0, "reason": "vision_unavailable"}
        shot = self.capture(monitor_index=monitor_index, save=True)
        prompt = (
            "Voce e um localizador de interface do JARVIS no Windows. "
            f"A imagem contem SOMENTE o monitor {shot['monitor']['index']}. "
            "Localize APENAS um elemento atualmente visivel e clicavel que corresponda a descricao. "
            "Nao invente elemento escondido, nao use memoria de capturas anteriores e nao escolha anuncio/patrocinado "
            "quando a descricao disser para ignorar anuncios. "
            "Responda SOMENTE JSON valido neste formato: "
            '{"found":true,"x":500,"y":500,"confidence":0.95,"label":"texto curto","reason":""}. '
            "x e y devem estar entre 0 e 1000, relativos a largura/altura da imagem. "
            "Se nao houver um unico alvo com seguranca, use found=false e confidence <= 0.5.\n\n"
            "Descricao do alvo: " + str(description)
        )
        part = types.Part.from_bytes(data=shot["bytes"], mime_type=shot["mime_type"])
        try:
            response = self.core.client.models.generate_content(
                model=self.model,
                contents=[prompt, part],
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                    max_output_tokens=220,
                    temperature=0,
                ),
            )
            raw = str(getattr(response, "text", "") or "").strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
            if not raw.startswith("{"):
                m = re.search(r"\{.*\}", raw, flags=re.S)
                raw = m.group(0) if m else "{}"
            data = json.loads(raw)
        except Exception as exc:
            self._log("warning", f"Localizacao visual falhou: {exc}")
            return {"found": False, "confidence": 0.0, "reason": str(exc)}

        found = bool(data.get("found"))
        try:
            confidence = max(0.0, min(float(data.get("confidence") or 0.0), 1.0))
            nx = max(0.0, min(float(data.get("x") or 0.0), 1000.0))
            ny = max(0.0, min(float(data.get("y") or 0.0), 1000.0))
        except Exception:
            return {"found": False, "confidence": 0.0, "reason": "invalid_coordinates"}
        monitor = shot["monitor"]
        abs_x = int(monitor["left"] + (nx / 1000.0) * monitor["width"])
        abs_y = int(monitor["top"] + (ny / 1000.0) * monitor["height"])
        result = {
            "found": found,
            "confidence": confidence,
            "x": abs_x,
            "y": abs_y,
            "label": str(data.get("label") or "").strip(),
            "reason": str(data.get("reason") or "").strip(),
            "monitor": int(monitor["index"]),
            "capture_id": shot.get("capture_id", ""),
        }
        self._log(
            "info",
            f"UI target found={found} conf={confidence:.2f} monitor={monitor['index']} label={result['label'][:80]}",
        )
        return result

    def analyze(
        self,
        question: str,
        monitor_index: Optional[int] = None,
    ) -> str:
        """Sempre captura uma imagem NOVA; nunca reutiliza last_screenshot como entrada."""
        try:
            # V6: invalida qualquer referência visual anterior antes de cada pedido.
            # last_screenshot continua apenas como diagnóstico após a NOVA captura.
            self.last_screenshot = None
            if not self.core or not getattr(self.core, "client", None):
                return (
                    "A visão está indisponível porque o cliente Gemini "
                    "não está configurado."
                )

            last_exc = None
            for attempt in range(2):
                # Cada tentativa captura novamente. Isso impede resposta baseada em
                # screenshot anterior quando a tela já mudou.
                shot = self.capture(monitor_index=monitor_index, save=True)
                now_text = datetime.now().astimezone().isoformat(timespec="seconds")
                prompt = (
                    "Você é o módulo de visão do assistente JARVIS no Windows. "
                    f"A imagem anexada contém SOMENTE o monitor {shot['monitor']['index']} solicitado. "
                    "Não diga que outro monitor aparece ao fundo ou parcialmente: pixels de outros monitores "
                    "não fazem parte desta captura. Esta requisição é independente de qualquer análise visual anterior. "
                    f"A imagem anexada foi capturada AGORA em {shot['captured_at']} "
                    f"(hora local atual no envio: {now_text}; id da captura: {shot['capture_id']}). "
                    "Analise SOMENTE a imagem anexada nesta requisição. Não use nem cite "
                    "horários, telas ou elementos de capturas anteriores. "
                    "Se houver um relógio visível, leia o horário VISÍVEL e diferencie-o do "
                    "horário de captura. Não invente botões, mensagens ou estados. "
                    "Se o usuário perguntar onde está algo, descreva a posição de forma prática. "
                    "Se houver erro, transcreva apenas o essencial. Se não conseguir ler algo "
                    "com segurança, diga isso.\n\nPergunta do usuário: " + str(question)
                )

                part = types.Part.from_bytes(
                    data=shot["bytes"],
                    mime_type=shot["mime_type"],
                )
                try:
                    response = self.core.client.models.generate_content(
                        model=self.model,
                        contents=[prompt, part],
                        config=types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                            max_output_tokens=900,
                        ),
                    )
                    text = str(getattr(response, "text", "") or "").strip()
                    if text:
                        self.last_error = ""
                        self._log(
                            "info",
                            f"Tela fresca analisada: monitor {shot['monitor']['index']} "
                            f"captura={shot['capture_id']} em {shot['captured_at']}"
                        )
                        return text
                    last_exc = RuntimeError("modelo não retornou texto")
                except Exception as exc:
                    last_exc = exc
                    self._log("warning", f"Visão tentativa {attempt + 1} falhou: {exc}")

            raise RuntimeError(str(last_exc or "falha desconhecida na visão"))

        except Exception as exc:
            self.last_error = str(exc)
            self._log("error", f"Falha na visão: {exc}")
            return f"Não consegui analisar a tela agora: {exc}"

    def status(self) -> Dict:
        return {
            "ok": bool(
                self.core
                and getattr(
                    self.core,
                    "client",
                    None
                )
            ),
            "model": self.model,
            "last_screenshot": self.last_screenshot,
            "last_error": self.last_error,
        }
