#!/usr/bin/env python3
"""Adaptador de GIFs: fala Giphy, responde no formato que o cliente espera.

O serviço original do upstream só sabe conversar com a API do Tenor — a
configuração dele chama-se literalmente `tenor_key`. Sem chave, ele
entrava em pânico em laço. E o Tenor deixou de emitir chaves novas.

Trocar o provedor pela raiz seria impossível: o cliente é um pacote
compilado. Mas ele lê o endereço do serviço de GIF de uma variável
substituída na partida do container, não embutida no pacote — então
basta apontá-lo para cá e responder no mesmo formato.

O formato foi lido do próprio cliente:

    GET /categories?locale=..     -> [ {title, image}, ... ]
    GET /trending?locale=..       -> { results: [ item, ... ] }
    GET /search?locale=..&query=X -> { results: [ item, ... ] }

    item = { url, media_formats: { tinywebm: { url } } }

`url` é o que vai na mensagem quando alguém escolhe o GIF, e
`media_formats.tinywebm.url` é a prévia — desenhada dentro de um
elemento <video>, e por isso precisa ser vídeo de verdade, não .gif nem
.webp. No Giphy o campo confiável para isso é `fixed_width_small.mp4`,
presente em todos os itens que inspecionamos.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

from pymongo import MongoClient

PORTA = int(os.environ.get("PORTA", "8602"))
CHAVE = os.environ.get("GIPHY_KEY", "")
MONGO = os.environ.get("MONGO_URL", "mongodb://database:27017")
BASE = "https://api.giphy.com/v1/gifs"
CLASSIFICACAO = os.environ.get("GIPHY_RATING", "pg-13")
TEMPO_LIMITE = 8
LIMITE = 40

# A cota é por chave, não por usuário: cem pessoas abrindo o seletor ao
# mesmo tempo seriam cem chamadas idênticas. O cache é curto porque
# "em alta" muda ao longo do dia, mas segura a rajada.
TTL_BUSCA = 300
TTL_ALTA = 600
TTL_CATEGORIAS = 3600

cli = MongoClient(MONGO, serverSelectionTimeoutMS=5000)
db = cli.revolt

_cache = {}
_trava = Lock()
acertos = faltas = erros = 0


def em_cache(chave):
    with _trava:
        v = _cache.get(chave)
    if v and v[0] > time.time():
        return v[1]
    return None


def guardar(chave, ttl, valor):
    with _trava:
        _cache[chave] = (time.time() + ttl, valor)
        if len(_cache) > 500:                 # teto simples de memória
            agora = time.time()
            for k in [k for k, v in _cache.items() if v[0] < agora]:
                _cache.pop(k, None)


def usuario_da_sessao(token):
    """Resolve o token de sessão para um id de usuário."""
    if not token or len(token) > 256:
        return None
    try:
        s = db.sessions.find_one({"token": token}, {"user_id": 1})
    except Exception:
        return None
    return s.get("user_id") if s else None


def giphy(caminho, params):
    """Chama a API do Giphy. A chave nunca sai daqui."""
    global erros
    if not CHAVE:
        return None
    p = dict(params)
    p["api_key"] = CHAVE
    p["rating"] = CLASSIFICACAO
    url = "%s/%s?%s" % (BASE, caminho, urllib.parse.urlencode(p))
    try:
        with urllib.request.urlopen(url, timeout=TEMPO_LIMITE) as r:
            if r.status != 200:
                return None
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        erros += 1
        return None


def previa(g):
    """A URL de vídeo da prévia, com as alternativas em ordem de tamanho."""
    im = g.get("images") or {}
    for nome in ("fixed_width_small", "downsized_small", "fixed_width",
                 "preview", "looping", "original_mp4"):
        v = im.get(nome) or {}
        if not isinstance(v, dict):
            continue
        u = v.get("mp4") or ""
        if not u and v.get("url", "").endswith(".mp4"):
            u = v["url"]
        if u:
            return u
    return None


def item(g):
    u = previa(g)
    if not u or not g.get("url"):
        return None
    # O nome do campo é herança do formato do Tenor; o cliente lê
    # exatamente este caminho. O conteúdo é mp4, apesar do "webm" no
    # nome — o elemento <video> não se importa com o rótulo.
    return {"id": g.get("id"),
            "url": g["url"],
            "content_description": g.get("title") or "",
            "media_formats": {"tinywebm": {"url": u},
                              "tinygif": {"url": u}}}


def resultados(d):
    return {"results": [i for i in (item(g) for g in (d or {}).get("data", []))
                        if i]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def responde(self, codigo, corpo):
        dados = json.dumps(corpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        global acertos, faltas
        partes = urllib.parse.urlparse(self.path)
        rota = partes.path.strip("/")
        q = urllib.parse.parse_qs(partes.query)

        if rota == "saude":
            return self.responde(200, {"ok": True, "chave": bool(CHAVE),
                                       "acertos": acertos, "faltas": faltas,
                                       "erros": erros, "cache": len(_cache)})

        # Sem sessão não há busca: a cota é da instância, e um endpoint
        # aberto seria consumido por qualquer um que descobrisse a URL.
        if not usuario_da_sessao(self.headers.get("X-Session-Token")):
            return self.responde(401, {"erro": "sessao_invalida"})

        if not CHAVE:
            return self.responde(503, {"erro": "sem_chave", "mensagem":
                                       "Busca de GIF não configurada."})

        if rota == "categories":
            chave = "cat"
            pronto = em_cache(chave)
            if pronto is None:
                d = giphy("categories", {})
                if d is None:
                    return self.responde(502, {"erro": "provedor_indisponivel"})
                pronto = []
                for c in d.get("data", []):
                    im = ((c.get("gif") or {}).get("images") or {})
                    capa = ((im.get("fixed_width_small") or {}).get("url") or
                            (im.get("fixed_width") or {}).get("url") or "")
                    if c.get("name"):
                        pronto.append({"title": c["name"], "image": capa})
                guardar(chave, TTL_CATEGORIAS, pronto)
                faltas += 1
            else:
                acertos += 1
            return self.responde(200, pronto)

        if rota == "trending":
            chave = "alta"
            pronto = em_cache(chave)
            if pronto is None:
                d = giphy("trending", {"limit": LIMITE})
                if d is None:
                    return self.responde(502, {"erro": "provedor_indisponivel"})
                pronto = resultados(d)
                guardar(chave, TTL_ALTA, pronto)
                faltas += 1
            else:
                acertos += 1
            return self.responde(200, pronto)

        if rota == "search":
            termo = (q.get("query") or q.get("q") or [""])[0].strip()[:80]
            if not termo:
                return self.responde(200, {"results": []})
            chave = "b:" + termo.lower()
            pronto = em_cache(chave)
            if pronto is None:
                d = giphy("search", {"q": termo, "limit": LIMITE,
                                     "lang": "pt"})
                if d is None:
                    return self.responde(502, {"erro": "provedor_indisponivel"})
                pronto = resultados(d)
                guardar(chave, TTL_BUSCA, pronto)
                faltas += 1
            else:
                acertos += 1
            return self.responde(200, pronto)

        self.responde(404, {"erro": "nao_encontrado"})


if __name__ == "__main__":
    print("adaptador de gif em :%d (chave %s)"
          % (PORTA, "presente" if CHAVE else "AUSENTE"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
