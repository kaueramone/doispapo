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
      '<div class="sub">Fale normalmente e arraste o limiar até a barra ' +
      'acender só com a sua voz — não com o ruído do ambiente.</div>' +
      '<div class="trilho"><div class="barra" id="dp-barra"></div>' +
        '<div class="marca" id="dp-marca"></div></div>' +
      '<div class="legenda"><span>silêncio</span>' +
        '<span class="situacao off" id="dp-sit">sem sinal</span>' +
        '<span>alto</span></div>' +
      '<label class="liga"><input type="checkbox" id="dp-liga">' +
        '<span>Cortar o som quando eu não estiver falando</span></label>' +
      '<label><span>Limiar</span>' +
        '<input type="range" id="dp-lim" min="' + MIN + '" max="' + MAX +
        '" step="1"><span class="val" id="dp-lim-v"></span></label>' +
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

    if (!animando) { animando = true; animar(); }
  }

  function animar() {
    if (!document.getElementById("dp-mic")) { animando = false; return; }
    var e = window.dpAudio.estado;
    var barra = document.getElementById("dp-barra");
    var sit = document.getElementById("dp-sit");
    if (barra) {
      barra.style.width = pct(e.nivel) + "%";
      barra.classList.toggle("fechado", !e.aberto);
    }
    if (sit) {
      var ativo = e.ctx && e.aberto;
      sit.textContent = !e.ctx ? "microfone inativo"
                               : (e.aberto ? "transmitindo" : "em silêncio");
      sit.className = "situacao " + (ativo ? "on" : "off");
    }
    requestAnimationFrame(animar);
  }

  // Ancora abaixo do ajuste de supressão de ruído, que é onde a pessoa
  // já está mexendo em microfone.
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
    if (!/^\/settings/.test(location.pathname)) {
      ultimoMotivo = "fora das configurações";
      return;
    }
    var alvo = porTexto();
    if (alvo) { ultimoMotivo = "ancorado por texto"; montar(alvo); return; }
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
