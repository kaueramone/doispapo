#!/usr/bin/env bash
# Desfaz a mudanca de rede do LiveKit.
#
#   bash reverter-rede-voz.sh <carimbo>
#
# O carimbo aparece no fim do aplicar-rede-voz.sh e nos nomes dos arquivos
# guardados aqui.
set -euo pipefail
RAIZ=/root/stoat
AQUI="$(cd "$(dirname "$0")" && pwd)"
CARIMBO="${1:?informe o carimbo, ex: 20260823130000}"

[ -f "$AQUI/livekit.yml.antes-$CARIMBO" ] || {
  echo "!! nao achei o estado guardado com esse carimbo"; ls "$AQUI" | head; exit 1; }

cp "$AQUI/livekit.yml.antes-$CARIMBO" "$RAIZ/livekit.yml"
cp "$AQUI/compose.yml.antes-$CARIMBO" "$RAIZ/compose.yml"
cd "$RAIZ" && docker compose up -d livekit >/dev/null
ufw delete allow 3478/udp >/dev/null 2>&1 || true
echo "==> revertido para o estado de $CARIMBO"
