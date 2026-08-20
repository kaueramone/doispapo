#!/usr/bin/env bash
# Sobe um build candidato num container proprio e passa o portao de
# fumaca nele, ANTES de trocar a producao de lugar.
#
#   ./fumaca.sh /root/stoat/branding/dist-nova
#
# Por que servir em vez de testar o site no ar: quando o teste roda depois
# da troca, o build quebrado JA esteve em producao. A 0.36.0 ficou de tela
# branca para quem abriu naquele intervalo. Aqui o candidato nunca chega
# perto do que esta sendo servido.
#
# O container e a MESMA imagem do servico web, com o mesmo .env.web: o
# inject.js precisa trocar os marcadores __VITE_*__ pelas URLs reais, ou o
# app sobe apontando para lugar nenhum e o portao reprovaria por um motivo
# que nao existe em producao.
set -euo pipefail

DIST="${1:?informe o diretorio do build}"
RAIZ=/root/stoat
IMAGEM=ghcr.io/stoatchat/for-web:0c31cf0
NOME=dp-fumaca
REDE=stoat_default
IP_PUBLICO=187.127.57.149

[ -f "$DIST/index.html" ] || { echo "!! $DIST nao parece um build"; exit 1; }

limpar() { docker rm -f "$NOME" >/dev/null 2>&1 || true; }
trap limpar EXIT
limpar

echo "==> servindo o candidato em um container proprio"
# O --add-host resolve o dominio publico de dentro da rede interna: o app
# busca a configuracao em VITE_API_URL, que aponta para chat.doispapo.com.
docker run -d --name "$NOME" --network "$REDE" \
  --add-host "chat.doispapo.com:$IP_PUBLICO" \
  --env-file "$RAIZ/.env.web" \
  -v "$DIST:/app/dist:ro" "$IMAGEM" >/dev/null

# Espera a PORTA atender, nao o container existir. O inject.js roda antes
# de o servidor subir; conferir so a presenca do node fazia o navegador
# chegar em porta fechada e o portao reprovar todo build por engano.
pronto=""
for _ in $(seq 1 60); do
  if docker exec "$NOME" node -e \
      "fetch('http://localhost:5000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" \
      >/dev/null 2>&1; then
    pronto=1; break
  fi
  sleep 1
done
[ -n "$pronto" ] || { echo "!! o candidato nao subiu"; docker logs "$NOME" | tail -20; exit 1; }

echo "==> abrindo no navegador"
# --network container: compartilha a pilha de rede com quem serve, para o
# endereco ser localhost.
#
# Isso NAO e conveniencia. Em http://nome:5000 o navegador nao considera a
# origem um contexto seguro, e as APIs que so existem em contexto seguro
# falham -- o app nao monta e o portao reprovaria TODO build, inclusive os
# bons. Foi o que aconteceu na primeira versao deste script. Origem
# localhost e contexto seguro mesmo sem TLS.
docker run --rm --network "container:$NOME" \
  -v /root/doispapo/branding/fumaca.js:/fumaca.js:ro \
  dp-fumaca:1 \
  node /fumaca.js "http://localhost:5000/"
