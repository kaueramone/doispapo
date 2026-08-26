#!/usr/bin/env python3
"""
Teste das rotas de solicitacao de entrada.

    docker compose cp deploy/convites/teste_solicitacoes_rotas.py convites:/t.py
    docker compose exec -T convites python3 /t.py

Segunda instancia na 8699, dubles no lugar da sessao e da permissao.
Nao toca em credencial e nao cria convite de verdade: `_api_stoat` e
substituido por um duble que REGISTRA o que seria chamado -- e isso e
proposital, porque o que precisa ser provado aqui e a ORDEM das
operacoes e a limpeza do convite orfao, nao o HTTP.

A chamada real a `POST /channels/{id}/invites` fica para a fase 5, onde
existe sessao de verdade no navegador.
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import app

P = "01ZZSOL"
SRV = P + "0000000000000000001"
SRV2 = P + "0000000000000000002"
CANAL = P + "000000000000000CANAL"[:19].upper()
PEDINTE = P + "00000000000000PEDE1"
ADMIN = P + "0000000000000ADMIN1"

sessao = {"uid": PEDINTE}
perm = {"valor": app.CONCEDE_TUDO}
app.usuario_da_sessao = lambda t: sessao["uid"] if t else None
app.permissao_no_servidor = lambda uid, sid: perm["valor"]

# Duble da API do Stoat: registra as chamadas e devolve codigo unico.
chamadas = []
trava_dub = threading.Lock()


def _duble(metodo, caminho, token, corpo=None):
    with trava_dub:
        chamadas.append((metodo, caminho))
        n = len([c for c in chamadas if c[0] == "POST"])
    return 200, {"_id": f"COD{n:05d}"}


app._api_stoat = _duble

srv = app.Servidor(("127.0.0.1", 8699), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

falhas = []


def confere(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(("  ok    " if ok else "  FALHA ") + rotulo +
          ("" if ok else f": {obtido!r} (esperado {esperado!r})"))
    if not ok:
        falhas.append(rotulo)


def chama(metodo, caminho, corpo=None, token="t"):
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Session-Token"] = token
    req = urllib.request.Request(
        "http://127.0.0.1:8699" + caminho, method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers=h)
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def limpa():
    for c in (app.db.dp_comunidade, app.db.servers):
        c.delete_many({"_id": {"$regex": "^" + P}})
    app.db.channels.delete_many({"_id": {"$regex": "^" + P}})
    app.db.users.delete_many({"_id": {"$regex": "^" + P}})
    app.db.dp_solicitacoes.delete_many({"servidor": {"$regex": "^" + P}})
    app.db.dp_solicitacoes.delete_many({"usuario": {"$regex": "^" + P}})
    app.db.server_members.delete_many({"_id.server": {"$regex": "^" + P}})
    app.db.server_bans.delete_many({"_id.server": {"$regex": "^" + P}})


def semeia():
    limpa()
    for sid in (SRV, SRV2):
        app.db.servers.insert_one({
            "_id": sid, "name": "Comunidade de teste", "owner": ADMIN,
            "channels": [CANAL]})
        app.db.dp_comunidade.insert_one({
            "_id": sid, "publica": True, "categoria": "games", "tags": [],
            "nome": "Comunidade de teste", "nome_busca": "comunidade de teste",
            "membros": 1, "em": 0})
    app.db.channels.insert_one({
        "_id": CANAL, "channel_type": "TextChannel", "server": SRV,
        "name": "chat"})
    app.db.users.insert_one({"_id": PEDINTE, "username": "pedinte",
                             "discriminator": "0001"})
    app.db.users.insert_one({"_id": ADMIN, "username": "admin",
                             "discriminator": "0002"})


semeia()
try:
    # ============================================ 1. criar
    print("\n1. criar solicitacao")
    sessao["uid"] = PEDINTE
    st, _ = chama("POST", "/solicitacoes", {"servidor": SRV}, token=None)
    confere("sem sessao -> 401", st, 401)
    st, b = chama("POST", "/solicitacoes", {"servidor": "nao-e-ulid"})
    confere("servidor invalido -> 400", st, 400)
    st, b = chama("POST", "/solicitacoes", {"servidor": "01ZZINEXISTENTE000000000ZZ"})
    confere("inexistente -> 404", st, 404)

    app.db.dp_comunidade.update_one({"_id": SRV2}, {"$set": {"publica": False}})
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV2})
    confere("privada -> 404 (nunca 403)", st, 404)
    app.db.dp_comunidade.update_one({"_id": SRV2}, {"$set": {"publica": True}})

    st, b = chama("POST", "/solicitacoes",
                  {"servidor": SRV, "mensagem": "  oi, quero entrar  "})
    confere("pedido criado -> 200", st, 200)
    confere("nasce PENDENTE", b.get("estado"), "PENDENTE")
    sol_id = b["id"]
    d = app.db.dp_solicitacoes.find_one({"servidor": SRV, "usuario": PEDINTE})
    confere("mensagem guardada sem espaco", d.get("mensagem"), "oi, quero entrar")
    confere("convite ainda vazio", d.get("convite"), None)

    st, b = chama("POST", "/solicitacoes", {"servidor": SRV})
    confere("pedir de novo -> 409", st, 409)
    confere("erro nomeado", b.get("erro"), "ja_solicitado")

    # ============================================ 2. guardas de estado
    print("\n2. guardas de estado")
    app.db.server_members.insert_one({"_id": {"server": SRV2, "user": PEDINTE}})
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV2})
    confere("ja e membro -> 409", st, 409)
    confere("erro nomeado", b.get("erro"), "ja_e_membro")
    app.db.server_members.delete_many({"_id.server": SRV2})

    app.db.server_bans.insert_one({"_id": {"server": SRV2, "user": PEDINTE}})
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV2})
    confere("banido -> 403", st, 403)
    confere("mensagem neutra (nao diz 'banido')",
            "banid" not in (b.get("mensagem") or "").lower(), True)
    app.db.server_bans.delete_many({"_id.server": SRV2})

    agora = time.time()
    app.db.dp_solicitacoes.insert_one({
        "servidor": SRV2, "usuario": PEDINTE, "estado": "REJEITADA",
        "em": agora - 10, "decidido_em": agora - 10})
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV2})
    confere("em carencia -> 429", st, 429)
    confere("diz quando libera", b.get("liberado_em") > agora, True)
    app.db.dp_solicitacoes.delete_many({"servidor": SRV2})

    # ============================================ 3. tetos
    print("\n3. tetos")
    for i in range(app.TETO_PENDENTES):
        app.db.dp_solicitacoes.insert_one({
            "servidor": f"{P}00000000000000TETO{i}", "usuario": PEDINTE,
            "estado": "PENDENTE", "em": time.time()})
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV2})
    confere("estourou pendentes -> 429", st, 429)
    confere("erro nomeado", b.get("erro"), "muitos_pendentes")
    app.db.dp_solicitacoes.delete_many({"servidor": {"$regex": "TETO"}})

    for i in range(app.TETO_PEDIDOS_DIA):
        app.db.dp_solicitacoes.insert_one({
            "servidor": f"{P}0000000000000DIA{i:03d}", "usuario": PEDINTE,
            "estado": "CANCELADA", "em": time.time() - 60})
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV2})
    confere("estourou pedidos do dia -> 429", st, 429)
    confere("erro nomeado", b.get("erro"), "muitos_pedidos")
    app.db.dp_solicitacoes.delete_many({"servidor": {"$regex": "DIA"}})

    # ============================================ 4. cancelar
    print("\n4. cancelar")
    sessao["uid"] = ADMIN
    st, b = chama("POST", f"/solicitacoes/{sol_id}/cancelar")
    confere("cancelar pedido dos outros -> 404", st, 404)
    sessao["uid"] = PEDINTE
    st, b = chama("POST", f"/solicitacoes/{sol_id}/cancelar")
    confere("cancelar o proprio -> 200", st, 200)
    confere("virou CANCELADA", b.get("estado"), "CANCELADA")
    st, b = chama("POST", f"/solicitacoes/{sol_id}/cancelar")
    confere("cancelar duas vezes -> 404", st, 404)
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV})
    confere("cancelou, pode pedir de novo na hora -> 200", st, 200)
    sol_id = b["id"]

    # ============================================ 5. fila do admin
    print("\n5. fila do administrador")
    sessao["uid"] = ADMIN
    perm["valor"] = None
    st, _ = chama("GET", f"/servidores/{SRV}/solicitacoes")
    confere("sem vinculo -> 404", st, 404)
    perm["valor"] = 0
    st, _ = chama("GET", f"/servidores/{SRV}/solicitacoes")
    confere("sem ManageServer -> 403", st, 403)
    st, _ = chama("GET", f"/servidores/{SRV}/solicitacoes/contagem")
    confere("contagem tambem exige permissao -> 403", st, 403)
    perm["valor"] = app.BIT_GERIR_SERVIDOR

    st, b = chama("GET", f"/servidores/{SRV}/solicitacoes")
    confere("fila -> 200", st, 200)
    confere("um pendente", len(b["itens"]), 1)
    confere("username resolvido", b["itens"][0]["username"], "pedinte")
    confere("id do pedido", b["itens"][0]["id"], sol_id)
    st, b = chama("GET", f"/servidores/{SRV}/solicitacoes/contagem")
    confere("contagem", b.get("pendentes"), 1)

    # ============================================ 6. decidir
    print("\n6. aceitar e rejeitar")
    st, b = chama("POST", f"/servidores/{SRV2}/solicitacoes/{sol_id}/aceitar")
    confere("id de outra comunidade -> 404", st, 404)

    sessao["uid"] = PEDINTE
    st, b = chama("POST", f"/servidores/{SRV}/solicitacoes/{sol_id}/aceitar")
    confere("decidir o proprio pedido -> 403", st, 403)
    confere("erro nomeado", b.get("erro"), "nao_pode_decidir_o_proprio")

    sessao["uid"] = ADMIN
    chamadas.clear()
    st, b = chama("POST", f"/servidores/{SRV}/solicitacoes/{sol_id}/aceitar")
    confere("aceitar -> 200", st, 200)
    confere("estado APROVADA", b.get("estado"), "APROVADA")
    confere("devolve o codigo do convite", bool(b.get("convite")), True)
    confere("criou convite pela API do Stoat",
            chamadas[0], ("POST", f"/channels/{CANAL}/invites"))
    d = app.db.dp_solicitacoes.find_one({"_id": app.ObjectId(sol_id)})
    confere("convite gravado", d.get("convite"), b["convite"])
    confere("decidido_por gravado", d.get("decidido_por"), ADMIN)

    st, b = chama("POST", f"/servidores/{SRV}/solicitacoes/{sol_id}/aceitar")
    confere("aceitar de novo -> 409", st, 409)
    confere("erro nomeado", b.get("erro"), "ja_decidida")

    # rejeitar
    app.db.dp_solicitacoes.delete_many({"servidor": SRV})
    sessao["uid"] = PEDINTE
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV})
    sol2 = b["id"]
    sessao["uid"] = ADMIN
    st, b = chama("POST", f"/servidores/{SRV}/solicitacoes/{sol2}/rejeitar",
                  {"motivo": "fora do perfil"})
    confere("rejeitar -> 200", st, 200)
    d = app.db.dp_solicitacoes.find_one({"_id": app.ObjectId(sol2)})
    confere("estado REJEITADA", d.get("estado"), "REJEITADA")
    confere("motivo gravado", d.get("motivo"), "fora do perfil")
    sessao["uid"] = PEDINTE
    st, b = chama("POST", "/solicitacoes", {"servidor": SRV})
    confere("rejeitado nao pede de novo na hora -> 429", st, 429)

    # ============================================ 7. corridas
    print("\n7. corridas")
    app.db.dp_solicitacoes.delete_many({"servidor": SRV})
    sessao["uid"] = PEDINTE
    largada = threading.Event()
    res = []

    def pede():
        largada.wait()
        res.append(chama("POST", "/solicitacoes", {"servidor": SRV})[0])

    ts = [threading.Thread(target=pede) for _ in range(20)]
    [t.start() for t in ts]; largada.set(); [t.join() for t in ts]
    print(f"      respostas: 200={res.count(200)} 409={res.count(409)}")
    # Nao basta "um 200": as 20 tem de ser ATENDIDAS. Com o backlog
    # padrao de 5 do socketserver, tres morriam com ConnectionResetError
    # antes de qualquer codigo nosso rodar -- e a assercao de "um 200"
    # passava mesmo assim.
    confere("as 20 foram atendidas", len(res), 20)
    confere("20 pedidos simultaneos -> um 200", res.count(200), 1)
    confere("um documento no banco",
            app.db.dp_solicitacoes.count_documents(
                {"servidor": SRV, "estado": "PENDENTE"}), 1)

    alvo = str(app.db.dp_solicitacoes.find_one({"servidor": SRV})["_id"])
    sessao["uid"] = ADMIN
    chamadas.clear()
    largada2 = threading.Event()
    res2 = []

    def aceita():
        largada2.wait()
        res2.append(chama(
            "POST", f"/servidores/{SRV}/solicitacoes/{alvo}/aceitar")[0])

    ts = [threading.Thread(target=aceita) for _ in range(10)]
    [t.start() for t in ts]; largada2.set(); [t.join() for t in ts]
    print(f"      respostas: 200={res2.count(200)} 409={res2.count(409)}")
    confere("10 aprovacoes simultaneas -> um 200", res2.count(200), 1)
    criados = len([c for c in chamadas if c[0] == "POST"])
    apagados = len([c for c in chamadas if c[0] == "DELETE"])
    print(f"      convites: criados={criados} apagados={apagados}")
    confere("todo convite orfao foi apagado", criados - apagados, 1)

    # ============================================ 8. reconciliacao
    print("\n8. reconciliacao de pendentes")
    app.db.dp_solicitacoes.delete_many({"servidor": {"$regex": "^" + P}})
    base = {"usuario": PEDINTE, "estado": "PENDENTE", "em": time.time()}
    app.db.dp_solicitacoes.insert_one(dict(base, servidor=SRV))
    app.db.server_bans.insert_one({"_id": {"server": SRV, "user": PEDINTE}})
    app.db.dp_solicitacoes.insert_one(dict(base, servidor=SRV2))
    app.db.server_members.insert_one({"_id": {"server": SRV2, "user": PEDINTE}})
    sumido = P + "000000000000SUMIDO1"
    app.db.dp_solicitacoes.insert_one(dict(base, servidor=sumido))

    app._reconcilia_solicitacoes()
    def est(sid):
        return (app.db.dp_solicitacoes.find_one({"servidor": sid}) or {}).get("estado")
    def mot(sid):
        return (app.db.dp_solicitacoes.find_one({"servidor": sid}) or {}).get("motivo")
    confere("banido -> ENCERRADA", est(SRV), "ENCERRADA")
    confere("motivo diz o porque", mot(SRV), "usuario_banido")
    confere("entrou por link -> ENCERRADA", est(SRV2), "ENCERRADA")
    confere("motivo diz o porque", mot(SRV2), "ja_entrou")
    confere("comunidade removida -> ENCERRADA", est(sumido), "ENCERRADA")
    confere("nenhuma virou REJEITADA (ninguem rejeitou)",
            app.db.dp_solicitacoes.count_documents(
                {"servidor": {"$regex": "^" + P}, "estado": "REJEITADA"}), 0)

    # comunidade que virou privada MANTEM os pendentes
    app.db.dp_solicitacoes.delete_many({"servidor": {"$regex": "^" + P}})
    app.db.server_bans.delete_many({"_id.server": {"$regex": "^" + P}})
    app.db.server_members.delete_many({"_id.server": {"$regex": "^" + P}})
    app.db.dp_solicitacoes.insert_one(dict(base, servidor=SRV))
    app.db.dp_comunidade.update_one({"_id": SRV}, {"$set": {"publica": False}})
    app._reconcilia_solicitacoes()
    confere("virou privada -> pendente CONTINUA", est(SRV), "PENDENTE")

finally:
    limpa()
    print(f"\nlimpeza -> dp_solicitacoes: {app.db.dp_solicitacoes.count_documents({})} (esperado 0)")
    print(f"           dp_comunidade: {app.db.dp_comunidade.count_documents({})} (esperado 3)")
    print(f"           servers: {app.db.servers.count_documents({})} (esperado 3)")
    print(f"           users: {app.db.users.count_documents({})} (esperado 21)")

print("\n" + ("TUDO PASSOU" if not falhas else f"{len(falhas)} FALHA(S): {falhas}"))
sys.exit(1 if falhas else 0)
