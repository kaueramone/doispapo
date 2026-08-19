/* Guarda de integridade — PRECISA ser o primeiro script injetado.
   Se um HTML truncado for guardado em cache, os blocos seguintes viram
   texto visível na tela e param de executar. Uma verificação que morasse
   num bloco posterior seria vítima da mesma quebra que deveria consertar,
   então ela vive aqui, antes de tudo que pode falhar. */
(function(){
  "use strict";
  var MARCADOR = "dp-js-marca";   // id do ÚLTIMO bloco injetado

  function limparERecarregar(motivo){
    var chave = "dp_recuperado";
    try{
      if(sessionStorage.getItem(chave) === motivo) return;  // evita laço
      sessionStorage.setItem(chave, motivo);
    }catch(e){}
    var tarefas = [];
    if(window.caches) tarefas.push(caches.keys().then(function(ks){
      return Promise.all(ks.map(function(k){ return caches.delete(k); }));
    }));
    if(navigator.serviceWorker) tarefas.push(
      navigator.serviceWorker.getRegistrations().then(function(rs){
        return Promise.all(rs.map(function(r){ return r.unregister(); }));
      }));
    Promise.all(tarefas)["catch"](function(){}).then(function(){
      location.reload();
    });
  }
  window.dpLimpar = limparERecarregar;

  function verificar(){
    if(document.getElementById(MARCADOR)) return;   // página íntegra
    console.warn("[Dois Papo] página incompleta em cache; limpando.");
    limparERecarregar("integridade");
  }

  /* Roda depois que o analisador terminou o HTML, quando o marcador
     final já existiria numa página íntegra. */
  if(document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", verificar);
  else
    setTimeout(verificar, 0);
})();
