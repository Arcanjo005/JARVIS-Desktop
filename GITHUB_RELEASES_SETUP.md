# JARVIS Desktop - GitHub Releases sem Git/Python no PC do usuário

## Primeira publicação

1. Crie no GitHub um repositório público, por exemplo `JARVIS-Desktop`.
2. Extraia o pacote **GitHub Ready** e envie o conteúdo da pasta para a raiz do repositório. A pasta `.github` também precisa ser enviada. O pacote foi reduzido para menos de 100 arquivos e nenhum arquivo passa de 25 MiB, justamente para caber no upload pelo navegador.
3. Abra **Actions** > **Build and Publish JARVIS Desktop**.
4. Clique em **Run workflow**.
5. Informe a versão, por exemplo `1.0.0`, e execute.
6. O GitHub monta o Windows EXE, cria `JARVIS_Setup_1.0.0.exe`, calcula SHA-256 e publica a Release.

O nome do seu repositório é inserido automaticamente no JARVIS durante o build. Não é necessário editar `update_config.json` manualmente. Publique as versões como releases normais (não prerelease), pois o botão automático acompanha a release estável mais recente.

## Próxima versão

Depois que o código novo estiver no repositório:

1. Abra **Actions** > **Build and Publish JARVIS Desktop**.
2. Use um número maior, por exemplo `1.0.1`.
3. Execute o workflow.

Quem já tiver o JARVIS receberá o botão **ATUALIZAR 1.0.1**. O aplicativo baixa o instalador da nova Release, valida o SHA-256, executa a atualização silenciosa e reinicia.

## Chave Gemini

A chave é de cada usuário. Ela não deve ser adicionada ao GitHub. Na primeira abertura, o JARVIS pede a chave e a protege com Windows DPAPI no perfil daquele usuário. Também existe o atalho **Configurar API Gemini** no Menu Iniciar e o botão **API** dentro do aplicativo.

## Repositório público

O auto-update sem token foi desenhado para repositório público. Um repositório privado exigiria autenticação no computador de cada usuário e não é recomendado para esta forma simples de distribuição.
