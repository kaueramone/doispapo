#!/usr/bin/env python3
"""
Prova das garantias de concorrencia de dp_solicitacoes.

Mongo standalone nao tem transacao. O plano inteiro apoia-se em duas coisas
no lugar dela: um indice unico parcial e um compare-and-swap. Este arquivo
existe para provar as duas contra o banco de verdade, e nao contra a leitura
que eu fiz da documentacao.

Usa ids falsos com prefixo 01ZZTESTE e apaga tudo no fim, inclusive se
falhar no meio.

    docker compose cp deploy/convites/teste_solicitacoes.py convites:/teste.py
    docker compose exec -T convites python3 /teste.py
"""
import os
import threading
import time

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

db = MongoClient(os.environ.get("MONGO_URL", "mongodb://database:27017"),
                 serverSelectionTimeoutMS=5000).revolt
COL = db.dp_solicitacoes

SRV = "01ZZTESTE0SERVIDOR00000001"
USR = "01ZZTESTE0USUARIO000000001"
PREFIXO = "01ZZTESTE"

falhas = []


def ok(cond, texto):
    print(("   PASSOU  " if cond else "   FALHOU  ") + texto, flush=True)
    if not cond:
        falhas.append(texto)


def limpa():
    COL.delete_many({"servidor": {"$regex": "^" + PREFIXO}})


def pedir(servidor=SRV, usuario=USR, estado="PENDENTE"):
    """Igual ao que a rota vai fazer: insere e deixa o banco recusar."""
    COL.insert_one({
        "servidor": servidor, "usuario": usuario, "estado": estado,
        "em": time.time(), "mensagem": None,
        "decidido_por": None, "decidido_em": None, "motivo": None,
        "convite": None,
    })


# ---------------------------------------------------------------- 1
def t1_duplicata():
    print("\n1. dois pedidos PENDENTE para o mesmo par")
    limpa()
    pedir()
    try:
        pedir()
        ok(False, "o segundo insert deveria ter sido recusado pelo banco")
    except DuplicateKeyError:
        ok(True, "segundo insert recusado com DuplicateKeyError")
    ok(COL.count_documents({"servidor": SRV}) == 1, "existe exatamente 1 documento")


# ---------------------------------------------------------------- 2
def t2_historico_convive():
    """A unicidade vale SO para PENDENTE -- o historico tem que caber junto."""
    print("\n2. historico convivendo com um pendente novo")
    limpa()
    pedir()
    COL.update_one({"servidor": SRV, "estado": "PENDENTE"},
                   {"$set": {"estado": "REJEITADA"}})
    try:
        pedir()
        ok(True, "pedido novo aceito depois da rejeicao")
    except DuplicateKeyError:
        ok(False, "o indice bloqueou um pedido legitimo apos rejeicao")

    COL.update_one({"servidor": SRV, "estado": "PENDENTE"},
                   {"$set": {"estado": "CANCELADA"}})
    try:
        pedir(estado="REJEITADA")
        pedir(estado="REJEITADA")
        ok(True, "duas rejeicoes do mesmo par convivem (unicidade nao alcanca)")
    except DuplicateKeyError:
        ok(False, "o indice bloqueou documentos fora de PENDENTE")


# ---------------------------------------------------------------- 3
def t3_corrida_criar():
    """Requisito 12: o dedo preso no botao."""
    print("\n3. 20 threads pedindo ao mesmo tempo (dedo preso no botao)")
    limpa()
    largada = threading.Event()
    venceu, recusado, estranho = [], [], []

    def tenta():
        largada.wait()
        try:
            pedir()
            venceu.append(1)
        except DuplicateKeyError:
            recusado.append(1)
        except Exception as e:
            estranho.append(repr(e))

    ts = [threading.Thread(target=tenta) for _ in range(20)]
    [t.start() for t in ts]
    largada.set()
    [t.join() for t in ts]

    print(f"      aceitos={len(venceu)} recusados={len(recusado)} erros={len(estranho)}")
    ok(not estranho, f"nenhum erro inesperado {estranho[:1]}")
    ok(len(venceu) == 1, "exatamente 1 thread conseguiu inserir")
    ok(COL.count_documents({"servidor": SRV}) == 1, "1 documento no banco")


# ---------------------------------------------------------------- 4
def t4_corrida_aprovar():
    """Dois administradores clicando em ACEITAR no mesmo instante."""
    print("\n4. 10 threads aprovando a mesma solicitacao")
    limpa()
    pedir()
    sid = COL.find_one({"servidor": SRV})["_id"]

    largada = threading.Event()
    ganhou, tarde = [], []

    def aprova(i):
        largada.wait()
        d = COL.find_one_and_update(
            {"_id": sid, "estado": "PENDENTE"},
            {"$set": {"estado": "APROVADA",
                      "decidido_por": f"admin{i}",
                      "decidido_em": time.time()}})
        (ganhou if d else tarde).append(i)

    ts = [threading.Thread(target=aprova, args=(i,)) for i in range(10)]
    [t.start() for t in ts]
    largada.set()
    [t.join() for t in ts]

    print(f"      aprovaram={len(ganhou)} chegaram tarde={len(tarde)}")
    ok(len(ganhou) == 1, "exatamente 1 aprovacao passou")
    d = COL.find_one({"_id": sid})
    ok(d["estado"] == "APROVADA", "estado final e APROVADA")
    ok(d["decidido_por"] == f"admin{ganhou[0]}",
       "decidido_por e de quem venceu, e nao foi sobrescrito")


# ---------------------------------------------------------------- 5
def t5_indice_parcial_do_catalogo():
    """Comunidade privada nao pode ser alcancavel pelo indice do catalogo."""
    print("\n5. o indice do catalogo so enxerga comunidade publica")
    plano = db.dp_comunidade.find(
        {"publica": True, "categoria": "games"}
    ).sort([("membros", -1), ("_id", 1)]).explain()

    vencedor = plano["queryPlanner"]["winningPlan"]
    txt = str(vencedor)
    ok("catalogo_por_categoria" in txt,
       "a consulta do catalogo usa catalogo_por_categoria")
    ok("COLLSCAN" not in txt, "nao e varredura de colecao")

    n_no_indice = db.dp_comunidade.count_documents({"publica": True})
    n_total = db.dp_comunidade.count_documents({})
    print(f"      no indice: {n_no_indice} de {n_total} comunidades")
    ok(n_no_indice == 0 and n_total == 3,
       "as 3 comunidades atuais estao fora do indice (todas privadas)")


if __name__ == "__main__":
    print("prova das garantias de dp_solicitacoes")
    try:
        t1_duplicata()
        t2_historico_convive()
        t3_corrida_criar()
        t4_corrida_aprovar()
        t5_indice_parcial_do_catalogo()
    finally:
        limpa()
        resto = COL.count_documents({"servidor": {"$regex": "^" + PREFIXO}})
        print(f"\nlimpeza: {resto} documentos de teste restantes (esperado 0)")
        print(f"dp_solicitacoes: {COL.count_documents({})} documentos (esperado 0)")

    print("\n" + ("TUDO PASSOU" if not falhas else f"{len(falhas)} FALHA(S): {falhas}"))
    raise SystemExit(1 if falhas else 0)
