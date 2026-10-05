# Executor paper dedicado — preparado, não ativado

O cron do GitHub falhou na janela temporal da R17.04. Este executor pode rodar num Linux sempre ligado, incluindo servidor contratado ou máquina própria; não precisa de login na Binance/OKX, saldo ou chave API. Nenhum endpoint de ordem está presente. A fonte pública de preços não substitui um computador que execute o código continuamente.

## Preparação do host

1. Usar o código congelado da ramificação `r17-06-funding-clock` e conferir o commit escolhido antes da ativação. O módulo novo importa os coletores e o motor paper da R17.04; não trocar módulos durante a janela prospectiva.
2. Criar usuário de serviço `igor`. Colocar o projeto em `/opt/igor/research` e criar `/var/lib/igor/market` e `/var/lib/igor/paper`, graváveis somente pelo usuário de serviço. Python 3.10+ basta para o executor; pandas/numpy são usados somente pelo estudo de funding.
3. Copiar para market o diretório `r17_03_market_data` do arquivo original, incluindo **todas** as capturas e o warmup. Manter a cópia original como evidência. O caminho paper deve ser independente e inicialmente vazio, pois a coorte ainda não tinha posições ou trades. Não conectar um segundo escritor a esses diretórios nem publicar essa cadeia local no branch original do GitHub.
4. Conferir relógio UTC sincronizado por NTP, rede pública OKX e armazenamento persistente. A mera ativação de time-sync.target não comprova precisão do relógio; o coletor também compara horário local e servidor e bloqueia diferença superior a cinco segundos.

Executar primeiro a pré-validação:

```bash
python3 /opt/igor/research/r16_edge_lab/r17_06_clock_runner.py \
  --archive /var/lib/igor/market --paper /var/lib/igor/paper --check
```

Se a última captura estiver mais de 24 horas atrás, o coletor existente bloqueia o próximo ciclo. Investigar e arquivar a lacuna com fonte pública antes de iniciar; não criar candle, apagar histórico ou reinterpretar backfill como sinal contemporâneo. Se o warmup ou o código divergirem da cadeia, a pré-validação também bloqueia.

## Ativação após preparar os caminhos

Copiar `igor-paper.service` e `igor-paper.timer` para `/etc/systemd/system/`, revisar usuário/caminhos e então:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now igor-paper.timer
systemctl list-timers igor-paper.timer
journalctl -u igor-paper.service
```

O timer dispara às 00:01:30, 04:01:30, 08:01:30, 12:01:30, 16:01:30 e 20:01:30 **UTC**, sem atraso aleatório. `Persistent=false` evita disparo retroativo por reinício; qualquer lacuna permanece registrada. Cada serviço é oneshot; não rodar também o modo contínuo no mesmo diretório. O lock local interrompe uma segunda instância; depois de uma falha, confirmar que o processo terminou antes de retirar eventual lock residual.

O protocolo novo interpreta `--event-name schedule` como o evento do timer dedicado. O motor conserva as portas originais de captura completa/temporal e processamento dentro de 120s; esse argumento não libera uma captura antiga. Reproduções antigas continuam SKIP. A configuração proposta não foi instalada nem recebeu credenciais nesta sessão.

Somente a primeira captura temporal válida e decisões arquivadas no host demonstram funcionamento. Registrar novo início prospectivo dessa infraestrutura, preservar hashes, manter backup, monitorar lacunas e tratar qualquer tarifa/funding não conciliado como não verificado. Um serviço preparado e testes offline não são lucro real, nem confirmação de 20% por mês.
