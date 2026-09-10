# Publicar JARVIS Desktop no GitHub Releases

## Primeira base Hot Runtime: 1.1.0

A versão 1.1.0 precisa de **um último build completo**, porque adiciona dependências/runtime que a 1.0.1 não possui (bandeja `pystray`, bootstrap de Hot Runtime e validações do executável congelado).

1. Envie os arquivos desta atualização para a raiz do repositório, preservando as pastas.
2. Abra **Actions > Build FULL JARVIS Installer (runtime/dependencies)**.
3. Use a versão `1.1.0`.
4. Aguarde o job ficar verde.
5. Baixe `JARVIS_Setup_1.1.0.exe` em Releases e instale por cima da versão atual.

O build completo é propositalmente rígido: antes do Inno Setup ele executa `JARVIS.exe --runtime-selftest` e valida módulos nativos de voz, Vosk, WebRTC VAD, bandeja Win32, overlay Qt e os assets do wake word. Também cria um Hot Runtime sintético e prova no próprio EXE que o código em `%LOCALAPPDATA%\JARVIS\runtime` consegue sobrepor o bundle.

## Próximas versões normais: sem PyInstaller

Para correções de interface, conversa, voz, comandos e lógica Python:

1. Atualize os fontes no repositório.
2. Abra **Actions > Publish JARVIS Hot Update (fast)**.
3. Informe uma versão nova, por exemplo `1.1.1`.
4. Mantenha `minimum_bootstrap` em `1.1.0` enquanto a base não mudar.
5. O GitHub roda regressões rápidas e publica `JARVIS_HotUpdate_1.1.1.zip`, `.json` e `.sha256`.
6. O JARVIS instalado detecta a Release e mostra o botão **ATUALIZAR**.

Esse fluxo não recompila Python, Qt, Whisper, Vosk ou o EXE. O pacote típico fica na ordem de centenas de KiB.

## Quando o workflow rápido deve recusar

`build/hot_runtime_baseline.json` contém hashes de arquivos que exigem build completo. Se qualquer um deles mudar, `tools/build_hot_update.py` para antes de publicar e informa quais arquivos exigem nova base. Isso é intencional.

## Versões são imutáveis

Nunca substitua o conteúdo de uma versão já publicada. Se algo precisar de correção, publique outro número (`1.1.2`, `1.1.3`...). O runtime também rejeita localmente o mesmo número de versão com conteúdo diferente.
