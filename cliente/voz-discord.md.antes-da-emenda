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
