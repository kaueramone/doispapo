# Dois Papo — contexto para sessões de IA

Plataforma de comunicação self-hosted: texto, voz e compartilhamento de tela.
Instância pública em `chat.doispapo.com`, landing em `doispapo.com`.

> **Este arquivo é público.** Dados de infraestrutura (IP, versões exatas,
> credenciais, caminhos de backup, postura de firewall) ficam **apenas** no
> `CLAUDE.local.md` da VPS, fora do git. Não traga nada disso para cá.

---

## Estrutura

```
doispapo/
├── cliente/                fonte do cliente web: patches + build
├── docs/fila.md            o que está combinado para fazer, e o que já foi apurado
├── docs/desempenho-voz.md  medição de qualidade e custo das chamadas
├── deploy/compose.yml      stack de containers
├── site/                   landing page (HTML estático)
├── branding/
│   ├── rebrand.py          aplica a marca sobre o build do cliente web
│   └── gerar_pix.py        gera payload BR Code + QR do PIX
├── assets/logos/           logos e cores da marca
└── assets/pix/             QR e payload PIX
```

## Marca

- Azul `#2E8BEB` · Roxo `#8C41D9` (gradiente horizontal)
- Fundo escuro `#101823`
- Logos em `assets/logos/` — variantes colorida, preta e branca
- Assinatura: `desenvolvido por kaueramone.dev`

## Regras de produto

| Regra | Valor |
|---|---|
| Cadastro | somente por convite |
| Comunidades que pode participar | ilimitado |
| Comunidades próprias por conta | 1 |
| Amigos por conta | 5 (fase inicial) |
| Resolução de vídeo/tela | 1920×1080 |

Configurado em `Revolt.toml` (gerado na VPS, fora do git):

```toml
[api.registration]
invite_only = true

[features.limits.default]
servers = 1
outgoing_friend_requests = 5
video_resolution = [1920, 1080]
```

## Serviços próprios

Em `deploy/`, cada um com seu Dockerfile. Nenhum publica porta — só a
rede interna, atrás do Caddy.

| Serviço | Porta | Papel |
|---|---|---|
| `convites` | 8600 | cota de convites, fila de espera, sons por servidor |
| `painel` | 8700 | painel administrativo |
| `emoji` | 8601 | espelho de emoji com cache preguiçoso em disco |

O `compose.override.yml` e o `Caddyfile` que os ligam moram na VPS e não
são versionados (contêm caminhos e configuração da instância).

Testes rodam dentro do container, contra o serviço de verdade:

```bash
docker compose cp deploy/convites/teste_som.py convites:/teste_som.py
docker compose exec -T convites python3 /teste_som.py

docker compose cp deploy/emoji/teste_emoji.py emoji:/teste_emoji.py
docker compose exec -T emoji python3 /teste_emoji.py
```

`deploy/verificar_servicos.py` procura variável usada num ramo que só é
atribuída em outro — os handlers são uma sequência de ramos por rota, e
esse defeito passa em qualquer linter de escopo porque o nome existe na
função. Já derrubou o envio de som com 502.

## Cliente web

O cliente é **compilado do fonte** (`cliente/`), no commit fixado do
upstream, com as nossas alterações como série de patches em
`cliente/patches/`. Não é um fork: nada é commitado na árvore do fonte.
Ver `cliente/README.md`.

Um build sem patch nenhum reproduz a imagem publicada byte a byte — é o
que torna a troca de pipeline reversível, e o `construir.sh` refaz essa
conferência sozinho sempre que a série está vazia.

`branding/rebrand.py` continua rodando por cima do build, aplicando a
marca, as traduções e os remendos que ainda vivem no bundle, e gera um
`dist-patched` que é montado no container.

**Nunca rode o `rebrand.py` apontando para `dist-patched`.** Esse é o
diretório que o container serve ao vivo; o script abre cada arquivo em
modo escrita, o que trunca para zero byte antes de reescrever. Quem
carregasse a página nesse instante recebia um `index.html` pela metade,
o service worker guardava aquilo e o navegador passava a exibir o
código-fonte dos scripts como texto na tela — sem que nenhuma correção
no servidor alcançasse aquele cliente.

Publique sempre pelo script, que monta o build num diretório novo,
confere enquanto ele ainda está fora do ar e só então troca de lugar:

```bash
branding/publicar.sh              # gerar, conferir e publicar
deploy/lancar.sh 0.33.0 "…"       # o mesmo, com commit + tag + push
```

`branding/verificar.py` é o portão. Reprova o build se o `index.html`
estiver malformado ou truncado, se alguma tag `<script>`/`<style>` for
alvo de um seletor `#id` (isso torna o código-fonte visível na tela), se
houver id repetido, se a revisão de precache divergir do arquivo, ou se
algum remendo do bundle não tiver encontrado seu alvo. Depois de
publicar, o `publicar.sh` compara o que o servidor **entrega** com o que
está em disco e reverte sozinho se divergir.

O que ele faz e **por que é assim**:

| Alvo | Ação |
|---|---|
| `messages-*.js` (68 locales) | substitui a marca — são catálogos de tradução, texto puro |
| `index-*.js` | substitui **só `Stoat` com caixa exata** |
| `*.css` | há texto visível em `content:` |
| `manifest.webmanifest`, `index.html`, `serviceWorker.js` | nome, título, notificações |
| `*.map` | removidos — não usados em produção e expõem o fonte |
| links institucionais | apontados para domínios próprios |

⚠️ **Nunca faça replace global de "revolt".** O bundle usa
`authentication.revolt` e `type:"revolt"` como identificadores de código —
trocar quebra login e tratamento de erro. A flag `IS_STOAT` deve ficar
intacta: ela **esconde** recursos exclusivos da instância oficial.

## Operação

```bash
docker compose ps
docker compose logs -f api
docker compose restart
docker compose pull && docker compose up -d
```

Criar convite:
```bash
CODE=$(openssl rand -hex 8)
docker compose exec -T database mongosh --quiet revolt \
  --eval "db.account_invites.insertOne({ _id: \"$CODE\" })"
echo "Convite: $CODE"
```

> Não existe exceção para o primeiro usuário: com `invite_only`, até o
> administrador precisa de um código para se registrar.

## Restrições que parecem marca mas são técnicas

- As imagens vêm de um registry externo; as URLs no `compose.yml` precisam
  continuar como estão ou nada sobe.
- O arquivo de configuração precisa se chamar `Revolt.toml` — é o caminho
  que os binários leem.

## DNS

Todos os registros apontam para a VPS. **`chat` precisa ficar sem proxy/CDN**:
WebRTC usa UDP, que proxy HTTP não encaminha — voz e tela quebram, e o
desafio ACME não chega. A landing page pode ficar atrás de proxy sem problema.
