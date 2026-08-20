# Fila

O que está combinado para fazer, com o que já foi apurado. Não é lista de
desejos: cada item aqui já passou por uma olhada no código, e o que está
escrito é o que se sabe hoje — inclusive o que ainda não se sabe.

---

## Destacar câmera ou tela da grade para uma janela própria

**Pedido.** Com câmeras e telas na janela cinza, clicar com o botão
direito num quadro e escolher tirá-lo da grade. Ele vira uma janela solta,
arrastável e redimensionável, para a pessoa posicionar cada transmissão
onde quiser na sua tela. No navegador, uma aba nova; no desktop, uma
janela nova.

**Onde encosta no código de hoje**

| Peça | Papel |
|---|---|
| `ParticipantTile.tsx` | o quadro que seria destacado |
| `VoiceCallCardActiveRoom.tsx` | a grade, e o foco (`toggleFocus`) |
| `rtc/state.tsx` → `visualTracks()` | quem entra na grade |
| `branding/tela.js` + `rebrand.py` §1g | assinatura de faixa sob demanda |

### Duas paredes que precisam ser resolvidas antes de escrever tela

**1. Sair da grade hoje significa parar de receber o vídeo.**

O aplicativo cancela a assinatura da faixa por visibilidade —
`IntersectionObserver` a 80%, com 3s de carência — e o nosso `tela.js`
acrescenta uma segunda condição por cima (§1g do `rebrand.py`). Um quadro
levado para fora do documento principal fica invisível para esse
observador, a assinatura cai, e a janela destacada mostra preto.

Ou seja: **destacar não é só mover um elemento**. É preciso um estado
"este quadro está sendo assistido em outro lugar" que isente a faixa das
duas regras de cancelamento. Se isso for esquecido, o defeito aparece uns
segundos depois de destacar — tempo suficiente para parecer instabilidade
de rede em vez de bug nosso.

**2. No desktop a janela nova não compartilha o contexto de JavaScript.**

Isso separa os dois ambientes de verdade:

- **Navegador.** Uma janela aberta com `window.open` na mesma origem
  compartilha o contexto com quem abriu (`window.opener`). Dá para
  entregar a `MediaStream` para a janela filha, ou literalmente mover o
  `<video>` para lá. Funciona.

- **Desktop (Tauri v2).** Uma janela nova é **outro webview**, com
  contexto próprio. Não há como passar uma `MediaStream` para ela. As
  saídas conhecidas, todas com custo:
  1. a janela destacada entra na sala do LiveKit como um segundo assinante
     — gasta banda em dobro e aparece como mais um participante, a menos
     que se invente uma identidade oculta;
  2. manter o vídeo na janela principal e usar uma janela Tauri
     transparente sempre-no-topo como moldura — frágil, e quebra ao mover
     a janela principal;
  3. transportar quadros por IPC — caro e com atraso.

**Caminho que provavelmente resolve os dois de uma vez:**
`documentPictureInPicture`. É uma janela real do sistema, solta,
redimensionável e sempre no topo, que hospeda DOM da própria página —
então o `<video>` continua no mesmo contexto e a faixa segue assinada
normalmente. E como o Tauri no Windows usa WebView2, que é Chromium, a
mesma implementação tende a valer para o desktop **sem precisar de janela
nativa nenhuma**.

O limite conhecido: **uma janela de Picture-in-Picture por documento**. O
pedido fala em posicionar as telas *que quiser*, no plural. Então ou
começamos com uma destacada por vez, ou combinamos Picture-in-Picture para
a primeira e `window.open` para as demais — o que reintroduz a diferença
entre navegador e desktop, só que restrita ao segundo quadro em diante.

### O que precisa ser decidido

1. Uma janela destacada por vez (simples, funciona nos dois ambientes) ou
   várias (exige o caminho híbrido acima)?
2. A janela destacada leva só o vídeo, ou também nome, indicador de fala e
   controle de volume?
3. Fechar a janela devolve o quadro à grade, ou deixa de assistir?
4. Ao sair da chamada, a janela destacada fecha sozinha — assumo que sim.

### Tamanho

Não é pequeno. O menu de contexto e o mover do elemento são a parte fácil;
o trabalho de verdade está na regra de assinatura (parede 1) e em provar o
comportamento no Tauri (parede 2). Vale fatiar: primeiro uma janela por
vez via `documentPictureInPicture` no navegador, medir, e só então decidir
sobre desktop e sobre várias janelas.

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
