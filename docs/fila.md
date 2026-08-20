# Fila

O que está combinado para fazer, com o que já foi apurado. Não é lista de
desejos: cada item aqui já passou por uma olhada no código, e o que está
escrito é o que se sabe hoje — inclusive o que ainda não se sabe.

---

## Destacar câmera ou tela — **entregue na 0.38.0**

Clique direito no quadro → "Destacar em janela própria". Várias ao mesmo
tempo, posicionadas onde a pessoa quiser. Fechar devolve à grade; sair da
chamada fecha todas.

**Mecanismo:** `window.open` na mesma origem — mesmo contexto de
JavaScript, então dá para entregar o `MediaStream`. Foi preferido ao
`documentPictureInPicture` porque este dá **uma** janela por aba e a
posição é escolhida pelo navegador; o objetivo aqui era arrumar várias no
lugar exato. O PiP continua possível como opção de "sempre no topo" — o
caminho do código é quase o mesmo, muda só como a janela é obtida.

**A parede da assinatura era real, e não era onde eu disse.** Registrei
antes que o contexto compartilhado resolveria sozinho. Não resolve: o
observador de visibilidade vive no documento principal, e o quadro fora da
grade deixa de ter um `<VideoTrack>` cuidando da assinatura. O destaque
assina por conta própria, e no caso de tela compartilhada ainda avisa o
`tela.js` via `window.dpTelaAssistir` — sem isso a janela escureceria
poucos segundos depois de abrir.

**Pendente de teste no desktop.** `window.open` dentro do WebView2 do
Tauri pode abrir no navegador do sistema em vez de uma janela do
aplicativo. Única suposição do desenho que segue não verificada.

---

---

## Dívidas conhecidas

**O compartilhamento de tela não tem cobertura automatizada nenhuma** — e é
a parte do produto com mais lógica própria: assinatura sob demanda, prévia
borrada, áudio em faixa separada, destaque em janela. Duas regressões
seguidas chegaram à produção pela mesma fresta (0.39.1: captura de prévia
em laço; e o áudio de tela, que nunca funcionou desde que a assinatura sob
demanda existe).

O portão de fumaça abre a página e confere que o aplicativo monta. Ele não
entra em canal, não compartilha tela e não assina faixa — então nada disso
é exercitado antes de publicar.

O que falta é um teste que ligue dois participantes de verdade contra a
instância, como `teste_som.py` e `teste_emoji.py` já fazem para os
serviços próprios. Com dois navegadores sem interface e duas contas de
teste dá para cobrir: entrar num canal com tela já em curso, começar a
compartilhar com gente dentro, assistir, parar de assistir, e conferir que
a faixa de áudio acompanha a de vídeo.

**`voz.js` ainda procura nomes minificados** — `eQVZMd`, `dKGhWu`,
`fXciza`, `hgBSwO`, `GrQgU`. Depender de nome sorteado pelo minificador já
quebrou coisa cinco vezes: foi o motivo de passarmos a compilar do fonte,
derrubou a conferência de versão (`const dW`), e derrubou os remendos da
página de Som e da atribuição do GIPHY. Agora que há fonte, esses cinco
podem virar marcadores estáveis, junto com a seção §1g do `rebrand.py`.
A §1h já foi: o marcador de fala e o `data-dp-uid` passaram a ser escritos
pelo `ParticipantTile` no fonte (0.38.0).

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
