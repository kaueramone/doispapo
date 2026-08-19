# Dois Papo para Windows

Invólucro nativo da plataforma, feito em [Tauri](https://v2.tauri.app).
A janela aponta direto para `chat.doispapo.com` — não há frontend próprio,
o aplicativo web continua sendo o mesmo.

## O que ele acrescenta ao navegador

- Janela própria, sem barra de endereço
- Ícone na bandeja do sistema
- Fechar esconde em vez de encerrar, para a chamada de voz não cair
- Atalho no menu Iniciar e ícone na barra de tarefas

## Compilação

Não é feita na VPS: gerar binário do Windows exige toolchain do Windows.
O workflow `.github/workflows/windows.yml` compila num runner do GitHub.

**Disparar:**
- Aba *Actions* → *Instalador Windows* → *Run workflow*, ou
- publicar uma tag: `git tag desktop-v0.1.0 && git push origin desktop-v0.1.0`

Os instaladores (`.exe` via NSIS e `.msi`) ficam nos artefatos da execução.

## Requisito no computador do usuário

O WebView2 já vem no Windows 10 e 11. Em instalações antigas o instalador
NSIS baixa o runtime automaticamente.

## Assinatura de código

O executável **não é assinado**. O SmartScreen exibirá "aplicativo não
reconhecido" e o usuário precisa clicar em *Mais informações → Executar
assim mesmo*. Assinar exige certificado pago (na faixa de US$ 200–400/ano);
para um grupo pequeno costuma não compensar.
