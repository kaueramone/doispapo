#!/usr/bin/env python3
"""
Teste da vitrine da comunidade (visibilidade, categoria e tags).

    docker compose cp deploy/convites/teste_vitrine.py convites:/teste_vitrine.py
    docker compose exec -T convites python3 /teste_vitrine.py

Mesma forma do teste_som.py: sobe uma segunda instancia na 8699 com
`usuario_da_sessao` e `permissao_no_servidor` trocados por dubles. Nao cria
sessao real nem toca em credencial nenhuma, e apaga o que gravou.

A parte final e diferente: le a permissao DE VERDADE contra o banco de
producao, sem dubles, porque generalizar o `pode_mover` mexeu num caminho
que ja estava em uso e regressao ali seria silenciosa.
"""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import app

SID = "01TESTE0000000000000000000"
STZ = "01M0BQBWYBJXVP5Q4RZGA1CRTC"
DONO_STZ = "01M0BJJMJX7QN76S2PP5NF6KX6"
ESTRANHO = "01ZZNAOEXISTE00000000000ZZ"

# Dubles. `permissao` e trocada em cada bloco para exercitar os ramos.
app.usuario_da_sessao = lambda t: "UID_DE_TESTE" if t else None
permissao = {"valor": app.CONCEDE_TUDO}
app.permissao_no_servidor = lambda uid, sid: permissao["valor"]

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
    app.db.dp_comunidade.delete_one({"_id": SID})


# =================================================== 1. categorias
print("\n1. GET /vitrine/categorias")
st, _ = chama("GET", "/vitrine/categorias", token=None)
confere("sem sessao -> 401", st, 401)

st, c = chama("GET", "/vitrine/categorias")
confere("com sessao -> 200", st, 200)
confere("9 categorias ativas", len(c.get("itens", [])), 9)
confere("games e a primeira", c["itens"][0]["id"], "games")
confere("geral e a ultima", c["itens"][-1]["id"], "geral")
confere("emoji vem junto", bool(c["itens"][0]["emoji"]), True)

# =================================================== 2. autorizacao
print("\n2. autorizacao do GET da vitrine")
st, _ = chama("GET", f"/servidores/{SID}/vitrine", token=None)
confere("sem sessao -> 401", st, 401)

permissao["valor"] = None            # nao e membro
st, b = chama("GET", f"/servidores/{SID}/vitrine")
confere("sem vinculo -> 404 (nao 403, para nao vazar existencia)", st, 404)

permissao["valor"] = 0               # membro sem poder nenhum
st, b = chama("GET", f"/servidores/{SID}/vitrine")
confere("membro sem ManageServer -> 403", st, 403)
confere("erro nomeado", b.get("erro"), "sem_permissao")

permissao["valor"] = app.BIT_MOVER   # tem OUTRO bit, nao este
st, _ = chama("GET", f"/servidores/{SID}/vitrine")
confere("bit errado nao serve -> 403", st, 403)

permissao["valor"] = app.BIT_GERIR_SERVIDOR
st, b = chama("GET", f"/servidores/{SID}/vitrine")
confere("com ManageServer -> 200", st, 200)
confere("padrao e privada", b.get("publica"), False)
confere("padrao e geral", b.get("categoria"), "geral")

# ============================ 2b. UMA resposta por requisicao negada
#
# Este bloco existe por causa de um defeito real: a guarda chamava
# `self.responde(...)` e devolvia o resultado, mas `responde` devolve
# None -- entao o `if erro is not None` do chamador nunca disparava. O
# 403 saia e o codigo seguia, escrevendo um 200 com os dados logo atras.
# As assercoes de status nao pegavam: o cliente le a PRIMEIRA resposta e
# vai embora. So o traceback de broken pipe no stderr denunciava.
#
# Por isso a conferencia aqui e no socket cru, contando cabecalhos.
import socket

def respostas_cruas(caminho, token="t"):
    """Quantas respostas HTTP o servidor escreve para UMA requisicao."""
    s_ = socket.create_connection(("127.0.0.1", 8699), timeout=3)
    req = (f"GET {caminho} HTTP/1.1\r\nHost: x\r\n"
           f"X-Session-Token: {token}\r\nConnection: close\r\n\r\n")
    s_.sendall(req.encode())
    dados = b""
    s_.settimeout(1.5)
    try:
        while True:
            p = s_.recv(4096)
            if not p:
                break
            dados += p
    except socket.timeout:
        pass
    s_.close()
    return dados.count(b"HTTP/1.")

print("\n2b. uma resposta por requisicao")
permissao["valor"] = None
confere("negado por 404 escreve UMA resposta",
        respostas_cruas(f"/servidores/{SID}/vitrine"), 1)
permissao["valor"] = 0
confere("negado por 403 escreve UMA resposta",
        respostas_cruas(f"/servidores/{SID}/vitrine"), 1)
permissao["valor"] = app.BIT_GERIR_SERVIDOR
confere("permitido escreve UMA resposta",
        respostas_cruas(f"/servidores/{SID}/vitrine"), 1)

# =================================================== 3. escrita
print("\n3. POST da vitrine")
limpa()
permissao["valor"] = app.CONCEDE_TUDO

st, _ = chama("POST", f"/servidores/{SID}/vitrine", {"publica": True}, token=None)
confere("sem sessao -> 401", st, 401)

st, b = chama("POST", f"/servidores/{SID}/vitrine", {})
confere("corpo vazio -> 400", st, 400)
confere("erro nomeado", b.get("erro"), "nada_a_mudar")

st, b = chama("POST", f"/servidores/{SID}/vitrine", {"categoria": "nao-existe"})
confere("categoria inexistente -> 400", st, 400)
confere("erro nomeado", b.get("erro"), "categoria_invalida")

st, b = chama("POST", f"/servidores/{SID}/vitrine",
              {"tags": ["a", "b", "c", "d", "e", "f"]})
confere("6 tags -> 400", st, 400)
confere("erro nomeado", b.get("erro"), "tags_demais")

st, b = chama("POST", f"/servidores/{SID}/vitrine",
              {"categoria": "games", "tags": "Tarkov, FPS , tarkov,  Ação "})
confere("categoria + tags -> 200", st, 200)
confere("categoria gravada", b.get("categoria"), "games")
confere("tags sem acento, sem repetida, minusculas",
        b.get("tags"), ["tarkov", "fps", "acao"])

st, b = chama("POST", f"/servidores/{SID}/vitrine", {"publica": True})
confere("virar publica -> 200", st, 200)
confere("publica no corpo", b.get("publica"), True)
confere("publica no banco",
        bool(app.db.dp_comunidade.find_one({"_id": SID}).get("publica")), True)
confere("entrou no indice parcial do catalogo",
        app.db.dp_comunidade.count_documents({"_id": SID, "publica": True}), 1)

st, b = chama("POST", f"/servidores/{SID}/vitrine", {"membros": 9999})
confere("campo desconhecido e ignorado -> 400", st, 400)
d = app.db.dp_comunidade.find_one({"_id": SID})
confere("membros NAO foi para 9999", d.get("membros") != 9999, True)

st, b = chama("POST", f"/servidores/{SID}/vitrine", {"publica": False})
confere("voltar a privada -> 200", st, 200)
confere("saiu do indice parcial",
        app.db.dp_comunidade.count_documents({"_id": SID, "publica": True}), 0)

# publica exige categoria valida: desativa 'games' e tenta publicar
print("\n4. publica sem categoria valida")
limpa()
app.db.dp_comunidade.update_one(
    {"_id": SID}, {"$set": {"categoria": "categoria-morta", "publica": False}},
    upsert=True)
st, b = chama("POST", f"/servidores/{SID}/vitrine", {"publica": True})
confere("categoria invalida barra a publicacao -> 400", st, 400)
confere("erro nomeado", b.get("erro"), "categoria_obrigatoria")
confere("continua privada no banco",
        bool(app.db.dp_comunidade.find_one({"_id": SID}).get("publica")), False)

# =================================================== 5. permissao de verdade
print("\n5. permissao real contra o banco (sem dubles)")
del app.permissao_no_servidor
import importlib
importlib.reload(app)   # devolve as funcoes originais

confere("dono do STZ recebe tudo",
        app.permissao_no_servidor(DONO_STZ, STZ), app.CONCEDE_TUDO)
confere("quem nao e membro recebe None",
        app.permissao_no_servidor(ESTRANHO, STZ), None)
confere("servidor inexistente recebe None",
        app.permissao_no_servidor(DONO_STZ, ESTRANHO), None)
confere("dono tem ManageServer",
        app.tem_permissao(DONO_STZ, STZ, app.BIT_GERIR_SERVIDOR), True)
confere("pode_mover NAO regrediu: dono move",
        app.pode_mover(DONO_STZ, STZ), True)
confere("pode_mover NAO regrediu: estranho nao move",
        app.pode_mover(ESTRANHO, STZ), False)

# =================================================== fim
app.db.dp_comunidade.delete_one({"_id": SID})
resto = app.db.dp_comunidade.count_documents({"_id": SID})
print(f"\nlimpeza: {resto} documento de teste restante (esperado 0)")
print(f"dp_comunidade: {app.db.dp_comunidade.count_documents({})} docs (esperado 3)")
print(f"publicas: {app.db.dp_comunidade.count_documents({'publica': True})} (esperado 0)")

print("\n" + ("TUDO PASSOU" if not falhas else f"{len(falhas)} FALHA(S): {falhas}"))
sys.exit(1 if falhas else 0)
