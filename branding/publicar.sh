#!/usr/bin/env bash
# Aplica a marca sobre o build do cliente e publica de forma atomica.
#
# A versao anterior gerava os arquivos DENTRO do diretorio que o container
# servia ao vivo. Cada publicacao truncava o index.html para zero byte e o
# reescrevia com a producao no ar; quem carregasse a pagina nesse intervalo
# recebia um arquivo pela metade, o service worker guardava aquilo e o
# navegador passava a exibir o codigo dos scripts como texto na tela, sem
# que nenhuma correcao no servidor alcancasse aquele cliente.
#
# Agora o build inteiro e montado num diretorio novo, conferido enquanto
# ainda esta fora do ar, e so entao trocado de lugar. Em nenhum momento
# existe um estado pela metade sendo servido.
set -euo pipefail

RAIZ=/root/stoat
BR=$RAIZ/branding
FONTE=/root/doispapo/branding

cd "$BR"

if [ ! -d dist-orig ]; then
  echo "==> extraindo build original do container"
  docker cp stoat-web-1:/app/dist ./dist-orig
fi

echo "==> montando o build novo (fora do ar)"
rm -rf dist-nova
python3 "$FONTE/rebrand.py" dist-orig dist-nova

echo
echo "==> conferindo o build antes de publicar"
python3 "$FONTE/verificar.py" dist-nova

for b in dist-nova/assets/index-*.js; do
  docker run --rm --entrypoint node -v "$BR/dist-nova/assets":/w:ro -w /w \
    ghcr.io/stoatchat/for-web:0c31cf0 --check "$(basename "$b")"
done
echo "  bundle passou no node --check"

# Quando chamado pelo lancar.sh, confere o numero de versao carimbado no
# bundle ANTES da troca. A versao vem de `git describe` lido na geracao;
# um build feito antes da tag sai com o numero anterior. Barrar aqui evita
# publicar uma versao mentindo sobre si mesma.
if [ -n "${VERSAO_ESPERADA:-}" ]; then
  # Dois `grep -o` encadeados picam a linha minificada em pedacos e
  # devolvem lixo; extrair o grupo de uma vez e o unico jeito confiavel.
  BAKED=$(python3 - <<'EOF'
import re, glob
for f in sorted(glob.glob('dist-nova/assets/index-*.js')):
    m = re.search(r'const dW="([0-9][0-9.]*)"',
                  open(f, encoding='utf-8', errors='replace').read())
    if m:
        print(m.group(1)); break
EOF
)
  if [ "$BAKED" != "$VERSAO_ESPERADA" ]; then
    echo "!! build carimbado com '${BAKED:-nada}', esperado '$VERSAO_ESPERADA'"
    echo "   nada foi publicado; a producao segue intacta"
    exit 1
  fi
  echo "  build carimbado com $BAKED"
fi

VERSAO=$(python3 -c "import json;print(json.load(open('dist-nova/versao.json'))['build'])")
echo
echo "==> versao do build: $VERSAO"

echo "==> trocando (atomico)"
rm -rf dist-antiga
[ -d dist-patched ] && mv dist-patched dist-antiga
mv dist-nova dist-patched

cd "$RAIZ"
docker compose restart web >/dev/null

echo "==> aguardando subir"
for _ in $(seq 1 60); do
  curl -sf --resolve chat.doispapo.com:443:187.127.57.149 \
    https://chat.doispapo.com/versao.json -o /dev/null && break
  sleep 1
done

SERVIDA=$(curl -s --resolve chat.doispapo.com:443:187.127.57.149 \
          https://chat.doispapo.com/versao.json | python3 -c \
          'import json,sys;print(json.load(sys.stdin)["build"])')

# Confere o que o servidor REALMENTE entrega, nao o que esta em disco.
TMP=$(mktemp)
curl -s --resolve chat.doispapo.com:443:187.127.57.149 \
     https://chat.doispapo.com/ -o "$TMP"
LOCAL=$(md5sum "$BR/dist-patched/index.html" | cut -d' ' -f1)
NOAR=$(md5sum "$TMP" | cut -d' ' -f1)
rm -f "$TMP"

if [ "$SERVIDA" != "$VERSAO" ] || [ "$LOCAL" != "$NOAR" ]; then
  echo
  echo "!! PUBLICACAO REPROVADA — revertendo"
  echo "   versao esperada=$VERSAO no ar=$SERVIDA"
  echo "   index.html disco=$LOCAL entregue=$NOAR"
  cd "$BR"
  rm -rf dist-falhou && mv dist-patched dist-falhou
  mv dist-antiga dist-patched
  cd "$RAIZ" && docker compose restart web >/dev/null
  echo "   revertido; o build reprovado ficou em $BR/dist-falhou"
  exit 1
fi

echo
echo "==> no ar: $VERSAO — o que o servidor entrega confere com o disco"
echo "    versao anterior guardada em $BR/dist-antiga (para reverter)"
echo
echo "Abas abertas sao recarregadas pelo proprio service worker assim que"
echo "ele ativa. Quem recarregar a pagina atualiza na hora."
