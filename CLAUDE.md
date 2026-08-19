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

## Rebranding do cliente web

O cliente vem como imagem pré-compilada. `branding/rebrand.py` extrai o
build, aplica a marca e gera um `dist-patched` que é montado por cima.

```bash
python3 branding/rebrand.py dist-orig dist-patched
```

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
