/* ---------------------------------------------------------------------
   Dois Papo — som de notificação por servidor.

   Hierarquia: se o servidor aberto tem som próprio, ele vale; senão,
   toca o padrão da plataforma.

   A troca acontece na construção do Audio. Os sons de notificação são
   data URIs embutidas no bundle (ou o arquivo do som de mensagem), então
   reconhecê-los é direto — e chamadas de voz não passam por aqui, porque
   usam srcObject, sem argumento no construtor.
--------------------------------------------------------------------- */
(function () {
  "use strict";
  var API = "/api-convites", token = null;
  var cache = {};            // servidor -> url do som (ou null)
  var pendentes = {};

  var _fetch = window.fetch;
  window.fetch = function (entrada, init) {
    try {
      var h = (init && init.headers) || (entrada && entrada.headers);
      if (h) {
        var t = h.get ? h.get("X-Session-Token") : h["X-Session-Token"];
        if (t) token = t;
      }
    } catch (e) {}
    return _fetch.apply(this, arguments);
  };

  function servidorAtual() {
    var m = location.pathname.match(/\/server\/([A-Z0-9]+)/i);
    return m ? m[1] : null;
  }

  function buscarSom(sid) {
    if (!sid || pendentes[sid] || cache[sid] !== undefined) return;
    pendentes[sid] = true;
    _fetch(API + "/sons/" + sid, {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) { cache[sid] = (d && d.tem) ? d.url : null; })
      .catch(function () { cache[sid] = null; })
      .then(function () { delete pendentes[sid]; });
  }

  function somDoServidor() {
    var sid = servidorAtual();
    if (!sid) return null;
    if (cache[sid] === undefined) { buscarSom(sid); return null; }
    return cache[sid];
  }

  /* ------------------------------------------------- interceptação */
  var Original = window.Audio;
  function ehNotificacao(src) {
    if (!src || typeof src !== "string") return false;
    return src.indexOf("data:audio/") === 0 ||
           src.indexOf("message_sound") >= 0;
  }
  window.Audio = function (src) {
    if (ehNotificacao(src)) {
      var proprio = somDoServidor();
      if (proprio) return new Original(proprio);
    }
    return arguments.length ? new Original(src) : new Original();
  };
  window.Audio.prototype = Original.prototype;

  /* ------------------------------------------------------- painel */
  var css = document.createElement("style");
  css.textContent =
    '#dp-som-bt{position:fixed;right:22px;bottom:74px;z-index:2147483000;' +
      'padding:11px 18px;border:0;border-radius:12px;cursor:pointer;' +
      'color:#fff;font:650 13.5px system-ui,sans-serif;' +
      'background:linear-gradient(100deg,#3fb950,#2E8BEB);' +
      'box-shadow:0 14px 34px -14px rgba(46,139,235,.9)}' +
    '#dp-som{position:fixed;inset:0;z-index:2147483001;display:flex;' +
      'align-items:center;justify-content:center;padding:22px;' +
      'background:rgba(4,8,14,.82);font:14px/1.6 system-ui,sans-serif;' +
      'color:#e8edf6}' +
    '#dp-som .cx{background:#141d2b;border:1px solid #22304a;' +
      'border-radius:16px;padding:26px;max-width:min(520px,94vw);width:100%}' +
    '#dp-som h3{font-size:17px;margin:0 0 4px}' +
    '#dp-som .sub{color:#93a1bb;font-size:13px;margin-bottom:16px}' +
    '#dp-som .atual{background:#0f1724;border:1px solid #22304a;' +
      'border-radius:10px;padding:12px 14px;margin-bottom:14px;font-size:13px}' +
    '#dp-som input[type=file]{width:100%;font-size:13px;color:#93a1bb}' +
    '#dp-som .acoes{display:flex;gap:10px;margin-top:16px}' +
    '#dp-som button{flex:1;cursor:pointer;border:0;border-radius:10px;' +
      'padding:11px;font:650 13px system-ui;color:#fff;' +
      'background:linear-gradient(100deg,#2E8BEB,#8C41D9)}' +
    '#dp-som button.sec{background:#22304a;color:#c7d1e4}' +
    '#dp-som button.perigo{background:#3a2030;color:#ffb3b3}' +
    '#dp-som button[disabled]{opacity:.5;cursor:not-allowed}' +
    '#dp-som .aviso{margin-top:13px;padding:11px 13px;border-radius:9px;' +
      'font-size:13px;display:none}' +
    '#dp-som .aviso.on{display:block;background:rgba(235,68,68,.12);' +
      'border:1px solid rgba(235,68,68,.34);color:#ffb3b3}' +
    '#dp-som .aviso.ok{background:rgba(74,222,128,.12);' +
      'border-color:rgba(74,222,128,.34);color:#8df0b0}';
  document.head.appendChild(css);

  function aviso(t, ok) {
    var e = document.getElementById("dp-som-msg");
    if (e) { e.textContent = t; e.className = "aviso on" + (ok ? " ok" : ""); }
  }

  function abrir() {
    if (document.getElementById("dp-som")) return;
    var sid = servidorAtual();
    if (!sid) return;
    var ov = document.createElement("div");
    ov.id = "dp-som";
    ov.innerHTML =
      '<div class="cx">' +
        '<h3>Som de notificação do servidor</h3>' +
        '<div class="sub">Vale para todos os membros. Sem som próprio, ' +
          'toca o padrão da plataforma.</div>' +
        '<div class="atual" id="dp-som-atual">Consultando…</div>' +
        '<input type="file" id="dp-som-arq" accept="audio/mpeg,audio/ogg,audio/wav,audio/mp4,.mp3,.ogg,.wav,.m4a">' +
        '<div class="sub" style="margin:8px 0 0">Até 512 KB. Prefira algo ' +
          'curto — um aviso longo cansa rápido.</div>' +
        '<div class="acoes">' +
          '<button class="sec" id="dp-som-fechar">Fechar</button>' +
          '<button id="dp-som-enviar">Enviar</button>' +
        '</div>' +
        '<div class="aviso" id="dp-som-msg"></div>' +
      '</div>';
    document.body.appendChild(ov);
    ov.addEventListener("click", function (e) { if (e.target === ov) ov.remove(); });
    document.getElementById("dp-som-fechar")
      .addEventListener("click", function () { ov.remove(); });
    document.getElementById("dp-som-enviar").addEventListener("click", enviar);
    atualizarAtual(sid);
  }

  function atualizarAtual(sid) {
    _fetch(API + "/sons/" + sid, {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var el = document.getElementById("dp-som-atual");
        if (!el) return;
        cache[sid] = d && d.tem ? d.url : null;
        if (!d || !d.tem) { el.textContent = "Nenhum som próprio configurado."; return; }
        el.innerHTML = "Atual: <b>" + (d.nome || "som") + "</b> " +
          '<button class="sec" id="dp-som-ouvir" style="flex:0;padding:5px 11px;' +
          'font-size:12px;margin-left:8px">Ouvir</button> ' +
          '<button class="perigo" id="dp-som-remover" style="flex:0;' +
          'padding:5px 11px;font-size:12px">Remover</button>';
        document.getElementById("dp-som-ouvir").addEventListener("click",
          function () { new Audio(d.url).play().catch(function () {}); });
        document.getElementById("dp-som-remover").addEventListener("click",
          function () { remover(sid); });
      })
      .catch(function () {});
  }

  function enviar() {
    var sid = servidorAtual();
    var inp = document.getElementById("dp-som-arq");
    var f = inp && inp.files && inp.files[0];
    if (!f) return aviso("Escolha um arquivo.");
    if (f.size > 512 * 1024) return aviso("Arquivo maior que 512 KB.");
    var bt = document.getElementById("dp-som-enviar");
    bt.disabled = true; bt.textContent = "Enviando…";

    var fr = new FileReader();
    fr.onload = function () {
      var b64 = String(fr.result).split(",")[1];
      _fetch(API + "/sons/" + sid, {
        method: "POST",
        headers: {"Content-Type": "application/json",
                  "X-Session-Token": token || ""},
        body: JSON.stringify({dados: b64, tipo: f.type || "audio/mpeg",
                              nome: f.name})
      }).then(function (r) { return r.json().then(function (j) {
          return {status: r.status, d: j}; }); })
        .then(function (r) {
          if (r.status !== 200) { aviso(r.d.mensagem || "Não foi possível enviar."); return; }
          delete cache[sid];
          aviso("Som atualizado. Vale para todos os membros.", true);
          atualizarAtual(sid);
        })
        .catch(function () { aviso("Falha ao enviar."); })
        .finally(function () { bt.disabled = false; bt.textContent = "Enviar"; });
    };
    fr.onerror = function () {
      aviso("Não consegui ler o arquivo.");
      bt.disabled = false; bt.textContent = "Enviar";
    };
    fr.readAsDataURL(f);
  }

  function remover(sid) {
    if (!confirm("Voltar ao som padrão da plataforma?")) return;
    _fetch(API + "/sons/" + sid, {
      method: "POST",
      headers: {"Content-Type": "application/json",
                "X-Session-Token": token || ""},
      body: JSON.stringify({remover: true})
    }).then(function () {
      delete cache[sid];
      aviso("Voltou ao som padrão.", true);
      atualizarAtual(sid);
    }).catch(function () { aviso("Falha ao remover."); });
  }

  /* ------------------------------------------------------ gatilho */
  var ROTULOS = /^(cargos|convites|banimentos|membros|vis[ãa]o geral)$/i;
  function nasConfigs() {
    if (!servidorAtual()) return false;
    var n = 0, els = document.querySelectorAll("div,span,a,button");
    for (var i = 0; i < els.length && n < 2; i++) {
      var t = (els[i].textContent || "").trim();
      if (t.length <= 24 && ROTULOS.test(t)) n++;
    }
    return n >= 2;
  }
  setInterval(function () {
    var bt = document.getElementById("dp-som-bt");
    if (nasConfigs()) {
      if (!bt) {
        bt = document.createElement("button");
        bt.id = "dp-som-bt";
        bt.textContent = "Som do servidor";
        bt.addEventListener("click", abrir);
        document.body.appendChild(bt);
      }
    } else if (bt && !document.getElementById("dp-som")) bt.remove();
  }, 1200);
})();
