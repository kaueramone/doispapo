#!/usr/bin/env python3
"""Exercita o adaptador de GIF.

    docker compose cp deploy/gifs/teste_gifs.py gifs:/teste_gifs.py
    docker compose exec -T gifs python3 /teste_gifs.py

A API do Giphy é substituída por um servidor local: o teste não pode
gastar cota nem depender de rede, e precisa poder devolver respostas
esquisitas de propósito. A sessão também é dublada — nada de criar
credencial de verdade.
"""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import app

chamadas = []

GIF = {"id": "abc", "url": "https://giphy.com/gifs/abc",
       "title": "um gato",
       "images": {"fixed_width_small": {"mp4": "https://m.giphy.com/a.mp4"},
                  "fixed_width": {"url": "https://m.giphy.com/a.gif"}}}
SEM_VIDEO = {"id": "sv", "url": "https://giphy.com/gifs/sv", "title": "x",
             "images": {"fixed_width": {"url": "https://m.giphy.com/b.gif"}}}


class Giphy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        chamadas.append(self.path)
        if "categories" in self.path:
            corpo = {"data": [{"name": "Reações", "gif": {"images": {
                "fixed_width_small": {"url": "https://m.giphy.com/c.gif"}}}}]}
        elif "quebrado" in self.path:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        else:
            corpo = {"data": [GIF, SEM_VIDEO]}
        d = json.dumps(corpo).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)


threading.Thread(
    target=ThreadingHTTPServer(("127.0.0.1", 8696), Giphy).serve_forever,
    daemon=True).start()
app.BASE = "http://127.0.0.1:8696/v1/gifs"
app.CHAVE = "chave-de-teste"
app.usuario_da_sessao = lambda t: "UID_DE_TESTE" if t else None
app._cache.clear()

threading.Thread(
    target=ThreadingHTTPServer(("127.0.0.1", 8695), app.Handler).serve_forever,
    daemon=True).start()

falhas = []


def confere(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(("  ok    " if ok else "  FALHA ") + rotulo +
          ("" if ok else f": {obtido!r} (esperado {esperado!r})"))
    if not ok:
        falhas.append(rotulo)


def pega(caminho, token="t"):
    req = urllib.request.Request("http://127.0.0.1:8695" + caminho,
                                 headers={"X-Session-Token": token} if token
                                 else {})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


print("autenticação:")
for rota in ("/trending", "/search?query=x", "/categories"):
    confere("sem sessão %s -> 401" % rota, pega(rota, token="")[0], 401)

print("\nformato que o cliente espera:")
s, d = pega("/trending?locale=en_US")
confere("responde", s, 200)
r = d.get("results", [])
confere("chave 'results' presente", isinstance(r, list), True)
confere("item sem vídeo é descartado", len(r), 1)
confere("url é a página do Giphy", r[0]["url"], "https://giphy.com/gifs/abc")
confere("prévia vem de media_formats.tinywebm",
        r[0]["media_formats"]["tinywebm"]["url"], "https://m.giphy.com/a.mp4")
confere("prévia é vídeo, não .gif",
        r[0]["media_formats"]["tinywebm"]["url"].endswith(".mp4"), True)

print("\ncategorias:")
s, d = pega("/categories?locale=en_US")
confere("responde", s, 200)
confere("é uma lista", isinstance(d, list), True)
confere("tem title e image", sorted(d[0].keys()), ["image", "title"])
confere("title preservado", d[0]["title"], "Reações")

print("\ncache (protege a cota):")
antes = len(chamadas)
pega("/search?query=gato")
meio = len(chamadas)
pega("/search?query=gato")
confere("primeira busca chama o provedor", meio - antes, 1)
confere("segunda busca NÃO chama", len(chamadas) - meio, 0)
pega("/search?query=cachorro")
confere("busca diferente chama de novo", len(chamadas) - meio, 1)

print("\nbusca vazia:")
s, d = pega("/search?query=")
confere("não chama o provedor", d.get("results"), [])

print("\nprovedor fora do ar:")
app._cache.clear()
app.BASE = "http://127.0.0.1:8696/v1/quebrado"
confere("vira 502, não 200 vazio", pega("/trending")[0], 502)

print("\nsem chave configurada:")
app.CHAVE = ""
confere("vira 503", pega("/categories")[0], 503)

print("\n%s" % ("FALHOU: " + ", ".join(falhas) if falhas else "tudo ok"))
sys.exit(1 if falhas else 0)
