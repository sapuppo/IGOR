# R17.01 — prontidão de observação, sem resultados de lucro

Data: 27/09/2026 no horário de São Paulo. Pesquisa em `r17-01-research`; R16.24.2 continua o baseline. A R17.00 perdeu −34,28% no STRESS e foi descartada. **Nenhuma posição real ou paper foi aberta nesta etapa.** O período prospectivo ainda tem zero dias avaliados e zero operações.

## Entregue

- Protocolo `R17_01_FORWARD_PROTOCOL_PT.md` registrado antes de consultar dados novos, com primeiro dia elegível 29/09/2026 00:00 UTC e critérios explícitos de integridade e rejeição.
- `R17_01_UNIVERSE.json` contém os 38 pares predefinidos; SHA-256 do arquivo `87099ccc30eb68b3d18b5902accab599280f17a9b587fcacf8242ee142e83d53`. A rotina rejeita uma lista editada.
- `r17_forward_capture.py` consulta apenas cinco rotas públicas USD-M (`time`, `exchangeInfo`, `klines`, `fundingRate`, `bookTicker`) via GET. Registra resposta bruta, timestamp de servidor e local, tempo da consulta de bid/ask, cobertura de velas, preço oficial de funding, status de negociação e problemas por par. Capturas sucessivas têm cadeia de SHA-256, e código ou universo alterado obrigam nova cadeia de pesquisa.
- Essa cadeia acusa alterações isoladas nos arquivos. Sem publicar periodicamente o último hash em um registro externo, ela **não comprova** que ninguém reescreveu todos os arquivos da série; essa ancoragem será necessária antes de chamar a evidência de auditável independentemente.
- `test_r17_forward_capture.py` exercita com dados **sintéticos**: respostas válidas, vela faltante, candle ainda aberto, `markPrice` ausente, bid/ask antigo, adulteração do arquivo, carimbo regressivo e código alterado. Os testes sintéticos não substituem uma captura real.

## Situação da execução

Este ambiente tentou consultar `https://fapi.binance.com/fapi/v1/time` com prazo de 5 s; a conexão expirou (`HTTP 000`). **Isso é apenas uma restrição deste ambiente, não uma necessidade de acessar o PC do usuário.** A execução na nuvem por GitHub Actions consulta rotas públicas, sem conta nem chaves da Binance, arquiva os JSON em `r17-01-market-data` e mantém o robô principal intocado. O script PowerShell local continua disponível como alternativa opcional, mas nenhuma configuração no computador do usuário é pré-requisito para a coleta na nuvem.

Em um checkout da ramificação `r17-01-research`, execute PowerShell na raiz do repositório:

```powershell
& .\r16_edge_lab\r17_01_capture_windows.ps1
```

Para verificar uma pasta já produzida:

```powershell
py -3 .\r16_edge_lab\r17_forward_capture.py verify --out-dir "$env:LOCALAPPDATA\IGOR\R17\captures"
```

Para observação no horário da decisão, o agendador em nuvem tenta executar após cada fronteira de 4 h UTC. Uma coleta atrasada rotula o histórico como `RETROSPECTIVE_BACKFILL` ou `MIXED_BACKFILL_AND_TIMELY_QUOTE`, nunca inventa preço de execução passado. Dados brutos ou snapshots futuros em falta são bloqueios, não zeros. GitHub Actions pode atrasar ou descartar agendamentos; verificar cada execução e registrar lacunas. **Coletar dados não é validar estratégia e não representa lucro.**

## Dados oficiais consultados para o esquema

- [Candles USD-M `/fapi/v1/klines`](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).
- [Funding USD-M com `markPrice`](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).
- [Melhor bid/ask USD-M `/fapi/v1/ticker/bookTicker`](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).

Próxima dependência técnica: fixar o código e as regras completas de **outro candidato economicamente distinto**, inclusive execução paper e saídas, antes de chamar qualquer observação futura de validação. A coleta pode registrar mercado agora, mas não retroage a data de congelamento do próximo alpha.
