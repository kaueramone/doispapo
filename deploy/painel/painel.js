(function(){
"use strict";
var $ = function(s){ return document.querySelector(s); };

function api(rota, opc){
  opc = opc || {};
  opc.credentials = "same-origin";
  if(opc.corpo){
    opc.method = opc.method || "POST";
    opc.headers = {"Content-Type":"application/json"};
    opc.body = JSON.stringify(opc.corpo);
    delete opc.corpo;
  }
  return fetch(rota, opc).then(function(r){
    return r.json().catch(function(){ return {}; })
      .then(function(j){ return {status:r.status, d:j}; });
  });
}
function msg(el, texto, ok){
  el.textContent = texto;
  el.className = "msg on" + (ok ? " ok" : "");
}
function esc(t){
  return String(t == null ? "" : t)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
function dataBr(ts){
  if(!ts) return "—";
  var d = new Date(ts*1000);
  return d.toLocaleDateString("pt-BR")+" "+
         d.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"});
}

/* ------------------------------------------------------------- sessão */
function entrar(e){
  e.preventDefault();
  var b = $("#b-entrar"); b.disabled = true;
  api("/api/login",{corpo:{usuario:$("#u").value, senha:$("#p").value}})
    .then(function(r){
      if(r.status === 200){ abrirApp(r.d.trocar_senha); }
      else msg($("#m-login"), r.d.mensagem || "Não foi possível entrar.");
    })
    .catch(function(){ msg($("#m-login"),"Falha de conexão."); })
    .finally(function(){ b.disabled = false; });
}
function abrirApp(trocar){
  $("#login").style.display = "none";
  $("#app").style.display = "block";
  carregarVisao();
  if(trocar){
    aba("conta");
    msg($("#m-senha"),"Você ainda usa a senha inicial. Troque agora.");
  }
}
function sair(){
  api("/api/logout",{method:"POST"}).finally(function(){ location.reload(); });
}

/* --------------------------------------------------------------- abas */
function aba(nome){
  document.querySelectorAll(".abas button").forEach(function(b){
    b.classList.toggle("on", b.dataset.p === nome);
  });
  document.querySelectorAll(".pg").forEach(function(p){
    p.classList.toggle("on", p.id === "pg-"+nome);
  });
  ({visao:carregarVisao, acessos:carregarMetricas, fila:carregarFila,
    usuarios:carregarUsuarios, convites:carregarConvites}[nome] || function(){})();
}

/* ------------------------------------------------------------- visão */
function carregarVisao(){
  api("/api/resumo").then(function(r){
    if(r.status !== 200) return;
    var d = r.d, campos = [
      ["contas","contas criadas"], ["usuarios","perfis"],
      ["servidores","comunidades"], ["mensagens","mensagens"],
      ["fila_pendente","na fila de espera"], ["convites_livres","convites livres"],
      ["sessoes","sessões ativas"], ["banidos","banidos"]
    ];
    $("#cards").innerHTML = campos.map(function(c){
      return '<div class="c"><div class="n">'+(d[c[0]]||0)+
             '</div><div class="r">'+c[1]+'</div></div>';
    }).join("");
  });
}

/* ----------------------------------------------------------- métricas */
function barras(itens, total){
  if(!itens.length) return '<p class="vazio">Sem dados no período.</p>';
  var max = Math.max.apply(null, itens.map(function(i){ return i[1]; })) || 1;
  return itens.map(function(i){
    return '<div class="linhaB"><span class="rot" style="min-width:auto;'+
      'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+
      esc(i[0])+'</span><span class="cx" style="max-width:180px">'+
      '<span class="barra" style="display:block;width:'+
      Math.round(i[1]/max*100)+'%"></span></span>'+
      '<span class="val">'+i[1]+'</span></div>';
  }).join("");
}
function carregarMetricas(){
  var dias = $("#dias").value;
  $("#met").innerHTML = '<p class="vazio">Carregando…</p>';
  api("/api/metricas?dias="+dias).then(function(r){
    var d = r.d;
    if(d.indisponivel){
      $("#met").innerHTML = '<div class="bloco"><p class="vazio">'+
        esc(d.motivo)+'</p></div>';
      return;
    }
    $("#met").innerHTML =
      '<div class="cards">'+
        '<div class="c"><div class="n">'+d.total+'</div>'+
        '<div class="r">visitas no período</div></div>'+
        '<div class="c"><div class="n">'+d.visitantes+'</div>'+
        '<div class="r">endereços distintos</div></div>'+
      '</div>'+
      '<div class="bloco"><h3>Por dia</h3>'+barras(d.por_dia)+'</div>'+
      '<div class="bloco"><h3>Por site</h3>'+barras(d.por_host)+'</div>'+
      '<div class="bloco"><h3>Páginas mais acessadas</h3>'+barras(d.rotas)+'</div>'+
      '<div class="bloco"><h3>Códigos de resposta</h3>'+barras(d.status)+'</div>'+
      (d.erros.length ? '<div class="bloco"><h3>Erros recentes</h3><table>'+
        '<thead><tr><th>Quando</th><th>Site</th><th>Rota</th><th>Status</th>'+
        '</tr></thead><tbody>'+d.erros.map(function(e){
          return '<tr><td>'+esc(e.quando)+'</td><td>'+esc(e.host)+'</td>'+
                 '<td><code>'+esc(e.rota)+'</code></td>'+
                 '<td><span class="tag er">'+e.status+'</span></td></tr>';
        }).join("")+'</tbody></table></div>' : "");
  });
}

/* --------------------------------------------------------------- fila */
function carregarFila(){
  api("/api/fila").then(function(r){
    var it = (r.d.itens)||[];
    if(!it.length){ $("#t-fila").innerHTML =
      '<p class="vazio">Ninguém na fila ainda.</p>'; return; }
    $("#t-fila").innerHTML = '<table><thead><tr><th>#</th><th>Nome</th>'+
      '<th>E-mail</th><th>Idade</th><th>Inscrição</th><th>Situação</th>'+
      '<th></th></tr></thead><tbody>'+
      it.map(function(f,i){
        return '<tr><td>'+(i+1)+'</td><td>'+esc(f.nome)+'</td>'+
          '<td><code>'+esc(f.email)+'</code></td><td>'+esc(f.idade)+'</td>'+
          '<td>'+dataBr(f.em)+'</td><td>'+
          (f.convidado ? '<span class="tag ok">convidado</span>'
                       : '<span class="tag al">aguardando</span>')+'</td>'+
          '<td style="white-space:nowrap">'+
          (f.convidado ? '<button class="ac" data-copiar="'+esc(f.codigo)+
                         '">copiar link</button>'
                       : '<button class="ac" data-convidar="'+esc(f.email)+
                         '">convidar</button>')+
          '<button class="ac perigo" data-remfila="'+esc(f.email)+
          '">remover</button></td></tr>';
      }).join("")+'</tbody></table>';
  });
}

/* ----------------------------------------------------------- usuários */
function carregarUsuarios(){
  api("/api/usuarios").then(function(r){
    var it = (r.d.itens)||[];
    if(!it.length){ $("#t-users").innerHTML =
      '<p class="vazio">Nenhuma conta ainda.</p>'; return; }
    $("#t-users").innerHTML = '<table><thead><tr><th>Usuário</th>'+
      '<th>E-mail</th><th>Convites</th><th>Sessões</th><th>Situação</th>'+
      '<th></th></tr></thead><tbody>'+
      it.map(function(u){
        return '<tr><td>'+esc(u.usuario||"—")+'</td>'+
          '<td><code>'+esc(u.email)+'</code></td>'+
          '<td>'+u.convites_gerados+' / '+u.cota+
          ' <button class="ac" data-cota="'+esc(u.id)+'" data-atual="'+
          u.cota+'">ajustar</button></td>'+
          '<td>'+u.sessoes+(u.sessoes ? ' <button class="ac" data-sess="'+
            esc(u.id)+'">encerrar</button>' : '')+'</td>'+
          '<td>'+(u.banido ? '<span class="tag er">banido</span>'
                           : '<span class="tag ok">ativo</span>')+'</td>'+
          '<td style="white-space:nowrap">'+
          '<button class="ac" data-banir="'+esc(u.id)+'" data-est="'+
            (u.banido?"1":"0")+'">'+(u.banido?"reativar":"banir")+'</button>'+
          '<button class="ac perigo" data-remuser="'+esc(u.id)+
            '" data-nome="'+esc(u.email)+'">excluir</button></td></tr>';
      }).join("")+'</tbody></table>';
  });
}

/* ----------------------------------------------------------- convites */
function carregarConvites(){
  api("/api/convites").then(function(r){
    var it = (r.d.itens)||[];
    if(!it.length){ $("#t-conv").innerHTML =
      '<p class="vazio">Nenhum convite.</p>'; return; }
    $("#t-conv").innerHTML = '<table><thead><tr><th>Código</th><th>Criado por</th>'+
      '<th>Origem</th><th>Situação</th><th></th></tr></thead><tbody>'+
      it.map(function(c){
        return '<tr><td><code>'+esc(c.codigo)+'</code></td>'+
          '<td>'+esc(c.criado_por_nome||c.criado_por||"—")+'</td>'+
          '<td>'+esc(c.origem||"—")+'</td>'+
          '<td>'+(c.usado ? '<span class="tag">usado</span>'
                          : '<span class="tag ok">livre</span>')+'</td>'+
          '<td style="white-space:nowrap">'+
          (c.usado ? '' : '<button class="ac" data-copiar="'+esc(c.codigo)+
            '">copiar link</button><button class="ac perigo" data-remconv="'+
            esc(c.codigo)+'">remover</button>')+'</td></tr>';
      }).join("")+'</tbody></table>';
  });
}

/* ------------------------------------------------------------- ações */
document.addEventListener("click", function(e){
  var b = e.target.closest("button"); if(!b) return;

  if(b.dataset.p) return aba(b.dataset.p);

  if(b.dataset.copiar){
    navigator.clipboard.writeText(
      "https://chat.doispapo.com/login/create?invite="+b.dataset.copiar);
    var t = b.textContent; b.textContent = "copiado!";
    setTimeout(function(){ b.textContent = t; }, 1600);
    return;
  }
  if(b.dataset.convidar){
    b.disabled = true;
    api("/api/fila/convidar",{corpo:{email:b.dataset.convidar}})
      .then(function(r){
        if(r.status===200) navigator.clipboard.writeText(r.d.link);
        carregarFila();
      });
    return;
  }
  if(b.dataset.remfila){
    if(!confirm("Remover "+b.dataset.remfila+" da fila?")) return;
    api("/api/fila/remover",{corpo:{email:b.dataset.remfila}})
      .then(carregarFila);
    return;
  }
  if(b.dataset.cota){
    var novo = prompt("Quantos convites esta conta pode gerar no total?",
                      b.dataset.atual);
    if(novo === null) return;
    novo = parseInt(novo,10);
    if(isNaN(novo)||novo<0) return alert("Valor inválido.");
    api("/api/usuarios/cota",{corpo:{id:b.dataset.cota, limite:novo}})
      .then(carregarUsuarios);
    return;
  }
  if(b.dataset.sess){
    if(!confirm("Encerrar todas as sessões desta conta?")) return;
    api("/api/usuarios/sessoes",{corpo:{id:b.dataset.sess}})
      .then(carregarUsuarios);
    return;
  }
  if(b.dataset.banir){
    var banindo = b.dataset.est === "0";
    if(banindo && !confirm("Banir esta conta? As sessões serão encerradas."))
      return;
    api("/api/usuarios/banir",{corpo:{id:b.dataset.banir, banir:banindo}})
      .then(carregarUsuarios);
    return;
  }
  if(b.dataset.remuser){
    if(prompt("Excluir permanentemente "+b.dataset.nome+
              "?\n\nIsto não pode ser desfeito. Digite REMOVER para confirmar.")
        !== "REMOVER") return;
    api("/api/usuarios/remover",
        {corpo:{id:b.dataset.remuser, confirmacao:"REMOVER"}})
      .then(function(){ carregarUsuarios(); carregarVisao(); });
    return;
  }
  if(b.dataset.remconv){
    if(!confirm("Remover este convite?")) return;
    api("/api/convites/remover",{corpo:{codigo:b.dataset.remconv}})
      .then(carregarConvites);
    return;
  }
});

/* ------------------------------------------------------------ ligação */
$("#f-login").addEventListener("submit", entrar);
$("#b-sair").addEventListener("click", sair);
$("#dias").addEventListener("change", carregarMetricas);
$("#b-gerar").addEventListener("click", function(){
  api("/api/convites/criar",{corpo:{quantidade:parseInt($("#qtd").value,10)||1}})
    .then(function(r){
      if(r.status===200){
        msg($("#m-conv"), "Gerado: "+r.d.codigos.join(", "), true);
        carregarConvites();
      }
    });
});
$("#f-senha").addEventListener("submit", function(e){
  e.preventDefault();
  api("/api/senha",{corpo:{atual:$("#s1").value, nova:$("#s2").value}})
    .then(function(r){
      msg($("#m-senha"), r.d.mensagem || "Erro.", r.status===200);
      if(r.status===200) setTimeout(function(){ location.reload(); }, 1800);
    });
});

api("/api/sessao").then(function(r){
  if(r.d && r.d.autenticado) abrirApp(r.d.trocar_senha);
});
})();
