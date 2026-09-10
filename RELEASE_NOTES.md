# JARVIS Desktop 1.0.1

- Corrige abertura recursiva de múltiplas janelas no executável empacotado.
- Overlay Qt agora usa um modo filho explícito do JARVIS.exe em vez de relançar a interface principal.
- Adiciona trava de instância única para impedir duas interfaces principais ao mesmo tempo.
- Instalação manual abre a configuração da API Gemini antes da primeira inicialização.
- A chave continua protegida por Windows DPAPI e preservada em atualizações automáticas.
- Diálogo da API é trazido para frente para não ficar escondido atrás do instalador.
- Mantém atualização via GitHub Releases e verificação SHA-256.
