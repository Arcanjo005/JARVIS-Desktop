# JARVIS Desktop 1.2.9 — Esfera 3D giratória restaurada

- Remove o visual antigo `core`/reator com círculos concêntricos que voltou a aparecer indevidamente.
- Restaura como padrão a esfera 3D giratória do renderer principal do JARVIS, com volume, reflexos, partículas orbitais e animação contínua.
- Configurações antigas salvas como `core` são migradas automaticamente para `crystal` para que a esfera velha não reapareça após atualizar.
- Retira `core` das opções visuais expostas ao usuário.
- Impede o overlay Qt antigo de assumir prioridade sobre a esfera 3D aprovada.
- Mantém os estados visuais sincronizados com o VoiceEngine: `OCIOSO`, `OUVINDO`, `ENTENDENDO`, `PENSANDO`, `EXECUTANDO` e `FALANDO`.
- Em modo ocioso a esfera permanece em repouso; não fica presa em `OUVINDO` só porque o modo conversa está ativo.
- Mantém as correções da 1.2.8 para interface de conversas, áudio moderno, Hot Runtime e diagnóstico.

Versão: 1.2.9
Canal: stable
