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
import base64, hashlib, hmac, json, os, re, secrets, threading, time
import urllib.request, urllib.parse, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

# Os sons que o cliente realmente toca — são os `case` do switch de
# reprodução. A configuração do app lista 14 chaves, mas quatro delas
# (unmute, userJoinVoice, userLeaveVoice, userMoved) têm interruptor e
# nenhum `case`: nunca soam. Aceitar essas quatro seria oferecer um
# campo que não produz efeito nenhum.
SONS_VALIDOS = ("message", "deafen", "undeafen", "mute",
                "ringtoneIncoming", "ringtoneOutgoing",
                "streamStart", "streamEnd",
                "streamViewerJoin", "streamViewerLeave")


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

    def corpo_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > 8192:
                return {}
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        # Proxy do template do Discord. Público dos dois lados: o
        # endpoint do Discord dispensa autenticação, e aqui não há
        # segredo envolvido — só leitura de dado que já é público.
        if self.path.startswith("/discord-template"):
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
        if self.path.startswith("/sons/"):
            partes = self.path.strip("/").split("/")
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

        if self.path == "/saude":
            return self.responde(200, {"ok": True})

        # Mapa faixa -> participante, para o cliente saber de quem é
        # cada fluxo de áudio que ele está reproduzindo.
        if self.path == "/faixas":
            vivo = faixas_ao_vivo()
            if vivo is not None:
                return self.responde(200, {"faixas": vivo, "origem": "livekit"})
            itens = {d["_id"]: {"participante": d.get("participante"),
                                "fonte": d.get("fonte")}
                     for d in db.faixas.find()}
            return self.responde(200, {"faixas": itens, "origem": "eventos"})

        # Chamadas em andamento, para o contador de duração.
        if self.path == "/chamadas":
            itens = {
                d["_id"]: {"inicio": d.get("inicio"),
                           "participantes": d.get("participantes", 0)}
                for d in db.chamadas.find({"encerrada": {"$ne": True}})
                if d.get("inicio")
            }
            return self.responde(200, {"chamadas": itens})

        # Lista da fila de espera — só para o administrador da instância.
        if self.path == "/fila":
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

        if self.path == "/saldo":
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
        # Webhook do LiveKit: registra início e fim das chamadas.
        # Não é exposto pelo Caddy — o LiveKit chama pela rede interna.
        if self.path == "/livekit":
            c = self.corpo_json()
            evento = c.get("event")
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
                    else:
                        db.faixas.delete_one({"_id": faixa})
            elif evento in ("participant_joined", "participant_left"):
                n = (c.get("room") or {}).get("numParticipants", 0)
                db.chamadas.update_one({"_id": sala},
                    {"$set": {"participantes": n}}, upsert=True)
            return self.responde(200, {"ok": True})

        # Enviar ou remover o som do servidor. Exige ser o dono.
        if self.path.startswith("/sons/"):
            sid = self.path.strip("/").split("/")[1]
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
        if self.path == "/fila":
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
        if self.path == "/gerar":
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
        if self.path == "/resgatar":
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
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
