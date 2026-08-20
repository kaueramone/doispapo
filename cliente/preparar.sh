#!/usr/bin/env bash
# Baixa o fonte do cliente web, no commit exato que roda em producao.
#
#   ./preparar.sh
#
# Ate a versao 0.27 o `dist-orig` vinha de `docker cp` do container: a
# imagem pronta do registry. Isso bastava enquanto as alteracoes eram
# cirurgicas (regex do rebrand.py sobre o bundle minificado). Para mexer
# no layout de voz - mover componentes de lugar, criar painel novo,
# trocar regra de exibicao - remendar minificado nao se sustenta.
#
# Aqui o fonte e baixado raso (--depth 1) no commit fixado. Nao e um
# fork: nada e commitado neste diretorio. O que e nosso vive em
# patches/, versionado no repositorio doispapo, e e aplicado pelo
# construir.sh. Assim o upstream continua limpo e substituivel.
#
# O build do fonte foi conferido contra a imagem publicada: 1451
# arquivos, todos com o mesmo md5. Nao e "equivalente", e o mesmo
# binario - o que significa que trocar a origem do dist e um no-op
# enquanto nenhum patch estiver aplicado.
set -euo pipefail

# Casado com a tag da imagem em compose.yml. Mudar os dois juntos.
COMMIT=0c31cf039ed7abade18e812b3ece05dfab3ff997
ORIGEM=https://github.com/stoatchat/for-web
DESTINO="${1:-/root/dp-web}"

if [ -d "$DESTINO/.git" ] && \
   [ "$(git -C "$DESTINO" rev-parse HEAD 2>/dev/null)" = "$COMMIT" ]; then
  echo "==> fonte ja esta em ${COMMIT:0:7}"
  exit 0
fi

echo "==> baixando o fonte em ${COMMIT:0:7}"
rm -rf "$DESTINO"
mkdir -p "$DESTINO"
cd "$DESTINO"
git init -q
git remote add origin "$ORIGEM"
git fetch -q --depth 1 origin "$COMMIT"
git checkout -q FETCH_HEAD

# Os submodulos sao lidos do proprio commit, entao nao ha versao para
# manter em dia aqui. O de marca (git.stoatinternal.com) e privado e vem
# marcado `update = none` no .gitmodules: o proprio upstream monta a
# imagem publica sem ele, e o copyAssets.mjs cai sozinho no
# scripts/assets_fallback. Pular nao causa divergencia - foi conferido
# no md5 do build.
git config -f .gitmodules --get-regexp path | while read -r chave caminho; do
  nome=${chave#submodule.}; nome=${nome%.path}
  url=$(git config -f .gitmodules --get "submodule.$nome.url")
  case "$url" in
    *stoatinternal*) echo "    pulando submodulo privado: $caminho"; continue;;
  esac
  sha=$(git ls-tree HEAD "$caminho" | awk '{print $3}')
  echo "    submodulo $caminho @ ${sha:0:7}"
  rm -rf "$caminho"; mkdir -p "$caminho"
  (
    cd "$caminho"
    git init -q
    git remote add origin "$url"
    git fetch -q --depth 1 origin "$sha"
    git checkout -q FETCH_HEAD
  )
done

echo "==> fonte pronto em $DESTINO"
