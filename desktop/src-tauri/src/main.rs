// Dois Papo — invólucro nativo para Windows.
//
// A janela aponta direto para a plataforma; não há frontend próprio.
// O papel do executável é dar janela nativa, ícone na bandeja, permissões
// de mídia e aviso de nova versão.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
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
            // Fechar esconde em vez de encerrar: chamadas de voz continuam.
            if let WindowEvent::CloseRequested { api, .. } = evento {
                api.prevent_close();
                let _ = janela.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("falha ao iniciar o Dois Papo");
}
