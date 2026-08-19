/* ---------------------------------------------------------------------
   Dois Papo — som de notificação por servidor, um para cada evento.

   Hierarquia: se o servidor aberto tem som próprio para aquele evento,
   ele vale; senão, toca o padrão da plataforma.

   A troca acontece na construção do Audio. Isso só é possível porque o
   rebrand.py transforma os sons embutidos em ARQUIVOS com nome
   (/assets/sounds/dp-<evento>.ogg). Enquanto eram data URIs em base64
   todas as chamadas eram indistinguíveis, e dava para trocar no máximo
   "algum som" — não este ou aquele. Chamadas de voz não passam por
   aqui: usam srcObject, sem argumento no construtor.
--------------------------------------------------------------------- */
(function () {
  "use strict";
  var API = "/api-convites", token = null;
  var cache = {};            // servidor -> { evento: url }
  var pendentes = {};

  /* Os eventos que o cliente realmente toca. A configuração do app lista
     14, mas quatro (unmute, userJoinVoice, userLeaveVoice, userMoved)
     têm interruptor e nenhum case no switch de reprodução: nunca soam.
     Oferecer campo para elas seria oferecer um botão sem efeito. */
  var SONS = [
    ["message",           "Nova mensagem"],
    ["ringtoneIncoming",  "Chamada recebida"],
    ["ringtoneOutgoing",  "Chamando"],
    ["mute",              "Microfone silenciado"],
    ["deafen",            "Áudio desligado"],
    ["undeafen",          "Áudio religado"],
    ["streamStart",       "Transmissão iniciada"],
    ["streamEnd",         "Transmissão encerrada"],
    ["streamViewerJoin",  "Espectador entrou"],
    ["streamViewerLeave", "Espectador saiu"]
  ];
  var VALIDOS = {};
  SONS.forEach(function (s) { VALIDOS[s[0]] = true; });

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

  function buscar(sid) {
    if (!sid || pendentes[sid] || cache[sid] !== undefined) return;
    pendentes[sid] = true;
    _fetch(API + "/sons/" + sid, {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var m = {};
        var sons = (d && d.sons) || {};
        for (var k in sons) if (sons[k] && sons[k].url) m[k] = sons[k].url;
        cache[sid] = m;
      })
      .catch(function () { cache[sid] = {}; })
      .then(function () { delete pendentes[sid]; });
  }

  function personalizado(evento) {
    var sid = servidorAtual();
    if (!sid || !evento) return null;
    if (cache[sid] === undefined) { buscar(sid); return null; }
    return cache[sid][evento] || null;
  }

  /* ------------------------------------------------- interceptação */
  var Original = window.Audio;

  function nomeDoSom(src) {
    if (!src || typeof src !== "string") return null;
    var m = src.match(/\/assets\/sounds\/dp-([A-Za-z]+)\.ogg/);
    if (m && VALIDOS[m[1]]) return m[1];
    if (src.indexOf("message_sound") >= 0) return "message";
    return null;
  }

  window.Audio = function (src) {
    var evento = nomeDoSom(src);
    if (evento) {
      var proprio = personalizado(evento);
      if (proprio) return new Original(proprio);
    }
    return arguments.length ? new Original(src) : new Original();
  };
  window.Audio.prototype = Original.prototype;

  /* ------------------------------------------------------- página */
  var CSS_ID = "dp-som-css";
  function estilo() {
    if (document.getElementById(CSS_ID)) return;
    var e = document.createElement("style");
    e.id = CSS_ID;
    e.textContent =
      '.dp-som-pg{display:flex;flex-direction:column;gap:14px}' +
      '.dp-som-pg h3{margin:0;font-size:17px;font-weight:700}' +
      '.dp-som-pg .sub{opacity:.68;font-size:13px;line-height:1.5;margin:0}' +
      '.dp-som-pg .lista{display:flex;flex-direction:column;gap:8px}' +
      '.dp-som-pg .linha{display:flex;align-items:center;gap:12px;' +
        'flex-wrap:wrap;padding:11px 14px;border-radius:11px;' +
        'background:var(--md-sys-color-surface-variant,rgba(127,127,127,.10))}' +
      '.dp-som-pg .rot{flex:1;min-width:150px;font-size:13.5px}' +
      '.dp-som-pg .rot .est{display:block;opacity:.6;font-size:12px;' +
        'margin-top:2px}' +
      '.dp-som-pg .rot .est.prop{opacity:.95;color:#8df0b0}' +
      '.dp-som-pg .acoes{display:flex;gap:7px;flex-shrink:0}' +
      '.dp-som-pg button{cursor:pointer;border:1px solid ' +
        'var(--md-sys-color-outline,rgba(127,127,127,.45));background:none;' +
        'color:inherit;border-radius:8px;padding:6px 13px;' +
        'font:600 12.5px system-ui,sans-serif}' +
      '.dp-som-pg button.trocar{border:0;color:#fff;' +
        'background:linear-gradient(100deg,#2E8BEB,#8C41D9)}' +
      '.dp-som-pg button[disabled]{opacity:.45;cursor:not-allowed}' +
      '.dp-som-pg button.perigo{color:var(--md-sys-color-error,#ff6b6b);' +
        'border-color:var(--md-sys-color-error,#ff6b6b)}' +
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

  /* Chamada pelo switch de render das configurações do servidor.
     Cada montagem cria os próprios elementos e guarda as referências em
     variáveis locais: o Solid monta e desmonta a página à vontade, e
     buscar por id encontraria restos de uma montagem anterior. */
  window.dpSomPagina = function (servidor) {
    estilo();
    var sid = (servidor && (servidor.id || servidor._id)) || servidorAtual();
    var raiz = el("div", {"class": "dp-som-pg"});

    raiz.appendChild(el("h3", null, "Sons de notificação"));
    raiz.appendChild(el("p", {"class": "sub"},
      "Um som para cada evento, valendo para todos os membros deste " +
      "servidor. Onde não houver som próprio, toca o padrão da " +
      "plataforma. Até 512 KB por arquivo — MP3, OGG, WAV ou M4A."));

    var msg = el("div", {"class": "aviso"});
    var lista = el("div", {"class": "lista"});
    raiz.appendChild(lista);
    raiz.appendChild(msg);

    function aviso(t, ok) {
      msg.textContent = t;
      msg.className = "aviso on" + (ok ? " ok" : "");
    }

    var linhas = {};
    SONS.forEach(function (par) {
      var chave = par[0], rotulo = par[1];

      var linha = el("div", {"class": "linha"});
      var rot = el("div", {"class": "rot"});
      rot.appendChild(el("span", null, rotulo));
      var est = el("span", {"class": "est"}, "padrão da plataforma");
      rot.appendChild(est);
      linha.appendChild(rot);

      var arq = el("input", {type: "file", style: "display:none",
        accept: "audio/mpeg,audio/ogg,audio/wav,audio/mp4,.mp3,.ogg,.wav,.m4a"});
      linha.appendChild(arq);

      var acoes = el("div", {"class": "acoes"});
      var ouvir = el("button", null, "Ouvir");
      var trocar = el("button", {"class": "trocar"}, "Trocar");
      var remover = el("button", {"class": "perigo"}, "Remover");
      remover.style.display = "none";
      acoes.appendChild(ouvir);
      acoes.appendChild(trocar);
      acoes.appendChild(remover);
      linha.appendChild(acoes);
      lista.appendChild(linha);

      linhas[chave] = {est: est, remover: remover, trocar: trocar, url: null};

      ouvir.addEventListener("click", function () {
        var u = linhas[chave].url || ("/assets/sounds/dp-" + chave + ".ogg");
        new Original(u).play().catch(function () {});
      });
      trocar.addEventListener("click", function () { arq.click(); });
      arq.addEventListener("change", function () {
        var f = arq.files && arq.files[0];
        if (!f) return;
        if (f.size > 512 * 1024) { arq.value = ""; return aviso(
          "“" + rotulo + "”: o arquivo precisa ter menos de 512 KB."); }
        enviar(chave, rotulo, f, trocar, function () { arq.value = ""; });
      });
      remover.addEventListener("click", function () {
        apagar(chave, rotulo, remover);
      });
    });

    function pinta(chave, info) {
      var l = linhas[chave];
      if (!l) return;
      if (info) {
        l.url = info.url;
        l.est.textContent = info.nome || "som próprio";
        l.est.className = "est prop";
        l.remover.style.display = "";
      } else {
        l.url = null;
        l.est.textContent = "padrão da plataforma";
        l.est.className = "est";
        l.remover.style.display = "none";
      }
    }

    function carregar() {
      _fetch(API + "/sons/" + sid, {cache: "no-store"})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var sons = (d && d.sons) || {};
          var m = {};
          SONS.forEach(function (par) {
            pinta(par[0], sons[par[0]] || null);
            if (sons[par[0]]) m[par[0]] = sons[par[0]].url;
          });
          cache[sid] = m;
        })
        .catch(function () { aviso("Não consegui consultar os sons."); });
    }

    function enviar(chave, rotulo, f, bt, aoFim) {
      bt.disabled = true; bt.textContent = "Enviando…";
      var fr = new FileReader();
      fr.onload = function () {
        var b64 = String(fr.result).split(",")[1];
        _fetch(API + "/sons/" + sid, {
          method: "POST",
          headers: {"Content-Type": "application/json",
                    "X-Session-Token": token || ""},
          body: JSON.stringify({som: chave, dados: b64,
                                tipo: f.type || "audio/mpeg", nome: f.name})
        }).then(function (r) {
            return r.json().then(function (j) {
              return {status: r.status, d: j}; });
          })
          .then(function (r) {
            if (r.status !== 200) {
              aviso("“" + rotulo + "”: " +
                    ((r.d && r.d.mensagem) || "não foi possível enviar."));
              return;
            }
            delete cache[sid];
            aviso("“" + rotulo + "” atualizado para todos os membros.", true);
            carregar();
          })
          .catch(function () { aviso("Falha ao enviar “" + rotulo + "”."); })
          .then(function () {
            bt.disabled = false; bt.textContent = "Trocar";
            if (aoFim) aoFim();
          });
      };
      fr.onerror = function () {
        aviso("Não consegui ler o arquivo.");
        bt.disabled = false; bt.textContent = "Trocar";
        if (aoFim) aoFim();
      };
      fr.readAsDataURL(f);
    }

    function apagar(chave, rotulo, bt) {
      bt.disabled = true;
      _fetch(API + "/sons/" + sid, {
        method: "POST",
        headers: {"Content-Type": "application/json",
                  "X-Session-Token": token || ""},
        body: JSON.stringify({som: chave, remover: true})
      }).then(function () {
        delete cache[sid];
        aviso("“" + rotulo + "” voltou ao padrão.", true);
        carregar();
      }).catch(function () {
        aviso("Falha ao remover “" + rotulo + "”.");
      }).then(function () { bt.disabled = false; });
    }

    carregar();
    return raiz;
  };
})();
