"""
JARVIS - Diagnóstico automático.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List

from jarvis_version import PUBLIC_NAME

try:
    from hardware_profile import HardwareProfile
except Exception:
    HardwareProfile = None

try:
    from semantic_language import linguistic_profile
except Exception:
    linguistic_profile = None


class DiagnosticsManager:
    def __init__(
        self,
        project_dir: str,
        logger=None
    ):
        self.project_dir = Path(
            project_dir
        )
        self.logger = logger

    @staticmethod
    def _mark(
        ok: bool
    ) -> str:
        return "✓" if ok else "✗"

    def _dependency(
        self,
        module: str
    ) -> bool:
        try:
            return (
                importlib.util.find_spec(
                    module
                )
                is not None
            )
        except Exception:
            return False

    def run(
        self,
        core=None,
        memory_store=None,
        voice_engine=None,
        desktop=None,
        windows=None,
        audio=None,
        vision=None,
        actions=None,
        performance=None,
        context=None,
        media_context=None,
        conditional_rules=None,
        behavior_memory=None,
    ) -> str:
        lines = [
            f"=== {PUBLIC_NAME} - DIAGNÓSTICO AUTOMÁTICO ===",
            "",
            f"Python: {sys.version.split()[0]}",
            f"Windows: {platform.platform()}",
        ]

        if HardwareProfile is not None:
            try:
                hw = HardwareProfile(self.project_dir, logger=self.logger).snapshot(include_gpu=True)
                lines.append(
                    f"CPU: {hw.get('cpu') or '?'} | "
                    f"{hw.get('physical_cores', '?')} físicos / {hw.get('logical_cores', '?')} lógicos | "
                    f"RAM={hw.get('ram_gb', '?')} GB"
                )
                lines.append(
                    f"Perfil {PUBLIC_NAME}: Whisper CPU={hw.get('whisper_cpu_threads', '?')} threads | "
                    f"TTS workers={hw.get('tts_prefetch_workers', '?')} | "
                    f"READ workers={hw.get('read_parallel_workers', '?')}"
                )
                lines.append(
                    "GPU: " + (", ".join(hw.get('gpus') or []) or "não identificada")
                )
                gpu_cfg = hw.get('gpu_stt') or {}
                if gpu_cfg.get('enabled'):
                    lines.append(
                        f"GPU STT ✓  backend={gpu_cfg.get('backend')}  "
                        f"gpu={gpu_cfg.get('gpu_name') or '-'}  modelo={gpu_cfg.get('model') or '-'}"
                    )
                else:
                    lines.append(
                        "GPU STT - não habilitado; execute CONFIGURAR_GPU_AMD_VULKAN.bat para AMD/Radeon"
                    )
            except Exception as exc:
                lines.append(f"Hardware profile ?  {exc}")
        if linguistic_profile is not None:
            try:
                lp = linguistic_profile()
                lines.append(
                    f"Linguagem: {lp.get('language_profile', 'pt-BR')} | "
                    f"{lp.get('semantic_family_count', '?')} famílias semânticas | "
                    f"{lp.get('phonetic_transform_count', '?')} transformações fonéticas | "
                    f"léxico={lp.get('lexical_form_count', '?')} | "
                    f"cobertura potencial={int(lp.get('coverage_estimate', 0)):,}"
                )
            except Exception as exc:
                lines.append(f"Linguagem: ?  {exc}")
        lines.append("")

        # Gemini
        try:
            core_ok = bool(
                core
                and core.is_available()
            )
            lines.append(
                f"Gemini {self._mark(core_ok)}"
                + (
                    f"  modelo={getattr(core, 'FAST_MODEL', '?')}"
                    if core
                    else ""
                )
            )
        except Exception as exc:
            lines.append(
                f"Gemini ✗  {exc}"
            )

        # Memória
        try:
            db_path = Path(
                memory_store.db_path
            )
            memory_ok = db_path.exists()

            db_check = "?"
            if memory_ok:
                connection = sqlite3.connect(
                    str(db_path)
                )
                try:
                    db_check = connection.execute(
                        "PRAGMA quick_check"
                    ).fetchone()[0]
                finally:
                    connection.close()

            lines.append(
                f"Memória {self._mark(memory_ok and db_check == 'ok')}"
                f"  banco={db_check}"
            )

        except Exception as exc:
            lines.append(
                f"Memória ✗  {exc}"
            )


        # Contexto/midia/regras/aprendizado operacional
        try:
            if media_context is not None:
                media = media_context.current() or {}
                label = media.get("service") or media.get("player") or "-"
                item = str(media.get("item") or "")[:80]
                lines.append(
                    f"Media Context V2 ✓  player={label}  "
                    f"confianca={float(media.get('confidence') or 0.0):.2f}"
                    + (f"  item={item}" if item else "")
                )
        except Exception as exc:
            lines.append(f"Media Context V2 ?  {exc}")
        try:
            if conditional_rules is not None:
                rows = conditional_rules.list() or []
                enabled = sum(1 for r in rows if r.get("enabled", True))
                lines.append(f"Regras condicionais V2 ✓  ativas={enabled}  total={len(rows)}")
        except Exception as exc:
            lines.append(f"Regras condicionais V2 ?  {exc}")
        try:
            if behavior_memory is not None:
                bs = behavior_memory.stats() or {}
                lines.append(
                    f"Behavior Memory V2 ✓  transicoes={bs.get('patterns', 0)}  "
                    f"sequencias={bs.get('sequences', 0)}  acoes={bs.get('action_patterns', 0)}"
                )
        except Exception as exc:
            lines.append(f"Behavior Memory V2 ?  {exc}")

        # Voz
        if voice_engine:
            try:
                status = voice_engine.status()
                mic_ok = bool(
                    status.get(
                        "microphone_available"
                    )
                )
                wake_ok = bool(
                    status.get(
                        "wake_model_ready"
                    )
                )
                whisper_ok = bool(
                    status.get(
                        "whisper_ready"
                    )
                )

                tts_status = status.get(
                    "tts_ok"
                )

                lines.append(
                    f"Microfone {self._mark(mic_ok)}"
                    f"  {status.get('input_device') or 'não detectado'}"
                )
                lines.append(
                    f"Wake word {self._mark(wake_ok)}"
                    f"  final={'SIM' if status.get('wake_requires_final') else 'NÃO'}"
                )
                wake_alive = status.get("wake_thread_alive")
                if wake_alive is None:
                    try:
                        thread = getattr(voice_engine, "_wake_thread", None)
                        wake_alive = bool(thread and thread.is_alive())
                    except Exception:
                        wake_alive = False
                classic_voice = "supervisor_thread_alive" not in status
                if classic_voice:
                    lines.append(
                        "Runtime de voz: "
                        f"ready={'SIM' if status.get('ready') else 'NÃO'}"
                        f"  wake-thread={'VIVA' if wake_alive else 'PARADA'}"
                        "  modo=ESTÁVEL-CLÁSSICO"
                        "  supervisor=DESATIVADO"
                    )
                else:
                    lines.append(
                        "Runtime de voz: "
                        f"ready={'SIM' if status.get('ready') else 'NÃO'}"
                        f"  wake-thread={'VIVA' if wake_alive else 'PARADA'}"
                        f"  supervisor={'VIVO' if status.get('supervisor_thread_alive') else 'PARADO'}"
                        f"  estágio={status.get('bootstrap_stage') or '-'}"
                        f"  idade={status.get('bootstrap_stage_age_ms', '-')} ms"
                        f"  autorestarts={status.get('self_heal_restarts', 0)}"
                    )
                lines.append(
                    "Identificação biométrica de voz "
                    + ("✓ cadastrada" if status.get("speaker_guard_enrolled") else "- desativada/opcional")
                )
                lines.append(
                    f"Voz: fala/captura={status.get('capture_ms') or '-'} ms"
                    f"  endpoint={status.get('endpoint_ms') or '-'} ms"
                    f"  motivo={status.get('endpoint_reason') or '-'}"
                    f"  STT={status.get('stt_ms') or '-'} ms"
                )
                lines.append(
                    f"Pós-fala: endpoint+STT={status.get('post_speech_ms') or '-'} ms"
                    f"  comando->fila TTS={status.get('voice_response_queue_ms') or '-'} ms"
                    f"  comando->primeiro áudio={status.get('tts_first_audio_ms') or '-'} ms"
                    f"  fim-da-fala->áudio={status.get('end_of_speech_to_audio_ms') or '-'} ms"
                    f"  ACK={'SIM' if status.get('voice_ack_enabled') else 'NÃO'}"
                )
                lines.append(
                    f"Microfone {status.get('mic_quality') or '?'}"
                    f"  ruído={status.get('noise_percent', '-')}%"
                    f"  gate={status.get('gate_percent', '-')}%"
                    f"  SNR={status.get('snr_db', '-')} dB"
                )
                if classic_voice:
                    lines.append(
                        "Captura de audio:"
                        f" modo={status.get('capture_mode') or 'stable-direct-16k'}"
                        "  driver=16000Hz direto"
                        f"  quadros={status.get('direct_frames_read', 0)}"
                        f"  ultimo-quadro={status.get('last_audio_frame_age_ms') if status.get('last_audio_frame_age_ms') is not None else '-'} ms"
                        f"  overflows={status.get('audio_driver_overflows', 0)}"
                    )
                    lines.append(
                        "Recuperacao de audio: sem callback/watchdog; "
                        f"falhas-reais={status.get('direct_open_failures', 0)}/3."
                    )
                else:
                    lines.append(
                        "Captura de audio:"
                        f" modo={status.get('capture_mode') or '-'}"
                        f"  driver={status.get('input_native_rate') or '-'}Hz->16000Hz"
                        f"  host={status.get('input_hostapi') or '-'}"
                        f"  rota={int(status.get('input_candidate_pos', 0)) + 1}/{max(1, int(status.get('input_candidate_count', 0) or 0))}"
                        f"  ring={status.get('audio_ring_depth', 0)}"
                        f"  descartados={status.get('audio_ring_dropped', 0)}"
                        f"  overflows={status.get('audio_driver_overflows', 0)}"
                        f"  callback={status.get('audio_callback_age_ms') if status.get('audio_callback_age_ms') is not None else '-'} ms"
                        f"  ultimo-quadro={status.get('last_audio_frame_age_ms') if status.get('last_audio_frame_age_ms') is not None else '-'} ms"
                    )
                    lines.append(
                        "Recuperacao de audio:"
                        f" streak={status.get('capture_reconnect_streak', 0)}"
                        f"  watchdog-callback={status.get('callback_watchdog_failures', 0)}"
                        f"  suspensa={'SIM' if status.get('auto_recovery_suspended') else 'NAO'}"
                    )
                lines.append(
                    f"STT principal: {status.get('stt_backend') or 'local'}"
                    f"  modo={status.get('transcript_mode') or '-'}"
                    f"  politica={status.get('stt_language_policy') or status.get('whisper_language') or 'pt'}"
                    f"  detectado={status.get('last_detected_language') or '-'}"
                    f"  bilingue={'SIM' if status.get('bilingual_recognition') else 'NÃO'}"
                )
                conv_on = bool(status.get('conversation_mode'))
                conv_open = bool(status.get('conversation_always_listen'))
                conv_state = "OUVINDO CONTINUO" if (conv_on and conv_open) else ("EM ESPERA" if status.get('conversation_passive') else "ATIVO")
                conv_sounds = bool(status.get('conversation_state_sounds')) if conv_on else bool(status.get('state_sounds'))
                lines.append(
                    f"Modo conversa contínua: {'SIM' if conv_on else 'NÃO'}"
                    f"  estado={conv_state if conv_on else '-'}"
                    f"  open-mic={'SIM' if (conv_on and conv_open) else 'NÃO'}"
                    f"  ocioso={status.get('conversation_idle_seconds', 0)}s"
                    f"  cues={'SIM' if conv_sounds else 'NÃO'}"
                )
                lines.append(
                    f"TTS: voz={status.get('tts_active_voice') or status.get('tts_voice') or '-'}"
                    f"  provider={status.get('tts_provider') or '-'}"
                    f"  rate={status.get('tts_rate') or '-'}"
                    f"  identidade={'TRAVADA' if status.get('tts_voice_lock') else 'FLEXÍVEL'}"
                    f"  fallback-local={'SIM' if status.get('tts_local_fallback_allowed') else 'NÃO'}"
                    f"  legenda={'palavra' if status.get('caption_word_sync') else 'texto-estavel'}"
                )
                vad_status = status.get("vad_status") or {}
                lines.append(
                    f"VAD V7: {status.get('endpoint_vad') or vad_status.get('backend') or '-'}"
                    f"  Silero={'SIM' if vad_status.get('silero_ready') else 'NÃO'}"
                    f"  WebRTC={'SIM' if vad_status.get('webrtc_ready') else 'NÃO'}"
                )
                fsm = status.get("state_machine") or {}
                lines.append(
                    f"FSM V7: {fsm.get('canonical_state') or '-'}"
                    f"  externo={fsm.get('external_state') or '-'}"
                    f"  detalhe={fsm.get('detail') or '-'}"
                    f"  transições inválidas={fsm.get('invalid_transitions', 0)}"
                )
                reliability = status.get("reliability") or {}
                timings = reliability.get("timings") or {}
                stt_timing = timings.get("stt") or {}
                capture_timing = timings.get("voice_capture") or {}
                if stt_timing or capture_timing:
                    lines.append(
                        "Telemetria V7: "
                        f"captura p50={capture_timing.get('p50_ms', '-')} ms "
                        f"p95={capture_timing.get('p95_ms', '-')} ms | "
                        f"STT p50={stt_timing.get('p50_ms', '-')} ms "
                        f"p95={stt_timing.get('p95_ms', '-')} ms"
                    )
                if status.get("deepgram_configured"):
                    lines.append(
                        f"Deepgram Flux ✓  modelo={status.get('deepgram_model') or '-'}"
                        f"  EOT={status.get('deepgram_eot_confidence', 0)}"
                        f"  palavra={status.get('deepgram_word_confidence', 0)}"
                    )
                    lines.append(
                        f"Flux: conexao={status.get('deepgram_connect_ms') or '-'} ms"
                        f"  cauda={status.get('deepgram_tail_ms') or '-'} ms"
                        f"  idiomas={','.join(status.get('deepgram_languages') or []) or '-'}"
                    )
                    if status.get("deepgram_last_error"):
                        lines.append(f"Último fallback Flux: {status.get('deepgram_last_error')}")
                else:
                    lines.append(
                        "Deepgram Flux - não configurado; execute CONFIGURAR_DEEPGRAM.bat"
                    )
                lines.append(
                    f"Whisper fallback {self._mark(whisper_ok)}"
                    f"  modelo={status.get('whisper_model')}"
                    f"  backend={status.get('whisper_backend') or '-'}"
                    f"  device={status.get('whisper_device') or '-'}"
                    f"  compute={status.get('whisper_compute_type') or '-'}"
                    f"  cpu_threads={status.get('whisper_cpu_threads') or '-'}"
                    f"  idioma={status.get('whisper_language') or 'pt'}"
                )
                if status.get("gpu_stt_last_error"):
                    lines.append(f"Último fallback GPU STT: {status.get('gpu_stt_last_error')}")

                if tts_status is None:
                    lines.append(
                        "TTS ?  ainda não testado nesta sessão"
                        f"  voz={status.get('tts_voice')}"
                        f"  velocidade={status.get('tts_rate') or '?'}"
                    )
                else:
                    lines.append(
                        f"TTS {self._mark(bool(tts_status))}"
                        f"  provider={status.get('tts_provider') or '-'}"
                        f"  voz={status.get('tts_voice')}"
                        f"  velocidade={status.get('tts_rate') or '?'}"
                    )

                if status.get(
                    "tts_last_error"
                ):
                    lines.append(
                        f"Último erro de TTS: {status['tts_last_error']}"
                    )

                if status.get(
                    "last_error"
                ):
                    lines.append(
                        f"Último erro de voz: {status['last_error']}"
                    )

            except Exception as exc:
                lines.append(
                    f"Voz ✗  {exc}"
                )
        else:
            lines.append(
                "Voz ✗  motor não carregado"
            )

        # Desktop
        if desktop:
            try:
                status = desktop.status()
                lines.append(
                    f"Bandeja {self._mark(bool(status.get('tray_ready')))}"
                )
                lines.append(
                    f"Atalho global {self._mark(bool(status.get('hotkey_ready')))}"
                    f"  {status.get('hotkey')}"
                )
                lines.append(
                    f"Iniciar com Windows "
                    f"{self._mark(bool(status.get('startup_enabled')))}"
                )
            except Exception as exc:
                lines.append(
                    f"Desktop ✗  {exc}"
                )

        # Monitores / janelas
        if windows:
            try:
                status = windows.status()
                lines.append(
                    f"Monitores ✓  {status.get('monitor_count')}"
                    f"  ativo={status.get('active_monitor')}"
                )
                lines.append(
                    f"Janela ativa: {status.get('active_window') or '(nenhuma)'}"
                )
            except Exception as exc:
                lines.append(
                    f"Monitores ✗  {exc}"
                )

        # Áudio
        if audio:
            try:
                status = audio.status()

                if status.get("ok"):
                    output = (
                        status.get("output")
                        or {}
                    )
                    input_device = (
                        status.get("input")
                        or {}
                    )

                    lines.append(
                        f"Saída de áudio ✓  "
                        f"{output.get('name') or 'não identificada'}"
                    )
                    lines.append(
                        f"Entrada de áudio ✓  "
                        f"{input_device.get('name') or 'não identificada'}"
                    )
                else:
                    lines.append(
                        f"Áudio ✗  {status.get('error')}"
                    )

            except Exception as exc:
                lines.append(
                    f"Áudio ✗  {exc}"
                )

        # Visão
        if vision:
            try:
                status = vision.status()
                lines.append(
                    f"Visão {self._mark(bool(status.get('ok')))}"
                    f"  modelo={status.get('model')}"
                )

                if status.get(
                    "last_error"
                ):
                    lines.append(
                        f"Último erro de visão: {status['last_error']}"
                    )
            except Exception as exc:
                lines.append(
                    f"Visão ✗  {exc}"
                )

        # Universal App Resolver / verificação determinística
        if actions:
            try:
                resolver = getattr(actions, "app_resolver", None)
                if resolver:
                    app_status = resolver.status()
                    lines.append(
                        f"App Resolver V7 ✓  locais={app_status.get('local_apps', 0)}"
                        f"  globais={app_status.get('global_apps', 0)}"
                        f"  aliases={app_status.get('personal_aliases', 0)}"
                    )
                    last = getattr(actions, "_last_app_resolution", {}) or {}
                    if last:
                        lines.append(
                            f"Última resolução: '{last.get('query', '')}'"
                            f"  confiança={last.get('confidence', 0)}"
                            f"  margem={last.get('margin', 0)}"
                            f"  segura={'SIM' if last.get('safe') else 'NÃO'}"
                        )
                else:
                    lines.append("App Resolver V7 ✗  fallback legado ativo")
                lines.append(
                    "Verificador de ações "
                    + ("✓" if getattr(actions, "action_verifier", None) else "✗")
                )
            except Exception as exc:
                lines.append(f"App Resolver V7 ✗  {exc}")

        # Performance / contexto operacional
        if performance:
            try:
                perf = performance.summary(50)
                if perf.get("count"):
                    lines.append(
                        f"Performance: amostras={perf.get('count')}  p50={perf.get('p50_ms')} ms  p95={perf.get('p95_ms')} ms"
                    )
                    lines.append(
                        f"Rotas: local p50={perf.get('local_p50_ms') or '-'} ms  Gemini p50={perf.get('gemini_p50_ms') or '-'} ms"
                        f"  texto p50={perf.get('text_p50_ms') or '-'} ms  voz pós-STT p50={perf.get('voice_p50_ms') or '-'} ms"
                    )
                    last = perf.get("last") or {}
                    if last:
                        lines.append(
                            f"Última interação: {last.get('total_ms', '-')} ms  source={last.get('source') or '-'}"
                            f"  intent={last.get('intent') or '-'}  etapas={last.get('stages') or {}}"
                        )
                    slow = perf.get("slowest") or []
                    if slow:
                        top = slow[0]
                        lines.append(
                            f"Pior recente: {top.get('total_ms', '-')} ms  intent={top.get('intent') or '-'}  etapas={top.get('stages') or {}}"
                        )
            except Exception as exc:
                lines.append(f"Performance ✗  {exc}")

        if context:
            try:
                ctx = context() if callable(context) else dict(context or {})
                if ctx:
                    lines.append(
                        f"Context Engine V{ctx.get('version', 2)}: app={ctx.get('app') or '-'}  monitor={ctx.get('monitor') or '-'}  "
                        f"acoes={ctx.get('actions', 0)}  referentes={len(ctx.get('references') or [])}  ultima={ctx.get('last_action') or '-'}"
                    )
            except Exception:
                pass

        # Dependências
        lines.extend([
            "",
            "Dependências:",
        ])

        dependencies = [
            ("sounddevice", "sounddevice"),
            ("Vosk", "vosk"),
            ("faster-whisper", "faster_whisper"),
            ("Edge TTS", "edge_tts"),
            ("pystray", "pystray"),
            ("MSS", "mss"),
            ("Pycaw", "pycaw"),
            ("Send2Trash", "send2trash"),
            ("WebRTC VAD", "webrtcvad"),
            ("Silero VAD", "silero_vad"),
            ("PySide6 overlay", "PySide6"),
            ("Speaker Guard", "sherpa_onnx"),
            ("Whisper.cpp Python", "pywhispercpp"),
        ]

        for label, module in dependencies:
            ok = self._dependency(
                module
            )
            lines.append(
                f"- {label}: {self._mark(ok)}"
            )

        return "\n".join(
            lines
        )
