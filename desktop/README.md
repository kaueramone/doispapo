# Dois Papo para Windows

Invólucro nativo da plataforma, feito em [Tauri](https://v2.tauri.app).
A janela aponta direto para `chat.doispapo.com` — não há frontend próprio,
o aplicativo web continua sendo o mesmo.

## O que ele acrescenta ao navegador

- Janela própria, sem barra de endereço
- Ícone na bandeja do sistema
- Fechar esconde em vez de encerrar, para a chamada de voz não cair
- Atalho no menu Iniciar e ícone na barra de tarefas

## Compilação

Não é feita na VPS: gerar binário do Windows exige toolchain do Windows.
O workflow `.github/workflows/windows.yml` compila num runner do GitHub.

**Disparar:**
- Aba *Actions* → *Instalador Windows* → *Run workflow*, ou
- publicar uma tag: `git tag desktop-v0.1.0 && git push origin desktop-v0.1.0`

Os instaladores (`.exe` via NSIS e `.msi`) ficam nos artefatos da execução.

## Requisito no computador do usuário

O WebView2 já vem no Windows 10 e 11. Em instalações antigas o instalador
NSIS baixa o runtime automaticamente.

## Assinatura de código

O executável **não é assinado**. O SmartScreen exibirá "aplicativo não
reconhecido" e o usuário precisa clicar em *Mais informações → Executar
assim mesmo*. Assinar exige certificado pago (na faixa de US$ 200–400/ano);
para um grupo pequeno costuma não compensar.

## Destacar a tela em janela própria

Desde a 0.1.6 o `main.rs` registra `on_new_window` na janela principal. Sem
isso, o wry no Windows responde `args.SetHandled(true)` sem criar janela
nenhuma, e `window.open()` devolve `null`. O Document Picture-in-Picture do
Chromium passa pelo **mesmo caminho** — `openPictureInPictureWindow` chama
`FindOrCreateFrameForNavigation(..., "_blank")` — então os dois jeitos de
destacar morriam no mesmo ponto. A causa nunca foi permissão do Windows nem
API ausente.

Por isso a janela principal passou a ser construída no Rust
(`WebviewWindowBuilder::from_config`) com `"create": false` no
`tauri.conf.json`: `on_new_window` só existe no builder.

### O teste que decide, antes de confiar no recurso

Abrir a janela não prova que a tela vai aparecer nela. Falta saber se os
dois documentos ficam no **mesmo processo de renderização** — sem isso não
há como entregar um `MediaStream` vivo de um para o outro.

A documentação da Microsoft diz que renderers são compartilhados entre
`CoreWebView2` da mesma pasta de dados, e que a WebView entregue ao
`NewWindow` "é devolvida ao script do opener como o WindowProxy aberto".
WindowProxy implica mesmo browsing context group, que implica mesmo
processo. Mas essa última ligação é **dedução**, não documentação.

Com o instalador novo na mão, destaque uma tela e rode no console **da
janela nova**:

```js
window.opener                    // null  -> grupo diferente, o caminho morreu
window.opener.location.href      // lança -> agent cluster diferente
window.opener.document.body      // imprime o <body> -> MESMO processo, resolvido
```

A terceira linha é a que decide. Acesso **síncrono** a `opener.document` só
é possível dentro do mesmo processo — o Chromium não tem como fazer isso
entre processos. Se ela imprimir o `<body>`, o `MediaStream` passa e o
`destacar.ts` (que já funciona no navegador) funciona aqui sem mudança.

### Se falhar

Dois planos B, nesta ordem de custo:

1. **Segunda janela assinando a faixa por conta própria.** Custa um decode
   extra e a faixa baixada duas vezes, mas dispensa opener, Environment
   compartilhado e `on_new_window` inteiro. Exige token do LiveKit com
   identidade distinta (`<user>#destaque-N`) — identidade repetida derruba
   a conexão principal com `DUPLICATE_IDENTITY`. É mudança na API, não no
   cliente.
2. **Loopback `RTCPeerConnection` local**, sinalizado por `BroadcastChannel`
   (que atravessa grupos de contexto, ao contrário de `postMessage`). Custa
   um encode + um decode a mais por tela destacada. Não toca no servidor.

`MediaStreamTrack` transferível **não** resolve: a spec exige o mesmo agent
cluster para o transfer (`DataCloneError` caso contrário), que é a mesma
condição de passar a referência direta — e `BroadcastChannel`, o único
canal entre grupos, não aceita transfer list.

### Detalhe que vale para qualquer um dos caminhos

A janela destacada tem de chamar `window.dpTelaAssistir(sid, true)` ao abrir
e `false` ao fechar. Sem isso o `dpTelaBloqueia` do `branding/tela.js` recusa
a assinatura e a janela abre preta. O `destacar.ts` já faz isso.
