#!/usr/bin/env bash
# Grava os contadores de rede da máquina num arquivo que o serviço de
# convites consegue ler.
#
# Por que não ler direto de dentro do container: `/proc/net/dev` é gerado
# por namespace de rede no momento da leitura. Montar o arquivo do host
# dentro do container devolve os números DO CONTAINER -- conferido: o host
# reportava 22 GB recebidos e o container, 200 bytes. Um número plausível
# e completamente errado, que é o pior tipo.
#
# Instalação (uma vez):
#   cp deploy/amostra-rede.sh /root/stoat/
#   mkdir -p /root/stoat/data/rede
#   crontab -l | { cat; echo "* * * * * /root/stoat/amostra-rede.sh"; } | crontab -
set -euo pipefail

DESTINO=/root/stoat/data/rede/atual
IFACE=$(ip -o -4 route show to default | awk '{print $5}')

[ -n "$IFACE" ] || exit 0

RX=$(cat "/sys/class/net/$IFACE/statistics/rx_bytes")
TX=$(cat "/sys/class/net/$IFACE/statistics/tx_bytes")

# Escrita atômica: o leitor roda a cada minuto e nunca deve pegar meia
# linha.
TMP="$DESTINO.tmp"
printf '%s %s %s\n' "$(date +%s)" "$RX" "$TX" > "$TMP"
mv "$TMP" "$DESTINO"
