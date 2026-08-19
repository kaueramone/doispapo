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

  /* Diagnóstico: informa o que existe na tela para eu mapear cada fluxo
     de áudio ao respectivo participante. */
  window.dpFalantes = function () {
    var a = window.dpAudio || {};
    var mids = document.querySelectorAll("audio,video");
    var lista = [];
    for (var i = 0; i < mids.length; i++) {
      var m = mids[i], attrs = {};
      for (var k = 0; k < m.attributes.length; k++)
        attrs[m.attributes[k].name] = m.attributes[k].value;
      lista.push({
        tag: m.tagName,
        atributos: attrs,
        temFluxo: !!m.srcObject,
        idDoFluxo: m.srcObject ? m.srcObject.id : null,
        paiClasses: m.parentElement ? m.parentElement.className : null
      });
    }
    var r = {
      elementosDeMidia: lista,
      fluxosMedidos: (a.remotos || []).map(function (x) {
        return { idDoFluxo: x.stream.id,
                 nivel: Math.round(x.nivel),
                 ativo: x.stream.active };
      }),
      meuNivel: a.estado ? Math.round(a.estado.nivel) : null
    };
    console.log(JSON.stringify(r, null, 2));
    return r;
  };

  /* ------------------------- luz de fala local ------------------------ */
  /* A luz nativa depende do servidor: o SFU analisa os níveis e transmite
     de volta a lista de falantes ativos, então há uma ida e volta antes de
     acender. Aqui acendemos direto do analisador local, em 40 ms.
     Só a própria luz — o áudio dos outros chega misturado, e analisá-lo
     individualmente exigiria interceptar a reprodução, com risco de mudo
     geral. */
  var meuNome = null, tokenSessao = null;

  var _fetch = window.fetch;
  window.fetch = function (entrada, init) {
    try {
      var h = (init && init.headers) || (entrada && entrada.headers);
      if (h) {
        var t = h.get ? h.get("X-Session-Token") : h["X-Session-Token"];
        if (t) tokenSessao = t;
      }
    } catch (e) {}
    return _fetch.apply(this, arguments);
  };

  function descobrirNome() {
    if (meuNome || !tokenSessao) return;
    _fetch("/api/users/@me", { headers: { "X-Session-Token": tokenSessao } })
      .then(function (r) { return r.json(); })
      .then(function (u) { if (u && u.username) meuNome = u.username; })
      .catch(function () {});
  }

  var estiloLuz = document.createElement("style");
  estiloLuz.textContent =
    ".dp-falando{position:relative}" +
    ".dp-falando::after{content:'';position:absolute;inset:-3px;" +
      "border-radius:12px;border:2px solid #3fb950;" +
      "box-shadow:0 0 10px rgba(63,185,80,.65);pointer-events:none;" +
      "animation:dp-pulso .9s ease-in-out infinite}" +
    "@keyframes dp-pulso{0%,100%{opacity:1}50%{opacity:.55}}" +
    "@media(prefers-reduced-motion:reduce){" +
      ".dp-falando::after{animation:none}}";
  document.head.appendChild(estiloLuz);

  function meuBloco() {
    if (!meuNome) return null;
    var spans = document.querySelectorAll("span");
    for (var i = 0; i < spans.length; i++) {
      if ((spans[i].textContent || "").trim() !== meuNome) continue;
      var bloco = spans[i].parentElement;
      // o bloco do participante contém o avatar em <svg>
      if (bloco && bloco.querySelector("svg")) return bloco;
    }
    return null;
  }

  function luzDeFala() {
    descobrirNome();
    var a = window.dpAudio;
    if (!a || !a.estado.ctx) {           // sem microfone ativo, sem luz
      document.querySelectorAll(".dp-falando").forEach(function (e) {
        e.classList.remove("dp-falando");
      });
      return;
    }
    // independe do portão estar ligado: a luz indica nível de voz
    var falando = a.estado.nivel >= a.cfg.limiar;
    var bloco = meuBloco();
    if (!bloco) return;
    bloco.classList.toggle("dp-falando", falando);
  }

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
  // a luz precisa de cadência bem mais rápida que o resto
  setInterval(luzDeFala, 40);
  new MutationObserver(entrarDireto).observe(document.documentElement,
    { childList: true, subtree: true });
})();
