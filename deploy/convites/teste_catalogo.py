#!/usr/bin/env python3
"""
Teste do catalogo publico.

    docker compose cp deploy/convites/teste_catalogo.py convites:/teste_catalogo.py
    docker compose exec -T convites python3 /teste_catalogo.py

Mesma forma dos outros: segunda instancia na 8699 com dubles no lugar da
sessao. Nao toca em credencial.

Cria 60 comunidades de mentira (prefixo 01ZZCAT) para exercitar a
paginacao por cursor de verdade -- com as 3 comunidades reais nao daria
para ver uma pagina virar, e paginacao errada e o tipo de defeito que so
aparece quando ja tem gente usando. Apaga tudo no fim.
"""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import app

PREFIXO = "01ZZCAT"
N = 60
UID = "01ZZUSUARIODETESTE00000001"

app.usuario_da_sessao = lambda t: UID if t else None

srv = app.Servidor(("127.0.0.1", 8699), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

falhas = []


def confere(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(("  ok    " if ok else "  FALHA ") + rotulo +
          ("" if ok else f": {obtido!r} (esperado {esperado!r})"))
    if not ok:
        falhas.append(rotulo)


def chama(caminho, token="t"):
    h = {}
    if token:
        h["X-Session-Token"] = token
    req = urllib.request.Request("http://127.0.0.1:8699" + caminho, headers=h)
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def sid(i):
    return f"{PREFIXO}{i:019d}"


def limpa():
    app.db.dp_comunidade.delete_many({"_id": {"$regex": "^" + PREFIXO}})
    app.db.servers.delete_many({"_id": {"$regex": "^" + PREFIXO}})
    app.db.dp_solicitacoes.delete_many({"servidor": {"$regex": "^" + PREFIXO}})
    app.db.server_members.delete_many({"_id.server": {"$regex": "^" + PREFIXO}})
    app.db.server_bans.delete_many({"_id.server": {"$regex": "^" + PREFIXO}})


def semeia():
    limpa()
    for i in range(N):
        # Membros deliberadamente EMPATADOS de 3 em 3: o desempate por
        # _id e justamente onde uma paginacao por cursor mal escrita
        # repete ou pula item.
        app.db.servers.insert_one({
            "_id": sid(i), "name": f"Comunidade {i:02d}",
            "description": f"descricao {i}", "owner": "x", "channels": []})
        app.db.dp_comunidade.insert_one({
            "_id": sid(i), "publica": True, "categoria":
                "games" if i % 2 else "musica",
            "tags": ["tarkov"] if i % 5 == 0 else [],
            "nome": f"Comunidade {i:02d}",
            "nome_busca": app.sem_acento(f"Comunidade {i:02d}"),
            "membros": (N - i) // 3, "em": 0})


print(f"semeando {N} comunidades publicas de teste...")
semeia()

try:
    # ============================================ 1. categorias
    print("\n1. GET /catalogo/categorias")
    st, _ = chama("/catalogo/categorias", token=None)
    confere("sem sessao -> 401", st, 401)

    st, b = chama("/catalogo/categorias")
    confere("com sessao -> 200", st, 200)
    porid = {c["id"]: c for c in b["itens"]}
    confere("games conta 30", porid["games"]["comunidades"], 30)
    confere("musica conta 30", porid["musica"]["comunidades"], 30)
    confere("geral conta as 3 reais (privadas) como 0",
            porid["geral"]["comunidades"], 0)
    confere("total bate", b["total"], 60)

    # ============================================ 2. paginacao
    print("\n2. paginacao por cursor")
    st, p1 = chama("/catalogo")
    confere("primeira pagina -> 200", st, 200)
    confere("24 itens por padrao", len(p1["itens"]), 24)
    confere("tem proximo", bool(p1["proximo"]), True)
    confere("ordenado por membros desc",
            p1["itens"][0]["membros"] >= p1["itens"][-1]["membros"], True)

    vistos, cursor, paginas = [], None, 0
    while True:
        st, pg = chama("/catalogo" + (f"?cursor={cursor}" if cursor else ""))
        if st != 200:
            falhas.append(f"pagina devolveu {st}")
            break
        vistos += [i["id"] for i in pg["itens"]]
        paginas += 1
        cursor = pg.get("proximo")
        if not cursor or paginas > 10:
            break
    confere("paginou tudo sem repetir", len(vistos), len(set(vistos)))
    confere("viu as 60", len(vistos), 60)
    confere("3 paginas (24+24+12)", paginas, 3)

    st, b = chama("/catalogo?limite=5")
    confere("limite respeitado", len(b["itens"]), 5)
    st, b = chama("/catalogo?limite=999")
    confere("limite tem teto", len(b["itens"]), app.PAGINA_MAXIMA)

    st, b = chama("/catalogo?cursor=lixo!!!")
    confere("cursor invalido nao estoura -> 200", st, 200)
    confere("cursor invalido comeca do inicio", len(b["itens"]), 24)

    # ============================================ 3. filtro e busca
    print("\n3. filtro e busca")
    st, b = chama("/catalogo?categoria=games&limite=48")
    confere("filtro por categoria", len(b["itens"]), 30)
    confere("so games", {i["categoria"] for i in b["itens"]}, {"games"})

    st, b = chama("/catalogo?categoria=nao%20existe")
    confere("categoria com espaco -> 400", st, 400)

    st, b = chama("/catalogo?q=Comunidade%2007")
    confere("busca por nome", [i["id"] for i in b["itens"]], [sid(7)])
    st, b = chama("/catalogo?q=COMUNIDADE%2007")
    confere("busca ignora maiuscula", len(b["itens"]), 1)
    st, b = chama("/catalogo?q=tarkov&limite=48")
    confere("busca por etiqueta", len(b["itens"]), 12)

    # ============================================ 4. ficha e estado
    print("\n4. ficha da comunidade e estado do botao")
    st, b = chama(f"/catalogo/{sid(3)}", token=None)
    confere("sem sessao -> 401", st, 401)

    st, b = chama(f"/catalogo/{sid(3)}")
    confere("publica -> 200", st, 200)
    confere("estado padrao", b.get("estado"), "disponivel")
    confere("nome vem do servidor", b.get("nome"), "Comunidade 03")
    confere("descricao vem do servidor", b.get("descricao"), "descricao 3")

    app.db.dp_comunidade.update_one({"_id": sid(3)},
                                    {"$set": {"publica": False}})
    st, b = chama(f"/catalogo/{sid(3)}")
    confere("privada -> 404 (nunca 403)", st, 404)
    app.db.dp_comunidade.update_one({"_id": sid(3)},
                                    {"$set": {"publica": True}})

    st, b = chama("/catalogo/01ZZNAOEXISTE00000000000ZZ")
    confere("inexistente -> 404", st, 404)

    app.db.server_members.insert_one({"_id": {"server": sid(4), "user": UID}})
    st, b = chama(f"/catalogo/{sid(4)}")
    confere("ja e membro", b.get("estado"), "membro")
    st, b = chama("/catalogo?limite=48")
    porid = {i["id"]: i for i in b["itens"]}
    confere("a LISTA tambem traz o estado (sem N+1)",
            porid[sid(4)]["estado"], "membro")
    confere("e o estado padrao dos outros", porid[sid(2)]["estado"], "disponivel")

    app.db.server_bans.insert_one({"_id": {"server": sid(5), "user": UID}})
    st, b = chama(f"/catalogo/{sid(5)}")
    confere("banido", b.get("estado"), "banido")

    app.db.dp_solicitacoes.insert_one({
        "servidor": sid(6), "usuario": UID, "estado": "PENDENTE",
        "em": app.time.time()})
    st, b = chama(f"/catalogo/{sid(6)}")
    confere("pendente", b.get("estado"), "pendente")

    agora = app.time.time()
    app.db.dp_solicitacoes.insert_one({
        "servidor": sid(7), "usuario": UID, "estado": "REJEITADA",
        "em": agora - 100, "decidido_em": agora - 100})
    st, b = chama(f"/catalogo/{sid(7)}")
    confere("rejeitado ha pouco -> em carencia", b.get("estado"), "rejeitado")
    confere("diz quando libera", b.get("liberado_em") > agora, True)

    app.db.dp_solicitacoes.update_one(
        {"servidor": sid(7)},
        {"$set": {"decidido_em": agora - app.CARENCIA_REJEICAO - 10}})
    st, b = chama(f"/catalogo/{sid(7)}")
    confere("carencia vencida -> pode pedir de novo",
            b.get("estado"), "disponivel")

    app.db.dp_solicitacoes.insert_one({
        "servidor": sid(8), "usuario": UID, "estado": "CANCELADA",
        "em": agora - 50, "decidido_em": agora - 50})
    st, b = chama(f"/catalogo/{sid(8)}")
    confere("cancelada nao bloqueia", b.get("estado"), "disponivel")

    # ============================================ 5. o indice e usado
    print("\n5. a consulta do catalogo usa indice")
    plano = str(app.db.dp_comunidade.find(
        {"$and": [{"publica": True}, {"categoria": "games"}]}
    ).sort([("membros", -1), ("_id", 1)]).explain()["queryPlanner"]["winningPlan"])
    confere("usa catalogo_por_categoria", "catalogo_por_categoria" in plano, True)
    confere("sem varredura de colecao", "COLLSCAN" not in plano, True)
    confere("sem ordenacao em memoria", "SORT" not in plano, True)

finally:
    limpa()
    print(f"\nlimpeza: {app.db.dp_comunidade.count_documents({'_id': {'$regex': '^' + PREFIXO}})} de teste (esperado 0)")
    print(f"dp_comunidade: {app.db.dp_comunidade.count_documents({})} docs (esperado 3)")
    print(f"publicas: {app.db.dp_comunidade.count_documents({'publica': True})} (esperado 0)")
    print(f"servers: {app.db.servers.count_documents({})} (esperado 3)")

print("\n" + ("TUDO PASSOU" if not falhas else f"{len(falhas)} FALHA(S): {falhas}"))
sys.exit(1 if falhas else 0)
