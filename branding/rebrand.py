#!/usr/bin/env python3
"""
Aplica a marca Dois Papo sobre o build do cliente web.

Entrada : dist original extraido do container
Saida   : dist-patched, pronto para bind-mount em /app/dist

Idempotente: rodar de novo sobre a saida nao causa dano.
"""
import glob, json, os, re, shutil, sys

SRC   = sys.argv[1] if len(sys.argv) > 1 else "dist-orig"
DST   = sys.argv[2] if len(sys.argv) > 2 else "dist-patched"
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")

MARCA = "Dois Papo"
SITE  = "https://kaueramone.dev"
AUTOR = "kaueramone.dev"

stats = {}
def conta(chave, n):
    stats[chave] = stats.get(chave, 0) + n

# ---------------------------------------------------------------- preparo
if os.path.exists(DST):
    shutil.rmtree(DST)
shutil.copytree(SRC, DST)
print(f"copiado {SRC} -> {DST}")

# ------------------------------------------------- 1. arquivos de traducao
# Sao catalogos Lingui {"hash":["texto"]}. Os hashes nunca contem a marca,
# entao substituir e seguro. Verificado: nao ha URLs de marca aqui.
for f in glob.glob(os.path.join(DST, "assets", "messages-*.js")):
    s = open(f, encoding="utf-8").read()
    orig = s
    s = s.replace("Stoat", MARCA).replace("STOAT", MARCA.upper()).replace("stoat", "dois papo")
    if s != orig:
        n = orig.count("Stoat") + orig.count("STOAT") + orig.count("stoat")
        conta("locales", n)
        open(f, "w", encoding="utf-8").write(s)

# --------------------------------- 1b. CSS (ha texto visivel em content:)
for f in glob.glob(os.path.join(DST, "assets", "*.css")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    if "Stoat" in s_:
        conta("css", s_.count("Stoat"))
        open(f, "w", encoding="utf-8").write(s_.replace("Stoat", MARCA))

# --------------------------- 1c. links do upstream -> destinos proprios
# ko-fi do upstream vira a pagina de apoio propria; institucionais viram
# o dominio proprio. Sao links VISIVEIS na interface.
LINKS = [
    # ORDEM IMPORTA: as URLs mais especificas primeiro, senao a troca
    # generica de github.com/<org> corrompe os caminhos mais longos.
    ("https://github.com/stoatchat/for-web/issues",
     "https://github.com/kaueramone/doispapo/issues"),
    ("https://github.com/orgs/stoatchat/discussions/categories/feature-suggestions",
     "https://github.com/kaueramone/doispapo/discussions"),
    ("https://github.com/orgs/stoatchat/discussions/categories/feedback",
     "https://github.com/kaueramone/doispapo/discussions"),
    ("https://github.com/orgs/stoatchat/discussions",
     "https://github.com/kaueramone/doispapo/discussions"),
    ("https://github.com/stoatchat", "https://github.com/kaueramone/doispapo"),
    ("https://ko-fi.com/stoatchat", "https://doispapo.com/apoie"),
    ("https://stoat.chat/terms",    "https://doispapo.com/termos"),
    ("https://stoat.chat/privacy",  "https://doispapo.com/privacidade"),
    ("https://stoat.chat/about",    "https://doispapo.com/sobre"),
    ("https://stoat.chat/aup",      "https://doispapo.com/uso-aceitavel"),
]
for f in glob.glob(os.path.join(DST, "assets", "*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    for de, para in LINKS:
        if de in s_:
            conta("links", s_.count(de))
            s_ = s_.replace(de, para)
    if s_ != o_:
        open(f, "w", encoding="utf-8").write(s_)

# ------------------------- 1d. completar a traducao pt-BR
# O catalogo pt-BR do upstream vem com ~31% das entradas iguais ao ingles
# (nao traduzidas). Aplicamos as traducoes proprias por msgId.
trad_p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "traducoes_pt_br.json")
if os.path.exists(trad_p):
    trad = json.load(open(trad_p, encoding="utf-8"))
    for f in glob.glob(os.path.join(DST, "assets", "messages-*.js")):
        s_ = open(f, encoding="utf-8", errors="replace").read()
        # so mexe no catalogo que ja esta em portugues do Brasil
        if "[Ontem \u00e0s]" not in s_ and "[Ontem às]" not in s_:
            continue
        n_ = 0
        for chave, texto in trad.items():
            alvo = '"%s":[' % chave
            i = s_.find(alvo)
            if i < 0:
                continue
            j = s_.index("]", i)
            atual = s_[i + len(alvo):j]
            # so substitui entradas de string simples
            if not (atual.startswith('"') and atual.endswith('"')):
                continue
            novo_val = json.dumps(texto, ensure_ascii=False)
            # dentro de template literal: escapar crase e cifrao
            novo_val = novo_val.replace("\\", "\\\\").replace("`", "\\`")
            s_ = s_[:i + len(alvo)] + novo_val + s_[j:]
            n_ += 1
        conta("traducoes-pt-br", n_)
        open(f, "w", encoding="utf-8").write(s_)
        break

# --------------- 1e. traduz o catalogo de FALLBACK embutido no bundle
# Alguns componentes leem do catalogo ingles compilado dentro do
# index-*.js, e nao do chunk pt-BR carregado sob demanda — por isso
# apareciam telas em ingles mesmo com o resto traduzido. Como a instancia
# e monolingue pt-BR, tornamos o proprio fallback portugues, usando o
# catalogo pt-BR (ja completado na etapa anterior) como fonte.
pad_simples = re.compile(r'"([A-Za-z0-9+/_-]{6})":\["((?:[^"\\]|\\.)*)"\]')

fonte = {}
for f in glob.glob(os.path.join(DST, "assets", "messages-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    if "[Ontem" not in s_:
        continue
    fonte = {m.group(1): m.group(2) for m in pad_simples.finditer(s_)}
    break

if fonte:
    for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
        s_ = open(f, encoding="utf-8", errors="replace").read()
        n_ = 0
        def troca(m):
            global n_
            chave, ingles = m.group(1), m.group(2)
            pt = fonte.get(chave)
            if pt is None or pt == ingles:
                return m.group(0)
            n_ += 1
            return '"%s":["%s"]' % (chave, pt)
        novo_ = pad_simples.sub(troca, s_)
        if n_:
            conta("fallback-traduzido", n_)
            open(f, "w", encoding="utf-8").write(novo_)

# ------------- 1f. strings hardcoded (fora do sistema de traducao)
# Alguns componentes do upstream tem texto em ingles direto no codigo,
# sem passar pelo i18n — por isso apareciam em ingles em TODOS os idiomas.
# Casamos o par propriedade:"valor" para nao pegar chave interna homonima
# (ex.: id:"default" continua intacto; so title:"Default" muda).
HARDCODED = {
    'title:"Create a group or server"': 'title:"Criar um grupo ou servidor"',
    'title:"Create or join a server"':  'title:"Criar ou entrar em um servidor"',
    'text:"Group"':    'text:"Grupo"',
    'text:"Server"':   'text:"Servidor"',
    'text:"Create"':   'text:"Criar"',
    'text:"Join"':     'text:"Entrar"',
    'title:"Incoming"':'title:"Recebidos"',
    'title:"Outgoing"':'title:"Enviados"',
    'title:"Blocked"': 'title:"Bloqueados"',
    'title:"Default"': 'title:"Padr\u00e3o"',
}
for f in glob.glob(os.path.join(DST, "assets", "*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    for de, para in HARDCODED.items():
        if de in s_:
            conta("hardcoded", s_.count(de))
            s_ = s_.replace(de, para)
    if s_ != o_:
        open(f, "w", encoding="utf-8").write(s_)

# ---------------------------------------------------- 2. manifest do PWA
mf = os.path.join(DST, "manifest.webmanifest")
m = json.load(open(mf, encoding="utf-8"))
m["name"] = MARCA
m["short_name"] = MARCA
m["description"] = "Plataforma de comunicacao — texto, voz e compartilhamento de tela."
m["lang"] = "pt-BR"
json.dump(m, open(mf, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
conta("manifest", 3)

# ------------------------------------------------- 3. service worker
sw = os.path.join(DST, "serviceWorker.js")
s = open(sw, encoding="utf-8").read()
n = s.count('"Stoat"')
s = s.replace('"Stoat"', f'"{MARCA}"')
open(sw, "w", encoding="utf-8").write(s)
conta("serviceWorker", n)

# ---------------------------- 4. bundle principal: SOMENTE o usuario sistema
# NAO tocar em authentication.revolt nem type:"revolt" — sao identificadores
# de codigo; alterar quebra login e tratamento de erro.
for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s = open(f, encoding="utf-8").read()
    novo = s.replace('username:"Revolt"', f'username:"{MARCA}"')
    conta("usuario-sistema", s.count('username:"Revolt"'))
    # O catalogo ingles vem embutido aqui como locale de fallback.
    # Substituir SO 'Stoat' com caixa exata: 'stoat.chat' (minusculo) e
    # 'IS_STOAT' (maiusculo) sao identificadores/URLs e ficam intactos.
    conta("bundle-fallback", novo.count("Stoat"))
    novo = novo.replace("Stoat", MARCA)
    if novo != s:
        open(f, "w", encoding="utf-8").write(novo)

# Source maps: removidos. Nao sao usados em producao, pesam ~20 MB e
# expoem o codigo-fonte original com a marca antiga.
mapas = glob.glob(os.path.join(DST, "**", "*.map"), recursive=True)
for mp in mapas:
    os.remove(mp)
conta("sourcemaps-removidos", len(mapas))

# ------------------------------------------------- 5. index.html + injecao
qr_path = os.path.join(ASSETS, "pix", "pix-qrcode.datauri.txt")
qr = open(qr_path).read().strip() if os.path.exists(qr_path) else ""
pix_payload = ""
p = os.path.join(ASSETS, "pix", "payload.txt")
if os.path.exists(p):
    pix_payload = open(p).read().strip()

idx = os.path.join(DST, "index.html")
h = open(idx, encoding="utf-8").read()
h = h.replace("<title>Stoat</title>", f"<title>{MARCA}</title>")
h = h.replace('<html lang="en">', '<html lang="pt-BR">')
conta("index.html", 2)

INJECAO = """
<style id="dp-marca">
  /* Assinatura do desenvolvedor — canto superior direito */
  #dp-assinatura{position:fixed;top:0;right:0;z-index:2147483000;
    display:flex;align-items:center;gap:.35em;
    padding:5px 12px 6px;border-radius:0 0 0 10px;
    font:11px/1 system-ui,-apple-system,"Segoe UI",sans-serif;
    color:#8b93a7;background:rgba(16,24,35,.78);
    -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
    pointer-events:none;user-select:none}
  #dp-assinatura a{color:#8C41D9;text-decoration:none;font-weight:650;
    pointer-events:auto}
  #dp-assinatura a:hover{color:#2E8BEB;text-decoration:underline}

  /* Logo na tela de login */
  #dp-login-logo{display:block;width:min(230px,58vw);height:auto;
    margin:0 auto 26px}

  /* Rodapé do login: remove links institucionais herdados e o Bluesky.
     O GitHub fica, apontando para o repositório próprio. */
  a[href*="doispapo.com/sobre"],
  a[href*="doispapo.com/termos"],
  a[href*="doispapo.com/privacidade"],
  a[href*="doispapo.com/uso-aceitavel"],
  a[href*="bsky.app"],
  a[href*="translate."],
  a[href*="developers."]{display:none!important}
</style>
<script id="dp-marca-js">
(function(){
  var LOGO="/assets/web/wordmark.svg";

  function assinatura(){
    if(document.getElementById("dp-assinatura"))return;
    if(!document.body)return;
    var d=document.createElement("div");
    d.id="dp-assinatura";
    d.innerHTML='por <a href="__SITE__" target="_blank" rel="noopener">__AUTOR__</a>';
    document.body.appendChild(d);
  }

  // Insere a logo no topo da tela de login/cadastro.
  function loginLogo(){
    if(document.getElementById("dp-login-logo"))return;
    var campo=document.querySelector(
      'input[type="password"],input[type="email"],input[name="email"]');
    if(!campo)return;
    var anc=campo.closest("form");
    if(!anc){
      anc=campo;
      for(var i=0;i<3&&anc.parentElement;i++)anc=anc.parentElement;
    }
    if(!anc||!anc.parentNode)return;
    var img=document.createElement("img");
    img.id="dp-login-logo"; img.src=LOGO; img.alt="__MARCA__";
    anc.parentNode.insertBefore(img,anc);
  }


  function tick(){ assinatura(); loginLogo(); }
  if(document.readyState!=="loading")tick();
  else document.addEventListener("DOMContentLoaded",tick);
  new MutationObserver(tick).observe(document.documentElement,
    {childList:true,subtree:true});
})();
</script>
"""
INJECAO = (INJECAO.replace("__SITE__", SITE).replace("__AUTOR__", AUTOR)
           .replace("__MARCA__", MARCA))

if "dp-marca" not in h:
    h = h.replace("</body>", INJECAO + "\n</body>")
    conta("injecao", 1)
open(idx, "w", encoding="utf-8").write(h)

# ------------------------------- 4b. idioma padrao = portugues do Brasil
# O app escolhe pelo navigator.languages e so cai no fallback quando nao
# reconhece nenhum. Trocamos esse fallback de ENGLISH para pt-BR.
for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    novo_, n_ = re.subn(r"\?\?(\w+)\.ENGLISH", r"??\1.PORTUGUESE_BRAZIL", s_)
    if n_:
        conta("idioma-padrao", n_)
        open(f, "w", encoding="utf-8").write(novo_)

# ------------------------------- 5b. assets de imagem da marca
# Troca os proprios arquivos de logo. Assim a marca aparece no login,
# na home, no favicon e no PWA sem depender de descobrir qual tela usa
# qual asset.
try:
    from PIL import Image
    import base64, io

    LOGOS = os.path.join(ASSETS, "logos")
    simb  = Image.open(os.path.join(LOGOS, "doispapo-simbolo.png")).convert("RGBA")
    simb_b= Image.open(os.path.join(LOGOS, "doispapo-simbolo-white.png")).convert("RGBA")
    cheio = Image.open(os.path.join(LOGOS, "doispapo-logo-color.png")).convert("RGBA")

    def quadrado(src, lado, ocupa=0.92, fundo=None):
        """Centraliza a imagem num canvas quadrado."""
        c = Image.new("RGBA", (lado, lado), fundo or (0, 0, 0, 0))
        alvo = int(lado * ocupa)
        r = src.copy()
        r.thumbnail((alvo, alvo), Image.LANCZOS)
        c.paste(r, ((lado - r.width) // 2, (lado - r.height) // 2), r)
        return c

    web = os.path.join(DST, "assets", "web")
    if os.path.isdir(web):
        quadrado(simb, 192).save(os.path.join(web, "android-chrome-192x192.png"))
        quadrado(simb, 512).save(os.path.join(web, "android-chrome-512x512.png"))
        # maskable: o SO recorta as bordas, entao o simbolo fica menor
        # e sobre fundo solido da marca
        quadrado(simb, 512, 0.58, (16, 24, 35, 255)).save(
            os.path.join(web, "masking-512x512.png"))
        conta("icones-pwa", 3)

        def svg_com_png(img, caminho):
            buf = io.BytesIO(); img.save(buf, "PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
                   f'viewBox="0 0 {img.width} {img.height}" '
                   f'width="{img.width}" height="{img.height}">'
                   f'<image href="data:image/png;base64,{b64}" '
                   f'width="{img.width}" height="{img.height}"/></svg>')
            open(caminho, "w", encoding="utf-8").write(svg)

        m = simb_b.copy(); m.thumbnail((256, 256), Image.LANCZOS)
        svg_com_png(m, os.path.join(web, "monochrome.svg"))
        wm = cheio.copy(); wm.thumbnail((500, 500), Image.LANCZOS)
        svg_com_png(wm, os.path.join(web, "wordmark.svg"))
        conta("svgs-marca", 2)

        ico = quadrado(simb, 64)
        ico.save(os.path.join(web, "icon.ico"), sizes=[(16,16),(32,32),(48,48),(64,64)])
        conta("favicon", 1)

    # favicon com hash na raiz de assets/
    for f in glob.glob(os.path.join(DST, "assets", "icon-*.ico")):
        quadrado(simb, 64).save(f, sizes=[(16,16),(32,32),(48,48),(64,64)])
        conta("favicon", 1)

except ImportError:
    print("AVISO: PIL indisponivel, assets de imagem nao trocados")

# ------------------------- 4c. remove o pop-up de novidades na entrada
# dN() retorna null quando a resposta nao tem o formato esperado, e com
# null o modal nao abre. Apontamos para um data: URI que devolve {} —
# deterministico e sem depender de rede.
for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    s_ = s_.replace("https://changelog.stoat.chat/v1/changelogs/latest",
                    "data:application/json,%7B%7D")
    if s_ != o_:
        conta("popup-novidades-off", 1)
        open(f, "w", encoding="utf-8").write(s_)

# --------------------------------- 5c. invalidacao do service worker
# O SW (workbox) guarda os assets por hash de revisao e por nome de cache.
# Trocamos o CONTEUDO dos arquivos mantendo os NOMES, entao sem isso o
# navegador continua servindo a copia antiga para sempre.
import hashlib
sw_p = os.path.join(DST, "serviceWorker.js")
sw = open(sw_p, encoding="utf-8", errors="replace").read()

def md5(caminho):
    h = hashlib.md5()
    with open(caminho, "rb") as fh:
        for pedaco in iter(lambda: fh.read(8192), b""):
            h.update(pedaco)
    return h.hexdigest()

def corrige(m):
    url = m.group(2)
    alvo = os.path.join(DST, url)
    if os.path.exists(alvo):
        return '{"revision":"%s","url":"%s"}' % (md5(alvo), url)
    return m.group(0)

sw, n_rev = re.subn(r'\{"revision":"([^"]*)","url":"([^"]*)"\}', corrige, sw)
conta("precache-revisoes", n_rev)

# id de build: muda o nome dos caches, fazendo o workbox descartar os antigos
# O id precisa refletir o CONTEUDO, nao os nomes: os nomes dos arquivos
# nao mudam entre rebuilds, entao hashear a listagem manteria o mesmo nome
# de cache para sempre e o navegador nunca buscaria a versao nova.
_h = hashlib.md5()
for _f in sorted(glob.glob(os.path.join(DST, "assets", "index-*.js")) +
                 glob.glob(os.path.join(DST, "assets", "messages-*.js")) +
                 [os.path.join(DST, "index.html")]):
    _h.update(md5(_f).encode())
build_id = _h.hexdigest()[:10]
sw, n_cn = re.subn(r'precache-v\d+', f"precache-dp-{build_id}", sw)
conta("cache-renomeado", n_cn)

# assume o controle imediatamente, sem esperar todas as abas fecharem
if "skipWaiting" not in sw[:400]:
    sw = ("self.addEventListener('install',function(){self.skipWaiting()});\n"
          "self.addEventListener('activate',function(e){"
          "e.waitUntil(self.clients.claim())});\n") + sw
    conta("skipWaiting", 1)

open(sw_p, "w", encoding="utf-8").write(sw)

# ------------------------------------------------- 6. relatorio
print("\n=== SUBSTITUICOES ===")
for k, v in stats.items():
    print(f"  {k:<18} {v}")

resto = 0
for f in glob.glob(os.path.join(DST, "**", "*.js"), recursive=True) + \
         [idx, mf]:
    try:
        s = open(f, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    resto += len(re.findall(r"stoat", s, re.I))
print(f"\n  ocorrencias de 'stoat' restantes: {resto}")
print("  (esperado: apenas URLs padrao sobrescritas pelo env e identificadores de codigo)")
