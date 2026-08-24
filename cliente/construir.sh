#!/usr/bin/env bash
# Aplica nossos patches sobre o fonte e compila o cliente web.
#
#   ./construir.sh            # gera /root/stoat/branding/dist-fonte
#
# Saida: o diretorio que o rebrand.py consome. Daqui para frente o
# publicar.sh nao muda em nada - continua montando fora do ar,
# conferindo e trocando de forma atomica.
#
# Os patches sao aplicados com `git apply --3way`. Nao e preciosismo:
# quando o upstream for atualizado, um patch que nao encaixa mais PARA a
# construcao com o arquivo e a linha em conflito, em vez de aplicar pela
# metade e produzir um cliente silenciosamente quebrado.
#
# O build roda inteiro dentro do Dockerfile do proprio upstream. O host
# nao tem Node, e nao deve ter: toolchain divergente entre a VPS e o CI
# do upstream e exatamente o tipo de diferenca que so aparece em
# producao.
set -euo pipefail

FONTE="${FONTE:-/root/dp-web}"
PATCHES="$(cd "$(dirname "$0")" && pwd)/patches"
SAIDA="${SAIDA:-/root/stoat/branding/dist-fonte}"
TAG=dp-web:local

"$(dirname "$0")/preparar.sh" "$FONTE"

cd "$FONTE"

echo "==> voltando o fonte ao estado limpo"
# O reset vem antes do clean de proposito. Um arquivo novo marcado com
# `git add -N` (o que acontece ao gerar os patches) conta como rastreado:
# o clean o deixa para tras, e ai o patch que o cria falha dizendo que o
# arquivo ja existe - com a construcao parando por um motivo que nao tem
# nada a ver com o patch.
git reset -q
git checkout -q -- .
git clean -qfd -e node_modules -e 'packages/*/node_modules'

aplicados=0
shopt -s nullglob
for p in "$PATCHES"/*.patch; do
  echo "    aplicando $(basename "$p")"
  # --3way encosta no indice do git e resolve deslocamento de linha;
  # se o trecho nao existir mais, falha alto em vez de aplicar torto.
  git apply --3way "$p"
  aplicados=$((aplicados + 1))
done
shopt -u nullglob
echo "==> $aplicados patch(es) aplicado(s)"

# Sons proprios, por COPIA e nao por patch.
#
# Sao arquivos binarios: `git diff` os reduz a "Binary files differ", que o
# `git apply --3way` da linha acima nao consegue aplicar. E como o
# `git reset --hard` restaura os originais rastreados a cada build, deixar
# o arquivo trocado na arvore tambem nao para de pe. Copiar aqui, depois
# do reset e antes da compilacao, e o que sobrevive as duas coisas.
# Derivado de $PATCHES, que ja foi resolvido em absoluto la em cima,
# ANTES do `cd "$FONTE"`. Calcular `dirname "$0"` aqui embaixo daria um
# caminho relativo ao fonte -- foi exatamente assim que este passo rodou
# calado da primeira vez, sem copiar som nenhum e sem reclamar.
SONS="$(dirname "$PATCHES")/../branding/sons"
DESTINO_SONS="$FONTE/packages/client/scripts/assets_fallback/sounds"
if [ -n "$SONS" ] && [ -d "$DESTINO_SONS" ]; then
  n=0
  for som in "$SONS"/*.ogg; do
    [ -e "$som" ] || continue
    nome="$(basename "$som")"
    # So substitui o que ja existe: um nome novo aqui nao viraria som
    # nenhum no aplicativo, e passaria despercebido.
    if [ -f "$DESTINO_SONS/$nome" ]; then
      # Abaixo de 4 KB o Vite EMBUTE o arquivo como data URI no bundle em
      # vez de emiti-lo separado -- e o portao de publicacao reprova, com
      # razao: som embutido nao da para personalizar depois. Comprimir bem
      # demais, portanto, quebra. Conferir aqui e mais barato que
      # descobrir cinco minutos de build adiante.
      bytes=$(stat -c%s "$som")
      if [ "$bytes" -lt 4200 ]; then
        echo "!!  som pequeno demais ($bytes bytes < 4200): $nome"
        echo "    o Vite embutiria como data URI. Recodifique com mais taxa."
        exit 1
      fi
      cp "$som" "$DESTINO_SONS/$nome"
      n=$((n + 1))
    else
      echo "!!  som ignorado, nao existe no upstream: $nome"
    fi
  done
  echo "==> $n som(ns) proprio(s) no lugar"
fi

# O --3way encosta no indice. Deixar assim faz `git diff` comparar com os
# patches ja aplicados em vez de com o upstream - e quem for gerar um
# patch depois de construir recebe so a ultima edicao, achando que tem a
# alteracao inteira. Limpar o indice aqui faz `git diff` voltar a
# significar "tudo o que e nosso". Use sempre o gerar-patches.sh.
git reset -q

echo "==> compilando (leva ~5 min)"
docker build -t "$TAG" "$FONTE"

echo "==> extraindo o dist"
rm -rf "$SAIDA.parcial"
cid=$(docker create "$TAG")
mkdir -p "$SAIDA.parcial"
docker cp "$cid:/app/dist/." "$SAIDA.parcial/" >/dev/null
docker rm "$cid" >/dev/null

# So troca depois de extrair inteiro: um dist pela metade em disco seria
# consumido pelo rebrand.py como se estivesse completo.
rm -rf "$SAIDA"
mv "$SAIDA.parcial" "$SAIDA"

echo "==> $(find "$SAIDA" -type f | wc -l) arquivos em $SAIDA"

# Sem patch aplicado, o build TEM que reproduzir a imagem publicada byte
# a byte. Enquanto essa igualdade valer, qualquer defeito que aparecer e
# de patch nosso, nunca da troca de pipeline - e isso e o que torna a
# migracao segura de reverter.
if [ "$aplicados" -eq 0 ] && [ -d /root/stoat/branding/dist-orig ]; then
  echo "==> nenhum patch: conferindo contra a imagem publicada"
  a=$(cd /root/stoat/branding/dist-orig && find . -type f -exec md5sum {} + | sort -k2 | md5sum)
  b=$(cd "$SAIDA" && find . -type f -exec md5sum {} + | sort -k2 | md5sum)
  if [ "$a" = "$b" ]; then
    echo "    identico ao dist-orig"
  else
    echo "!!  DIVERGE do dist-orig - o build nao esta reprodutivel"
    exit 1
  fi
fi
