/* ---------------------------------------------------------------------
   Dois Papo — tela de Amigos: busca, "Adicionar amigo" e status na linha.

   O Discord abre esta tela com uma busca de largura total, um botao
   rotulado, e cada linha mostrando o status por extenso sob o nome.
   Aqui havia so um "+" sem rotulo, nenhuma busca, e a linha com nada
   alem do nome.

   Por que JS e nao CSS, como nas camadas anteriores: CSS nao cria campo
   de texto, nao filtra linhas e nao inventa o texto do status. E o "+"
   original tem a largura travada pelo app — o rotulo via ::after chega
   a renderizar (112px medidos), mas o botao continua em 32px e corta
   tudo. Sai mais limpo desenhar um botao proprio e delegar o clique ao
   original, que ja sabe abrir o fluxo. O original fica ESCONDIDO, nao
   removido: se este script quebrar, ele reaparece e a tela segue util.

   Ancoras estaveis (nenhuma classe, que sao hashes do build):
     button[aria-label="Adicionar um amigo"]   o botao original
     mdui-navigation-rail                      a barra de filtros
     mdui-list / -item / -subheader            a lista de amigos
     circle[fill="var(--brand-presence-...)"]  a bolinha de presenca
--------------------------------------------------------------------- */
(function () {
  "use strict";

  var ID_BARRA = "dp-amigos-barra";
  var ID_VAZIO = "dp-amigos-vazio";
  var termo = "";

  /* Rotulos iguais aos que o proprio app ja usa no seletor de status —
     lidos do bundle, nao inventados, para a tela nao falar duas
     linguas. O Discord chama "busy" de "Nao perturbar"; aqui fica
     "Ocupado", que e como aparece no resto da interface. */
  var STATUS = {
    online:    "Disponível",
    idle:      "Ausente",
    focus:     "Concentrado",
    busy:      "Ocupado",
    invisible: "Invisível"
  };

  function semAcento(s) {
    return (s || "").toLowerCase().normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function original() {
    return document.querySelector('button[aria-label="Adicionar um amigo"]');
  }

  function raizDaTela() {
    var rail = document.querySelector("mdui-navigation-rail");
    return rail ? (rail.closest("main") || document) : null;
  }

  /* O nome do amigo e o unico filho SEM slot: o avatar vai em
     slot="icon" e o status que injetamos, em slot="description". Ler o
     textContent inteiro faria a busca casar com o status — quem
     digitasse "disponivel" veria a lista toda. */
  function nomeDe(item) {
    return [].filter.call(item.childNodes, function (n) {
      return n.nodeType !== 1 || !n.getAttribute("slot");
    }).map(function (n) { return n.textContent || ""; }).join(" ").trim();
  }

  /* A bolinha de presenca guarda o status no PROPRIO nome da variavel
     CSS: fill="var(--brand-presence-online)". E a unica fonte no DOM —
     nao ha texto nem atributo dizendo em que estado a pessoa esta. */
  function statusDe(item) {
    var c = item.querySelector("circle");
    if (!c) return null;
    var m = /--brand-presence-([a-z]+)/.exec(c.getAttribute("fill") || "");
    return m ? (STATUS[m[1]] || null) : null;
  }

  /* Marca as listas desta tela para o CSS poder mexer na altura e na
     divisoria sem alcancar os mdui-list das configuracoes. */
  function anotarStatus(raiz) {
    [].forEach.call(raiz.querySelectorAll("mdui-list"), function (l) {
      l.setAttribute("data-dp-amigos", "");
    });
    [].forEach.call(raiz.querySelectorAll("mdui-list-item"), function (item) {
      var texto = statusDe(item);
      var atual = item.querySelector('[slot="description"][data-dp]');
      if (!texto) { if (atual) atual.remove(); return; }
      if (atual) {
        if (atual.textContent !== texto) atual.textContent = texto;
        return;
      }
      var s = document.createElement("span");
      s.setAttribute("slot", "description");
      s.setAttribute("data-dp", "");
      s.textContent = texto;
      item.appendChild(s);
    });
  }

  /* Esconde quem nao casa. Um subcabecalho ("Online - 3") some junto
     quando o grupo inteiro sumiu, senao sobra um titulo anunciando uma
     lista vazia. */
  function filtrar() {
    var t = semAcento(termo.trim());
    var visiveisTotal = 0;

    [].forEach.call(document.querySelectorAll("mdui-list"), function (lista) {
      var grupo = null, noGrupo = 0;

      function fecharGrupo() {
        if (grupo) grupo.style.display = noGrupo ? "" : "none";
      }

      /* Os itens NAO sao filhos diretos da lista: o caminho real e
         mdui-list-item < a < div < div < mdui-list. Varrer children
         encontraria so o subcabecalho e um <div>. querySelectorAll
         devolve na ordem do documento, que e o que o agrupamento por
         subcabecalho precisa. */
      [].forEach.call(
        lista.querySelectorAll("mdui-list-subheader, mdui-list-item"),
        function (el) {
          if (el.tagName.toLowerCase() === "mdui-list-subheader") {
            fecharGrupo();
            grupo = el; noGrupo = 0;
            return;
          }
          var casa = !t || semAcento(nomeDe(el)).indexOf(t) !== -1;
          /* quem ocupa a linha e o <a> em volta; esconder so o item
             deixaria o espaco dele na lista */
          (el.closest("a") || el).style.display = casa ? "" : "none";
          if (casa) { noGrupo++; visiveisTotal++; }
        });
      fecharGrupo();
    });

    var vazio = document.getElementById(ID_VAZIO);
    if (vazio) vazio.style.display = (t && !visiveisTotal) ? "" : "none";
  }

  function montar() {
    var rail = document.querySelector("mdui-navigation-rail");
    if (!rail || document.getElementById(ID_BARRA)) return;
    var btn = original();
    if (!btn) return;

    /* esconde o "+" sem rotulo; o pai e quem ocupa espaco na fila */
    (btn.parentElement || btn).style.display = "none";

    var barra = document.createElement("div");
    barra.id = ID_BARRA;

    var busca = document.createElement("input");
    busca.type = "search";
    busca.placeholder = "Buscar";
    busca.setAttribute("aria-label", "Buscar amigos");
    busca.autocomplete = "off";
    busca.addEventListener("input", function () {
      termo = busca.value;
      filtrar();
    });
    /* Esc limpa, como no Discord */
    busca.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && busca.value) {
        e.stopPropagation();
        busca.value = ""; termo = ""; filtrar();
      }
    });

    var add = document.createElement("button");
    add.id = "dp-amigos-add";
    add.type = "button";
    add.textContent = "Adicionar amigo";
    add.addEventListener("click", function () {
      var alvo = original();
      if (alvo) alvo.click();
    });

    barra.appendChild(busca);
    barra.appendChild(add);
    rail.parentNode.insertBefore(barra, rail.nextSibling);

    var vazio = document.createElement("div");
    vazio.id = ID_VAZIO;
    vazio.textContent = "Nenhum amigo com esse nome.";
    vazio.style.display = "none";
    barra.parentNode.insertBefore(vazio, barra.nextSibling);
  }

  /* A tela monta e desmonta a cada troca de rota, e a lista se redesenha
     sozinha quando alguem entra, sai ou muda de status. Reagir a mutacao
     cobre os tres casos sem depender de evento de roteador.

     anotarStatus() acrescenta um <span>, o que gera nova mutacao — mas
     ela e idempotente: na segunda passada o span ja existe e nada muda,
     entao o ciclo morre em uma volta. */
  var pendente = null;
  function agendar() {
    if (pendente) return;
    pendente = setTimeout(function () {
      pendente = null;
      var raiz = raizDaTela();
      if (!raiz) { termo = ""; return; }
      montar();
      anotarStatus(raiz);
      filtrar();
    }, 80);
  }

  new MutationObserver(agendar)
    .observe(document.body, { childList: true, subtree: true });

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", agendar);
  else agendar();
})();
