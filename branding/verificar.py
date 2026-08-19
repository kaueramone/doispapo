#!/usr/bin/env python3
"""Confere um build da marca ANTES de ele entrar no ar.

Existe porque uma publicacao com o index.html pela metade ficou horas no ar
sem ninguem perceber: o navegador guardava o arquivo truncado e passava a
exibir o codigo dos scripts como texto na tela. Aqui as conferencias sao
baratas e rodam antes da troca, quando ainda da para abortar sem prejuizo.
"""
import sys, os, re, json, hashlib
from html.parser import HTMLParser

DST = sys.argv[1]
erros, avisos = [], []

def md5(caminho):
    h = hashlib.md5()
    with open(caminho, "rb") as fh:
        for p in iter(lambda: fh.read(8192), b""):
            h.update(p)
    return h.hexdigest()

# ---------------------------------------------- 1. index.html bem formado
idx = os.path.join(DST, "index.html")
if not os.path.exists(idx):
    erros.append("index.html nao existe")
    print("\n".join(erros)); sys.exit(1)

h = open(idx, encoding="utf-8").read()
if len(h) < 40000:
    erros.append(f"index.html suspeito de truncagem: {len(h)} caracteres")
if not h.rstrip().endswith("</html>") and "</body>" not in h[-200:]:
    erros.append("index.html nao termina em </body>/</html> — truncado?")

ab = len(re.findall(r"<script\b", h))
fe = len(re.findall(r"</script\s*>", h))
if ab != fe:
    erros.append(f"tags de script desbalanceadas: {ab} abrem, {fe} fecham")

# Sequencias que encerram o modo de leitura de script dentro de um <script>
for m in re.finditer(r'<script[^>]*>(.*?)</script\s*>', h, re.S):
    corpo = m.group(1)
    for seq in ("</script", "<script", "<!--"):
        if seq in corpo:
            erros.append(f"sequencia {seq!r} dentro de um bloco <script> — "
                         "o analisador encerraria o script ali")

class Conta(HTMLParser):
    def __init__(self):
        super().__init__(); self.pilha = []; self.texto_solto = 0
        self.vazias = {"area","base","br","col","embed","hr","img","input",
                       "link","meta","param","source","track","wbr"}
    def handle_starttag(self, t, a):
        if t not in self.vazias: self.pilha.append(t)
    def handle_endtag(self, t):
        if t in self.pilha:
            while self.pilha and self.pilha.pop() != t: pass
    def handle_data(self, d):
        # codigo vazando como texto visivel no corpo da pagina
        if self.pilha and self.pilha[-1] in ("body", "div") and \
           re.search(r"function\s*\(|=>|addEventListener", d):
            self.texto_solto += 1

c = Conta(); c.feed(h)
if c.pilha:
    erros.append(f"tags sem fechamento: {c.pilha[:6]}")
if c.texto_solto:
    erros.append(f"{c.texto_solto} trecho(s) de codigo vazando como texto")

# ------------------ 1b. ids de tag nao podem colidir com a interface
# Um <script id="X"> e um elemento id="X" fazem o seletor "#X" casar com
# os dois. O script herda position/display do painel, o display:none que
# o navegador da a scripts e sobrescrito, e o codigo-fonte vira uma
# sobreposicao em tela cheia que bloqueia a pagina inteira. Aconteceu com
# "dp-som", que nomeava ao mesmo tempo a tag e o modal de som.
ids = re.findall(r'<(?:script|style)\s[^>]*id="([^"]+)"', h)
vistos = {}
for i in re.findall(r'\sid="([^"]+)"', h):
    vistos[i] = vistos.get(i, 0) + 1

for i in ids:
    # regra CSS "#id{" ou "#id " em qualquer lugar: estilo estatico do
    # documento ou CSS embutido em string de JS, injetado em tempo de uso
    if re.search(r'#' + re.escape(i) + r'\s*(?:\{|,|\s+[.:\[a-zA-Z])', h):
        erros.append(f'a tag <script/style id="{i}"> e alvo de um seletor '
                     f'CSS "#{i}" — o codigo-fonte apareceria na tela')
    if vistos.get(i, 0) > 1:
        erros.append(f'id "{i}" usado {vistos[i]}x: a tag colide com um '
                     'elemento da interface')

# qualquer id repetido no documento e defeito, mesmo fora de tags
for i, n in vistos.items():
    if n > 1 and i not in ids:
        avisos.append(f'id "{i}" repetido {n}x no documento')

# --------------------------------- 2. precache: revisao bate com o arquivo
sw_p = os.path.join(DST, "serviceWorker.js")
if os.path.exists(sw_p):
    sw = open(sw_p, encoding="utf-8", errors="replace").read()
    faltando = divergentes = 0
    for rev, url in re.findall(r'\{"revision":"([^"]+)","url":"([^"]+)"\}', sw):
        alvo = os.path.join(DST, url)
        if not os.path.exists(alvo):
            faltando += 1
        elif md5(alvo) != rev:
            divergentes += 1
            if url == "index.html":
                erros.append("revisao do index.html no service worker nao "
                             "corresponde ao arquivo — o navegador guardaria "
                             "uma copia com identidade errada")
    if faltando:
        erros.append(f"{faltando} arquivo(s) do precache nao existem")
    if divergentes:
        (erros if divergentes > 1 else avisos).append(
            f"{divergentes} revisao(oes) do precache divergem do arquivo")
else:
    erros.append("serviceWorker.js nao existe")

# ------------------------- 2b. a pagina de som entrou nas configuracoes
# O remendo casa identificadores minificados. Se o upstream renomear algo,
# a substituicao nao encontra o alvo e falha calada: a entrada some da
# lista sem nenhum erro. Conferir aqui transforma isso num build reprovado.
bundle = ""
for _b in sorted(os.listdir(os.path.join(DST, "assets"))):
    if _b.startswith("index-") and _b.endswith(".js"):
        bundle += open(os.path.join(DST, "assets", _b), encoding="utf-8",
                       errors="replace").read()
if bundle:
    if 'id:"dpsom"' not in bundle:
        erros.append("a entrada de Som nao entrou na lista de configuracoes")
    if 'case"dpsom"' not in bundle:
        erros.append("a pagina de Som nao entrou no switch de render")

# ------------------- 2c. nenhum link para pagina institucional inexistente
# O projeto nao tem Sobre / Termos / Privacidade / Uso aceitavel. Um link
# para elas e um 404 na cara do usuario, em pagina de login e formulario.
if bundle:
    mortos = re.findall(r'doispapo\.com/(sobre|termos|privacidade|'
                        r'uso-aceitavel)', bundle)
    if mortos:
        from collections import Counter
        d = ", ".join(f"/{k} x{v}" for k, v in Counter(mortos).items())
        erros.append(f"link para pagina inexistente no bundle: {d}")

# -------------------------- 2d. os sons por evento existem como arquivo
# A pagina identifica QUAL evento esta tocando pelo nome do arquivo. Se
# a conversao de data URI para arquivo falhar, a troca por evento para
# de funcionar sem erro visivel.
#
# A lista NAO e fixa: sai do proprio bundle. Uma lista escrita a mao ja
# ficou defasada uma vez - a regex que a alimentava usava \w, que nao
# casa "$", e quatro sons com cifrao no nome minificado passaram batido
# por varias versoes.
if bundle:
    _casos = re.findall(r'case"([a-zA-Z]+)":\{this\.node=new Audio\(([\w$]+)\)',
                        bundle)
    if not _casos:
        erros.append("nao encontrei o switch de reproducao de som no bundle")
    else:
        _faltam = [n for n, _ in _casos
                   if not os.path.exists(os.path.join(
                       DST, "assets", "sounds", "dp-%s.ogg" % n))]
        if _faltam:
            erros.append("som sem arquivo proprio: " + ", ".join(_faltam))
        _embutidos = [n for n, v in _casos
                      if re.search(re.escape(v) + r'="data:audio', bundle)]
        if _embutidos:
            erros.append("som ainda embutido como data URI (nao da para "
                         "personalizar): " + ", ".join(_embutidos))
        avisos.append("%d sons de notificacao reconhecidos" % len(_casos))

# ----------------------------------------- 3. sobras da marca do upstream
resto = 0
for raiz, _, arqs in os.walk(os.path.join(DST, "assets")):
    for a in arqs:
        if a.endswith(".js"):
            s = open(os.path.join(raiz, a), encoding="utf-8",
                     errors="replace").read()
            resto += len(re.findall(r"bsky\.app|translate\.stoat|"
                                    r"support\.stoat|stoat\.gg", s))
if resto:
    avisos.append(f"{resto} link(s) do upstream ainda no bundle")

# ------------------------------------------------------------- resultado
for a in avisos: print(f"  aviso: {a}")
if erros:
    print("\nBUILD REPROVADO:")
    for e in erros: print(f"  ERRO: {e}")
    sys.exit(1)
print(f"  build aprovado ({len(h)} caracteres no index.html, "
      f"{ab} blocos de script)")
