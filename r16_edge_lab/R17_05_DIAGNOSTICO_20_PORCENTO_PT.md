# R17.05 — auditoria de estratégias e meta de 20% por mês

Relatório em 28/09/2026 UTC. `R16.24.2 – Portfolio Integration` continua sendo a última baseline validada do robô principal. Este diagnóstico não altera o robô ou a captura paper `R17.04` e não envia ordens reais.

## O que está medido, e o que falta

- Acervo local: 38 pares Binance USD-M no manifesto SHA-256 `a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041`; velas 15m, 1h, 4h e funding de 2021 a **30/06/2026**. São 152 arquivos conferidos por SHA pelo código do replay. Não há série local julho–setembro/2026. A coorte histórica não é livre de sobrevivência, e todo esse período já foi visto em pesquisas anteriores: resultados são diagnósticos retrospectivos, nunca validação OOS.
- R16.29.2 STRESS, pesquisa anterior (não baseline): 66 meses, melhor +14,79%, **0 meses >=20%**, equivalente mensal composto +0,79%, drawdown diário marcado 31,69%, exposição bruta média 10,98%. Em janeiro–junho/2026: +3,66%, +0,15%, −0,24%, −2,32%, −2,03%, −3,57%. Custo assumido sem conciliação efetiva da conta. Na mesma janela jan/2023–jun/2026, retorno composto da R16.29.2 STRESS +37,22%. [Métricas anteriores](https://github.com/sapuppo/IGOR/blob/r16-29-audit/r16_edge_lab/r16_29_2_audit/stress_metrics.json) podem ter caminho diferente na referência histórica; os valores estão nos artefatos locais `r16_29_2_audit/stress_metrics.json`.
- R17.00, momentum semanal neutro, falhou: −34,28% STRESS entre nov/2023–jun/2026; 433/556 posições pararam no stop, DD35,65%. Ganhos brutos insuficientes até antes de taxas. R17.04, rompimento na OKX, começou *apenas* coleta e paper, sem retorno mensal válido.

## Teste novo realizado sem alterar parâmetros após ver retorno

Protocolo `R17-RR7-BTC30-W1` [registrado antes da execução](https://github.com/sapuppo/IGOR/blob/r17-05-regime-rotation/r16_edge_lab/R17_05_REGIME_ROTATION_PROTOCOL_PT.md): entre quatro altcoins com força relativa de sete dias, comprar em tendência BTC positiva de 30 dias e vender as quatro mais fracas em tendência negativa. Rebalancear semanalmente, quatro posições de 15% cada, até 60% bruto, stop individual 5%, taxa 0,06% e derrapagem 0,04% por lado. Os sinais usam apenas velas encerradas antes da entrada. Operações apenas em paper simulado.

A execução originalmente prevista para 2021–jun/2026 **abortou sem produzir PnL** após detectar candle ausente numa posição VETUSDT em fevereiro/2022. Onze pares têm lacunas sincronizadas em fevereiro e abril/2022 até no histórico 15m. O addendum de integridade, registrado antes de qualquer retorno da estratégia, fixou o estudo `R17-RR7-BTC30-W1-DQ` para **jan/2023–jun/2026**, mantendo regras idênticas e marcando a escolha do recorte como limitação. Não se preencheu a lacuna com preço inventado.

| Medida, janela jan/2023–jun/2026 | R17.05 rotação (diagnóstico) | R16.29.2 STRESS (referência) |
| --- | ---: | ---: |
| Retorno acumulado | **−55,80%** | +37,22% |
| Saldo de 10.000 USDT | 4.419,74 USDT | não recalculado para mesmo capital nesta tabela |
| Melhor mês | +16,48% | até +14,79% no período total de 66 meses |
| Pior mês | −14,57% | até −13,12% no período total de 66 meses |
| Meses >=20% | **0/42** | 0/42 |
| Drawdown diário marcado | **64,73%** | 31,69% no período total de 66 meses |
| Posições encerradas | 688 (509 stops) | política diferente |
| Exposição bruta média diária | 21,74% | 10,98% no período total |

A R17.05 perdeu **mesmo antes** das deduções de 947,95 USDT em comissão presumida, ~631,96 USDT de derrapagem estimada e 285,39 USDT de funding proxy. O sinal vendido respondeu por −3.895 USDT das perdas líquidas, o comprado por −1.685 USDT. Houve 288 candles com stop e evento de funding cujo ordenamento intrabar é ambíguo; até 47,76 USDT de funding são afetados por essa ambiguidade estimada, insuficiente para mudar a conclusão. **Rejeitar R17.05.** O resultado não autoriza otimização retrospectiva para salvar a estratégia.

### 2026: porcentagens mensais simuladas, não retorno real

| Mês | R16.29.2 STRESS (referência) | R17.05-DQ |
| --- | ---: | ---: |
| Janeiro | +3,66% | −9,40% |
| Fevereiro | +0,15% | +0,99% |
| Março | −0,24% | −8,10% |
| Abril | −2,32% | −0,19% |
| Maio | −2,03% | −6,55% |
| Junho | −3,57% | +1,23% |
| Julho–setembro | dados não disponíveis nesta base | dados não disponíveis nesta base |

Os números de R17.05 são **proxy**: o funding usa o fechamento da vela como substituto da marca oficial e não há série histórica de bid/ask, impacto no livro ou tarifa real da conta. Os valores não demonstram retornos executáveis. [Replay completo, 688 trades](https://github.com/sapuppo/IGOR/blob/r17-05-regime-rotation/r16_edge_lab/R17_05_REGIME_ROTATION_DIAGNOSTIC.json) e [código](https://github.com/sapuppo/IGOR/blob/r17-05-regime-rotation/r16_edge_lab/run_r17_05_regime_rotation.py), congelado para o teste.

## Estratégia concreta para procurar vantagem, sem prometer rendimento

1. **Manter a candidata R17.04 em paper**, com BTC como filtro, rompimento em 4h, 35 swaps OKX, book/funding públicos reais, 10% do patrimônio por posição e limite de 40% bruto; registrar cobertura dos ciclos, slippage estimada e meses individualmente. Essa hipótese ainda não foi demonstrada lucrativa. Nenhum aumento de exposição até validar ganhos líquidos prospectivos.
2. **Investigar uma fonte de retorno estrutural distinta**: posição spot comprada e swap vendido para receber funding em períodos positivos. Requer histórico sincronizado de spot e perp, preço de marca no instante do financiamento, comissão nas duas pernas, margens e risco de liquidação. Candle isolado e taxa de funding não bastam para comprovar arbitragem. Também considerar formação de mercado apenas depois de obter livro L2 e trades para modelar fila e fills; sem esses dados, não chamar spread teórico de lucro.
3. **Estabelecer porta mensurável para cada estratégia futura**: regras e custo congelados antes de observações novas; >=180 dias prospectivos completos; >=100 operações encerradas; patrimônio marcado e funding/custos reconciliáveis; lucro líquido positivo, drawdown <=15%, e publicar mediana mensal, pior mês e quantidade de meses >=20%. Se falhar, rejeitar o candidato, não multiplicar alavancagem para forçar a meta.

**Conclusão:** 20% ao mês por 12 meses equivalem a ~792% ao ano composto. As estratégias testadas até aqui **não** entregaram essa consistência. A exposição média pequena da R16 não é licença para alavancar: seu drawdown de 31,69% já excede o limite prudente de 15%, e a rotação com exposição maior perdeu capital. Nenhuma estratégia nova deve substituir a R16.24.2 ou negociar capital real neste estágio.
