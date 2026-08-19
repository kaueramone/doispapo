/* ---------------------------------------------------------------------
   Dois Papo — importação de template do Discord.

   O template é um recurso oficial e público do Discord: o endpoint não
   pede autenticação, então nenhum token do usuário entra nisso. A leitura
   passa pelo nosso serviço apenas porque o navegador não consegue chamar
   a API do Discord diretamente (sem CORS).

   A criação usa a sessão de quem está importando, então respeita as
   permissões da pessoa no servidor.
--------------------------------------------------------------------- */
(function () {
  "use strict";
  var API = "/api-convites", token = null, previa = null, rodando = false;

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

  /* A API permite 20 requisições por 10 segundos e informa o estado nos
     cabeçalhos. A primeira versão espaçava 260ms às cegas — o dobro da
     velocidade permitida — e, ao receber 429, contava como falha e seguia
     adiante, perdendo o canal. Agora seguimos o que a própria API informa
     e repetimos o que foi recusado. */
  var limite = {restante: 20, resetEm: 0};

  function api(rota, opc, tentativa) {
    opc = opc || {}; tentativa = tentativa || 0;
    opc.headers = Object.assign({"Content-Type": "application/json"},
      opc.headers || {}, token ? {"X-Session-Token": token} : {});
    if (opc.corpo) { opc.method = opc.method || "POST";
                     opc.body = JSON.stringify(opc.corpo); delete opc.corpo; }

    // pausa preventiva quando a cota está no fim
    var pausa = 0;
    if (limite.restante <= 1 && limite.resetEm > Date.now())
      pausa = limite.resetEm - Date.now() + 150;

    return esperar(pausa).then(function () {
      return _fetch(rota, opc).then(function (r) {
        var rem = parseInt(r.headers.get("x-ratelimit-remaining"), 10);
        var reset = parseInt(r.headers.get("x-ratelimit-reset-after"), 10);
        if (!isNaN(rem)) limite.restante = rem;
        if (!isNaN(reset)) limite.resetEm = Date.now() + reset;

        if (r.status === 429 && tentativa < 8) {
          var ra = parseInt(r.headers.get("retry-after"), 10);
          // retry-after pode vir em segundos; normalizamos
          if (!isNaN(ra) && ra < 100) ra = ra * 1000;
          var d = !isNaN(ra) ? ra : (!isNaN(reset) ? reset : 3000);
          return esperar(d + 300).then(function () {
            return api(rota, {method: opc.method, body: opc.body,
                              headers: opc.headers}, tentativa + 1);
          });
        }
        return r.json().catch(function () { return {}; })
          .then(function (j) { return {status: r.status, d: j}; });
      });
    });
  }

  function servidorAtual() {
    var m = location.pathname.match(/\/server\/([A-Z0-9]+)/i);
    return m ? m[1] : null;
  }

  var esperar = function (ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  };

  /* ------------------------------------------------------------ estilo */
  var css = document.createElement("style");
  css.textContent =
    '#dp-imp-bt{position:fixed;right:22px;bottom:22px;z-index:2147483000;' +
      'display:flex;align-items:center;gap:8px;padding:11px 18px;' +
      'border:0;border-radius:12px;cursor:pointer;color:#fff;' +
      'font:650 13.5px system-ui,-apple-system,sans-serif;' +
      'background:linear-gradient(100deg,#2E8BEB,#8C41D9);' +
      'box-shadow:0 14px 34px -14px rgba(140,65,217,.9)}' +
    '#dp-imp-bt:hover{transform:translateY(-2px)}' +
    '#dp-imp{position:fixed;inset:0;z-index:2147483001;display:flex;' +
      'align-items:center;justify-content:center;padding:22px;' +
      'background:rgba(4,8,14,.82);backdrop-filter:blur(4px);' +
      'font:14px/1.6 system-ui,-apple-system,sans-serif;color:#e8edf6}' +
    '#dp-imp .cx{background:#141d2b;border:1px solid #22304a;' +
      'border-radius:16px;padding:26px;max-width:min(620px,94vw);' +
      'width:100%;max-height:88vh;overflow:auto}' +
    '#dp-imp h3{font-size:18px;margin:0 0 4px}' +
    '#dp-imp .sub{color:#93a1bb;font-size:13px;margin-bottom:18px}' +
    '#dp-imp ol{margin:0 0 16px 18px;font-size:13px;color:#a9b6cd}' +
    '#dp-imp ol li{margin-bottom:5px}' +
    '#dp-imp input{width:100%;background:#0b1119;color:#e8edf6;' +
      'border:1px solid #22304a;border-radius:10px;padding:11px 13px;' +
      'font:14px system-ui}' +
    '#dp-imp input:focus{outline:0;border-color:#8C41D9}' +
    '#dp-imp .acoes{display:flex;gap:10px;margin-top:16px}' +
    '#dp-imp button{flex:1;cursor:pointer;border:0;border-radius:10px;' +
      'padding:12px;font:650 13.5px system-ui;color:#fff;' +
      'background:linear-gradient(100deg,#2E8BEB,#8C41D9)}' +
    '#dp-imp button.sec{background:#22304a;color:#c7d1e4}' +
    '#dp-imp button[disabled]{opacity:.5;cursor:not-allowed}' +
    '#dp-imp .aviso{margin-top:14px;padding:11px 13px;border-radius:9px;' +
      'font-size:13px;display:none}' +
    '#dp-imp .aviso.on{display:block;background:rgba(235,68,68,.12);' +
      'border:1px solid rgba(235,68,68,.34);color:#ffb3b3}' +
    '#dp-imp .aviso.ok{background:rgba(74,222,128,.12);' +
      'border-color:rgba(74,222,128,.34);color:#8df0b0}' +
    '#dp-imp .previa{margin-top:16px;background:#0f1724;border-radius:11px;' +
      'border:1px solid #22304a;padding:14px;max-height:230px;overflow:auto}' +
    '#dp-imp .cat{font-weight:650;margin:8px 0 3px;font-size:13px}' +
    '#dp-imp .ch{font-size:12.5px;color:#93a1bb;margin-left:14px}' +
    '#dp-imp .resumo{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;' +
      'color:#93a1bb;margin-top:10px}' +
    '#dp-imp .resumo b{color:#e8edf6}';
  document.head.appendChild(css);

  /* ------------------------------------------------------------ janela */
  function abrir() {
    if (document.getElementById("dp-imp")) return;
    var ov = document.createElement("div");
    ov.id = "dp-imp";
    ov.innerHTML =
      '<div class="cx">' +
        '<h3>Importar estrutura do Discord</h3>' +
        '<div class="sub">Recria categorias, canais e cargos a partir de um ' +
          'template do seu servidor no Discord.</div>' +
        '<ol>' +
          '<li>No Discord: <b>Configurações do Servidor → Modelos</b></li>' +
          '<li>Crie um modelo e copie o link (<code>discord.new/…</code>)</li>' +
          '<li>Cole abaixo e confira a prévia antes de importar</li>' +
        '</ol>' +
        '<input id="dp-imp-link" placeholder="https://discord.new/…" ' +
          'autocomplete="off" spellcheck="false">' +
        '<div class="acoes">' +
          '<button class="sec" id="dp-imp-fechar">Cancelar</button>' +
          '<button id="dp-imp-ver">Consultar</button>' +
        '</div>' +
        '<div class="aviso" id="dp-imp-msg"></div>' +
        '<div id="dp-imp-previa"></div>' +
      '</div>';
    document.body.appendChild(ov);

    ov.addEventListener("click", function (e) {
      if (e.target === ov && !rodando) ov.remove();
    });
    document.getElementById("dp-imp-fechar")
      .addEventListener("click", function () { if (!rodando) ov.remove(); });
    document.getElementById("dp-imp-ver")
      .addEventListener("click", consultar);
    document.getElementById("dp-imp-link")
      .addEventListener("keydown", function (e) {
        if (e.key === "Enter") consultar();
      });
  }

  function msg(txt, ok) {
    var el = document.getElementById("dp-imp-msg");
    if (!el) return;
    el.textContent = txt;
    el.className = "aviso on" + (ok ? " ok" : "");
  }

  function consultar() {
    var v = (document.getElementById("dp-imp-link").value || "").trim();
    if (!v) return msg("Cole o link do template.");
    var bt = document.getElementById("dp-imp-ver");
    bt.disabled = true; bt.textContent = "Consultando…";
    _fetch(API + "/discord-template?codigo=" + encodeURIComponent(v))
      .then(function (r) { return r.json().then(function (j) {
        return {status: r.status, d: j}; }); })
      .then(function (r) {
        if (r.status !== 200) { msg(r.d.mensagem || "Não foi possível ler."); return; }
        previa = r.d;
        mostrarPrevia(r.d);
        msg("Template lido. Confira antes de importar.", true);
      })
      .catch(function () { msg("Falha ao consultar."); })
      .finally(function () {
        bt.disabled = false; bt.textContent = "Consultar";
      });
  }

  function mostrarPrevia(d) {
    var s = d.resumo;
    var html = '<div class="resumo">' +
      '<span><b>' + s.categorias + '</b> categorias</span>' +
      '<span><b>' + s.texto + '</b> texto</span>' +
      '<span><b>' + s.voz + '</b> voz</span>' +
      '<span><b>' + s.cargos + '</b> cargos</span>' +
      (s.truncados ? '<span><b>' + s.truncados + '</b> nomes encurtados</span>' : '') +
      '</div><div class="previa">';
    d.categorias.forEach(function (c) {
      html += '<div class="cat">' + escapar(c.titulo) + '</div>';
      c.canais.forEach(function (ch) {
        html += '<div class="ch">' + (ch.tipo === "Voice" ? "🔊" : "#") + " " +
                escapar(ch.nome) + '</div>';
      });
    });
    d.sem_categoria.forEach(function (ch) {
      html += '<div class="ch">' + (ch.tipo === "Voice" ? "🔊" : "#") + " " +
              escapar(ch.nome) + '</div>';
    });
    html += '</div><div class="acoes">' +
      '<button class="sec" id="dp-imp-cancela">Fechar</button>' +
      '<button id="dp-imp-go">Importar para este servidor</button></div>' +
      '<div id="dp-imp-prog" class="sub" style="margin-top:12px"></div>';
    document.getElementById("dp-imp-previa").innerHTML = html;
    document.getElementById("dp-imp-go").addEventListener("click", importar);
    document.getElementById("dp-imp-cancela").addEventListener("click",
      function () { if (!rodando) document.getElementById("dp-imp").remove(); });
  }

  function escapar(t) {
    return String(t == null ? "" : t)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function progresso(t) {
    var el = document.getElementById("dp-imp-prog");
    if (el) el.textContent = t;
  }

  /* ---------------------------------------------------------- execução */
  function importar() {
    var srv = servidorAtual();
    if (!srv) return msg("Abra as configurações de um servidor para importar.");
    if (!previa || rodando) return;

    rodando = true;
    document.getElementById("dp-imp-go").disabled = true;
    progresso("Lendo o que já existe no servidor…");

    var criados = 0, pulados = 0, falhas = 0;
    var porNome = {}, cargosPorNome = {}, catsExistentes = [];

    function corHex(n) {
      if (!n) return null;
      return "#" + ("000000" + (n >>> 0).toString(16)).slice(-6);
    }

    // Uma chamada devolve o servidor com os canais completos. Sem isso,
    // repetir a importação duplicaria tudo que já tinha sido criado.
    api("/api/servers/" + srv + "?include_channels=true").then(function (r) {
      if (r.status === 200 && r.d) {
        (r.d.channels || []).forEach(function (c) {
          if (c && c.name) porNome[c.name] = c._id || c.id;
        });
        (r.d.roles ? Object.keys(r.d.roles) : []).forEach(function (id) {
          var nm = r.d.roles[id] && r.d.roles[id].name;
          if (nm) cargosPorNome[nm] = id;
        });
        catsExistentes = (r.d.categories || []).slice();
      }
      return seguir();
    }).catch(function () { rodando = false; msg("Não consegui ler o servidor."); });

    function seguir() {
      var total = previa.resumo.texto + previa.resumo.voz;
      if (!confirm("Serão criados até " + total + " canais, " +
            previa.resumo.categorias + " categorias e " +
            previa.resumo.cargos + " cargos.\n\n" +
            "O que já existir com o mesmo nome será reaproveitado, não " +
            "duplicado. Nada é apagado.\n\nContinuar?")) {
        rodando = false;
        document.getElementById("dp-imp-go").disabled = false;
        return;
      }
      return fazerCargos(0);
    }

    function fazerCargos(i) {
      var cargos = previa.cargos;
      if (i >= cargos.length) return fazerCanais();
      var c = cargos[i];
      progresso("Cargos… " + (i + 1) + "/" + cargos.length);
      if (cargosPorNome[c.nome]) { pulados++; return fazerCargos(i + 1); }
      return api("/api/servers/" + srv + "/roles", {corpo: {name: c.nome}})
        .then(function (r) {
          var id = r.d && (r.d.id || r.d._id);
          if (r.status !== 200 || !id) { falhas++; return; }
          criados++;
          var cor = corHex(c.cor);
          if (!cor) return;
          return api("/api/servers/" + srv + "/roles/" + id,
                     {method: "PATCH", corpo: {colour: cor}});
        })
        .catch(function () { falhas++; })
        .then(function () { return fazerCargos(i + 1); });
    }

    var fila = [], catsNovas = [];

    function fazerCanais() {
      fila = [];
      previa.categorias.forEach(function (cat) {
        cat.canais.forEach(function (ch) { fila.push({cat: cat.titulo, ch: ch}); });
      });
      previa.sem_categoria.forEach(function (ch) { fila.push({cat: null, ch: ch}); });
      return proximo(0);
    }

    function proximo(i) {
      if (i >= fila.length) return finalizar();
      var item = fila[i], ch = item.ch;
      progresso("Canais… " + (i + 1) + "/" + fila.length + "  (" + ch.nome + ")");

      var existente = porNome[ch.nome];
      if (existente) {
        pulados++;
        registrar(item.cat, existente);
        return proximo(i + 1);
      }
      var corpo = {name: ch.nome, type: ch.tipo};
      if (ch.descricao) corpo.description = ch.descricao;
      if (ch.nsfw) corpo.nsfw = true;
      return api("/api/servers/" + srv + "/channels", {corpo: corpo})
        .then(function (r) {
          var id = r.d && (r.d._id || r.d.id);
          if (r.status !== 200 || !id) { falhas++; return; }
          criados++; porNome[ch.nome] = id;
          registrar(item.cat, id);
        })
        .catch(function () { falhas++; })
        .then(function () { return proximo(i + 1); });
    }

    function registrar(titulo, id) {
      if (!titulo) return;
      var c = catsNovas.filter(function (x) { return x.title === titulo; })[0];
      if (!c) { c = {title: titulo, channels: []}; catsNovas.push(c); }
      if (c.channels.indexOf(id) < 0) c.channels.push(id);
    }

    function finalizar() {
      progresso("Organizando categorias…");
      // O PATCH substitui a lista inteira: mesclamos com as que já
      // existiam, senão a importação apagaria a organização anterior.
      var finais = catsExistentes.map(function (c) {
        return {id: c.id, title: c.title, channels: (c.channels || []).slice()};
      });
      catsNovas.forEach(function (nova) {
        var igual = finais.filter(function (x) { return x.title === nova.title; })[0];
        if (igual) {
          nova.channels.forEach(function (id) {
            if (igual.channels.indexOf(id) < 0) igual.channels.push(id);
          });
        } else {
          finais.push({id: "dp" + Math.random().toString(36).slice(2, 10),
                       title: nova.title, channels: nova.channels});
        }
      });

      return api("/api/servers/" + srv, {method: "PATCH",
                 corpo: {categories: finais}})
        .then(function (r) {
          rodando = false;
          document.getElementById("dp-imp-go").disabled = false;
          progresso("");
          if (r.status !== 200) {
            msg("Canais criados, mas não consegui gravar as categorias. " +
                "Rode de novo: o que já existe será reaproveitado.");
            return;
          }
          msg("Pronto. " + criados + " criados, " + pulados +
              " já existiam, " + finais.length + " categorias." +
              (falhas ? " " + falhas + " falharam — rode de novo para completar." : ""),
              !falhas);
        })
        .catch(function () {
          rodando = false;
          msg("Falhou ao organizar categorias. Rode de novo.");
        });
    }
  }

  /* -------------------------------------------------------- gatilho */
  // Botão flutuante só nas configurações de servidor. Detectar por texto
  // dos itens do menu é mais estável que depender de estrutura interna.
  var ROTULOS = /^(cargos|convites|banimentos|membros|vis[ãa]o geral)$/i;

  function deveMostrar() {
    if (!servidorAtual()) return false;
    var n = 0, els = document.querySelectorAll("div,span,a,button");
    for (var i = 0; i < els.length && n < 2; i++) {
      var t = (els[i].textContent || "").trim();
      if (t.length <= 24 && ROTULOS.test(t)) n++;
    }
    return n >= 2;
  }

  function tick() {
    var bt = document.getElementById("dp-imp-bt");
    if (deveMostrar()) {
      if (!bt) {
        bt = document.createElement("button");
        bt.id = "dp-imp-bt";
        bt.textContent = "Importar do Discord";
        bt.addEventListener("click", abrir);
        document.body.appendChild(bt);
      }
    } else if (bt && !document.getElementById("dp-imp")) {
      bt.remove();
    }
  }
  setInterval(tick, 1200);
})();
