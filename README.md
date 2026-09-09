# JARVIS Desktop 1.0

Esta é a linha de distribuição Windows do JARVIS. O usuário final instala **`JARVIS_Setup_X.Y.Z.exe`** e não precisa ter Python, pip ou Git.

## Instalação e primeira configuração

- destino padrão: **`C:\JARVIS`**;
- cria atalhos no Menu Iniciar e, opcionalmente, na Área de Trabalho/inicialização do Windows;
- na primeira abertura, o JARVIS pede a **API key do Gemini**;
- a chave é protegida com **Windows DPAPI** no perfil daquele usuário, fora do pacote do programa;
- instalações antigas com `GEMINI_API_KEY` no `.env` são migradas automaticamente sem apagar outras configurações.

O botão **API** no topo permite trocar a chave depois.

## Atualizações

O Desktop consulta a **última GitHub Release** configurada no build. Quando encontra uma versão maior, mostra **ATUALIZAR X.Y.Z**. O instalador é baixado, o SHA-256 é validado e só então a atualização silenciosa é executada. Memória, preferências, perfis e arquivos locais desconhecidos pelo instalador não são apagados.

O repositório inclui `.github/workflows/build-release.yml`. Em **Actions > Build and Publish JARVIS Desktop**, informe uma versão `X.Y.Z`; o próprio GitHub compila em Windows, cria o instalador e publica a Release. Veja `GITHUB_RELEASES_SETUP.md`.

## Código-fonte / build

O código desta pasta é para desenvolvimento e para o GitHub Actions. O instalador distribuído ao usuário contém o runtime necessário. O arquivo grande `speaker_guard_campplus.onnx` pode ser armazenado no repositório em duas partes dentro de `build/asset_parts`; `tools/restore_large_assets.py` reconstrói e valida o SHA-256 antes do build.

## Voz

Wake principal:

- `Jarvis`
- `Oi Jarvis`
- `Ei Jarvis`

Variações fonéticas observadas, como `Jarbas`, também são normalizadas para JARVIS. A voz padrão é **pt-BR-AntonioNeural**, travada para não trocar silenciosamente por outra voz. A prosódia padrão usa `+10%` de velocidade (`+0 Hz` de pitch). Pode ser ajustada em runtime com `fala mais rápido`, `fala normal` e `fala mais devagar`.

## Reconhecimento PT-BR + English

A Build 16 mantém a separação entre:

- **transcrição literal** — o texto que o STT realmente ouviu e que aparece na interface;
- **interpretação operacional** — normalizações internas usadas apenas para executar ações com segurança.

Exemplo: se o áudio for transcrito como `Abrei o ópero`, a interface continua mostrando exatamente isso; o executor pode interpretar internamente como `abre Opera`. Os logs usam `STT FINAL: literal=... | interpretado=...` quando há diferença.

Para a melhor combinação de português + inglês, o STT principal é **Deepgram Flux Multilingual** (`flux-general-multi`) com hints simultâneos `pt-BR` e `en-US`, keyterms do catálogo de aplicativos e detecção de fim de turno do próprio modelo. Execute **`CONFIGURAR_DEEPGRAM.bat`** se o diagnóstico disser que Deepgram não está configurado.

Sem Deepgram/rede, o fallback continua local com Vosk + faster-whisper, limitado a uma política PT/EN para impedir detecções curtas absurdas como `ru`, `pl` e `it`. O fallback prioriza resposta rápida; para precisão máxima offline, a GPU/Vulkan pode ser configurada separadamente.

Perguntas sociais básicas como `Tudo bom cara` são respondidas localmente e não precisam esperar a API Gemini. Para perguntas que realmente precisam do modelo, a Build 13 limita o timeout/retry do cliente para não ficar dezenas de segundos parado em backoff de rede.

## Contexto e mídia V2

A linha Build 13 adicionou um contexto curto com validade/confiança para app, monitor, site, mídia e tópico. O Media Context unifica Spotify/VLC/streaming, e o JARVIS evita dizer que uma ação foi confirmada quando só enviou o comando. Regras locais `quando X -> faça Y` podem automatizar apenas ações seguras, e a memória comportamental V2 aprende metadados de sequências/padrões para sugerir rotinas sem executá-las sozinha.

O modo distante foi deixado para uma etapa futura.

## Organização

- `main.py` — entrada oficial
- `gui.py` — interface oficial
- `voice_engine.py` — wake/STT/TTS oficial
- `jarvis_router.py` — roteamento local oficial
- `core.py` — conversa/IA
- `actions.py` — ações locais
- `memory_store.py` — memória principal em `data/jarvis_memory.db`
- `jarvis_identity.py` — nome/configuração canônica
- `jarvis_version.py` — versão oficial
- `plugins/` — plugins
- `data/` — memória e estado local

Não há uma segunda árvore duplicada do projeto nesta distribuição.

## Testes

Execute **`TESTAR_JARVIS.bat`** para a bateria rápida. Para a bateria completa, execute **`TESTAR_JARVIS_COMPLETO.bat`**. O manual operacional está em **`MANUAL_DE_USO_E_TESTES.md`** e o changelog em **`ATUALIZACAO_BUILD13.md`**.

## Objetivo do projeto

A Build 16 mantém a fundação de wake/voz/latência e integra melhor as camadas já existentes: streaming universal, agente multi-etapas, pesquisa atual com Google Search, conversa contínua mais conservadora, memória comportamental local, proatividade de saúde do PC e orb compacto. Ações sensíveis/irreversíveis continuam protegidas por confirmação e pelo Safety Runtime.



## Build 16 — interface conversacional e robustez de turnos

- Composer multilinha: **Enter envia** e **Shift+Enter cria nova linha**; Enter na busca de conversas não dispara mais uma mensagem acidental.
- Respostas, comandos locais, plugins e atualizações de UI recebem um **token de turno**; callbacks atrasados de uma solicitação antiga são descartados ao iniciar outra.
- Trocar/criar/apagar a conversa ativa invalida eventos pendentes da conversa anterior, evitando resposta fantasma na conversa errada.
- Streaming ganhou descarte explícito de bolha órfã e limpeza de chunks após interrupção/watchdog.
- Histórico de até 120 mensagens é desenhado em lotes de 10, mantendo a janela responsiva durante a restauração.
- TTS tem uma única rota por resposta; texto novo interrompe áudio anterior para não haver duas falas sobrepostas.
- Cache de respostas deixou de reutilizar follow-ups dependentes de contexto como “isso”, “essa parte” e “explica isso”.
- Confirmações curtas depois de uma pergunta do JARVIS continuam pelo histórico em vez de receber uma resposta genérica local.
- Erros internos ficam no diagnóstico/log; o chat recebe uma mensagem curta e compreensível.
- O instalador continua sem backup interno, preserva estado do usuário e remove caches/logs/resíduos técnicos antigos.

## Build 15 — comunicação, boot e scroll

- Comunicação/STT com reparo contextual conservador, melhor continuidade de frases curtas e consenso com o vocabulário real de aplicativos instalados.
- Primeiro frame antecipado: voz, IA, agente, overlay, telemetria, catálogo de apps e integrações avançadas entram depois, em paralelo.
- Dependências pesadas de automação/HTTP/brilho/COM/WMI são carregadas apenas no primeiro uso.
- Histórico visual é restaurado depois que a janela já abriu, evitando a sensação de travamento em conversas longas.
- Scroll do chat com limite por gesto, acumulação de touchpad, bloqueio de evento duplicado e auto-scroll agrupado sem fila infinita.
- Recalibração manual do microfone passa a usar o stream já aberto, sem reiniciar o dispositivo.

## Build 14 — distribuição enxuta

- backups automáticos de código e banco diário removidos;
- caches, screenshots técnicos e histórico não fazem parte do pacote de atualização;
- backend Whisper Vulkan e modelo `ggml-small-q5_1.bin` não são mais embarcados; continuam disponíveis sob demanda via `ATIVAR_GPU_STT_AMD.bat`;
- o instalador padrão atualiza diretamente `C:\\JARVIS` e preserva `.env`, memória, preferências e perfil de voz.
