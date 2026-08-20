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
