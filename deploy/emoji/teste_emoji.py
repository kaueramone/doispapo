#!/usr/bin/env python3
"""Exercita o espelho de emoji.

Roda DENTRO do container:

    docker compose cp deploy/emoji/teste_emoji.py emoji:/teste_emoji.py
    docker compose exec -T emoji python3 /teste_emoji.py

A origem é um servidor de mentira levantado aqui, não o CDN de verdade:
o teste precisa ser repetível e não pode depender de host de terceiro
estar no ar — que é justamente a dependência que este serviço existe
para eliminar.
"""
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import app

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="9"/></svg>'
pedidos = []


class Origem(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        pedidos.append(self.path)
        # Os codepoints abaixo são os combinados para cada cenário. O
        # nome do arquivo é o único canal que o serviço realmente usa,
        # então é por ele que o cenário é escolhido.
        if "1f9ff" in self.path:            # upstream não tem esse emoji
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if "1f4a9" in self.path:            # responde 200 com lixo
            corpo = b"isto nao e um svg"
        else:
            corpo = SVG
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


app.CACHE = tempfile.mkdtemp(prefix="emoji-teste-")
threading.Thread(
    target=ThreadingHTTPServer(("127.0.0.1", 8698), Origem).serve_forever,
    daemon=True).start()
app.ORIGEM = "http://127.0.0.1:8698/emoji"
app.FALHAS.clear()

threading.Thread(
    target=ThreadingHTTPServer(("127.0.0.1", 8697), app.Handler).serve_forever,
    daemon=True).start()

falhas = []


def confere(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(("  ok    " if ok else "  FALHA ") + rotulo +
          ("" if ok else f": {obtido!r} (esperado {esperado!r})"))
    if not ok:
        falhas.append(rotulo)


def pega(caminho):
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8697" + caminho, timeout=5)
        return r.status, r.read(), r.headers.get("Cache-Control")
    except urllib.error.HTTPError as e:
        return e.code, b"", None


print("cache preguiçoso:")
s, b, cc = pega("/fluent-3d/1f600.svg?v=1")
confere("primeira busca responde", s, 200)
confere("conteúdo é o do upstream", b, SVG)
confere("foi ao upstream uma vez", len(pedidos), 1)
confere("gravou em disco",
        os.path.exists(os.path.join(app.CACHE, "fluent-3d", "1f600.svg")), True)
confere("marcado como imutável", "immutable" in (cc or ""), True)

s, b, _ = pega("/fluent-3d/1f600.svg?v=1")
confere("segunda busca responde", s, 200)
confere("NÃO voltou ao upstream", len(pedidos), 1)

print("\nvalidação de entrada:")
for caminho, esperado, rotulo in [
        ("/inventado/1f600.svg", 404, "pacote fora da lista"),
        ("/fluent-3d/algo.svg", 404, "nome que não é codepoint"),
        ("/fluent-3d/1f600.png", 404, "extensão diferente de svg"),
        ("/fluent-3d/../../etc/passwd", 404, "travessia com ../"),
        ("/fluent-3d/..%2f..%2fetc%2fpasswd", 404, "travessia percent-encoded"),
        ("/fluent-3d", 404, "caminho incompleto"),
        ("/a/b/c.svg", 404, "caminho fundo demais")]:
    confere(rotulo, pega(caminho)[0], esperado)

print("\nfalha do upstream:")
antes = len(pedidos)
confere("404 no upstream vira 404", pega("/noto/1f9ff.svg")[0], 404)
confere("não grava o que falhou",
        os.path.exists(os.path.join(app.CACHE, "noto", "1f9ff.svg")), False)

print("\nresposta que não é SVG:")
confere("upstream mentindo vira 404", pega("/mutant/1f4a9.svg")[0], 404)
confere("não grava conteúdo inválido",
        os.path.exists(os.path.join(app.CACHE, "mutant", "1f4a9.svg")), False)

print("\nsaúde:")
s, b, _ = pega("/saude")
confere("responde", s, 200)
confere("traz contadores", b"acertos" in b, True)

shutil.rmtree(app.CACHE, ignore_errors=True)
print("\n%s" % ("FALHOU: " + ", ".join(falhas) if falhas else "tudo ok"))
sys.exit(1 if falhas else 0)
