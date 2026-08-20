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
  var t = document.querySelector('[name="cf-turnstile-response"]');
  api("/api/login",{corpo:{usuario:$("#u").value, senha:$("#p").value,
                           turnstile: t ? t.value : ""}})
    .then(function(r){
      if(r.status === 200){ abrirApp(r.d.trocar_senha); }
      else msg($("#m-login"), r.d.mensagem || "Não foi possível entrar.");
    })
    .catch(function(){ msg($("#m-login"),"Falha de conexão."); })
    .finally(function(){
      b.disabled = false;
      // o token do Turnstile é de uso único: renova para a próxima tentativa
      if(window.turnstile) try{ turnstile.reset(); }catch(e){}
    });
}
function abrirApp(trocar){
  $("#login").style.display = "none";
  $("#app").style.display = "grid";
  api("/api/sessao").then(function(r){
    if(r.d && r.d.usuario) $("#su").value = r.d.usuario;
  });
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
    usuarios:carregarUsuarios, convites:carregarConvites,
    feedback:carregarFeedback, novidades:carregarNovidades,
    consumo:carregarConsumo
   }[nome] || function(){})();
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
  api("/api/senha",{corpo:{atual:$("#s1").value, nova:$("#s2").value,
                           usuario:$("#su").value}})
    .then(function(r){
      msg($("#m-senha"), r.d.mensagem || "Erro.", r.status===200);
      if(r.status===200) setTimeout(function(){ location.reload(); }, 1800);
    });
});

  /* ------------------------------------------------------------ consumo */
function gb(b){
  if(!b) return "0 GB";
  var g = b/1073741824;
  return (g >= 10 ? g.toFixed(0) : g.toFixed(2)) + " GB";
}

function carregarConsumo(){
  api("/api/consumo?dias="+encodeURIComponent($("#c-dias").value))
    .then(function(r){
      var d = r.d || {};
      if(!d.amostras){
        $("#c-cards").innerHTML = "";
        $("#c-dias-tab").innerHTML =
          '<p class="vazio">Ainda não há amostras. A coleta roda a cada '+
          'minuto e começou agora.</p>';
        $("#c-comunidades").innerHTML = "";
        return;
      }
      var m = d.medido||{}, dec = d.decisao||{};
      $("#c-cards").innerHTML = [
        ["<b>"+gb(m.total_bytes)+"</b>", "no período (medido)"],
        ["<b>"+gb(m.por_dia_bytes)+"</b>", "por dia"],
        ["<b>"+gb(m.projecao_mes_bytes)+"</b>", "projeção de 30 dias"],
        ["<b>"+Math.round(dec.minutos_chamada_por_dia||0)+"</b>", "min de chamada/dia"],
        ["<b>"+(dec.pico_faixas_video||0)+"</b>", "pico de faixas de vídeo"],
        ["<b>"+(dec.qualidade_media!=null?dec.qualidade_media.toFixed(2):"—")+"</b>",
         "qualidade média do SFU"]
      ].map(function(c){
        return '<div class="c"><div class="n">'+c[0].replace(/<\/?b>/g,"")+
               '</div><div class="r">'+c[1]+'</div></div>';
      }).join("");

      var dias = d.dias||[];
      $("#c-dias-tab").innerHTML = !dias.length ? '<p class="vazio">Sem dados.</p>' :
        '<table><thead><tr><th>Dia</th><th>Entrada</th><th>Saída</th>'+
        '<th>Total</th><th>Min. com chamada</th></tr></thead><tbody>'+
        dias.map(function(x){
          return '<tr><td>'+esc(x.dia)+'</td><td>'+gb(x.entrada)+'</td><td>'+
                 gb(x.saida)+'</td><td>'+gb(x.entrada+x.saida)+'</td><td>'+
                 x.minutos+'</td></tr>';
        }).join("")+'</tbody></table>';

      var com = d.estimado_por_comunidade||[];
      $("#c-comunidades").innerHTML = !com.length ? '<p class="vazio">Sem chamadas no período.</p>' :
        com.map(function(c){
          return '<div style="margin-bottom:14px">'+
            '<div class="flex" style="gap:8px;align-items:center">'+
              '<b>'+esc(c.comunidade)+'</b>'+
              '<span class="tag">~'+gb(c.bytes)+'</span>'+
              '<span class="sp"></span>'+
              '<small>'+c.minutos+' min com chamada</small>'+
            '</div>'+
            '<table><tbody>'+c.canais.map(function(x){
              return '<tr><td>'+esc(x.nome)+'</td><td>~'+gb(x.bytes)+
                     '</td><td><small>'+x.minutos+' min</small></td></tr>';
            }).join("")+'</tbody></table></div>';
        }).join("");
    });
}

$("#c-dias").addEventListener("change", carregarConsumo);

/* --------------------------------------------------------- comentários */
var ESTADOS = {recebido:"Recebido", analisando:"Em análise",
               resolvido:"Resolvido", recusado:"Recusado"};
var TIPOS = {sugestao:"sugestão", comentario:"comentário", bug:"erro"};

function carregarFeedback(){
  var q = "?tipo="+encodeURIComponent($("#f-tipo").value)+
          "&estado="+encodeURIComponent($("#f-estado").value);
  api("/api/feedback"+q).then(function(r){
    var it = (r.d.itens)||[];
    if(!it.length){ $("#t-feedback").innerHTML =
      '<p class="vazio">Nada enviado ainda.</p>'; return; }
    $("#t-feedback").innerHTML = it.map(function(f){
      return '<div class="bloco" style="margin-bottom:12px">'+
        '<div class="flex" style="gap:8px;align-items:center">'+
          '<span class="tag">'+esc(TIPOS[f.tipo]||f.tipo)+'</span>'+
          '<span class="tag '+(f.estado==="resolvido"?"ok":
             f.estado==="recusado"?"perigo":"al")+'">'+
             esc(ESTADOS[f.estado]||f.estado)+'</span>'+
          '<b>'+esc(f.titulo)+'</b>'+
          '<span class="sp"></span>'+
          '<small>'+esc((f.autor||{}).nome)+' · '+dataBr(f.em)+'</small>'+
        '</div>'+
        '<p style="white-space:pre-wrap;margin:10px 0">'+esc(f.texto)+'</p>'+
        '<label for="r-'+f.id+'">Resposta</label>'+
        '<textarea id="r-'+f.id+'" rows="2">'+esc(f.resposta||"")+'</textarea>'+
        '<div class="flex" style="margin-top:8px;gap:8px;align-items:center">'+
          '<select data-estado="'+f.id+'">'+
            Object.keys(ESTADOS).map(function(k){
              return '<option value="'+k+'"'+(k===f.estado?" selected":"")+
                     '>'+ESTADOS[k]+'</option>'; }).join("")+
          '</select>'+
          '<button class="ac" data-responder="'+f.id+'">Salvar</button>'+
        '</div></div>';
    }).join("");
  });
}

/* ----------------------------------------------------------- novidades */
function carregarNovidades(){
  api("/api/novidades").then(function(r){
    var it = (r.d.itens)||[];
    if(!it.length){ $("#t-novidades").innerHTML =
      '<p class="vazio">Nenhum post ainda.</p>'; return; }
    $("#t-novidades").innerHTML = it.map(function(n){
      return '<div class="bloco" style="margin-bottom:12px">'+
        '<div class="flex" style="gap:8px;align-items:center">'+
          (n.publicado ? '<span class="tag ok">publicado</span>'
                       : '<span class="tag al">rascunho</span>')+
          (n.titulo ? '<b>'+esc(n.titulo)+'</b>' : '')+
          '<span class="sp"></span>'+
          '<small>'+dataBr(n.em)+' · '+n.curtidas+' curtidas · '+
            n.comentarios+' comentários</small>'+
        '</div>'+
        '<p style="white-space:pre-wrap;margin:10px 0">'+esc(n.texto)+'</p>'+
        '<div class="flex" style="gap:8px">'+
          '<button class="ac" data-pub="'+n.id+'" data-valor="'+
            (n.publicado?"0":"1")+'">'+
            (n.publicado?"despublicar":"publicar")+'</button>'+
          '<button class="ac" data-coment="'+n.id+'">ver comentários</button>'+
          '<button class="ac perigo" data-rempost="'+n.id+'">remover</button>'+
        '</div>'+
        '<div id="c-'+n.id+'"></div></div>';
    }).join("");
  });
}

function carregarComentarios(pid){
  api("/api/novidades/"+pid+"/comentarios").then(function(r){
    var it = (r.d.itens)||[];
    var alvo = $("#c-"+pid);
    if(!alvo) return;
    if(!it.length){ alvo.innerHTML =
      '<p class="vazio">Sem comentários.</p>'; return; }
    alvo.innerHTML = '<table><tbody>'+it.map(function(c){
      return '<tr'+(c.removido?' style="opacity:.5"':'')+'>'+
        '<td>'+esc((c.autor||{}).nome)+'</td>'+
        '<td>'+esc(c.texto)+'</td>'+
        '<td><small>'+dataBr(c.em)+'</small></td>'+
        '<td>'+(c.removido ? '<span class="tag">removido</span>'
          : '<button class="ac perigo" data-remcom="'+pid+':'+c.id+
            '">remover</button>')+'</td></tr>';
    }).join("")+'</tbody></table>';
  });
}

$("#f-tipo").addEventListener("change", carregarFeedback);
$("#f-estado").addEventListener("change", carregarFeedback);

$("#b-publicar").addEventListener("click", function(){
  var texto = $("#n-texto").value.trim();
  if(!texto){ msg($("#m-novidade"), "Escreva o texto.", false); return; }
  api("/api/novidades",{corpo:{titulo:$("#n-titulo").value,
       texto:texto, publicado: !$("#n-rascunho").checked}})
    .then(function(r){
      if(r.status===200){
        $("#n-titulo").value = ""; $("#n-texto").value = "";
        msg($("#m-novidade"), "Publicado.", true);
        carregarNovidades();
      } else msg($("#m-novidade"), r.d.erro || "Erro.", false);
    });
});

// Delegação: os botões nascem depois, junto com a lista.
document.addEventListener("click", function(e){
  var b = e.target.closest && e.target.closest("button");
  if(!b) return;
  var id;
  if((id = b.dataset.responder)){
    var sel = document.querySelector('[data-estado="'+id+'"]');
    api("/api/feedback/"+id,{corpo:{
      resposta: $("#r-"+id).value, estado: sel ? sel.value : undefined}})
      .then(carregarFeedback);
  } else if((id = b.dataset.pub)){
    api("/api/novidades/"+id,{corpo:{publicado: b.dataset.valor === "1"}})
      .then(carregarNovidades);
  } else if((id = b.dataset.rempost)){
    if(confirm("Remover o post, com curtidas e comentários?"))
      api("/api/novidades/"+id+"/remover",{corpo:{}}).then(carregarNovidades);
  } else if((id = b.dataset.coment)){
    carregarComentarios(id);
  } else if((id = b.dataset.remcom)){
    var par = id.split(":");
    api("/api/novidades/"+par[0]+"/comentarios/"+par[1]+"/remover",{corpo:{}})
      .then(function(){ carregarComentarios(par[0]); });
  }
});

api("/api/sessao").then(function(r){
  if(r.d && r.d.autenticado) abrirApp(r.d.trocar_senha);
});
})();
