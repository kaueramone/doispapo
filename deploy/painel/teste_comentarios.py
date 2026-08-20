#!/usr/bin/env python3
"""Exercita Comentários e Novidades ponta a ponta.

Roda DENTRO do container do painel, com o `app.py` do serviço de convites
copiado ao lado como `cliente.py`:

    docker compose cp deploy/convites/app.py painel:/app/cliente.py
    docker compose cp deploy/painel/teste_comentarios.py painel:/app/teste.py
    docker compose exec -T painel python3 /app/teste.py

Os dois lados moram em serviços diferentes -- o cliente escreve pelo
convites, o admin lê e responde pelo painel -- mas conversam pelas mesmas
coleções do banco. Testar um lado só provaria que cada metade funciona
sozinha, que não é a pergunta: a pergunta é se o que a pessoa escreve
chega no painel e se a resposta do admin volta para ela.

Por isso as duas aplicações sobem no mesmo processo, em portas locais
separadas, com a autenticação trocada por dublês. Nenhuma sessão real é
criada e tudo que é gravado é apagado no fim.

Cobre o que os dois lados combinam entre si e nenhum dos dois garante
sozinho: rascunho não vaza para o cliente, resposta do admin aparece em
"Meus envios", contador de comentários acompanha remoção pelos dois
caminhos, e apagar uma novidade leva junto curtidas e comentários.
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import app        # painel
import cliente    # convites

UID = "01TESTECOMENTARIOS00000000"
OUTRO = "01TESTEOUTROUSUARIO0000000"
NOME = "Fulano de Teste"

P_CLIENTE, P_PAINEL = 8698, 8697

# Dublês de autenticação. O cliente resolve token -> usuário; o painel
# valida o cookie de sessão do admin.
cliente.usuario_da_sessao = lambda t: {"tok": UID, "tok2": OUTRO}.get(t)
app.sessao_valida = lambda t: True

for porta, mod in ((P_CLIENTE, cliente), (P_PAINEL, app)):
    s = ThreadingHTTPServer(("127.0.0.1", porta), mod.Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()

falhas = []


def confere(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(("  ok    " if ok else "  FALHA ") + rotulo +
          ("" if ok else f": {obtido!r} (esperado {esperado!r})"))
    if not ok:
        falhas.append(rotulo)


def _chama(porta, metodo, caminho, corpo=None, cabecalhos=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{porta}{caminho}", method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers=dict({"Content-Type": "application/json"}, **(cabecalhos or {})))
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def cli(metodo, caminho, corpo=None, token="tok"):
    cab = {"X-Session-Token": token} if token else {}
    return _chama(P_CLIENTE, metodo, caminho, corpo, cab)


def adm(metodo, caminho, corpo=None):
    return _chama(P_PAINEL, metodo, caminho, corpo,
                  {"Cookie": "dp_painel=qualquer"})


def limpa():
    d = app.db
    for pid in [x["_id"] for x in d.dp_novidades.find(
            {"texto": {"$regex": "^\\[teste\\]"}}, {"_id": 1})]:
        d.dp_novidades_curtidas.delete_many({"post": pid})
        d.dp_novidades_comentarios.delete_many({"post": pid})
        d.dp_novidades.delete_one({"_id": pid})
    d.dp_feedback.delete_many({"uid": {"$in": [UID, OUTRO]}})
    d.dp_novidades_curtidas.delete_many({"uid": {"$in": [UID, OUTRO]}})
    d.dp_novidades_comentarios.delete_many({"uid": {"$in": [UID, OUTRO]}})
    d.users.delete_many({"_id": {"$in": [UID, OUTRO]}})


# O teto de envios é por hora: sem limpar antes, uma segunda rodada na
# mesma hora começaria estourando o limite.
limpa()
app.db.users.insert_one({"_id": UID, "username": "teste", "display_name": NOME})

try:
    print("comentário: cliente escreve, admin lê")
    s, b = cli("POST", "/feedback", {"tipo": "sugestao",
                                     "titulo": "  Título com espaço  ",
                                     "texto": "Texto da sugestão."})
    confere("envio aceito", s, 200)
    fid = b.get("id")

    s, b = adm("GET", "/api/feedback")
    meu = [i for i in b.get("itens", []) if i["id"] == fid]
    confere("aparece no painel", len(meu), 1)
    if meu:
        confere("título aparado", meu[0]["titulo"], "Título com espaço")
        confere("estado inicial", meu[0]["estado"], "recebido")
        confere("autor resolvido pelo display_name",
                meu[0]["autor"]["nome"], NOME)

    s, b = adm("GET", "/api/feedback?tipo=bug")
    confere("filtro de tipo exclui", [i["id"] for i in b["itens"]].count(fid), 0)
    s, b = adm("GET", "/api/feedback?tipo=sugestao&estado=recebido")
    confere("filtro certo inclui", [i["id"] for i in b["itens"]].count(fid), 1)

    print("\ncomentário: admin responde, cliente vê")
    s, _ = adm("POST", f"/api/feedback/{fid}",
               {"estado": "analisando", "resposta": "Vamos olhar."})
    confere("resposta aceita", s, 200)
    s, b = cli("GET", "/feedback/meus")
    meu = [i for i in b["itens"] if i["id"] == fid]
    confere("meus envios traz o item", len(meu), 1)
    if meu:
        confere("estado atualizado", meu[0]["estado"], "analisando")
        confere("resposta chegou", meu[0]["resposta"], "Vamos olhar.")
        confere("marca quando respondeu", bool(meu[0]["respondido_em"]), True)

    adm("POST", f"/api/feedback/{fid}", {"resposta": ""})
    d = app.db.dp_feedback.find_one({"_id": app.ObjectId(fid)})
    confere("apagar a resposta limpa a data", d["respondido_em"], None)
    confere("apagar a resposta zera o campo", d["resposta"], None)

    s, _ = adm("POST", f"/api/feedback/{fid}", {})
    confere("nada a mudar -> 400", s, 400)

    print("\ncomentário: cada um vê só o que mandou")
    cli("POST", "/feedback", {"tipo": "bug", "titulo": "Do outro",
                              "texto": "Não é meu."}, token="tok2")
    s, b = cli("GET", "/feedback/meus")
    confere("envio alheio não vaza",
            [i["titulo"] for i in b["itens"]].count("Do outro"), 0)

    print("\ncomentário: validações")
    s, _ = cli("POST", "/feedback", {"tipo": "elogio", "titulo": "a",
                                     "texto": "b"})
    confere("tipo inválido -> 400", s, 400)
    s, _ = cli("POST", "/feedback", {"tipo": "bug", "titulo": "   ",
                                     "texto": "b"})
    confere("título só de espaço -> 400", s, 400)
    s, _ = cli("POST", "/feedback", {"tipo": "bug", "titulo": "a",
                                     "texto": "b"}, token=None)
    confere("sem sessão -> 401", s, 401)
    s, _ = cli("GET", "/feedback/meus", token=None)
    confere("meus envios sem sessão -> 401", s, 401)

    app.db.dp_feedback.delete_many({"uid": UID})
    for i in range(cliente.TETO_FEEDBACK_HORA):
        cli("POST", "/feedback", {"tipo": "bug", "titulo": f"t{i}",
                                  "texto": "x"})
    s, _ = cli("POST", "/feedback", {"tipo": "bug", "titulo": "demais",
                                     "texto": "x"})
    confere("acima do teto por hora -> 429", s, 429)
    app.db.dp_feedback.delete_many({"uid": UID})

    print("\nnovidade: rascunho não vaza")
    s, b = adm("POST", "/api/novidades",
               {"titulo": "Primeira", "texto": "[teste] rascunho",
                "publicado": False})
    confere("criação aceita", s, 200)
    pid = b.get("id")
    s, b = cli("GET", "/novidades")
    confere("cliente não vê rascunho",
            [i["id"] for i in b["itens"]].count(pid), 0)
    s, _ = cli("POST", f"/novidades/{pid}/curtir")
    confere("curtir rascunho -> 404", s, 404)
    s, _ = cli("POST", f"/novidades/{pid}/comentarios", {"texto": "oi"})
    confere("comentar rascunho -> 404", s, 404)

    adm("POST", f"/api/novidades/{pid}", {"publicado": True,
                                          "texto": "[teste] publicada"})
    s, b = cli("GET", "/novidades")
    visto = [i for i in b["itens"] if i["id"] == pid]
    confere("publicar mostra para o cliente", len(visto), 1)
    if visto:
        confere("texto editado chegou", visto[0]["texto"], "[teste] publicada")
        confere("começa sem curtida", visto[0]["curtidas"], 0)
        confere("começa sem curti", visto[0]["curti"], False)

    print("\nnovidade: curtida vai e volta")
    s, b = cli("POST", f"/novidades/{pid}/curtir")
    confere("curte", (b.get("curti"), b.get("curtidas")), (True, 1))
    s, b = cli("POST", f"/novidades/{pid}/curtir")
    confere("descurte", (b.get("curti"), b.get("curtidas")), (False, 0))
    cli("POST", f"/novidades/{pid}/curtir")
    cli("POST", f"/novidades/{pid}/curtir", token="tok2")
    s, b = cli("GET", "/novidades")
    visto = [i for i in b["itens"] if i["id"] == pid][0]
    confere("duas pessoas somam", visto["curtidas"], 2)
    confere("curti é de quem pergunta", visto["curti"], True)
    s, b = _chama(P_CLIENTE, "GET", "/novidades", None,
                  {"X-Session-Token": "tok2"})
    confere("o outro também curtiu",
            [i for i in b["itens"] if i["id"] == pid][0]["curti"], True)

    print("\nnovidade: comentário e contador")
    s, b = cli("POST", f"/novidades/{pid}/comentarios",
               {"texto": "Comentário meu."})
    confere("comenta", s, 200)
    cid = b.get("id")
    cli("POST", f"/novidades/{pid}/comentarios", {"texto": "Do outro."},
        token="tok2")
    s, b = cli("GET", "/novidades")
    confere("contador soma os dois",
            [i for i in b["itens"] if i["id"] == pid][0]["comentarios"], 2)
    s, b = cli("GET", f"/novidades/{pid}/comentarios")
    confere("lista os dois", len(b["itens"]), 2)
    meus = [i for i in b["itens"] if i["meu"]]
    confere("marca qual é meu", len(meus), 1)
    confere("autor resolvido", meus[0]["autor"]["nome"], NOME)

    s, _ = cli("POST", f"/novidades/{pid}/comentarios/{cid}/remover")
    confere("remove o próprio", s, 200)
    s, b = cli("GET", "/novidades")
    confere("contador desce",
            [i for i in b["itens"] if i["id"] == pid][0]["comentarios"], 1)
    s, b = cli("GET", f"/novidades/{pid}/comentarios")
    confere("removido some do cliente", len(b["itens"]), 1)
    s, b = adm("GET", f"/api/novidades/{pid}/comentarios")
    confere("admin ainda vê o removido", len(b["itens"]), 2)
    confere("e sabe que foi removido",
            sorted(i["removido"] for i in b["itens"]), [False, True])

    s, _ = cli("POST", f"/novidades/{pid}/comentarios/{cid}/remover")
    confere("remover de novo não desconta duas vezes", s, 200)
    s, b = cli("GET", "/novidades")
    confere("contador segue em 1",
            [i for i in b["itens"] if i["id"] == pid][0]["comentarios"], 1)

    alheio = [i for i in adm("GET", f"/api/novidades/{pid}/comentarios")[1]
              ["itens"] if not i["removido"]][0]["id"]
    s, _ = adm("POST", f"/api/novidades/{pid}/comentarios/{alheio}/remover")
    confere("admin modera", s, 200)
    s, b = cli("GET", "/novidades")
    confere("contador zera",
            [i for i in b["itens"] if i["id"] == pid][0]["comentarios"], 0)

    print("\nnovidade: limites e remoção")
    s, b = adm("POST", "/api/novidades",
               {"titulo": "T" * 200, "texto": "[teste] " + "x" * 900})
    grande = b.get("id")
    d = app.db.dp_novidades.find_one({"_id": app.ObjectId(grande)})
    confere("texto cortado no limite", len(d["texto"]), cliente.LIMITE_POST)
    confere("título cortado no limite", len(d["titulo"]),
            cliente.LIMITE_TITULO)
    s, _ = adm("POST", "/api/novidades", {"texto": "   "})
    confere("novidade vazia -> 400", s, 400)

    s, _ = adm("POST", f"/api/novidades/{pid}/remover")
    confere("remove a novidade", s, 200)
    oid = app.ObjectId(pid)
    confere("some do banco",
            app.db.dp_novidades.count_documents({"_id": oid}), 0)
    confere("curtidas vão junto",
            app.db.dp_novidades_curtidas.count_documents({"post": oid}), 0)
    confere("comentários vão junto",
            app.db.dp_novidades_comentarios.count_documents({"post": oid}), 0)
    s, b = cli("GET", "/novidades")
    confere("cliente não vê mais",
            [i["id"] for i in b["itens"]].count(pid), 0)

    s, _ = cli("GET", "/novidades", token=None)
    confere("listar sem sessão -> 401", s, 401)
    s, _ = cli("POST", "/novidades/000000000000000000000000/curtir")
    confere("curtir inexistente -> 404", s, 404)

finally:
    limpa()

confere("nada ficou no banco",
        (app.db.dp_feedback.count_documents({"uid": UID}),
         app.db.users.count_documents({"_id": UID}),
         app.db.dp_novidades.count_documents({"texto": {"$regex": "^\\[teste\\]"}})),
        (0, 0, 0))

print("\n%s" % ("FALHOU: " + ", ".join(falhas) if falhas else "tudo ok"))
sys.exit(1 if falhas else 0)
