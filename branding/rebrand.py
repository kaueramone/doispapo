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
  #dp-rodape{position:fixed;left:0;right:0;bottom:0;z-index:2147483000;
    display:flex;justify-content:center;align-items:center;gap:.4em;
    height:22px;font:11px/1 system-ui,-apple-system,"Segoe UI",sans-serif;
    color:#8b93a7;background:rgba(16,24,35,.82);
    -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
    pointer-events:none;user-select:none}
  #dp-rodape a{color:#8C41D9;text-decoration:none;pointer-events:auto;
    font-weight:600}
  #dp-rodape a:hover{text-decoration:underline;color:#2E8BEB}
  #dp-pix{margin-top:14px;padding:14px;border-radius:12px;
    background:rgba(140,65,217,.08);border:1px solid rgba(140,65,217,.25);
    text-align:center;font:13px/1.5 system-ui,sans-serif;color:inherit}
  #dp-pix img{width:200px;height:200px;border-radius:8px;display:block;
    margin:10px auto;background:#fff;padding:8px}
  #dp-pix code{display:block;word-break:break-all;font-size:10px;
    opacity:.65;margin-top:8px;line-height:1.4}

  /* Rodape do login: remove os links institucionais herdados e o Bluesky.
     O GitHub fica, apontando para o repositorio proprio (trocado no bundle). */
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
  var QR="__QR__", PAYLOAD="__PAYLOAD__";

  function rodape(){
    if(document.getElementById("dp-rodape"))return;
    var d=document.createElement("div");
    d.id="dp-rodape";
    d.innerHTML='desenvolvido por <a href="__SITE__" target="_blank" rel="noopener">__AUTOR__</a>';
    document.body.appendChild(d);
  }

  // Insere o QR do PIX abaixo do texto de doacao, quando ele aparecer.
  function pix(){
    if(!QR)return;
    var alvos=document.querySelectorAll("h1,h2,h3,h4,p,span,div,button,a");
    for(var i=0;i<alvos.length;i++){
      var el=alvos[i], t=(el.textContent||"").trim();
      if(t.length>60)continue;
      if(!/^(doar|donate|doa[cç][aã]o|apoiar)\\b/i.test(t))continue;
      if(el.querySelector("#dp-pix"))continue;
      var host=el.closest("section,div")||el.parentElement;
      if(!host||host.querySelector("#dp-pix"))continue;
      var box=document.createElement("div");
      box.id="dp-pix";
      box.innerHTML='<strong>Apoie o __MARCA__ via PIX</strong>'+
        '<img alt="QR Code PIX" src="'+QR+'">'+
        '<div>Chave: <strong>kaueramone@live.com</strong></div>'+
        '<code>'+PAYLOAD+'</code>';
      host.appendChild(box);
      return;
    }
  }

  function tick(){ rodape(); pix(); }
  if(document.readyState!=="loading")tick();
  else document.addEventListener("DOMContentLoaded",tick);
  new MutationObserver(tick).observe(document.documentElement,
    {childList:true,subtree:true});
})();
</script>
"""
INJECAO = (INJECAO.replace("__QR__", qr).replace("__PAYLOAD__", pix_payload)
           .replace("__SITE__", SITE).replace("__AUTOR__", AUTOR)
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
build_id = hashlib.md5("".join(sorted(os.listdir(os.path.join(DST, "assets")))).encode()).hexdigest()[:8]
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
