#!/usr/bin/env python3
"""Espelho dos emoji, com cache preguiçoso em disco.

O cliente vinha pedindo cada emoji direto ao CDN do upstream:

    https://static.stoat.chat/emoji/fluent-3d/1f600.svg?v=1

Isso deixava a plataforma dependente da infraestrutura de terceiro — se
aquele domínio sair do ar, os emoji somem de todas as conversas — e
fazia o navegador de cada usuário conversar com um host que não é nosso,
a cada emoji renderizado.

Aqui a primeira requisição de cada arquivo busca lá e grava em disco; da
segunda em diante sai daqui. Com o uso, vira um espelho completo do que
a comunidade realmente usa, sem baixar centenas de MB de antemão.
"""
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

PORTA = int(os.environ.get("PORTA", "8601"))
CACHE = os.environ.get("CACHE", "/cache")
ORIGEM = os.environ.get("ORIGEM", "https://static.stoat.chat/emoji")
TEMPO_LIMITE = 8
TAMANHO_MAX = 2 * 1024 * 1024      # nenhum emoji legítimo passa disso

# Os pacotes que o cliente oferece. Lista fechada: o nome entra num
# caminho de arquivo, e aceitar qualquer texto abriria travessia de
# diretório.
PACOTES = ("fluent-3d", "fluent-color", "fluent-flat",
           "mutant", "noto", "twemoji")

# Emoji são nomeados pelos codepoints em hexadecimal, unidos por hífen.
RE_ARQUIVO = re.compile(r"^[0-9a-f]{1,6}(?:-[0-9a-f]{1,6}){0,8}\.svg$")

# Falha do upstream não vira buraco permanente: guardamos por pouco
# tempo, só para não repetir a mesma busca inútil a cada emoji na tela.
FALHAS = {}
FALHA_TTL = 60
_trava = Lock()

acertos = faltas = erros = 0


def caminho_local(pacote, arquivo):
    return os.path.join(CACHE, pacote, arquivo)


def buscar(pacote, arquivo):
    """Traz do upstream e grava. Devolve os bytes, ou None."""
    global erros
    url = "%s/%s/%s?v=1" % (ORIGEM, pacote, arquivo)
    req = urllib.request.Request(url, headers={"User-Agent": "DoisPapo"})
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as r:
            if r.status != 200:
                return None
            dados = r.read(TAMANHO_MAX + 1)
    except (urllib.error.URLError, OSError, ValueError):
        erros += 1
        return None
    if not dados or len(dados) > TAMANHO_MAX:
        return None
    if b"<svg" not in dados[:400].lower():
        return None                     # não é o que dissemos que era

    destino = caminho_local(pacote, arquivo)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    # grava em temporário e renomeia: duas requisições simultâneas para
    # o mesmo emoji não podem deixar um arquivo pela metade em disco
    tmp = "%s.%d.tmp" % (destino, os.getpid())
    try:
        with open(tmp, "wb") as fh:
            fh.write(dados)
        os.replace(tmp, destino)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return dados


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def erro(self, codigo):
        self.send_response(codigo)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        global acertos, faltas
        rota = self.path.split("?", 1)[0].strip("/")

        if rota == "saude":
            corpo = ('{"ok":true,"acertos":%d,"faltas":%d,"erros":%d}'
                     % (acertos, faltas, erros)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return

        partes = rota.split("/")
        if len(partes) != 2:
            return self.erro(404)
        pacote, arquivo = partes
        if pacote not in PACOTES or not RE_ARQUIVO.match(arquivo):
            return self.erro(404)

        local = caminho_local(pacote, arquivo)
        dados = None
        if os.path.exists(local):
            try:
                with open(local, "rb") as fh:
                    dados = fh.read()
                acertos += 1
            except OSError:
                dados = None

        if dados is None:
            chave = pacote + "/" + arquivo
            with _trava:
                ate = FALHAS.get(chave, 0)
            if ate > time.time():
                return self.erro(404)
            dados = buscar(pacote, arquivo)
            if dados is None:
                with _trava:
                    FALHAS[chave] = time.time() + FALHA_TTL
                return self.erro(404)
            faltas += 1

        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(dados)))
        # o conteúdo de um codepoint não muda; só o pacote inteiro seria
        # trocado, e aí o caminho muda junto
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(dados)


if __name__ == "__main__":
    os.makedirs(CACHE, exist_ok=True)
    print("espelho de emoji em :%d (cache em %s)" % (PORTA, CACHE), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
