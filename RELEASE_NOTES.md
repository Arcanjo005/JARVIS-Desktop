# JARVIS Desktop 1.3.5 — Interface responsiva e esfera 3D

## Interface

- Histórico de conversas funcional no lugar da navegação decorativa. Nova conversa, busca e seleção usam a persistência existente. Em janelas estreitas, o histórico fica recolhido e pode ser aberto pelo botão superior.
- Botão **+** restaurado no campo de mensagem, com controles de voz, modo, autonomia, presença, legendas, API, diagnóstico e ferramentas existentes.
- Ajuda **O que posso pedir?**, também acessível por F1. Os exemplos preenchem o chat sem executar ações automaticamente.
- Um único botão **ATUALIZAR**, no canto superior direito. O pulso só aparece quando o atualizador detecta uma versão disponível; para durante download e aplicação.
- Layout adaptável ao tamanho da janela, à área útil do monitor e à escala. Corrigidos posição inicial fora da tela e corte de linhas em escalas de 150% e 200%.
- Mensagens completas, selecionáveis, com quebra de linha e altura calculadas a partir das métricas reais do texto. A legenda amarela pode resumir visualmente uma resposta longa sem cortar o histórico.

## Esfera e desempenho

A esfera central não usa mais uma fotografia com brilho animado. Ela possui geometria XYZ, rotação contínua, profundidade, superfície sombreada, pontos e órbitas. A renderização por software usa supersampling e redução LANCZOS.

O renderizador fica em um processo separado, com filas limitadas, controle de ritmo e pausa quando a área não está visível. O encerramento do processo é controlado. Em espaço vertical extremamente reduzido, elementos decorativos cedem espaço ao chat e aos controles.

O fundo arquitetônico desfocado é separado do texto e dos controles. A interface usa dimensões físicas e fontes nativas em telas de alta densidade; não é uma promessa de renderização 4K a 60 quadros por segundo nem de aceleração GPU.

## Confiabilidade

- Corrigido aviso antigo de atualização que podia substituir o progresso de download.
- Corrigidas fala duplicada e resposta falada atrasada atravessando uma troca de conversa ou turno.
- Corrigido corte da última linha das mensagens em DPI alto.
- Eliminada a renderização pesada em uma thread que compartilha o interpretador Tk com a interface.
- Mantidos o controlador principal, o VoiceEngine, o patch de confiabilidade de áudio, os modelos de wake e as proteções do atualizador.
- Entrada de interface estável; o workflow não copia uma implementação sobre outra. O preparador canônico continua responsável pela ativação do entry point.

## Validação

Antes da solicitação deste instalador, o Windows CI aprovou 19 verificações de preflight, 367 verificações dos quatro selftests legados, 34 testes comportamentais de interface e os testes adicionais de monitor, DPI, texto e renderizador empacotado com PyInstaller. A build completa repete os gates de preflight e mantém os smoke tests do executável final.

Os testes de interface usam Tk e SQLite reais, com respostas e voz determinísticas. Microfone físico, serviços externos, transição entre monitores físicos e desempenho específico no i5-6500 ainda dependem de validação no equipamento do usuário.

Distribuição: instalador completo do Windows, não um pacote de hot update.
Versão: **1.3.5**. Canal: **stable**.
