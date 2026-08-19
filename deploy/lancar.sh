#!/usr/bin/env bash
# Lança uma versão da plataforma na ordem correta.
#
#   ./lancar.sh 0.26.0 "descrição da mudança"
#
# A ordem importa: a versão exibida no app vem de `git describe`, lido
# durante a geração do build. Gerar antes de criar a tag faz o app exibir
# a versão anterior — foi o que aconteceu na 0.20.0.
#
# A publicação em si é delegada ao publicar.sh, que monta o build num
# diretório separado, confere enquanto ele ainda está fora do ar e só
# então troca. Este script não escreve nada no que está sendo servido.
set -euo pipefail

VERSAO="${1:?informe a versão, ex: 0.26.0}"
DESC="${2:-versão $VERSAO}"
REPO=/root/doispapo

cd "$REPO"

if git rev-parse "v$VERSAO" >/dev/null 2>&1; then
  echo "erro: a tag v$VERSAO já existe"; exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "==> 1/4 commitando alterações pendentes"
  git add -A && git commit -q -m "$DESC"
else
  echo "==> 1/4 nada pendente para commitar"
fi

echo "==> 2/4 criando a tag ANTES do build"
git tag -a "v$VERSAO" -m "$DESC"

echo "==> 3/4 gerando, conferindo e publicando"
if ! VERSAO_ESPERADA="$VERSAO" "$REPO/branding/publicar.sh"; then
  echo
  echo "!! publicação reprovada — removendo a tag v$VERSAO"
  git tag -d "v$VERSAO" >/dev/null
  exit 1
fi

echo "==> 4/4 enviando ao GitHub"
git push -q origin main && git push -q origin "v$VERSAO"

echo
echo "v$VERSAO no ar."
