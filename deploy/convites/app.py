#!/usr/bin/env python3
"""
Serviço de cota de convites do Dois Papo.

Regra: cada conta pode gerar até LIMITE convites de conta. A cota conta
convites GERADOS (não os usados) — o slot é reservado na criação e volta
se o convite não usado for apagado.

Ponte entre os dois tipos de convite do produto:
  channel_invites  -> convite de servidor (tem 'creator')
  account_invites  -> convite de cadastro (ganha 'criado_por' e 'origem')

Quando alguém sem conta abre um convite de servidor, consultamos quem o
criou e, havendo cota, emitimos um convite de conta em nome dessa pessoa.
"""
import base64, hashlib, hmac, json, os, queue, re, secrets, threading, time
import urllib.request, urllib.parse, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from bson import ObjectId
from pymongo import MongoClient

LIMITE = int(os.environ.get("LIMITE_CONVITES", "5"))
MONGO  = os.environ.get("MONGO_URL", "mongodb://database:27017")
PORTA  = int(os.environ.get("PORTA", "8600"))

cli = MongoClient(MONGO, serverSelectionTimeoutMS=5000)
db  = cli.revolt
trava = threading.Lock()   # serializa a checagem de cota + emissão

RE_CODIGO = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RE_EMAIL  = re.compile(r"^[^@\s]{1,64}@[^@\s.]{1,63}(\.[^@\s.]{2,63})+$")
RE_DATA   = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ADMIN_UID = os.environ.get("ADMIN_UID", "")


def idade(nascimento):
    """Idade em anos a partir de AAAA-MM-DD."""
    from datetime import date
    a, m, d = (int(x) for x in nascimento.split("-"))
    hoje = date.today()
    return hoje.year - a - ((hoje.month, hoje.day) < (m, d))


def usuario_da_sessao(token):
    """Resolve o token de sessão para um id de usuário."""
    if not token or len(token) > 256:
        return None
    s = db.sessions.find_one({"token": token}, {"user_id": 1})
    return s.get("user_id") if s else None


# ------------------------------------------------------------- metricas
# Tres fontes, deliberadamente separadas -- misturar medicao com
# estimativa num mesmo numero e como se mente com grafico.
#
#   1. Contadores de rede da MAQUINA, via amostra-rede.sh. Verdade
#      absoluta sobre quanto trafego entrou e saiu, sem saber de quem.
#   2. Metricas do SFU (Prometheus). Participantes, salas, qualidade,
#      latencia de encaminhamento e pacotes descartados. Sao por no, sem
#      rotulo de sala -- entao tambem nao dividem por comunidade.
#   3. Composicao das salas, amostrada da API do SFU. E o unico caminho
#      para saber QUEM consumiu: quantas faixas de cada tipo, em qual
#      canal, de qual servidor.
#
# O rateio por comunidade sai de (3) e e ESTIMATIVA. O total de (1) e
# medicao. O painel mostra os dois lado a lado, rotulados.
METRICAS_URL = os.environ.get("LIVEKIT_METRICAS", "http://livekit:6789/metrics")
REDE_ARQUIVO = os.environ.get("REDE_ARQUIVO", "/rede/atual")
METRICAS_INTERVALO = 60

# Taxas medidas nesta instancia (ver docs/desempenho-voz.md). Servem para
# ratear o total real entre as comunidades, nao para inventar um total.
KBIT_VIDEO = 2313
KBIT_AUDIO = 3


def _prometheus(texto):
    """Le o formato do Prometheus para um dicionario simples."""
    fora = {}
    for linha in texto.splitlines():
        if not linha or linha.startswith("#"):
            continue
        nome, _, resto = linha.partition("{")
        if resto:
            valor = resto.rsplit("}", 1)[-1].strip()
        else:
            nome, _, valor = linha.partition(" ")
            resto = ""
        # O rotulo `type` precisa ser casado com precisao: `node_type="SERVER"`
        # contem a sequencia `type="` dentro dele. Procurar por substring
        # capturava "SERVER" como se fosse o tipo, e ai a busca por
        # ("livekit_participant_total", "") nunca casava -- todo campo do
        # SFU vinha zero, num documento bem formado e sem erro nenhum.
        achou = re.search(r'(?:^|,)type="([^"]*)"', resto)
        rotulo = achou.group(1) if achou else ""
        try:
            fora[(nome.strip(), rotulo)] = float(valor)
        except ValueError:
            continue
    return fora


def _rede_agora():
    try:
        with open(REDE_ARQUIVO, encoding="utf-8") as fh:
            t, rx, tx = fh.read().split()
        return int(t), int(rx), int(tx)
    except Exception:
        return None


_rede_anterior = None


def coletar_metricas():
    global _rede_anterior
    agora = time.time()
    doc = {"em": agora}

    # --- 1. rede real da maquina ---
    atual = _rede_agora()
    if atual and _rede_anterior:
        dt = atual[0] - _rede_anterior[0]
        if 0 < dt < 600:
            doc["rede"] = {
                "segundos": dt,
                "entrada_bytes": max(0, atual[1] - _rede_anterior[1]),
                "saida_bytes": max(0, atual[2] - _rede_anterior[2]),
            }
    if atual:
        _rede_anterior = atual

    # --- 2. metricas do SFU ---
    try:
        with urllib.request.urlopen(METRICAS_URL, timeout=5) as r:
            m = _prometheus(r.read().decode("utf-8", "replace"))
        qs_soma = m.get(("livekit_quality_score_sum", ""), 0)
        qs_qtd = m.get(("livekit_quality_score_count", ""), 0)
        doc["sfu"] = {
            "participantes": m.get(("livekit_participant_total", ""), 0),
            "salas": m.get(("livekit_room_total", ""), 0),
            "latencia_encaminhamento": m.get(("livekit_forward_latency", ""), 0),
            "jitter_encaminhamento": m.get(("livekit_forward_jitter", ""), 0),
            "pacotes_saida": m.get(("livekit_node_packet_total", "out"), 0),
            "pacotes_descartados": m.get(("livekit_node_packet_total", "dropped"), 0),
            "qualidade_media": (qs_soma / qs_qtd) if qs_qtd else None,
        }
    except Exception as e:
        print(f"metricas: SFU indisponivel ({e})", flush=True)

    # --- 3. composicao das salas ---
    try:
        salas = _chamar("ListRooms", {}).get("rooms") or []
        por_canal = {}
        for sala in salas:
            nome = sala.get("name")
            if not nome:
                continue
            ps = _chamar("ListParticipants", {"room": nome}, nome).get(
                "participants") or []
            video = audio = 0
            for p in ps:
                for t in (p.get("tracks") or []):
                    if t.get("muted"):
                        continue
                    if t.get("type") == "VIDEO":
                        video += 1
                    else:
                        audio += 1
            if ps:
                por_canal[nome] = {"participantes": len(ps),
                                   "faixas_video": video,
                                   "faixas_audio": audio,
                                   "peso": video * KBIT_VIDEO + audio * KBIT_AUDIO}
        doc["canais"] = por_canal
    except Exception as e:
        print(f"metricas: composicao indisponivel ({e})", flush=True)

    db.dp_metricas.insert_one(doc)


def _laco_metricas():
    while True:
        try:
            coletar_metricas()
        except Exception as e:
            print(f"metricas: falha na coleta ({e})", flush=True)
        time.sleep(METRICAS_INTERVALO)


def inicia_metricas():
    threading.Thread(target=_laco_metricas, daemon=True).start()


# ------------------------------------------------- feedback e novidades
# Ate a 0.35 a tela de Comentarios levava para discussoes no GitHub do
# upstream: tres links para fora, num projeto que nao e o nosso. Quem
# clicava saia da plataforma para falar de um produto diferente.
#
# Agora o envio acontece aqui, e o painel trata. As colecoes vivem no
# mesmo banco do resto (prefixo dp_ para nao colidir com o upstream).

TIPOS_FEEDBACK = ("sugestao", "comentario", "bug")
ESTADOS_FEEDBACK = ("recebido", "analisando", "resolvido", "recusado")

LIMITE_TITULO = 120
LIMITE_TEXTO = 4000
LIMITE_COMENTARIO = 1000
LIMITE_POST = 560

# Envios por usuario por hora. Nao e defesa contra abuso coordenado --
# a instancia e fechada por convite --, e sim contra o dedo preso no
# botao e contra script de teste que esquece de parar.
TETO_FEEDBACK_HORA = 10
TETO_COMENTARIO_HORA = 30


def _texto(valor, limite):
    """Normaliza texto vindo do cliente: corta, apara e recusa vazio."""
    if not isinstance(valor, str):
        return None
    v = valor.replace("\r\n", "\n").strip()
    if not v:
        return None
    return v[:limite]


def _excedeu(colecao, uid, teto):
    desde = time.time() - 3600
    return colecao.count_documents({"uid": uid, "em": {"$gte": desde}}) >= teto


# ================================================== conquistas
# O que cada pessoa ja fez, e o que ainda falta.
#
# Tres das quatro medidas sao retroativas, porque o dado ja existia:
# comunidades saem de `server_members`, mensagens de `messages` e amigos
# das `relations` do proprio usuario. Tempo de voz NAO era guardado por
# pessoa em lugar nenhum -- a colecao `chamadas` registra a sala, nunca
# quem estava nela -- entao ele comeca a contar a partir de agora.
#
# O degrau mora na regra: acrescentar uma conquista e acrescentar uma
# linha nesta lista.
CONQUISTAS = [
    {"chave": "voz_50h", "titulo": "Cinquenta horas de conversa",
     "descricao": "Somar 50 horas em canais de voz", "meta": 50 * 3600,
     "unidade": "horas", "icone": "headset_mic"},
    {"chave": "comunidades_5", "titulo": "Circulando",
     "descricao": "Participar de 5 comunidades", "meta": 5,
     "unidade": "comunidades", "icone": "groups"},
    {"chave": "mensagens_100", "titulo": "Cem mensagens",
     "descricao": "Escrever 100 mensagens", "meta": 100,
     "unidade": "mensagens", "icone": "forum"},
    {"chave": "amigos_10", "titulo": "Dez amigos",
     "descricao": "Ter 10 amizades aceitas", "meta": 10,
     "unidade": "amigos", "icone": "diversity_3"},
    {"chave": "primeira_live", "titulo": "No ar",
     "descricao": "Compartilhar a tela pela primeira vez", "meta": 1,
     "unidade": "transmissoes", "icone": "screen_share"},
]

# Sessao de voz aberta por mais tempo do que isto nao e sessao: e resto de
# um `participant_left` que nunca chegou -- servico reiniciado, webhook
# perdido. Somar isso daria a alguem 50 horas por ter esquecido a aba
# aberta durante uma queda.
TETO_SESSAO_VOZ = 12 * 3600


def _contar_voz(evento, sala, uid, agora):
    """Acumula tempo de voz por pessoa, a partir dos webhooks do LiveKit."""
    if not uid or not sala:
        return
    try:
        chave = {"uid": uid, "sala": sala}
        if evento == "participant_joined":
            db.dp_voz_sessoes.update_one(
                chave, {"$set": {"inicio": agora}}, upsert=True)
            return

        sessao = db.dp_voz_sessoes.find_one_and_delete(chave)
        if not sessao:
            return
        delta = agora - float(sessao.get("inicio") or agora)
        if delta <= 0 or delta > TETO_SESSAO_VOZ:
            return
        db.dp_voz_total.update_one(
            {"_id": uid}, {"$inc": {"segundos": delta}}, upsert=True)
    except Exception:
        # Contagem de conquista nunca pode derrubar o webhook: o que esta
        # em jogo do outro lado e a entrada de alguem numa chamada.
        pass


# ================================================== mover de canal
# A API do Stoat nao implementa mover ninguem: a unica rota de voz e
# `join_call`. A permissao `MoveMembers` existe na definicao do cliente e
# nao e usada em lugar nenhum.
#
# Entao o movimento e feito por fora, e a autoridade fica AQUI -- nunca no
# navegador de quem pede. Escrevemos um atributo no participante alvo pela
# API do LiveKit (temos a chave de administrador da sala); o cliente dele
# le esse atributo e se conecta no destino sozinho.
BIT_MOVER = 1 << 35

# Quanto esperamos o cliente obedecer antes de tirar a pessoa da sala.
# Sem isso, "mover" viraria um pedido: um cliente que ignore a ordem
# deixaria o administrador sem poder nenhum. Com isso, ou a pessoa vai
# para o destino, ou sai de onde estava -- o comando vale de um jeito ou
# de outro.
PRAZO_OBEDECER = 8


def pode_mover(uid, servidor):
    """Se este usuario tem MoveMembers neste servidor.

    Le os cargos direto do banco em vez de acreditar no cliente. Ignora
    sobreposicoes por canal de proposito: e uma checagem conservadora --
    quem tem a permissao no servidor pode mover; quem nao tem, nao move,
    mesmo que algum canal especifico lhe desse o direito.
    """
    srv = db.servers.find_one(
        {"_id": servidor},
        {"owner": 1, "roles": 1, "default_permissions": 1})
    if not srv:
        return False
    if srv.get("owner") == uid:
        return True

    membro = db.server_members.find_one(
        {"_id": {"server": servidor, "user": uid}}, {"roles": 1})
    if not membro:
        return False

    perm = int(srv.get("default_permissions") or 0)
    cargos = srv.get("roles") or {}
    meus = [cargos[r] for r in (membro.get("roles") or []) if r in cargos]
    # Do menos importante para o mais importante, que e como o allow/deny
    # de cada cargo se sobrepoe.
    meus.sort(key=lambda c: int(c.get("rank") or 0), reverse=True)
    for c in meus:
        p = c.get("permissions") or {}
        perm = (perm | int(p.get("a") or 0)) & ~int(p.get("d") or 0)

    return bool(perm & BIT_MOVER)


def _cobrar_obediencia(origem, alvo):
    """Tira da sala antiga quem nao atendeu a ordem de mudar de canal."""
    try:
        ps = _chamar("ListParticipants", {"room": origem}, origem)
        ainda = any(p.get("identity") == alvo
                    for p in (ps.get("participants") or []))
        if ainda:
            _chamar("RemoveParticipant",
                    {"room": origem, "identity": alvo}, origem)
    except Exception:
        # A sala pode ter acabado, ou a pessoa ja ter saido por conta
        # propria. Nos dois casos nao ha nada a cobrar.
        pass


def _medidas(uid):
    """Os numeros de uma pessoa. Barato: a base inteira tem centenas de docs."""
    voz = db.dp_voz_total.find_one({"_id": uid}) or {}
    u = db.users.find_one({"_id": uid}, {"relations": 1}) or {}
    amigos = sum(1 for r in (u.get("relations") or [])
                 if r.get("status") == "Friend")
    return {
        "voz_50h": float(voz.get("segundos") or 0),
        "comunidades_5": db.server_members.count_documents({"_id.user": uid}),
        "mensagens_100": db.messages.count_documents({"author": uid}),
        "amigos_10": amigos,
        "primeira_live": int(voz.get("transmissoes") or 0),
    }


def conquistas_de(uid, so_ganhas=False):
    """Estado das conquistas, gravando as que acabaram de ser atingidas.

    A data de conquista e gravada uma vez e nunca recalculada: se alguem
    sair de uma comunidade depois, a conquista continua ganha. Perder o
    que ja foi conquistado por causa de uma mudanca posterior seria uma
    punicao que ninguem pediu.
    """
    medidas = _medidas(uid)
    ganhas = {d["chave"]: d.get("em") for d in db.dp_conquistas.find({"uid": uid})}

    saida = []
    for c in CONQUISTAS:
        valor = medidas.get(c["chave"], 0)
        if c["chave"] not in ganhas and valor >= c["meta"]:
            em = time.time()
            db.dp_conquistas.update_one(
                {"uid": uid, "chave": c["chave"]},
                {"$setOnInsert": {"em": em}}, upsert=True)
            ganhas[c["chave"]] = em

        tem = c["chave"] in ganhas
        if so_ganhas and not tem:
            continue
        item = {"chave": c["chave"], "titulo": c["titulo"],
                "icone": c["icone"], "conquistada": tem,
                "em": ganhas.get(c["chave"])}
        if not so_ganhas:
            item.update({"descricao": c["descricao"], "meta": c["meta"],
                         "valor": valor, "unidade": c["unidade"]})
        saida.append(item)
    return saida


def _perfis(uids):
    """Nome e avatar por id, numa consulta so."""
    fora = {}
    for u in db.users.find({"_id": {"$in": list(set(uids))}},
                           {"username": 1, "avatar": 1, "display_name": 1}):
        fora[u["_id"]] = {
            "nome": u.get("display_name") or u.get("username") or "?",
            "avatar": (u.get("avatar") or {}).get("_id"),
        }
    return fora


def limite_de(uid):
    """Cota individual definida no painel; cai no padrão se não houver."""
    c = db.painel_cotas.find_one({"_id": uid})
    try:
        return int(c["limite"]) if c and "limite" in c else LIMITE
    except (TypeError, ValueError):
        return LIMITE


def saldo(uid):
    usados = db.account_invites.count_documents({"criado_por": uid})
    LIMITE_U = limite_de(uid)
    return {
        "limite": LIMITE_U,
        "usados": usados,
        "disponiveis": max(0, LIMITE_U - usados),
    }


def emitir(uid, origem=None):
    """Emite um convite de conta em nome de uid, respeitando a cota."""
    with trava:
        s = saldo(uid)
        if s["disponiveis"] <= 0:
            return None, s
        codigo = secrets.token_hex(8)
        doc = {"_id": codigo, "criado_por": uid}
        if origem:
            doc["origem"] = origem
        db.account_invites.insert_one(doc)
        return codigo, saldo(uid)



# ------------------------------------------------- LiveKit: estado real
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "http://livekit:7880")

# ---------------------------------------------------------------- repasse
# O LiveKit entrega webhooks EM ORDEM, com uma fila por URL. Quando o
# voice-ingress respondia 500 (acontece na corrida entre sair de um canal
# e os eventos de faixa daquela sala chegarem depois), o LiveKit tentava
# 5 vezes ao longo de 15s -- e tudo que estava atras esperava. O
# participant_joined do canal NOVO ficava parado nesses 15s, entao os
# cards da lista e o seu proprio deslocamento entre canais so apareciam
# muito depois do audio ja estar conectado.
#
# Aqui a entrega e desacoplada: respondemos ao LiveKit na hora e
# repassamos por conta propria. A fila e FIFO com UM trabalhador de
# proposito -- a ordem importa, um track_published chegando antes do
# participant_joined geraria justamente o 500 que queremos evitar.
#
# Sem retentativa: um 500 do voice-ingress aqui significa que o estado
# ja nao existe mais do lado dele. Repetir nao ressuscita nada, so
# reintroduz a espera que motivou este codigo.
INGRESS_URL = os.environ.get("VOICE_INGRESS_URL",
                             "http://voice-ingress:8500/worldwide")
INGRESS_TIMEOUT = 5
INGRESS_FILA_MAX = 500

_ingress_fila = None


LK_KEY = os.environ.get("LIVEKIT_KEY", "")
LK_SECRET = os.environ.get("LIVEKIT_SECRET", "")

# metadata da sala, por nome de sala. Alimentado pelos eventos que a
# trazem; consultado pelos que nao trazem.
_meta_salas = {}


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _assina(corpo):
    """Refaz a assinatura que o voice-ingress confere sobre o corpo.

    O LiveKit assina um JWT cujo claim `sha256` e o resumo do corpo. Se
    mudarmos um byte do corpo, a assinatura antiga deixa de valer -- por
    isso reassinamos com a mesma chave, que ja temos por sermos nos que
    consultamos a API do LiveKit.
    """
    agora = int(time.time())
    cab = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"},
                           separators=(",", ":")).encode())
    carga = _b64u(json.dumps(
        {"iss": LK_KEY, "nbf": agora - 5, "exp": agora + 300,
         "sha256": base64.b64encode(hashlib.sha256(corpo).digest()).decode()},
        separators=(",", ":")).encode())
    sig = _b64u(hmac.new(LK_SECRET.encode(), f"{cab}.{carga}".encode(),
                         hashlib.sha256).digest())
    return f"{cab}.{carga}.{sig}"


def _completa_metadata(corpo, dados):
    """Devolve (corpo, cabecalho_auth) com room.metadata garantida.

    O LiveKit omite `room.metadata` nos eventos de faixa (track_published,
    track_unpublished, track_muted, track_unmuted) -- manda so sid e name.
    O voice-ingress exige a metadata em TODOS os ramos para saber o
    servidor, entao respondia 500 em cada um deles. Eram 172 das 187
    falhas em 24h: nao era corrida, era falta de campo.

    O efeito visivel: a API nunca registrava quem esta com camera, tela
    ou microfone mudo -- os icones de estado na lista ficavam parados.

    A metadata da sala nao muda durante a vida dela, e os eventos de
    entrada e saida a trazem. Guardamos de la e completamos aqui.
    """
    sala = (dados.get("room") or {}).get("name")
    if not sala:
        return corpo, None

    meta = (dados.get("room") or {}).get("metadata")
    if meta:
        if _meta_salas.get(sala) != meta:
            _meta_salas[sala] = meta
            db.chamadas.update_one({"_id": sala}, {"$set": {"metadata": meta}},
                                   upsert=True)
        return corpo, None

    lembrada = _meta_salas.get(sala)
    if lembrada is None:
        doc = db.chamadas.find_one({"_id": sala}, {"metadata": 1})
        lembrada = (doc or {}).get("metadata")
        if lembrada:
            _meta_salas[sala] = lembrada
    if not lembrada or not LK_SECRET:
        return corpo, None

    dados["room"]["metadata"] = lembrada
    novo_corpo = json.dumps(dados, separators=(",", ":")).encode()
    return novo_corpo, _assina(novo_corpo)


def _ingress_trabalhador():
    while True:
        corpo, cabecalhos, evento, dados = _ingress_fila.get()
        try:
            try:
                corpo, auth = _completa_metadata(corpo, dados)
                if auth:
                    cabecalhos = dict(cabecalhos, Authorization=auth)
            except Exception as e:
                print(f"ingress: nao consegui completar {evento} ({e})",
                      flush=True)

            req = urllib.request.Request(INGRESS_URL, data=corpo,
                                         headers=cabecalhos, method="POST")
            with urllib.request.urlopen(req, timeout=INGRESS_TIMEOUT) as r:
                r.read()
        except Exception as e:
            # Registrar e seguir. Este e o unico lugar onde a falha fica
            # visivel agora que o LiveKit nao insiste mais nela.
            print(f"ingress: {evento} recusado pelo voice-ingress ({e})",
                  flush=True)
        finally:
            _ingress_fila.task_done()


def inicia_repasse():
    global _ingress_fila
    _ingress_fila = queue.Queue(maxsize=INGRESS_FILA_MAX)
    threading.Thread(target=_ingress_trabalhador, daemon=True).start()


def enfileira_ingress(corpo, cabecalhos, evento, dados):
    """Enfileira sem nunca bloquear a resposta ao LiveKit."""
    try:
        _ingress_fila.put_nowait((corpo, cabecalhos, evento, dados))
        return True
    except queue.Full:
        # Descartar o mais novo mantem a ordem do que ja esta na fila.
        print(f"ingress: fila cheia, {evento} descartado", flush=True)
        return False
LIVEKIT_KEY = os.environ.get("LIVEKIT_KEY", "")
LIVEKIT_SECRET = os.environ.get("LIVEKIT_SECRET", "")
_cache_faixas = {"em": 0, "dados": {}}


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _token(sala=None):
    """JWT HS256 no formato aceito pelo LiveKit."""
    agora = int(time.time())
    video = {"roomList": True}
    if sala:
        video = {"roomAdmin": True, "room": sala}
    cab = _b64(json.dumps({"alg": "HS256", "typ": "JWT"},
                          separators=(",", ":")).encode())
    corpo = _b64(json.dumps({"iss": LIVEKIT_KEY, "nbf": agora - 5,
                             "exp": agora + 60, "video": video},
                            separators=(",", ":")).encode())
    assin = _b64(hmac.new(LIVEKIT_SECRET.encode(),
                          f"{cab}.{corpo}".encode(), hashlib.sha256).digest())
    return f"{cab}.{corpo}.{assin}"


def _chamar(metodo, corpo, sala=None):
    req = urllib.request.Request(
        f"{LIVEKIT_URL}/twirp/livekit.RoomService/{metodo}",
        data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + _token(sala)})
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read() or b"{}")


def faixas_ao_vivo():
    """Mapa faixa -> participante consultando o LiveKit.

    Montar esse mapa só por webhooks perde tudo que aconteceu antes de o
    serviço começar a escutar — foi o que deixou os participantes já
    conectados sem luz. Aqui o estado vem da fonte, a qualquer momento.
    """
    if not LIVEKIT_KEY or not LIVEKIT_SECRET:
        return None
    if time.time() - _cache_faixas["em"] < 5:
        return _cache_faixas["dados"]
    try:
        salas = _chamar("ListRooms", {}).get("rooms") or []
        mapa = {}
        for s in salas:
            nome = s.get("name")
            if not nome:
                continue
            ps = _chamar("ListParticipants", {"room": nome},
                         sala=nome).get("participants") or []
            for p in ps:
                for t in (p.get("tracks") or []):
                    sid = t.get("sid")
                    if not sid:
                        continue
                    mapa[sid] = {"participante": p.get("identity"),
                                 "fonte": t.get("source") or t.get("type"),
                                 "sala": nome,
                                 "mudo": bool(t.get("muted"))}
        _cache_faixas.update({"em": time.time(), "dados": mapa})
        return mapa
    except Exception as e:
        print(f"livekit: falha ao consultar estado ({e})", flush=True)
        return None



# --------------------------------------------- template do Discord
RE_TEMPLATE = re.compile(r"[A-Za-z0-9_-]{6,32}$")
LIMITE_NOME = 32          # limite de nome de canal na nossa API
TIPOS = {0: "Text", 2: "Voice", 5: "Text"}   # 5 = anúncios vira texto


def corta(txt, n):
    txt = (txt or "").strip()
    return txt[:n] if len(txt) > n else txt


def template_discord(codigo):
    """Busca e normaliza um template público do Discord.

    O navegador não consegue chamar a API do Discord (sem CORS), então o
    proxy é obrigatório. O endpoint é público: não usa token nenhum, o que
    evita o self-botting que ferramentas equivalentes exigem.
    """
    req = urllib.request.Request(
        f"https://discord.com/api/v10/guilds/templates/{codigo}",
        headers={"User-Agent": "DoisPapo/1.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        d = json.loads(r.read())

    g = d.get("serialized_source_guild") or {}
    canais = g.get("channels") or []

    cats = {c["id"]: {"titulo": corta(c.get("name"), LIMITE_NOME),
                      "posicao": c.get("position", 0), "canais": []}
            for c in canais if c.get("type") == 4}
    soltos = []

    for c in sorted(canais, key=lambda x: (x.get("position", 0), x.get("id", 0))):
        tipo = c.get("type")
        if tipo == 4 or tipo not in TIPOS:
            continue
        item = {
            "nome": corta(c.get("name"), LIMITE_NOME),
            "nome_original": c.get("name"),
            "tipo": TIPOS[tipo],
            "descricao": corta(c.get("topic"), 1024) or None,
            "nsfw": bool(c.get("nsfw")),
        }
        pai = c.get("parent_id")
        (cats[pai]["canais"] if pai in cats else soltos).append(item)

    ordenadas = sorted(cats.values(), key=lambda x: x["posicao"])
    return {
        "nome": d.get("name"),
        "origem": g.get("name"),
        "categorias": ordenadas,
        "sem_categoria": soltos,
        "cargos": [{"nome": corta(r.get("name"), LIMITE_NOME),
                    "cor": r.get("color") or 0}
                   for r in (g.get("roles") or [])
                   if r.get("name") != "@everyone"],
        "resumo": {
            "categorias": len(ordenadas),
            "texto": sum(1 for c in canais if c.get("type") in (0, 5)),
            "voz": sum(1 for c in canais if c.get("type") == 2),
            "cargos": max(0, len(g.get("roles") or []) - 1),
            "truncados": sum(
                1 for c in canais
                if c.get("name") and len(c["name"]) > LIMITE_NOME),
        },
    }



# ------------------------------------------- som próprio do servidor
LIMITE_SOM = 512 * 1024      # 512 KB: aviso curto, não trilha sonora

# Os 14 sons que o cliente toca — um `case` para cada, no switch de
# reprodução.
#
# Por um tempo esta lista teve só 10. A regex que a extraía do bundle
# usava \w para o nome da variável minificada, e \w não casa "$":
# unmute, userJoinVoice, userLeaveVoice e userMoved usam e$e, t$e, n$e e
# r$e. Some quatro sons da lista e a conclusão parece ser que eles não
# tocam — mas tocam, e um deles é o de entrar na chamada.
SONS_VALIDOS = ("message",
                "ringtoneIncoming", "ringtoneOutgoing",
                "userJoinVoice", "userLeaveVoice", "userMoved",
                "mute", "unmute", "deafen", "undeafen",
                "streamStart", "streamEnd",
                "streamViewerJoin", "streamViewerLeave")


# 512 KB em base64 ocupam ~700 KB, mais os outros campos do JSON. O
# teto padrao de corpo (8 KB) engoliria todo upload real devolvendo um
# objeto vazio, e o erro apareceria como "som desconhecido".
LIMITE_CORPO_SOM = 1024 * 1024


def chave_som(servidor, som):
    return "%s:%s" % (servidor, som)
TIPOS_SOM = {"audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav",
             "audio/webm": "webm", "audio/mp4": "m4a"}


def dono_do_servidor(uid, servidor):
    """Só o dono troca o som — vale para todos os membros."""
    if not uid or not servidor:
        return False
    s = db.servers.find_one({"_id": servidor}, {"owner": 1})
    return bool(s and s.get("owner") == uid)


# ------------------------------------------------------- Turnstile
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "")
TURNSTILE_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_ok(token, ip=None):
    """Valida o token do Turnstile junto à Cloudflare.

    Sem segredo configurado a verificação é ignorada, para o serviço não
    ficar inacessível caso a chave ainda não tenha sido provisionada.
    """
    if not TURNSTILE_SECRET:
        return True
    if not token or len(token) > 4096:
        return False
    dados = {"secret": TURNSTILE_SECRET, "response": token}
    if ip:
        dados["remoteip"] = ip
    try:
        req = urllib.request.Request(
            TURNSTILE_URL,
            data=urllib.parse.urlencode(dados).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return bool(json.loads(r.read()).get("success"))
    except Exception as e:
        # Falha de rede não pode virar porta aberta: nega e registra.
        print(f"turnstile: falha ao verificar ({e})", flush=True)
        return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # silencia o log padrão, ruidoso
        pass

    def registra(self, status, detalhe=""):
        print(f"{self.command} {self.path} -> {status} {detalhe}", flush=True)

    def responde(self, codigo, corpo):
        self.registra(codigo, corpo.get("erro", "") if isinstance(corpo, dict) else "")
        dados = json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def caminho(self):
        """O caminho da requisição, sem a query string.

        Fatiar `self.path` direto deixa a query grudada no último
        pedaço: "/sons/X/message/audio?v=1" vira [..., "audio?v=1"], o
        ramo do áudio não é reconhecido e a resposta cai no catálogo —
        o navegador recebe JSON onde esperava som. As rotas de
        igualdade têm o mesmo problema: "/saldo?x=1" não casa "/saldo".
        """
        return self.path.split("?", 1)[0]

    def corpo_json(self, limite=8192):
        """Le e decodifica o corpo, ate `limite` bytes.

        O teto padrao e pequeno de proposito: quase todo endpoint aqui
        recebe um punhado de campos, e aceitar corpos grandes sem motivo
        e superficie de abuso. Quem precisa de mais - o envio de som -
        passa o proprio limite e confere o Content-Length antes, para o
        excesso virar 413 em vez de um corpo vazio silencioso.
        """
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > limite:
                return {}
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def corpo_bruto(self, limite=65536):
        """Os bytes do corpo, exatamente como chegaram.

        O voice-ingress confere a assinatura JWT SOBRE O CORPO. Decodificar
        e reserializar muda espacos e ordem de chaves, a assinatura deixa de
        bater e todo evento repassado viraria 401. Por isso o repasse leva
        os bytes originais, e o JSON e lido a partir deles.
        """
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > limite:
                return b""
            return self.rfile.read(n)
        except Exception:
            return b""

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        rota = self.caminho()
        # Proxy do template do Discord. Público dos dois lados: o
        # endpoint do Discord dispensa autenticação, e aqui não há
        # segredo envolvido — só leitura de dado que já é público.
        if rota.startswith("/discord-template"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            bruto = (q.get("codigo") or [""])[0].strip()
            # aceita link completo ou só o código
            bruto = bruto.rstrip("/").split("/")[-1].split("?")[0]
            if not RE_TEMPLATE.match(bruto):
                return self.responde(400, {"erro": "codigo_invalido",
                    "mensagem": "Informe o link ou o código do template."})
            try:
                return self.responde(200, template_discord(bruto))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return self.responde(404, {"erro": "nao_encontrado",
                        "mensagem": "Template não encontrado. Confira o link."})
                return self.responde(502, {"erro": "discord",
                    "mensagem": "O Discord recusou a consulta."})
            except Exception:
                return self.responde(502, {"erro": "indisponivel",
                    "mensagem": "Não foi possível consultar o Discord agora."})

        # Som próprio do servidor: metadados. Público, porque qualquer
        # membro precisa saber que existe para tocá-lo.
        if rota.startswith("/sons/"):
            partes = rota.strip("/").split("/")
            sid = partes[1] if len(partes) > 1 else ""
            if not RE_CODIGO.match(sid or ""):
                return self.responde(400, {"erro": "servidor_invalido"})
            # /sons/{sid}              -> catálogo do servidor
            # /sons/{sid}/{som}/audio  -> os bytes de um som
            if len(partes) > 3 and partes[3] == "audio":
                som = partes[2]
                if som not in SONS_VALIDOS:
                    return self.responde(404, {"erro": "som_desconhecido"})
                doc = db.sons.find_one({"_id": chave_som(sid, som)})
                if not doc:
                    return self.responde(404, {"erro": "sem_som"})
                dados = base64.b64decode(doc["dados"])
                self.send_response(200)
                self.send_header("Content-Type", doc.get("tipo", "audio/mpeg"))
                self.send_header("Content-Length", str(len(dados)))
                # o nome do arquivo não muda; a versão no endereço é que
                # obriga o navegador a buscar de novo após a troca
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(dados)
                return
            sons = {}
            for d in db.sons.find({"servidor": sid}, {"dados": 0}):
                som = d.get("som")
                if som not in SONS_VALIDOS:
                    continue
                v = int(d.get("em", 0))
                sons[som] = {
                    "nome": d.get("nome"), "tipo": d.get("tipo"), "versao": v,
                    "url": f"/api-convites/sons/{sid}/{som}/audio?v={v}"}
            return self.responde(200, {"sons": sons})

        if rota == "/saude":
            return self.responde(200, {"ok": True})

        # Mapa faixa -> participante, para o cliente saber de quem é
        # cada fluxo de áudio que ele está reproduzindo.
        if rota == "/faixas":
            vivo = faixas_ao_vivo()
            if vivo is not None:
                return self.responde(200, {"faixas": vivo, "origem": "livekit"})
            itens = {d["_id"]: {"participante": d.get("participante"),
                                "fonte": d.get("fonte")}
                     for d in db.faixas.find()}
            return self.responde(200, {"faixas": itens, "origem": "eventos"})

        # Chamadas em andamento, para o contador de duração.
        if rota == "/condicoes":
            agora = int(time.time())
            itens = []
            for d in db.dp_condicoes.find():
                idade = agora - int(d.get("em") or 0)
                # Mais de dois minutos parado nao e medicao, e lembranca.
                if idade > 120:
                    continue
                itens.append({"usuario": d["_id"], "ha_s": idade,
                              "sala": d.get("sala"), "fps": d.get("fps"),
                              "altura": d.get("altura"),
                              "limite": d.get("limite"),
                              "msQuadro": d.get("msQuadro"),
                              "pausado": d.get("pausado"),
                              "capturaFps": d.get("capturaFps"),
                              "segCpu": d.get("segCpu"),
                              "segBanda": d.get("segBanda"),
                              "motor": d.get("motor"),
                              "codec": d.get("codec"),
                              "app": d.get("app")})
            return self.responde(200, {"transmissores": itens})

        if rota == "/chamadas":
            itens = {
                d["_id"]: {"inicio": d.get("inicio"),
                           "participantes": d.get("participantes", 0)}
                for d in db.chamadas.find({"encerrada": {"$ne": True}})
                if d.get("inicio")
            }
            return self.responde(200, {"chamadas": itens})

        # Lista da fila de espera — só para o administrador da instância.
        if rota == "/fila":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid or (ADMIN_UID and uid != ADMIN_UID):
                return self.responde(403, {"erro": "sem_permissao"})
            itens = [
                {"nome": d.get("nome"), "email": d["_id"],
                 "nascimento": d.get("nascimento"),
                 "idade": d.get("idade"),
                 "em": d.get("em"), "convidado": bool(d.get("convidado"))}
                for d in db.fila_espera.find().sort("em", 1)
            ]
            return self.responde(200, {"total": len(itens), "itens": itens})

        # ------------------------------------------------ meus envios
        # A pessoa precisa poder ver o que mandou e no que deu. Sem isso
        # o formulario e um buraco: escreve, envia, e nunca sabe se foi
        # lido -- que e exatamente o que os links para fora faziam.
        if rota == "/feedback/meus":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            itens = [
                {"id": str(d["_id"]), "tipo": d.get("tipo"),
                 "titulo": d.get("titulo"), "texto": d.get("texto"),
                 "estado": d.get("estado", "recebido"),
                 "resposta": d.get("resposta"),
                 "respondido_em": d.get("respondido_em"),
                 "em": d.get("em")}
                for d in db.dp_feedback.find({"uid": uid}).sort("em", -1).limit(100)
            ]
            return self.responde(200, {"itens": itens})

        # ------------------------------------------------ conquistas
        # Duas leituras diferentes de proposito: a sua propria mostra o
        # progresso de tudo, inclusive do que falta; a de outra pessoa
        # mostra so o que ela ja tem. Progresso alheio e informacao que
        # ninguem pediu para expor -- "faltam 3 amigos para o fulano" nao
        # e assunto de terceiros.
        if rota == "/conquistas":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            return self.responde(200, {"itens": conquistas_de(uid)})

        m = re.fullmatch(r"/conquistas/([0-9A-Z]{26})", rota)
        if m:
            if not usuario_da_sessao(self.headers.get("X-Session-Token")):
                return self.responde(401, {"erro": "sessao_invalida"})
            return self.responde(
                200, {"itens": conquistas_de(m.group(1), so_ganhas=True)})

        # ------------------------------------------------- novidades
        if rota == "/novidades":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                antes = float((q.get("antes") or [0])[0])
            except (TypeError, ValueError):
                antes = 0
            filtro = {"publicado": True}
            if antes:
                filtro["em"] = {"$lt": antes}
            posts = list(db.dp_novidades.find(filtro).sort("em", -1).limit(20))
            ids = [d["_id"] for d in posts]
            # Uma consulta para saber o que ESTE usuario curtiu, em vez de
            # uma por post.
            curtidos = {c["post"] for c in db.dp_novidades_curtidas.find(
                {"post": {"$in": ids}, "uid": uid}, {"post": 1})}
            itens = [
                {"id": str(d["_id"]), "texto": d.get("texto", ""),
                 "em": d.get("em"), "titulo": d.get("titulo"),
                 "curtidas": int(d.get("curtidas", 0)),
                 "curti": d["_id"] in curtidos,
                 "comentarios": int(d.get("comentarios", 0))}
                for d in posts
            ]
            return self.responde(200, {"itens": itens})

        m = re.fullmatch(r"/novidades/([0-9a-f]{24})/comentarios", rota)
        if m:
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            try:
                pid = ObjectId(m.group(1))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            docs = list(db.dp_novidades_comentarios
                        .find({"post": pid, "removido": {"$ne": True}})
                        .sort("em", 1).limit(200))
            perfis = _perfis([d["uid"] for d in docs])
            itens = [
                {"id": str(d["_id"]), "texto": d.get("texto", ""),
                 "em": d.get("em"), "uid": d["uid"], "meu": d["uid"] == uid,
                 "autor": perfis.get(d["uid"], {"nome": "?", "avatar": None})}
                for d in docs
            ]
            return self.responde(200, {"itens": itens})

        if rota == "/saldo":
            tok = self.headers.get("X-Session-Token")
            uid = usuario_da_sessao(tok)
            if not uid:
                return self.responde(401, {
                    "erro": "sessao_invalida",
                    "token_enviado": bool(tok)})
            s = saldo(uid)
            s["codigos"] = [
                {"codigo": d["_id"], "usado": bool(d.get("used"))}
                for d in db.account_invites.find({"criado_por": uid})
            ]
            return self.responde(200, s)

        self.responde(404, {"erro": "nao_encontrado"})

    # --------------------------------------------------------------- POST
    def do_POST(self):
        rota = self.caminho()
        # Webhook do LiveKit: registra início e fim das chamadas.
        # Não é exposto pelo Caddy — o LiveKit chama pela rede interna.
        if rota == "/livekit":
            bruto = self.corpo_bruto()
            try:
                c = json.loads(bruto or b"{}")
            except Exception:
                c = {}
            evento = c.get("event")

            # Primeiro o repasse, depois a nossa contabilidade: o estado de
            # voz da API e o que desenha os cards da lista, e nao pode ficar
            # atras de uma escrita nossa no Mongo.
            cabecalhos = {"Content-Type": self.headers.get(
                "Content-Type", "application/webhook+json")}
            if self.headers.get("Authorization"):
                cabecalhos["Authorization"] = self.headers["Authorization"]
            enfileira_ingress(bruto, cabecalhos, evento or "?", c)

            sala = (c.get("room") or {}).get("name")
            if not sala:
                return self.responde(200, {"ok": True})
            agora = time.time()
            if evento == "room_started":
                db.chamadas.update_one(
                    {"_id": sala},
                    {"$set": {"inicio": agora, "encerrada": False}},
                    upsert=True)
            elif evento == "room_finished":
                db.chamadas.update_one({"_id": sala},
                    {"$set": {"encerrada": True, "fim": agora}})
            # track_published traz o par (faixa, participante) — é o que
            # permite ao navegador saber de quem é cada fluxo de áudio.
            # O cliente só enxerga o identificador da faixa; quem sabe o
            # dono é o servidor.
            elif evento in ("track_published", "track_unpublished"):
                faixa = (c.get("track") or {}).get("sid")
                quem = (c.get("participant") or {}).get("identity")
                tipo = (c.get("track") or {}).get("source") or ""
                if faixa:
                    if evento == "track_published" and quem:
                        db.faixas.update_one({"_id": faixa}, {"$set": {
                            "participante": quem, "sala": sala,
                            "fonte": tipo, "em": agora}}, upsert=True)
                        # Transmitir a tela e o que o produto existe para
                        # fazer: vale registrar quem ja fez pelo menos uma.
                        if "screen" in tipo.lower():
                            db.dp_voz_total.update_one(
                                {"_id": quem},
                                {"$inc": {"transmissoes": 1}}, upsert=True)
                    else:
                        db.faixas.delete_one({"_id": faixa})
            elif evento in ("participant_joined", "participant_left"):
                n = (c.get("room") or {}).get("numParticipants", 0)
                db.chamadas.update_one({"_id": sala},
                    {"$set": {"participantes": n}}, upsert=True)
                _contar_voz(evento, sala,
                            (c.get("participant") or {}).get("identity"),
                            agora)
            return self.responde(200, {"ok": True})

        # ------------------------------------ quem esta assistindo o que
        # O cliente NAO consegue publicar isso sozinho: o token que a API
        # emite vem com `canUpdateOwnMetadata: false`, entao o
        # `setAttributes` do navegador e recusado pelo LiveKit. Quem tem a
        # chave de administrador da sala somos nos -- entao o navegador
        # avisa aqui, e daqui o atributo e escrito em nome da pessoa.
        #
        # A propagacao continua sendo a nativa: escrito o atributo, o
        # LiveKit avisa a sala inteira, e quem entrar depois ja recebe o
        # valor atual.
        if rota == "/assistindo":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            c = self.corpo_json(limite=4096)
            sala = (c.get("sala") or "").strip()
            faixas = c.get("faixas") or []
            if not sala or not isinstance(faixas, list):
                return self.responde(400, {"erro": "campos_obrigatorios"})
            # Ids de faixa do LiveKit, e no maximo os de uma tela cheia de
            # quadros. O limite existe para o atributo nao virar um campo
            # de texto livre escrito pelo navegador.
            limpas = [f for f in faixas
                      if isinstance(f, str) and re.fullmatch(r"TR_[A-Za-z0-9]{1,32}", f)][:24]
            try:
                _chamar("UpdateParticipant",
                        {"room": sala, "identity": uid,
                         "attributes": {"dp_assistindo": ",".join(limpas)}},
                        sala)
            except Exception:
                # Nao e erro do usuario, e nao ha o que ele faca: quem nao
                # esta mais na sala simplesmente nao tem atributo para
                # atualizar.
                return self.responde(200, {"ok": False})
            return self.responde(200, {"ok": True})

        # ------------------------------ como esta indo quem transmite
        # `qualityLimitationReason` e `totalEncodeTime` sao estatisticas
        # do codificador de quem transmite. Nao existem no servidor, nao
        # existem para quem assiste, e nenhuma metrica do LiveKit as
        # alcanca -- o LiveKit ve pacotes chegando, nao ve o navegador
        # decidindo largar quadros porque o processador nao deu conta.
        #
        # Sem isto aqui, diagnosticar "esta travando" depende de pedir
        # para a pessoa abrir o webrtc-internals e ler em voz alta.
        if rota == "/condicoes":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            c = self.corpo_json(limite=1024)

            def numero(v, teto):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return None
                return v if 0 <= v <= teto else None

            def texto(v, tamanho):
                # Nome de codec e de motor de codificacao. Fecha o
                # conjunto de caracteres: e texto vindo do navegador.
                if not isinstance(v, str):
                    return None
                v = v.strip()[:tamanho]
                return v if re.fullmatch(r"[A-Za-z0-9 ._/+-]*", v) else None

            limite = c.get("limite")
            if limite not in ("cpu", "banda", "outro"):
                limite = None

            db.dp_condicoes.update_one(
                {"_id": uid},
                {"$set": {"em": int(time.time()),
                          "sala": (c.get("sala") or "")[:32],
                          "fps": numero(c.get("fps"), 120),
                          "altura": numero(c.get("altura"), 4320),
                          "limite": limite,
                          "msQuadro": numero(c.get("msQuadro"), 10000),
                          "pausado": bool(c.get("pausado")),
                          "capturaFps": numero(c.get("capturaFps"), 240),
                          "segCpu": numero(c.get("segCpu"), 86400),
                          "segBanda": numero(c.get("segBanda"), 86400),
                          "motor": texto(c.get("motor"), 48),
                          "codec": texto(c.get("codec"), 16),
                          "app": bool(c.get("app"))}},
                upsert=True)
            return self.responde(200, {"ok": True})

        # --------------------------------------- mover alguem de canal
        if rota == "/mover":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            c = self.corpo_json(limite=2048)
            alvo = (c.get("usuario") or "").strip()
            destino = (c.get("canal") or "").strip()
            if not re.fullmatch(r"[0-9A-Z]{26}", alvo or "") or \
               not re.fullmatch(r"[0-9A-Z]{26}", destino or ""):
                return self.responde(400, {"erro": "campos_obrigatorios"})

            canal = db.channels.find_one({"_id": destino},
                                         {"voice": 1, "server": 1})
            # `"voice" in canal`, e NAO `canal.get("voice")`.
            #
            # No banco a marca de canal de voz e um documento vazio:
            # `voice: {}`. Em Python o dicionario vazio e falso, entao o
            # teste por valor recusava TODO canal de voz com
            # "canal_nao_e_de_voz" -- a rota inteira era inalcancavel, e o
            # defeito ficou escondido atras de um arrasto que tambem nao
            # funcionava. O que existe aqui e a chave, nao o conteudo.
            if not canal or "voice" not in canal:
                return self.responde(400, {"erro": "canal_nao_e_de_voz"})

            if not pode_mover(uid, canal.get("server")):
                return self.responde(403, {"erro": "sem_permissao"})

            # Onde a pessoa esta agora. As sessoes de voz sao alimentadas
            # pelos webhooks do LiveKit, entao esta e a verdade do SFU --
            # nao um palpite do navegador de quem pediu.
            # Mais recente primeiro: se um resto de sessao sobreviver a
            # uma queda, e a entrada atual que manda.
            sessao = db.dp_voz_sessoes.find_one({"uid": alvo},
                                                sort=[("inicio", -1)])
            if not sessao:
                return self.responde(409, {"erro": "nao_esta_em_voz"})
            origem = sessao.get("sala")
            if origem == destino:
                return self.responde(200, {"ok": True, "ja_estava": True})

            # A ordem viaja como atributo do participante: o cliente dele
            # ja escuta mudanca de atributo por causa do "quem esta
            # assistindo", entao nao ha canal novo a inventar. O carimbo
            # evita que uma reconexao releia a ordem antiga e mova a
            # pessoa de novo.
            try:
                _chamar("UpdateParticipant",
                        {"room": origem, "identity": alvo,
                         "attributes": {
                             "dp_mover": "%s:%d" % (destino, int(time.time()))
                         }},
                        origem)
            except Exception:
                return self.responde(502, {"erro": "sfu_indisponivel"})

            threading.Timer(PRAZO_OBEDECER, _cobrar_obediencia,
                            (origem, alvo)).start()
            return self.responde(200, {"ok": True})

        # ------------------------------------------- enviar feedback
        if rota == "/feedback":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            c = self.corpo_json(limite=16384)
            tipo = c.get("tipo")
            if tipo not in TIPOS_FEEDBACK:
                return self.responde(400, {"erro": "tipo_invalido"})
            titulo = _texto(c.get("titulo"), LIMITE_TITULO)
            texto = _texto(c.get("texto"), LIMITE_TEXTO)
            if not titulo or not texto:
                return self.responde(400, {"erro": "campos_obrigatorios"})
            if _excedeu(db.dp_feedback, uid, TETO_FEEDBACK_HORA):
                return self.responde(429, {"erro": "muitos_envios"})
            doc = {"uid": uid, "tipo": tipo, "titulo": titulo,
                   "texto": texto, "em": time.time(),
                   "estado": "recebido", "resposta": None,
                   "respondido_em": None}
            r = db.dp_feedback.insert_one(doc)
            return self.responde(200, {"ok": True, "id": str(r.inserted_id)})

        # -------------------------------------------- curtir novidade
        m = re.fullmatch(r"/novidades/([0-9a-f]{24})/curtir", rota)
        if m:
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            try:
                pid = ObjectId(m.group(1))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            if not db.dp_novidades.find_one({"_id": pid, "publicado": True},
                                            {"_id": 1}):
                return self.responde(404, {"erro": "nao_encontrado"})
            # A chave composta e o que torna a curtida idempotente: dois
            # cliques rapidos, ou dois dispositivos, nao viram duas.
            chave = {"_id": f"{pid}:{uid}"}
            if db.dp_novidades_curtidas.find_one(chave, {"_id": 1}):
                db.dp_novidades_curtidas.delete_one(chave)
                delta, curti = -1, False
            else:
                db.dp_novidades_curtidas.insert_one(
                    dict(chave, post=pid, uid=uid, em=time.time()))
                delta, curti = 1, True
            db.dp_novidades.update_one({"_id": pid}, {"$inc": {"curtidas": delta}})
            d = db.dp_novidades.find_one({"_id": pid}, {"curtidas": 1})
            # O contador e denormalizado; se algum dia divergir, a verdade
            # esta na colecao de curtidas. Nunca deixamos passar negativo.
            total = max(0, int((d or {}).get("curtidas", 0)))
            return self.responde(200, {"ok": True, "curti": curti,
                                       "curtidas": total})

        # ---------------------------------------- comentar novidade
        m = re.fullmatch(r"/novidades/([0-9a-f]{24})/comentarios", rota)
        if m:
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            try:
                pid = ObjectId(m.group(1))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            if not db.dp_novidades.find_one({"_id": pid, "publicado": True},
                                            {"_id": 1}):
                return self.responde(404, {"erro": "nao_encontrado"})
            c = self.corpo_json(limite=8192)
            texto = _texto(c.get("texto"), LIMITE_COMENTARIO)
            if not texto:
                return self.responde(400, {"erro": "texto_obrigatorio"})
            if _excedeu(db.dp_novidades_comentarios, uid, TETO_COMENTARIO_HORA):
                return self.responde(429, {"erro": "muitos_envios"})
            r = db.dp_novidades_comentarios.insert_one(
                {"post": pid, "uid": uid, "texto": texto,
                 "em": time.time(), "removido": False})
            db.dp_novidades.update_one({"_id": pid}, {"$inc": {"comentarios": 1}})
            return self.responde(200, {"ok": True, "id": str(r.inserted_id)})

        # ------------------------------- remover o proprio comentario
        m = re.fullmatch(r"/novidades/([0-9a-f]{24})/comentarios/"
                         r"([0-9a-f]{24})/remover", rota)
        if m:
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            try:
                pid, cid = ObjectId(m.group(1)), ObjectId(m.group(2))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            # A remocao e marcada, nao apagada: o painel precisa poder ver
            # o que existiu ao tratar uma denuncia.
            r = db.dp_novidades_comentarios.update_one(
                {"_id": cid, "post": pid, "uid": uid, "removido": {"$ne": True}},
                {"$set": {"removido": True, "removido_em": time.time()}})
            if r.modified_count:
                db.dp_novidades.update_one({"_id": pid},
                                           {"$inc": {"comentarios": -1}})
            return self.responde(200, {"ok": True})

        # Enviar ou remover o som do servidor. Exige ser o dono.
        if rota.startswith("/sons/"):
            sid = rota.strip("/").split("/")[1]
            # Cada ramo do do_POST le o proprio corpo: o `c` do ramo do
            # webhook nao existe aqui. Ler ANTES de responder 401/403
            # tambem evita fechar a conexao com o corpo pela metade, o
            # que o navegador mostra como erro de rede em vez do status.
            tam = int(self.headers.get("Content-Length", "0") or 0)
            if tam > LIMITE_CORPO_SOM:
                return self.responde(413, {"erro": "muito_grande",
                    "mensagem": "O arquivo precisa ter menos de 512 KB."})
            c = self.corpo_json(LIMITE_CORPO_SOM)
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            if not dono_do_servidor(uid, sid):
                return self.responde(403, {
                    "erro": "sem_permissao",
                    "mensagem": "Só o dono do servidor pode trocar o som."})

            som = (c.get("som") or "").strip()
            if som not in SONS_VALIDOS:
                return self.responde(400, {
                    "erro": "som_desconhecido",
                    "mensagem": "Som desconhecido."})

            if c.get("remover"):
                db.sons.delete_one({"_id": chave_som(sid, som)})
                return self.responde(200, {"ok": True, "removido": True})

            dados = c.get("dados") or ""
            tipo = (c.get("tipo") or "").split(";")[0].strip().lower()
            nome = (c.get("nome") or "som")[:60]
            if tipo not in TIPOS_SOM:
                return self.responde(415, {"erro": "tipo_invalido",
                    "mensagem": "Envie um arquivo MP3, OGG, WAV ou M4A."})
            try:
                bruto = base64.b64decode(dados, validate=True)
            except Exception:
                return self.responde(400, {"erro": "dados_invalidos"})
            if not bruto or len(bruto) > LIMITE_SOM:
                return self.responde(413, {"erro": "muito_grande",
                    "mensagem": "O arquivo precisa ter menos de 512 KB."})

            db.sons.update_one({"_id": chave_som(sid, som)}, {"$set": {
                "servidor": sid, "som": som,
                "dados": base64.b64encode(bruto).decode(),
                "tipo": tipo, "nome": nome, "por": uid,
                "em": int(time.time())}}, upsert=True)
            return self.responde(200, {"ok": True, "tamanho": len(bruto)})

        # Inscrição na fila de espera. Endpoint público — vem da landing.
        if rota == "/fila":
            c = self.corpo_json()
            nome = (c.get("nome") or "").strip()[:80]
            email = (c.get("email") or "").strip().lower()[:120]
            nasc = (c.get("nascimento") or "").strip()

            ip = self.headers.get("X-Forwarded-For",
                                  self.client_address[0]).split(",")[0].strip()
            if not turnstile_ok(c.get("turnstile"), ip):
                return self.responde(403, {"erro": "captcha",
                    "mensagem": "Verificação de segurança falhou. "
                                "Recarregue a página e tente de novo."})

            if len(nome) < 2:
                return self.responde(400, {"erro": "nome_invalido",
                    "mensagem": "Informe seu nome."})
            if not RE_EMAIL.match(email):
                return self.responde(400, {"erro": "email_invalido",
                    "mensagem": "Informe um e-mail válido."})
            if not RE_DATA.match(nasc):
                return self.responde(400, {"erro": "data_invalida",
                    "mensagem": "Informe sua data de nascimento."})
            try:
                anos = idade(nasc)
            except Exception:
                return self.responde(400, {"erro": "data_invalida",
                    "mensagem": "Data de nascimento inválida."})
            if anos < 13 or anos > 120:
                return self.responde(422, {"erro": "idade_invalida",
                    "mensagem": "É preciso ter ao menos 13 anos."})

            # e-mail é a chave: reinscrever apenas atualiza os dados e
            # preserva a posição original na fila
            ja = db.fila_espera.find_one({"_id": email})
            if ja:
                db.fila_espera.update_one({"_id": email},
                    {"$set": {"nome": nome, "nascimento": nasc,
                              "idade": anos}})
                pos = db.fila_espera.count_documents(
                    {"em": {"$lte": ja.get("em", 0)}})
                return self.responde(200, {"ja_inscrito": True,
                    "posicao": pos,
                    "mensagem": "Você já está na fila. Seus dados foram "
                                "atualizados."})

            agora = time.time()
            db.fila_espera.insert_one({
                "_id": email, "nome": nome, "nascimento": nasc,
                "idade": anos, "em": agora, "convidado": False})
            pos = db.fila_espera.count_documents({"em": {"$lte": agora}})
            return self.responde(200, {"posicao": pos,
                "mensagem": "Pronto! Avisaremos assim que abrirmos vagas."})

        # Gera um convite para o próprio usuário autenticado.
        if rota == "/gerar":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            codigo, s = emitir(uid)
            if not codigo:
                return self.responde(409, dict(s, erro="sem_cota"))
            return self.responde(200, dict(s, codigo=codigo))

        # Troca um convite de SERVIDOR por um convite de CONTA, debitando
        # a cota de quem criou o convite de servidor. Não exige sessão:
        # é justamente o caso de quem ainda não tem conta.
        if rota == "/resgatar":
            codigo_srv = (self.corpo_json().get("codigo") or "").strip()
            if not RE_CODIGO.match(codigo_srv):
                return self.responde(400, {"erro": "codigo_invalido"})

            conv = db.channel_invites.find_one({"_id": codigo_srv})
            if not conv:
                return self.responde(404, {"erro": "convite_inexistente"})

            criador = conv.get("creator")
            if not criador:
                return self.responde(422, {"erro": "convite_sem_autor"})

            # Reaproveita: um convite de servidor gera no máximo um convite
            # de conta. Sem isso, chamadas repetidas drenariam a cota.
            ja = db.account_invites.find_one(
                {"origem": codigo_srv, "used": {"$ne": True}})
            if ja:
                return self.responde(200, {"codigo": ja["_id"],
                                           "reaproveitado": True})

            codigo, s = emitir(criador, origem=codigo_srv)
            if not codigo:
                u = db.users.find_one({"_id": criador}, {"username": 1}) or {}
                return self.responde(409, {
                    "erro": "sem_cota",
                    "convidou": u.get("username"),
                    "mensagem": "Quem te convidou não tem mais convites "
                                "disponíveis.",
                })
            return self.responde(200, dict(s, codigo=codigo))

        self.responde(404, {"erro": "nao_encontrado"})


if __name__ == "__main__":
    db.account_invites.create_index("criado_por")
    db.fila_espera.create_index("em")
    db.chamadas.create_index("encerrada")
    db.faixas.create_index("sala")
    db.account_invites.create_index("origem")
    print(f"servico de convites em :{PORTA} (limite {LIMITE})", flush=True)
    inicia_repasse()
    inicia_metricas()
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
