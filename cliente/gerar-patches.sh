#!/usr/bin/env bash
# Regenera a serie de patches a partir do fonte editado.
#
#   ./gerar-patches.sh
#
# Sempre `git diff HEAD`, nunca `git diff`. A diferenca importa: o
# construir.sh aplica os patches com `git apply --3way`, que escreve no
# indice. Depois disso `git diff` compara a arvore com os patches JA
# aplicados e devolve apenas a ultima edicao - um patch que parece
# completo, aplica sem erro e produz um cliente sem metade da mudanca.
#
# Um arquivo por patch. Quando o upstream mudar, o `git apply --3way` do
# construir.sh falha apontando o arquivo em conflito, em vez de aplicar
# torto o que sobrou.
set -euo pipefail

FONTE="${FONTE:-/root/dp-web}"
PATCHES="$(cd "$(dirname "$0")" && pwd)/patches"

cd "$FONTE"

# Sem isto, um arquivo criado por nos (ainda sem intent-to-add) nao entra
# no diff e o patch sai sem ele.
git add -N . >/dev/null 2>&1 || true

declare -A SERIE=(
  [0001-estado-de-voz]=packages/client/components/rtc/state.tsx
  [0002-rodape-de-voz]=packages/client/components/ui/components/features/voice/VoiceDock.tsx
  [0003-janela-de-chamada]=packages/client/components/ui/components/features/voice/callCard/VoiceCallCard.tsx
  [0004-controles-da-chamada]=packages/client/components/ui/components/features/voice/callCard/VoiceCallCardActions.tsx
  [0005-grade-da-chamada]=packages/client/components/ui/components/features/voice/callCard/VoiceCallCardActiveRoom.tsx
  [0006-lista-de-canais]=packages/client/src/interface/navigation/channels/ServerSidebar.tsx
  [0007-lista-de-conversas]=packages/client/src/interface/navigation/channels/HomeSidebar.tsx
  [0008-cabecalho-do-canal]=packages/client/src/interface/channels/ChannelHeader.tsx
)

for nome in $(printf '%s\n' "${!SERIE[@]}" | sort); do
  git diff HEAD --no-color -- "${SERIE[$nome]}" > "$PATCHES/$nome.patch"
  printf '  %-32s %s linhas\n' "$nome.patch" \
    "$(grep -c '^[+-]' "$PATCHES/$nome.patch" || true)"
done

# Um arquivo alterado que nao esteja na serie sairia do build sem deixar
# rastro no repositorio - some no proximo construir.sh, que reseta a
# arvore. Melhor avisar agora.
esperados=$(printf '%s\n' "${SERIE[@]}" | sort)
alterados=$(git diff HEAD --name-only | sort)
sobrando=$(comm -13 <(echo "$esperados") <(echo "$alterados"))
if [ -n "$sobrando" ]; then
  echo
  echo "!! alterados e FORA da serie (nao viram patch, serao perdidos):"
  echo "$sobrando" | sed 's/^/     /'
  exit 1
fi
