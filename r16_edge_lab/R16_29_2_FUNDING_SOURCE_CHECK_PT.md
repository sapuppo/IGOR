# R16.29.2 — verificação adicional da fonte do preço de funding

**Resultado: o invariante 11 continua `BLOCKED`; o Gate 3 continua `TECHNICALLY_INVALID`.** A R16.24.2 permanece a última baseline validada. Não alteramos o alfa, os dados originais, os ledgers ou os resultados BASE/STRESS do relatório principal.

## Investigação executada

O endpoint `/fapi/v1/fundingRate` documenta `markPrice` como o preço associado à cobrança de funding. Já `/fapi/v1/markPriceKlines` documenta candles OHLC identificados pela abertura do intervalo. Os dois campos têm significados distintos: a existência de um candle histórico não prova que sua abertura é o preço exato usado na cobrança. Fontes: [documentação da API USD-M](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data) e [arquivo público com `.CHECKSUM`](https://github.com/binance/binance-public-data).

1. Tentativa de consulta direta na [execução 36285425944](https://github.com/sapuppo/IGOR/actions/runs/36285425944): HTTP 451 no endpoint, interrompida. Não houve uso de espelho ou contorno da restrição.
2. A [execução 36285712977](https://github.com/sapuppo/IGOR/actions/runs/36285712977) recuperou arquivos diários oficiais de `markPriceKlines` de 1 minuto, validou SHA-256 contra `.CHECKSUM` e comparou seu open, close e close do minuto anterior a amostras de `markPrice` já congeladas no suplemento da auditoria.

| Verificação | Contagem |
|---|---:|
| Arquivos diários consultados, cinco símbolos e três datas | 15 |
| Arquivos encontrados com checksum validado | 14 |
| Arquivo indisponível na amostra (`SOLUSDT`, 15/11/2023) | 1 |
| Eventos de 15/01/2021 com candle presente e `markPrice` de cobrança ausente | 15 |
| Eventos de 2023/2024 comparáveis com `markPrice` conhecido | 27 |
| Abertura do minuto exatamente igual ao preço da cobrança | **16/27** |
| Abertura do minuto diferente do preço da cobrança | **11/27** |
| Fechamento do próprio minuto exatamente igual | **0/27** |

Exemplo: BTCUSDT em 15/02/2024 00:00 UTC tinha preço de cobrança **51.816,90327305** e abertura do candle de 1 minuto **51.817,98284752**. Para ETHUSDT em 15/11/2023 00:00 UTC, respectivamente **1.979,75289030** e **1.980,02529536**. Mesmo divergências pequenas bastam para refutar equivalência exata. O fechamento do minuto também carregaria informação posterior à cobrança.

O [JSON de evidência](R16_29_2_FUNDING_SOURCE_EVIDENCE.json) registra 45 eventos selecionados, preços originais, candidatos, comparações, os 14 hashes de arquivos comprovados e o arquivo ausente. A amostra é um teste de refutação da equivalência, não uma estimativa estatística da diferença em todos os 8.480 eventos afetados do backtest. O arquivo de candles de 2021 oferece uma **aproximação potencial** para estudo de sensibilidade, mas não substitui o valor real da liquidação.

## Próxima decisão técnica

Para validar todo o período 2021–2026 sob o contrato vigente, é necessária outra fonte independente que identifique **o preço efetivo da cobrança por símbolo e horário** nos eventos sem `markPrice`. Caso essa fonte não seja encontrada, qualquer mudança de período, tolerância ou definição do invariante exige uma revisão metodológica explícita e prévia, seguida por novo replay. Uma nova janela técnica retrospectiva continuaria sem OOS intocado, pois os alfas já foram selecionados com acesso ao histórico. O holdout prospectivo de 180 dias e 100 operações fechadas permanece `NOT_STARTED`.
