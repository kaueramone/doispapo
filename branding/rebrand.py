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
LINKS = {
    "https://ko-fi.com/stoatchat": "https://doispapo.com/apoie",
    "https://stoat.chat/terms":    "https://doispapo.com/termos",
    "https://stoat.chat/privacy":  "https://doispapo.com/privacidade",
    "https://stoat.chat/about":    "https://doispapo.com/sobre",
    "https://stoat.chat/aup":      "https://doispapo.com/uso-aceitavel",
}
for f in glob.glob(os.path.join(DST, "assets", "*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    for de, para in LINKS.items():
        if de in s_:
            conta("links", s_.count(de))
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
