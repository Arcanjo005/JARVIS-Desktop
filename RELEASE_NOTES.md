# JARVIS Desktop 1.2.4 — Hot Update mais rápido

- Otimiza o workflow `Publish JARVIS Hot Update (fast)` para reduzir o tempo de publicação de atualizações normais.
- Remove do caminho rápido as três suítes de regressão completas e o `compileall` global; esses gates continuam obrigatórios no build Windows completo.
- Mantém no Hot Update o `jarvis_hot_update_selftest.py`, dedicado à validação do runtime de atualização, rollback, integridade e precedência de código.
- O builder continua compilando individualmente cada fonte Python que realmente entra no pacote antes de publicar.
- Adiciona gatilho por `.github/hot-update-request.json`, permitindo solicitar uma nova versão sem abrir manualmente a tela de Actions.
- Reduz o timeout do workflow rápido e impede execuções concorrentes do mesmo Hot Update.
- Evita recompressão desnecessária do artifact e reduz o nível de compressão interno do ZIP para acelerar a geração.
- Adiciona `.gitignore` para evitar novos caches Python, logs, `dist/`, `release/`, ambientes virtuais e outras saídas locais no repositório.
- Mantém intacta a proteção do baseline: mudanças em `main.py`, bootstrap, dependências, toolchain, modelos Vosk/ONNX e outros arquivos críticos continuam exigindo build completo do instalador.
