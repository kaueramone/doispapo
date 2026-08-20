# Fila

O que está combinado para fazer, com o que já foi apurado. Não é lista de
desejos: cada item aqui já passou por uma olhada no código, e o que está
escrito é o que se sabe hoje — inclusive o que ainda não se sabe.

---

## Destacar câmera ou tela da grade para uma janela própria

**Pedido.** Com câmeras e telas na janela cinza, clicar com o botão
direito num quadro e tirá-lo da grade. Ele vira uma janela solta,
arrastável e redimensionável, para a pessoa posicionar cada transmissão
onde quiser na sua tela. É **arranjo local**: não muda nada para os
outros participantes da chamada.

### O que o Discord faz de fato (pesquisado, 2026-08)

Vale corrigir a referência antes de projetar em cima dela. O Discord tem
**Pop Out View**: destaca a **janela inteira da chamada** — com todas as
transmissões dentro — para **uma** janela separada, que se move pela tela,
tem *Stay On Top* para fixar acima das outras, e botão de tela cheia.

O que ele **não** tem é uma janela por transmissão. Destacar cada stream
para sua própria janela é pedido recorrente da comunidade há anos, com
várias linhas abertas no fórum de suporte, e segue não implementado. Hoje
a saída de quem precisa disso é capturar a janela do Discord várias vezes
e recortar cada pedaço.

Ou seja: o que foi pedido aqui é **mais** do que o Discord entrega. Isso
não é motivo para não fazer — é motivo para fatiar, porque a primeira
fatia já dá paridade com ele.

### O que a plataforma web oferece

**`documentPictureInPicture`** — janela real do sistema, sempre no topo,
que hospeda DOM da própria página.

| | |
|---|---|
| Contexto de JavaScript | **compartilhado** com a página que abriu |
| Sempre no topo | sim, por natureza |
| Quantidade | **uma por aba**, limite do próprio navegador |
| Posição | definida pelo navegador; o site não escolhe |
| Requisito | contexto seguro (HTTPS) — já temos |
| Suporte | Chromium; **não** está no Firefox nem no Safari |

O contexto compartilhado é o que derruba a parede 1: o `<video>` continua
sendo o mesmo elemento, no mesmo documento lógico, então o observador de
visibilidade não o considera fora de tela e a faixa segue assinada.

**`window.open` na mesma origem** — para ir além de uma janela.

| | |
|---|---|
| Contexto de JavaScript | compartilhado via `window.opener` |
| Sempre no topo | não |
| Quantidade | várias |
| Posição e tamanho | a pessoa ajusta; o site pode sugerir |
| Suporte | todos os navegadores |
| Pega | bloqueador de pop-up — precisa de gesto do usuário (o clique do menu de contexto serve) |

### Desenho sugerido, em duas fatias

**Fatia 1 — paridade com o Discord, e um pouco além.** Destacar *um*
quadro via `documentPictureInPicture`. Resolve o caso comum (uma tela
compartilhada que a pessoa quer no segundo monitor), não precisa de janela
nativa, e já nasce sempre-no-topo. Como é o mesmo contexto, não há
duplicação de assinatura nem participante fantasma.

Detalhe que já temos meio caminho andado: a janela da chamada **já é**
flutuante e arrastável, com canto magnético e tela cheia
(`VoiceCallCard.tsx`). O que falta é ela poder sair da página.

**Fatia 2 — várias janelas.** `window.open` para o segundo quadro em
diante. Aqui aparece a diferença entre navegador e desktop, e só aqui.

### Desktop (Tauri v2)

O invólucro aponta para `chat.doispapo.com` e não tem frontend próprio. Um
`WebviewWindow` novo do Tauri é **outro webview, com contexto próprio** —
não dá para entregar uma `MediaStream` a ele, e por isso não serve.

O caminho é não criar janela nativa nenhuma: o WebView2 do Windows é
Chromium *evergreen*, sempre na versão recente, então
`documentPictureInPicture` deve funcionar dentro do webview que já existe.
**Isso precisa ser testado antes de virar plano** — é a única suposição
aqui que não foi verificada. Para a fatia 2, falta apurar o que o Tauri
faz com `window.open` (pode abrir no navegador do sistema em vez de um
webview).

### O que precisa ser decidido

1. Fatia 1 sozinha resolve o seu caso, ou várias janelas é requisito desde
   o começo?
2. A janela destacada leva só o vídeo, ou também nome, indicador de fala e
   volume?
3. Fechar devolve o quadro à grade, ou deixa de assistir?
4. Ao sair da chamada, a janela destacada fecha sozinha — assumo que sim.

### Tamanho

Fatia 1 é modesta: menu de contexto no `ParticipantTile`, mover o nó para
a janela de PiP, copiar as folhas de estilo, e devolver ao fechar. Fatia 2
é bem maior, e carrega sozinha quase toda a incerteza de desktop.

---

## Dívidas conhecidas

**`voz.js` ainda procura nomes minificados** — `eQVZMd`, `dKGhWu`,
`fXciza`, `hgBSwO`, `GrQgU`. Depender de nome sorteado pelo minificador já
quebrou coisa quatro vezes: foi o motivo de passarmos a compilar do fonte,
derrubou a conferência de versão (`const dW`), e derrubou os remendos da
página de Som e da atribuição do GIPHY. Agora que há fonte, esses cinco
podem virar marcadores estáveis, junto com as seções §1g e §1h do
`rebrand.py`.

**Sem teste automatizado nos endpoints de feedback e novidades.** O
projeto tem o padrão — `teste_som.py` e `teste_emoji.py` rodam dentro do
container contra o serviço real — e as rotas novas do `convites` e do
`painel` foram entregues sem o equivalente.

**Mensagens de sistema continuam sendo criadas.** Desde a 0.34.0 elas não
aparecem no chat, mas seguem no banco e ainda marcam o canal como não
lido. Falta decidir se são apagadas de vez.

**Plural do contador de membros** (`NdK37b`) é a única entrada do catálogo
com estrutura ICU que ficou sem tradução; as outras 21 com variável já
foram.
