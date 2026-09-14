# JARVIS Desktop 1.3.5 — Interface responsiva e esfera 3D

## Interface

- Histórico funcional no lugar da navegação decorativa: nova conversa, busca e seleção usam a persistência existente. Em janelas estreitas, o histórico fica recolhido e pode ser aberto pelo botão superior.
- Botão **+** restaurado no campo de mensagem, com controles de voz, modo, autonomia, presença, legendas, API, diagnóstico e ferramentas existentes.
- Ajuda **O que posso pedir?**, também acessível por F1. Os exemplos preenchem o chat sem executar ações automaticamente.
- Um único botão **ATUALIZAR**, no canto superior direito. O pulso só aparece quando o atualizador detecta uma versão disponível; para durante download e aplicação.
- Layout adaptável ao tamanho da janela, à área útil do monitor e à escala. Corrigidos posição inicial fora da tela, transições rápidas entre escalas e corte de linhas em DPI alto.
- Mensagens completas, selecionáveis, com quebra de linha e altura calculadas pelas métricas reais do texto. A legenda amarela pode resumir visualmente uma resposta longa sem cortar o histórico.

## Esfera e desempenho

A esfera central não usa uma fotografia com brilho animado. Possui geometria XYZ, rotação contínua, profundidade, superfície sombreada, pontos e órbitas. A renderização por software usa supersampling e redução LANCZOS.

O renderizador fica em um processo separado, com filas limitadas, controle de ritmo e pausa quando não está visível. O encerramento é controlado. Em espaço vertical extremamente reduzido, elementos decorativos cedem espaço ao chat e aos controles.

O fundo arquitetônico desfocado é separado do texto e dos controles. A interface usa dimensões físicas e fontes nativas em telas de alta densidade. Não é uma promessa de 4K a 60 quadros por segundo nem de aceleração GPU.

## Confiabilidade

- Corrigido aviso antigo de atualização que podia substituir o progresso do download.
- Corrigidas fala duplicada e resposta falada atrasada atravessando uma troca de conversa ou turno.
- Corrigida interrupção de voz por texto que podia ignorar a opção **JARVIS fala** desativada ou duplicar a fala de uma resposta em streaming.
- Corrigido corte da última linha das mensagens em DPI alto.
- Removida a renderização pesada em uma thread que compartilhava o interpretador Tk com a interface.
- Mantidos o controlador principal, o VoiceEngine, o patch de confiabilidade de áudio, os modelos de wake e as proteções do atualizador.
- Entrada de interface estável: o workflow não copia uma implementação sobre outra. O preparador canônico continua responsável pela ativação do entry point.

## Validação

Antes desta solicitação de instalador, o Windows CI aprovou **20 verificações de preflight**, **367 verificações dos quatro selftests legados**, **36 testes comportamentais de interface** e os testes adicionais de monitor, DPI, texto e renderizador empacotado com PyInstaller.

Código validado: `23a4a659c42d4181051f0e401dd9071a82e09017`.
Execução de qualidade: `34872842017`.
Os relatórios JSON, capturas e fontes correspondentes foram conferidos. A build completa repete os gates de preflight e mantém os smoke tests do executável final.

Os testes de interface usam Tk e SQLite reais, com respostas e voz determinísticas. Microfone físico, serviços externos, transição entre monitores físicos e desempenho específico no i5-6500 ainda dependem de validação no equipamento do usuário.

Distribuição: instalador completo do Windows, não um pacote de hot update.
Versão: **1.3.5**. Canal: **stable**.
