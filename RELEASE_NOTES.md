# JARVIS Desktop 1.2.4 — Interface refinada e atualização mais rápida

- Mantém e consolida as melhorias de interface/UX da linha 1.2.3: prioridade para UI e chat, inicialização escalonada, voz/Whisper sob demanda, watchdog de responsividade, fila gráfica limitada por ciclo e diagnóstico automático de congelamento.
- Preserva o Chat Core e a interface Blue Core, com separação mais segura entre chat, voz, overlay e módulos em segundo plano.
- Inclui as correções atuais em `main.py` e `requirements.txt`, por isso esta versão é publicada como instalador completo e não como Hot Update.
- Otimiza o workflow `Publish JARVIS Hot Update (fast)` para as próximas atualizações normais, reduzindo testes redundantes e trabalho de compressão.
- Mantém no caminho rápido o `jarvis_hot_update_selftest.py` e a compilação individual das fontes que realmente entram no pacote.
- Adiciona gatilho por `.github/hot-update-request.json` para solicitar Hot Updates sem abrir manualmente a tela do GitHub Actions.
- Adiciona também gatilho por `.github/build-request.json`, permitindo disparar builds completos diretamente pelo fluxo integrado.
- Reduz o timeout do Hot Update, impede execuções concorrentes e evita recompressão desnecessária do artifact.
- Adiciona `.gitignore` para impedir novos caches Python, logs, `dist/`, `release/`, ambientes virtuais e outras saídas locais no repositório.
- Mantém intacta a proteção do baseline: mudanças em bootstrap, dependências, toolchain, modelos Vosk/ONNX e outros arquivos críticos continuam exigindo instalador completo.

Versão: 1.2.4
Canal: stable
