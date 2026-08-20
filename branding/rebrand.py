#!/usr/bin/env python3
"""
Aplica a marca Dois Papo sobre o build do cliente web.

Entrada : dist original extraido do container
Saida   : dist-patched, pronto para bind-mount em /app/dist

Idempotente: rodar de novo sobre a saida nao causa dano.
"""
import collections, glob, json, os, re, shutil, sys

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


# --------------------------- 1d. sobras que a troca de URL nao alcanca
def remove_bsky(s_):
    """Remove o icone do Bluesky do rodape do login.

    Apontava para o perfil do upstream e nao temos conta equivalente.
    Casa parenteses em vez de cortar por posicao fixa: o bundle e
    minificado e os identificadores mudam a cada build. Se qualquer
    conferencia falhar, devolve o texto intacto - preferimos o icone
    errado a um bundle corrompido.
    """
    i = s_.find('href:"https://bsky.app')
    if i < 0:
        return s_, 0
    ini = s_.rfind(",c(", 0, i)
    if ini < 0 or i - ini > 40:
        return s_, 0
    j = s_.index("(", ini)
    prof, k = 0, j
    while k < len(s_):
        if s_[k] == "(":
            prof += 1
        elif s_[k] == ")":
            prof -= 1
            if prof == 0:
                break
        k += 1
    if prof != 0 or not (0 < k - ini < 600):
        return s_, 0
    if "bsky.app" not in s_[ini:k]:
        return s_, 0
    return s_[:ini] + s_[k + 1:], 1


SOBRAS = [
    # sem plataforma de traducao propria; a conversa acontece no repositorio
    ("https://translate.stoat.chat/projects/revolt/",
     "https://github.com/kaueramone/doispapo/discussions"),
    ("https://support.stoat.chat/kb/safety/blocked-for-spam",
     "https://doispapo.com/uso-aceitavel"),
    ("https://support.stoat.chat/kb/troubleshooting/connection-issues",
     "https://github.com/kaueramone/doispapo/discussions"),
    ("https://stoat.gg/meet-gifbox", "https://github.com/kaueramone/doispapo/discussions"),
    # Emoji: cada um era um <img> buscado no CDN do upstream, a cada
    # emoji renderizado. Isso deixava a plataforma dependente da
    # infraestrutura deles - se aquele dominio sair do ar, os emoji
    # somem de todas as conversas - e fazia o navegador de cada usuario
    # conversar com um host que nao e nosso. Agora aponta para o
    # espelho proprio, que guarda em disco na primeira busca.
    ("https://static.stoat.chat/emoji/", "/emoji/"),
    # a troca cega de marca gerou um rotulo nosso apontando para o webmail
    # do upstream; o ramo so vale para enderecos @stoat.chat, mas o nome
    # errado nao pode ficar
    ('"Stoat Mail","https://webmail.revolt.wtf"',
     '"Webmail","https://webmail.revolt.wtf"'),
    ('"Dois Papo Mail","https://webmail.revolt.wtf"',
     '"Webmail","https://webmail.revolt.wtf"'),
]
for f in glob.glob(os.path.join(DST, "assets", "*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    for de, para in SOBRAS:
        if de in s_:
            conta("sobras", s_.count(de))
            s_ = s_.replace(de, para)
    s_, n_b = remove_bsky(s_)
    conta("bluesky-removido", n_b)
    if s_ != o_:
        open(f, "w", encoding="utf-8").write(s_)


# ------------------------------------ 1i. atribuicao do provedor de GIF
# Os termos do Giphy exigem atribuicao visivel onde os GIFs aparecem.
# Nao e cortesia: e condicao de uso da API.
#
# O seletor ja tem um rodape - herdado do provedor do upstream, que
# convidava a enviar GIFs para o gifbox.me. Reaproveitamos esse espaco
# em vez de inventar um elemento novo: menos remendo, e o texto cai
# exatamente onde o usuario ja olha.
# Ancorado no msgId, nunca no nome minificado do <Trans> nem no da
# constante da URL - ver a nota da secao 1e.
_ID = r'[A-Za-z_$][\w$]*'
GIF_TEXTOS = [
    (re.compile(_ID + r'\(' + _ID + r',\{id:"H6eQWV"\}\)'), '"Powered by GIPHY"'),
    (re.compile(_ID + r'\(' + _ID + r',\{id:"9gXZi5"\}\)'), '"Abrir o GIPHY"'),
    (re.compile(_ID + r'\(' + _ID + r',\{id:"jSklQb"\}\)'), '"Nenhum GIF encontrado"'),
    (re.compile(_ID + r'\(' + _ID + r',\{id:"CVvh2T"\}\)'), '"Tente outra busca."'),
    (re.compile(r'(' + _ID + r')="https://gifbox\.me/upload"'),
     r'\1="https://giphy.com"'),
]
for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    for padrao, para in GIF_TEXTOS:
        s_, n_gif = padrao.subn(para, s_)
        if n_gif:
            conta("gif-atribuicao", n_gif)
    if s_ != o_:
        open(f, "w", encoding="utf-8").write(s_)


# ---- 1h. marcador de quem esta falando: agora vive no fonte ----
# Era regex sobre o bundle, casando `{speaking:!p()&&v(),video:` e
# `+(p()?" vc_tile group":" vc_tile")`. `p` e `v` eram nomes sorteados
# pelo minificador: mudaram no build seguinte e os dois remendos sumiram
# em silencio -- a luz de fala e o `data-dp-uid` junto.
#
# Agora ParticipantTile.tsx escreve `dp-fala` e `data-dp-uid` diretamente
# (cliente/patches/0021). Nada a fazer aqui.

# ---------------------- 1g. compartilhamento de tela sob demanda
# Numa chamada com duas pessoas transmitindo, quem so quer conversar
# recebia as duas telas ao vivo. Um blur no CSS nao resolveria: o video
# continuaria sendo baixado e decodificado. A economia vem de nao
# assinar a faixa.
#
# O app JA gerencia assinatura por visibilidade (IntersectionObserver a
# 80%, com 3s de carencia). Nao ha sistema novo aqui - so uma segunda
# condicao nos tres pontos em que ele assina. A decisao mora em
# tela.js, atras de window.dpTelaBloqueia; se aquele script nao tiver
# sido avaliado, todas as expressoes viram falso e o comportamento
# volta a ser exatamente o de antes.
TELA = [
    # 1) sala do LiveKit: entrega a instancia para o script
    (re.compile(r'(this\.remoteParticipants=new Map,this\.sidToIdentity='
                r'new Map,this\.options=Object\.assign\(Object\.assign\('
                r'\{\},[\w$]+\),e\))'),
     r'\1,(window.dpSalaNova&&window.dpSalaNova(this))',
     "tela-sala"),

    # 2) video: so assina se o usuario tiver pedido para assistir
    (re.compile(r'je\(\(\)=>\{i&&o\.publication instanceof ([\w$]+)&&'
                r'u\(\)&&o\.publication\.setSubscribed\(!0\)\}\)'),
     r'je(()=>{i&&o.publication instanceof \1&&u()&&!(window.dpTelaBloqueia'
     r'&&window.dpTelaBloqueia(o.publication))&&'
     r'o.publication.setSubscribed(!0)})',
     "tela-assina"),

    # 3) video: desassina tambem quando bloqueado, nao so quando some
    #    da tela - no caso relatado os dois quadros estao VISIVEIS
    (re.compile(r'je\(\(\)=>\{i&&o\.publication instanceof ([\w$]+)&&'
                r'd\(\)===!1&&u\(\)===!1&&'
                r'o\.publication\.setSubscribed\(!1\)\}\)'),
     r'je(()=>{i&&o.publication instanceof \1&&((d()===!1&&u()===!1)||'
     r'(window.dpTelaBloqueia&&window.dpTelaBloqueia(o.publication)))&&'
     r'o.publication.setSubscribed(!1)})',
     "tela-desassina"),

    # 4) audio: o componente de audio assinava tudo a forca, inclusive
    #    o som da tela compartilhada
    (re.compile(r'for\(const s of i\)s\.publication\.setSubscribed\(!0\),'
                r'console\.info\(s\.publication\)'),
     r'for(const s of i)(window.dpTelaBloqueia&&'
     r'window.dpTelaBloqueia(s.publication))||'
     r'(s.publication.setSubscribed(!0),console.info(s.publication))',
     "tela-audio"),
]
for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    for padrao, troca, rotulo in TELA:
        s_, n = padrao.subn(troca, s_)
        if n:
            conta(rotulo, n)
    if s_ != o_:
        open(f, "w", encoding="utf-8").write(s_)


# ------------------------------ 1f. links institucionais que nao existem
# O projeto nao tem paginas Sobre / Termos / Privacidade / Uso aceitavel.
# Elas nunca foram escritas, e apontar para 404 e pior do que nao ter o
# link. Aqui os links somem sem deixar buraco visual.
#
# Sao dois casos diferentes:
#
#   - No rodape do login os tres links formam um grupo proprio, com o
#     separador antes. Remove-se o grupo inteiro e sobra o icone do
#     repositorio, que continua fazendo sentido sozinho.
#   - Nos formularios o link de uso aceitavel esta NO MEIO de uma frase.
#     Remover o elemento comeria as palavras junto, entao o gabarito vira
#     um <span>: o texto continua igual, sem virar link.

def remove_rodape(s_):
    """Tira o grupo de links institucionais do rodape do login."""
    # Sem nome minificado: `c` era o ajudante de componente daquele build
    # e virou outra letra no seguinte, levando o remendo junto.
    _i = r'[A-Za-z_$][\w$]*'
    padrao = re.compile(
        r',' + _i + r'\(' + _i + r',\{\}\),' + _i + r'\(' + _i +
        r',\{get children\(\)\{return\['
        r'(.{0,400}?)\]\}\}\)')
    ids = ('uyJsf6', 'xowcRf', 'LcET2C')   # Sobre, Termos, Privacidade

    def troca(m):
        # so remove se o grupo for exatamente o dos tres institucionais;
        # qualquer outra coisa fica intacta
        return "" if all(i in m.group(1) for i in ids) else m.group(0)

    return padrao.subn(troca, s_)


# Os gabaritos <a> das quatro rotas viram <span>. Isso resolve os dois
# casos de uma vez: o link no meio da frase perde so o link, e os
# gabaritos do rodape - que ficam definidos mas sem referencia depois da
# remocao do grupo - param de carregar a URL morta no arquivo.
GABARITO = re.compile(
    r'([A-Za-z_$][\w$]*)\("<a href=https://doispapo\.com/'
    r'(?:sobre|termos|privacidade|uso-aceitavel)[^"]*"\)')

for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    s_, n_r = remove_rodape(s_)
    conta("rodape-institucional", n_r)
    # O nome do ajudante vem do proprio trecho: escreve-lo a mao geraria
    # chamada para uma funcao que nao existe mais neste build.
    s_, n_g = GABARITO.subn(r'\1("<span>")', s_)
    conta("link-institucional", n_g)
    if s_ != o_:
        open(f, "w", encoding="utf-8").write(s_)


# ------------- 1e. "Som de notificacao" como pagina nativa das configuracoes
# O app mantem um registro das paginas de configuracao do servidor: um
# switch em render() e uma lista de entradas em list(). Acrescentar nos
# dois lugares deixa a funcao no mesmo lugar que o usuario ja procura -
# grupo Personalizacao, ao lado de Emojis - em vez de um botao flutuante.
# Os identificadores minificados sao casados por padrao, nao literalmente,
# para o remendo sobreviver a um rebuild do upstream.
# NENHUM nome minificado no padrao. `c` e `b` eram os nomes que o
# empacotador tinha sorteado para o helper de componente e para o <Trans>
# naquele build; bastou o bundle mudar de conteudo para virarem outros
# (`y`, no caso) e os dois remendos sumirem em silencio. O que nao muda
# sao os literais: o id da pagina, o msgId da traducao, o formato da
# chamada. E so isso que ancora aqui.
IDENT = r'[A-Za-z_$][\w$]*'
PG_LISTA = re.compile(
    r'(entries:\[\{id:"emojis",icon:' + IDENT + r'\(' + IDENT + r',\{size:20\}\),'
    r'title:' + IDENT + r'\(' + IDENT + r',\{id:"etgedT"\}\)\})\]')
PG_RENDER = re.compile(
    r'(case"emojis":return ' + IDENT + r'\(' + IDENT + r',\{server:e\}\);)')

for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_
    # As chamadas sao protegidas: se o script da pagina nao tiver sido
    # avaliado, a lista de configuracoes continua funcionando sem a
    # entrada, em vez de quebrar inteira.
    # Substituicao por funcao: o texto tem acento, e re trataria "\\u"
    # numa string de template como escape invalido.
    s_, n1 = PG_LISTA.subn(
        lambda m: m.group(1) + ',{id:"dpsom",'
        'icon:(window.dpSomIcone?window.dpSomIcone():null),'
        'title:"Som de notifica\u00e7\u00e3o"}]', s_)
    s_, n2 = PG_RENDER.subn(
        lambda m: m.group(1) + 'case"dpsom":return window.dpSomPagina?'
        'window.dpSomPagina(e):null;', s_)
    if n1 or n2:
        conta("pagina-som", n1 + n2)
    if s_ != o_:
        open(f, "w", encoding="utf-8").write(s_)

# ------------------------- 1d. completar a traducao pt-BR
# O catalogo pt-BR do upstream vem com ~31% das entradas iguais ao ingles
# (nao traduzidas). Aplicamos as traducoes proprias por msgId.
trad_p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "traducoes_pt_br.json")
def _fim_da_lista(txt, inicio):
    """Indice do ']' que fecha a lista aberta em `inicio`.

    Procurar o primeiro ']' bastava enquanto so mexiamos em entradas de
    string simples. Mensagem com variavel e uma lista de pedacos --
    ["Voce tem ",["0"]," itens"] -- e o primeiro ']' fecha a variavel, no
    meio da entrada.
    """
    prof = 0
    i = inicio
    n = len(txt)
    while i < n:
        c = txt[i]
        if c == '"':
            i += 1
            while i < n and txt[i] != '"':
                if txt[i] == "\\":
                    i += 1
                i += 1
        elif c == "[":
            prof += 1
        elif c == "]":
            prof -= 1
            if prof == 0:
                return i
        i += 1
    return -1


def _variaveis(txt):
    """Nomes das variaveis de uma entrada compilada, em ordem."""
    return re.findall(r'\[\s*"([^"]+)"\s*\]', txt)


def _catalogo_pt_br():
    """Descobre o chunk do catalogo pt-BR pelo mapa de import do bundle.

    A versao anterior pegava o primeiro messages-*.js que contivesse
    "[Ontem as]" e parava ali. So que pt-PT tambem diz "Ontem as". Eram
    DOIS candidatos, e qual vinha primeiro dependia da ordem em que o
    sistema de arquivos devolvia o glob - sorteio a cada build.

    Perder esse sorteio nao quebraria nada de forma visivel: as traducoes
    entrariam no catalogo de Portugal, o contador diria 249, o
    verificar.py aprovaria, e a interface em pt-BR ficaria exatamente
    como estava. Um defeito com aparencia de sucesso.

    O bundle carrega a resposta certa: o mapa de import do lingui liga o
    locale ao seu chunk. Ler dali e determinista - e quando nao da para
    resolver, parar e melhor do que traduzir o idioma errado.
    """
    padrao = re.compile(r'pt-BR/messages\.ts"\s*:\s*\(\)\s*=>\s*'
                        r'[^(]*\(\s*\(\)\s*=>\s*import\("\./(messages-[^"]+\.js)"')
    for idx in glob.glob(os.path.join(DST, "assets", "index-*.js")):
        m = padrao.search(open(idx, encoding="utf-8", errors="replace").read())
        if m:
            caminho = os.path.join(DST, "assets", m.group(1))
            if os.path.exists(caminho):
                return caminho
    return None


if os.path.exists(trad_p):
    trad = json.load(open(trad_p, encoding="utf-8"))
    alvo_pt = _catalogo_pt_br()
    if not alvo_pt:
        raise SystemExit(
            "erro: nao deu para identificar o catalogo pt-BR pelo mapa de\n"
            "      import do bundle. Traduzir o catalogo errado passaria\n"
            "      por sucesso, entao a geracao para aqui.")
    for f in [alvo_pt]:
        s_ = open(f, encoding="utf-8", errors="replace").read()
        n_ = 0
        for chave, texto in trad.items():
            alvo = '"%s":' % chave
            i = s_.find(alvo)
            if i < 0:
                continue
            ab = i + len(alvo)
            if ab >= len(s_) or s_[ab] != "[":
                continue
            fim = _fim_da_lista(s_, ab)
            if fim < 0:
                continue
            atual = s_[ab + 1:fim]

            if isinstance(texto, list):
                # Entrada com variavel. As variaveis TEM que ser as mesmas:
                # traduzir ["Voce tem ",["0"]," itens"] para uma frase sem
                # o ["0"] apagaria o numero da tela, e o contador diria que
                # deu tudo certo.
                if _variaveis(atual) != _variaveis(json.dumps(
                        texto, ensure_ascii=False)):
                    print("  aviso: %s ignorada — variaveis nao batem" % chave)
                    continue
                novo_val = json.dumps(texto, ensure_ascii=False,
                                      separators=(",", ":"))[1:-1]
            else:
                # so substitui entradas de string simples
                if not (atual.startswith('"') and atual.endswith('"')
                        and not _variaveis(atual)):
                    continue
                novo_val = json.dumps(texto, ensure_ascii=False)

            # dentro de template literal: escapar crase e cifrao
            novo_val = novo_val.replace("\\", "\\\\").replace("`", "\\`")
            s_ = s_[:ab + 1] + novo_val + s_[fim:]
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

# Mesma resolucao deterministica da secao 1d: escolher pelo texto "[Ontem"
# pegava tanto pt-BR quanto pt-PT, e qual vinha primeiro dependia da ordem
# do sistema de arquivos. Traduzir o fallback para portugues de Portugal
# passaria despercebido -- o contador diria o mesmo numero.
fonte = {}
_cat_pt = _catalogo_pt_br()
if _cat_pt:
    fonte = {m.group(1): m.group(2) for m in
             pad_simples.finditer(open(_cat_pt, encoding="utf-8",
                                       errors="replace").read())}

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

# --------------------- 2a. sons embutidos como data URI no bundle
# Descoberta importante: o app NÃO toca os arquivos de assets/sounds/.
# O empacotador embutiu os marcadores silenciosos — pequenos — como
# data:audio/ogg;base64 dentro do próprio bundle, e deixou só o som de
# mensagem, maior, como arquivo separado. Por isso apenas ele funcionava,
# e por isso trocar a pasta sounds/ não surtia efeito algum.
#
# Os 13 data URIs são idênticos entre si, então a troca precisa ser por
# nome de variável, obtido do switch do playSound.
import base64 as _b64

_MAPA_SONS = {
    "deafen": "deafen.ogg",
    "undeafen": "undeafen.ogg",
    "mute": "mute.ogg",
    "unmute": "unmute.ogg",
    "ringtoneIncoming": "ringtone_incoming.ogg",
    "ringtoneOutgoing": "ringtone_outgoing.ogg",
    "streamStart": "stream_start.ogg",
    "streamEnd": "stream_end.ogg",
    "streamViewerJoin": "stream_viewer_join.ogg",
    "streamViewerLeave": "stream_viewer_leave.ogg",
    "userJoinVoice": "user_join_voice.ogg",
    "userLeaveVoice": "user_leave_voice.ogg",
    "userMoved": "user_moved.ogg",
}

def _uri(nome):
    cam = os.path.join(ASSETS, "sons", nome)
    if not os.path.exists(cam):
        return None
    return "data:audio/ogg;base64," + _b64.b64encode(open(cam, "rb").read()).decode()

for f in glob.glob(os.path.join(DST, "assets", "index-*.js")):
    s_ = open(f, encoding="utf-8", errors="replace").read()
    o_ = s_

    # ATENCAO ao \w: ele NAO casa "$", e o minificador usa cifrao nos
    # nomes. Com (\w+) quatro sons ficavam de fora - unmute,
    # userJoinVoice, userLeaveVoice e userMoved, cujas variaveis sao
    # e$e, t$e, n$e e r$e. Eles seguiam embutidos como data URI, sem
    # como serem identificados nem trocados, e o diagnostico errado foi
    # concluir que "nao tocam".
    pares = re.findall(r'case"([a-zA-Z]+)":\{this\.node=new Audio\(([\w$]+)\)',
                       s_)
    for nome, var in pares:
        arq = _MAPA_SONS.get(nome)
        if not arq:
            continue                      # "message" já é arquivo real
        origem = os.path.join(ASSETS, "sons", arq)
        if not os.path.exists(origem):
            continue
        # Vira ARQUIVO, nao data URI. Tres ganhos: o bundle perde ~9
        # audios em base64; o som passa a ser cacheavel como qualquer
        # asset; e - o que viabiliza o som por evento - da para saber
        # QUAL som esta tocando lendo o nome do arquivo. Com data URI
        # todas as chamadas eram indistinguiveis entre si.
        # O "message" ja vinha assim no upstream.
        rel = "assets/sounds/dp-%s.ogg" % nome
        destino = os.path.join(DST, rel)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        shutil.copyfile(origem, destino)
        url = "/" + rel
        # (?<![\w$]) e nao \b: o minificador batiza variaveis com $, e
        # \b nao casa antes de $ -- nao e caractere de palavra. Com \b,
        # todo som cuja variavel comecasse com $ escapava da troca e
        # continuava como data URI, sem virar arquivo. Foi o que aconteceu
        # com "unmute" quando ele virou $$e.
        pad = re.compile(r'(?<![\w$])' + re.escape(var) +
                         r'="data:audio/ogg;base64,[A-Za-z0-9+/=]+"')
        s2, n = pad.subn(lambda m, v=var, u=url: '%s="%s"' % (v, u),
                         s_, count=1)
        if n:
            s_ = s2
            conta("sons-arquivo", 1)

    # Sobram cópias do mesmo silêncio em variáveis que o switch não nomeia.
    # Sem como saber a qual evento pertencem, recebem um aviso neutro —
    # melhor um som discreto do que silêncio inexplicável.
    generico = _uri("user_moved.ogg")
    if generico:
        restantes = re.findall(r'"data:audio/ogg;base64,[A-Za-z0-9+/=]{2000,}"', s_)
        if restantes:
            alvo = collections.Counter(restantes).most_common(1)[0][0]
            n = s_.count(alvo)
            s_ = s_.replace(alvo, '"%s"' % generico)
            conta("sons-genericos", n)

    if s_ != o_:
        open(f, "w", encoding="utf-8").write(s_)

# O padrao de "message" ja vem como arquivo, mas com hash no nome. Uma
# copia com nome previsivel deixa a pagina tocar o som padrao de
# QUALQUER evento pelo mesmo caminho, sem precisar descobrir o hash.
_msg = glob.glob(os.path.join(DST, "assets", "message_sound-*.ogg"))
if _msg:
    _dest = os.path.join(DST, "assets", "sounds", "dp-message.ogg")
    os.makedirs(os.path.dirname(_dest), exist_ok=True)
    shutil.copyfile(_msg[0], _dest)
    conta("sons-arquivo", 1)

# ------------------------------- 2b. sons de notificação
# O upstream distribui marcadores silenciosos: 13 dos 14 arquivos têm o
# mesmo MD5 e 1,000s de duração. Só o som de mensagem é real — por isso
# apenas ele tocava. Substituímos pelos tons sintetizados, afinados entre
# si e sem questão de licença.
_sons = os.path.join(ASSETS, "sons")
_destino_sons = os.path.join(DST, "assets", "sounds")
if os.path.isdir(_sons) and os.path.isdir(_destino_sons):
    for _f in sorted(os.listdir(_sons)):
        if not _f.endswith(".ogg"):
            continue
        shutil.copy2(os.path.join(_sons, _f),
                     os.path.join(_destino_sons, _f))
        conta("sons", 1)

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
<style id="dp-css-marca">
  /* Nenhum seletor pode tornar visivel o codigo-fonte de um script. */
  script,style{display:none!important}
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
<script id="dp-js-marca">
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

  // O link entregue ao convidado traz o código na consulta:
  // /login/create?invite=CODIGO. Sem ler daqui, o campo ficava vazio e a
  // pessoa tinha de copiar o código do endereço que acabou de abrir —
  // justamente o atrito que o link pronto deveria eliminar.
  var codigoDireto=null;
  try{
    codigoDireto=new URLSearchParams(location.search).get("invite");
    if(codigoDireto&&!/^[A-Za-z0-9_-]{1,64}$/.test(codigoDireto))
      codigoDireto=null;
    if(codigoDireto)sessionStorage.setItem("dp_convite_conta",codigoDireto);
    else codigoDireto=sessionStorage.getItem("dp_convite_conta");
  }catch(e){}

  var resgatando=false;
  function preencheConvite(){
    var srv=null;
    try{ srv=sessionStorage.getItem("dp_convite_srv"); }catch(e){}
    if((!srv&&!codigoDireto)||resgatando)return;
    // campo de codigo de convite na tela de cadastro
    var alvo=null, ins=document.querySelectorAll("input");
    for(var i=0;i<ins.length;i++){
      var el=ins[i], ctx=((el.placeholder||"")+" "+(el.name||"")+" "+
        (el.getAttribute("aria-label")||"")).toLowerCase();
      if(/convite|invite/.test(ctx)){ alvo=el; break; }
    }
    if(!alvo||alvo.value)return;
    // código de conta já veio pronto no link: preenche sem consultar
    if(codigoDireto){
      alvo.value=codigoDireto;
      alvo.dispatchEvent(new Event("input",{bubbles:true}));
      alvo.dispatchEvent(new Event("change",{bubbles:true}));
      return;
    }

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

  /* A verificação de integridade vive em guarda.js, o primeiro bloco
     injetado — aqui ela seria vítima da quebra que deveria consertar. */

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
# Os ids das TAGS vivem num espaco reservado "dp-js-"/"dp-css-".
# Um id de tag igual a um id de elemento da interface faz o seletor
# "#id" casar tambem com a tag: o <script> herda position/display do
# painel e o proprio codigo-fonte vira uma sobreposicao em tela cheia.
# Foi o que aconteceu com "dp-som", que era ao mesmo tempo a tag do
# script e o modal de som por servidor.
for _arq, _id in (("guarda.js", "dp-js-guarda"),
                  ("audio.js", "dp-js-audio"),
                  ("audio-ui.js", "dp-js-audio-ui"),
                  ("voz.js", "dp-js-voz"),
                  ("discord.js", "dp-js-discord"),
                  ("som-servidor.js", "dp-js-som"),
                  ("tela.js", "dp-js-tela")):
    _cam = os.path.join(_base, _arq)
    if not os.path.exists(_cam) or _id in h:
        continue
    _js = open(_cam, encoding="utf-8").read()
    _scripts += f'<script id="{_id}">\n{_js}\n</script>\n'
    conta("audio", 1)
INJECAO = _scripts + INJECAO

if "dp-css-marca" not in h:
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

# id de build: muda o nome dos caches, fazendo o workbox descartar os antigos
# O id precisa refletir o CONTEUDO, nao os nomes: os nomes dos arquivos
# nao mudam entre rebuilds, entao hashear a listagem manteria o mesmo nome
# de cache para sempre e o navegador nunca buscaria a versao nova.
_h = hashlib.md5()
# Inclui também os sons e os ícones: trocar o conteúdo de um asset sem
# alterar o identificador deixaria os navegadores com a versão antiga em
# cache, sem qualquer sinal de que há coisa nova.
for _f in sorted(glob.glob(os.path.join(DST, "assets", "index-*.js")) +
                 glob.glob(os.path.join(DST, "assets", "messages-*.js")) +
                 glob.glob(os.path.join(DST, "assets", "sounds", "*.ogg")) +
                 glob.glob(os.path.join(DST, "assets", "web", "*")) +
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

# As revisoes do precache SO podem ser calculadas depois do carimbo acima.
# O index.html muda quando o build id entra nele; calcular antes gravava no
# service worker o md5 de um arquivo que nunca chega a ser servido, e o
# navegador ficava com uma copia cuja identidade nao correspondia a nada.
def corrige(m):
    url = m.group(2)
    alvo = os.path.join(DST, url)
    if os.path.exists(alvo):
        return '{"revision":"%s","url":"%s"}' % (md5(alvo), url)
    return m.group(0)

sw, n_rev = re.subn(r'\{"revision":"([^"]*)","url":"([^"]*)"\}', corrige, sw)
conta("precache-revisoes", n_rev)


# Na ativacao, o SW apaga qualquer cache que nao seja deste build.
# Na ativacao: apaga todo cache que nao seja deste build e, se apagou
# algum, forca a recarga das abas abertas. Sem essa recarga uma aba que
# ficou com HTML corrompido continua exibindo o conteudo velho mesmo
# depois do cache ter sido descartado - o documento ja renderizado
# permanece no ar ate o usuario fechar todas as abas.
_guarda = ("self.addEventListener('activate',function(e){e.waitUntil("
           "caches.keys().then(function(ks){"
           "var velhos=ks.filter(function(k){return k.indexOf('%s')===-1});"
           "return Promise.all(velhos.map(function(k){return caches.delete(k)}))"
           ".then(function(){return self.clients.claim()})"
           ".then(function(){"
           "if(!velhos.length)return;"
           "return self.clients.matchAll({type:'window'}).then(function(cs){"
           "cs.forEach(function(c){try{Promise.resolve(c.navigate(c.url))"
           ".catch(function(){})}catch(_){}})})})"
           "}).catch(function(){}))});\n" % build_id)
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
