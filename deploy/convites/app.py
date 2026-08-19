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
import json, os, re, secrets, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pymongo import MongoClient

LIMITE = int(os.environ.get("LIMITE_CONVITES", "5"))
MONGO  = os.environ.get("MONGO_URL", "mongodb://database:27017")
PORTA  = int(os.environ.get("PORTA", "8600"))

cli = MongoClient(MONGO, serverSelectionTimeoutMS=5000)
db  = cli.revolt
trava = threading.Lock()   # serializa a checagem de cota + emissão

RE_CODIGO = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def usuario_da_sessao(token):
    """Resolve o token de sessão para um id de usuário."""
    if not token or len(token) > 256:
        return None
    s = db.sessions.find_one({"token": token}, {"user_id": 1})
    return s.get("user_id") if s else None


def saldo(uid):
    usados = db.account_invites.count_documents({"criado_por": uid})
    return {
        "limite": LIMITE,
        "usados": usados,
        "disponiveis": max(0, LIMITE - usados),
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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # silencia o log padrão, ruidoso
        pass

    def responde(self, codigo, corpo):
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

        if self.path == "/saldo":
            uid = usuario_da_sessao(self.headers.get("X-Session-Token"))
            if not uid:
                return self.responde(401, {"erro": "sessao_invalida"})
            s = saldo(uid)
            s["codigos"] = [
                {"codigo": d["_id"], "usado": bool(d.get("used"))}
                for d in db.account_invites.find({"criado_por": uid})
            ]
            return self.responde(200, s)

        self.responde(404, {"erro": "nao_encontrado"})

    # --------------------------------------------------------------- POST
    def do_POST(self):
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
    db.account_invites.create_index("origem")
    print(f"servico de convites em :{PORTA} (limite {LIMITE})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
