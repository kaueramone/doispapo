/* ---------------------------------------------------------------------
   Dois Papo — processamento do microfone.

   Intercepta o getUserMedia e passa o áudio por uma cadeia de Web Audio:

     origem -> analisador (medidor) -> ganho (portão) -> destino

   O portão corta a transmissão quando o nível fica abaixo do limiar, com
   ataque rápido e liberação lenta para não picotar o fim das palavras.

   SEGURANÇA: qualquer falha devolve o stream original sem processar. Um
   erro aqui calaria o microfone, então a regra é degradar para o
   comportamento nativo em vez de arriscar.

   Desligar sem recompilar:
     localStorage.setItem("dp_audio_off","1"); location.reload();
--------------------------------------------------------------------- */
(function () {
  "use strict";

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  try { if (localStorage.getItem("dp_audio_off") === "1") return; } catch (e) {}

  var PADRAO = { ativo: true, limiar: -50, sensibilidade: 1 };
  var cfg = carregar();
  var estado = { nivel: -100, aberto: false, ctx: null, analisador: null };

  function carregar() {
    try {
      var j = JSON.parse(localStorage.getItem("dp_audio") || "{}");
      return Object.assign({}, PADRAO, j);
    } catch (e) { return Object.assign({}, PADRAO); }
  }
  function salvar() {
    try { localStorage.setItem("dp_audio", JSON.stringify(cfg)); } catch (e) {}
  }

  /* ------------------------------------------------ cadeia de processamento */
  function processar(stream) {
    var trilhas = stream.getAudioTracks();
    if (!trilhas.length) return stream;

    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return stream;

    var ctx = new Ctx();
    var origem = ctx.createMediaStreamSource(stream);
    var analisador = ctx.createAnalyser();
    analisador.fftSize = 1024;
    analisador.smoothingTimeConstant = 0.25;

    var ganho = ctx.createGain();
    ganho.gain.value = 1;

    origem.connect(analisador);
    analisador.connect(ganho);

    var destino = ctx.createMediaStreamDestination();
    ganho.connect(destino);

    estado.ctx = ctx;
    estado.analisador = analisador;

    // O navegador suspende o contexto até haver interação do usuário.
    var retomar = function () {
      if (ctx.state === "suspended") ctx.resume().catch(function () {});
    };
    retomar();
    ["click", "keydown", "touchstart"].forEach(function (ev) {
      document.addEventListener(ev, retomar, { once: true, passive: true });
    });

    /* ------------------------------------------------------ portão de ruído */
    var buf = new Float32Array(analisador.fftSize);
    var ATAQUE = 0.012;      // sobe quase imediato: não corta o início da fala
    var LIBERACAO = 0.28;    // desce devagar: evita picotar o fim das palavras
    var ESPERA_MS = 320;     // segura aberto após cair, para pausas curtas
    var caiuEm = 0;

    function medir() {
      analisador.getFloatTimeDomainData(buf);
      var soma = 0;
      for (var i = 0; i < buf.length; i++) soma += buf[i] * buf[i];
      var rms = Math.sqrt(soma / buf.length);
      var db = rms > 0 ? 20 * Math.log10(rms) : -100;
      estado.nivel = db;

      if (!cfg.ativo) {
        ganho.gain.setTargetAtTime(1, ctx.currentTime, ATAQUE);
        estado.aberto = true;
        return;
      }

      var agora = Date.now();
      if (db >= cfg.limiar) {
        caiuEm = 0;
        estado.aberto = true;
        ganho.gain.setTargetAtTime(1, ctx.currentTime, ATAQUE);
      } else {
        if (!caiuEm) caiuEm = agora;
        if (agora - caiuEm > ESPERA_MS) {
          estado.aberto = false;
          ganho.gain.setTargetAtTime(0, ctx.currentTime, LIBERACAO);
        }
      }
    }
    var relogio = setInterval(medir, 40);

    // Encerrar o contexto junto com a trilha evita vazar recurso a cada
    // entrada e saída de canal de voz.
    trilhas[0].addEventListener("ended", function () {
      clearInterval(relogio);
      try { ctx.close(); } catch (e) {}
      if (estado.ctx === ctx) { estado.ctx = null; estado.analisador = null; }
    });

    var saida = new MediaStream();
    destino.stream.getAudioTracks().forEach(function (t) { saida.addTrack(t); });
    stream.getVideoTracks().forEach(function (t) { saida.addTrack(t); });
    return saida;
  }

  /* ---------------------------------------------------------- interceptação */
  var original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = function (restricoes) {
    return original(restricoes).then(function (stream) {
      if (!restricoes || !restricoes.audio) return stream;
      try {
        return processar(stream);
      } catch (e) {
        // Degrada para o áudio nativo: melhor sem portão que sem microfone.
        console.warn("[Dois Papo] processamento de áudio desativado:", e);
        return stream;
      }
    });
  };

  window.dpAudio = {
    cfg: cfg,
    estado: estado,
    salvar: salvar,
    // getUserMedia sem o nosso processamento, para o painel medir o sinal
    // cru na calibração sem passar duas vezes pela mesma cadeia
    original: original,
    desligar: function () {
      try { localStorage.setItem("dp_audio_off", "1"); } catch (e) {}
      location.reload();
    }
  };
})();
