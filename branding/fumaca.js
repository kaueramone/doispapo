/* ---------------------------------------------------------------------
   Portão de fumaça: o cliente sobe de verdade?

   O verificar.py confere a estrutura do HTML e se cada remendo achou seu
   alvo. O `node --check` confere sintaxe. Nenhum dos dois EXECUTA o
   aplicativo — e foi por essa fresta que a 0.36.0 passou: um ciclo de
   importação deixava uma variável na zona morta temporal, o módulo
   estourava na inicialização e a tela ficava branca. Build aprovado,
   produção derrubada.

   Aqui um navegador de verdade abre a página, espera o app montar e
   recolhe o que deu errado. Dois sinais, porque um só engana:

     1) erro não tratado no console  — o sintoma direto
     2) #root vazio ao fim da espera — a tela branca em si, mesmo que
        nada tenha sido registrado no console

   Uso:
     node fumaca.js <url>

   Sai com 0 se o app montou sem erro, 1 se não.
--------------------------------------------------------------------- */
const { chromium } = require("playwright");

const URL_ALVO = process.argv[2];
const ESPERA_MS = Number(process.env.FUMACA_ESPERA || 30000);

/* Ruído que não indica app quebrado: o cliente é uma instância privada,
   então requisição barrada por falta de sessão é o estado normal de quem
   abre a página deslogado. Filtrar por PADRÃO conhecido, nunca por
   "ignore os erros" — senão o portão para de valer. */
const RUIDO = [
  /401|403/,
  /Failed to load resource/i,
  /net::ERR_/,
  /favicon/i,
  /ServiceWorker/i,
  /manifest/i,
];

function ruido(texto) {
  return RUIDO.some((p) => p.test(texto));
}

(async () => {
  if (!URL_ALVO) {
    console.error("uso: node fumaca.js <url>");
    process.exit(2);
  }

  const navegador = await chromium.launch({ args: ["--no-sandbox"] });
  // Sem cache e sem service worker: queremos julgar ESTE build, não o
  // que o navegador guardou de uma visita anterior.
  const contexto = await navegador.newContext({
    serviceWorkers: "block",
    bypassCSP: false,
  });
  const pagina = await contexto.newPage();

  const erros = [];
  // A pilha e o que permite mapear de volta ao fonte: sem ela sobra a
  // mensagem, que diz o QUE quebrou e nao ONDE.
  pagina.on("pageerror", (e) =>
    erros.push(String((e && (e.stack || e.message)) || e)),
  );
  pagina.on("console", (m) => {
    if (m.type() === "error") erros.push(m.text());
  });

  let montou = false;
  try {
    await pagina.goto(URL_ALVO, { waitUntil: "domcontentloaded", timeout: ESPERA_MS });
    // O app é uma SPA: o sinal de vida é o #root deixar de estar vazio.
    await pagina.waitForFunction(
      () => {
        const r = document.getElementById("root");
        return !!r && r.childElementCount > 0;
      },
      undefined,
      { timeout: ESPERA_MS },
    );
    montou = true;
  } catch {
    montou = false;
  }

  const graves = erros.filter((t) => !ruido(t));

  await navegador.close();

  console.log(`  montou: ${montou ? "sim" : "NAO"}`);
  console.log(`  erros no console: ${erros.length} (relevantes: ${graves.length})`);
  for (const e of graves.slice(0, 10)) console.log(`    ! ${e.slice(0, 200)}`);

  if (!montou || graves.length) {
    console.log("  REPROVADO no portao de fumaca");
    process.exit(1);
  }
  console.log("  aplicativo montou sem erro");
})();
