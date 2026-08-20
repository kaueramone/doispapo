#!/usr/bin/env python3
"""
Painel administrativo do Dois Papo.

Autenticação própria, sem relação com as contas da plataforma: usuário e
senha guardados como hash scrypt, sessão em cookie HttpOnly.
"""
import hashlib, hmac, json, os, re, secrets, threading, time, urllib.parse
import urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from bson import ObjectId
from pymongo import MongoClient

MONGO   = os.environ.get("MONGO_URL", "mongodb://database:27017")
PORTA   = int(os.environ.get("PORTA", "8700"))
LOG     = os.environ.get("ACCESS_LOG", "/logs/acessos.log")
LIMITE  = int(os.environ.get("LIMITE_CONVITES", "5"))
SESSAO_H = int(os.environ.get("SESSAO_HORAS", "12"))
RAIZ    = os.path.dirname(os.path.abspath(__file__))

cli = MongoClient(MONGO, serverSelectionTimeoutMS=5000)
db  = cli.revolt
trava = threading.Lock()
tentativas = {}          # ip -> (contagem, instante do bloqueio)

# ----------------------------------------------------------------- senha
def hash_senha(senha, sal=None):
    sal = sal or secrets.token_hex(16)
    h = hashlib.scrypt(senha.encode(), salt=sal.encode(),
                       n=16384, r=8, p=1, dklen=32).hex()
    return {"sal": sal, "hash": h}

def confere_senha(senha, doc):
    if not doc:
        return False
    novo = hash_senha(senha, doc.get("sal", ""))
    return hmac.compare_digest(novo["hash"], doc.get("hash", ""))

def admin():
    return db.painel_admin.find_one({"_id": "admin"})

def garante_admin():
    """Cria o administrador no primeiro boot e imprime a senha uma vez."""
    if admin():
        return
    senha = secrets.token_urlsafe(15)
    doc = hash_senha(senha)
    doc.update({"_id": "admin", "usuario": "admin", "criado": time.time(),
                "trocar_senha": True})
    db.painel_admin.insert_one(doc)
    print("=" * 62, flush=True)
    print("  PAINEL — credenciais iniciais (aparecem só desta vez)", flush=True)
    print("  usuario: admin", flush=True)
    print(f"  senha  : {senha}", flush=True)
    print("  troque no primeiro acesso.", flush=True)
    print("=" * 62, flush=True)

# ---------------------------------------------------------------- sessão
def cria_sessao():
    tok = secrets.token_urlsafe(32)
    db.painel_sessoes.insert_one(
        {"_id": tok, "em": time.time(),
         "expira": time.time() + SESSAO_H * 3600})
    return tok

def sessao_valida(tok):
    if not tok:
        return False
    s = db.painel_sessoes.find_one({"_id": tok})
    if not s:
        return False
    if s.get("expira", 0) < time.time():
        db.painel_sessoes.delete_one({"_id": tok})
        return False
    return True

# --------------------------------------------------------------- métricas
def metricas(dias=7):
    """Agrega o access log do Caddy. Tolera arquivo ausente."""
    corte = time.time() - dias * 86400
    por_dia, por_host, rotas, status, ips = {}, {}, {}, {}, set()
    erros, total = [], 0
    try:
        with open(LOG, encoding="utf-8", errors="replace") as fh:
            for linha in fh:
                try:
                    d = json.loads(linha)
                except Exception:
                    continue
                if d.get("msg") != "handled request":
                    continue
                ts = d.get("ts", 0)
                if ts < corte:
                    continue
                req = d.get("request", {})
                host = req.get("host", "?")
                uri = req.get("uri", "/").split("?")[0]
                st = d.get("status", 0)
                ip = req.get("client_ip", "")
                # ruído: chamadas internas da própria plataforma
                if uri.startswith(("/api/", "/ws", "/autumn", "/january")):
                    continue
                total += 1
                dia = time.strftime("%Y-%m-%d", time.localtime(ts))
                por_dia[dia] = por_dia.get(dia, 0) + 1
                por_host[host] = por_host.get(host, 0) + 1
                rotas[f"{host}{uri}"] = rotas.get(f"{host}{uri}", 0) + 1
                status[str(st)] = status.get(str(st), 0) + 1
                if ip:
                    ips.add(ip)
                if st >= 400 and len(erros) < 40:
                    erros.append({"quando": dia, "host": host, "rota": uri,
                                  "status": st})
    except FileNotFoundError:
        return {"indisponivel": True,
                "motivo": "Log de acesso ainda não gerado."}
    ordena = lambda m, n: sorted(m.items(), key=lambda x: -x[1])[:n]
    return {
        "total": total, "visitantes": len(ips), "dias": dias,
        "por_dia": sorted(por_dia.items()),
        "por_host": ordena(por_host, 10),
        "rotas": ordena(rotas, 15),
        "status": ordena(status, 8),
        "erros": erros[:20],
    }

# ---------------------------------------------------------------- dados
def perfis_de(uids):
    """Nome de exibicao por id de usuario, numa consulta so."""
    fora = {}
    for u in db.users.find({"_id": {"$in": list(set(u for u in uids if u))}},
                           {"username": 1, "display_name": 1}):
        fora[u["_id"]] = {"nome": u.get("display_name")
                          or u.get("username") or "?"}
    return fora


def cota_de(uid):
    c = db.painel_cotas.find_one({"_id": uid})
    return int(c["limite"]) if c and "limite" in c else LIMITE

def lista_usuarios():
    out = []
    for a in db.accounts.find({}, {"email": 1, "verification": 1}):
        uid = a["_id"]
        u = db.users.find_one({"_id": uid}, {"username": 1, "discriminator": 1}) or {}
        ger = db.account_invites.count_documents({"criado_por": uid})
        lim = cota_de(uid)
        conv = db.account_invites.find_one({"claimed_by": uid}) or {}
        out.append({
            "id": uid,
            "email": a.get("email"),
            "usuario": u.get("username"),
            "tag": u.get("discriminator"),
            "verificado": (a.get("verification") or {}).get("status") == "Verified",
            "convites_gerados": ger,
            "cota": lim,
            "convites_livres": max(0, lim - ger),
            "convidado_por": conv.get("criado_por"),
            "banido": bool(db.painel_banidos.find_one({"_id": uid})),
            "sessoes": db.sessions.count_documents({"user_id": uid}),
        })
    out.sort(key=lambda x: (x["usuario"] or "", x["email"] or ""))
    return out

# ------------------------------------------------------------- handler
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

    def log_message(self, *a):
        pass

    # ---------------------------------------------------------- utilidades
    def responde(self, cod, corpo, cabecalhos=None):
        dados = json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(cod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (cabecalhos or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(dados)

    def html(self, caminho):
        try:
            dados = open(os.path.join(RAIZ, caminho), "rb").read()
        except FileNotFoundError:
            return self.responde(404, {"erro": "nao_encontrado"})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def corpo(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(n) or b"{}") if 0 < n <= 65536 else {}
        except Exception:
            return {}

    def cookie(self, nome):
        bruto = self.headers.get("Cookie", "")
        for parte in bruto.split(";"):
            k, _, v = parte.strip().partition("=")
            if k == nome:
                return urllib.parse.unquote(v)
        return None

    def autenticado(self):
        return sessao_valida(self.cookie("dp_painel"))

    def exige(self):
        if self.autenticado():
            return True
        self.responde(401, {"erro": "nao_autenticado"})
        return False

    def rota(self):
        return urllib.parse.urlparse(self.path).path

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        r = self.rota()
        if r in ("/", "/index.html"):
            return self.html("painel.html")
        if r == "/painel.js":
            try:
                dados = open(os.path.join(RAIZ, "painel.js"), "rb").read()
            except FileNotFoundError:
                return self.responde(404, {"erro": "nao_encontrado"})
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(dados)
            return
        if r == "/saude":
            return self.responde(200, {"ok": True})
        if r == "/api/sessao":
            a = admin()
            corpo = {"autenticado": self.autenticado(),
                     "trocar_senha": bool(a and a.get("trocar_senha"))}
            if corpo["autenticado"]:
                corpo["usuario"] = (a or {}).get("usuario")
            return self.responde(200, corpo)

        if not r.startswith("/api/"):
            return self.responde(404, {"erro": "nao_encontrado"})
        if not self.exige():
            return

        # ------------------------------------------------- feedback
        # O que chega da tela de Comentarios do cliente. O admin le,
        # muda o estado e responde; a resposta volta para "Meus envios"
        # da propria pessoa.
        if r == "/api/feedback":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            filtro = {}
            tipo = (q.get("tipo") or [""])[0]
            estado = (q.get("estado") or [""])[0]
            if tipo in ("sugestao", "comentario", "bug"):
                filtro["tipo"] = tipo
            if estado in ("recebido", "analisando", "resolvido", "recusado"):
                filtro["estado"] = estado
            docs = list(db.dp_feedback.find(filtro).sort("em", -1).limit(300))
            perfis = perfis_de([d["uid"] for d in docs])
            return self.responde(200, {"itens": [
                {"id": str(d["_id"]), "tipo": d.get("tipo"),
                 "titulo": d.get("titulo"), "texto": d.get("texto"),
                 "estado": d.get("estado", "recebido"),
                 "resposta": d.get("resposta"), "em": d.get("em"),
                 "respondido_em": d.get("respondido_em"),
                 "uid": d.get("uid"),
                 "autor": perfis.get(d.get("uid"), {"nome": "?"})}
                for d in docs], "total": len(docs)})

        # ------------------------------------------------ novidades
        if r == "/api/novidades":
            docs = list(db.dp_novidades.find().sort("em", -1).limit(200))
            return self.responde(200, {"itens": [
                {"id": str(d["_id"]), "titulo": d.get("titulo"),
                 "texto": d.get("texto", ""), "em": d.get("em"),
                 "publicado": bool(d.get("publicado")),
                 "curtidas": int(d.get("curtidas", 0)),
                 "comentarios": int(d.get("comentarios", 0))}
                for d in docs]})

        m = re.fullmatch(r"/api/novidades/([0-9a-f]{24})/comentarios", r)
        if m:
            try:
                pid = ObjectId(m.group(1))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            # Inclui os removidos: tratar denuncia exige ver o que existiu.
            docs = list(db.dp_novidades_comentarios.find({"post": pid})
                        .sort("em", 1).limit(500))
            perfis = perfis_de([d["uid"] for d in docs])
            return self.responde(200, {"itens": [
                {"id": str(d["_id"]), "texto": d.get("texto", ""),
                 "em": d.get("em"), "uid": d.get("uid"),
                 "removido": bool(d.get("removido")),
                 "autor": perfis.get(d.get("uid"), {"nome": "?"})}
                for d in docs]})

        if r == "/api/metricas":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            dias = max(1, min(90, int((q.get("dias") or ["7"])[0])))
            return self.responde(200, metricas(dias))

        if r == "/api/resumo":
            return self.responde(200, {
                "contas": db.accounts.count_documents({}),
                "usuarios": db.users.count_documents({}),
                "servidores": db.servers.count_documents({}),
                "mensagens": db.messages.count_documents({}),
                "fila": db.fila_espera.count_documents({}),
                "fila_pendente": db.fila_espera.count_documents({"convidado": False}),
                "convites": db.account_invites.count_documents({}),
                "convites_livres": db.account_invites.count_documents(
                    {"used": {"$ne": True}}),
                "sessoes": db.sessions.count_documents({}),
                "banidos": db.painel_banidos.count_documents({}),
            })

        if r == "/api/usuarios":
            return self.responde(200, {"itens": lista_usuarios()})

        if r == "/api/fila":
            itens = [{"email": d["_id"], "nome": d.get("nome"),
                      "nascimento": d.get("nascimento"), "idade": d.get("idade"),
                      "em": d.get("em"), "convidado": bool(d.get("convidado")),
                      "codigo": d.get("codigo")}
                     for d in db.fila_espera.find().sort("em", 1)]
            return self.responde(200, {"itens": itens})

        if r == "/api/convites":
            itens = []
            for c in db.account_invites.find():
                dono = c.get("criado_por")
                u = db.users.find_one({"_id": dono}, {"username": 1}) if dono else None
                itens.append({"codigo": c["_id"], "usado": bool(c.get("used")),
                              "criado_por": dono,
                              "criado_por_nome": (u or {}).get("username"),
                              "usado_por": c.get("claimed_by"),
                              "origem": c.get("origem")})
            return self.responde(200, {"itens": itens})

        self.responde(404, {"erro": "nao_encontrado"})

    # --------------------------------------------------------------- POST
    def do_POST(self):
        r = self.rota()
        c = self.corpo()

        if r == "/api/login":
            ip = self.headers.get("X-Forwarded-For", self.client_address[0])
            ip = ip.split(",")[0].strip()
            n, ate = tentativas.get(ip, (0, 0))
            if ate > time.time():
                return self.responde(429, {
                    "erro": "bloqueado",
                    "mensagem": "Muitas tentativas. Aguarde um minuto."})
            if not turnstile_ok(c.get("turnstile"), ip):
                return self.responde(403, {"erro": "captcha",
                    "mensagem": "Verificação de segurança falhou. "
                                "Recarregue a página e tente de novo."})
            a = admin()
            if (c.get("usuario") or "").strip() != (a or {}).get("usuario") \
                    or not confere_senha(c.get("senha") or "", a):
                n += 1
                tentativas[ip] = (n, time.time() + 60 if n >= 5 else 0)
                return self.responde(401, {
                    "erro": "credenciais",
                    "mensagem": "Usuário ou senha incorretos."})
            tentativas.pop(ip, None)
            tok = cria_sessao()
            return self.responde(200, {"ok": True,
                "trocar_senha": bool(a.get("trocar_senha"))},
                [("Set-Cookie",
                  f"dp_painel={tok}; Path=/; HttpOnly; Secure; "
                  f"SameSite=Lax; Max-Age={SESSAO_H*3600}")])

        if r == "/api/logout":
            tok = self.cookie("dp_painel")
            if tok:
                db.painel_sessoes.delete_one({"_id": tok})
            return self.responde(200, {"ok": True},
                [("Set-Cookie", "dp_painel=; Path=/; HttpOnly; Secure; "
                                "SameSite=Lax; Max-Age=0")])

        if not self.exige():
            return

        # --------------------------------------- tratar um feedback
        m = re.fullmatch(r"/api/feedback/([0-9a-f]{24})", r)
        if m:
            try:
                fid = ObjectId(m.group(1))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            campos = {}
            estado = c.get("estado")
            if estado in ("recebido", "analisando", "resolvido", "recusado"):
                campos["estado"] = estado
            if "resposta" in c:
                texto = (c.get("resposta") or "").strip()[:4000]
                campos["resposta"] = texto or None
                campos["respondido_em"] = time.time() if texto else None
            if not campos:
                return self.responde(400, {"erro": "nada_a_mudar"})
            db.dp_feedback.update_one({"_id": fid}, {"$set": campos})
            return self.responde(200, {"ok": True})

        # -------------------------------------- criar/editar novidade
        if r == "/api/novidades":
            texto = (c.get("texto") or "").strip()[:560]
            if not texto:
                return self.responde(400, {"erro": "texto_obrigatorio"})
            doc = {"titulo": (c.get("titulo") or "").strip()[:120] or None,
                   "texto": texto, "em": time.time(),
                   "publicado": bool(c.get("publicado", True)),
                   "curtidas": 0, "comentarios": 0}
            res = db.dp_novidades.insert_one(doc)
            return self.responde(200, {"ok": True, "id": str(res.inserted_id)})

        m = re.fullmatch(r"/api/novidades/([0-9a-f]{24})", r)
        if m:
            try:
                pid = ObjectId(m.group(1))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            campos = {}
            if "texto" in c:
                texto = (c.get("texto") or "").strip()[:560]
                if not texto:
                    return self.responde(400, {"erro": "texto_obrigatorio"})
                campos["texto"] = texto
            if "titulo" in c:
                campos["titulo"] = (c.get("titulo") or "").strip()[:120] or None
            if "publicado" in c:
                campos["publicado"] = bool(c.get("publicado"))
            if not campos:
                return self.responde(400, {"erro": "nada_a_mudar"})
            db.dp_novidades.update_one({"_id": pid}, {"$set": campos})
            return self.responde(200, {"ok": True})

        m = re.fullmatch(r"/api/novidades/([0-9a-f]{24})/remover", r)
        if m:
            try:
                pid = ObjectId(m.group(1))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            # O post sai junto com o que pendurava nele. Deixar curtidas e
            # comentarios orfaos so acumularia lixo que ninguem le.
            db.dp_novidades.delete_one({"_id": pid})
            db.dp_novidades_curtidas.delete_many({"post": pid})
            db.dp_novidades_comentarios.delete_many({"post": pid})
            return self.responde(200, {"ok": True})

        m = re.fullmatch(r"/api/novidades/([0-9a-f]{24})/comentarios/"
                         r"([0-9a-f]{24})/remover", r)
        if m:
            try:
                pid, cid = ObjectId(m.group(1)), ObjectId(m.group(2))
            except Exception:
                return self.responde(404, {"erro": "nao_encontrado"})
            res = db.dp_novidades_comentarios.update_one(
                {"_id": cid, "post": pid, "removido": {"$ne": True}},
                {"$set": {"removido": True, "removido_em": time.time(),
                          "removido_por": "admin"}})
            if res.modified_count:
                db.dp_novidades.update_one({"_id": pid},
                                           {"$inc": {"comentarios": -1}})
            return self.responde(200, {"ok": True})

        if r == "/api/senha":
            atual = c.get("atual") or ""
            nova = c.get("nova") or ""
            usuario = (c.get("usuario") or "").strip()
            a = admin()
            if not confere_senha(atual, a):
                return self.responde(401, {"mensagem": "Senha atual incorreta."})

            mudou = {}
            if usuario and usuario != a.get("usuario"):
                if not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", usuario):
                    return self.responde(400, {"mensagem":
                        "Usuário: 3 a 32 caracteres, letras, números, "
                        ". _ -"})
                mudou["usuario"] = usuario
            if nova:
                if len(nova) < 10:
                    return self.responde(400, {"mensagem":
                        "A nova senha precisa de ao menos 10 caracteres."})
                d = hash_senha(nova)
                mudou.update({"sal": d["sal"], "hash": d["hash"],
                              "trocar_senha": False})
            if not mudou:
                return self.responde(400, {"mensagem": "Nada a alterar."})

            db.painel_admin.update_one({"_id": "admin"}, {"$set": mudou})
            db.painel_sessoes.delete_many({})   # derruba todas as sessões
            partes = []
            if "usuario" in mudou:
                partes.append("Usuário alterado")
            if "hash" in mudou:
                partes.append("senha alterada")
            return self.responde(200, {"ok": True,
                "mensagem": ". ".join(partes).capitalize() +
                            ". Entre novamente."})

        # ---- fila de espera
        if r == "/api/fila/convidar":
            email = (c.get("email") or "").strip().lower()
            d = db.fila_espera.find_one({"_id": email})
            if not d:
                return self.responde(404, {"mensagem": "Não está na fila."})
            with trava:
                codigo = secrets.token_hex(8)
                db.account_invites.insert_one(
                    {"_id": codigo, "origem": "fila:" + email})
                db.fila_espera.update_one({"_id": email}, {"$set": {
                    "convidado": True, "codigo": codigo,
                    "convidado_em": time.time()}})
            return self.responde(200, {"codigo": codigo,
                "link": f"https://chat.doispapo.com/login/create?invite={codigo}"})

        if r == "/api/fila/remover":
            email = (c.get("email") or "").strip().lower()
            db.fila_espera.delete_one({"_id": email})
            return self.responde(200, {"ok": True})

        # ---- usuários
        if r == "/api/usuarios/cota":
            uid, lim = c.get("id"), c.get("limite")
            if not uid or not isinstance(lim, int) or not (0 <= lim <= 500):
                return self.responde(400, {"mensagem": "Cota inválida."})
            db.painel_cotas.update_one({"_id": uid},
                {"$set": {"limite": lim}}, upsert=True)
            return self.responde(200, {"ok": True, "limite": lim})

        if r == "/api/usuarios/banir":
            uid, banir = c.get("id"), bool(c.get("banir", True))
            if not uid:
                return self.responde(400, {"mensagem": "Usuário inválido."})
            if banir:
                db.painel_banidos.update_one({"_id": uid},
                    {"$set": {"em": time.time(),
                              "motivo": (c.get("motivo") or "")[:200]}},
                    upsert=True)
                # encerra as sessões para o efeito ser imediato
                n = db.sessions.delete_many({"user_id": uid}).deleted_count
                return self.responde(200, {"ok": True, "sessoes_encerradas": n})
            db.painel_banidos.delete_one({"_id": uid})
            return self.responde(200, {"ok": True})

        if r == "/api/usuarios/sessoes":
            uid = c.get("id")
            n = db.sessions.delete_many({"user_id": uid}).deleted_count
            return self.responde(200, {"ok": True, "encerradas": n})

        if r == "/api/usuarios/remover":
            uid = c.get("id")
            if not uid or c.get("confirmacao") != "REMOVER":
                return self.responde(400, {
                    "mensagem": "Confirmação ausente."})
            rel = {}
            for col, filtro in [
                ("accounts", {"_id": uid}), ("users", {"_id": uid}),
                ("sessions", {"user_id": uid}),
                ("painel_cotas", {"_id": uid}),
                ("painel_banidos", {"_id": uid}),
            ]:
                rel[col] = db[col].delete_many(filtro).deleted_count
            return self.responde(200, {"ok": True, "removido": rel})

        # ---- convites
        if r == "/api/convites/criar":
            qtd = c.get("quantidade") or 1
            qtd = max(1, min(20, int(qtd)))
            dono = c.get("dono") or None
            codigos = []
            with trava:
                for _ in range(qtd):
                    cod = secrets.token_hex(8)
                    doc = {"_id": cod}
                    if dono:
                        doc["criado_por"] = dono
                    db.account_invites.insert_one(doc)
                    codigos.append(cod)
            return self.responde(200, {"codigos": codigos})

        if r == "/api/convites/remover":
            cod = c.get("codigo")
            d = db.account_invites.find_one({"_id": cod})
            if d and d.get("used"):
                return self.responde(409, {
                    "mensagem": "Convite já usado — não pode ser removido."})
            db.account_invites.delete_one({"_id": cod})
            return self.responde(200, {"ok": True})

        self.responde(404, {"erro": "nao_encontrado"})


if __name__ == "__main__":
    garante_admin()
    db.painel_sessoes.create_index("expira")
    db.fila_espera.create_index("em")
    print(f"painel em :{PORTA}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
