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

    // O atributo trackref vira "[object Object]" ao ser serializado. Se o
    // framework também tiver atribuído como propriedade, o objeto real
    // está lá — e com ele o participante.
    function espiar(obj, prof) {
      if (obj === null || obj === undefined) return obj;
      var t = typeof obj;
      if (t !== "object") return t === "function" ? "<função>" : obj;
      if (prof > 2) return "<...>";
      var out = {};
      var chaves = Object.keys(obj).slice(0, 14);
      for (var i = 0; i < chaves.length; i++) {
        try { out[chaves[i]] = espiar(obj[chaves[i]], prof + 1); }
        catch (e) { out[chaves[i]] = "<erro>"; }
      }
      return out;
    }

    var mids = document.querySelectorAll("audio");
    var lista = [];
    for (var i = 0; i < mids.length; i++) {
      var m = mids[i];
      var proprias = Object.keys(m).slice(0, 20);
      var faixa = m.srcObject && m.srcObject.getAudioTracks
                  ? m.srcObject.getAudioTracks()[0] : null;
      lista.push({
        fonte: m.getAttribute("data-lk-source"),
        local: m.getAttribute("data-lk-local-participant"),
        idDoFluxo: m.srcObject ? m.srcObject.id : null,
        idDaFaixa: faixa ? faixa.id : null,
        rotuloDaFaixa: faixa ? faixa.label : null,
        propriedadesProprias: proprias,
        trackref: espiar(m.trackref, 0),
        nivel: (function () {
          var r = (a.remotos || []).filter(function (x) {
            return m.srcObject && x.stream === m.srcObject; })[0];
          return r ? Math.round(r.nivel) : null;
        })()
      });
    }
    var r = { elementos: lista, meuNivel: a.estado ? Math.round(a.estado.nivel) : null };
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
  var meuNome = null, meuUid = null, tokenSessao = null;

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
      .then(function (u) {
        if (!u) return;
        if (u.username) meuNome = u.username;
        // o id é o que casa com data-dp-uid no quadro do grid; o nome
        // só serve para a lista lateral
        if (u._id || u.id) meuUid = u._id || u.id;
      })
      .catch(function () {});
  }

  var estiloLuz = document.createElement("style");
  estiloLuz.textContent =
    /* dp-fala é carimbada pelo próprio app no quadro do grid, com o
       mesmo valor que ele usa para o indicador nativo (rebrand.py,
       seção 1h). No grid não há adivinhação: quem diz quem está
       falando é quem já sabe. */
    ".dp-falando{position:relative}" +
    ".vc_tile.dp-falando::after{border-radius:14px;inset:-2px}" +
    /* Nada a recolorir: o indicador nativo do quadro foi desligado no
       bundle (rebrand.py). Ele desenhava com o tempo do app, atrasado,
       por cima da nossa luz — duas luzes em ritmos diferentes no mesmo
       quadro leem como defeito. */
    ".dp-falando::after{content:'';position:absolute;inset:-3px;" +
      "border-radius:12px;border:2px solid #3fb950;" +
      "box-shadow:0 0 10px rgba(63,185,80,.65);pointer-events:none;" +
      "animation:dp-pulso .9s ease-in-out infinite}" +
    "@keyframes dp-pulso{0%,100%{opacity:1}50%{opacity:.55}}" +
    "@media(prefers-reduced-motion:reduce){" +
      ".dp-falando::after{animation:none}}";
  document.head.appendChild(estiloLuz);

  /* ---------------- remoção da luz nativa (duplicada) ----------------- */
  /* Comparando o bloco em silêncio e falando, o estado de fala acrescenta
     exatamente estas quatro classes. Retirá-las devolve o visual de
     silêncio, deixando a indicação por conta do nosso anel.

     Sem observador de mutação: a tentativa anterior vigiava o documento
     inteiro e varria os descendentes de cada nó inserido, o que travava a
     interface ao abrir um servidor. Aqui a limpeza acontece no laço que
     já roda, sobre os blocos que já foram localizados — poucas operações
     por ciclo, em vez de milhares por renderização.

     Efeito colateral desejado: em quem não conseguimos mapear, a luz
     nativa permanece. Melhor um indicador lento que nenhum.

     Desligar: localStorage.setItem("dp_nativa","1"); location.reload();  */
  var CLASSE_BLOCO = "eQVZMd";   // bloco do participante na lista lateral
  var CLASSES_FALA = ["dKGhWu", "fXciza", "hgBSwO", "GrQgU"];
  var manterNativa = false;
  try { manterNativa = localStorage.getItem("dp_nativa") === "1"; } catch (e) {}

  /* dKGhWu é utilitária: nos quadros do grid ela está presente mesmo em
     silêncio, então ali é estrutural e removê-la desarrumaria o layout.
     Só sai da lista lateral, onde de fato acompanha o estado de fala. */
  function limparNativa(bloco) {
    if (manterNativa || !bloco || !bloco.classList) return;
    var lateral = bloco.classList.contains(CLASSE_BLOCO);
    for (var i = 0; i < CLASSES_FALA.length; i++) {
      var c = CLASSES_FALA[i];
      if (c === "dKGhWu" && !lateral) continue;
      if (bloco.classList.contains(c)) bloco.classList.remove(c);
    }
  }

  /* O mesmo participante aparece em dois lugares: na lista lateral do
     canal e no grid central. Ambos precisam acender.

     O mapa é remontado a cada 500 ms, não a cada ciclo de 40 ms: varrer
     todos os spans 25 vezes por segundo, uma vez por participante, é
     justamente o tipo de custo que travou a interface antes. Blocos não
     surgem e somem nesse ritmo. */
  var mapaBlocos = {}, mapaEm = 0;

  function atualizarMapaBlocos() {
    var agora = Date.now();
    if (agora - mapaEm < 500) return;
    mapaEm = agora;
    var novo = {};

    /* Lista lateral: nome em <span>, avatar em <svg> irmão.
       O `closest` NÃO é detalhe. Sem ele a varredura casa qualquer
       elemento da página cujo texto seja o nome do participante — e o
       nome de quem fala aparece em todas as mensagens do histórico do
       chat. O resultado era o histórico inteiro acendendo de verde. */
    var spans = document.querySelectorAll("." + CLASSE_BLOCO + " span");
    for (var i = 0; i < spans.length; i++) {
      var t = (spans[i].textContent || "").trim();
      if (!t || t.length > 40) continue;
      var bloco = spans[i].parentElement;
      if (!bloco || !bloco.querySelector("svg")) continue;
      if (!bloco.closest("." + CLASSE_BLOCO)) continue;
      (novo[t] = novo[t] || []).push(bloco);
    }

    /* O grid não entra mais neste mapa. Casar o nome do participante
       com o texto do quadro era frágil de origem: o mesmo nome aparece
       no histórico do chat, nas menções e nas notificações de entrada
       na chamada. Agora o próprio app carimba `dp-fala` no quadro, com
       o estado que ele já calcula — o contorno é só CSS. */

    mapaBlocos = novo;
  }

  function blocosDe(nome) { return (nome && mapaBlocos[nome]) || []; }
  function meusBlocos() {
    return quadrosDe(meuUid).concat(blocosDe(meuNome));
  }

  /* ---- de quem é cada fluxo: o cliente só vê o id da faixa; quem sabe
     o dono é o servidor, que recebe isso pelos webhooks do LiveKit ---- */
  var faixas = {};          // TR_xxx -> { participante, fonte }
  var nomes = {};           // idUsuario -> nome
  /* Dois limiares e um tempo de espera. Um limiar só faz a luz piscar
     em cada respiro e sílaba: o nível cruza a linha dezenas de vezes por
     frase. Liga em -63, só desliga abaixo de -68 e nunca antes de 280ms
     — acende na hora e larga com calma. */
  var LIMIAR_REMOTO = -63;
  var LIMIAR_SOLTA = -68;
  var SEGURA_MS = 280;

  var estadoFala = {};
  function decidirFala(chave, nivel, liga, solta) {
    if (liga === undefined) { liga = LIMIAR_REMOTO; solta = LIMIAR_SOLTA; }
    var e = estadoFala[chave] || (estadoFala[chave] = {on: false, ate: 0});
    var agora = Date.now();
    if (nivel >= liga) { e.on = true; e.ate = agora + SEGURA_MS; }
    else if (e.on && agora >= e.ate && nivel < solta) { e.on = false; }
    return e.on;
  }

  /* Quadros do grid, achados pelo identificador que o app carimba
     (rebrand.py, seção 1h) — sem casar texto, sem depender de classe
     gerada pelo empacotador. */
  function quadrosDe(uid) {
    if (!uid) return [];
    try {
      return Array.prototype.slice.call(
        document.querySelectorAll('[data-dp-uid="' + uid + '"]'));
    } catch (e) { return []; }
  }

  function buscarFaixas() {
    fetch(API + "/faixas", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) { faixas = d.faixas || {}; })
      .catch(function () {});
  }
  buscarFaixas();
  setInterval(buscarFaixas, 15000);

  function nomeDe(id) {
    if (!id) return null;
    if (nomes[id] !== undefined) return nomes[id];
    if (!tokenSessao) return null;
    nomes[id] = null;                      // evita repetir a consulta
    _fetch("/api/users/" + id, { headers: { "X-Session-Token": tokenSessao } })
      .then(function (r) { return r.json(); })
      .then(function (u) { if (u && u.username) nomes[id] = u.username; })
      .catch(function () {});
    return null;
  }

  function luzDosOutros() {
    var a = window.dpAudio;
    if (!a || !a.remotos) return;
    for (var i = 0; i < a.remotos.length; i++) {
      var r = a.remotos[i];
      var fx = r.stream.getAudioTracks ? r.stream.getAudioTracks()[0] : null;
      if (!fx) continue;
      var info = faixas[fx.id];
      if (!info || (info.fonte || "").toUpperCase() !== "MICROPHONE") continue;
      var uid = info.participante;
      var alvos = quadrosDe(uid);
      var nome = nomeDe(uid);
      if (nome) alvos = alvos.concat(blocosDe(nome));
      if (!alvos.length) continue;
      var falando = decidirFala(uid, r.nivel);
      for (var b = 0; b < alvos.length; b++) {
        limparNativa(alvos[b]);
        alvos[b].classList.toggle("dp-falando", falando);
      }
    }
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
    // independe do portão estar ligado: a luz indica nível de voz.
    // Mesmo amortecimento dos outros, ancorado no limiar do portão:
    // sem ele a própria luz pisca a cada sílaba.
    var falando = decidirFala("eu", a.estado.nivel,
                              a.cfg.limiar, a.cfg.limiar - 5);
    var blocos = meusBlocos();
    for (var i = 0; i < blocos.length; i++) {
      limparNativa(blocos[i]);
      blocos[i].classList.toggle("dp-falando", falando);
    }
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
  // Isolamento por função: uma exceção em qualquer delas parava o ciclo
  // inteiro a cada 40ms — foi o que apagou o anel quando CLASSE_BLOCO
  // ficou indefinida, sem nenhum sinal além do console.
  function protegido(nome, fn) {
    try { fn(); }
    catch (e) {
      if (!protegido[nome]) {
        protegido[nome] = true;          // avisa uma vez, não 25x/s
        console.warn("[Dois Papo] falha em " + nome + ":", e);
      }
    }
  }
  setInterval(function () {
    protegido("mapa", atualizarMapaBlocos);
    protegido("luzLocal", luzDeFala);
    protegido("luzOutros", luzDosOutros);
  }, 40);
  // Amortecido: sem isso o observador dispara uma varredura de botões por
  // mutação, e abrir um servidor gera centenas delas de uma vez. Foi esse
  // padrão que travou a interface na tentativa anterior.
  var pendente = null;
  new MutationObserver(function () {
    if (pendente) return;
    pendente = setTimeout(function () { pendente = null; entrarDireto(); }, 150);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
