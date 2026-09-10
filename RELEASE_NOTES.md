# JARVIS Desktop 1.1.0 — Stable Hot Runtime

- Corrige a bandeja do Windows: `pystray` passa a fazer parte do runtime e o backend Win32 é validado antes de publicar o instalador.
- O botão X só oculta o JARVIS quando a bandeja realmente está disponível; caso contrário, encerra normalmente em vez de deixar processo invisível no Gerenciador de Tarefas.
- A bandeja ganhou supervisor próprio: o loop Win32 só marca `tray_ready` depois que o ícone ficou visível e tenta se recuperar se Explorer/backend encerrar inesperadamente.
- O JARVIS deixa de forçar "Iniciar com Windows" em runtime; a escolha feita no instalador/menu da bandeja é preservada.
- Voz/wake word ganhou supervisor de recuperação: falhas de microfone/PortAudio reabrem o stream automaticamente com backoff limitado.
- Seleção de microfone não depende mais exclusivamente do dispositivo padrão nem de 16 kHz nativos. Se o driver só aceitar 44,1/48 kHz, o JARVIS captura na taxa real do dispositivo e reamostra internamente para 16 kHz antes de Vosk/WebRTC VAD.
- A GUI só anuncia voz pronta depois que Vosk + microfone realmente inicializam; captura manual usa o mesmo `VoiceEngine`, sem abrir um segundo reconhecedor/stream legado.
- `send2trash` e `pystray` agora fazem parte explícita das dependências do instalador.
- O build completo usa PyInstaller/tool hooks fixados em versões validadas e executa smoke test dentro do `JARVIS.exe` congelado antes do Inno Setup, verificando sounddevice, Vosk, WebRTC VAD, pystray Win32, PySide6 e assets do wake word.
- O build também prova no EXE final que código em `%LOCALAPPDATA%\JARVIS\runtime` realmente tem precedência sobre a cópia congelada; uma base incapaz de receber hot updates não pode ser publicada.
- Reinício após hot update usa um novo ambiente do bootloader PyInstaller; instalação externa restaura a busca normal de DLLs do Windows antes de abrir o Setup.
- Adiciona Hot Runtime seguro em `%LOCALAPPDATA%\JARVIS\runtime`: atualizações normais passam a ser ZIPs pequenos, com SHA-256, validação de manifesto, ativação atômica e rollback após duas falhas de boot.
- Uma versão de hot update é imutável: o mesmo número nunca pode substituir silenciosamente bytes diferentes já instalados.
- Novo workflow `Publish JARVIS Hot Update (fast)` compila/testa apenas fontes e publica mudanças normais sem PyInstaller nem build Windows.
- Alterações em dependências, `main.py`, bootstrap, toolchain bloqueada ou modelos continuam exigindo um novo instalador base completo.
