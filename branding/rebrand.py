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
# Versão exibida nas configurações: vem da tag mais recente do git, para
# não depender de eu lembrar de atualizar uma constante a cada release.
def _versao_do_git():
    import subprocess
    try:
        t = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=8)
        v = (t.stdout or "").strip().lstrip("v")
        return v if re.fullmatch(r"\d+(\.\d+)*", v or "") else None
    except Exception:
        return None

VERSAO_APP = _versao_do_git() or "0.0.0"
VERSAO_UPSTREAM = "0.14.1"
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
    ("https://developers.stoat.chat", "https://developers.doispapo.com"),
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
    # campos de busca e de escrita, também fora do i18n
    'placeholder:"Search messages..."':  'placeholder:"Buscar mensagens..."',
    'placeholder:"Search for emojis..."':'placeholder:"Buscar emojis..."',
    'placeholder:"Search for GIFs..."':  'placeholder:"Buscar GIFs..."',
    'placeholder:"Type here :D"':        'placeholder:"Escreva aqui :D"',
    # entrada composta (texto + variável): o aplicador de traduções só
    # mexe em texto simples, para não corromper a estrutura. Vai aqui.
    '"uJTQKq":["With "': '"uJTQKq":["Com "',
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

  #dp-login-logo{display:block;width:min(230px,58vw);height:auto;
    margin:0 auto 26px}

  a[href*="doispapo.com/sobre"],
  a[href*="doispapo.com/termos"],
  a[href*="doispapo.com/privacidade"],
  a[href*="doispapo.com/uso-aceitavel"],
  a[href*="bsky.app"],
  a[href*="translate."]{display:none!important}

  /* Painel de convites nas configuracoes */
  #dp-convites{margin:0 0 18px;padding:18px 20px;border-radius:14px;
    background:linear-gradient(150deg,rgba(46,139,235,.10),
      rgba(140,65,217,.10));border:1px solid rgba(140,65,217,.28);
    font:14px/1.55 system-ui,-apple-system,sans-serif;color:inherit}
  #dp-convites h3{margin:0 0 4px;font-size:15px;font-weight:700}
  #dp-convites .dp-sub{opacity:.72;font-size:12.5px;margin-bottom:12px}
  #dp-convites .dp-n{font-size:30px;font-weight:750;line-height:1;
    background:linear-gradient(100deg,#2E8BEB,#8C41D9);
    -webkit-background-clip:text;background-clip:text;color:transparent}
  #dp-convites .dp-lin{display:flex;align-items:baseline;gap:.5em;
    margin-bottom:12px}
  #dp-convites button{cursor:pointer;border:0;border-radius:9px;
    padding:9px 16px;font:650 13px system-ui,sans-serif;color:#fff;
    background:linear-gradient(100deg,#2E8BEB,#8C41D9)}
  #dp-convites button[disabled]{opacity:.45;cursor:not-allowed}
  #dp-convites ul{list-style:none;margin:12px 0 0;padding:0}
  #dp-convites li{display:flex;justify-content:space-between;gap:1em;
    padding:6px 9px;border-radius:7px;background:rgba(0,0,0,.16);
    margin-top:5px;font:12px/1.4 ui-monospace,monospace}
  #dp-convites li .dp-uso{opacity:.6;font-family:system-ui,sans-serif}
  #dp-convites li .dir{display:flex;align-items:center;gap:9px;
    flex-shrink:0}
  #dp-convites code{user-select:all}
  #dp-convites .copiar{cursor:pointer;border:1px solid rgba(140,65,217,.4);
    background:rgba(140,65,217,.12);color:inherit;border-radius:7px;
    padding:4px 10px;font:600 11.5px system-ui,sans-serif;white-space:nowrap;
    transition:background .15s,border-color .15s}
  #dp-convites .copiar:hover{background:rgba(140,65,217,.25);
    border-color:rgba(140,65,217,.7)}
  #dp-convites .copiar.feito{background:rgba(74,222,128,.16);
    border-color:rgba(74,222,128,.45)}

  /* Editor de imagem */
  #dp-ed{position:fixed;inset:0;z-index:2147483002;display:flex;
    align-items:center;justify-content:center;padding:20px;
    background:rgba(4,8,14,.82);-webkit-backdrop-filter:blur(4px);
    backdrop-filter:blur(4px);
    font:14px/1.5 system-ui,-apple-system,sans-serif;color:#e8edf6}
  #dp-ed .cx{background:#141d2b;border:1px solid #22304a;border-radius:16px;
    padding:20px;max-width:min(440px,92vw);width:100%}
  #dp-ed h4{margin:0 0 3px;font-size:16px;font-weight:700}
  #dp-ed .ajuda{opacity:.65;font-size:12.5px;margin-bottom:14px}
  #dp-ed .palco{position:relative;width:100%;aspect-ratio:1;
    border-radius:12px;overflow:hidden;background:#0b1119;cursor:grab;
    touch-action:none}
  #dp-ed .palco.arrastando{cursor:grabbing}
  #dp-ed canvas{display:block;width:100%;height:100%}
  #dp-ed .mascara{position:absolute;inset:0;pointer-events:none;
    box-shadow:0 0 0 9999px rgba(11,17,25,.55);border:2px solid #8C41D9}
  #dp-ed .mascara.circ{border-radius:50%}
  #dp-ed .linha{display:flex;align-items:center;gap:10px;margin-top:14px}
  #dp-ed input[type=range]{flex:1;accent-color:#8C41D9}
  #dp-ed .abas{display:flex;gap:6px;margin-top:12px}
  #dp-ed .abas button{flex:1;background:#0b1119;border:1px solid #22304a;
    color:#93a1bb;font:600 12.5px system-ui;padding:8px;border-radius:8px;
    cursor:pointer}
  #dp-ed .abas button.on{border-color:#8C41D9;color:#e8edf6;
    background:rgba(140,65,217,.16)}
  #dp-ed .acoes{display:flex;gap:10px;margin-top:16px}
  #dp-ed .acoes button{flex:1;cursor:pointer;border:0;border-radius:10px;
    padding:11px;font:650 13.5px system-ui}
  #dp-ed .cancelar{background:#22304a;color:#c7d1e4}
  #dp-ed .confirmar{background:linear-gradient(100deg,#2E8BEB,#8C41D9);
    color:#fff}

  /* Banner de nova versao */
  #dp-att{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);
    z-index:2147483001;display:flex;align-items:center;gap:12px;
    padding:11px 16px;border-radius:12px;
    font:13px/1 system-ui,-apple-system,sans-serif;color:#e8edf6;
    background:rgba(16,24,35,.96);border:1px solid rgba(140,65,217,.45);
    box-shadow:0 12px 34px -10px rgba(0,0,0,.7)}
  #dp-att button{cursor:pointer;border:0;border-radius:8px;
    padding:8px 14px;font:650 12.5px system-ui,sans-serif;color:#fff;
    background:linear-gradient(100deg,#2E8BEB,#8C41D9)}

  /* Aviso na tela de cadastro */
  #dp-aviso-convite{margin:0 0 16px;padding:12px 14px;border-radius:10px;
    font:13px/1.5 system-ui,sans-serif;
    background:rgba(140,65,217,.12);border:1px solid rgba(140,65,217,.3)}
  #dp-aviso-convite.dp-erro{background:rgba(235,68,68,.12);
    border-color:rgba(235,68,68,.35)}
</style>
<script id="dp-marca-js">
(function(){
  var LOGO="/assets/web/wordmark.svg", API="/api-convites", TOKEN=null;

  /* ---- captura o token de sessao das requisicoes do proprio app ---- */
  var _fetch=window.fetch;
  window.fetch=function(entrada,init){
    try{
      var h=(init&&init.headers)||(entrada&&entrada.headers);
      if(h){
        var t=h.get?h.get("X-Session-Token"):h["X-Session-Token"];
        if(t)TOKEN=t;
      }
    }catch(e){}
    return _fetch.apply(this,arguments);
  };
  var _srh=XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.setRequestHeader=function(n,v){
    if(String(n).toLowerCase()==="x-session-token")TOKEN=v;
    return _srh.apply(this,arguments);
  };

  function api(rota,opc){
    opc=opc||{};
    opc.headers=Object.assign({"Content-Type":"application/json"},
      opc.headers||{}, TOKEN?{"X-Session-Token":TOKEN}:{});
    return fetch(API+rota,opc).then(function(r){
      return r.json().then(function(j){ return {status:r.status,dados:j}; });
    });
  }

  /* ---------------------------- assinatura ---------------------------- */
  function assinatura(){
    if(document.getElementById("dp-assinatura")||!document.body)return;
    var d=document.createElement("div");
    d.id="dp-assinatura";
    d.innerHTML='por <a href="__SITE__" target="_blank" rel="noopener">__AUTOR__</a>';
    document.body.appendChild(d);
  }

  /* ------------------------- logo no login ---------------------------- */
  function loginLogo(){
    if(document.getElementById("dp-login-logo"))return;
    var campo=document.querySelector(
      'input[type="password"],input[type="email"],input[name="email"]');
    if(!campo)return;
    var anc=campo.closest("form");
    if(!anc){ anc=campo;
      for(var i=0;i<3&&anc.parentElement;i++)anc=anc.parentElement; }
    if(!anc||!anc.parentNode)return;
    var img=document.createElement("img");
    img.id="dp-login-logo"; img.src=LOGO; img.alt="__MARCA__";
    anc.parentNode.insertBefore(img,anc);
  }

  /* ------- convite de servidor -> convite de conta (sem login) -------- */
  var m=location.pathname.match(/^\\/invite\\/([A-Za-z0-9_-]+)/);
  if(m){ try{ sessionStorage.setItem("dp_convite_srv",m[1]); }catch(e){} }

  var resgatando=false;
  function preencheConvite(){
    var srv=null;
    try{ srv=sessionStorage.getItem("dp_convite_srv"); }catch(e){}
    if(!srv||resgatando)return;
    // campo de codigo de convite na tela de cadastro
    var alvo=null, ins=document.querySelectorAll("input");
    for(var i=0;i<ins.length;i++){
      var el=ins[i], ctx=((el.placeholder||"")+" "+(el.name||"")+" "+
        (el.getAttribute("aria-label")||"")).toLowerCase();
      if(/convite|invite/.test(ctx)){ alvo=el; break; }
    }
    if(!alvo||alvo.value)return;
    resgatando=true;
    api("/resgatar",{method:"POST",body:JSON.stringify({codigo:srv})})
      .then(function(r){
        var box=document.createElement("div");
        box.id="dp-aviso-convite";
        if(r.status===200&&r.dados.codigo){
          alvo.value=r.dados.codigo;
          // avisa os frameworks reativos da mudanca
          alvo.dispatchEvent(new Event("input",{bubbles:true}));
          alvo.dispatchEvent(new Event("change",{bubbles:true}));
          box.textContent="Convite aplicado automaticamente. "+
            "Basta preencher seus dados para criar a conta.";
        }else if(r.dados.erro==="sem_cota"){
          box.className="dp-erro";
          box.textContent=r.dados.mensagem||
            "Quem te convidou não tem mais convites disponíveis.";
        }else{ resgatando=false; return; }
        var anc=alvo.closest("form")||alvo.parentElement;
        if(anc&&anc.parentNode&&!document.getElementById("dp-aviso-convite"))
          anc.parentNode.insertBefore(box,anc);
      })
      .catch(function(){ resgatando=false; });
  }

  /* -------------- painel de convites nas configuracoes ---------------- */
  function painelConvites(){
    if(document.getElementById("dp-convites"))return;
    // Ancora no item "Encerrar sessao", que so existe na tela de
    // configuracoes e e estavel — diferente de cabecalhos genericos.
    var anc=null, cand=document.querySelectorAll("div,li,button,a,span");
    for(var i=0;i<cand.length;i++){
      var t=(cand[i].textContent||"").trim();
      if(t.length>28)continue;
      if(!/^(encerrar sess|sair da conta|log ?out)/i.test(t))continue;
      anc=cand[i];
      // sobe ate um bloco com irmaos, para inserir na lista
      for(var k=0;k<4&&anc.parentElement;k++){
        if(anc.parentElement.children.length>1)break;
        anc=anc.parentElement;
      }
      break;
    }
    if(!anc||!anc.parentNode)return;

    var cx=document.createElement("div");
    cx.id="dp-convites";
    cx.innerHTML='<h3>Seus convites</h3>'+
      '<div class="dp-sub">Cada conta pode convidar até 5 pessoas para '+
      'criar conta no Dois Papo.</div>'+
      '<div class="dp-lin"><span class="dp-n" id="dp-n">–</span>'+
      '<span>disponíveis</span></div>'+
      '<button id="dp-gerar">Gerar convite</button>'+
      '<ul id="dp-lista"></ul>';
    anc.parentNode.insertBefore(cx,anc);

    function pinta(d){
      var n=document.getElementById("dp-n"); if(!n)return;
      n.textContent=d.disponiveis;
      var b=document.getElementById("dp-gerar");
      b.disabled=d.disponiveis<=0;
      if(d.disponiveis<=0)b.textContent="Sem convites disponíveis";
      var ul=document.getElementById("dp-lista");
      ul.innerHTML="";
      (d.codigos||[]).forEach(function(c){
        var li=document.createElement("li");
        li.innerHTML='<code>'+c.codigo+'</code>'+
          '<span class="dir"><span class="dp-uso">'+
          (c.usado?"usado":"disponível")+'</span>'+
          (c.usado?'':'<button type="button" class="copiar">'+
                     'copiar link</button>')+'</span>';
        var bt=li.querySelector(".copiar");
        if(bt)bt.addEventListener("click",function(e){
          e.preventDefault(); e.stopPropagation();
          var b=this;
          navigator.clipboard.writeText(
            location.origin+"/login/create?invite="+c.codigo
          ).then(function(){
            b.textContent="copiado!"; b.classList.add("feito");
            setTimeout(function(){
              b.textContent="copiar link"; b.classList.remove("feito");
            },1800);
          }).catch(function(){
            b.textContent="não deu"; 
            setTimeout(function(){ b.textContent="copiar link"; },1800);
          });
        });
        ul.appendChild(li);
      });
    }
    function erro(msg){
      var n=document.getElementById("dp-n"); if(n)n.textContent="?";
      var s=cx.querySelector(".dp-sub"); if(s)s.textContent=msg;
    }
    var tentativas=0;
    function carregar(){
      api("/saldo").then(function(r){
        if(r.status===200){ pinta(r.dados); return; }
        if(r.status===401&&tentativas<20){
          // O token so aparece quando o app faz sua primeira chamada a
          // API. Insistimos em vez de desistir na primeira negativa.
          tentativas++;
          erro("Carregando seus convites…");
          setTimeout(carregar,1500);
          return;
        }
        if(r.status===401)erro("Não foi possível identificar sua sessão. "+
          "Recarregue a página.");
        else erro("Não foi possível carregar seus convites.");
      }).catch(function(){
        if(tentativas<20){ tentativas++; setTimeout(carregar,1500); }
        else erro("Serviço de convites indisponível.");
      });
    }
    carregar();
    document.getElementById("dp-gerar").addEventListener("click",function(){
      api("/gerar",{method:"POST"}).then(carregar).catch(function(){});
    });
  }


  /* --------------------- editor de imagem ----------------------------- */
  function abrirEditor(arquivo, aoConcluir, aoCancelar){
    var url=URL.createObjectURL(arquivo), img=new Image();
    img.onload=function(){ montar(); };
    img.onerror=function(){ URL.revokeObjectURL(url); aoCancelar(); };
    img.src=url;

    function montar(){
      var LADO=512, redondo=true, esc=1, escMin=1, x=0, y=0;

      var ov=document.createElement("div");
      ov.id="dp-ed";
      ov.innerHTML=
        '<div class="cx">'+
          '<h4>Ajustar imagem</h4>'+
          '<div class="ajuda">Arraste para escolher o enquadramento e use '+
          'o controle para aproximar.</div>'+
          '<div class="palco"><canvas></canvas>'+
            '<div class="mascara circ"></div></div>'+
          '<div class="abas">'+
            '<button data-f="1" class="on">Quadrada</button>'+
            '<button data-f="1.78">Larga (16:9)</button>'+
          '</div>'+
          '<div class="linha"><span>Zoom</span>'+
            '<input type="range" min="100" max="400" value="100"></div>'+
          '<div class="acoes">'+
            '<button class="cancelar">Cancelar</button>'+
            '<button class="confirmar">Usar imagem</button>'+
          '</div>'+
        '</div>';
      document.body.appendChild(ov);

      var palco=ov.querySelector(".palco"), cv=ov.querySelector("canvas"),
          ctx=cv.getContext("2d"), masc=ov.querySelector(".mascara"),
          zoom=ov.querySelector("input[type=range]"), prop=1;

      function dimensionar(){
        var lc=palco.clientWidth, ac=Math.round(lc/prop);
        palco.style.aspectRatio=String(prop);
        cv.width=lc; cv.height=ac;
        escMin=Math.max(lc/img.width, ac/img.height);
        if(esc<escMin)esc=escMin;
        zoom.value=String(Math.round(esc/escMin*100));
        limitar(); desenhar();
      }
      function limitar(){
        var lc=cv.width, ac=cv.height,
            li=img.width*esc, ai=img.height*esc;
        x=Math.min(0,Math.max(x,lc-li));
        y=Math.min(0,Math.max(y,ac-ai));
        if(li<lc)x=(lc-li)/2;
        if(ai<ac)y=(ac-ai)/2;
      }
      function desenhar(){
        ctx.clearRect(0,0,cv.width,cv.height);
        ctx.drawImage(img,x,y,img.width*esc,img.height*esc);
      }

      // arrastar
      var arr=false,px=0,py=0;
      function ini(e){ arr=true; palco.classList.add("arrastando");
        var p=e.touches?e.touches[0]:e; px=p.clientX; py=p.clientY; }
      function mov(e){ if(!arr)return; e.preventDefault();
        var p=e.touches?e.touches[0]:e;
        x+=p.clientX-px; y+=p.clientY-py; px=p.clientX; py=p.clientY;
        limitar(); desenhar(); }
      function fim(){ arr=false; palco.classList.remove("arrastando"); }
      palco.addEventListener("mousedown",ini);
      palco.addEventListener("touchstart",ini,{passive:true});
      window.addEventListener("mousemove",mov);
      window.addEventListener("touchmove",mov,{passive:false});
      window.addEventListener("mouseup",fim);
      window.addEventListener("touchend",fim);

      zoom.addEventListener("input",function(){
        var cx=cv.width/2, cy=cv.height/2, antes=esc;
        esc=escMin*(parseInt(zoom.value,10)/100);
        // mantem o centro visual estavel ao aproximar
        x=cx-(cx-x)*(esc/antes);
        y=cy-(cy-y)*(esc/antes);
        limitar(); desenhar();
      });

      ov.querySelectorAll(".abas button").forEach(function(b){
        b.addEventListener("click",function(){
          ov.querySelectorAll(".abas button").forEach(function(o){
            o.classList.remove("on"); });
          b.classList.add("on");
          prop=parseFloat(b.dataset.f); redondo=prop===1;
          masc.classList.toggle("circ",redondo);
          dimensionar();
        });
      });

      function encerrar(){
        window.removeEventListener("mousemove",mov);
        window.removeEventListener("touchmove",mov);
        window.removeEventListener("mouseup",fim);
        window.removeEventListener("touchend",fim);
        URL.revokeObjectURL(url); ov.remove();
      }
      ov.querySelector(".cancelar").addEventListener("click",function(){
        encerrar(); aoCancelar(); });
      ov.querySelector(".confirmar").addEventListener("click",function(){
        var lf=LADO, af=Math.round(LADO/prop);
        var saida=document.createElement("canvas");
        saida.width=lf; saida.height=af;
        var k=lf/cv.width;
        saida.getContext("2d").drawImage(img, x*k, y*k,
          img.width*esc*k, img.height*esc*k);
        saida.toBlob(function(b){ encerrar(); aoConcluir(b); },
          "image/png");
      });

      dimensionar();
      window.addEventListener("resize",dimensionar);
    }
  }

  // Intercepta o envio de imagem antes de o app ler o arquivo.
  document.addEventListener("change",function(e){
    var inp=e.target;
    if(!inp||inp.tagName!=="INPUT"||inp.type!=="file")return;
    if(inp.getAttribute("data-dp-pronto")){
      inp.removeAttribute("data-dp-pronto"); return; }
    var f=inp.files&&inp.files[0];
    if(!f||!/^image\//.test(f.type))return;
    if(typeof DataTransfer==="undefined")return;
    e.stopImmediatePropagation(); e.preventDefault();
    abrirEditor(f,function(blob){
      try{
        var dt=new DataTransfer();
        dt.items.add(new File([blob],
          (f.name||"imagem").replace(/\.\w+$/,"")+".png",
          {type:"image/png"}));
        inp.setAttribute("data-dp-pronto","1");
        inp.files=dt.files;
        inp.dispatchEvent(new Event("change",{bubbles:true}));
      }catch(err){}
    },function(){ try{ inp.value=""; }catch(err){} });
  },true);

  /* ------------------- auto-atualizacao de versao -------------------- */
  var VERSAO="__BUILD__", avisando=false;

  function limparERecarregar(nova){
    try{
      // evita laco de recarga se algo der errado
      if(sessionStorage.getItem("dp_atualizando")===nova)return;
      sessionStorage.setItem("dp_atualizando",nova);
    }catch(e){}
    var tarefas=[];
    if(window.caches)tarefas.push(caches.keys().then(function(ks){
      return Promise.all(ks.map(function(k){ return caches.delete(k); }));
    }));
    if(navigator.serviceWorker)tarefas.push(
      navigator.serviceWorker.getRegistrations().then(function(rs){
        return Promise.all(rs.map(function(r){ return r.unregister(); }));
      }));
    Promise.all(tarefas).catch(function(){}).then(function(){
      location.reload();
    });
  }

  function banner(nova){
    if(avisando||document.getElementById("dp-att"))return;
    avisando=true;
    var d=document.createElement("div");
    d.id="dp-att";
    d.innerHTML='<span>Nova versão disponível.</span>'+
      '<button id="dp-att-b">Atualizar agora</button>';
    document.body.appendChild(d);
    document.getElementById("dp-att-b")
      .addEventListener("click",function(){ limparERecarregar(nova); });
  }

  function checarVersao(inicial){
    fetch("/versao.json",{cache:"no-store"})
      .then(function(r){ return r.json(); })
      .then(function(v){
        if(!v||!v.build||v.build===VERSAO)return;
        // No carregamento, atualiza direto: nada foi digitado ainda.
        // Com o app aberto, apenas avisa — recarregar sozinho apagaria
        // uma mensagem sendo escrita.
        if(inicial)limparERecarregar(v.build);
        else banner(v.build);
      })
      .catch(function(){});
  }

  checarVersao(true);
  setInterval(function(){ checarVersao(false); }, 300000);

  function tick(){ assinatura(); loginLogo(); preencheConvite();
                   painelConvites(); }
  if(document.readyState!=="loading")tick();
  else document.addEventListener("DOMContentLoaded",tick);
  new MutationObserver(tick).observe(document.documentElement,
    {childList:true,subtree:true});
})();
</script>
"""
INJECAO = (INJECAO.replace("__SITE__", SITE).replace("__AUTOR__", AUTOR)
           .replace("__MARCA__", MARCA))

# Áudio: precisa ser avaliado ANTES do módulo do app, para embrulhar o
# getUserMedia antes de o shim do webrtc-adapter embrulhar por cima.
# Script inline no fim do body roda durante a análise do HTML; módulos
# são adiados, então a ordem fica garantida.
_base = os.path.dirname(os.path.abspath(__file__))
# ORDEM IMPORTA: audio.js define window.dpAudio, do qual audio-ui.js
# depende. Montar a lista e prefixar UMA vez preserva a ordem; prefixar
# dentro do laço a inverteria, e a interface sairia na primeira linha por
# não encontrar o módulo ainda.
_scripts = ""
for _arq, _id in (("audio.js", "dp-audio"),
                  ("audio-ui.js", "dp-audio-ui"),
                  ("voz.js", "dp-voz")):
    _cam = os.path.join(_base, _arq)
    if not os.path.exists(_cam) or _id in h:
        continue
    _js = open(_cam, encoding="utf-8").read()
    _scripts += f'<script id="{_id}">\n{_js}\n</script>\n'
    conta("audio", 1)
INJECAO = _scripts + INJECAO

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

# ------------- 5d. wordmark inline no bundle + versao do app
# O logotipo da tela de login e da home NAO e um arquivo: e um <svg>
# inline dentro de um template do framework (500x94). Trocamos o path
# vetorial por um <image> que aponta para a nossa logo branca.
try:
    from PIL import Image as _Img
    _branca = _Img.open(os.path.join(ASSETS, "logos",
                                     "doispapo-logo-white.png")).convert("RGBA")
    _w = os.path.join(DST, "assets", "web")
    os.makedirs(_w, exist_ok=True)
    _r = _branca.copy()
    _r.thumbnail((520, 520), _Img.LANCZOS)
    _r.save(os.path.join(_w, "logo-branco.png"))
    _prop = _r.width / _r.height
except Exception:
    _prop = 1.3

_ALT = 94
_LARG = int(_ALT * _prop)
_novo_svg = ('<svg xmlns=http://www.w3.org/2000/svg width=%d height=%d '
             'fill=none viewBox="0 0 %d %d"><image '
             'href="/assets/web/logo-branco.png" width=%d height=%d '
             'preserveAspectRatio="xMidYMid meet"></image></svg>'
             % (_LARG, _ALT, _LARG, _ALT, _LARG, _ALT))

_ABRE = "<svg xmlns=http://www.w3.org/2000/svg width=500 height=94 fill=none>"
for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    i_ = s_.find(_ABRE)
    if i_ < 0:
        continue
    # O template e C('<svg ...><path d="...">') e termina logo apos o
    # path — nao ha </svg>, o framework fecha sozinho. Por isso NAO se
    # pode cortar ate o proximo </svg>: ele pertence a outro template
    # 47 mil caracteres adiante, e apaga-lo destroi o bundle.
    # Trocamos exclusivamente o elemento <path>.
    ip_ = s_.find('<path d="M478.909', i_)
    if ip_ < 0:
        continue
    fd_ = s_.find('d="', ip_) + 3
    fa_ = s_.find('"', fd_)          # fim do atributo d
    fp_ = s_.find(">", fa_)          # fim da tag <path ...>
    if fa_ < 0 or fp_ < 0 or fp_ - ip_ > 12000:
        print("AVISO: limites do path inesperados, wordmark nao trocado")
        continue

    _img = ('<image href="/assets/web/logo-branco.png" width=%d height=%d '
            'preserveAspectRatio="xMidYMid meet">' % (_LARG, _ALT))
    antes_, depois_ = s_[:ip_], s_[fp_ + 1:]
    s_ = antes_ + _img + depois_

    # a caixa do svg era feita para um logotipo largo; ajusta para a
    # proporcao da nossa logo, senao ela fica perdida no meio do vao
    s_ = s_.replace(_ABRE,
        "<svg xmlns=http://www.w3.org/2000/svg width=%d height=%d "
        "fill=none viewBox=\"0 0 %d %d\">" % (_LARG, _ALT, _LARG, _ALT), 1)
    # TRAVA: confirma que o literal do template continua bem fechado.
    # Uma edicao que estoure os limites da string quebra o bundle inteiro
    # e o node --check nao necessariamente acusa.
    _iz = s_.find("var ZUe=C(")
    if _iz >= 0:
        _jz = _iz + len("var ZUe=C(")
        _asp = s_[_jz]
        _k = _jz + 1
        while _k < len(s_):
            if s_[_k] == "\\":
                _k += 2; continue
            if s_[_k] == _asp:
                break
            _k += 1
        if s_[_k + 1:_k + 3] != "')" and s_[_k + 1:_k + 2] != ")":
            raise SystemExit(
                "ABORTADO: o template do wordmark ficou malformado "
                "(fecha com %r seguido de %r). Nada foi gravado."
                % (s_[_k], s_[_k+1:_k+12]))

    conta("wordmark-inline", 1)

    # Versao exibida nas configuracoes: a do upstream nao diz nada para
    # quem usa a nossa instancia.
    n_v = s_.count('"%s"' % VERSAO_UPSTREAM)
    if n_v:
        s_ = s_.replace('"%s"' % VERSAO_UPSTREAM, '"%s"' % VERSAO_APP)
        conta("versao-app", n_v)

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

# Arquivo de versao consultado pelo cliente para detectar atualizacao.
json.dump({"build": build_id}, open(os.path.join(DST, "versao.json"), "w"))

# Carimba o build id no script injetado.
_idx = os.path.join(DST, "index.html")
_h = open(_idx, encoding="utf-8").read()
if "__BUILD__" in _h:
    open(_idx, "w", encoding="utf-8").write(_h.replace("__BUILD__", build_id))

# Na ativacao, o SW apaga qualquer cache que nao seja deste build.
_guarda = ("self.addEventListener('activate',function(e){e.waitUntil("
           "caches.keys().then(function(ks){return Promise.all(ks.filter("
           "function(k){return k.indexOf('%s')===-1}).map(function(k){"
           "return caches.delete(k)}))}))});\n" % build_id)
if "dp-guarda-cache" not in sw:
    sw = "// dp-guarda-cache\n" + _guarda + sw
    conta("guarda-cache", 1)

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
