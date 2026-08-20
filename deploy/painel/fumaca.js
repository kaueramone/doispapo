/* ---------------------------------------------------------------------
   Portão de fumaça do painel.

   Existe por um defeito concreto: o bloco de Comentários e Novidades foi
   inserido ancorado em `api("/api/sessao")`, que eu supus única — mas a
   primeira ocorrência estava DENTRO de `abrirApp()`. As funções de
   carregamento ficaram no escopo daquela função, o `aba()` deixou de
   enxergá-las, e como o mapa de abas referencia todas de uma vez, TODA
   troca de aba passou a estourar. Fila, Usuários e Convites pararam de
   carregar por causa de um recurso que não tem relação com eles.

   A sintaxe seguiu válida, então `node --check` passou. Só um navegador
   de verdade, trocando de aba, mostra esse tipo de coisa.

   Uso:
     node fumaca.js <url> <token-de-sessao>

   O token vem de uma sessão descartável criada para o teste — nunca a
   sessão de quem administra. Quem chama é responsável por apagá-la
   depois.
--------------------------------------------------------------------- */
const { chromium } = require("playwright");

const URL_ALVO = process.argv[2];
const TOKEN = process.argv[3];
const ABAS = ["visao", "acessos", "fila", "usuarios", "convites",
              "feedback", "novidades", "consumo", "conta"];

/* O desafio da Cloudflare não sobe num navegador sem sessão real, e isso
   não diz nada sobre o painel. Filtrado por padrão conhecido. */
const RUIDO = [/challenges\.cloudflare\.com/i, /font-size:0/, /turnstile/i];

(async () => {
  if (!URL_ALVO || !TOKEN) {
    console.error("uso: node fumaca.js <url> <token-de-sessao>");
    process.exit(2);
  }

  const navegador = await chromium.launch({ args: ["--no-sandbox"] });
  const contexto = await navegador.newContext();
  await contexto.addCookies([{
    name: "dp_painel", value: TOKEN,
    domain: new URL(URL_ALVO).hostname,
    path: "/", httpOnly: true, secure: true, sameSite: "Lax",
  }]);

  const pagina = await contexto.newPage();
  const erros = [];
  pagina.on("pageerror", (e) => erros.push(String(e.stack || e.message)));
  pagina.on("console", (m) => {
    if (m.type() === "error") erros.push(m.text());
  });

  await pagina.goto(URL_ALVO, { waitUntil: "networkidle", timeout: 30000 });

  const entrou = await pagina.evaluate(
    () => getComputedStyle(document.querySelector("#app")).display !== "none",
  );

  const vazias = [];
  for (const nome of ABAS) {
    await pagina.click(`.abas button[data-p="${nome}"]`).catch(() => {});
    await pagina.waitForTimeout(1200);
    // Conteúdo é o que existe ALÉM do título e do subtítulo da seção: uma
    // aba que só mostra o próprio cabeçalho não carregou nada.
    const corpo = await pagina.evaluate((n) => {
      const sec = document.querySelector("#pg-" + n);
      if (!sec) return null;
      const alvos = sec.querySelectorAll("table, .cards > *, .bloco, .vazio, #met > *");
      return alvos.length;
    }, nome);
    if (!corpo) vazias.push(nome);
  }

  const graves = erros.filter((t) => !RUIDO.some((p) => p.test(t)));
  await navegador.close();

  console.log(`  entrou: ${entrou ? "sim" : "NAO"}`);
  console.log(`  abas sem conteudo: ${vazias.length ? vazias.join(", ") : "nenhuma"}`);
  console.log(`  erros: ${erros.length} (relevantes: ${graves.length})`);
  for (const e of graves.slice(0, 8)) console.log(`    ! ${e.slice(0, 200)}`);

  if (!entrou || vazias.length || graves.length) {
    console.log("  REPROVADO");
    process.exit(1);
  }
  console.log("  painel inteiro respondeu");
})();
