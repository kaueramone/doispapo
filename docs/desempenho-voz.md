# Desempenho e qualidade de voz, câmera e tela

Análise a partir de medição na instância, não de suposição. Os números
vêm de 6 horas de registro do SFU com uso real, das estatísticas de RTP
que ele emite por faixa, e da configuração em vigor.

> **Estado em 20/08/2026.** Os itens 1, 2 e 3 da ordem sugerida (§5)
> foram feitos: `dynacast` na 0.42.0, métricas e aba de Consumo no
> painel, `adaptiveStream` na 0.43.0. O que está medido depois disso
> aparece marcado como tal. Faltam H.264 e TURN.

---

## 1. O que foi medido

**Máquina.** 2 vCPU, 7,8 GB. Em uso normal o SFU fica em ~2,7% de CPU e
108 MB. Carga média 0,40. **CPU não é o gargalo** — e não deveria ser
mesmo: um SFU encaminha pacotes, não recodifica vídeo.

**Rede.** 26,9 GB enviados e 22,1 GB recebidos em 44 h de máquina no ar.
Fora de chamada, o tráfego de fundo fica em ~600 kbit/s de saída.

**Faixas de vídeo.** Mediana **2.313 kbit/s** por faixa, p95 4.049. Bate
com a camada média do simulcast (1280×720 a 2,5 Mbit/s).

**Faixas de áudio.** Mediana 3 kbit/s, p95 21. Áudio é irrelevante no
custo; toda a conta é vídeo.

**Perda de pacotes.** Mediana 0%, **p95 2,13%**, máxima **58,3%**. É o
número mais preocupante do levantamento: metade das amostras é perfeita,
mas a cauda é ruim. 2% já produz artefato visível; 58% é conexão
desmoronando.

---

## 2. Os dois achados que mais pesam

### 2.1 `dynacast` e `adaptiveStream` estavam desligados — **resolvido**

São as duas alavancas principais do LiveKit, e ambas estavam no padrão
`false` da biblioteca. Hoje as duas estão ligadas.

**`dynacast`** (0.42.0) faz o SFU avisar quem transmite para parar de
enviar as camadas que ninguém assina. Antes, quem compartilhava a tela
**enviava o tempo todo**, mesmo sem ninguém assistindo — especialmente
desperdiçado aqui, porque a nossa assinatura sob demanda foi feita
justamente para ninguém receber sem pedir: economizávamos a descida de
quem assiste e seguíamos pagando a subida de quem transmite.

**Medido em produção**, com uma tela publicada e ninguém assistindo:

| | antes | depois |
|---|---|---|
| entrada da máquina | 3.399 kbit/s | **162 kbit/s** |
| saída da máquina | 2.752 kbit/s | **77 kbit/s** |

A tela seguia publicada nos dois casos — o que sumiu foi só o que
ninguém estava olhando.

**`adaptiveStream`** (0.43.0) faz cada assinante pedir a camada
compatível com o tamanho real do elemento na tela. Câmera publica em
três camadas (180p, 360p e a captura) e tela em duas (metade e
original); sem isso o cliente pedia sempre a maior, mesmo num quadro de
300 px na grade. Com o `dynacast` do outro lado, camada que ninguém pede
deixa de ser enviada — então a economia vale para os dois lados.

Estimativa para uma chamada de 6 pessoas com uma tela assistida por 5:

| | antes | com as duas ligadas |
|---|---|---|
| subida de quem transmite | 2,3 Mbit/s sempre | ~0 quando ninguém assiste |
| descida por espectador | 2,3 Mbit/s | 0,6 Mbit/s em quadro pequeno |
| saída total do servidor | ~11,5 Mbit/s | ~3 Mbit/s |

**O que o `adaptiveStream` cobrou em cuidado:** ele decide o que
continua chegando observando os elementos onde a faixa foi encaixada, e
os observadores nascem no documento principal. A janela destacada vive
em outro documento — para o observador ela nunca está visível, e a faixa
seria desligada com a janela aberta na frente da pessoa. O `destacar.ts`
responde pela visibilidade dela por conta própria, via
`observeElementInfo`. Aba escondida pausa vídeo depois de 5 s (o áudio
nunca pausa) e voltar religa na hora.

**Ainda não verificado com duas pessoas de verdade na chamada.** A
divida de §8 continua de pé.

### 2.2 O codec é VP8, e VP8 quase não tem aceleração por hardware

O cliente não escolhe codec, então fica no VP8 padrão (confirmado no
registro: `"mime": "video/VP8"`).

Isso liga direto com o pedido de aceleração por hardware: **decodificar
VP8 é quase sempre por software**. H.264 tem decodificação por hardware
praticamente universal — Intel QuickSync, NVIDIA, AMD, Apple. Numa
máquina modesta, assistir a uma tela em 720p VP8 consome CPU que em
H.264 seria quase nada.

Ou seja: a "opção de aceleração por hardware" não é um botão que se
liga. **É a escolha de codec que decide se existe hardware capaz de
ajudar.**

Contrapartidas honestas: H.264 tem simulcast pior em alguns navegadores,
e nem todo Linux traz encoder H.264. O caminho é preferir H.264 com VP8
como reserva, e medir.

---

## 3. Conectividade: sem TURN

`turn.enabled: false`, e não há servidor TURN externo. Quem está atrás de
NAT simétrico ou firewall restritivo não consegue UDP direto e cai no
TCP 7881.

Mídia sobre TCP é ruim por construção: retransmissão e bloqueio de fila
transformam perda em travamento e atraso crescente. É a explicação mais
provável para a cauda de perda alta que medimos — não é que a rede da
pessoa perde 58%, é que o caminho dela é o pior disponível.

Ligar o TURN embutido do LiveKit numa porta própria daria um caminho
intermediário (UDP relayed) antes de cair para TCP.

---

## 4. Sem visibilidade — **resolvido**

O SFU não expunha métricas (`prometheus_port` não configurado), então não
havia como acompanhar nada disso ao longo do tempo: tudo nesta análise
saiu de log bruto, o que serve para investigação e não serve para
operação.

Hoje o `convites` coleta a cada minuto de três fontes separadas — os
contadores de rede da máquina, as métricas do SFU e o peso das faixas por
canal — e o painel mostra o resultado na aba **Consumo**, com o total
medido de um lado e o rateio estimado por comunidade do outro, nunca
somados. Ver §6.

---

## 5. Ordem sugerida

| # | Mudança | Efeito esperado | Risco | Estado |
|---|---|---|---|---|
| 1 | Ligar `dynacast` e `adaptiveStream` | maior de todos | baixo | **feito** (0.42.0 e 0.43.0) |
| 2 | Expor métricas do SFU | sem isso não se mede nada | nenhum | **feito** |
| 3 | Painel de consumo (§6) | decisão de upgrade com base em dado | baixo | **feito** |
| 4 | Preferir H.264 no compartilhamento | destrava aceleração por hardware | médio | aberto |
| 5 | Ligar TURN | corrige a cauda de perda | médio | aberto |

A ordem não é arbitrária: 1 é barato e grande, 2 e 3 são o que permite
saber se 4 e 5 valeram a pena. Fazer 4 antes de 2 é mexer no codec sem
poder comparar antes e depois.

---

## 6. Painel de consumo

**O que dá para saber com precisão:** o total real de entrada e saída da
máquina, lido dos contadores da interface. É verdade absoluta, mas não
separa por comunidade.

**O que dá para estimar bem:** minutos de faixa por canal. Amostrando os
participantes de cada sala a cada 30 s, sabe-se quantas faixas de cada
tipo estavam ativas e quantas pessoas assinavam. Multiplicando pelas
taxas medidas (2,3 Mbit/s por vídeo, ~20 kbit/s por áudio) chega-se a um
consumo estimado por comunidade.

**Desenho:** o `convites` amostra e grava agregados diários por canal e
por servidor; o painel mostra duas coisas lado a lado — o total real
medido e a divisão estimada por comunidade. Deixar claro qual é qual
importa: misturar medição com estimativa numa mesma barra é como se
mente com gráfico.

**Para decidir upgrade**, o painel precisa responder três perguntas:
minutos de chamada por dia, pico simultâneo de faixas de vídeo, e GB por
mês. A terceira é a conta financeira; a segunda é a que diz quando a
máquina não aguenta mais.

> Os 2,3 Mbit/s por faixa foram medidos **antes** do `dynacast` e do
> `adaptiveStream`. A constante que alimenta o rateio do painel
> (`KBIT_VIDEO`) ainda usa esse valor e precisa ser recalibrada com
> alguns dias de série nova.

**Conta de capacidade, com os números de hoje:** uma sessão de 3 h com 6
pessoas e uma tela assistida por 5 gasta ~18 GB. Diariamente, ~540
GB/mês. Longe de qualquer teto de plano. O limite prático chega antes
pelo simultâneo: 20 espectadores de 2 telas seriam ~92 Mbit/s de saída
sustentada, e aí 2 vCPU começam a pesar no processamento de pacotes.

Com `dynacast` e `adaptiveStream` ligados, esse mesmo cenário cai para
perto de um quarto — o que provavelmente adia o upgrade por bastante
tempo. **Por isso a medição vem antes da decisão de máquina.**

---

## 7. Aceleração por hardware, por plataforma

**Navegador.** Não há como ligar por código; quem decide é o navegador.
O que está ao nosso alcance é oferecer um fluxo que o hardware saiba
decodificar — ou seja, o item 4. Um seletor "usar aceleração" que não
mude o codec seria um botão que não faz nada.

**Desktop (Tauri v2 / WebView2).** Aqui existe controle real: dá para
passar argumentos ao WebView2 na inicialização, inclusive os que
governam decodificação por GPU. Como argumentos valem só na subida, um
seletor exige reiniciar o aplicativo — o que combina com o item de
bandeja que já recarrega o conteúdo.

Antes de prometer, precisa ser medido no Windows: qual codec o WebView2
decodifica por hardware naquela máquina, e se os argumentos mudam algo.
Não tenho como verificar isso daqui.

---

## 8. O que esta análise não cobre

Não medi latência fim a fim percebida, nem qualidade subjetiva de
imagem, nem o efeito de cada mudança — porque nenhuma foi feita ainda.
Os números acima descrevem o estado atual; a comparação depois de cada
alteração é o que vai dizer se funcionou, e isso exige o item 2 primeiro.

Também não há teste automatizado de chamada, o que significa que
qualquer alteração aqui vai para produção sem prova — a mesma dívida
registrada em `fila.md`.
