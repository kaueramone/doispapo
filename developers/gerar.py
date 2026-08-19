#!/usr/bin/env python3
"""
Gera developers.doispapo.com a partir do OpenAPI da própria instância.

Usar a especificação servida pela API garante que a referência descreva a
versão que está no ar, em vez de repetir documentação de terceiros que
pode divergir.
"""
import html, json, os, re, sys

SPEC = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
SAIDA = sys.argv[2] if len(sys.argv) > 2 else "site-developers"
BASE = "https://chat.doispapo.com/api"

d = json.load(open(SPEC, encoding="utf-8"))
paths = d.get("paths", {})
schemas = d.get("components", {}).get("schemas", {})

def esc(t):
    return html.escape(str(t) if t is not None else "")

# ------------------------------------------------- agrupamento por área
AREAS = [
    ("bots", "Bots", "Criar, configurar e convidar bots."),
    ("channels", "Canais", "Mensagens, permissões e convites de canal."),
    ("servers", "Servidores", "Comunidades, membros, cargos e emojis."),
    ("users", "Usuários", "Perfis, amizades e mensagens diretas."),
    ("invites", "Convites", "Consultar e resgatar convites."),
    ("auth", "Autenticação", "Sessões e conta. Bots não usam estas rotas."),
    ("sync", "Sincronização", "Configurações e estado de leitura."),
    ("push", "Notificações", "Registro para push."),
    ("onboard", "Integração", "Primeiro acesso da conta."),
    ("safety", "Segurança", "Denúncias."),
    ("custom", "Emojis", "Emojis personalizados."),
    ("policy", "Políticas", "Mudanças de termos."),
]

def area_de(p):
    prim = p.strip("/").split("/")[0]
    for chave, _, _ in AREAS:
        if prim == chave:
            return chave
    return "outros"

grupos = {}
for p, item in paths.items():
    for metodo, op in item.items():
        if metodo not in ("get", "post", "put", "patch", "delete"):
            continue
        grupos.setdefault(area_de(p), []).append((p, metodo, op))
for g in grupos.values():
    g.sort(key=lambda x: (x[0], x[1]))

# ------------------------------------------------- tipos legíveis
def tipo(s, prof=0):
    if not isinstance(s, dict) or prof > 3:
        return "any"
    if "$ref" in s:
        return s["$ref"].split("/")[-1]
    if "anyOf" in s or "oneOf" in s:
        return " | ".join(tipo(x, prof+1) for x in (s.get("anyOf") or s["oneOf"]))
    t = s.get("type")
    if t == "array":
        return tipo(s.get("items", {}), prof+1) + "[]"
    if t == "object" or (t is None and "properties" in s):
        return "object"
    if isinstance(t, list):
        return " | ".join(t)
    return t or "any"

def corpo_exemplo(op):
    rb = op.get("requestBody", {}).get("content", {}).get("application/json", {})
    esq = rb.get("schema")
    if not esq:
        return None
    if "$ref" in esq:
        esq = schemas.get(esq["$ref"].split("/")[-1], {})
    props = esq.get("properties", {})
    if not props:
        return None
    obrig = set(esq.get("required", []))
    ex = {}
    for k, v in list(props.items())[:8]:
        t = tipo(v)
        ex[k] = {"string": "texto", "integer": 0, "number": 0,
                 "boolean": True}.get(t, "…" if t.endswith("[]") is False else [])
    return json.dumps(ex, ensure_ascii=False, indent=2), obrig, props

# ------------------------------------------------- montagem do HTML
def bloco_operacao(p, metodo, op):
    cor = {"get": "get", "post": "post", "patch": "patch",
           "put": "patch", "delete": "del"}[metodo]
    ident = re.sub(r"[^a-z0-9]+", "-", (metodo + p).lower()).strip("-")
    resumo = op.get("summary") or ""
    desc = op.get("description") or ""
    seg = op.get("security")

    partes = [f'<article class="op" id="{ident}">']
    partes.append(f'<div class="op-cab"><span class="m {cor}">{metodo.upper()}</span>'
                  f'<code class="rota">{esc(p)}</code></div>')
    if resumo:
        partes.append(f'<h4>{esc(resumo)}</h4>')
    if desc and desc != resumo:
        partes.append(f'<p class="desc">{esc(desc)}</p>')
    if seg:
        partes.append('<p class="auth">🔑 Requer autenticação</p>')

    params = op.get("parameters", [])
    if params:
        partes.append('<table class="tb"><thead><tr><th>Parâmetro</th>'
                      '<th>Onde</th><th>Tipo</th><th>Obrigatório</th></tr></thead><tbody>')
        for q in params:
            partes.append(
                f'<tr><td><code>{esc(q.get("name"))}</code></td>'
                f'<td>{esc(q.get("in"))}</td>'
                f'<td class="t">{esc(tipo(q.get("schema", {})))}</td>'
                f'<td>{"sim" if q.get("required") else "não"}</td></tr>')
        partes.append('</tbody></table>')

    ce = corpo_exemplo(op)
    if ce:
        exemplo, obrig, props = ce
        partes.append('<div class="rot">Corpo da requisição</div>')
        partes.append('<table class="tb"><thead><tr><th>Campo</th><th>Tipo</th>'
                      '<th>Obrigatório</th></tr></thead><tbody>')
        for k, v in list(props.items())[:14]:
            partes.append(f'<tr><td><code>{esc(k)}</code></td>'
                          f'<td class="t">{esc(tipo(v))}</td>'
                          f'<td>{"sim" if k in obrig else "não"}</td></tr>')
        partes.append('</tbody></table>')
        partes.append(f'<pre><code>{esc(exemplo)}</code></pre>')

    resp = [c for c in op.get("responses", {}) if c != "default"]
    if resp:
        partes.append('<div class="rot">Respostas</div><p class="cods">' +
                      " ".join(f'<span class="cod">{esc(c)}</span>' for c in resp) +
                      '</p>')

    partes.append('</article>')
    return "\n".join(partes)

secoes, indice = [], []
for chave, titulo, sub in AREAS:
    if chave not in grupos:
        continue
    ops = grupos[chave]
    indice.append(f'<li><a href="#a-{chave}">{esc(titulo)}'
                  f'<span class="qt">{len(ops)}</span></a></li>')
    secoes.append(f'<section class="area" id="a-{chave}">'
                  f'<h3>{esc(titulo)}</h3><p class="sub">{esc(sub)}</p>' +
                  "\n".join(bloco_operacao(*o) for o in ops) + '</section>')

TOTAL_OPS = sum(len(v) for v in grupos.values())

os.makedirs(SAIDA, exist_ok=True)
tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "template.html"), encoding="utf-8").read()
saida = (tpl.replace("__INDICE__", "\n".join(indice))
            .replace("__SECOES__", "\n".join(secoes))
            .replace("__NOPS__", str(TOTAL_OPS))
            .replace("__NROTAS__", str(len(paths)))
            .replace("__VERSAO__", esc(d.get("info", {}).get("version", ""))))
open(os.path.join(SAIDA, "index.html"), "w", encoding="utf-8").write(saida)
print(f"gerado: {SAIDA}/index.html  ({len(saida)//1024} KB, "
      f"{TOTAL_OPS} operacoes em {len(grupos)} areas)")
