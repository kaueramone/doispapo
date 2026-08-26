#!/usr/bin/env python3
"""
Teste do endurecimento do servico (fase 8).

    docker compose cp deploy/convites/teste_endurecimento.py convites:/teste_endurecimento.py
    docker compose exec -T convites python3 /teste_endurecimento.py

Mesma forma dos outros: instancias proprias em portas altas, com
`usuario_da_sessao` trocado por um duble. Nao cria sessao real, nao toca em
credencial e nao grava nada no banco.

Prova tres coisas que so aparecem sob carga -- exatamente o tipo de defeito
que passa em revisao de codigo e derruba o servico em producao:

  1. O teto de conexoes existe e RESPONDE. Sem teto, o
     ThreadingHTTPServer cria uma thread por conexao e nunca para: mil
     conexoes ociosas sao mil threads paradas, e o processo morre sem ter
     recebido um byte de HTTP.
  2. A vaga VOLTA quando a conexao fecha. Um teto que so desce e um
     vazamento com nome bonito: o servico funcionaria por um tempo e
     depois recusaria tudo para sempre.
  3. Conexao ociosa nao segura a thread eternamente. Com HTTP/1.1 a
     conexao fica aberta entre requisicoes; sem prazo, quem abre e cala
     ocupa a vaga ate o fim do mundo -- e o item 1 viraria so uma forma
     mais lenta de morrer.

E uma coisa que aparece sem carga nenhuma:

  4. /discord-template exige sessao, e a exige ANTES de validar o codigo.
     A ordem importa: se validasse primeiro, um desconhecido descobriria
     pela resposta quais codigos tem forma valida, e continuaria podendo
     nos fazer falar com o discord.com.
"""
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import app

app.usuario_da_sessao = lambda t: "UID_DE_TESTE" if t else None

falhas = []


def confere(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(("  ok    " if ok else "  FALHA ") + rotulo +
          ("" if ok else f": {obtido!r} (esperado {esperado!r})"))
    if not ok:
        falhas.append(rotulo)


def sobe(porta, teto, prazo):
    """Uma instancia com teto e prazo proprios.

    O teto e lido no __init__ do Servidor, entao a constante do modulo e
    trocada antes de construir. O prazo mora na classe do Handler, entao
    cada instancia ganha uma subclasse -- senao o prazo curto do teste 3
    mataria as conexoes ociosas do teste 1.
    """
    class H(app.Handler):
        timeout = prazo
    app.TETO_THREADS = teto
    srv = app.Servidor(("127.0.0.1", porta), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def pede(porta, caminho, token="t"):
    h = {}
    if token:
        h["X-Session-Token"] = token
    req = urllib.request.Request(f"http://127.0.0.1:{porta}{caminho}",
                                 headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def bruta(porta, texto=None, prazo=5):
    """Socket cru. Devolve o socket aberto quando texto e None."""
    s = socket.create_connection(("127.0.0.1", porta), timeout=prazo)
    if texto is None:
        return s
    s.sendall(texto)
    dados = b""
    try:
        while True:
            p = s.recv(4096)
            if not p:
                break
            dados += p
    except socket.timeout:
        pass
    s.close()
    return dados


# ------------------------------------------------------- 1 e 2: o teto
print("\n== teto de conexoes ==")
TETO = 4
srv = sobe(8697, TETO, 60)

# Antes de encher: uma requisicao normal passa.
cod, _ = pede(8697, "/saude")
confere("com vaga, /saude responde 200", cod, 200)

# Enche o teto com conexoes que conectam e nao falam nada -- o caso que
# derruba o servidor sem teto, porque nenhuma delas chega ao nosso codigo.
ociosas = [bruta(8697) for _ in range(TETO)]
time.sleep(0.4)   # deixa o accept loop pegar todas

resposta = bruta(8697, b"GET /saude HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
primeira = resposta.split(b"\r\n", 1)[0] if resposta else b""
confere("cheio, a conexao seguinte leva 503", primeira,
        b"HTTP/1.1 503 Service Unavailable")
confere("o 503 tem exatamente uma resposta HTTP", resposta.count(b"HTTP/1."), 1)
try:
    corpo = json.loads(resposta.split(b"\r\n\r\n", 1)[1])
except Exception:
    corpo = {}
confere("o 503 traz erro nomeado", corpo.get("erro"), "ocupado")
confere("o 503 traz Retry-After", b"Retry-After:" in resposta, True)

# Fecha as ociosas: as vagas tem de voltar.
for s in ociosas:
    s.close()
# As threads presas no recv precisam notar o fim da conexao e sair.
for _ in range(50):
    time.sleep(0.1)
    cod, _ = pede(8697, "/saude")
    if cod == 200:
        break
confere("apos fechar, a vaga volta e /saude responde 200", cod, 200)
srv.shutdown()

# ------------------------------------------------ 3: conexao ociosa cai
print("\n== prazo da conexao ociosa ==")
srv2 = sobe(8696, 16, 2)
s = bruta(8696, prazo=10)
inicio = time.monotonic()
s.settimeout(8)
try:
    lido = s.recv(4096)          # nada foi enviado; esperamos o fim
    caiu = (lido == b"")
except socket.timeout:
    caiu = False
except OSError:
    caiu = True                  # RST tambem e a conexao terminando
gasto = time.monotonic() - inicio
s.close()
confere("conexao ociosa e encerrada pelo servidor", caiu, True)
confere("e encerrada perto do prazo, nao muito depois", gasto < 6, True)
srv2.shutdown()

# -------------------------------------- 4: /discord-template com sessao
print("\n== /discord-template exige sessao ==")
srv3 = sobe(8695, 16, 30)

cod, corpo = pede(8695, "/discord-template?codigo=abcdef", token=None)
confere("sem sessao, 401", cod, 401)
confere("sem sessao, erro nomeado", corpo.get("erro"), "sessao_invalida")

# Codigo de forma invalida E sem sessao: quem responde primeiro e a
# sessao. Se viesse 400 aqui, a rota estaria contando a desconhecidos
# qual codigo tem forma valida.
cod, _ = pede(8695, "/discord-template?codigo=x", token=None)
confere("sem sessao ganha do codigo invalido (401, nao 400)", cod, 401)

# Com sessao, a validacao do codigo volta a valer -- e para antes de
# qualquer chamada ao discord.com, entao o teste nao sai para a internet.
cod, corpo = pede(8695, "/discord-template?codigo=x")
confere("com sessao e codigo curto, 400", cod, 400)
confere("com sessao e codigo curto, erro nomeado",
        corpo.get("erro"), "codigo_invalido")
srv3.shutdown()

print()
if falhas:
    print(f"FALHOU: {len(falhas)} -> {falhas}")
    sys.exit(1)
print("tudo certo")
