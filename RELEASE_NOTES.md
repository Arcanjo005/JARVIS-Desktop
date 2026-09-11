# JARVIS Desktop 1.2.8 — Runtime unificado, esfera moderna e base para updates rápidos

- Remove o conflito que fazia o bootstrap legado 1.2.3 substituir a interface moderna pela tela antiga mesmo nas versões 1.2.6/1.2.7.
- Mantém os patches funcionais úteis do bootstrap antigo, mas bloqueia explicitamente o layout legado e o detector antigo de microfone.
- A interface efetiva passa a usar `gui_conversation_shell`: lateral dedicada a conversas, histórico, busca, nova conversa e botão `COPIAR CONVERSA`.
- Nova conversa passa a iniciar o viewport no topo, sem herdar uma posição de rolagem antiga.
- Corrige a esfera do modo conversa: o modo de conversa não força mais `OUVINDO` permanentemente. Em repouso ela fica compacta em `OCIOSO`; ativa quando o microfone realmente captura ou quando o JARVIS entende, pensa, executa ou fala.
- Preserva a esfera Qt/PySide6 moderna com estilos Cristal, Núcleo, Anéis, Pulso e Minimal e mantém fallback apenas quando o processo Qt realmente não puder iniciar.
- O diagnóstico agora detalha backend efetivo da esfera, processo Qt, estilo, estado enviado, estado visual, modo compacto e últimos logs do overlay quando houver fallback.
- O diagnóstico de áudio passa a mostrar a entrada PortAudio efetiva, Host API, taxa nativa/reamostragem, VAD, STT, overflows e último erro do VoiceEngine.
- Mantém o detector moderno de microfone do `voice_engine.py`, com teste real de `RawInputStream`, preferência por APIs estáveis e fallback 44,1/48 kHz com reamostragem para 16 kHz.
- Corrige o bootstrap de Hot Runtime para descobrir a versão do instalador sem importar `jarvis_version` antes da ativação. Isso impede o runtime embutido antigo de contaminar a sessão antes de uma atualização rápida entrar em `sys.path`.
- Fixa a base do atualizador em 1.2.8 para permitir que as próximas correções normais de interface/esfera/áudio sejam distribuídas por Hot Update, evitando PyInstaller/Inno Setup sempre que os arquivos protegidos não mudarem.

Versão: 1.2.8
Canal: stable
