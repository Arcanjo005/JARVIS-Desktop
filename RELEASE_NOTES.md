# JARVIS Desktop 1.2.5 — Histórico e interface correta após atualizar

- Corrige o caso em que um Hot Runtime antigo salvo no AppData podia continuar sobrescrevendo a interface de um instalador mais novo.
- Ao instalar uma versão completa mais recente, runtimes antigos agora são desativados automaticamente e o código da instalação nova passa a prevalecer.
- Isso restaura a interface atual da lateral, incluindo a lista de conversas já salva no banco; o histórico não é apagado ao criar um novo chat.
- Mantém na lateral apenas a navegação principal da interface atual, deixando ações complementares concentradas no menu de três pontos para evitar duplicação visual.
- Garante que a versão atual do controle de rolagem da conversa seja realmente carregada, evitando que uma GUI antiga continue causando comportamento de scroll incorreto após a atualização.
- O diagnóstico passa a informar `Versão instalada`, `Versão efetiva` e se há `Hot Runtime` ativo, incluindo sua pasta quando aplicável.
- `Voz` ainda não inicializada deixa de aparecer como falha quando estiver corretamente no modo sob demanda/lazy.
- Entrada e saída de áudio sem nome identificável passam a ser mostradas como estado indeterminado, em vez de um check verde enganoso.
- O núcleo protegido do Hot Runtime foi separado e também bloqueado para pacotes source-only, preservando a segurança do bootstrap nas próximas atualizações rápidas.
- Mantém as otimizações de responsividade, inicialização escalonada, watchdog da UI, Chat Core e demais melhorias da linha 1.2.x.

Versão: 1.2.5
Canal: stable
