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
# Calculado ANTES do cd. Com `dirname "$0"` relativo, tudo que dependesse
# dele depois do `cd "$FONTE"` ia procurar dentro do fonte e nao achar --
# foi assim que o conferidor de simbolos deixou de rodar calado.
AQUI="$(cd "$(dirname "$0")" && pwd)"
PATCHES="$AQUI/patches"

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
  [0009-chat-sem-avisos-do-sistema]=packages/client/components/app/interface/channels/text/Messages.tsx
  [0010-busca-de-gif]=packages/client/components/ui/components/features/messaging/composition/picker/GifPicker.tsx
  [0011-comentarios]=packages/client/components/app/interface/settings/user/Feedback.tsx
  [0012-novidades]=packages/client/components/app/interface/settings/user/Novidades.tsx
  [0013-menu-de-configuracoes]=packages/client/components/app/interface/settings/UserSettings.tsx
  [0014-sem-experimentos-vazios]=packages/client/components/state/stores/Experiments.ts
  [0015-membros-online]=packages/client/src/interface/channels/text/MemberSidebar.tsx
  [0016-conversas-diretas]=packages/client/src/interface/navigation/channels/HomeSidebar.tsx
  [0017-pedidos-de-amizade]=packages/client/src/interface/navigation/servers/ServerList.tsx
  [0018-acoes-do-perfil]=packages/client/components/ui/components/features/profiles/ProfileActions.tsx
  [0019-entrada-imediata]=packages/client/components/ui/components/features/voice/VoiceChannelPreview.tsx
  [0020-destacar-janela]=packages/client/components/ui/components/features/voice/destacar.ts
  [0021-quadro-destacavel]=packages/client/components/ui/components/features/voice/callCard/ParticipantTile.tsx
  [0022-menu-com-extras]=packages/client/components/app/menus/UserContextMenu.tsx
  [0023-audio-de-tela-audivel]=packages/client/components/state/stores/Voice.ts
  [0024-selo-ao-vivo]=packages/client/components/ui/components/features/voice/VoiceStatefulUserIcons.tsx
  [0026-faixa-de-presenca]=packages/client/components/ui/components/features/voice/FaixaDePresenca.tsx
  [0027-linha-de-entrada]=packages/client/components/ui/components/features/voice/callCard/VoiceCallCardPreview.tsx
  [0028-canal-de-texto]=packages/client/src/interface/channels/text/TextChannel.tsx
  [0029-traducoes-pt-br]=packages/client/components/i18n/catalogs/pt-BR/messages.po
  [0030-item-de-menu]=packages/client/components/ui/components/design/MenuButton.tsx
  [0031-tema-web]=packages/client/components/ui/themes/stoatWebTheme.ts
  [0032-marca-carregando]=packages/client/components/ui/components/utils/MarcaCarregando.tsx
  [0033-tela-de-carregamento]=packages/client/src/LoadingScreen.tsx
  [0034-entrada-do-app]=packages/client/src/Interface.tsx
  [0035-barra-de-titulo]=packages/client/components/app/interface/desktop/Titlebar.tsx
  [0036-conquistas]=packages/client/components/app/interface/settings/user/Conquistas.tsx
  [0037-arrastar-usuario]=packages/client/components/ui/components/features/voice/arrastar-usuario.ts
  [0039-porta-de-entrada]=packages/client/components/auth/src/AuthPage.tsx
  [0040-cartao-do-fluxo]=packages/client/components/auth/src/flows/Flow.tsx
  [0041-criar-conta]=packages/client/components/auth/src/flows/FlowCreate.tsx
  [0038-palco-movel]=packages/client/components/ui/components/features/voice/callCard/VoiceCallCardActiveRoom.tsx
  [0042-folga-de-reproducao]=packages/client/components/ui/components/features/voice/folga.ts
  [0043-audio-da-sala]=packages/client/components/rtc/components/RoomAudioManager.tsx
  [0044-vitrine-da-comunidade]=packages/client/components/app/interface/settings/server/Vitrine.tsx
  [0045-visao-geral-com-vitrine]=packages/client/components/app/interface/settings/server/Overview.tsx
  [0046-fila-de-solicitacoes]=packages/client/components/app/interface/settings/server/Solicitacoes.tsx
  [0047-abas-do-servidor]=packages/client/components/app/interface/settings/ServerSettings.tsx
  [0048-catalogo]=packages/client/src/interface/Descobrir.tsx
  [0049-rotas]=packages/client/src/index.tsx
  [0050-tela-inicial]=packages/client/src/interface/Home.tsx
)

for nome in $(printf '%s\n' "${!SERIE[@]}" | sort); do
  git diff HEAD --no-color -- "${SERIE[$nome]}" > "$PATCHES/$nome.patch"
  printf '  %-32s %s linhas\n' "$nome.patch" \
    "$(grep -c '^[+-]' "$PATCHES/$nome.patch" || true)"
done

# Um arquivo alterado que nao esteja na serie sairia do build sem deixar
# rastro no repositorio - some no proximo construir.sh, que reseta a
# arvore. Melhor avisar agora.
# Componente usado em JSX sem existir no arquivo passa pelo empacotador
# calado e so estoura quando aquela tela renderiza -- um `<MdTrophy />`
# sem import derrubou as configuracoes inteiras. Aqui e barato conferir.
FONTE="$FONTE" python3 "$AQUI/conferir-simbolos.py" "${SERIE[@]}"

esperados=$(printf '%s\n' "${SERIE[@]}" | sort)

# Os sons entram por COPIA no construir.sh, nao por patch -- sao binarios, e
# `git diff` os reduz a "Binary files differ", que o `git apply` nao aplica.
# Aparecem aqui como alterados a cada build; sem esta excecao, o aviso de
# "fora da serie" dispara sempre, e um aviso que sempre dispara e um aviso
# que ninguem le mais.
alterados=$(git diff HEAD --name-only \
            | grep -v '^packages/client/scripts/assets_fallback/sounds/' \
            | sort)
sobrando=$(comm -13 <(echo "$esperados") <(echo "$alterados"))
if [ -n "$sobrando" ]; then
  echo
  echo "!! alterados e FORA da serie (nao viram patch, serao perdidos):"
  echo "$sobrando" | sed 's/^/     /'
  exit 1
fi
