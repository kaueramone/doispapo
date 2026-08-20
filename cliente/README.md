# Cliente web compilado do fonte

Até a 0.32 o cliente vinha como imagem pronta do registry e as nossas
alterações eram aplicadas por regex sobre o bundle minificado, no
`branding/rebrand.py`. Isso serve para remendo cirúrgico — trocar uma
string, desligar um indicador, acrescentar uma condição num ponto
conhecido. Não serve para layout: mover um componente de lugar por
expressão regular não sobrevive a nenhum upgrade do upstream, e quando
quebra não há como depurar.

Daqui em diante o cliente é **compilado do fonte**, no commit exato que
já rodava, com as nossas alterações versionadas como série de patches.

> Não é um fork. Nada é commitado em `/root/dp-web`. O que é nosso vive
> em `patches/`, dentro deste repositório.

## Por que dá para confiar na troca

Um build **sem nenhum patch** reproduz a imagem publicada byte a byte:
1451 arquivos, todos com o mesmo md5, incluindo `index.html` e o
`index-*.js`. O `construir.sh` refaz essa conferência sozinho sempre que
a série está vazia, e falha se divergir.

Isso é o que torna a migração reversível na prática: qualquer defeito que
apareça é de patch nosso, nunca da troca de pipeline.

## Como funciona

```
preparar.sh      baixa o fonte raso no commit fixado, com os submódulos
                 públicos (o de marca é privado — o próprio upstream monta
                 a imagem pública sem ele)

construir.sh     reseta a árvore, aplica patches/, compila no Dockerfile
                 do upstream e extrai para branding/dist-fonte

gerar-patches.sh regenera patches/ a partir do fonte editado
```

`branding/publicar.sh` chama o `construir.sh` e segue como sempre:
`rebrand.py` por cima, `verificar.py` como portão, troca atômica e
reversão automática se o servidor entregar algo diferente do disco.

## Editando

```bash
vim /root/dp-web/packages/client/...     # edita o fonte
cliente/gerar-patches.sh                 # vira patch
cliente/construir.sh                     # compila
```

Arquivo novo precisa entrar no mapa `SERIE` do `gerar-patches.sh`. Ele
reprova se encontrar arquivo alterado fora da série — sem isso a
alteração sumiria no próximo `construir.sh`, que reseta a árvore.

**Nunca use `git diff` cru para gerar patch.** O `construir.sh` aplica
com `git apply --3way`, que escreve no índice; depois disso `git diff`
compara com os patches já aplicados e devolve só a última edição. O
patch sai parecendo completo, aplica sem erro e produz um cliente com
metade da mudança. O `gerar-patches.sh` usa `git diff HEAD` justamente
por isso.

## Upgrade do upstream

Trocar o `COMMIT` no `preparar.sh` e a tag da imagem no `compose.yml`
(os dois juntos — o `Dockerfile` de runtime e o `inject.js` vêm da
imagem). Rodar `construir.sh`: cada patch que não encaixar mais para a
construção apontando o arquivo em conflito.

## O que ainda depende de nome minificado

O `rebrand.py` e o `branding/voz.js` continuam alcançando o bundle
compilado — as seções `1g` (assinatura de tela sob demanda) e `1h`
(marcador de quem fala), e as classes `eQVZMd`, `dKGhWu`, `fXciza`,
`hgBSwO`, `GrQgU` que o `voz.js` procura. Com o fonte na mão, essas duas
seções podem virar patch e as classes podem virar marcadores estáveis.
Não foi feito ainda: sobreviveram à mudança (conferido), e trocar de uma
vez misturaria duas mudanças num mesmo lançamento.
