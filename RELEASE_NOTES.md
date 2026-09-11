# JARVIS Desktop 1.2.7 — Interface de conversas realmente ativada

- Corrige a falha da 1.2.6 em que o instalador era publicado com a nova camada de interface no repositório, mas o entrypoint continuava importando `gui.JarvisGUI`.
- O build agora troca e valida explicitamente o entrypoint para `gui_conversation_shell.JarvisGUI` antes do PyInstaller.
- A lateral esquerda fica dedicada às conversas: nova conversa, busca e histórico salvos.
- Remove da lateral telemetria e atalhos duplicados que já pertencem ao menu de três pontos.
- Mantém Diagnóstico, Logs, Memórias, Contexto, Rotinas, Esfera e demais controles no menu `⋮`.
- O botão superior direito `COPIAR CONVERSA` copia a conversa ativa inteira diretamente do banco, pronta para colar no ChatGPT como relatório.
- A exportação inclui versão, build, título, ID, horário, remetentes e conteúdo de cada mensagem.
- O workflow falha antes de compilar se o novo shell de conversas não estiver realmente ligado ao entrypoint, evitando publicar novamente uma versão com interface antiga.

Versão: 1.2.7
Canal: stable
