#!/usr/bin/env python3
"""Confere se todo componente usado em JSX existe no arquivo.

Nasceu de um erro concreto: um `<MdTrophy />` sem import derrubou a tela de
configuracoes inteira. O empacotador nao reclama -- identificador que nao
existe so estoura quando o componente renderiza, e o portao de fumaca abre
o aplicativo, nao cada tela dele.

Uso:  python3 conferir-simbolos.py <arquivos relativos a FONTE>
"""
import os
import re
import sys

RAIZ = os.environ.get("FONTE", "/root/dp-web")

# Codigo comentado nao renderiza. Sem tirar os comentarios, metade do que
# o verificador acusa e exemplo desligado -- e um verificador barulhento e
# um verificador ignorado.
COMENTARIO_BLOCO = re.compile(r"/\*.*?\*/", re.S)
COMENTARIO_LINHA = re.compile(r"^\s*//.*$", re.M)

# `<Nome` precedido de letra, `.` ou `>` e generico de TypeScript
# (`Accessor<State>`, `Setter<HTMLDivElement>`), nao JSX.
USO = re.compile(r"(?<![A-Za-z0-9_.>])<([A-Z][A-Za-z0-9_]*)(?:\.[A-Za-z0-9_]+)*[\s/>]")


def declarados(fonte):
    nomes = set()
    for m in re.finditer(r"import\s+(?:type\s+)?([^;]+?)\s+from\s", fonte):
        for parte in re.split(r"[{},]", m.group(1)):
            parte = re.sub(r"^\*\s+as\s+", "", parte.strip())
            parte = re.split(r"\s+as\s+", parte)[-1].strip()
            if parte and parte != "*":
                nomes.add(parte)
    nomes.update(re.findall(
        r"(?:const|let|var|function|class)\s+([A-Za-z0-9_]+)", fonte))
    return nomes


faltando = []
for caminho in sys.argv[1:]:
    inteiro = os.path.join(RAIZ, caminho)
    if not inteiro.endswith((".tsx", ".jsx")) or not os.path.exists(inteiro):
        continue
    bruto = open(inteiro, encoding="utf-8").read()
    fonte = COMENTARIO_LINHA.sub("", COMENTARIO_BLOCO.sub("", bruto))
    tem = declarados(bruto)
    for nome in sorted(set(USO.findall(fonte))):
        if nome not in tem:
            faltando.append((caminho, nome))

if faltando:
    print("!! componente usado em JSX sem declaracao no arquivo:")
    for caminho, nome in faltando:
        print("     %-64s <%s>" % (caminho, nome))
    raise SystemExit(1)
print("   simbolos conferidos: todo componente JSX existe")
