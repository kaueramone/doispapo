// Dois Papo — invólucro nativo para Windows.
//
// A janela aponta direto para a plataforma; não há frontend próprio.
// O papel do executável é dar janela nativa, ícone na bandeja e
// permissões de mídia — o resto continua sendo a aplicação web.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};

/// Mostra e traz a janela para frente, restaurando se estiver minimizada.
fn revelar(app: &tauri::AppHandle) {
    if let Some(j) = app.get_webview_window("principal") {
        let _ = j.unminimize();
        let _ = j.show();
        let _ = j.set_focus();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let abrir = MenuItem::with_id(app, "abrir", "Abrir Dois Papo", true, None::<&str>)?;
            let sair = MenuItem::with_id(app, "sair", "Sair", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&abrir, &sair])?;

            TrayIconBuilder::with_id("principal")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Dois Papo")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, evento| match evento.id.as_ref() {
                    "abrir" => revelar(app),
                    "sair" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, evento| {
                    // clique esquerdo na bandeja reabre a janela
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

            Ok(())
        })
        .on_window_event(|janela, evento| {
            // Fechar esconde em vez de encerrar: chamadas de voz continuam.
            // Sair de verdade é pelo menu da bandeja.
            if let WindowEvent::CloseRequested { api, .. } = evento {
                api.prevent_close();
                let _ = janela.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("falha ao iniciar o Dois Papo");
}
