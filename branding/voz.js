/* ---------------------------------------------------------------------
   Dois Papo — comportamento dos canais de voz.

   1) Entrar direto: abrir um canal de voz já conecta, sem o segundo
      clique em "Entrar na chamada".
   2) Contador: mostra há quanto tempo a chamada está aberta, ao lado do
      canal. O tempo vem do servidor, alimentado pelos webhooks do
      LiveKit — contar a partir do que este navegador viu daria número
      errado para quem chega depois.
--------------------------------------------------------------------- */
(function () {
  "use strict";
  var API = "/api-convites";

  /* ------------------------------------------------------ entrar direto */
  var saiuDe = null;   // canal do qual o usuário saiu de propósito

  function botaoEntrar() {
    var els = document.querySelectorAll("button,[role='button'],a");
    for (var i = 0; i < els.length; i++) {
      var t = (els[i].textContent || "").trim();
      if (t.length > 28) continue;
      // O texto muda conforme o canal: "Iniciar a chamada" quando vazio,
      // "Entrar na chamada" ao voltar, e "Com Fulano, Ciclano" quando já
      // há gente dentro.
      if (/^(iniciar a chamada|entrar na chamada|entrar no canal de voz|join call|start the call)$/i.test(t))
        return els[i];
      if (els[i].tagName === "BUTTON" && /^com .{1,24}$/i.test(t))
        return els[i];
    }
    return null;
  }

  function canalAtual() {
    var m = location.pathname.match(/\/channel\/([A-Z0-9]+)/i);
    return m ? m[1] : null;
  }

  // Sair é decisão explícita: não reconectamos enquanto a pessoa
  // continuar olhando o mesmo canal.
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("button,[role='button']");
    if (!b) return;
    var t = (b.textContent || "").trim();
    if (t.length < 40 && /(sair da chamada|desconectar|encerrar chamada|leave call)/i.test(t))
      saiuDe = canalAtual();
  }, true);

  var ultimo = location.pathname;
  setInterval(function () {
    if (location.pathname !== ultimo) {
      ultimo = location.pathname;
      if (saiuDe && saiuDe !== canalAtual()) saiuDe = null;
    }
  }, 400);

  function entrarDireto() {
    if (saiuDe && saiuDe === canalAtual()) return;
    var b = botaoEntrar();
    if (b) b.click();
  }

  /* --------------------------------------------------------- contador */
  var chamadas = {};

  function buscar() {
    fetch(API + "/chamadas", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) { chamadas = d.chamadas || {}; })
      .catch(function () {});
  }
  buscar();
  setInterval(buscar, 20000);

  function formatar(seg) {
    var h = Math.floor(seg / 3600), m = Math.floor((seg % 3600) / 60),
        s = Math.floor(seg % 60);
    if (h) return h + "h" + String(m).padStart(2, "0");
    if (m) return m + "min";
    return s + "s";
  }

  function pintarContadores() {
    var agora = Date.now() / 1000;
    Object.keys(chamadas).forEach(function (id) {
      var c = chamadas[id];
      if (!c || !c.inicio) return;
      var links = document.querySelectorAll('a[href*="/channel/' + id + '"]');
      for (var i = 0; i < links.length; i++) {
        var alvo = links[i];
        var eti = alvo.querySelector(".dp-tempo");
        if (!eti) {
          eti = document.createElement("span");
          eti.className = "dp-tempo";
          alvo.appendChild(eti);
        }
        eti.textContent = formatar(agora - c.inicio);
        eti.title = "chamada aberta há " + formatar(agora - c.inicio);
      }
    });
    // remove os que não têm mais chamada
    document.querySelectorAll(".dp-tempo").forEach(function (e) {
      var a = e.closest("a[href]");
      if (!a) return;
      var m = a.getAttribute("href").match(/\/channel\/([A-Z0-9]+)/i);
      if (!m || !chamadas[m[1]]) e.remove();
    });
  }

  var css = document.createElement("style");
  css.textContent =
    ".dp-tempo{margin-left:auto;padding:1px 7px;border-radius:999px;" +
    "font:600 10.5px/1.5 ui-monospace,monospace;color:#8df0b0;" +
    "background:rgba(63,185,80,.14);border:1px solid rgba(63,185,80,.3);" +
    "white-space:nowrap;flex-shrink:0}";
  document.head.appendChild(css);

  function tick() { entrarDireto(); pintarContadores(); }
  setInterval(tick, 1000);
  new MutationObserver(entrarDireto).observe(document.documentElement,
    { childList: true, subtree: true });
})();
