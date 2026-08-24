#!/usr/bin/env python3
"""Mostra, ao vivo, o que cada tela compartilhada esta publicando.

Roda DENTRO do container `convites`: a porta 7880 do LiveKit nao e
publicada no host, so existe na rede interna do compose.

    docker exec -i stoat-convites-1 python3 - < rede/olhar-salas.py

O que importa ler aqui e o `bitrate` da camada de cima. Ele denuncia qual
configuracao de codificacao a pessoa esta usando:

    2500000  -> padrao de fabrica da livekit (h1080fps15): QUINZE quadros
    3000000  -> nosso 720p30
    6000000  -> nosso 1080p30

Se alguem reclama de travamento e aparece 2500000, aquela pessoa ainda
nao recomecou o compartilhamento depois da atualizacao -- o codificador
so e configurado no instante em que a tela e publicada.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.request

URL = os.environ.get("LIVEKIT_URL", "http://livekit:7880")


def credenciais():
    """Le a chave do livekit.yml montado no container, sem depender de env."""
    chave = os.environ.get("LIVEKIT_KEY", "")
    segredo = os.environ.get("LIVEKIT_SECRET", "")
    if chave and segredo:
        return chave, segredo
    for caminho in ("/livekit.yml", "/etc/livekit.yml", "/root/stoat/livekit.yml"):
        try:
            texto = open(caminho, encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"^keys:\s*\n\s+([A-Za-z0-9]+):\s*([A-Za-z0-9]+)", texto, re.M)
        if m:
            return m.group(1), m.group(2)
    raise SystemExit("nao encontrei a chave do LiveKit")


CHAVE, SEGREDO = credenciais()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def token(sala=None):
    agora = int(time.time())
    video = {"roomAdmin": True, "room": sala} if sala else {"roomList": True}
    cab = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    corpo = _b64(json.dumps(
        {"iss": CHAVE, "nbf": agora - 5, "exp": agora + 60, "video": video},
        separators=(",", ":")).encode())
    assin = _b64(hmac.new(SEGREDO.encode(), f"{cab}.{corpo}".encode(),
                          hashlib.sha256).digest())
    return f"{cab}.{corpo}.{assin}"


def chamar(metodo, corpo, sala=None):
    req = urllib.request.Request(
        f"{URL}/twirp/livekit.RoomService/{metodo}",
        data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token(sala)})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read() or b"{}")


LEITURA = {2500000: "PADRAO DE FABRICA (15 fps)",
           3000000: "nosso 720p30",
           6000000: "nosso 1080p30"}

for s in chamar("ListRooms", {}).get("rooms") or []:
    nome = s.get("name")
    if not nome:
        continue
    ps = chamar("ListParticipants", {"room": nome}, nome).get("participants") or []
    if not ps:
        continue
    print(f"== sala {nome}")
    for p in ps:
        for t in p.get("tracks") or []:
            fonte = t.get("source") or t.get("type")
            if "SCREEN" not in str(fonte).upper():
                continue
            print(f"  {p.get('identity')}  {fonte}  "
                  f"{t.get('width')}x{t.get('height')}  "
                  f"simulcast={t.get('simulcast')}  mudo={t.get('muted')}")
            for c in t.get("layers") or []:
                b = c.get("bitrate")
                print(f"      camada {c.get('quality'):8s} "
                      f"{c.get('width')}x{c.get('height')}  bitrate={b}"
                      + (f"  <- {LEITURA[b]}" if b in LEITURA else ""))
