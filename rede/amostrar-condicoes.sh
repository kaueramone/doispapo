#!/usr/bin/env bash
# Coleta a serie do /condicoes por alguns minutos.
#
#   rede/amostrar-condicoes.sh 30 > /tmp/serie.txt &
#
# Uma leitura isolada nao decide nada: 1 fps pode ser a tela parada e pode
# ser a captura estrangulada. O que separa os dois casos e a SERIE.
set -u
n="${1:-30}"
IP=$(getent hosts chat.doispapo.com | awk '{print $1; exit}')
for i in $(seq 1 "$n"); do
  curl -s --resolve "chat.doispapo.com:443:$IP" \
    https://chat.doispapo.com/api-convites/condicoes \
  | python3 -c '
import json,sys,time
d=json.load(sys.stdin)
for t in d.get("transmissores",[]):
    print("%s  %s  fps=%-5s alt=%-5s limite=%-6s ms/quadro=%-6s pausado=%s ha=%ss" % (
        time.strftime("%H:%M:%S"), t["usuario"][:10],
        t.get("fps"), t.get("altura"), t.get("limite"),
        (round(t["msQuadro"],1) if t.get("msQuadro") is not None else None),
        t.get("pausado"), t.get("ha_s")), end="")
    print("  captura=%-5s segCpu=%-6s segBanda=%s" % (
        t.get("capturaFps"),
        (round(t["segCpu"],1) if t.get("segCpu") is not None else None),
        (round(t["segBanda"],1) if t.get("segBanda") is not None else None)), end="")
    print("  motor=%-28s codec=%-6s app=%s" % (
        t.get("motor"), t.get("codec"), t.get("app")))
' 2>/dev/null
  sleep 10
done
