/* ---------------------------------------------------------------------
   Dois Papo — painel do medidor de microfone.

   Mostra o nível captado em tempo real e permite posicionar o limiar do
   portão. A barra fica verde quando está transmitindo e apagada quando o
   portão fechou, para a pessoa enxergar o efeito enquanto ajusta.
--------------------------------------------------------------------- */
(function () {
  "use strict";
  if (!window.dpAudio) return;

  var CSS =
    '#dp-mic{margin:16px 0;padding:18px 20px;border-radius:14px;' +
      'background:linear-gradient(150deg,rgba(46,139,235,.10),' +
      'rgba(140,65,217,.10));border:1px solid rgba(140,65,217,.28);' +
      'font:14px/1.55 system-ui,-apple-system,sans-serif;color:inherit}' +
    '#dp-mic h3{margin:0 0 3px;font-size:15px;font-weight:700}' +
    '#dp-mic .sub{opacity:.7;font-size:12.5px;margin-bottom:15px}' +
    '#dp-mic .trilho{position:relative;height:16px;border-radius:8px;' +
      'background:rgba(0,0,0,.32);overflow:hidden;margin-bottom:9px}' +
    '#dp-mic .barra{position:absolute;inset:0 auto 0 0;width:0%;' +
      'background:linear-gradient(90deg,#3fb950,#8C41D9);' +
      'transition:width .06s linear,opacity .12s}' +
    '#dp-mic .barra.fechado{opacity:.22}' +
    '#dp-mic .marca{position:absolute;top:-3px;bottom:-3px;width:3px;' +
      'background:#fff;border-radius:2px;box-shadow:0 0 6px rgba(0,0,0,.7)}' +
    '#dp-mic .legenda{display:flex;justify-content:space-between;' +
      'font-size:11.5px;opacity:.6;margin-bottom:14px}' +
    '#dp-mic .situacao{font-weight:650;font-size:12.5px}' +
    '#dp-mic .situacao.on{color:#3fb950}' +
    '#dp-mic .situacao.off{opacity:.55}' +
    '#dp-mic label{display:flex;align-items:center;gap:10px;' +
      'font-size:13px;margin-top:12px}' +
    '#dp-mic input[type=range]{flex:1;accent-color:#8C41D9}' +
    '#dp-mic .val{min-width:58px;text-align:right;font-size:12px;' +
      'opacity:.75;font-variant-numeric:tabular-nums}' +
    '#dp-mic .liga{display:flex;align-items:center;gap:9px;' +
      'margin-bottom:14px;font-size:13px;cursor:pointer}' +
    '#dp-mic .liga input{accent-color:#8C41D9;width:16px;height:16px}' +
    '#dp-mic .direcao{display:flex;justify-content:space-between;font-size:11px;opacity:.55;margin:-4px 0 2px}' +
    '#dp-mic .dica{font-size:11.5px;opacity:.6;margin-top:12px;' +
      'line-height:1.5}';

  var st = document.createElement("style");
  st.id = "dp-mic-css";
  st.textContent = CSS;
  document.head.appendChild(st);

  var MIN = -80, MAX = -10;           // faixa útil do limiar, em dB
  var pct = function (db) {
    return Math.max(0, Math.min(100, ((db - (-70)) / 70) * 100));
  };

  var painel, animando = false;

  function montar(ancora) {
    painel = document.createElement("div");
    painel.id = "dp-mic";
    painel.innerHTML =
      '<h3>Sensibilidade do microfone</h3>' +
      '<div class="sub">Fique em silêncio e veja até onde a barra chega: esse é o seu ruído de fundo. Arraste o corte para a <b>direita</b> desse ponto. Depois fale e confirme que acende.</div>' +
      '<div class="trilho"><div class="barra" id="dp-barra"></div>' +
        '<div class="marca" id="dp-marca"></div></div>' +
      '<div class="legenda"><span>silêncio</span>' +
        '<span class="situacao off" id="dp-sit">sem sinal</span>' +
        '<span>alto</span></div>' +
      '<label class="liga"><input type="checkbox" id="dp-liga">' +
        '<span>Cortar o som quando eu não estiver falando</span></label>' +
      '<label><span>Corte</span>' +
        '<input type="range" id="dp-lim" min="' + MIN + '" max="' + MAX +
        '" step="1"><span class="val" id="dp-lim-v"></span></label>' +
      '<div class="direcao"><span>&#8592; deixa passar mais</span>' +
        '<span>corta mais &#8594;</span></div>' +
      '<div class="dica">O corte só vale para o que você transmite. ' +
      'Funciona junto com a supressão de ruído acima.</div>';
    ancora.parentNode.insertBefore(painel, ancora.nextSibling);

    var liga = painel.querySelector("#dp-liga");
    var lim = painel.querySelector("#dp-lim");
    liga.checked = window.dpAudio.cfg.ativo;
    lim.value = window.dpAudio.cfg.limiar;
    atualizarRotulo();

    liga.addEventListener("change", function () {
      window.dpAudio.cfg.ativo = liga.checked;
      window.dpAudio.salvar();
    });
    lim.addEventListener("input", function () {
      window.dpAudio.cfg.limiar = parseInt(lim.value, 10);
      window.dpAudio.salvar();
      atualizarRotulo();
    });

    function atualizarRotulo() {
      painel.querySelector("#dp-lim-v").textContent =
        window.dpAudio.cfg.limiar + " dB";
      painel.querySelector("#dp-marca").style.left =
        pct(window.dpAudio.cfg.limiar) + "%";
    }

    abrirMicrofone();
    if (!animando) { animando = true; animar(); }
  }

  /* --------- microfone próprio do painel, para calibrar sem chamada ----- */
  var mon = { ctx: null, analisador: null, trilhas: [], nivel: -100,
              buf: null, erro: null };

  function abrirMicrofone() {
    if (mon.ctx || !window.dpAudio || !window.dpAudio.original) return;
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) { mon.erro = "navegador sem Web Audio"; return; }
    window.dpAudio.original({ audio: true }).then(function (st) {
      if (!document.getElementById("dp-mic")) {   // painel já fechou
        st.getTracks().forEach(function (t) { t.stop(); });
        return;
      }
      mon.ctx = new Ctx();
      var src = mon.ctx.createMediaStreamSource(st);
      mon.analisador = mon.ctx.createAnalyser();
      mon.analisador.fftSize = 1024;
      mon.analisador.smoothingTimeConstant = 0.2;
      src.connect(mon.analisador);
      mon.buf = new Float32Array(mon.analisador.fftSize);
      mon.trilhas = st.getTracks();
      if (mon.ctx.state === "suspended") mon.ctx.resume().catch(function(){});
    }).catch(function (e) {
      mon.erro = (e && e.name === "NotAllowedError")
        ? "permissão de microfone negada"
        : "não foi possível abrir o microfone";
    });
  }

  // Soltar o microfone ao sair é obrigatório: senão o indicador de
  // gravação do sistema fica aceso depois de fechar as configurações.
  function fecharMicrofone() {
    mon.trilhas.forEach(function (t) { try { t.stop(); } catch (e) {} });
    if (mon.ctx) { try { mon.ctx.close(); } catch (e) {} }
    mon = { ctx: null, analisador: null, trilhas: [], nivel: -100,
            buf: null, erro: null };
  }

  function medirProprio() {
    if (!mon.analisador) return null;
    mon.analisador.getFloatTimeDomainData(mon.buf);
    var soma = 0;
    for (var i = 0; i < mon.buf.length; i++) soma += mon.buf[i] * mon.buf[i];
    var rms = Math.sqrt(soma / mon.buf.length);
    mon.nivel = rms > 0 ? 20 * Math.log10(rms) : -100;
    return mon.nivel;
  }

  function animar() {
    var painelVivo = document.getElementById("dp-mic");
    if (!painelVivo) { animando = false; fecharMicrofone(); return; }

    var e = window.dpAudio.estado;
    // Em chamada, o nível vem da cadeia real; fora dela, do microfone
    // que o painel abriu só para calibração.
    var emChamada = !!e.ctx;
    var nivel = emChamada ? e.nivel : medirProprio();
    var aberto = emChamada ? e.aberto
                           : (nivel !== null && nivel >= window.dpAudio.cfg.limiar);

    var barra = document.getElementById("dp-barra");
    var sit = document.getElementById("dp-sit");
    if (barra) {
      barra.style.width = pct(nivel === null ? -100 : nivel) + "%";
      barra.classList.toggle("fechado", !aberto);
    }
    if (sit) {
      var txt, cls;
      if (mon.erro && !emChamada) { txt = mon.erro; cls = "off"; }
      else if (nivel === null) { txt = "abrindo microfone…"; cls = "off"; }
      else if (aberto) {
        txt = emChamada
          ? "transmitindo" + (e.ganhoReal !== undefined
              ? " (ganho " + e.ganhoReal + ")" : "")
          : "acima do corte";
        cls = "on";
      }
      else { txt = "em silêncio"; cls = "off"; }
      sit.textContent = txt;
      sit.className = "situacao " + cls;
    }
    requestAnimationFrame(animar);
  }

  var ANCORAS = [
    /supress[ãa]o de ru[íi]do/i,
    /processamento de voz/i,
    /sele[çc]ionar entrada de [áa]udio/i
  ];
  var tentativas = 0, ultimoMotivo = "ainda não tentou";

  function porTexto() {
    var alvos = document.querySelectorAll("div,section,label,span,h1,h2,h3,h4");
    for (var a = 0; a < ANCORAS.length; a++) {
      for (var i = 0; i < alvos.length; i++) {
        var t = (alvos[i].textContent || "").trim();
        if (t.length > 60 || !ANCORAS[a].test(t)) continue;
        var bloco = alvos[i];
        for (var k = 0; k < 3 && bloco.parentElement; k++) {
          if (bloco.parentElement.children.length > 1) break;
          bloco = bloco.parentElement;
        }
        if (bloco && bloco.parentNode) return bloco;
      }
    }
    return null;
  }

  // Âncora de reserva: o controle de volume é um input range e está
  // comprovadamente na mesma tela. Mais confiável que procurar texto,
  // que muda conforme tradução e versão.
  function porControle() {
    var faixas = document.querySelectorAll('input[type="range"]');
    for (var i = 0; i < faixas.length; i++) {
      var f = faixas[i];
      if (f.closest("#dp-mic")) continue;
      var bloco = f;
      for (var k = 0; k < 4 && bloco.parentElement; k++) {
        bloco = bloco.parentElement;
        if (bloco.parentElement &&
            bloco.parentElement.children.length > 1) break;
      }
      if (bloco && bloco.parentNode) return bloco;
    }
    return null;
  }

  function procurar() {
    if (document.getElementById("dp-mic")) return;
    // Sem guarda de rota: as configurações abrem como modal e a URL
    // continua a do canal. A busca por texto é específica o bastante.
    var alvo = porTexto();
    if (alvo) { ultimoMotivo = "ancorado por texto"; montar(alvo); return; }
    if (!/^\/settings/.test(location.pathname)) {
      ultimoMotivo = "rótulo não encontrado e fora de /settings";
      return;
    }
    alvo = porControle();
    if (alvo) { ultimoMotivo = "ancorado no controle de volume";
                montar(alvo); return; }
    ultimoMotivo = "nenhuma âncora encontrada nesta tela";
    if (++tentativas === 40)
      console.warn("[Dois Papo] painel do microfone: " + ultimoMotivo +
        ". Rode dpDiag() para detalhes.");
  }

  // Diagnóstico: evita ficar adivinhando por que o painel não apareceu.
  window.dpDiag = function () {
    var d = {
      processamentoAtivo: !!window.dpAudio,
      painelMontado: !!document.getElementById("dp-mic"),
      rota: location.pathname,
      motivo: ultimoMotivo,
      controlesRange: document.querySelectorAll('input[type="range"]').length,
      contextoAudio: window.dpAudio && window.dpAudio.estado.ctx
                     ? "ativo" : "inativo",
      nivel: window.dpAudio ? window.dpAudio.estado.nivel : null,
      emChamada: !!(window.dpAudio && window.dpAudio.estado.ctx),
      ganhoReal: window.dpAudio ? window.dpAudio.estado.ganhoReal : null,
      cortesAplicados: window.dpAudio ? window.dpAudio.estado.cortes : null,
      config: window.dpAudio ? window.dpAudio.cfg : null
    };
    console.table(d);
    return d;
  };

  new MutationObserver(procurar).observe(document.documentElement,
    { childList: true, subtree: true });
  if (document.readyState !== "loading") procurar();
  else document.addEventListener("DOMContentLoaded", procurar);
})();
