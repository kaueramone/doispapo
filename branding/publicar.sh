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

# Conferimos o que o servidor entrega batendo direto no endereco dele,
# sem depender de cache de DNS. O endereco e resolvido agora: dado de
# infraestrutura nao entra no repositorio (ver CLAUDE.md).
IP_CHAT=$(getent hosts chat.doispapo.com | awk '{print $1; exit}')
[ -n "$IP_CHAT" ] || { echo "!! nao resolvi chat.doispapo.com"; exit 1; }

# Publicar derruba quem esta em chamada.
#
# O service worker novo assume e manda as abas abertas recarregarem --
# isso e o que faz a correcao chegar sem ninguem precisar apertar nada.
# Quem esta falando nesse instante cai no meio da frase.
#
# Descoberto do jeito ruim: a 0.43.0 subiu com cinco pessoas numa
# chamada. A serie de metricas ja sabia disso; era so perguntar.
#
# Para publicar assim mesmo (correcao urgente vale mais que a chamada):
#   FORCAR=1 branding/publicar.sh
EM_CHAMADA=$(cd "$RAIZ" && docker compose exec -T painel python3 -c "
import os, time
from pymongo import MongoClient
db = MongoClient(os.environ.get('MONGO_URL','mongodb://database:27017')).revolt
d = db.dp_metricas.find_one(sort=[('em', -1)])
# Amostra velha nao diz nada sobre agora.
print(int((d or {}).get('sfu', {}).get('participantes') or 0)
      if d and time.time() - d['em'] < 120 else 0)
" 2>/dev/null | tr -dc '0-9')

if [ "${EM_CHAMADA:-0}" -gt 0 ] && [ -z "${FORCAR:-}" ]; then
  echo "!! $EM_CHAMADA pessoa(s) em chamada agora."
  echo "   Publicar recarrega as abas abertas e derruba quem esta falando."
  echo "   Para publicar assim mesmo:  FORCAR=1 $0"
  exit 1
fi

cd "$BR"

# Referencia de reproducao. Nao e mais a entrada do rebrand: serve para o
# construir.sh conferir que um build SEM patch sai identico a imagem
# publicada - a garantia de que a troca de pipeline nao mudou nada por
# conta propria.
if [ ! -d dist-orig ]; then
  echo "==> extraindo build original do container"
  docker cp stoat-web-1:/app/dist ./dist-orig
fi

# Ate a 0.32 a entrada era o dist-orig: a imagem pronta do registry, com
# nossas alteracoes aplicadas por regex sobre o bundle minificado. Isso
# servia para remendo cirurgico e nao serve para layout - mover
# componente de lugar por expressao regular nao sobrevive a nenhum
# upgrade. Agora o cliente e compilado do fonte, com os patches em
# cliente/patches, e o rebrand continua fazendo o que sempre fez por cima.
echo "==> compilando o cliente a partir do fonte"
/root/doispapo/cliente/construir.sh

echo "==> montando o build novo (fora do ar)"
rm -rf dist-nova
python3 "$FONTE/rebrand.py" dist-fonte dist-nova

echo
echo "==> conferindo o build antes de publicar"
python3 "$FONTE/verificar.py" dist-nova

for b in dist-nova/assets/index-*.js; do
  docker run --rm --entrypoint node -v "$BR/dist-nova/assets":/w:ro -w /w \
    ghcr.io/stoatchat/for-web:0c31cf0 --check "$(basename "$b")"
done
echo "  bundle passou no node --check"

# Portao de fumaca: um navegador de verdade abre ESTE build e confere que
# o aplicativo monta sem erro nao tratado.
#
# O verificar.py confere estrutura e o node --check confere sintaxe --
# nenhum dos dois EXECUTA nada. A 0.36.0 passou nos dois e derrubou a
# producao: um ciclo de importacao deixava uma variavel na zona morta
# temporal, o modulo estourava na inicializacao e a tela ficava branca.
#
# Roda ANTES da troca, contra um container separado. Testar o site depois
# de publicar tambem detectaria, mas so depois de o build quebrado ja ter
# sido servido a quem abrisse naquele intervalo.
echo
echo "==> portao de fumaca (o aplicativo sobe?)"
"$FONTE/fumaca.sh" "$BR/dist-nova"

# Quando chamado pelo lancar.sh, confere o numero de versao carimbado no
# bundle ANTES da troca. A versao vem de `git describe` lido na geracao;
# um build feito antes da tag sai com o numero anterior. Barrar aqui evita
# publicar uma versao mentindo sobre si mesma.
if [ -n "${VERSAO_ESPERADA:-}" ]; then
  # Dois `grep -o` encadeados picam a linha minificada em pedacos e
  # devolvem lixo; extrair o grupo de uma vez e o unico jeito confiavel.
  #
  # NAO procure pelo nome da constante. A versao anterior casava
  # `const dW="..."`, e `dW` era so o nome que o minificador tinha
  # sorteado naquele build. Assim que o bundle passou a ser compilado do
  # fonte com codigo nosso dentro, o mesmo valor virou `uW` e a
  # conferencia nao achou nada - reprovando um build que estava
  # perfeitamente carimbado.
  #
  # O que nao depende de sorteio e a forma: uma constante com o numero,
  # e um objeto logo em seguida que a usa como `version`. E isso que
  # ancora a busca; os nomes ficam por conta do grupo de captura.
  BAKED=$(python3 - <<'EOF'
import re, glob
padrao = re.compile(r'const\s+([A-Za-z_$][\w$]*)\s*=\s*"([0-9][0-9.]*)"\s*,'
                    r'\s*[A-Za-z_$][\w$]*\s*=\s*\{\s*version\s*:\s*\1\b')
for f in sorted(glob.glob('dist-nova/assets/index-*.js')):
    m = padrao.search(open(f, encoding='utf-8', errors='replace').read())
    if m:
        print(m.group(2)); break
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
  curl -sf --resolve "chat.doispapo.com:443:$IP_CHAT" \
    https://chat.doispapo.com/versao.json -o /dev/null && break
  sleep 1
done

SERVIDA=$(curl -s --resolve "chat.doispapo.com:443:$IP_CHAT" \
          https://chat.doispapo.com/versao.json | python3 -c \
          'import json,sys;print(json.load(sys.stdin)["build"])')

# Confere o que o servidor REALMENTE entrega, nao o que esta em disco.
TMP=$(mktemp)
curl -s --resolve "chat.doispapo.com:443:$IP_CHAT" \
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
