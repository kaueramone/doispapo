#!/usr/bin/env bash
# Roda o portão de fumaça do painel contra a instância no ar.
#
#   deploy/painel/fumaca.sh
#
# Cria uma sessão descartável, abre o painel num navegador de verdade,
# passa por todas as abas e apaga a sessão no fim -- inclusive se o teste
# falhar no meio.
set -euo pipefail

RAIZ=/root/stoat
URL="${1:-https://painel.doispapo.com/}"
HOSTNAME_ALVO=$(echo "$URL" | sed -E 's#^https?://([^/]+).*#\1#')
IP_PUBLICO=187.127.57.149
AQUI="$(cd "$(dirname "$0")" && pwd)"

cd "$RAIZ"

TOKEN=$(docker compose exec -T painel python3 -c "
import os, secrets, time
from pymongo import MongoClient
db = MongoClient(os.environ.get('MONGO_URL','mongodb://database:27017')).revolt
t = 'fumaca-' + secrets.token_urlsafe(16)
db.painel_sessoes.insert_one({'_id': t, 'em': time.time(),
                              'expira': time.time() + 300, 'fumaca': True})
print(t)
" | tr -d '\r')

limpar() {
  docker compose exec -T painel python3 -c "
import os
from pymongo import MongoClient
MongoClient(os.environ.get('MONGO_URL','mongodb://database:27017')).revolt \
  .painel_sessoes.delete_many({'fumaca': True})
" >/dev/null 2>&1 || true
}
trap limpar EXIT

docker run --rm --add-host "$HOSTNAME_ALVO:$IP_PUBLICO" \
  -v "$AQUI/fumaca.js:/fumaca.js:ro" \
  dp-fumaca:1 node /fumaca.js "$URL" "$TOKEN"
