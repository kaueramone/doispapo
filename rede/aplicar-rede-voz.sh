#!/usr/bin/env bash
# Aplica a mudanca de rede do LiveKit: TURN proprio e porta UDP unica.
#
#   bash aplicar-rede-voz.sh          # aborta se houver gente em chamada
#   FORCAR=1 bash aplicar-rede-voz.sh # aplica mesmo assim
#
# O que muda, e por que:
#
#   1. TURN ligado (UDP 3478). Das 222 entradas em voz medidas, so 197
#      completaram a conexao RTC -- uma em cada nove pessoas nao entrava.
#      Sem TURN a unica alternativa era TCP, e video por TCP trava.
#
#   2. Uma porta UDP no lugar de 101. O intervalo 50000-50100 custava 209
#      processos `docker-proxy` e 601 MB de RAM parados, e limitava os
#      fluxos simultaneos ao tamanho do intervalo.
#
# NAO mexe em `network_mode: host`, que seria o passo seguinte: com a rede
# do host o container deixa de resolver `redis` pelo nome, e consertar isso
# exige publicar o Redis no host -- risco maior do que o ganho, ja que a
# porta unica acima recupera quase toda a memoria.
set -euo pipefail

RAIZ=/root/stoat
AQUI="$(cd "$(dirname "$0")" && pwd)"
CARIMBO=$(date +%Y%m%d%H%M%S)

# ---------------------------------------------------- portao
# Reiniciar o LiveKit derruba toda chamada em andamento. Mesmo portao do
# publicar.sh, pelo mesmo motivo.
gente=$(docker exec stoat-livekit-1 sh -c \
  "wget -qO- http://localhost:6789/metrics 2>/dev/null" \
  | awk '/^livekit_participant_total/ {print $2}' | head -1)
gente=${gente:-0}

if [ "${gente%.*}" -gt 0 ] && [ -z "${FORCAR:-}" ]; then
  echo "!! ha $gente pessoa(s) em chamada agora."
  echo "   Reiniciar o LiveKit derruba todas. Rode de novo com FORCAR=1"
  echo "   se for para interromper mesmo assim."
  exit 1
fi

echo "==> guardando o estado atual"
cp "$RAIZ/livekit.yml"  "$AQUI/livekit.yml.antes-$CARIMBO"
cp "$RAIZ/compose.yml"  "$AQUI/compose.yml.antes-$CARIMBO"

echo "==> trocando a configuracao"
cp "$AQUI/livekit.yml.novo" "$RAIZ/livekit.yml"

echo "==> ajustando as portas publicadas"
python3 - "$RAIZ/compose.yml" <<'PY'
import sys
caminho = sys.argv[1]
s = open(caminho, encoding="utf-8").read()
antes = '      - "50000-50100:50000-50100/udp"'
depois = ('      - "50000:50000/udp"\n'
          '      - "3478:3478/udp"\n'
          '      - "30000-30060:30000-30060/udp"')
if antes not in s:
    raise SystemExit("!! nao achei a linha das portas UDP no compose.yml")
open(caminho, "w", encoding="utf-8").write(s.replace(antes, depois, 1))
print("   portas: 50000/udp (midia) e 3478/udp (TURN)")
PY

echo "==> liberando o TURN no firewall"
ufw allow 3478/udp comment "LiveKit TURN" >/dev/null

echo "==> subindo"
cd "$RAIZ"
docker compose up -d livekit >/dev/null

echo "==> conferindo"
ok=""
for _ in $(seq 1 30); do
  if docker exec stoat-livekit-1 sh -c \
      "wget -qO- http://localhost:6789/metrics" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 1
done

if [ -z "$ok" ]; then
  echo "!! o LiveKit nao respondeu. Revertendo."
  cp "$AQUI/livekit.yml.antes-$CARIMBO" "$RAIZ/livekit.yml"
  cp "$AQUI/compose.yml.antes-$CARIMBO" "$RAIZ/compose.yml"
  docker compose up -d livekit >/dev/null
  echo "   estado anterior restaurado."
  exit 1
fi

proxies=$(pgrep -fc "[d]ocker-proxy" || echo 0)
echo
echo "==> no ar. Processos docker-proxy agora: $proxies (eram 209)"
echo "    Reverter:  bash $AQUI/reverter-rede-voz.sh $CARIMBO"
echo
echo "Teste a fazer: entrar em voz de uma rede movel (4G/5G), que e onde"
echo "a conexao direta costuma falhar. Se entrar, o TURN esta cumprindo."
