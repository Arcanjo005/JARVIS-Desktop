from __future__ import annotations

import ast
from pathlib import Path

import core
from jarvis_version import BUILD

ROOT = Path(__file__).resolve().parent
GUI = (ROOT / "gui.py").read_text(encoding="utf-8")
CORE = (ROOT / "core.py").read_text(encoding="utf-8")
checks = 0


def check(condition, detail=""):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(detail or f"check {checks} failed")


check(BUILD.endswith("beta.16") or "desktop." in BUILD, BUILD)

# Composer conversacional: multilinha, Enter local e nenhum Return global.
check("self.text_input = ctk.CTkTextbox(" in GUI)
check('self.text_input.bind("<Return>", self._on_composer_return' in GUI)
check("Shift+Enter" in GUI)
check("COMPOSER_MAX_CHARS = 16000" in GUI)
check('self.root.bind("<Return>"' not in GUI)
check("self.text_input.focus_set()" in GUI)

# Historico grande entra em lotes e nao trava a mainloop.
restore_start = GUI.index("    def _cancel_history_restore")
restore_end = GUI.index("    def _clear_chat_widgets", restore_start)
restore = GUI[restore_start:restore_end]
check("batch_size = 10" in restore)
check("self.root.after(1, lambda: render_batch(end))" in restore)
check("suppress_autoscroll=True" in restore)
check("_history_restore_generation" in restore)
check("_deferred_visual_messages" in restore)
check("self._set_composer_enabled(False)" in restore)
check("self._set_composer_enabled(True)" in restore)
check("self._restoring_history = True" not in restore)
for method_name in ("_new_conversation", "_switch_conversation", "_delete_conversation"):
    start = GUI.index(f"    def {method_name}")
    next_def = GUI.find("\n    def ", start + 10)
    method_src = GUI[start: next_def if next_def > 0 else len(GUI)]
    check("_invalidate_active_work()" in method_src, method_name)

bubble_start = GUI.index("    def _create_chat_bubble")
bubble_end = GUI.index("    def _set_message_text", bubble_start)
bubble = GUI[bubble_start:bubble_end]
check("if not suppress_autoscroll and not self._restoring_history:" in bubble)

# Scroll e streaming nao podem gerar fila infinita ou resposta velha.
wheel_start = GUI.index("    def _install_chat_mousewheel")
wheel_end = GUI.index("    def _queue_stream_chunk_threadsafe", wheel_start)
wheel = GUI[wheel_start:wheel_end]
check(".bind_all(" not in wheel)
check("max(-12, min(12" in wheel)
check("_chat_wheel_remainder" in wheel)
check('return "break"' in wheel)
scroll_start = GUI.index("    def _schedule_chat_scroll")
scroll_end = GUI.index("    def _queue_voice_stream_tts_ready", scroll_start)
scroll = GUI[scroll_start:scroll_end]
check("after_cancel(self._chat_scroll_job)" in scroll)
check("_chat_manual_scroll_until" in scroll)
check("_active_stream_token" in GUI)
check('self._post_ui_event("stream_start", work_token, PUBLIC_NAME)' in GUI)
check('self._post_ui_event("stream_finish", work_token, response)' in GUI or 'self._post_ui_event("stream_finish", work_token, result)' in GUI)
check("def _discard_streaming_visual" in GUI)

# Toda chamada Tk imediata de worker passa pela fila segura.
tree = ast.parse(GUI)
after_zero = []
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "after" and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == 0:
            after_zero.append(node.lineno)
check(not after_zero, f"root.after(0) remanescentes: {after_zero}")
check('elif event_name == "work_ui_call":' in GUI)
check("self._work_thread_context = threading.local()" in GUI)
check("def _post_context_ui_call" in GUI)

process_start = GUI.index('    def _process_message(self, message: str, source: str = "text"):')
process_end = GUI.index("    def _detect_system_command", process_start)
process = GUI[process_start:process_end]
check("self._post_ui_call(" not in process)
check("self._post_work_ui_call(work_token" in process)
check("self._work_thread_context.token = work_token" in process)
check("self._work_thread_context.token = 0" in process)
check("def _clear_stream_chunk_queue" in GUI)

# Mensagens fora da Tk herdam o token do turno e nao aparecem atrasadas.
add_start = GUI.index("    def add_message")
add_end = GUI.index("    def _speak", add_start)
add = GUI[add_start:add_end]
check("self._post_context_ui_call(" in add)
check("voice_turn = bool(self._voice_command_active)" in add)
check(add.count("self._speak_voice_response_if_needed(message)") == 1)
check(add.count("self._speak(message)") == 1)

# Nova digitacao interrompe TTS anterior mesmo se a geracao ja terminou.
send_start = GUI.index("    def send_message")
send_end = GUI.index("    @staticmethod\n    def _v8_text_failed", send_start)
send = GUI[send_start:send_end]
check("self.voice_engine.stop_speaking(clear_queue=True)" in send)
check("cancel_active_response" in send)
check("_discard_streaming_visual()" in send)
check("self.goal_executor.cancel()" in send)
check("Tive um erro interno" in GUI)
check("self.root.update()" not in GUI[GUI.index("    def _copy_to_clipboard"):GUI.index("    def _copy_conversation")])

# Cache semantico so guarda conhecimento estavel, nunca follow-up deitico.
ctx = core.JarvisCore.__new__(core.JarvisCore)
check(ctx._cache_ttl_for("o que e memoria RAM") > 0)
check(ctx._cache_ttl_for("e isso?") == 0)
check(ctx._cache_ttl_for("me explica isso") == 0)
check(ctx._cache_ttl_for("como funciona essa parte") == 0)
check(ctx._semantic_cache_topic("me explica isso") == "")
check(ctx._semantic_cache_topic("como funciona memoria RAM").startswith("howworks:"))

# "sim/isso/pode ser" depois de pergunta do JARVIS deve continuar com contexto.
history = [
    {"is_user": True, "message": "Quero configurar o modo de voz"},
    {"is_jarvis": True, "message": "Prefere o modo contínuo?"},
]
check(ctx._instant_conversation_response("pode ser", conversation_history=history) == "")
check(ctx._instant_conversation_response("sim", conversation_history=history) == "")
check(bool(ctx._instant_conversation_response("obrigado", conversation_history=[])))

# Contexto de follow-up maior e memoria antiga explicitamente subordinada ao turno atual.
prompt = ctx._prepare_context(
    "e o segundo?",
    [
        {"is_user": i % 2 == 0, "is_jarvis": i % 2 == 1, "message": f"msg {i}"}
        for i in range(12)
    ],
    ["uma preferencia antiga"],
)
check("msg 2" in prompt and "msg 11" in prompt)
check("memória" in prompt.lower() and "atual" in prompt.lower())
check("transcrição fonética" in prompt)
check("def cancel_active_response" in CORE)

print(f"JARVIS BUILD 16 SELFTEST: PASS ({checks} verificacoes)")
