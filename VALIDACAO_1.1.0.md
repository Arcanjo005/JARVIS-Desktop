# Validação JARVIS Desktop 1.1.0

Validações realizadas no snapshot entregue:

- `python -m compileall -q .`: PASS
- `jarvis_hot_update_selftest.py`: PASS — 25 verificações
- `jarvis_desktop_selftest.py`: PASS — 73 verificações
- `jarvis_build16_selftest.py`: PASS — 61 verificações
- `jarvis_v8_selftest.py`: PASS — 201 verificações
- Smoke de reamostragem: 16 kHz, 44,1 kHz e 48 kHz -> 16 kHz: PASS
- Baseline Hot Runtime: 24 arquivos bloqueados, hashes conferidos: PASS
- Builder Hot Update 1.1.1 de prova: 49 arquivos, ~432 KiB: PASS

O ambiente desta análise é Linux, portanto o PyInstaller/Inno Setup Windows final
não foi executado localmente. O workflow completo foi reforçado para executar no
runner Windows um `--runtime-selftest` dentro do `JARVIS.exe` final e uma prova de
precedência do Hot Runtime antes de permitir a criação/publicação do instalador.
