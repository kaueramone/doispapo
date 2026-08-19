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
import json, os, re, secrets, threading, time
import urllib.request, urllib.parse
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
        if self.path == "/saude":
            return self.responde(200, {"ok": True})

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
            elif evento in ("participant_joined", "participant_left"):
                n = (c.get("room") or {}).get("numParticipants", 0)
                db.chamadas.update_one({"_id": sala},
                    {"$set": {"participantes": n}}, upsert=True)
            return self.responde(200, {"ok": True})

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
    db.account_invites.create_index("origem")
    print(f"servico de convites em :{PORTA} (limite {LIMITE})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
