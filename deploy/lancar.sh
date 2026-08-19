#!/usr/bin/env bash
# Lança uma versão da plataforma na ordem correta.
#
#   ./lancar.sh 0.21.0 "descrição da mudança"
#
# A ordem importa: a versão exibida no app vem de `git describe`, lido
# durante a geração do build. Gerar antes de criar a tag faz o app exibir
# a versão anterior — foi o que aconteceu na 0.20.0.
set -euo pipefail

VERSAO="${1:?informe a versão, ex: 0.21.0}"
DESC="${2:-versão $VERSAO}"
REPO=/root/doispapo
RAIZ=/root/stoat

cd "$REPO"

if git rev-parse "v$VERSAO" >/dev/null 2>&1; then
  echo "erro: a tag v$VERSAO já existe"; exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "==> commitando alterações pendentes"
  git add -A && git commit -q -m "$DESC"
fi

echo "==> 1/4 criando a tag ANTES do build"
git tag -a "v$VERSAO" -m "$DESC"

echo "==> 2/4 gerando o build"
cd "$RAIZ/branding"
python3 "$REPO/branding/rebrand.py" dist-orig dist-patched | grep -E "versao-app|ABORTADO" || true

BAKED=$(grep -o 'const dW="[0-9.]*"' dist-patched/assets/index-*.js | head -1 |
        grep -o '[0-9.]*')
if [ "$BAKED" != "$VERSAO" ]; then
  echo "erro: o build ficou com $BAKED e não $VERSAO — tag não aplicada"
  cd "$REPO" && git tag -d "v$VERSAO"
  exit 1
fi
echo "    build carimbado com $BAKED"

echo "==> 3/4 publicando"
cd "$RAIZ" && docker compose restart web >/dev/null
until curl -sf --resolve chat.doispapo.com:443:187.127.57.149 \
      https://chat.doispapo.com/versao.json -o /dev/null; do sleep 1; done

echo "==> 4/4 enviando ao GitHub"
cd "$REPO" && git push -q origin main && git push -q origin "v$VERSAO"

echo
echo "v$VERSAO no ar."
curl -s --resolve chat.doispapo.com:443:187.127.57.149 \
  https://chat.doispapo.com/versao.json
echo
