#!/usr/bin/env python3
"""Exercita o caminho completo de som personalizado.

Roda DENTRO do container:

    docker compose cp deploy/convites/teste_som.py convites:/teste_som.py
    docker compose exec -T convites python3 /teste_som.py

Sobe uma segunda instância na 8699 com `usuario_da_sessao` e
`dono_do_servidor` trocados por dublês. Não cria sessão real nem toca em
credencial nenhuma, e apaga o que gravou.

Existe porque dois defeitos deste caminho só apareciam com uma sessão
válida — invisíveis para qualquer teste feito de fora com curl:

  1. `c` (o corpo da requisição) nunca era atribuído neste ramo, o que
     derrubava a conexão e chegava ao navegador como 502
  2. o corpo era limitado a 8 KB, e um som de 512 KB vira ~700 KB de
     base64 — todo upload real recebia um objeto vazio e respondia
     "som desconhecido"
"""
import base64
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import app

SID = "01TESTE0000000000000000000"
app.usuario_da_sessao = lambda t: "UID_DE_TESTE" if t else None
app.dono_do_servidor = lambda uid, sid: True

srv = ThreadingHTTPServer(("127.0.0.1", 8699), app.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

falhas = []


def confere(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(("  ok    " if ok else "  FALHA ") + rotulo +
          ("" if ok else f": {obtido!r} (esperado {esperado!r})"))
    if not ok:
        falhas.append(rotulo)


def chama(metodo, caminho, corpo=None, token="t"):
    req = urllib.request.Request(
        "http://127.0.0.1:8699" + caminho, method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"Content-Type": "application/json",
                 "X-Session-Token": token})
    try:
        r = urllib.request.urlopen(req)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ~300 KB: tamanho realista de um mp3 curto, bem acima do teto antigo
BRUTO = b"\xff\xfb\x90\x00" + b"\x00" * 300000
MP3 = base64.b64encode(BRUTO).decode()

print("upload de mp3 de %d KB:" % (len(BRUTO) // 1024))
s, _ = chama("POST", "/sons/" + SID,
             {"som": "message", "dados": MP3, "tipo": "audio/mpeg",
              "nome": "meu-som.mp3"})
confere("POST aceito", s, 200)

s, b = chama("GET", "/sons/" + SID)
cat = json.loads(b).get("sons", {})
confere("catalogo lista o som", "message" in cat, True)
confere("nome preservado", cat.get("message", {}).get("nome"), "meu-som.mp3")

s, b = chama("GET", "/sons/%s/message/audio" % SID)
confere("audio baixa", s, 200)
confere("bytes idênticos ao enviado", b, BRUTO)

# A página pede o áudio com ?v=<versao> para furar o cache do navegador.
# Sem remover a query antes de fatiar o caminho, o último pedaço vira
# "audio?v=1", o ramo do áudio não é reconhecido e a resposta cai no
# catálogo: o navegador recebe JSON e o play() falha em silêncio.
req = urllib.request.Request(
    "http://127.0.0.1:8699/sons/%s/message/audio?v=1" % SID,
    headers={"X-Session-Token": "t"})
r = urllib.request.urlopen(req)
confere("com ?v= ainda é áudio", r.headers.get("Content-Type"), "audio/mpeg")
confere("com ?v= os bytes conferem", r.read(), BRUTO)

print("\nisolamento entre eventos:")
s, _ = chama("POST", "/sons/" + SID,
             {"som": "deafen", "dados": MP3, "tipo": "audio/ogg", "nome": "d"})
confere("segundo evento aceito", s, 200)
cat = json.loads(chama("GET", "/sons/" + SID)[1]).get("sons", {})
confere("os dois convivem", sorted(cat), ["deafen", "message"])
chama("POST", "/sons/" + SID, {"som": "deafen", "remover": True})
cat = json.loads(chama("GET", "/sons/" + SID)[1]).get("sons", {})
confere("remover um não afeta o outro", sorted(cat), ["message"])

print("\nvalidações:")
s, _ = chama("POST", "/sons/" + SID,
             {"som": "inexistente", "dados": MP3, "tipo": "audio/mpeg"})
confere("evento desconhecido -> 400", s, 400)
s, _ = chama("POST", "/sons/" + SID,
             {"som": "userJoinVoice", "dados": MP3, "tipo": "audio/mpeg"})
confere("entrar na chamada é personalizável", s, 200)
chama("POST", "/sons/" + SID, {"som": "userJoinVoice", "remover": True})
confere("a lista tem os 14 sons", len(app.SONS_VALIDOS), 14)
s, _ = chama("POST", "/sons/" + SID,
             {"som": "deafen", "dados": MP3, "tipo": "application/pdf"})
confere("tipo não suportado -> 415", s, 415)
s, _ = chama("POST", "/sons/" + SID,
             {"som": "deafen", "tipo": "audio/mpeg",
              "dados": base64.b64encode(b"x" * 600000).decode()})
confere("acima de 512 KB -> 413", s, 413)
s, _ = chama("POST", "/sons/" + SID, {"som": "message"}, token="")
confere("sem sessão -> 401", s, 401)
s, _ = chama("GET", "/sons/%s/naoexiste/audio" % SID)
confere("audio de evento inválido -> 404", s, 404)

print("\nremoção:")
s, _ = chama("POST", "/sons/" + SID, {"som": "message", "remover": True})
confere("remove", s, 200)
confere("catálogo vazio",
        json.loads(chama("GET", "/sons/" + SID)[1]).get("sons"), {})

app.db.sons.delete_many({"servidor": SID})
confere("nada ficou no banco",
        app.db.sons.count_documents({"servidor": SID}), 0)

print("\n%s" % ("FALHOU: " + ", ".join(falhas) if falhas else "tudo ok"))
sys.exit(1 if falhas else 0)
