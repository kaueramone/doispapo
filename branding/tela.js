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

  /* Quantas capturas de prévia já falharam, e quando pode tentar de novo.

     Sem isto a captura vira laço: ela só grava `previas[s]` quando
     consegue um quadro, então uma falha deixa a condição de tentar
     verdadeira para sempre. Enquanto `cuidar` só rodava em evento isso
     passava batido; com a varredura periódica virou assinatura ligando e
     desligando a cada poucos segundos, e a tela não aparecia para
     ninguém.

     A capa NÃO depende da prévia: sem imagem ela ainda mostra o aviso e o
     botão de assistir. Desistir é aceitável; insistir não é. */
  var tentativas = {};   // sid -> capturas falhas
  var proxima = {};      // sid -> instante em que pode tentar de novo
  var MAX_TENTATIVAS = 3;
  var RECUO_MS = 8000;

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
  function podeCapturar(s) {
    if (previas[s] || capturando[s]) return false;
    if ((tentativas[s] || 0) >= MAX_TENTATIVAS) return false;
    if (proxima[s] && Date.now() < proxima[s]) return false;
    /* Com a aba escondida nao adianta tentar: desde que o adaptiveStream
       existe, o servidor para de mandar video nesse estado e o elemento
       nunca ganha um quadro. Sem esta linha as tres tentativas seriam
       gastas a toa e a previa nao voltaria mais nesta sessao. */
    if (document.hidden) return false;
    return true;
  }

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
        if (pronto) {
          delete tentativas[s];
          delete proxima[s];
        } else {
          tentativas[s] = (tentativas[s] || 0) + 1;
          proxima[s] = Date.now() + RECUO_MS * tentativas[s];
        }
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
          // Simetrico ao botao de assistir: solta o audio junto, senao a
          // faixa de som continuaria assinada com a imagem ja parada.
          marcarAssistido(pub, false);
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
      marcarAssistido(pub, true);
      pintar(pub);
      // o elemento só ganha stream depois que a faixa chega
      setTimeout(function () { pintar(pub); }, 1200);
    });
    cx.appendChild(b); cx.appendChild(sp); cx.appendChild(bt);
    capa.appendChild(cx);
    alvo.appendChild(capa);
  }

  /* Uma tela compartilhada sao DUAS publicacoes: o video e, quando quem
     transmite marca "compartilhar audio", uma faixa de audio separada,
     com sid proprio.

     Marcar so a do video deixava a do audio para sempre bloqueada -- o
     cuidar() desassina audio de tela enquanto o sid DELE nao estiver em
     `assistindo`, e esse sid nunca era marcado. Resultado: ninguem ouvia
     o som de tela nenhuma, e o problema nao aparecia na imagem, que
     funcionava normalmente.

     Aqui as duas andam juntas, ligadas pelo participante. */
  /* De quem e esta publicacao.

     `RemoteTrackPublication` NAO tem propriedade `participant` -- conferido
     no bundle, `this.participant =` nao existe. E `pub.track.participant`
     so vale quando a faixa esta assinada, que e exatamente o que ainda nao
     aconteceu quando precisamos disto.

     Sobra procurar na sala, que e onde a relacao de fato mora. Sem isto a
     irma de audio nunca era encontrada e o som de tela seguia mudo mesmo
     depois de clicar em assistir. */
  function participanteDe(pub) {
    var alvo = sid(pub);
    if (!alvo) return null;
    for (var i = 0; i < salas.length; i++) {
      var achado = null;
      try {
        salas[i].remoteParticipants.forEach(function (p) {
          if (achado) return;
          p.trackPublications.forEach(function (q) {
            if (!achado && sid(q) === alvo) achado = p;
          });
        });
      } catch (e) {}
      if (achado) return achado;
    }
    return null;
  }

  function irmaDeAudio(pub) {
    try {
      var p = (pub && pub.participant) ||
              (pub && pub.track && pub.track.participant) ||
              participanteDe(pub);
      if (!p || !p.getTrackPublication) return null;
      return p.getTrackPublication("screen_share_audio") || null;
    } catch (e) { return null; }
  }

  function marcarAssistido(pub, ligado) {
    try {
      var lista = [pub, irmaDeAudio(pub)];
      for (var i = 0; i < lista.length; i++) {
        var p = lista[i];
        if (!p) continue;
        var k = sid(p);
        if (!k) continue;
        publicacoes[k] = p;
        if (ligado) {
          assistindo[k] = true;
          try { p.setSubscribed(true); } catch (e) {}
        } else {
          delete assistindo[k];
          try { p.setSubscribed(false); } catch (e) {}
        }
      }
    } catch (e) {}
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
    if (podeCapturar(s)) capturar(pub);
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

      /* Varrer ao CONECTAR, e não só aqui.

         Este gancho roda no construtor da sala, antes de haver conexão:
         `remoteParticipants` está vazio e a varredura não encontra nada.
         E `participantConnected` só dispara para quem chega DEPOIS de
         você. Quem já estava compartilhando a tela quando você entrou não
         era visto por ninguém: sem capa, sem prévia e sem assinatura --
         um quadro vazio, sem nem o aviso de "assistir" para clicar. */
      sala.on("connected", function () {
        // Passadas pontuais, não varredura recorrente.
        //
        // A versão anterior varria a cada segundo, e isso transformou uma
        // captura que falha num laço: `capturar` só grava a prévia quando
        // consegue o quadro, então a condição de tentar continuava
        // verdadeira e a assinatura ficava ligando e desligando -- a tela
        // não aparecia para ninguém. O recuo em `podeCapturar` corrige a
        // causa; aqui reduzimos a superfície de qualquer jeito.
        varrer(sala);
        setTimeout(function () { varrer(sala); }, 1500);
        setTimeout(function () { varrer(sala); }, 5000);
      });

      /* Voltar para a aba e um bom momento para tentar de novo: e o
         instante em que o video volta a chegar. */
      document.addEventListener("visibilitychange", function () {
        if (!document.hidden) varrer(sala);
      });

      // O quadro do app pode ser recriado a qualquer momento; repintar é
      // barato e devolve a camada quando ela some. A varredura vai junto:
      // é a rede que apanha qualquer publicação que nenhum evento trouxe.
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

  /* Marca uma tela como assistida por fora do fluxo normal.

     Existe para o quadro destacado em janela propria: ele sai da grade, e
     sem isto o dpTelaBloqueia continuaria recusando a assinatura -- a
     janela nova abriria preta. Recebe o sid da faixa, nao a publicacao,
     porque quem chama e o cliente compilado, do outro lado da injecao. */
  window.dpTelaAssistir = function (s, ligado) {
    try {
      if (!s) return;
      var pub = publicacoes[s];
      if (pub) {
        marcarAssistido(pub, ligado);
      } else if (ligado) {
        assistindo[s] = true;      // ainda nao vimos a publicacao
      } else {
        delete assistindo[s];
      }
    } catch (e) {}
  };

  window.dpTela = function () {
    return {salas: salas.length, publicacoes: Object.keys(publicacoes),
            assistindo: Object.keys(assistindo),
            previas: Object.keys(previas)};
  };
})();
