/* ---------------------------------------------------------------------
   Dois Papo — compartilhamento de tela sob demanda.

   Numa chamada com duas pessoas transmitindo, quem só quer conversar
   recebia as duas telas ao vivo: banda e CPU gastas para assistir o que
   ninguém pediu.

   Um blur no CSS NÃO resolveria isso. O vídeo continuaria sendo baixado
   e decodificado; só ficaria embaçado na tela. A economia real vem de
   não assinar a faixa — `setSubscribed(false)` —, e aí o servidor de
   mídia para de enviar.

   O app já gerencia assinatura por visibilidade: assina quando o quadro
   entra na tela (80%) e desassina depois de 3s fora dela. O que faltava
   era uma segunda condição. O rebrand.py acrescenta uma chamada a
   `dpTelaBloqueia` nos três pontos onde o app assina, e é isso que
   este arquivo decide.

   A prévia é um quadro real, capturado numa assinatura de ~2s e depois
   reduzido a poucos pixels antes de ser ampliado de volta. A redução é
   o que garante que nada legível sobre da tela de quem transmite — um
   blur de CSS por cima de um quadro nítido ainda entrega o conteúdo a
   quem inspeciona o elemento.

   Desligar tudo: localStorage.setItem("dp_tela_off", "1")
--------------------------------------------------------------------- */
(function () {
  "use strict";
  if (localStorage.getItem("dp_tela_off")) return;

  var FONTES = {screen_share: true, screen_share_audio: true};
  var LARGURA_PREVIA = 44;      // px: reduz a isto antes de ampliar
  var ESPERA_QUADRO = 4000;     // ms para desistir da captura

  var assistindo = {};   // sid -> true, escolha do usuário
  var previas = {};      // sid -> dataURL do quadro borrado
  var capturando = {};   // sid -> true enquanto captura
  var liberados = {};    // sid -> true: deixa o app assinar (só na captura)
  var porFaixa = {};     // id da MediaStreamTrack -> elemento de mídia
  var publicacoes = {};  // sid -> publicação
  var salas = [];

  function sid(pub) {
    return (pub && (pub.trackSid || pub.sid || (pub.trackInfo &&
            pub.trackInfo.sid))) || null;
  }
  function ehTela(pub) {
    try { return !!(pub && FONTES[pub.source]); } catch (e) { return false; }
  }

  /* Consultado pelo app nos pontos em que ele assinaria. Verdadeiro =
     não assine. Precisa ser à prova de erro: uma exceção aqui deixaria
     a chamada inteira sem áudio. */
  window.dpTelaBloqueia = function (pub) {
    try {
      if (!ehTela(pub)) return false;
      var s = sid(pub);
      if (!s) return false;
      publicacoes[s] = pub;
      if (liberados[s]) return false;     // janela de captura da prévia
      return !assistindo[s];
    } catch (e) { return false; }
  };

  /* ------------------------------------------ mapa faixa -> elemento
     Descobrir a que elemento o app ligou cada faixa é o que permite
     colocar a prévia exatamente por cima do quadro certo, sem adivinhar
     por posição ou por nome do participante. */
  (function () {
    var proto = window.HTMLMediaElement && HTMLMediaElement.prototype;
    if (!proto) return;
    var d = Object.getOwnPropertyDescriptor(proto, "srcObject");
    if (!d || !d.set) return;
    Object.defineProperty(proto, "srcObject", {
      configurable: true,
      get: d.get,
      set: function (v) {
        d.set.call(this, v);
        try {
          if (v && v.getTracks) {
            var fs = v.getTracks();
            for (var i = 0; i < fs.length; i++) porFaixa[fs[i].id] = this;
          }
        } catch (e) {}
      }
    });
  })();

  function elementoDe(pub) {
    try {
      var f = pub.track && pub.track.mediaStreamTrack;
      return (f && porFaixa[f.id]) || null;
    } catch (e) { return null; }
  }

  /* ------------------------------------------------------- prévia */
  function capturar(pub) {
    var s = sid(pub);
    if (!s || capturando[s] || previas[s] || pub.kind === "audio") return;
    capturando[s] = true;
    liberados[s] = true;                 // deixa o app assinar e ligar
    try { pub.setSubscribed(true); } catch (e) {}

    var fim = Date.now() + ESPERA_QUADRO;
    (function tentar() {
      var faixa = pub.track && pub.track.mediaStreamTrack;
      var pronto = false;
      if (faixa) {
        var el = porFaixa[faixa.id];
        if (el && el.videoWidth > 0) { desenhar(s, el); pronto = true; }
      }
      if (pronto || Date.now() > fim) {
        delete liberados[s];
        delete capturando[s];
        if (!assistindo[s]) { try { pub.setSubscribed(false); } catch (e) {} }
        pintar(pub);
        return;
      }
      setTimeout(tentar, 200);
    })();
  }

  function desenhar(s, video) {
    try {
      var prop = video.videoHeight / video.videoWidth || 0.5625;
      var l = LARGURA_PREVIA, a = Math.max(1, Math.round(l * prop));
      var c = document.createElement("canvas");
      c.width = l; c.height = a;
      // reduzir a ~44px destrói a informação de verdade; o blur que vem
      // depois é só acabamento visual
      c.getContext("2d").drawImage(video, 0, 0, l, a);
      previas[s] = c.toDataURL("image/jpeg", 0.6);
    } catch (e) {}
  }

  /* ------------------------------------------------------ camada */
  function estilo() {
    if (document.getElementById("dp-tela-css")) return;
    var e = document.createElement("style");
    e.id = "dp-tela-css";
    e.textContent =
      '.dp-tela-capa{position:absolute;inset:0;z-index:5;overflow:hidden;' +
        'border-radius:inherit;display:flex;align-items:center;' +
        'justify-content:center;background:#0b1119}' +
      '.dp-tela-capa img{position:absolute;inset:0;width:100%;height:100%;' +
        'object-fit:cover;filter:blur(14px) saturate(.7) brightness(.55);' +
        'transform:scale(1.15)}' +
      '.dp-tela-capa .dp-cx{position:relative;text-align:center;' +
        'color:#e8edf6;font:500 13px system-ui,sans-serif;padding:14px;' +
        'text-shadow:0 1px 6px rgba(0,0,0,.6)}' +
      '.dp-tela-capa .dp-cx b{display:block;font-size:14.5px;' +
        'font-weight:700;margin-bottom:3px}' +
      '.dp-tela-capa .dp-cx span{display:block;opacity:.75;font-size:12px;' +
        'margin-bottom:11px}' +
      '.dp-tela-capa button{cursor:pointer;border:0;border-radius:9px;' +
        'padding:9px 20px;font:650 13px system-ui,sans-serif;color:#fff;' +
        'background:linear-gradient(100deg,#2E8BEB,#8C41D9)}' +
      '.dp-tela-parar{position:absolute;right:9px;top:9px;z-index:6;' +
        'cursor:pointer;border:0;border-radius:8px;padding:6px 12px;' +
        'font:600 12px system-ui,sans-serif;color:#e8edf6;' +
        'background:rgba(11,17,25,.72)}';
    document.head.appendChild(e);
  }

  function alvoDe(pub) {
    var el = elementoDe(pub);
    if (el && el.parentElement) return el.parentElement;
    return null;
  }

  function pintar(pub) {
    estilo();
    var s = sid(pub);
    if (!s) return;
    var alvo = alvoDe(pub);
    if (!alvo) return;
    if (getComputedStyle(alvo).position === "static")
      alvo.style.position = "relative";

    var capa = alvo.querySelector(":scope > .dp-tela-capa");
    var parar = alvo.querySelector(":scope > .dp-tela-parar");

    if (assistindo[s]) {
      if (capa) capa.remove();
      if (!parar) {
        parar = document.createElement("button");
        parar.className = "dp-tela-parar";
        parar.textContent = "Parar de assistir";
        parar.addEventListener("click", function (ev) {
          ev.stopPropagation();
          delete assistindo[s];
          try { pub.setSubscribed(false); } catch (e) {}
          pintar(pub);
        });
        alvo.appendChild(parar);
      }
      return;
    }

    if (parar) parar.remove();
    if (capa) return;

    capa = document.createElement("div");
    capa.className = "dp-tela-capa";
    if (previas[s]) {
      var img = document.createElement("img");
      img.src = previas[s];
      img.alt = "";
      capa.appendChild(img);
    }
    var cx = document.createElement("div");
    cx.className = "dp-cx";
    var b = document.createElement("b");
    b.textContent = nomeDe(pub) || "Compartilhando a tela";
    var sp = document.createElement("span");
    sp.textContent = "Pausado para poupar sua banda";
    var bt = document.createElement("button");
    bt.textContent = "Assistir";
    bt.addEventListener("click", function (ev) {
      ev.stopPropagation();
      assistindo[s] = true;
      try { pub.setSubscribed(true); } catch (e) {}
      pintar(pub);
      // o elemento só ganha stream depois que a faixa chega
      setTimeout(function () { pintar(pub); }, 1200);
    });
    cx.appendChild(b); cx.appendChild(sp); cx.appendChild(bt);
    capa.appendChild(cx);
    alvo.appendChild(capa);
  }

  function nomeDe(pub) {
    try {
      var p = pub.participant || (pub.track && pub.track.participant);
      return (p && (p.name || p.identity)) || null;
    } catch (e) { return null; }
  }

  /* ------------------------------------------------------- sala */
  function cuidar(pub) {
    if (!ehTela(pub)) return;
    var s = sid(pub);
    if (!s) return;
    publicacoes[s] = pub;
    if (assistindo[s]) return;
    if (pub.kind === "audio") {
      try { pub.setSubscribed(false); } catch (e) {}
      return;
    }
    if (!previas[s] && !capturando[s]) capturar(pub);
    else pintar(pub);
  }

  function varrer(sala) {
    try {
      sala.remoteParticipants.forEach(function (p) {
        p.trackPublications.forEach(cuidar);
      });
    } catch (e) {}
  }

  window.dpSalaNova = function (sala) {
    try {
      if (!sala || salas.indexOf(sala) >= 0) return;
      salas.push(sala);
      ["trackPublished", "trackSubscribed", "trackUnsubscribed"]
        .forEach(function (ev) {
          sala.on(ev, function (a, b) {
            try { cuidar(b && b.source ? b : a); } catch (e) {}
          });
        });
      sala.on("participantConnected", function () { varrer(sala); });
      // o quadro do app pode ser recriado a qualquer momento; repintar
      // é barato e devolve a camada quando ela some
      setInterval(function () {
        for (var s in publicacoes) {
          if (!capturando[s]) { try { pintar(publicacoes[s]); } catch (e) {} }
        }
      }, 1000);
      varrer(sala);
    } catch (e) {}
  };

  /* Nome da sala conectada — é o id do canal da chamada. Quem usa é o
     som por servidor: sem isso ele só sabe qual servidor está na tela,
     e tocaria o som errado para quem navega durante a chamada. */
  window.dpSalaNome = function () {
    for (var i = 0; i < salas.length; i++) {
      try {
        var s = salas[i];
        if (s && s.name && (s.state === "connected" || !s.state)) return s.name;
      } catch (e) {}
    }
    return null;
  };

  window.dpTela = function () {
    return {salas: salas.length, publicacoes: Object.keys(publicacoes),
            assistindo: Object.keys(assistindo),
            previas: Object.keys(previas)};
  };
})();
