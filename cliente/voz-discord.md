# Voz no modelo Discord

Registro da mudança: o que passou a valer, onde mora cada peça e por quê.

## Comportamento

| Regra | Onde |
|---|---|
| Quem está em cada canal de voz aparece na lista **sem entrar** | já existia — `VoiceChannelPreview`, com `channel.voiceParticipants` como fonte quando você não está na sala |
| Clique simples abre o canal e **não conecta** | já era assim |
| **Duplo clique conecta**; no canal em que você já está, não faz nada | `0006-lista-de-canais` |
| Duplo clique em outro canal **troca** de sala sem passar por desligar | `connect()` já desconectava antes; faltava o gatilho |
| Microfone, áudio, câmera, tela e desligar no **rodapé da lista de canais** | `0002-rodape-de-voz`, `0004-controles-da-chamada` |
| Estado da conexão no rodapé, **ping em ms no hover** | `0002`, `0001-estado-de-voz` |
| Janela cinza **só com câmera ou tela**, e só enquanto houver alguma | `0001`, `0003-janela-de-chamada` |
| Na janela, **só os quadros de câmera e tela** — ninguém em áudio puro | `0001`, `0005-grade-da-chamada` |

Sem vídeo na sala, nada é montado sobre o histórico: a janela era
`position: absolute` por cima das mensagens, então tirá-la devolve a
altura inteira ao chat.

## Decisões que o código impôs

**`vidTracks` não mede vídeo.** É construído com `withPlaceholder: true`
para a câmera, então tem uma entrada por participante mesmo com todas as
câmeras desligadas — é contagem de gente, não de vídeo. Usar `.length`
faria a janela aparecer sempre e encheria a grade de cards de quem só
está ouvindo. Daí `visualTracks()`, que filtra quem tem publicação de
verdade; a grade, o foco e a regra de exibição passaram a ler dele.

**O botão de chamada no cabeçalho dependia de `showCard`.** Como
`showCard` agora significa "há vídeo na tela", ele voltaria a oferecer
"entrar na chamada" numa sala em que você já está. Passou a depender da
conexão real — e serve de porta de entrada para quem não descobrir o
duplo clique.

**O ping não tem acessor público.** Vem de `room.engine.client.rtt`, que
o cliente de sinalização mantém com o próprio ping/pong. O acesso é
guardado: se o formato mudar, `ping()` devolve `undefined` e o rodapé
relata o estado sem número, em vez de estourar dentro de um render.

**O tooltip do ping é concatenado, não interpolado.** O catálogo
compilado guarda mensagem com placeholder como lista de fragmentos, e o
`rebrand.py` só troca entradas que são string inteira — interpolar
deixaria essa linha em inglês para sempre nesta instância. `Latency` é
string simples; o número entra fora do macro.

## O que saiu

`branding/voz.js` perdeu o `entrarDireto` (48 linhas): ele clicava no
botão "Entrar na chamada" por fora, procurando por texto. Nunca teve
como acertar — o texto do botão mudava conforme o canal ("Iniciar a
chamada", "Entrar na chamada", "Com Fulano"), e o script não enxerga o
estado do app. Junto saiu o `MutationObserver` que existia só para
realimentá-lo.

`VoiceCallCardPreview` deixou de ser usado. O arquivo continua no
upstream; não mexemos nele para não criar conflito à toa.

## Traduções acrescentadas

`branding/traducoes_pt_br.json`, por msgId:

| msgId | inglês | pt-BR |
|---|---|---|
| `4ni4Xj` | Voice connected | Voz conectada |
| `xIgsFr` | Connection lost | Sem conexão |
| `8vQkDt` | Latency | Latência |

`Connecting` e `Reconnecting` o upstream já traduz.

## Defeito encontrado de passagem

O `rebrand.py` escolhia o catálogo pt-BR pegando o primeiro
`messages-*.js` que contivesse `[Ontem às]`. **pt-PT também diz "Ontem
às"** — eram dois candidatos, e qual vinha primeiro dependia da ordem
que o sistema de arquivos devolvia ao `glob`.

Perder esse sorteio não quebraria nada de forma visível: as 249
traduções entrariam no catálogo de Portugal, o contador diria 249, o
`verificar.py` aprovaria, e a interface em pt-BR ficaria exatamente como
estava. Um defeito com aparência de sucesso.

Agora o chunk é resolvido pelo mapa de import do próprio bundle
(`pt-BR/messages.ts` → `messages-*.js`), e a geração para se não
conseguir resolver.

---

## Proposta em aberto — presença da chamada sem vídeo

Escrita em 22/08, depois de rever o modelo com a série já em produção.
**Nada aqui foi implementado.** É material para decidir, não registro do
que vale.

### O que a revisão confirmou

Com os patches no ar, a sidebar já entrega o essencial do Discord: quem
está em cada canal sem precisar entrar, selo AO VIVO em quem transmite,
tempo de sessão, e os controles no rodapé. A distância para o Discord é
menor do que a auditoria visual sugeria — aquela foi medida no build
antigo, sem estes patches.

Sobra uma diferença real, e é estreita: **uma chamada só de áudio não
tem presença nenhuma na área principal**. Três pessoas conversando sem
câmera deixam o histórico exatamente como se nada estivesse acontecendo.
A informação existe, mas só na sidebar, pequena.

### Proposta 1 — faixa compacta quando conectado sem vídeo

Estender o gatilho de "há vídeo na sala" para "estou conectado a este
canal", com duas alturas em vez de uma:

| Estado | Hoje | Proposta |
|---|---|---|
| Fora da chamada | chat inteiro | chat inteiro |
| Conectado, sem vídeo | chat inteiro | faixa de ~120px + chat |
| Conectado, com vídeo | janela + chat | janela + chat |

O princípio do documento continua valendo: nada monta sobre o histórico
sem motivo. O que muda é que **estar numa chamada passa a contar como
motivo** — e o custo são 120px, não a tela.

Detalhe que facilita: o `vidTracks` que este documento descarta por não
medir vídeo — construído com `withPlaceholder: true`, uma entrada por
participante — é exatamente a fonte que uma faixa de presença quer. O
dado que foi filtrado fora da grade é o dado certo para a faixa. O
`visualTracks()` continua mandando na janela; a faixa leria o outro.

Onde encosta: a regra de exibição em `0003-janela-de-chamada` e a grade
em `0005-grade-da-chamada`.

### Proposta 2 — linha de entrada quando há gente e você está fora

Uma linha fina no topo do chat, só quando o canal tem participantes e
você não está conectado:

    3 pessoas em voz · Entrar

Resolve o mesmo problema de descoberta que este documento já reconhece
ao manter o botão do cabeçalho como porta de entrada para quem não acha
o duplo clique — mas no lugar para onde a pessoa está olhando, e sem
tirar altura de nada quando o canal está vazio.

Lê `channel.voiceParticipants`, a mesma fonte que o
`VoiceChannelPreview` usa fora da sala. Patch novo, pequeno.

### O que foi considerado e descartado

**O palco em tela cheia do Discord**, com a conversa num painel lateral.
Custa a altura do chat de forma permanente, cria estados novos para
manter, e o que ele entrega — quem está, quem fala, quem transmite — a
sidebar já entrega. Seria trocar uma solução mais enxuta por uma mais
cara pelo mesmo resultado.

Chegou a ser escrito um `VoiceChannel.tsx` nessa linha, com roteamento
por `channel.isVoice` e atrás de experimento. Foi desfeito ao ler este
documento: contrariava a decisão registrada aqui, e o `gerar-patches.sh`
o teria absorvido para dentro da série na geração seguinte.

Também não mexeria em: duplo clique para conectar, controles no rodapé,
e chat com altura inteira quando não há nada acontecendo. As três são
decisões boas — e a última é melhor que o Discord, cujo chat de canal de
voz vive espremido num painel lateral.

### Achado de passagem

O `<Match>` comentado em `ChannelPage.tsx` (linhas 60–64) casa
`type === "VoiceChannel"`. Esse tipo não existe em "voice chats v2": o
canal de voz é canal de texto com objeto `voice`, lido por
`channel.isVoice`. Aquele bloco não está apenas desativado — nunca
casaria. Vale apagar ou corrigir o comentário, para não sugerir a quem
ler que basta descomentar.

---

# Emenda de 23/08/2026 — o canal de voz virou palco

**Esta emenda substitui a regra central acima.** O que mudou não foi um
detalhe: mudou o que é a página de um canal de voz.

## A regra que caiu

> Janela cinza só com câmera ou tela, e só enquanto houver alguma. Sem vídeo na
> sala, nada é montado sobre o histórico.

Ela partia de uma premissa que deixou de valer: a de que **o histórico é o
centro da página, sempre**. A janela de chamada era uma intrusa sobre ele, e
por isso precisava se justificar a cada momento.

## A regra que vale

**Canal de voz e canal de texto são páginas diferentes.**

| | Área principal | Histórico |
|---|---|---|
| Canal de texto | o histórico | é a própria área principal |
| Canal de voz | **o palco da chamada** | gaveta da direita, pelo ícone de chat no cabeçalho |

O palco tem três estados, todos ocupando a área inteira:

1. **De fora** — o cartão de entrada, com quem já está lá dentro. É o
   `VoiceCallCardPreview` do upstream, que esta série tinha aposentado (ver "O
   que saiu"); voltou ao papel para o qual foi escrito.
2. **Dentro, sem vídeo** — os participantes em ladrilhos de 260×180, avatar de
   88px. Mesmo peso visual que teriam com a câmera ligada.
3. **Dentro, com vídeo** — a grade de quadros, como antes.

O `showCard` deixou de exigir `hasVisual()`: agora significa apenas "estou
conectado a este canal". Quem decide o que aparece é o próprio palco.

## O que isso aposentou

- **A faixa de presença** (`0026`) não morreu: virou o estado 2 do palco. O
  componente ganhou uma variante e a faixa fina de 112px deixou de ser usada.
- **A linha de entrada** (`0027`/`0028`) saiu. Ela existia para dar um caminho
  de entrada sem cobrir o histórico — problema que o palco resolve por
  construção, sendo ele mesmo a porta.

## Duas coisas que o código impôs

**O palco de quem está de fora não passa pelo portal.** O `Float` é um
elemento só, e ele tem outro trabalho: virar miniatura quando você navega para
longe da chamada em que está. Se o palco de um canal que você apenas *olha*
usasse esse mesmo elemento, ver o canal B enquanto conversa no A tomaria o
portal e a chamada A perderia a miniatura. Então o cartão de entrada é montado
direto na página, e o portal fica reservado a "a chamada em que eu estou".

**O marcador virou a área.** Ele nasceu como um `<div>` vazio no topo do
histórico, só para dizer ao cartão flutuante onde se ancorar. Agora cresce para
ocupar a área principal, e o palco recebe dele a posição *e* a altura — que o
efeito passou a aplicar inline, porque a altura era fixa em `40vh` no CSS. É
isso que faz o palco encolher sozinho quando a gaveta de chat abre.

**As gavetas da direita são exclusivas.** Chat e lista de membros disputam o
mesmo espaço; sem isso, abrir o chat deixava as duas abertas e o palco espremido
numa terceira coluna. O botão de membros continua trocando de uma para a outra
num clique.
