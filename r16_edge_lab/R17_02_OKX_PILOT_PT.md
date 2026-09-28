# R17.02 — piloto público independente na OKX

Registro técnico em 28/09/2026 UTC. A R16.24.2 continua sendo o baseline validado do robô principal; o estudo R17.00 foi rejeitado e a coorte Binance R17.01 permanece separada. Este piloto verifica se podemos obter **dados públicos diretamente na nuvem**, sem conta Binance, sem acesso ao PC e sem qualquer ordem. Não existe sinal de investimento congelado para este piloto.

## Fonte e escopo

- Contrato piloto: `BTC-USDT-SWAP` na OKX, em uma cadeia de arquivos própria. A escolha de um contrato só serve para testar a coleta; não foi feita com base em lucratividade. Consultas GET públicas: horário, catálogo de contratos, velas 4h com `confirm=1`, histórico de funding e ticker com bid/ask e timestamp.
- O GitHub Actions público nos EUA recebeu HTTP 451 da API de futuros Binance e HTTP 403 da Bybit em 28/09/2026, mas recebeu HTTP 200 com `code=0` de horário, velas, funding, ticker e catálogo OKX. O arquivo público `data.binance.vision` respondeu HTTP 200 para checksum histórico; arquivo atrasado não substitui cotação atual do livro.
- Armazenar respostas observadas, timestamp da bolsa, fonte/código por hash e hash encadeado no branch `r17-02-okx-market-data`. A cada 4h uma execução agendada tenta observar a última vela encerrada; falhas e atrasos não serão simulados como capturas pontuais. Livro/ticker acima de 5 segundos de idade invalida a cotação como referência de decisão.
- O campo `realizedRate`/`fundingRate` é guardado quando há evento no período; ausência de um evento numa janela de 4h é admissível. Este piloto **não estima custos de negociação da Binance**, não reproduz preço de execução na Binance nem calcula lucro ou perda. Uma pesquisa de estratégia na OKX exige universo, regras completas, riscos, custos e hipóteses congelados previamente em protocolo novo.

Porta de aceite desta etapa: ao menos uma execução real da coleta OKX, validação dos arquivos e commit no branch de dados. Mesmo com essa porta concluída, não promover robô, não afirmar retorno mensal e não tratar o histórico já consultado como teste fora da amostra.

## Primeira verificação real

Execução [36448091271](https://github.com/sapuppo/IGOR/actions/runs/36448091271) concluída com sucesso em 28/09/2026 UTC. Captura [1790611353448](https://github.com/sapuppo/IGOR/blob/r17-02-okx-market-data/r17_okx_market_data/capture-1790611353448-371f3cc4f4d1dcf0.json) arquivada no branch de dados, vela 12:00–16:00 UTC confirmada, livro com 376 ms de idade na verificação, sem evento de funding dentro da janela, `status=COMPLETE` e `problems=[]`. Classe `MIXED_BACKFILL_AND_TIMELY_QUOTE`: foi observada antes de 29/09/2026 e, portanto, não valida uma estratégia. O cron ainda precisará ser verificado após a primeira execução agendada.
