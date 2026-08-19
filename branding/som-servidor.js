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

  /* ------------------------------------------------------- pagina
     Vive como pagina nativa das configuracoes do servidor, no grupo
     Personalizacao, ao lado de Emojis. O rebrand.py acrescenta a
     entrada na lista e o caso no switch de render; aqui so montamos
     o conteudo. Nada de botao flutuante nem sobreposicao.

     Cada montagem cria os proprios elementos e guarda as referencias
     em variaveis locais: o Solid monta e desmonta a pagina a vontade,
     e buscar por id encontraria restos de uma montagem anterior. */
  var CSS_ID = "dp-som-css";
  function estilo() {
    if (document.getElementById(CSS_ID)) return;
    var e = document.createElement("style");
    e.id = CSS_ID;
    e.textContent =
      '.dp-som-pg{display:flex;flex-direction:column;gap:14px}' +
      '.dp-som-pg h3{margin:0;font-size:17px;font-weight:700}' +
      '.dp-som-pg .sub{opacity:.68;font-size:13px;line-height:1.5;margin:0}' +
      '.dp-som-pg .cartao{padding:14px 16px;border-radius:12px;' +
        'background:var(--md-sys-color-surface-variant,rgba(127,127,127,.10));' +
        'display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13.5px}' +
      '.dp-som-pg .cartao b{font-weight:650}' +
      '.dp-som-pg input[type=file]{font:13px system-ui,sans-serif;' +
        'padding:11px;border-radius:10px;border:1px dashed ' +
        'var(--md-sys-color-outline,rgba(127,127,127,.45));' +
        'background:transparent;color:inherit;width:100%}' +
      '.dp-som-pg .acoes{display:flex;gap:10px;flex-wrap:wrap}' +
      '.dp-som-pg button{cursor:pointer;border:0;border-radius:9px;' +
        'padding:9px 17px;font:650 13px system-ui,sans-serif;color:#fff;' +
        'background:linear-gradient(100deg,#2E8BEB,#8C41D9)}' +
      '.dp-som-pg button[disabled]{opacity:.45;cursor:not-allowed}' +
      '.dp-som-pg button.sec{background:transparent;color:inherit;' +
        'border:1px solid var(--md-sys-color-outline,rgba(127,127,127,.45))}' +
      '.dp-som-pg button.perigo{background:transparent;' +
        'color:var(--md-sys-color-error,#ff6b6b);' +
        'border:1px solid var(--md-sys-color-error,#ff6b6b)}' +
      '.dp-som-pg button.mini{padding:5px 12px;font-size:12px}' +
      '.dp-som-pg .aviso{padding:10px 13px;border-radius:9px;font-size:13px;' +
        'display:none}' +
      '.dp-som-pg .aviso.on{display:block;background:rgba(235,68,68,.12);' +
        'border:1px solid rgba(235,68,68,.34);color:#ffb3b3}' +
      '.dp-som-pg .aviso.ok{background:rgba(74,222,128,.12);' +
        'border-color:rgba(74,222,128,.34);color:#8df0b0}';
    document.head.appendChild(e);
  }

  function el(tag, attrs, texto) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (texto != null) e.textContent = texto;
    return e;
  }

  /* Icone da entrada na lista lateral (nota musical). */
  window.dpSomIcone = function () {
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("width", "20"); s.setAttribute("height", "20");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("fill", "currentColor");
    var p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", "M12 3v10.55A4 4 0 1 0 14 17V7h4V3z");
    s.appendChild(p);
    return s;
  };

  /* Chamada pelo switch de render das configuracoes do servidor.
     Recebe o servidor e devolve o elemento da pagina. */
  window.dpSomPagina = function (servidor) {
    estilo();
    var sid = (servidor && (servidor.id || servidor._id)) || servidorAtual();
    var raiz = el("div", {"class": "dp-som-pg"});

    raiz.appendChild(el("h3", null, "Som de notificação"));
    raiz.appendChild(el("p", {"class": "sub"},
      "Vale para todos os membros deste servidor. Sem som próprio, " +
      "toca o padrão da plataforma."));

    var cartao = el("div", {"class": "cartao"}, "Consultando…");
    raiz.appendChild(cartao);

    var arq = el("input", {type: "file",
      accept: "audio/mpeg,audio/ogg,audio/wav,audio/mp4,.mp3,.ogg,.wav,.m4a"});
    raiz.appendChild(arq);
    raiz.appendChild(el("p", {"class": "sub"},
      "Até 512 KB. Prefira algo curto — um aviso longo cansa rápido."));

    var acoes = el("div", {"class": "acoes"});
    var enviar = el("button", null, "Enviar");
    acoes.appendChild(enviar);
    raiz.appendChild(acoes);

    var msg = el("div", {"class": "aviso"});
    raiz.appendChild(msg);

    function aviso(t, ok) {
      msg.textContent = t;
      msg.className = "aviso on" + (ok ? " ok" : "");
    }

    function mostrarAtual() {
      _fetch(API + "/sons/" + sid, {cache: "no-store"})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          cache[sid] = d && d.tem ? d.url : null;
          cartao.textContent = "";
          if (!d || !d.tem) {
            cartao.textContent = "Nenhum som próprio configurado.";
            return;
          }
          var t = el("span");
          t.appendChild(document.createTextNode("Atual: "));
          t.appendChild(el("b", null, d.nome || "som"));
          cartao.appendChild(t);
          var ouvir = el("button", {"class": "sec mini"}, "Ouvir");
          ouvir.addEventListener("click", function () {
            new Original(d.url).play().catch(function () {});
          });
          var rem = el("button", {"class": "perigo mini"}, "Remover");
          rem.addEventListener("click", function () { remover(); });
          cartao.appendChild(ouvir);
          cartao.appendChild(rem);
        })
        .catch(function () { cartao.textContent = "Não consegui consultar."; });
    }

    function remover() {
      if (!confirm("Voltar ao som padrão da plataforma?")) return;
      _fetch(API + "/sons/" + sid, {
        method: "POST",
        headers: {"Content-Type": "application/json",
                  "X-Session-Token": token || ""},
        body: JSON.stringify({remover: true})
      }).then(function () {
        delete cache[sid];
        aviso("Voltou ao som padrão.", true);
        mostrarAtual();
      }).catch(function () { aviso("Falha ao remover."); });
    }

    enviar.addEventListener("click", function () {
      var f = arq.files && arq.files[0];
      if (!f) return aviso("Escolha um arquivo.");
      if (f.size > 512 * 1024) return aviso("Arquivo maior que 512 KB.");
      enviar.disabled = true; enviar.textContent = "Enviando…";
      var fr = new FileReader();
      fr.onload = function () {
        var b64 = String(fr.result).split(",")[1];
        _fetch(API + "/sons/" + sid, {
          method: "POST",
          headers: {"Content-Type": "application/json",
                    "X-Session-Token": token || ""},
          body: JSON.stringify({dados: b64, tipo: f.type || "audio/mpeg",
                                nome: f.name})
        }).then(function (r) {
            return r.json().then(function (j) {
              return {status: r.status, d: j}; });
          })
          .then(function (r) {
            if (r.status !== 200) {
              aviso((r.d && r.d.mensagem) || "Não foi possível enviar.");
              return;
            }
            delete cache[sid];
            arq.value = "";
            aviso("Som atualizado. Vale para todos os membros.", true);
            mostrarAtual();
          })
          .catch(function () { aviso("Falha ao enviar."); })
          .then(function () {
            enviar.disabled = false; enviar.textContent = "Enviar";
          });
      };
      fr.onerror = function () {
        aviso("Não consegui ler o arquivo.");
        enviar.disabled = false; enviar.textContent = "Enviar";
      };
      fr.readAsDataURL(f);
    });

    mostrarAtual();
    return raiz;
  };
})();
