#!/usr/bin/env python3
"""Procura variável usada num ramo que só é atribuída em outro.

Os handlers HTTP são escritos como uma sequência de ramos independentes:

    def do_POST(self):
        if self.path == "/livekit":
            c = self.corpo_json()
            ...
        if self.path.startswith("/sons/"):
            ...  c.get("som")        # <-- `c` não existe aqui

Esse trecho é sintaticamente válido, passa em qualquer linter que só
olhe escopo (o nome ESTÁ atribuído na função, algumas linhas acima) e
explode apenas quando aquele ramo específico é exercido. Foi assim que
o envio de som quebrou com 502 — o ramo nunca tinha rodado antes.

A conferência aqui é de fluxo: para cada ramo, um nome lido precisa ter
sido atribuído antes da cadeia de ramos ou dentro do próprio ramo.

Uso: verificar_servicos.py arquivo.py [arquivo.py ...]
"""
import ast, sys, builtins

def nomes_atribuidos(no):
    saida = set()
    for n in ast.walk(no):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            saida.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            saida.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                saida.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            saida.add(n.name)
    return saida


def nomes_modulo(arv):
    """Só o que existe no escopo do módulo.

    Percorrer a árvore inteira traria as variáveis locais de todas as
    funções junto, e aí qualquer nome pareceria definido — o verificador
    aprovaria tudo, inclusive o bug que ele existe para pegar.
    """
    saida = set()
    for stmt in arv.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            saida.add(stmt.name)
        else:
            saida |= nomes_atribuidos(stmt)
    return saida


def checar(caminho):
    src = open(caminho, encoding="utf-8").read()
    arv = ast.parse(src)
    globais = nomes_modulo(arv) | set(dir(builtins))
    achados = []

    for fn in ast.walk(arv):
        if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("do_")):
            continue
        params = {a.arg for a in fn.args.args}
        antes = set(params)

        for stmt in fn.body:
            ehramo = isinstance(stmt, ast.If) and any(
                isinstance(n, ast.Attribute) and n.attr == "path"
                for n in ast.walk(stmt.test))
            if ehramo:
                dentro = nomes_atribuidos(stmt)
                for n in ast.walk(stmt):
                    if (isinstance(n, ast.Name)
                            and isinstance(n.ctx, ast.Load)
                            and n.id not in dentro
                            and n.id not in antes
                            and n.id not in globais):
                        achados.append((fn.name, n.lineno, n.id))
            # O que um ramo atribui NAO vale para os seguintes: aquele
            # ramo so roda para a rota dele. Contar essas atribuicoes
            # como disponiveis foi exatamente o engano que produziu o
            # bug - o `c` do ramo do webhook parecia valer para todos.
            # De um `if/else` aproveitamos so o que os dois lados
            # atribuem; de laco nada, porque pode nao executar.
            if isinstance(stmt, ast.If):
                se = set().union(*[nomes_atribuidos(x) for x in stmt.body]) \
                     if stmt.body else set()
                senao = set().union(*[nomes_atribuidos(x) for x in stmt.orelse]) \
                        if stmt.orelse else set()
                antes |= (se & senao)
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                pass
            else:
                antes |= nomes_atribuidos(stmt)
    return achados


falhou = False
for caminho in sys.argv[1:]:
    achados = checar(caminho)
    if achados:
        falhou = True
        print(f"\n{caminho}:")
        for fn, linha, nome in sorted(set(achados)):
            print(f"  linha {linha}: '{nome}' usado em {fn} sem estar "
                  "atribuído neste ramo")
    else:
        print(f"{caminho}: ok")

sys.exit(1 if falhou else 0)
