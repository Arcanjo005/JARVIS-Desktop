# JARVIS Desktop 1.2.12 — Esfera única e legenda de cinema

- Mantém somente uma esfera 3D pequena em todos os estados; o modo conversa não cria uma esfera maior concorrente.
- O modo conversa amplia apenas a área transparente necessária para a legenda, mantendo a esfera no mesmo tamanho visual do modo ocioso.
- Remove competição entre o overlay Qt e o fallback Tk: quando o Qt está ativo, qualquer janela Tk antiga é encerrada explicitamente.
- A esfera continua mudando apenas cor, brilho e energia conforme o estado real do VoiceEngine: ocioso, ouvindo, entendendo/pensando, executando, falando e recuperação.
- Legenda estilo filme em alta nitidez: texto amarelo com contorno preto forte, renderizado por vetores Qt para boa leitura sobre qualquer fundo.
- Preserva por alguns segundos a última fala do usuário durante ENTENDENDO/PENSANDO para mostrar o que o JARVIS entendeu antes da resposta.
- Mantém o renderer 3D em processo separado para não competir com a mainloop Tk do chat.
- Mantém o fallback Tk de emergência limitado e sensível à fila da UI, evitando regressão do travamento progressivo observado na 1.2.10.
- Mantém intacto o VoiceEngine e a recuperação de áudio rápida já estabilizados na 1.2.11.

Versão: 1.2.12
Canal: stable
