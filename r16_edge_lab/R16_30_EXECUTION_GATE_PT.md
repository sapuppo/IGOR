# R16.30 — reconciliação prospectiva de execução USD-M

**Estado em 27/09/2026: `BLOCKED_NO_ACCOUNT_EXECUTIONS`.** O histórico H1 contém fills *simulados*. Nesta etapa não havia um conjunto independente de ordens submetidas, fills USD-M e extrato completo de conta no mesmo intervalo. Os testes sintéticos passam, mas não são evidência de execução nem de lucro. A baseline identificada pelo usuário como R16.24.2 permanece intacta; H1 continua pesquisa retrospectiva `TECHNICALLY_INVALID`, sem OOS e sem promoção.

## Entrega e critérios

O script `r16_30_execution_reconcile.py` recebe **três arquivos independentes** para um período prospectivo de uma conta dedicada à estratégia. Executa somente leitura local. Retorna `SAMPLE_RECONCILED` se as ordens estiverem completas, cada fill casar por ID e símbolo/lado, cada posição fechar, os valores de PnL concordarem, e a conta e a cobertura de exportação forem declaradas. Toda divergência e toda falta de evidência produzem `BLOCKED` (exit code 2). A aprovação cobre **apenas a amostra recebida**.

| Arquivo | Origem | Campos necessários |
|---|---|---|
| `plans.csv` | Registro do executor **feito antes do fill**, uma linha por ordem submetida | `position_id,leg,symbol,side,exchange_order_id,submit_ts_ms,reference_price,planned_qty,sim_fee_usdt`; `leg` = ENTRY/EXIT, UTC em milissegundos, preço de referência na decisão, taxa *estimada* da mesma ordem |
| `trades.json` | Array completo de `GET /fapi/v1/userTrades` da conta USD-M | `id,orderId,symbol,side,time,qty,price,commission,commissionAsset,realizedPnl`; acumular todas as páginas de todos os símbolos; preencher ordens parcialmente executadas |
| `income.json` | Array completo de `GET /fapi/v1/income` da mesma conta e período | `tranId,incomeType,income,asset,time,symbol`; **todos** os tipos, inclusive `FUNDING_FEE`, `COMMISSION`, `REALIZED_PNL` e quaisquer outros lançamentos |

Exemplo, após coleta local e revisão do período UTC:

```bash
python3 r16_30_execution_reconcile.py \
  --plans plans.csv --trades trades.json --income income.json \
  --start-ms <inicio_utc_ms> --end-ms <fim_utc_ms> \
  --complete-trades --complete-income --isolated-account \
  --out reconciliacao.json
```

Se um valor de funding previsto tiver sido gravado **antes** da liquidação, incluir `--expected-funding-usdt <valor>` para exigir concordância da previsão com o extrato em até 0,0001 USDT. O relatório também calcula PnL a preços de referência, desvio total de execução e diferença entre comissão prevista e cobrada. Divergência de taxa da simulação é um dado a investigar, não um passe automático para o modelo.

Os três indicadores de cobertura só podem ser usados quando todas as páginas estiverem exportadas e a conta/subconta não contiver operações de outra estratégia. Uma exportação de `Order History` não substitui as execuções individuais: ordens canceladas e parcialmente preenchidas precisam de documentação e não recebem aprovação neste verificador. Se taxas forem em BNB ou PnL/funding em ativo diferente de USDT, o programa bloqueia até existir conversão em USDT com taxa e instante documentados. Não enviar senhas, chave de API ou extrato com identificação pessoal desnecessária.

Registre também rejects, cancelamentos, alterações de ordem e book/quote no instante de envio em coleta independente para investigar spread, latência e oportunidade perdida. **O script atual mede desvio do preço de referência e comissões de ordens preenchidas; não valida por si só spread observado, filtros históricos, margem ou liquidação.** Seu PnL em USDT é da *amostra de posições fechadas* somado ao funding da conta isolada; rebates e outros lançamentos impedem reconciliação simples.

## Resultado observável nesta etapa

| Checagem | Resultado |
|---|---|
| Código de reconciliação local e 6 cenários sintéticos | PASS: fill parcial, slippage desfavorável, fee e funding, falta de fill, lançamento divergente, taxa não USDT, ordem sem vínculo e extratos vazios |
| Intenções prospectivas + IDs de ordens submetidas pelo IGOR | Ausentes |
| Extratos de fills e todos os tipos de income da conta | Ausentes |
| Comparação simulador × execução real | `BLOCKED_NO_ACCOUNT_EXECUTIONS` |
| Invariante histórico de markPrice de funding R16.29.2 | Ainda bloqueado, independente deste verificador |
| Validade técnica geral / OOS / aptidão a operar capital | `TECHNICALLY_INVALID` / falso / não aprovada |

## Próxima coleta objetiva

1. Fixar o executor, registrar `plans.csv` de forma causal no início de cada ordem prospectiva e guardar o ID retornado. Não remontar planos a partir dos fills.
2. Coletar os trades e o extrato financeiro em conta ou subconta isolada, com as três listas completas e limites UTC iguais; solicitar registros que incluam fills parciais. A documentação de API consultada informa que os endpoints de consultas usuais só trazem os três meses mais recentes e que `userTrades` usa janelas máximas de sete dias; programar exportações antes de perder a janela.
3. Rodar o script e investigar cada `BLOCKED` com o extrato original. Só depois de resolver o funding histórico no seu próprio gate técnico, congelar um candidato e iniciar o período futuro predefinido de 180 dias e ao menos 100 trades fechados. Se 100 trades não ocorrerem, o resultado segue inconclusivo.

**Fontes oficiais consultadas em 27/09/2026:** [Binance USD-M Account Trade List](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List), [Get Income History](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Get-Income-History), [exportar histórico de ordens USD-M](https://www.binance.com/en/support/faq/detail/e21b95dc590e4c13b8f8bdcc9bbc4f82). A evidência de pesquisa e decisões anteriores está em `R16_30_DECISION_PT.md` e nos artefatos R16.29.2.
