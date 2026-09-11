# JARVIS Desktop 1.2.11 — Rebranding da esfera 3D e recuperação de áudio

- Substitui os renderers concorrentes por uma única identidade visual 3D suave para a esfera de voz.
- Remove o visual de reator/círculos concêntricos e elimina a aparência pixelada das versões anteriores.
- Em modo ocioso a esfera fica pequena e discreta; no modo conversa cresce apenas um pouco.
- O modo conversa não força mais o estado `OUVINDO`: o VoiceEngine continua sendo a fonte de verdade dos estados visuais.
- Cores por estado real: azul ocioso, verde/ciano ouvindo, violeta entendendo/pensando, laranja executando, azul-claro falando e vermelho somente durante erro real.
- A esfera mantém animação contínua com volume, iluminação especular móvel, energia interna e partícula orbital para reforçar a sensação de rotação 3D.
- Adiciona legenda compacta sob a esfera no modo conversa, diferenciando `Voce:` e `JARVIS:` sem painel grande de logs.
- Evita que erros de áudio antigos permaneçam presos na interface após a entrada voltar a funcionar.
- Reduz a recuperação de microfone/dispositivo de 30/60/120 segundos para backoff rápido de 2/4/8/15/30 segundos no máximo.
- Mantém seleção real de microfone por `RawInputStream`, preferência por WASAPI/MME/DirectSound, fallback 44,1/48 kHz e reamostragem interna para 16 kHz.
- Mantém VAD, wake word, STT, TTS, telemetria e diagnóstico do VoiceEngine moderno.

Versão: 1.2.11
Canal: stable
