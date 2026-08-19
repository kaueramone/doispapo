#!/usr/bin/env bash
# Aplica a marca sobre o build do cliente e publica.
# Uso: ./publicar.sh
set -e

RAIZ=/root/stoat
BR=$RAIZ/branding

cd "$BR"

# Extrai o build original do container, caso ainda não exista
if [ ! -d dist-orig ]; then
  echo "==> extraindo build original do container"
  docker cp stoat-web-1:/app/dist ./dist-orig
fi

echo "==> aplicando a marca"
python3 /root/doispapo/branding/rebrand.py dist-orig dist-patched

VERSAO=$(python3 -c "import json;print(json.load(open('dist-patched/versao.json'))['build'])")
echo
echo "==> versão do build: $VERSAO"

echo "==> reiniciando o cliente web"
cd "$RAIZ"
docker compose restart web >/dev/null

echo "==> aguardando subir"
until curl -sf --resolve chat.doispapo.com:443:187.127.57.149 \
      https://chat.doispapo.com/versao.json -o /dev/null; do sleep 1; done

SERVIDA=$(curl -s --resolve chat.doispapo.com:443:187.127.57.149 \
          https://chat.doispapo.com/versao.json)
echo
echo "==> no ar: $SERVIDA"
echo
echo "Os navegadores já abertos vão exibir o aviso de nova versão em até"
echo "5 minutos. Quem recarregar a página atualiza na hora."
