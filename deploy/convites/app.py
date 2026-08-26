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
import unicodedata
import urllib.request, urllib.parse, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

LIMITE = int(os.environ.get("LIMITE_CONVITES", "5"))
MONGO  = os.environ.get("MONGO_URL", "mongodb://database:27017")
PORTA  = int(os.environ.get("PORTA", "8600"))
# Teto de conexoes simultaneas. 128 casa com o backlog do listen(): nao
# adianta aceitar mais rapido do que se atende. O custo de uma thread
# parada e a pilha dela, entao o numero e generoso o bastante para o
# catalogo (que dispara varias requisicoes ao abrir) e baixo o bastante
# para que um flood encontre um limite em vez de encontrar o fim da RAM.
TETO_THREADS = int(os.environ.get("TETO_THREADS", "128"))
_ocupado = json.dumps({"erro": "ocupado",
    "mensagem": "Serviço ocupado. Tente de novo em instantes."},
    ensure_ascii=False).encode()
RECUSA_OCUPADO = (
    b"HTTP/1.1 503 Service Unavailable\r\n"
    b"Content-Type: application/json; charset=utf-8\r\n"
    b"Content-Length: " + str(len(_ocupado)).encode() + b"\r\n"
    b"Retry-After: 2\r\n"
    b"Cache-Control: no-store\r\n"
    b"Connection: close\r\n\r\n" + _ocupado)

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

# ManageServer -- o bit 1. E a permissao que ja governa as abas "Visao
# geral", "Convites" e "Banimentos" das configuracoes do servidor. Quem
# hoje cria um link de convite passa a poder mexer na vitrine: e a mesma
# autoridade exercida por outro caminho, e nao um conceito novo.
BIT_GERIR_SERVIDOR = 1 << 1

# O que o dono recebe. Mesmo valor do cliente (`GrantAllSafe`).
CONCEDE_TUDO = 0x000F_FFFF_FFFF_FFFF

# Quanto esperamos o cliente obedecer antes de tirar a pessoa da sala.
# Sem isso, "mover" viraria um pedido: um cliente que ignore a ordem
# deixaria o administrador sem poder nenhum. Com isso, ou a pessoa vai
# para o destino, ou sai de onde estava -- o comando vale de um jeito ou
# de outro.
PRAZO_OBEDECER = 8


def permissao_no_servidor(uid, servidor):
    """A permissao efetiva de uid neste servidor, ou None se nao ha vinculo.

    Le os cargos direto do banco em vez de acreditar no cliente. Ignora
    sobreposicoes por canal de proposito: e uma checagem conservadora --
    quem tem a permissao no servidor a tem; quem nao tem, nao a tem,
    mesmo que algum canal especifico lhe desse o direito.

    A distincao entre None e 0 importa: None e "nao e membro, ou o
    servidor nao existe", e quem recebe None nao pode nem saber que o
    servidor existe. 0 e "e membro e nao pode nada".
    """
    srv = db.servers.find_one(
        {"_id": servidor},
        {"owner": 1, "roles": 1, "default_permissions": 1})
    if not srv:
        return None
    if srv.get("owner") == uid:
        return CONCEDE_TUDO

    membro = db.server_members.find_one(
        {"_id": {"server": servidor, "user": uid}}, {"roles": 1})
    if not membro:
        return None

    perm = int(srv.get("default_permissions") or 0)
    cargos = srv.get("roles") or {}
    meus = [cargos[r] for r in (membro.get("roles") or []) if r in cargos]
    # Do menos importante para o mais importante, que e como o allow/deny
    # de cada cargo se sobrepoe. `rank` MENOR e o cargo mais importante,
    # entao a ordenacao e invertida para o mais importante sobrepor por
    # ultimo.
    meus.sort(key=lambda c: int(c.get("rank") or 0), reverse=True)
    for c in meus:
        p = c.get("permissions") or {}
        perm = (perm | int(p.get("a") or 0)) & ~int(p.get("d") or 0)

    return perm


def tem_permissao(uid, servidor, bit):
    """Se uid tem este bit neste servidor."""
    perm = permissao_no_servidor(uid, servidor)
    return bool(perm is not None and perm & bit)


def pode_mover(uid, servidor):
    """Se este usuario tem MoveMembers neste servidor.

    Caso particular de tem_permissao. Mantido com nome proprio porque e
    assim que a rota /mover le, e porque o nome diz o que a checagem
    significa naquele lugar.
    """
    return tem_permissao(uid, servidor, BIT_MOVER)


# ============================================== vitrine da comunidade
#
# Visibilidade, categoria e tags -- o que o catalogo publico le.
#
# Vive em `dp_comunidade` e NAO no documento do servidor, por dois motivos
# apurados no codigo:
#
#   1. `PATCH /servers/{id}` da API tem schema fechado; campo nosso seria
#      recusado, e escrever direto no documento seria passar por cima da
#      API que e dona dele.
#   2. `servers.categories` ja significa "categorias de CANAIS" -- o nome
#      esta ocupado, e reusa-lo produziria confusao na primeira manutencao.
#
# O `discoverable` nativo tambem nao serve: a API so o aceita de quem tem a
# flag `privileged`, que vale para a instancia INTEIRA. Testado contra a
# producao em 26/08: 403 NotPrivileged ate para o dono da comunidade.
CATEGORIA_PADRAO = "geral"
MAX_TAGS = 5
RE_TAG = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")

# Quanto tempo alguem rejeitado espera antes de poder pedir de novo.
# Menos que isso vira insistencia que o administrador tem de suportar;
# mais vira banimento disfarcado, sem ninguem ter escolhido banir.
CARENCIA_REJEICAO = 7 * 24 * 3600

# Tetos de pedido. Nao sao defesa contra abuso coordenado -- a instancia e
# fechada por convite --, e sim contra script e contra o dedo preso no
# botao. Os numeros saem da escala real:
#
#   PENDENTES: ha 3 comunidades hoje. Cinco cobre pedir para todas com
#   folga, e ainda impede uma conta de pedir para o catalogo inteiro.
#   Quando o catalogo passar de ~30, sobe ESTE, nao o diario.
#
#   DIA: um humano explorando o catalogo com calma nao chega perto. Um
#   script chega em segundos.
TETO_PENDENTES = 5
TETO_PEDIDOS_DIA = 20

# A API do Stoat, pela rede interna do compose.
API_STOAT = os.environ.get("API_STOAT", "http://api:14702")

# Cartoes por pagina do catalogo. Teto separado do padrao para o cliente
# nao poder pedir a colecao inteira numa requisicao so.
PAGINA_CATALOGO = 24
PAGINA_MAXIMA = 48


def sem_acento(t):
    """Minusculas, sem acento. E o que entra em busca e em etiqueta."""
    t = unicodedata.normalize("NFKD", (t or "").strip().lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _normaliza_tags(bruto):
    """Aceita lista ou texto com virgulas. Devolve (tags, erro).

    Tira acento de proposito: a tag vai virar filtro na URL do catalogo, e
    e melhor decidir isso agora do que descobrir depois com link publicado.
    """
    if bruto is None:
        return [], None
    if isinstance(bruto, str):
        bruto = bruto.replace(";", ",").split(",")
    if not isinstance(bruto, list):
        return None, "tags_invalidas"
    vistas, saida = set(), []
    for t in bruto:
        if not isinstance(t, str):
            return None, "tags_invalidas"
        t = re.sub(r"[^a-z0-9-]+", "-", sem_acento(t)).strip("-")[:20]
        if not t:
            continue
        if not RE_TAG.match(t) or t in vistas:
            continue
        vistas.add(t)
        saida.append(t)
        if len(saida) > MAX_TAGS:
            return None, "tags_demais"
    return saida, None


def categoria_valida(slug):
    return bool(slug and db.dp_categorias.find_one(
        {"_id": slug, "ativa": True}, {"_id": 1}))


def vitrine_de(servidor):
    """O estado da vitrine, com padroes para quem ainda nao tem linha."""
    d = db.dp_comunidade.find_one({"_id": servidor}) or {}
    return {
        "publica": bool(d.get("publica")),
        "categoria": d.get("categoria") or CATEGORIA_PADRAO,
        "tags": list(d.get("tags") or []),
        "membros": int(d.get("membros") or 0),
    }


def denormaliza(sid):
    """Copia nome e contagem de membros do servidor para a nossa linha.

    O catalogo ordena por tamanho e busca por nome. Fazer isso com
    $lookup em `servers` a cada pagina seria caro e, pior, impossivel de
    indexar junto com `publica` e `categoria`. Entao os dois campos vivem
    denormalizados aqui.

    NAO sao a verdade -- a verdade e `servers.name` e a contagem de
    `server_members`. Divergencia num cartao e aceitavel; o laco de fundo
    reconcilia, e toda escrita na vitrine passa por aqui.
    """
    srv = db.servers.find_one({"_id": sid}, {"name": 1}) or {}
    nome = srv.get("name") or ""
    return {
        "nome": nome,
        "nome_busca": sem_acento(nome),
        "membros": db.server_members.count_documents({"_id.server": sid}),
        "membros_em": time.time(),
    }


def _laco_vitrine():
    """Reconcilia nome e contagem das comunidades publicas.

    So as publicas: sao as unicas que aparecem em cartao, e o indice
    parcial ja as separa. Hoje sao zero ou tres documentos.
    """
    while True:
        time.sleep(300)
        try:
            for d in db.dp_comunidade.find({"publica": True}, {"_id": 1}):
                db.dp_comunidade.update_one(
                    {"_id": d["_id"]}, {"$set": denormaliza(d["_id"])})
            _reconcilia_solicitacoes()
        except Exception as e:
            # Reconciliacao nao e funcionalidade: se falhar, o cartao fica
            # com um numero velho ate a proxima volta.
            print(f"vitrine: reconciliacao falhou ({e})", flush=True)


def inicia_vitrine():
    threading.Thread(target=_laco_vitrine, daemon=True).start()


def estado_para(uid, sid):
    """O que o botao do cartao deve dizer para esta pessoa.

    Decidido AQUI e nao no navegador. E o que impede a interface de
    oferecer "solicitar entrada" para quem esta banido -- o cliente
    apenas desenha o que este calculo devolveu.
    """
    if db.server_members.find_one(
            {"_id": {"server": sid, "user": uid}}, {"_id": 1}):
        return "membro", {}
    if db.server_bans.find_one(
            {"_id": {"server": sid, "user": uid}}, {"_id": 1}):
        return "banido", {}

    # A mais recente, nao "alguma": o historico guarda rejeicoes antigas.
    s = db.dp_solicitacoes.find_one(
        {"servidor": sid, "usuario": uid}, sort=[("em", -1)])
    if s:
        if s.get("estado") == "PENDENTE":
            return "pendente", {"solicitacao": str(s["_id"]),
                                "pedido_em": s.get("em")}
        if s.get("estado") == "REJEITADA":
            quando = float(s.get("decidido_em") or s.get("em") or 0)
            libera = quando + CARENCIA_REJEICAO
            if time.time() < libera:
                return "rejeitado", {"liberado_em": libera}
    return "disponivel", {}


def estados_para(uid, sids):
    """Estado do botao para varios servidores de uma vez.

    Tres consultas para a pagina inteira, e nao tres por cartao. Com 24
    cartoes, a versao ingenua faria 72 idas ao banco -- o N+1 que so
    incomoda quando o catalogo ja cresceu, e que e barato evitar agora.

    As duas primeiras consultam pela CHAVE PRIMARIA composta (`$in` de
    documentos `{server, user}`), e nao por `_id.user`: assim usam o
    indice `_id_` que ja existe, sem precisar criar indice novo numa
    colecao que e do upstream.
    """
    if not sids:
        return {}
    chaves = [{"server": x, "user": uid} for x in sids]
    membro = {d["_id"]["server"] for d in
              db.server_members.find({"_id": {"$in": chaves}}, {"_id": 1})}
    banido = {d["_id"]["server"] for d in
              db.server_bans.find({"_id": {"$in": chaves}}, {"_id": 1})}

    # Ordem crescente de propósito: a ultima gravada sobrescreve, entao o
    # que sobra no dicionario e a solicitacao mais recente de cada
    # servidor -- a mesma regra do estado_para de um so.
    ultima = {}
    for d in db.dp_solicitacoes.find(
            {"usuario": uid, "servidor": {"$in": sids}}).sort("em", 1):
        ultima[d["servidor"]] = d

    agora = time.time()
    fora = {}
    for sid in sids:
        if sid in membro:
            fora[sid] = ("membro", {})
            continue
        if sid in banido:
            fora[sid] = ("banido", {})
            continue
        d = ultima.get(sid)
        if d and d.get("estado") == "PENDENTE":
            fora[sid] = ("pendente", {"solicitacao": str(d["_id"]),
                                      "pedido_em": d.get("em")})
            continue
        if d and d.get("estado") == "REJEITADA":
            libera = float(d.get("decidido_em") or d.get("em") or 0) \
                + CARENCIA_REJEICAO
            if agora < libera:
                fora[sid] = ("rejeitado", {"liberado_em": libera})
                continue
        fora[sid] = ("disponivel", {})
    return fora


def _arquivo_url(doc):
    """Caminho do autumn para um anexo. Relativo de proposito: serve em
    qualquer host que o Caddy atenda, sem o cliente precisar da config."""
    if not doc or not doc.get("_id") or not doc.get("tag"):
        return None
    return f"/autumn/{doc['tag']}/{doc['_id']}"


def cartao(d, srv, estado=None, detalhe=None):
    """O cartao do catalogo. `d` e a linha nossa, `srv` o documento do
    servidor -- que pode faltar se o servidor foi apagado."""
    srv = srv or {}
    c = {
        "id": d["_id"],
        "nome": srv.get("name") or d.get("nome") or "",
        "descricao": srv.get("description") or "",
        "icone": _arquivo_url(srv.get("icon")),
        "banner": _arquivo_url(srv.get("banner")),
        "membros": int(d.get("membros") or 0),
        "categoria": d.get("categoria") or CATEGORIA_PADRAO,
        "tags": list(d.get("tags") or []),
    }
    if estado:
        c["estado"] = estado
        c.update(detalhe or {})
    return c


def _cursor_le(bruto):
    """(membros, id) a partir do cursor opaco, ou None se nao servir.

    Cursor invalido devolve None e a consulta comeca do inicio, em vez de
    estourar: e string vinda da URL, e URL as pessoas editam.
    """
    if not bruto:
        return None
    try:
        cru = base64.urlsafe_b64decode(bruto.encode() + b"==").decode()
        m, i = cru.split(":", 1)
        if not re.fullmatch(r"[0-9A-Z]{26}", i):
            return None
        return int(m), i
    except Exception:
        return None


def _cursor_escreve(d):
    return base64.urlsafe_b64encode(
        f"{int(d.get('membros') or 0)}:{d['_id']}".encode()
    ).decode().rstrip("=")


def pagina_do_catalogo(uid, categoria=None, cursor=None, q=None,
                       limite=None):
    """Uma pagina de comunidades publicas, por cursor.

    Cursor e nao `skip`: com `skip` a pagina 50 le e joga fora 1.200
    documentos, e uma comunidade que ganha membros entre duas paginas faz
    itens pularem ou repetirem. A ordem e (membros desc, _id asc) --
    exatamente a dos indices parciais, entao a consulta nao ordena em
    memoria.
    """
    limite = max(1, min(int(limite or PAGINA_CATALOGO), PAGINA_MAXIMA))
    condicoes = [{"publica": True}]

    if categoria:
        condicoes.append({"categoria": categoria})

    if q:
        termo = sem_acento(q)[:40]
        if termo:
            # Busca no nome denormalizado ou em etiqueta exata. A varredura
            # fica contida pelo indice parcial (so publicas). Quando o
            # catalogo crescer, o caminho e um indice de texto -- e a
            # consulta muda so aqui.
            condicoes.append({"$or": [
                {"nome_busca": {"$regex": re.escape(termo)}},
                {"tags": termo},
            ]})

    cur = _cursor_le(cursor)
    if cur:
        m, i = cur
        condicoes.append({"$or": [
            {"membros": {"$lt": m}},
            {"membros": m, "_id": {"$gt": i}},
        ]})

    # Um a mais que o limite: e assim que se sabe se ha proxima pagina sem
    # uma segunda consulta de contagem.
    docs = list(db.dp_comunidade
                .find({"$and": condicoes})
                .sort([("membros", -1), ("_id", 1)])
                .limit(limite + 1))
    tem_mais = len(docs) > limite
    docs = docs[:limite]

    ids = [d["_id"] for d in docs]
    servidores = {
        x["_id"]: x for x in db.servers.find(
            {"_id": {"$in": ids}},
            {"name": 1, "description": 1, "icon": 1, "banner": 1})
    }
    # O estado do botao vem calculado do servidor, tambem na listagem: e
    # o que impede o cartao de oferecer "solicitar entrada" para quem
    # esta banido, sem depender de o cliente pedir a ficha de cada um.
    estados = estados_para(uid, ids)
    return {
        "itens": [
            cartao(d, servidores.get(d["_id"]), *estados.get(d["_id"], (None, {})))
            for d in docs
        ],
        "proximo": _cursor_escreve(docs[-1]) if tem_mais and docs else None,
    }


def _api_stoat(metodo, caminho, token, corpo=None):
    """Chama a API do Stoat COM A SESSAO DE QUEM PEDIU.

    Nunca com credencial de terceiro, e isso e a decisao central desta
    rota: quem aprova e quem cria o convite. A propria API refaz a
    checagem de permissao, e o registro de auditoria dela sai no nome
    certo -- de graca. O servico nao guarda, nao reusa e nao registra o
    token; ele so o repassa dentro da mesma requisicao.
    """
    req = urllib.request.Request(
        API_STOAT + caminho, method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"Content-Type": "application/json",
                 "X-Session-Token": token})
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.status, json.loads(r.read() or b"{}")


def _canal_para_convite(sid):
    """Onde apontar o convite emitido na aprovacao.

    Convite para canal de voz e valido, mas joga a pessoa numa sala em vez
    de numa conversa. Percorre `servers.channels` NA ORDEM (a ordem da
    barra lateral, que e a que o dono escolheu) e pega o primeiro canal de
    texto puro.
    """
    srv = db.servers.find_one({"_id": sid}, {"channels": 1})
    ids = list((srv or {}).get("channels") or [])
    if not ids:
        return None
    docs = {c["_id"]: c for c in db.channels.find(
        {"_id": {"$in": ids}}, {"voice": 1, "channel_type": 1})}
    for i in ids:
        c = docs.get(i)
        if c and c.get("channel_type") == "TextChannel" and "voice" not in c:
            return i
    return ids[0]


def solicitacao_publica(s):
    """O que o proprio solicitante pode ver do seu pedido."""
    return {
        "id": str(s["_id"]),
        "servidor": s["servidor"],
        "estado": s.get("estado"),
        "em": s.get("em"),
        "decidido_em": s.get("decidido_em"),
        "motivo": s.get("motivo"),
        # O codigo do convite so vai para quem foi aprovado -- e o proprio
        # dono do pedido, ninguem mais le esta rota.
        "convite": s.get("convite") if s.get("estado") == "APROVADA" else None,
    }


def _reconcilia_solicitacoes():
    """Fecha pendentes que a realidade ja resolveu.

    Nao e "rejeitar": ninguem rejeitou. Dai o estado ENCERRADA, com o
    motivo dizendo o que aconteceu -- marcar isso como REJEITADA
    dispararia um "seu pedido foi recusado" que nunca existiu.

    A comunidade ficar PRIVADA de proposito NAO entra aqui: ela fecha
    para pedidos novos, e o administrador decide os que ja estao na fila.
    Encerrar em massa produziria um aviso de recusa para gente que nao
    fez nada errado, por uma configuracao que nem sabia existir.
    """
    agora = time.time()
    for s in db.dp_solicitacoes.find({"estado": "PENDENTE"},
                                     {"servidor": 1, "usuario": 1}):
        sid, u = s["servidor"], s["usuario"]
        motivo = None
        if not db.servers.find_one({"_id": sid}, {"_id": 1}):
            motivo = "comunidade_removida"
        elif db.server_bans.find_one(
                {"_id": {"server": sid, "user": u}}, {"_id": 1}):
            motivo = "usuario_banido"
        elif db.server_members.find_one(
                {"_id": {"server": sid, "user": u}}, {"_id": 1}):
            # Entrou por link enquanto o pedido estava aberto. O pedido
            # perdeu o proposito, e aprovar depois nao faria nada.
            motivo = "ja_entrou"
        if motivo:
            db.dp_solicitacoes.update_one(
                {"_id": s["_id"], "estado": "PENDENTE"},
                {"$set": {"estado": "ENCERRADA", "decidido_em": agora,
                          "motivo": motivo}})


def guarda_vitrine(uid, sid):
    """Guarda comum das rotas de vitrine.

    Devolve o par (codigo, corpo) do erro, ou None quando pode seguir.
    NAO responde por conta propria, e isso e deliberado: a primeira
    versao chamava `self.responde(...)` aqui e devolvia o resultado --
    mas `responde` devolve None, entao o `if erro is not None` do
    chamador nunca disparava. O 403 saia e o codigo seguia, escrevendo um
    200 com os dados logo atras. Duas respostas na mesma conexao, e a
    segunda entregava exatamente o que a primeira negou.

    Quem nao e membro recebe 404 e nao 403: 403 confirmaria que o
    servidor existe, e a existencia de comunidade privada nao pode vazar.
    """
    perm = permissao_no_servidor(uid, sid)
    if perm is None:
        return 404, {"erro": "nao_encontrado"}
    if not perm & BIT_GERIR_SERVIDOR:
        return 403, {
            "erro": "sem_permissao",
            "mensagem": "Você precisa de Gerenciar Servidor para mexer "
                        "na vitrine da comunidade."}
    return None


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
    # Com HTTP/1.1 a conexao fica aberta entre requisicoes, e sem prazo
    # uma conexao ociosa segura a thread para sempre. O socketserver
    # aplica isto com settimeout() no socket; o BaseHTTPRequestHandler
    # trata o estouro fechando a conexao, que e o comportamento correto:
    # o navegador reabre sozinho quando precisar. 30s e bem acima de
    # qualquer pausa entre as requisicoes que o cliente faz de verdade.
    timeout = 30

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
        # Proxy do template do Discord. O dado do outro lado é público e
        # não há segredo envolvido, mas a rota exige sessão mesmo assim, e
        # o motivo não é sigilo: é custo. Cada chamada segura uma thread
        # nossa por até 12s numa conexão de saída para o discord.com, e
        # o endereço IP que aparece lá é o da VM, um só para todo mundo.
        # Sem sessão, qualquer pessoa da internet transforma isto num
        # amplificador: gasta as nossas threads e queima a nossa cota no
        # Discord, e o preço cai sobre quem está usando o produto.
        if rota.startswith("/discord-template"):
            if not usuario_da_sessao(self.headers.get("X-Session-Token")):
                return self.responde(401, {"erro": "sessao_invalida",
                    "mensagem": "Entre na sua conta para importar do Discord."})
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
            # Duas listas, e nao uma com um campo "papel": quem le isto de
            # fora -- o amostrar-condicoes.sh -- pede "transmissores" e
            # imprime uma linha por item. Misturar quem assiste nessa mesma
            # lista mudaria o significado da serie ja coletada sem avisar.
            transmite, assiste = [], []
            for d in db.dp_condicoes.find():
                idade = agora - int(d.get("em") or 0)
                # Mais de dois minutos parado nao e medicao, e lembranca.
                if idade > 120:
                    continue
                item = {"usuario": d.get("usuario") or d["_id"],
                        "ha_s": idade,
                        "papel": d.get("papel") or "transmite",
                        "faixa": d.get("faixa"),
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
                        "renderFps": d.get("renderFps"),
                        "decodeFps": d.get("decodeFps"),
                        "largados": d.get("largados"),
                        "msBuffer": d.get("msBuffer"),
                        "perda": d.get("perda"),
                        "travadas": d.get("travadas"),
                        "bruto": d.get("bruto") or {},
                        "app": d.get("app")}
                if item["papel"] == "assiste":
                    assiste.append(item)
                else:
                    transmite.append(item)
            return self.responde(200, {"transmissores": transmite,
                                       "assistentes": assiste})

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

        if rota == "/solicitacoes/minhas":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            docs = list(db.dp_solicitacoes.find({"usuario": uid})
                        .sort("em", -1).limit(50))
            nomes = {
                x["_id"]: x.get("name") for x in db.servers.find(
                    {"_id": {"$in": [d["servidor"] for d in docs]}},
                    {"name": 1})
            }
            itens = []
            for d in docs:
                i = solicitacao_publica(d)
                i["nome"] = nomes.get(d["servidor"]) or ""
                itens.append(i)
            return self.responde(200, {"itens": itens})

        m = re.fullmatch(
            r"/servidores/([0-9A-Z]{26})/solicitacoes/contagem", rota)
        if m:
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            erro = guarda_vitrine(uid, m.group(1))
            if erro:
                return self.responde(*erro)
            # Rota separada e enxuta de proposito: e ela que o contador da
            # engrenagem consulta em laco, e ele so precisa do numero.
            return self.responde(200, {"pendentes": db.dp_solicitacoes
                .count_documents({"servidor": m.group(1),
                                  "estado": "PENDENTE"})})

        m = re.fullmatch(r"/servidores/([0-9A-Z]{26})/solicitacoes", rota)
        if m:
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            sid = m.group(1)
            erro = guarda_vitrine(uid, sid)
            if erro:
                return self.responde(*erro)
            docs = list(db.dp_solicitacoes
                        .find({"servidor": sid, "estado": "PENDENTE"})
                        .sort("em", -1).limit(200))
            # Perfis em lote: uma consulta para a fila inteira, e nao uma
            # por linha.
            perfis = _perfis([d["usuario"] for d in docs])
            contas = {
                u["_id"]: u.get("username") for u in db.users.find(
                    {"_id": {"$in": [d["usuario"] for d in docs]}},
                    {"username": 1})
            }
            return self.responde(200, {"itens": [{
                "id": str(d["_id"]),
                "usuario": d["usuario"],
                "nome": perfis.get(d["usuario"], {}).get("nome", "?"),
                "username": contas.get(d["usuario"]) or "",
                "avatar": perfis.get(d["usuario"], {}).get("avatar"),
                "mensagem": d.get("mensagem"),
                "em": d.get("em"),
            } for d in docs]})

        # --- catalogo (a ordem importa: "categorias" antes do ULID)
        if rota == "/catalogo/categorias":
            if not usuario_da_sessao(self.headers.get("X-Session-Token")):
                return self.responde(401, {"erro": "sessao_invalida"})
            # Quantas comunidades publicas ha em cada categoria, numa
            # agregacao so. Sem isso a tela pediria uma contagem por
            # categoria e faria nove requisicoes para desenhar um menu.
            contagem = {
                x["_id"]: x["n"] for x in db.dp_comunidade.aggregate([
                    {"$match": {"publica": True}},
                    {"$group": {"_id": "$categoria", "n": {"$sum": 1}}},
                ])
            }
            itens = [
                {"id": c["_id"], "nome": c.get("nome") or c["_id"],
                 "emoji": c.get("emoji") or "",
                 "comunidades": int(contagem.get(c["_id"], 0))}
                for c in db.dp_categorias.find(
                    {"ativa": True}, {"nome": 1, "emoji": 1}).sort("ordem", 1)
            ]
            return self.responde(200, {
                "itens": itens,
                "total": sum(contagem.values()),
            })

        m = re.fullmatch(r"/catalogo/([0-9A-Z]{26})", rota)
        if m:
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            sid = m.group(1)
            d = db.dp_comunidade.find_one({"_id": sid})
            ehmembro = db.server_members.find_one(
                {"_id": {"server": sid, "user": uid}}, {"_id": 1})
            # 404 e nao 403 quando a comunidade nao e publica: 403
            # confirmaria que ela existe, e a existencia de comunidade
            # privada nao pode vazar. Quem ja e membro enxerga a ficha da
            # sua propria comunidade mesmo com ela privada.
            if not d or (not d.get("publica") and not ehmembro):
                return self.responde(404, {"erro": "nao_encontrado"})
            srv = db.servers.find_one(
                {"_id": sid},
                {"name": 1, "description": 1, "icon": 1, "banner": 1})
            if not srv:
                return self.responde(404, {"erro": "nao_encontrado"})
            estado, detalhe = estado_para(uid, sid)
            return self.responde(200, cartao(d, srv, estado, detalhe))

        if rota == "/catalogo":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            p = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)

            def um(nome, tam=64):
                v = (p.get(nome) or [""])[0]
                return v[:tam] if isinstance(v, str) else ""

            categoria = um("categoria", 40)
            if categoria and not RE_CODIGO.match(categoria):
                return self.responde(400, {"erro": "categoria_invalida"})
            return self.responde(200, pagina_do_catalogo(
                uid,
                categoria=categoria or None,
                cursor=um("cursor", 128) or None,
                q=um("q", 60) or None,
                limite=um("limite", 4) or None))

        if rota == "/vitrine/categorias":
            if not usuario_da_sessao(self.headers.get("X-Session-Token")):
                return self.responde(401, {"erro": "sessao_invalida"})
            itens = [
                {"id": c["_id"], "nome": c.get("nome") or c["_id"],
                 "emoji": c.get("emoji") or ""}
                for c in db.dp_categorias.find(
                    {"ativa": True}, {"nome": 1, "emoji": 1}).sort("ordem", 1)
            ]
            return self.responde(200, {"itens": itens})

        m = re.fullmatch(r"/servidores/([0-9A-Z]{26})/vitrine", rota)
        if m:
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            erro = guarda_vitrine(uid, m.group(1))
            if erro:
                return self.responde(*erro)
            return self.responde(200, vitrine_de(m.group(1)))

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
            # 1 KB nao cabia mais o que e preciso medir. Os contadores
            # brutos -- quadros capturados, enviados, recebidos,
            # decodificados, largados, e o tamanho da fonte, da captura e
            # do monitor -- sao o que separa "a captura nao entrega" de "o
            # navegador esta reduzindo cada quadro antes de codificar".
            c = self.corpo_json(limite=4096)

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

            papel = "assiste" if c.get("papel") == "assiste" else "transmite"
            faixa = texto(c.get("faixa"), 24) or ""

            # Lista fechada, com teto por campo. `bruto` e um dicionario
            # montado no navegador: aceito como veio, ele vira campo de
            # texto livre gravado no banco por quem quiser.
            TETOS = {"camadas": 8,
                     "quadrosEnviados": 1e9, "quadrosCodificados": 1e9,
                     "quadrosCapturados": 1e9, "quadrosRecebidos": 1e9,
                     "quadrosDecodificados": 1e9, "quadrosLargados": 1e9,
                     "segCongelado": 86400, "pausas": 1e6,
                     "fonteLargura": 16384, "fonteAltura": 16384,
                     "capturaLargura": 16384, "capturaAltura": 16384,
                     "capturaPedida": 240,
                     "telaLargura": 16384, "telaAltura": 16384,
                     "telaEscala": 8,
                     "exibeLargura": 16384, "exibeAltura": 16384}
            entrada = c.get("bruto")
            bruto = {}
            if isinstance(entrada, dict):
                for chave, teto in TETOS.items():
                    v = numero(entrada.get(chave), teto)
                    if v is not None:
                        bruto[chave] = v
                superficie = texto(entrada.get("superficie"), 16)
                if superficie:
                    bruto["superficie"] = superficie

            doc = {"em": int(time.time()),
                   "usuario": uid,
                   "papel": papel,
                   "faixa": faixa,
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
                   "renderFps": numero(c.get("renderFps"), 240),
                   "decodeFps": numero(c.get("decodeFps"), 240),
                   "largados": numero(c.get("largados"), 1e6),
                   "msBuffer": numero(c.get("msBuffer"), 60000),
                   "perda": numero(c.get("perda"), 100),
                   "travadas": numero(c.get("travadas"), 1e6),
                   "bruto": bruto,
                   "app": bool(c.get("app"))}

            # A chave inclui papel e faixa. Com `_id: uid` a medida de quem
            # assiste sobrescrevia a de quem transmite a cada dez segundos,
            # e duas telas abertas ao mesmo tempo brigavam pelo mesmo
            # registro -- vencia a ultima a chegar.
            db.dp_condicoes.update_one(
                {"_id": "%s:%s:%s" % (uid, papel, faixa)},
                {"$set": doc}, upsert=True)

            # O documento acima e o AGORA, sobrescrito a cada dez segundos.
            # Esta colecao e a serie -- e foi a serie, nunca a leitura
            # isolada, que decidiu cada pergunta desta investigacao: 1 fps
            # pode ser a tela parada e pode ser a captura estrangulada, e o
            # que separa os dois casos e a sequencia. Some sozinha pelo TTL.
            try:
                from datetime import datetime, timezone
                db.dp_condicoes_serie.insert_one(
                    dict(doc, quando=datetime.now(timezone.utc)))
            except Exception:
                # Medicao nao e funcionalidade: se o historico falhar, a
                # chamada segue e o "agora" acima ja foi gravado.
                pass
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

        if rota == "/solicitacoes":
            corpo = self.corpo_json(limite=2048)
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})

            sid = corpo.get("servidor")
            if not isinstance(sid, str) or not re.fullmatch(
                    r"[0-9A-Z]{26}", sid):
                return self.responde(400, {"erro": "servidor_invalido"})

            # 404 para privada e para inexistente, pelo mesmo motivo do
            # catalogo: a existencia de comunidade privada nao pode vazar.
            d = db.dp_comunidade.find_one({"_id": sid}, {"publica": 1})
            if not d or not d.get("publica") or not db.servers.find_one(
                    {"_id": sid}, {"_id": 1}):
                return self.responde(404, {"erro": "nao_encontrado"})

            # O MESMO calculo que o catalogo usa para desenhar o botao.
            # Uma funcao so, para a tela e a escrita nunca discordarem.
            estado, det = estado_para(uid, sid)
            if estado == "membro":
                return self.responde(409, {
                    "erro": "ja_e_membro",
                    "mensagem": "Você já faz parte desta comunidade."})
            if estado == "banido":
                return self.responde(403, {
                    "erro": "sem_acesso",
                    "mensagem": "Você não pode entrar nesta comunidade."})
            if estado == "pendente":
                return self.responde(409, {
                    "erro": "ja_solicitado",
                    "mensagem": "Seu pedido já foi enviado."})
            if estado == "rejeitado":
                return self.responde(429, dict(det, **{
                    "erro": "em_carencia",
                    "mensagem": "Seu pedido foi recusado há pouco. "
                                "Tente novamente mais tarde."}))

            if db.dp_solicitacoes.count_documents(
                    {"usuario": uid, "estado": "PENDENTE"}) >= TETO_PENDENTES:
                return self.responde(429, {
                    "erro": "muitos_pendentes",
                    "mensagem": f"Você já tem {TETO_PENDENTES} pedidos "
                                "aguardando resposta."})
            if db.dp_solicitacoes.count_documents(
                    {"usuario": uid,
                     "em": {"$gte": time.time() - 86400}}) >= TETO_PEDIDOS_DIA:
                return self.responde(429, {
                    "erro": "muitos_pedidos",
                    "mensagem": "Você fez pedidos demais hoje. "
                                "Tente amanhã."})

            msg = corpo.get("mensagem")
            msg = msg.strip()[:280] if isinstance(msg, str) else None

            doc = {"servidor": sid, "usuario": uid, "estado": "PENDENTE",
                   "em": time.time(), "mensagem": msg or None,
                   "decidido_por": None, "decidido_em": None,
                   "motivo": None, "convite": None}
            try:
                db.dp_solicitacoes.insert_one(doc)
            except DuplicateKeyError:
                # O indice unico parcial. Dez cliques produzem um pedido,
                # e a corrida termina aqui em vez de no banco sujo.
                return self.responde(409, {
                    "erro": "ja_solicitado",
                    "mensagem": "Seu pedido já foi enviado."})
            return self.responde(200, solicitacao_publica(doc))

        m = re.fullmatch(r"/solicitacoes/([0-9a-f]{24})/cancelar", rota)
        if m:
            self.corpo_json(limite=256)
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            # `usuario` na condicao: e o que impede cancelar o pedido dos
            # outros mandando o id deles.
            d = db.dp_solicitacoes.find_one_and_update(
                {"_id": ObjectId(m.group(1)), "usuario": uid,
                 "estado": "PENDENTE"},
                {"$set": {"estado": "CANCELADA", "decidido_em": time.time()}},
                return_document=True)
            if not d:
                return self.responde(404, {"erro": "nao_encontrado"})
            return self.responde(200, solicitacao_publica(d))

        m = re.fullmatch(
            r"/servidores/([0-9A-Z]{26})/solicitacoes/([0-9a-f]{24})"
            r"/(aceitar|rejeitar)", rota)
        if m:
            sid, oid, acao = m.group(1), m.group(2), m.group(3)
            corpo = self.corpo_json(limite=1024)
            token = self.headers.get("X-Session-Token")
            uid = usuario_da_sessao(token)
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            erro = guarda_vitrine(uid, sid)
            if erro:
                return self.responde(*erro)

            sol = db.dp_solicitacoes.find_one(
                {"_id": ObjectId(oid), "servidor": sid})
            if not sol:
                # `servidor` na consulta: mandar o id de uma solicitacao de
                # OUTRA comunidade nao a alcanca por esta rota.
                return self.responde(404, {"erro": "nao_encontrado"})
            if sol.get("estado") != "PENDENTE":
                return self.responde(409, {
                    "erro": "ja_decidida",
                    "estado": sol.get("estado"),
                    "mensagem": "Este pedido já foi respondido."})
            if sol.get("usuario") == uid:
                # Vale inclusive para o dono. Quem pede nao decide.
                return self.responde(403, {
                    "erro": "nao_pode_decidir_o_proprio",
                    "mensagem": "Você não pode decidir o próprio pedido."})

            motivo = corpo.get("motivo")
            motivo = motivo.strip()[:280] if isinstance(motivo, str) else None
            agora = time.time()

            if acao == "rejeitar":
                d = db.dp_solicitacoes.find_one_and_update(
                    {"_id": sol["_id"], "estado": "PENDENTE"},
                    {"$set": {"estado": "REJEITADA", "decidido_por": uid,
                              "decidido_em": agora, "motivo": motivo}},
                    return_document=True)
                if not d:
                    return self.responde(409, {"erro": "ja_decidida"})
                return self.responde(200, {"ok": True, "estado": "REJEITADA"})

            # --- aceitar
            canal = _canal_para_convite(sid)
            if not canal:
                return self.responde(409, {
                    "erro": "sem_canal",
                    "mensagem": "A comunidade não tem canal para onde "
                                "mandar o convite."})

            # O convite e criado ANTES do compare-and-swap, e nao depois.
            # Se falhasse depois, a solicitacao ja estaria APROVADA sem
            # codigo nenhum -- a pessoa veria "aprovado" e nao teria como
            # entrar. Nesta ordem, o pior caso e um convite orfao, que a
            # linha abaixo apaga.
            try:
                _, inv = _api_stoat(
                    "POST", f"/channels/{canal}/invites", token)
                codigo = inv.get("_id")
            except Exception as e:
                print(f"solicitacoes: convite falhou ({e})", flush=True)
                return self.responde(502, {
                    "erro": "convite_falhou",
                    "mensagem": "Não consegui criar o convite agora. "
                                "Tente de novo."})
            if not codigo:
                return self.responde(502, {"erro": "convite_falhou"})

            d = db.dp_solicitacoes.find_one_and_update(
                {"_id": sol["_id"], "estado": "PENDENTE"},
                {"$set": {"estado": "APROVADA", "decidido_por": uid,
                          "decidido_em": agora, "motivo": motivo,
                          "convite": codigo}},
                return_document=True)
            if not d:
                # Outro administrador decidiu entre a leitura e aqui.
                # Desfaz o convite que acabamos de criar, senao fica um
                # codigo valido solto que ninguem sabe que existe.
                try:
                    _api_stoat("DELETE", f"/invites/{codigo}", token)
                except Exception:
                    pass
                return self.responde(409, {
                    "erro": "ja_decidida",
                    "mensagem": "Este pedido já foi respondido."})
            return self.responde(200, {"ok": True, "estado": "APROVADA",
                                       "convite": codigo})

        m = re.fullmatch(r"/servidores/([0-9A-Z]{26})/vitrine", rota)
        if m:
            sid = m.group(1)
            # Corpo antes da sessao, como no envio de som: fechar a conexao
            # sem drenar o corpo faz o navegador mostrar "erro de rede" em
            # vez do 401/403 que a gente quis dizer.
            corpo = self.corpo_json(limite=2048)
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            erro = guarda_vitrine(uid, sid)
            if erro:
                return self.responde(*erro)

            mudanca = {}
            if "categoria" in corpo:
                cat = corpo.get("categoria")
                if not isinstance(cat, str) or not categoria_valida(cat):
                    return self.responde(400, {
                        "erro": "categoria_invalida",
                        "mensagem": "Escolha uma categoria da lista."})
                mudanca["categoria"] = cat
            if "tags" in corpo:
                tags, e = _normaliza_tags(corpo.get("tags"))
                if e:
                    return self.responde(400, {
                        "erro": e,
                        "mensagem": f"Use no máximo {MAX_TAGS} etiquetas "
                                    "curtas, sem acento."})
                mudanca["tags"] = tags
            if "publica" in corpo:
                mudanca["publica"] = bool(corpo.get("publica"))
            if not mudanca:
                return self.responde(400, {"erro": "nada_a_mudar"})

            # Publica sem categoria valida nao teria onde aparecer no
            # catalogo -- viraria comunidade listada em lugar nenhum.
            atual = vitrine_de(sid)
            if (mudanca.get("publica", atual["publica"])
                    and not categoria_valida(
                        mudanca.get("categoria", atual["categoria"]))):
                return self.responde(400, {
                    "erro": "categoria_obrigatoria",
                    "mensagem": "Escolha a categoria antes de tornar a "
                                "comunidade pública."})

            agora = time.time()
            # Nome e contagem denormalizados, para o catalogo ordenar por
            # tamanho e buscar por nome sem $lookup a cada pagina. O laco
            # de fundo reconcilia; aqui e para o cartao ja nascer certo.
            mudanca.update(denormaliza(sid))
            mudanca["por"] = uid
            mudanca["atualizado_em"] = agora
            db.dp_comunidade.update_one(
                {"_id": sid},
                {"$set": mudanca, "$setOnInsert": {"em": agora}},
                upsert=True)
            return self.responde(200, vitrine_de(sid))

        self.responde(404, {"erro": "nao_encontrado"})


class Servidor(ThreadingHTTPServer):
    """ThreadingHTTPServer com fila de conexoes maior que o padrao.

    O padrao do socketserver e 5, e nao e limite de threads: e o backlog
    do listen(). Conexao que chega com a fila cheia leva RST antes de
    qualquer codigo nosso rodar -- o cliente ve "erro de rede", nao um
    erro nosso, e nada disso aparece no log do servico.

    Encontrado medindo, nao supondo: o teste de corrida das solicitacoes
    manda 20 pedidos ao mesmo tempo, e tres morriam com
    ConnectionResetError. As guardas estavam certas (um 200, o resto 409),
    mas tres requisicoes nunca chegaram a ser atendidas.

    Isso passou a importar mais agora: o contador de pendentes consulta em
    laco, e o catalogo dispara varias requisicoes ao abrir. 128 e o teto
    usual do kernel e nao custa memoria -- e fila de socket, nao de
    thread.
    """
    request_queue_size = 128

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._vagas = threading.Semaphore(TETO_THREADS)

    def process_request(self, request, client_address):
        """Gera a thread da conexao SO se houver vaga.

        O ThreadingHTTPServer cria uma thread por conexao e nao tem teto.
        Com protocol_version HTTP/1.1 a thread fica presa pela conexao
        inteira, nao por uma requisicao -- entao N conexoes abertas sao N
        threads paradas. Um cliente que abre milhares de conexoes e nao
        fala nada derruba o servico sem enviar um byte de HTTP.

        A recusa e imediata, com blocking=False, e isso e deliberado:
        process_request roda na thread do accept. Esperar aqui por vaga
        pararia de aceitar conexoes para TODO mundo -- trocar uma recusa
        honesta de um cliente por uma indisponibilidade de todos e um mau
        negocio. Quem e recusado recebe 503 com Retry-After, que e uma
        resposta, e nao um RST sem explicacao.
        """
        if not self._vagas.acquire(blocking=False):
            try:
                request.sendall(RECUSA_OCUPADO)
            except Exception:
                pass
            self.shutdown_request(request)
            print(f"503 ocupado: teto de {TETO_THREADS} conexoes", flush=True)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            # t.start() falhou: a thread nunca rodou, entao o finally do
            # process_request_thread nunca vai devolver esta vaga.
            self._vagas.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._vagas.release()


if __name__ == "__main__":
    db.account_invites.create_index("criado_por")
    db.fila_espera.create_index("em")
    db.chamadas.create_index("encerrada")
    db.faixas.create_index("sala")
    db.account_invites.create_index("origem")
    # TTL na criacao, e nao depois: uma serie que grava a cada dez segundos
    # por transmissor e por espectador cresce rapido, e colecao sem prazo
    # de validade e do tipo que so aparece quando o disco enche.
    try:
        db.dp_condicoes_serie.create_index("quando", expireAfterSeconds=3 * 24 * 3600)
        db.dp_condicoes_serie.create_index([("usuario", 1), ("em", 1)])
    except Exception as e:
        print(f"indice da serie de condicoes: {e}", flush=True)
    # Descoberta de comunidades. Criados aqui alem do script de migracao
    # para que um container novo os recrie sozinho -- indice que so existe
    # porque alguem rodou um script uma vez e o tipo de coisa que some numa
    # reinstalacao e so aparece como lentidao meses depois.
    try:
        db.dp_categorias.create_index([("ativa", 1), ("ordem", 1)],
                                      name="ativas_por_ordem")
        SO_PUBLICAS = {"publica": True}
        db.dp_comunidade.create_index(
            [("categoria", 1), ("membros", -1), ("_id", 1)],
            name="catalogo_por_categoria", partialFilterExpression=SO_PUBLICAS)
        db.dp_comunidade.create_index(
            [("membros", -1), ("_id", 1)],
            name="catalogo_populares", partialFilterExpression=SO_PUBLICAS)
        db.dp_comunidade.create_index(
            [("tags", 1)],
            name="catalogo_por_tag", partialFilterExpression=SO_PUBLICAS)
        db.dp_comunidade.create_index(
            [("nome_busca", 1)],
            name="catalogo_por_nome", partialFilterExpression=SO_PUBLICAS)
        # O unico indice UNICO do banco. Com ele, dez cliques em "solicitar"
        # produzem UM pedido -- garantia de banco, nao checagem no codigo.
        # Mongo standalone nao tem transacao; isto ocupa o lugar dela.
        db.dp_solicitacoes.create_index(
            [("servidor", 1), ("usuario", 1)],
            name="um_pendente_por_pessoa", unique=True,
            partialFilterExpression={"estado": "PENDENTE"})
        db.dp_solicitacoes.create_index(
            [("servidor", 1), ("estado", 1), ("em", -1)], name="fila_do_admin")
        db.dp_solicitacoes.create_index(
            [("usuario", 1), ("em", -1)], name="pedidos_da_pessoa")
    except Exception as e:
        print(f"indices da descoberta: {e}", flush=True)
    print(f"servico de convites em :{PORTA} (limite {LIMITE})", flush=True)
    inicia_repasse()
    inicia_metricas()
    inicia_vitrine()
    Servidor(("0.0.0.0", PORTA), Handler).serve_forever()
