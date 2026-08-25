// Dois Papo — invólucro nativo para Windows.
//
// A janela aponta direto para a plataforma; não há frontend próprio.
// O papel do executável é dar janela nativa, ícone na bandeja, permissões
// de mídia e aviso de nova versão.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicU32, Ordering};

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    webview::{NewWindowResponse, WebviewWindowBuilder},
    Manager, WindowEvent,
};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

const VERSAO: &str = env!("CARGO_PKG_VERSION");
const API_RELEASES: &str =
    "https://api.github.com/repos/kaueramone/doispapo/releases/latest";
const PAGINA_DOWNLOAD: &str = "https://doispapo.com/baixar/windows";

/// Mostra e traz a janela para frente, restaurando se estiver minimizada.
fn revelar(app: &tauri::AppHandle) {
    if let Some(j) = app.get_webview_window("principal") {
        let _ = j.unminimize();
        let _ = j.show();
        let _ = j.set_focus();
    }
}

/// Compara versões no formato x.y.z. Devolve true se `remota` for maior.
fn e_mais_nova(remota: &str, local: &str) -> bool {
    let parte = |v: &str| -> Vec<u32> {
        v.trim_start_matches(|c: char| !c.is_ascii_digit())
            .split('.')
            .map(|p| p.chars().take_while(|c| c.is_ascii_digit())
                      .collect::<String>().parse().unwrap_or(0))
            .collect()
    };
    let (r, l) = (parte(remota), parte(local));
    for i in 0..r.len().max(l.len()) {
        let (a, b) = (*r.get(i).unwrap_or(&0), *l.get(i).unwrap_or(&0));
        if a != b {
            return a > b;
        }
    }
    false
}

/// Recarrega o conteúdo descartando o service worker.
///
/// O invólucro e o aplicativo web têm ciclos diferentes: o executável quase
/// não muda, e o cliente web é publicado com frequência. Quem está com o
/// invólucro em dia pode mesmo assim estar vendo um cliente antigo, porque
/// o service worker serve o que guardou até decidir trocar.
///
/// Recarregar sozinho não resolve isso — por isso o registro é removido
/// antes, e só então a página recarrega.
fn recarregar_conteudo(app: &tauri::AppHandle) {
    if let Some(janela) = app.get_webview_window("principal") {
        // O recarregamento fica FORA da cadeia opcional de propósito. Com
        // `navigator.serviceWorker?.…`, um ambiente sem service worker
        // curto-circuitaria a expressão inteira e nem recarregaria — o
        // botão não faria nada, que é o defeito que este trabalho corrige.
        let _ = janela.eval(
            "Promise.resolve(\
               navigator.serviceWorker ? \
                 navigator.serviceWorker.getRegistrations() : [])\
             .then(rs => Promise.all(rs.map(r => r.unregister())))\
             .catch(() => {})\
             .then(() => location.reload(), () => location.reload());",
        );
        let _ = janela.show();
        let _ = janela.set_focus();
    }
}

/// Aviso simples, só quando a verificação foi pedida pelo menu.
///
/// Não bloqueante de propósito: um diálogo que trava a espera dentro do
/// runtime assíncrono prende a tarefa até alguém clicar.
fn avisar(app: &tauri::AppHandle, pedida: bool, texto: &str) {
    if !pedida {
        return;
    }
    app.dialog()
        .message(texto.to_string())
        .title("Dois Papo")
        .kind(MessageDialogKind::Info)
        .show(|_| {});
}

/// Consulta a última release publicada e avisa se houver versão nova.
///
/// `pedida` distingue o clique no menu da checagem automática da abertura.
/// Silêncio é a resposta certa para a automática — ninguém quer um aviso
/// "está tudo em dia" a cada vez que abre o programa. Para o clique, é a
/// resposta errada: a pessoa perguntou e não recebeu nada, o que faz o item
/// de menu parecer quebrado.
async fn verificar_atualizacao(app: tauri::AppHandle, pedida: bool) {
    let cliente = match reqwest::Client::builder()
        .user_agent(format!("DoisPapo/{VERSAO}"))
        .timeout(std::time::Duration::from_secs(12))
        .build()
    {
        Ok(c) => c,
        Err(_) => {
            avisar(&app, pedida, "Não foi possível verificar agora.");
            return;
        }
    };

    let resposta = match cliente.get(API_RELEASES).send().await {
        Ok(r) => r,
        Err(_) => {
            avisar(
                &app,
                pedida,
                "Não foi possível verificar agora. Confira sua conexão.",
            );
            return;
        }
    };
    let dados: serde_json::Value = match resposta.json().await {
        Ok(d) => d,
        Err(_) => {
            avisar(&app, pedida, "Não foi possível verificar agora.");
            return;
        }
    };
    let tag = match dados.get("tag_name").and_then(|t| t.as_str()) {
        Some(t) => t,
        None => {
            avisar(&app, pedida, "Não foi possível verificar agora.");
            return;
        }
    };

    if !e_mais_nova(tag, VERSAO) {
        if pedida {
            // Estar com o invólucro em dia não garante estar com o cliente
            // web em dia, então a resposta vem com a ação que resolve isso.
            let app3 = app.clone();
            app.dialog()
                .message(format!(
                    "Você está na versão mais recente ({VERSAO}).\n\n\
                     Se algo parecer desatualizado na tela, recarregar limpa \
                     o que ficou guardado e busca a versão nova do aplicativo."
                ))
                .title("Dois Papo está em dia")
                .kind(MessageDialogKind::Info)
                .buttons(MessageDialogButtons::OkCancelCustom(
                    "Recarregar".into(),
                    "Fechar".into(),
                ))
                .show(move |recarregar| {
                    if recarregar {
                        recarregar_conteudo(&app3);
                    }
                });
        }
        return;
    }

    let limpa = tag.trim_start_matches("desktop-v").to_string();
    let app2 = app.clone();
    app.dialog()
        .message(format!(
            "A versão {limpa} já está disponível.\n\
             Você está usando a {VERSAO}.\n\n\
             Deseja baixar agora? O download abre no navegador."
        ))
        .title("Nova versão do Dois Papo")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Atualizar".into(),
            "Depois".into(),
        ))
        .show(move |atualizar| {
            if atualizar {
                use tauri_plugin_shell::ShellExt;
                let _ = app2.shell().open(PAGINA_DOWNLOAD, None);
            }
        });
}

/// Contador de janelas destacadas, para o rotulo nao repetir.
///
/// Rotulo repetido faz o `build()` falhar, e a falha aconteceria dentro do
/// handler de janela nova -- onde nao ha para quem reclamar. A segunda tela
/// destacada simplesmente nao abriria.
static DESTAQUES: AtomicU32 = AtomicU32::new(0);

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            /*
              A janela principal e construida AQUI, e nao pelo
              `tauri.conf.json`, por um motivo so: `on_new_window` existe
              apenas no `WebviewWindowBuilder`.

              Sem esse handler, o wry no Windows responde
              `args.SetHandled(true)` sem criar janela nenhuma
              (`wry/src/webview2/mod.rs`), e `window.open()` devolve `null`.
              Como o Document Picture-in-Picture do Chromium passa pelo
              MESMO caminho -- `openPictureInPictureWindow` chama
              `FindOrCreateFrameForNavigation(..., "_blank")` -- os dois
              jeitos de destacar a tela morriam no mesmo ponto. Era por isso
              que "destacar em janela" nao funcionava no aplicativo, e a
              causa nao era permissao do Windows nem API ausente.

              A configuracao da janela continua no JSON (com
              `"create": false`); `from_config` le o mesmo objeto.
            */
            let config = app.config().app.windows.first().cloned().ok_or(
                "nenhuma janela configurada no tauri.conf.json",
            )?;
            let app_ = app.handle().clone();

            WebviewWindowBuilder::from_config(app.handle(), &config)?
                .on_new_window(move |url, features| {
                    let n = DESTAQUES.fetch_add(1, Ordering::Relaxed);

                    /*
                      `window_features(features)` NAO e detalhe de tamanho
                      e posicao: no Windows ele tambem aplica
                      `with_environment(opener.environment)`, e a
                      documentacao da Microsoft e explicita em exigir que a
                      WebView entregue ao `NewWindow` esteja no MESMO
                      Environment e no mesmo perfil do opener.

                      E dai vem a parte que decide se isto vale a pena: a
                      Microsoft documenta que a nova WebView "e devolvida ao
                      script do opener como o WindowProxy aberto". Um
                      WindowProxy so existe dentro do mesmo browsing context
                      group -- e mesma origem, mesmo grupo e sem `noopener`
                      dao o mesmo processo de renderizacao e o mesmo agent
                      cluster. E agent cluster igual e exatamente a condicao
                      para entregar um `MediaStream` vivo de um documento ao
                      outro, que e o que o `destacar.ts` ja faz no navegador.

                      Essa ultima ligacao e DEDUZIDA, nao documentada. O
                      teste que a confirma esta no README do desktop.
                    */
                    let janela = WebviewWindowBuilder::new(
                        &app_,
                        format!("destaque-{n}"),
                        tauri::WebviewUrl::External(
                            "about:blank".parse().expect("about:blank e valido"),
                        ),
                    )
                    .window_features(features)
                    .title(url.as_str())
                    .on_document_title_changed(|janela, titulo| {
                        let _ = janela.set_title(&titulo);
                    })
                    .build();

                    match janela {
                        Ok(janela) => NewWindowResponse::Create { window: janela },
                        // Recusar e melhor que derrubar o aplicativo: o
                        // `destacar.ts` ja trata `window.open` devolvendo
                        // null, mantendo o quadro na grade e avisando.
                        Err(e) => {
                            eprintln!("janela de destaque nao abriu: {e}");
                            NewWindowResponse::Deny
                        }
                    }
                })
                .build()?;

            let abrir = MenuItem::with_id(app, "abrir", "Abrir Dois Papo", true, None::<&str>)?;
            let buscar = MenuItem::with_id(app, "buscar", "Procurar atualização", true, None::<&str>)?;
            let sair = MenuItem::with_id(app, "sair", "Sair", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&abrir, &buscar, &sair])?;

            // Ícone próprio da bandeja: fundo sólido, para ler bem tanto em
            // barra clara quanto escura.
            TrayIconBuilder::with_id("principal")
                .icon(tauri::include_image!("./icons/bandeja.png"))
                .tooltip(format!("Dois Papo {VERSAO}"))
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, evento| match evento.id.as_ref() {
                    "abrir" => revelar(app),
                    "buscar" => {
                        let a = app.clone();
                        tauri::async_runtime::spawn(verificar_atualizacao(a, true));
                    }
                    "sair" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, evento| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = evento
                    {
                        revelar(tray.app_handle());
                    }
                })
                .build(app)?;

            // Verificação ao abrir, com folga para a janela carregar antes.
            let a = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(std::time::Duration::from_secs(8)).await;
                verificar_atualizacao(a, false).await;
            });

            Ok(())
        })
        .on_window_event(|janela, evento| {
            if let WindowEvent::CloseRequested { api, .. } = evento {
                // Fechar esconde em vez de encerrar: chamadas de voz
                // continuam. Mas SO a janela principal -- uma janela de
                // destaque que apenas se esconde ficaria segurando a
                // assinatura da faixa para sempre, e o botao de fechar
                // dela nao faria nada visivel na segunda vez.
                if janela.label() == "principal" {
                    api.prevent_close();
                    let _ = janela.hide();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("falha ao iniciar o Dois Papo");
}
