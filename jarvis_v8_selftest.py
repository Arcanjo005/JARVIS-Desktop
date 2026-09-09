from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from jarvis_router import V8Router


def _commands(route):
    return [str(x).lower() for x in route.commands]


def _assert_route(text, kind, expected, intent=None):
    router = V8Router()
    result = router.route(text)
    assert result is not None, text
    assert result.kind == kind, (text, result.kind, kind, result)
    if intent is not None:
        assert result.intent == intent, (text, result.intent, intent)
    if expected is not None:
        got = _commands(result)
        exp = [str(x).lower() for x in expected]
        assert got == exp, (text, got, exp)


def check_router_regression():
    cases = [
        # Conversa nunca cai em comando/app/web.
        ("Como funciona o ChatGPT?", "conversation", [], "CONVERSATION"),
        ("Funciona o ChatGPT", "conversation", [], "CONVERSATION"),
        ("Tá tudo bem?", "local", ["v8:social_chat"], "SOCIAL_CHAT"),
        # Build 10: modo conversa contínua é local/determinístico.
        ("Modo conversa", "local", ["v8:mode:conversation"], "MODE_CONVERSATION"),
        ("Conversar", "local", ["v8:mode:conversation"], "MODE_CONVERSATION"),
        ("Vamos conversar", "local", ["v8:mode:conversation"], "MODE_CONVERSATION"),
        ("Sair do modo conversa", "local", ["v8:mode:auto"], "MODE_AUTO"),
        ("Modo auto", "local", ["v8:mode:auto"], "MODE_AUTO"),
        ("Modo comando", "local", ["v8:mode:command"], "MODE_COMMAND"),
        # Build 11: presença, autonomia, contexto e Agent Runtime.
        ("Modo JARVIS", "local", ["v8:presence:jarvis"], "PRESENCE_MODE"),
        ("Zero discreto", "local", ["v8:presence:discreto"], "PRESENCE_MODE"),
        ("Autonomia manual", "local", ["v8:autonomy:manual"], "AUTONOMY_MODE"),
        ("Autonomia assistida", "local", ["v8:autonomy:assistido"], "AUTONOMY_MODE"),
        ("O que você sabe agora", "local", ["v8:operational_context"], "OPERATIONAL_CONTEXT"),
        ("Qual foi o último download", "local", ["v8:last_download"], "LAST_DOWNLOAD"),
        ("O que copiei", "local", ["v8:clipboard"], "CLIPBOARD_CONTEXT"),
        ("Pula a abertura", "local", ["v8:crunchy:skip:0"], "CRUNCHY_SKIP"),
        ("Agora baixa esse arquivo", "local", ["v8:goal:baixa esse arquivo"], "AGENT_GOAL"),
        ("Entra nesse site", "local", ["v8:goal:Entra nesse site"], "AGENT_GOAL"),
        ("Aprende rotina trabalho", "local", ["v8:workflow:start:trabalho"], "WORKFLOW_START"),
        ("Terminar rotina", "local", ["v8:workflow:stop"], "WORKFLOW_STOP"),
        ("Executa rotina trabalho", "local", ["v8:workflow:run:trabalho"], "WORKFLOW_RUN"),
        ("Como está o meu PC", "local", ["status do pc"], "PC_DIAGNOSE"),
        ("Cara, como funciona o ChatGPT?", "conversation", [], "CONVERSATION"),
        ("Tá tudo bem com meu computador?", "local", ["status do pc"], "PC_DIAGNOSE"),
        # Fast lane local.
        ("Que horas são?", "local", ["v8:time"], "LOCAL_INSTANT"),
        ("Me diz a hora", "local", ["v8:time"], "LOCAL_INSTANT"),
        ("Saber a hora", "local", ["v8:time"], "LOCAL_INSTANT"),
        ("Hora", "local", ["v8:time"], "LOCAL_INSTANT"),
        ("Fala a hora", "local", ["v8:time"], "LOCAL_INSTANT"),
        ("Que dia é hoje?", "local", ["v8:date"], "LOCAL_INSTANT"),
        ("Que dia é hj", "local", ["v8:date"], "LOCAL_INSTANT"),
        ("Que dia e hj", "local", ["v8:date"], "LOCAL_INSTANT"),
        ("Qual é a data?", "local", ["v8:date"], "LOCAL_INSTANT"),
        ("Quanto de RAM estou usando?", "local", ["v8:ram"], "LOCAL_INSTANT"),
        ("Quanto de RAM esta consumindo", "local", ["v8:ram"], "LOCAL_INSTANT"),
        ("Passar a memoria RAM", "local", ["v8:ram"], "LOCAL_INSTANT"),
        ("Quanto de CPU estou usando?", "local", ["v8:cpu"], "LOCAL_INSTANT"),
        ("Qual programa está aberto agora?", "local", ["v8:open_windows"], "WINDOWS_LOCAL"),
        ("Qual programa aberto agora", "local", ["v8:open_windows"], "WINDOWS_LOCAL"),
        ("Programa aberto agora", "local", ["v8:open_windows"], "WINDOWS_LOCAL"),
        ("Janela ativa", "local", ["v8:active_window"], "WINDOWS_LOCAL"),
        ("Quantos monitores tem", "local", ["v8:monitors"], "LOCAL_INSTANT"),
        ("Quantas telas", "local", ["v8:monitors"], "LOCAL_INSTANT"),
        ("Tirar print", "local", ["v8:screenshot"], "SCREENSHOT"),
        ("O que você pode fazer?", "local", ["v8:capabilities"], "CAPABILITIES"),
        ("Mapa de capacidades", "local", ["v8:capabilities"], "CAPABILITIES"),
        ("Me manda capacidades", "local", ["v8:capabilities"], "CAPABILITIES"),
        # Visão.
        ("Descreve minha tela.", "local", ["descreve minha tela"], "VISION"),
        ("Descreve o que tem na minha tela", "local", ["descreve minha tela"], "VISION"),
        ("Descreve monitor 1.", "local", ["descreve monitor 1"], "VISION"),
        ("Descreve tela 1", "local", ["descreve monitor 1"], "VISION"),
        ("Descreve tela 2", "local", ["descreve monitor 2"], "VISION"),
        ("Tela 2", "local", ["descreve monitor 2"], "VISION"),
        ("Descreve segunda tela", "local", ["descreve monitor 2"], "VISION"),
        ("Descreve pra mim o que tem no monitor 1", "local", ["descreve monitor 1"], "VISION"),
        ("O que tem na área de trabalho?", "local", ["descreve minha tela"], "VISION"),
        ("Me explica essa imagem na tela 1", "local", ["v8:vision:1|Me explica essa imagem na tela 1"], "VISION"),
        # Apps + linguagem social.
        ("Abre Opera.", "local", ["Abre Opera"], "OPEN_APP"),
        ("Cara, abre o Opera aí pra mim.", "local", ["abre Opera"], "OPEN_APP"),
        ("Por favor, abre o Opera.", "local", ["abre Opera"], "OPEN_APP"),
        ("Abre BloodStrike.", "local", ["Abre BloodStrike"], "OPEN_APP"),
        ("Abre Discord.", "local", ["Abre Discord"], "OPEN_APP"),
        ("Abre meu navegador", "local", ["abre Opera"], "OPEN_APP"),
        # Build 6: camada lexical/semântica tolera erros reais de texto/STT.
        ("Abro Opera", "local", ["abre Opera"], "OPEN_APP"),
        ("Minimmiza Opera", "local", ["minimiza Opera"], "MINIMIZE_WINDOW"),
        ("Móvel Opera para outra tela", "local", ["v8:move_other:Opera"], "MOVE_OTHER"),
        ("Fichar o BS", "local", ["fecha OBS"], "CLOSE_APP"),
        # Multi-intent.
        ("Abre Opera e OBS.", "local", ["Abre Opera", "Abre OBS"], "MULTI_ACTION"),
        ("Abre aí o Opera e o OBS", "local", ["Abre Opera", "Abre OBS"], "MULTI_ACTION"),
        ("Abre Opera e depois abre OBS", "local", ["Abre Opera", "abre OBS"], "MULTI_ACTION"),
        ("Abrir Opera na tela 2", "local", ["Abrir Opera", "move Opera para monitor 2"], "MULTI_ACTION"),
        ("Abre Opera no segundo monitor", "local", ["Abre Opera", "move Opera para monitor 2"], "MULTI_ACTION"),
        ("Abre Opera, coloca ele no monitor 2 e depois abre OBS.", "local", ["Abre Opera", "coloca Opera para monitor 2", "abre OBS"], "MULTI_ACTION"),
        ("Abre Opera e vai pro mLabs", "local", ["Abre Opera", "v8:open_site_in_app:Opera|accounts.mlabs.io"], "MULTI_ACTION"),
        ("Abre Opera e vai pro Spotify", "local", ["Abre Opera", "v8:open_site_in_app:Opera|open.spotify.com"], "MULTI_ACTION"),
        # Arquivos/pastas + variações naturais.
        ("Cria uma pasta chamada Arcanjo na área de trabalho.", "local", ["crie pasta no desktop Arcanjo"], "CREATE_FOLDER"),
        ("Criar pasta Arcanjo", "local", ["crie pasta no desktop Arcanjo"], "CREATE_FOLDER"),
        ("Quero que crie uma pasta chamada Arcanjo.", "local", ["crie pasta no desktop Arcanjo"], "CREATE_FOLDER"),
        ("Quero criar uma pasta chamada Arcanjo", "local", ["crie pasta no desktop Arcanjo"], "CREATE_FOLDER"),
        ("Crie uma pasta chamada Arcanjo", "local", ["crie pasta no desktop Arcanjo"], "CREATE_FOLDER"),
        ("Faz uma pasta chamada Arcanjo", "local", ["crie pasta no desktop Arcanjo"], "CREATE_FOLDER"),
        ("Faça uma pasta chamada Arcanjo", "local", ["crie pasta no desktop Arcanjo"], "CREATE_FOLDER"),
        ("Cria uma pasta chamada Beta em downloads", "local", ["v8:create_folder:downloads|Beta"], "CREATE_FOLDER"),
        ("Cria uma pasta com nome de Beta", "local", ["crie pasta no desktop Beta"], "CREATE_FOLDER"),
        ("Crie pasta no desktop Arcanjo", "local", ["crie pasta no desktop Arcanjo"], "CREATE_FOLDER"),
        ("Cria um arquivo de texto chamado Arcanjo.", "local", ["v8:create_text:Arcanjo"], "CREATE_TEXT"),
        # Janelas: alvo deve chegar limpo.
        ("Minimiza Opera", "local", ["Minimiza Opera"], "MINIMIZE_WINDOW"),
        ("Minimiza janela Opera", "local", ["Minimiza Opera"], "MINIMIZE_WINDOW"),
        ("Maximiza Opera", "local", ["Maximiza Opera"], "MAXIMIZE_WINDOW"),
        ("Expande Opera", "local", ["Expande Opera"], "MAXIMIZE_WINDOW"),
        ("Move Opera para monitor 2", "local", ["Move Opera para monitor 2"], "MOVE_WINDOW"),
        ("Mandar Opera para tela 2", "local", ["move Opera para monitor 2"], "MOVE_WINDOW"),
        ("Mover janela Opera para segundo monitor", "local", ["Mover Opera para monitor 2"], "MOVE_WINDOW"),
        ("Coloca o Opera no segundo monitor", "local", ["Coloca Opera para monitor 2"], "MOVE_WINDOW"),
        ("Bota o Opera na outra tela", "local", ["v8:move_other:Opera"], "MOVE_OTHER"),
        ("Volta o Opera para tela 2", "local", ["move Opera para monitor 2"], "MOVE_WINDOW"),
        ("Abaixo ao volume para 50", "local", ["volume em 50"], "LEGACY"),
        # Site sem contexto continua local, nunca pesquisa automática.
        ("Abre o YouTube", "local", ["abra o site youtube.com"], "OPEN_SITE"),
        ("Pesquisa como o ChatGPT funciona no Opera", "local", ["v8:browser_search:Opera|como o ChatGPT funciona"], "BROWSER_SEARCH"),
        # Interrupção textual final; a interrupção durante TTS usa a via acústica.
        ("Zero, para.", "local", ["v8:interrupt"], "PRIORITY_INTERRUPT"),
        ("Zero, cancela.", "local", ["v8:interrupt"], "PRIORITY_INTERRUPT"),
    ]
    for case in cases:
        _assert_route(*case)

    # Pronome em uma mesma frase depende do OPEN anterior.
    router = V8Router()
    result = router.route("Abre Opera, coloca ele no monitor 2 e depois abre OBS")
    assert len(result.steps) == 3
    assert result.steps[1].depends_on == 0
    assert result.steps[1].require_success is True
    assert result.steps[2].depends_on is None

    # Contexto de app entre turnos só existe após execução confirmada.
    router = V8Router()
    router.route("Abre Opera")
    before = router.route("Vai pro YouTube")
    assert before.commands == ["abra o site youtube.com"]
    router.mark_app_success("Opera")
    after = router.route("Vai pro YouTube")
    assert after.commands == ["v8:open_site_in_app:Opera|youtube.com"]

    # Pronome de app nunca cai na janela ativa sem antecedente confirmado.
    router = V8Router()
    assert router.route("Minimiza ele").commands == ["v8:clarify_app"]
    assert router.route("Fecha ele").commands == ["v8:clarify_app"]
    router.route("Abre Opera")  # planejamento sozinho não cria contexto.
    assert router.route("Move ele para monitor 2").commands == ["v8:clarify_app"]
    router.mark_app_success("Opera")
    assert router.route("Minimiza ele").commands == ["Minimiza Opera"]
    assert router.route("Minimiza ele agora").commands == ["Minimiza Opera"]
    assert router.route("Maximiza ele").commands == ["Maximiza Opera"]
    assert router.route("outra tela").commands == ["v8:move_other:Opera"]
    assert router.route("para outra agora").commands == ["v8:move_other:Opera"]
    assert router.route("move Opera").commands == ["v8:clarify_move:Opera"]
    assert router.route("Abre ele").commands == ["Abre Opera"]
    assert router.route("Fecha ele").commands == ["Fecha Opera"]
    assert router.route("Vai pro mLabs").commands == ["v8:open_site_in_app:Opera|accounts.mlabs.io"]
    assert router.route("Vai pro Spotify").commands == ["v8:open_site_in_app:Opera|open.spotify.com"]

    # Build 8: slots de dialogo completam apenas a informacao ausente.
    router = V8Router()
    assert router.route("move Discord").commands == ["v8:clarify_move:Discord"]
    assert router.route("2").commands == ["move Discord para monitor 2"]
    router = V8Router()
    assert router.route("pesquisa no Opera").commands == ["v8:browser_search:Opera|"]
    assert router.route("filmes de terror recentes").commands == ["v8:browser_search:Opera|filmes de terror recentes"]

    # Build 9: ação elíptica guarda o alvo faltante.
    router = V8Router()
    assert router.route("agora fecha").commands == ["v8:clarify_app"]
    assert router.route("o Opera").commands == ["fecha Opera"]

    # Dentro da mesma frase, navegação contextual depende da abertura do browser.
    router = V8Router()
    plan = router.route("Abre Opera e depois entra no YouTube")
    assert plan.commands == ["Abre Opera", "v8:open_site_in_app:Opera|youtube.com"]
    assert plan.steps[1].depends_on == 0 and plan.steps[1].require_success

    # OPEN + monitor também é uma dependência explícita.
    router = V8Router()
    plan = router.route("Abre Opera na tela 2")
    assert plan.commands == ["Abre Opera", "move Opera para monitor 2"]
    assert plan.steps[1].depends_on == 0 and plan.steps[1].require_success

    # OPEN + MOVE podem vir colados na fala sem "e": a entidade do app não
    # pode virar "opera colocar".
    router = V8Router()
    plan = router.route("abre opera colocar na tela 2, mas antes abre o obs")
    assert plan.commands == ["abre obs", "abre opera", "move opera para monitor 2"]
    assert plan.steps[2].depends_on == 1 and plan.steps[2].require_success

    # Contexto visual curto.
    router = V8Router()
    first = router.route("Descreve monitor 1")
    second = router.route("Agora descreve o que tem nele")
    assert first.commands == ["descreve monitor 1"]
    assert second.commands == ["descreve monitor 1"]

    return len(cases) + 18


def check_window_primitives():
    import ctypes
    from advanced_windows import AdvancedWindows, RECT

    class FakeUser32:
        def IsWindowVisible(self, hwnd):
            return 1
        def IsIconic(self, hwnd):
            return 1
        def GetWindowRect(self, hwnd, ptr):
            rect = ctypes.cast(ptr, ctypes.POINTER(RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = -32000, -32000, -31840, -31972
            return 1
        def GetWindowThreadProcessId(self, hwnd, ptr):
            if ptr:
                ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ulong)).contents.value = 123
            return 1

    manager = object.__new__(AdvancedWindows)
    manager.user32 = FakeUser32()
    manager.kernel32 = None
    manager.logger = None
    manager._window_title = lambda hwnd: "OBS 32.1.2 - Perfil: Sem nome"
    manager._process_name_for_hwnd = lambda hwnd: "obs64.exe"
    item = manager._window_item(100, require_visible=True)
    assert item is not None, "janela minimizada foi descartada"
    assert item["height"] == 28
    assert manager._score_window("obs", item["title"], item["process_name"]) >= 0.98

    manager2 = object.__new__(AdvancedWindows)
    manager2.list_windows = lambda: [
        {"title": "JARVIS - Assistente de Sistema", "process_name": "python.exe"},
        {"title": "Discagem Rápida - Opera", "process_name": "opera.exe"},
        {"title": "Instagram - Opera", "process_name": "opera.exe"},
        {"title": "OBS 32.1.2", "process_name": "obs64.exe"},
        {"title": "Program Manager", "process_name": "explorer.exe"},
    ]
    manager2.active_window_title = lambda: "Discagem Rápida - Opera"
    apps = manager2.list_open_applications()
    names = [row["name"] for row in apps]
    assert names[0] == "Opera" and apps[0]["active"] is True
    assert apps[0]["window_count"] == 2
    assert "OBS Studio" in names and "JARVIS" in names

    # Photoshop/Adobe: a palette pequena do mesmo processo nao pode vencer
    # a janela principal ao resolver o alvo por nome do aplicativo.
    manager3 = object.__new__(AdvancedWindows)
    manager3.list_windows = lambda: [
        {
            "hwnd": 11, "title": "Camadas", "process_name": "Photoshop.exe",
            "width": 290, "height": 760, "area": 220400,
            "owner_hwnd": 99, "is_tool_window": True, "foreground": True,
        },
        {
            "hwnd": 22, "title": "MES DOS PAIS FEED.psd @ 38%", "process_name": "Photoshop.exe",
            "width": 1920, "height": 1080, "area": 2073600,
            "owner_hwnd": 0, "is_tool_window": False, "foreground": False,
        },
    ]
    main = manager3.find_window("photoshop", min_score=0.60)
    assert main is not None and main["hwnd"] == 22, main
    return 7


def check_voice_primitives():
    from voice_engine import VoiceEngine, _AudioRingStream

    # Priority Interrupt: frases muito próximas/exatas; conversa comum não interrompe.
    engine = object.__new__(VoiceEngine)
    assert engine._is_interrupt_phrase("jarvis para")
    assert engine._is_interrupt_phrase("jarvis cancela")
    assert not engine._is_interrupt_phrase("tá tudo bem")
    assert not engine._is_interrupt_phrase("jarvis, como funciona o chatgpt")

    # Fast Lane consulta o Router V8: local claro pula Whisper; conversa e
    # efeitos destrutivos continuam fora da via rápida.
    assert engine._is_fast_safe_local_command("programa aberto agora")
    assert engine._is_fast_safe_local_command("Que horas são?")
    assert engine._is_fast_safe_local_command("Abre Opera")
    assert engine._is_fast_safe_local_command("Abre Opera e OBS")
    assert not engine._is_fast_safe_local_command("Como funciona o ChatGPT?")
    assert not engine._is_fast_safe_local_command("Funciona o ChatGPT")
    assert engine._is_fast_safe_local_command("Tá tudo bem?")
    assert engine._is_fast_safe_local_command("Como está meu PC?")
    assert engine._is_fast_safe_local_command("Descreve tela 2")
    # Build 9: pesquisa livre não pula a transcrição bilíngue final.
    assert not engine._is_fast_safe_local_command("Pesquisa no Opera placa de vídeo")
    assert engine._is_reversible_browser_search("Pesquisa no Opera placa de vídeo")
    assert not engine._is_reversible_browser_search("Como funciona o ChatGPT?")
    assert engine._is_fast_safe_local_command("pausa")
    assert engine._is_fast_safe_local_command("pular a abertura")
    assert engine._is_fast_safe_local_command("próximo episódio")
    assert engine._is_fast_safe_local_command("abril opera")
    assert engine._is_fast_safe_local_command("móvel opera para outra tela")
    assert engine._is_fast_safe_local_command("para outra tela")
    assert engine._is_fast_safe_local_command("minimmiza")
    assert not engine._is_fast_safe_local_command("Fecha Opera")
    assert not engine._is_fast_safe_local_command("Cria uma pasta chamada Arcanjo")

    # O callback só alimenta o ring; consumidor lê depois.
    ring = _AudioRingStream(320, 16000, seconds=0.10, watchdog=0.5)
    frame = (b"\x01\x00" * 320)
    ring.callback(frame, 320, None, None)
    raw, overflow = ring.read(320)
    assert raw == frame and overflow is False

    # Com blocksize=0 o host pode entregar blocos maiores/variaveis; o ring
    # recompõe exatamente quadros de 20 ms para VAD/Vosk.
    ring_var = _AudioRingStream(320, 16000, seconds=0.20, watchdog=0.5)
    ring_var.callback(frame * 3, 960, None, None)
    assert ring_var.read(320)[0] == frame
    assert ring_var.read(320)[0] == frame
    assert ring_var.read(320)[0] == frame

    # O wake consumer pode saltar backlog velho e voltar ao audio recente;
    # a captura de comando continua usando read() normal.
    ring_latest = _AudioRingStream(320, 16000, seconds=1.0, watchdog=0.5)
    for i in range(35):
        ring_latest.callback((int(i).to_bytes(2, "little") * 320), 320, None, None)
    before_depth = ring_latest.depth
    recent, _ = ring_latest.read_latest(320, max_backlog_chunks=6)
    assert before_depth > 6 and ring_latest.depth <= 5
    assert recent != (b"\x00\x00" * 320)

    # Build 12 R2: captura abre imediatamente após o wake. O feedback visual da
    # esfera substitui o antigo "Sim?", economizando um ciclo completo de TTS.
    if "JARVIS_VOICE_ACK" not in os.environ:
        assert VoiceEngine.VOICE_ACK is False
    if "JARVIS_ENDPOINT_LOCAL" not in os.environ:
        assert VoiceEngine.ENDPOINT_LOCAL <= 0.10
    if "JARVIS_ENDPOINT_NORMAL" not in os.environ:
        assert 0.30 <= VoiceEngine.ENDPOINT_NORMAL <= 0.55
    if "JARVIS_TTS_VOICE_LOCK" not in os.environ:
        assert VoiceEngine.TTS_VOICE_LOCK is True
    if "JARVIS_TTS_ALLOW_LOCAL_FALLBACK" not in os.environ:
        assert VoiceEngine.TTS_ALLOW_LOCAL_FALLBACK is False
    assert engine._looks_like_local_intent_candidate("aprendi rotina de trabalho")
    assert engine._live_phrase_needs_more_time("move opera")
    assert engine._live_phrase_needs_more_time("abre opera")
    assert engine._live_phrase_needs_more_time("como funciona a memoria de um")
    assert not engine._live_phrase_needs_more_time("diz a hora")

    # Sob pressão, descarta antigo em vez de bloquear o callback/driver.
    for _ in range(140):
        ring.callback(frame, 320, None, None)
    assert ring.dropped > 0
    assert ring.depth > 0
    assert ring.discard() > 0
    assert ring.depth == 0

    # Por padrão, Whisper não recebe prompt/hotwords de apps/intenção.
    if "JARVIS_WHISPER_BIAS" not in os.environ:
        assert VoiceEngine.WHISPER_BIAS is False
    return 46


def check_deepgram_auth_cache():
    from deepgram_flux import get_key_state, is_configured, mark_key_invalid, mark_key_valid

    old = os.environ.get("DEEPGRAM_API_KEY")
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis_v8_dg_") as td:
            key_a = "dg_test_key_v8_A"
            key_b = "dg_test_key_v8_B"
            os.environ["DEEPGRAM_API_KEY"] = key_a
            assert is_configured(td)
            mark_key_invalid(td, key_a, "HTTP 401")
            state = get_key_state(td)
            assert state["invalid_auth"] is True
            assert is_configured(td) is False
            raw = (Path(td) / "data" / "deepgram_state.json").read_text(encoding="utf-8")
            assert key_a not in raw
            assert "key_hash" in json.loads(raw)

            # Mudou a chave: libera um novo teste automaticamente.
            os.environ["DEEPGRAM_API_KEY"] = key_b
            assert is_configured(td) is True
            mark_key_valid(td, key_b)
            assert get_key_state(td)["invalid_auth"] is False
    finally:
        if old is None:
            os.environ.pop("DEEPGRAM_API_KEY", None)
        else:
            os.environ["DEEPGRAM_API_KEY"] = old
    return 8


def check_memory_recovery():
    from memory_store import MemoryStore

    with tempfile.TemporaryDirectory(prefix="jarvis_v8_mem_") as td:
        db = Path(td) / "jarvis_memory.db"
        db.write_bytes(b"not-a-sqlite-database\x00broken")
        store = MemoryStore(db_path=str(db))
        try:
            cid = store.create_conversation("V8 selftest")
            assert int(cid) >= 1
            row = store.conn.execute("PRAGMA quick_check").fetchone()
            assert row and str(row[0]).lower() == "ok"
            corrupt_dir = Path(td) / "recovery"
            preserved = list(corrupt_dir.glob("jarvis_memory_corrupt_*"))
            assert preserved, "banco corrompido original nao foi preservado"
        finally:
            store.close()
    return 4


def check_app_resolver_prewarm():
    from universal_app_resolver import UniversalAppResolver

    with tempfile.TemporaryDirectory(prefix="jarvis_v8_apps_") as td:
        resolver = UniversalAppResolver(td, load_global=False)
        resolver.ingest_candidates(
            [
                {"name": "Opera GX", "target": r"C:\Apps\Opera GX\opera.exe", "source": "Teste", "installed": True},
                {"name": "OBS Studio", "target": r"C:\Apps\OBS\obs64.exe", "source": "Teste", "installed": True},
                {"name": "Discord", "target": r"C:\Apps\Discord\Discord.exe", "source": "Teste", "installed": True},
                {"name": "Steam", "target": r"C:\Apps\Steam\steam.exe", "source": "Teste", "installed": True},
                # DisplayIcon não pode ganhar do launcher real do mesmo produto.
                {"name": "Blood Strike", "target": r"C:\Games\BloodStrike.ico", "source": "Registro", "installed": True},
                {"name": "Blood Strike", "target": "steam://rungameid/3199170", "source": "Steam", "installed": True},
                {"name": "Visual Studio", "target": r"C:\Apps\VS\devenv.exe", "source": "Teste", "installed": True},
                {"name": "Android Studio", "target": r"C:\Apps\Android\studio64.exe", "source": "Teste", "installed": True},
            ],
            save=False,
        )
        stats = resolver.prewarm_local_forms()
        assert stats["apps"] >= 7
        assert len(resolver._forms_cache) >= 7

        assert resolver.resolve("operar").selected.record.name == "Opera GX"
        assert resolver.resolve("ó per a").selected.record.name == "Opera GX"
        assert resolver.resolve("o b s").selected.record.name == "OBS Studio"
        assert resolver.resolve("discordia").selected.record.name == "Discord"
        for spoken in ("dix cor de", "discor de", "discordio"):
            result = resolver.resolve(spoken)
            assert result.safe and result.selected and result.selected.record.name == "Discord", (spoken, result)
        for spoken in ("BloodStrike", "Blood Strike", "Bloody Strike", "blod strike"):
            result = resolver.resolve(spoken)
            assert result.safe and result.selected
            assert result.selected.record.target.startswith("steam://"), (spoken, result.selected.record.target)
        assert resolver.resolve("estim").safe and resolver.resolve("estim").selected.record.name == "Steam"
        assert resolver.resolve("Studio").safe is False
    return 16


def main():
    total = 0
    total += check_router_regression()
    total += check_window_primitives()
    total += check_voice_primitives()
    total += check_deepgram_auth_cache()
    total += check_memory_recovery()
    total += check_app_resolver_prewarm()
    print(f"JARVIS V8 SELFTEST: PASS ({total} verificacoes)")


if __name__ == "__main__":
    main()
