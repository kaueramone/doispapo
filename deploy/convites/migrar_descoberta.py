#!/usr/bin/env python3
"""
Fase 1 da descoberta de comunidades: colecoes, indices e seed.

Idempotente: pode rodar quantas vezes quiser sem estragar nada. NAO altera
nenhum documento do Revolt -- so cria colecoes nossas (dp_*) e os indices
delas. O seed usa $setOnInsert, entao rodar de novo nunca sobrescreve uma
decisao que um administrador ja tomou pela interface.

    docker compose cp deploy/convites/migrar_descoberta.py convites:/migrar.py
    docker compose exec -T convites python3 /migrar.py --conferir   # so olha
    docker compose exec -T convites python3 /migrar.py              # aplica

Desfazer (a fase inteira e reversivel):
    db.dp_categorias.drop(); db.dp_comunidade.drop(); db.dp_solicitacoes.drop()
"""
import os
import sys
import time

from pymongo import ASCENDING, DESCENDING, MongoClient

CONFERIR = "--conferir" in sys.argv

cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://database:27017"),
                  serverSelectionTimeoutMS=5000)
db = cli.revolt

# ------------------------------------------------------------------ categorias
#
# A lista vive AQUI e nao no frontend, e depois passa a ser editavel pelo
# painel. O `_id` e o slug: ele vai na URL do catalogo, entao mudar depois
# quebraria link. Escolhido sem acento e sem espaco por isso.
#
# `ordem` deixa buracos de 10 para caber categoria nova no meio sem renumerar
# tudo. "Geral" fica por ultimo de proposito: e o destino padrao de quem ainda
# nao escolheu, e nao deve abrir o catalogo.
CATEGORIAS = [
    ("games",           "Games",            "\U0001F3AE",  10),
    ("tecnologia",      "Tecnologia",       "\U0001F4BB",  20),
    ("musica",          "Musica",           "\U0001F3B5",  30),
    ("filmes-e-series", "Filmes e Series",  "\U0001F3AC",  40),
    ("esportes",        "Esportes",         "⚽",      50),
    ("motociclismo",    "Motociclismo",     "\U0001F3CD",  60),
    ("arte",            "Arte",             "\U0001F3A8",  70),
    ("educacao",        "Educacao",         "\U0001F4DA",  80),
    ("geral",           "Geral",            "\U0001F4AC", 999),
]
CATEGORIA_PADRAO = "geral"


def log(*a):
    print(*a, flush=True)


def categorias():
    log("\n== dp_categorias ==")
    for slug, nome, emoji, ordem in CATEGORIAS:
        ja = db.dp_categorias.find_one({"_id": slug})
        if ja:
            log(f"   ja existe: {slug}")
            continue
        if CONFERIR:
            log(f"   criaria:   {slug} ({nome})")
            continue
        db.dp_categorias.insert_one({
            "_id": slug,
            "nome": nome,
            "emoji": emoji,
            "ordem": ordem,
            "ativa": True,
            # Gancho de subcategoria. Sempre None na v1 -- existe desde o
            # primeiro dia para que subcategoria entre depois sem migracao.
            "pai": None,
        })
        log(f"   criada:    {slug} ({nome})")


def comunidades():
    """Uma linha por servidor existente, sempre PRIVADA.

    O item 21 do pedido e explicito: nenhuma comunidade existente pode virar
    publica sem ato do administrador. Por isso `publica: False` no seed, e
    $setOnInsert para que rodar de novo nao desfaca quem ja se marcou publica.
    """
    log("\n== dp_comunidade ==")
    agora = time.time()
    for s in db.servers.find({}, {"name": 1}):
        sid = s["_id"]
        # Prefixo de `compound_id` -- nao e varredura.
        n = db.server_members.count_documents({"_id.server": sid})
        ja = db.dp_comunidade.find_one({"_id": sid}, {"publica": 1, "categoria": 1})
        if ja:
            log(f"   ja existe: {s.get('name')} "
                f"(publica={ja.get('publica')}, categoria={ja.get('categoria')})")
            continue
        if CONFERIR:
            log(f"   criaria:   {s.get('name')} -> privada, {CATEGORIA_PADRAO}, {n} membros")
            continue
        db.dp_comunidade.update_one(
            {"_id": sid},
            {"$setOnInsert": {
                "publica": False,
                "categoria": CATEGORIA_PADRAO,
                "tags": [],
                "membros": n,
                "membros_em": agora,
                "em": agora,
                "por": None,
            }},
            upsert=True)
        log(f"   criada:    {s.get('name')} -> privada, {CATEGORIA_PADRAO}, {n} membros")


def indices():
    log("\n== indices ==")

    def cria(colecao, chaves, **kw):
        nome = kw.get("name")
        if CONFERIR:
            log(f"   criaria:   {colecao.name}.{nome}")
            return
        colecao.create_index(chaves, **kw)   # create_index e idempotente
        log(f"   ok:        {colecao.name}.{nome}")

    # --- dp_categorias: a listagem do catalogo, sempre ordenada
    cria(db.dp_categorias, [("ativa", ASCENDING), ("ordem", ASCENDING)],
         name="ativas_por_ordem")

    # --- dp_comunidade
    #
    # Os tres indices sao PARCIAIS sobre `publica: true`. Isso nao e so
    # economia de espaco: comunidade privada nem entra no indice, entao uma
    # consulta do catalogo nao consegue enxerga-la nem por engano. E a
    # garantia estrutural do requisito 4 -- a existencia de comunidade
    # privada nao vaza.
    SO_PUBLICAS = {"publica": True}

    cria(db.dp_comunidade,
         [("categoria", ASCENDING), ("membros", DESCENDING), ("_id", ASCENDING)],
         name="catalogo_por_categoria", partialFilterExpression=SO_PUBLICAS)

    cria(db.dp_comunidade,
         [("membros", DESCENDING), ("_id", ASCENDING)],
         name="catalogo_populares", partialFilterExpression=SO_PUBLICAS)

    cria(db.dp_comunidade, [("tags", ASCENDING)],
         name="catalogo_por_tag", partialFilterExpression=SO_PUBLICAS)

    # --- dp_solicitacoes
    #
    # O UNICO indice unico do banco inteiro, e a peca central da feature.
    # Parcial sobre PENDENTE porque a unicidade so vale para pedido aberto:
    # depois de rejeitado ou cancelado, a pessoa pode pedir de novo, e os
    # documentos antigos continuam no historico.
    #
    # Com ele, dez cliques no botao produzem UM pedido -- por garantia de
    # banco, nao por checagem no codigo. Mongo standalone nao tem transacao;
    # isto e o que ocupa o lugar dela.
    cria(db.dp_solicitacoes,
         [("servidor", ASCENDING), ("usuario", ASCENDING)],
         name="um_pendente_por_pessoa", unique=True,
         partialFilterExpression={"estado": "PENDENTE"})

    # Fila do administrador e o contador da engrenagem.
    cria(db.dp_solicitacoes,
         [("servidor", ASCENDING), ("estado", ASCENDING), ("em", DESCENDING)],
         name="fila_do_admin")

    # Estado do botao no catalogo, "meus pedidos", e o teto por usuario.
    # Sem este, o rate limit seria varredura de colecao a cada pedido -- que
    # e o defeito que o teto de feedback tem hoje.
    cria(db.dp_solicitacoes,
         [("usuario", ASCENDING), ("em", DESCENDING)],
         name="pedidos_da_pessoa")


def conferencia_final():
    log("\n== conferencia ==")
    for nome in ("dp_categorias", "dp_comunidade", "dp_solicitacoes"):
        col = db[nome]
        log(f"\n   {nome}: {col.count_documents({})} documentos")
        for i in col.list_indexes():
            extra = ""
            if i.get("unique"):
                extra += " UNIQUE"
            if "partialFilterExpression" in i:
                extra += f" parcial={dict(i['partialFilterExpression'])}"
            log(f"      - {i['name']}: {dict(i['key'])}{extra}")

    n_pub = db.dp_comunidade.count_documents({"publica": True})
    log(f"\n   comunidades publicas: {n_pub}"
        + ("  <- esperado no fim da fase 1" if n_pub == 0 else "  <- ATENCAO"))

    # O que NAO foi tocado.
    log(f"\n   servers intactos:     {db.servers.count_documents({})} "
        f"(com discoverable: {db.servers.count_documents({'discoverable': {'$exists': True}})})")


if __name__ == "__main__":
    log("modo:", "CONFERIR (nada sera escrito)" if CONFERIR else "APLICAR")
    categorias()
    comunidades()
    indices()
    if not CONFERIR:
        conferencia_final()
    log("\nfim.")
