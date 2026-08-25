#!/usr/bin/env python3
"""Le a serie de condicoes e mostra onde os quadros somem.

Roda DENTRO do container `convites`, que e quem alcanca o Mongo:

    docker exec -i stoat-convites-1 python3 - < rede/olhar-condicoes.py
    docker exec -i stoat-convites-1 python3 - < rede/olhar-condicoes.py 60

O argumento e a janela em minutos (padrao 30).

POR QUE ESTA FERRAMENTA EXISTE

O `amostrar-condicoes.sh` batia no `/condicoes` a cada dez segundos e
imprimia o que estava la naquele instante. Isso tinha dois furos que
custaram caro na auditoria:

  1. Ele lia mais rapido do que o cliente escrevia, entao a mesma medicao
     aparecia varias vezes -- 45 das 604 linhas da serie de 24/08 eram
     repeticao. Contar linhas em vez de medicoes distintas inflava a
     amostra sem que nada avisasse.
  2. So existia o lado de quem TRANSMITE. Recepcao, decodificacao e
     renderizacao nunca tiveram numero, e "travou" nao tinha como ser
     confirmado nem descartado.

Agora ha historico de verdade no banco (`dp_condicoes_serie`, com TTL de
tres dias) e os dois lados relatam. Esta ferramenta le esse historico.

COMO LER

A tabela segue o caminho do quadro, e a pergunta e sempre a mesma: qual e
o PRIMEIRO ponto onde 30 deixa de ser 30?

    captura   quadros que o navegador arranca da tela
    envio     quadros que o codificador entrega ao WebRTC
    ---------------------------------------------------- (o SFU fica no meio)
    decodif.  quadros que o decodificador de quem assiste produziu
    na tela   quadros que viraram IMAGEM (requestVideoFrameCallback)

`captura ~= envio` e o codificador acompanhando a origem: o gargalo esta
ANTES, na captura. `captura` alta com `envio` baixo poe a culpa no
codificador ou na banda -- e ai `limite` e `ms/quadro` dizem qual dos
dois. `decodif.` alto com `na tela` baixo tira a rede da historia por
completo: os quadros chegaram e o navegador de quem assiste nao os
desenhou.
"""
import os, sys, time
from collections import defaultdict

from pymongo import MongoClient

JANELA_MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 30

db = MongoClient(os.environ.get("MONGO_URL", "mongodb://database:27017")).revolt
desde = int(time.time()) - JANELA_MIN * 60

amostras = list(db.dp_condicoes_serie.find({"em": {"$gte": desde}}).sort("em", 1))
if not amostras:
    print(f"nenhuma amostra nos ultimos {JANELA_MIN} min.")
    print("A serie so tem conteudo enquanto alguem compartilha tela.")
    sys.exit(0)


def mediana(xs):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def n(v, casas=0):
    if v is None:
        return "-"
    return f"{v:.{casas}f}"


grupos = defaultdict(list)
for a in amostras:
    grupos[(a.get("usuario"), a.get("papel"), a.get("faixa"))].append(a)

print(f"janela: {JANELA_MIN} min · {len(amostras)} amostras · "
      f"{len(grupos)} fluxo(s)\n")

for (uid, papel, faixa), v in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
    dur = (v[-1]["em"] - v[0]["em"]) / 60.0
    print("=" * 74)
    print(f"{uid[:10]}  {papel:9s}  faixa {faixa or '-':18s}  "
          f"{len(v)} amostras · {dur:.0f} min")

    if papel == "transmite":
        cap = mediana([a.get("capturaFps") for a in v])
        env = mediana([a.get("fps") for a in v])
        ms = mediana([a.get("msQuadro") for a in v])
        print(f"  captura {n(cap):>5s} fps   ->   envio {n(env):>5s} fps"
              f"   ({n(ms,1)} ms/quadro)")

        # `segCpu`/`segBanda` sao ACUMULADOS desde o inicio da faixa. So a
        # diferenca entre a primeira e a ultima amostra significa algo: um
        # valor alto numa leitura isolada e a soma de uma sessao inteira.
        dcpu = (v[-1].get("segCpu") or 0) - (v[0].get("segCpu") or 0)
        dban = (v[-1].get("segBanda") or 0) - (v[0].get("segBanda") or 0)
        limites = {a.get("limite") for a in v if a.get("limite")}
        print(f"  segurado por processador: {dcpu:.0f}s · por banda: {dban:.0f}s"
              f" · motivos vistos: {', '.join(sorted(limites)) or 'nenhum'}")

        b = v[-1].get("bruto") or {}
        cl, ca = b.get("capturaLargura"), b.get("capturaAltura")
        tl, ta = b.get("telaLargura"), b.get("telaAltura")
        sup = b.get("superficie") or "?"
        pedida = b.get("capturaPedida")
        print(f"  captura {n(cl)}x{n(ca)} @ {n(pedida)} pedidos · "
              f"monitor {n(tl)}x{n(ta)} · superficie: {sup}")

        # O teste da hipotese principal, e ele precisa de cuidado.
        #
        # Comparar a captura com o MONITOR so vale quando a superficie e o
        # monitor. Numa janela, a fonte e a janela -- que pode legitimamente
        # ser menor que a tela, e ai "monitor maior que captura" nao prova
        # reducao nenhuma. O que prova, nos dois casos, e a largura da
        # captura bater EXATAMENTE no teto pedido: fonte menor que o teto
        # sai no tamanho dela, entao largura igual ao teto significa que
        # havia mais pixel do que coube e o navegador reduziu cada quadro.
        TETO = {"low": 1280, "high": 1920}
        if cl and cl in TETO.values():
            print(f"  ^ a captura saiu com largura EXATAMENTE no teto pedido "
                  f"({n(cl)}px): a fonte e maior e o navegador esta reduzindo")
            print(f"    cada quadro dentro do caminho de captura, antes de "
                  f"chegar ao codificador.")
        elif cl and tl and sup == "monitor" and tl > cl:
            print(f"  ^ monitor {n(tl)}px capturado a {n(cl)}px: reducao "
                  f"dentro do caminho de captura")

        print(f"  camadas ativas: {n(b.get('camadas'))} · "
              f"motor: {v[-1].get('motor') or '?'} · "
              f"codec: {v[-1].get('codec') or '?'} · "
              f"app: {bool(v[-1].get('app'))}")
        motor = (v[-1].get("motor") or "").lower()
        if motor and not any(x in motor for x in
                             ("mediafoundation", "nvenc", "d3d11", "external",
                              "vaapi", "quicksync")):
            print(f"    ^ '{v[-1].get('motor')}' e codificador de SOFTWARE. "
                  f"O de hardware nao pegou.")

        pausadas = sum(1 for a in v if a.get("pausado"))
        if pausadas:
            print(f"  pausado em {pausadas}/{len(v)} amostras "
                  f"(ninguem assinando -- economia, nao defeito)")
            # Armadilha nova, criada pela camada unica: com a faixa pausada
            # o Chrome zera o bitrate alvo e passa a declarar
            # `qualityLimitationReason: bandwidth`. Lido de frente, isso
            # manda a proxima investigacao atras de uma congestao que nao
            # existe -- e com uma camada so, `pausado` acontece o tempo
            # todo que ninguem estiver assistindo.
            banda_pausada = sum(1 for a in v
                                if a.get("pausado") and a.get("limite") == "banda")
            if banda_pausada and banda_pausada >= pausadas * 0.8:
                print(f"    ^ IGNORE o 'banda' acima: {banda_pausada} das "
                      f"{pausadas} amostras pausadas o declaram. Faixa pausada")
                print(f"      tem bitrate alvo zero, e o navegador chama isso "
                      f"de limitacao por banda. Nao e congestao.")
            if pausadas >= len(v) * 0.8:
                print(f"    ^ com quase tudo pausado, o unico numero valido "
                      f"aqui e a CAPTURA. Encoder, envio e SFU nao foram")
                print(f"      exercitados: e preciso alguem ASSISTINDO para "
                      f"medir o resto do caminho.")
    else:
        dec = mediana([a.get("decodeFps") for a in v])
        ren = mediana([a.get("renderFps") for a in v])
        rec = mediana([a.get("fps") for a in v])
        print(f"  recebido {n(rec):>5s} fps   ->   decodificado {n(dec):>5s} fps"
              f"   ->   NA TELA {n(ren):>5s} fps")
        larg = sum(a.get("largados") or 0 for a in v)
        trav = sum(a.get("travadas") or 0 for a in v)
        buf = mediana([a.get("msBuffer") for a in v])
        perda = mediana([a.get("perda") for a in v])
        print(f"  largados: {larg:.0f} · travou: {trav:.0f}x · "
              f"buffer {n(buf,0)} ms · perda {n(perda,2)}%")
        b = v[-1].get("bruto") or {}
        print(f"  exibido em {n(b.get('exibeLargura'))}x{n(b.get('exibeAltura'))}"
              f" · decodificador: {v[-1].get('motor') or '?'}"
              f" · codec: {v[-1].get('codec') or '?'}")
        # Um quadro pequeno recebendo 360p nao e defeito: e o adaptiveStream
        # pedindo a camada do tamanho do elemento. Vale dizer isso aqui para
        # a leitura nao virar alarme falso.
        if dec and ren and dec - ren >= 3:
            print(f"  ^ decodificou {n(dec)} e desenhou {n(ren)}: "
                  f"a perda esta na EXIBICAO, nao na rede")

print("=" * 74)
print("\nO SFU fica entre os dois blocos. Para ver o lado dele:")
print("  docker exec -i stoat-convites-1 python3 - < rede/olhar-salas.py")
print("  docker logs stoat-livekit-1 --since 30m | grep rtpStats | tail -1")
