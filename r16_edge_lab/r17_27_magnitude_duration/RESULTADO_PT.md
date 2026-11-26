# R17.27 — resultado dos testes de magnitude e duração

**Concluído em 26/11/2026.** Pesquisa isolada na branch `research-r17-27-magnitude-duration`. Objetivo: verificar se estimar ganho, perda e duração e aumentar os horizontes supera a R17.26. Meta de 5% a 10% ao mês é apenas critério de pesquisa.

**Seleção congelada antes do replay de novembro: CAIXA. Critério histórico de meta aprovado: não. Nenhuma alteração promovida à versão principal.**

## Comparação líquida: julho a outubro de 2026

Retorno total compreende 123 dias. Mensal equivalente usa `(1+retorno_total)^(30,4375/dias)-1`; não significa que cada mês rendeu esse valor. Taxas, spread, slippage e funding estão incluídos. Caixa não negocia, portanto não demonstra vantagem preditiva.

| Variante | Total líquido | Mensal equivalente | DD máximo | Sharpe | Profit factor | Trades | Meses positivos | Total com custos 2x |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Probabilidade + ganhos/perdas médios | -9.875% | -2.540% | 10.296% | -4.400 | 0.362 | 180 | 0/4 | +0.000% |
| Ganho/perda previstos | -6.771% | -1.720% | 8.670% | -3.520 | 0.553 | 171 | 1/4 | +0.125% |
| Ganho/perda + duração | -6.771% | -1.720% | 8.670% | -3.520 | 0.553 | 171 | 1/4 | +0.125% |
| Ganho/perda + duração + book | -6.058% | -1.535% | 8.150% | -3.354 | 0.604 | 196 | 2/4 | -0.385% |
| Retorno direto + duração + book | -17.345% | -4.604% | 19.877% | -5.542 | 0.576 | 633 | 1/4 | -6.272% |
| Retorno direto com penalização | +0.000% | +0.000% | 0.000% | 0.000 | — | 0 | 0/4 | +0.000% |
| Ganho/perda + duração + book, sem pausas | -5.802% | -1.468% | 7.779% | -3.109 | 0.652 | 213 | 2/4 | -0.385% |
| Momentum determinístico | -56.590% | -18.657% | 56.593% | -21.136 | 0.423 | 2971 | 0/4 | -59.141% |
| Referência de impulso de volume | +0.194% | +0.048% | 3.430% | 0.141 | 1.044 | 28 | 1/4 | -0.563% |
| Modelo com book: somente 30 min | +0.179% | +0.044% | 0.430% | 1.723 | 1.483 | 5 | 1/4 | +0.000% |
| Modelo com book: somente 60 min | +1.292% | +0.318% | 0.496% | 3.582 | 2.925 | 16 | 2/4 | +0.050% |
| Modelo com book: somente 180 min | -6.775% | -1.721% | 8.432% | -3.884 | 0.557 | 193 | 2/4 | -0.435% |

## Retornos mensais efetivamente observados

**Novembro cobre apenas 1 a 24/11/2026 (UTC).** Nenhum resultado do restante de novembro ou de dezembro foi observado. Os demais meses de 2026 não fazem parte desta avaliação; dezembro/2025 a junho/2026 fornecem histórico e treino.

| Variante | Julho | Agosto | Setembro | Outubro | Novembro parcial | Nov. custos 2x |
|---|---:|---:|---:|---:|---:|---:|
| Probabilidade + ganhos/perdas médios | -0.407% | -8.440% | +0.000% | -1.165% | +0.000% | +0.000% |
| Ganho/perda previstos | +0.719% | -5.465% | -0.523% | -1.571% | +0.133% | +0.000% |
| Ganho/perda + duração | +0.719% | -5.465% | -0.523% | -1.571% | +0.133% | +0.000% |
| Ganho/perda + duração + book | +0.276% | -5.623% | +0.217% | -0.950% | -0.316% | +0.000% |
| Retorno direto + duração + book | +1.716% | -3.937% | -7.623% | -8.428% | -9.641% | -5.193% |
| Retorno direto com penalização | +0.000% | +0.000% | +0.000% | +0.000% | +0.000% | +0.000% |
| Ganho/perda + duração + book, sem pausas | +0.276% | -4.835% | +0.217% | -1.503% | -0.316% | +0.000% |
| Momentum determinístico | -20.018% | -15.850% | -20.047% | -19.330% | -16.604% | -20.054% |
| Referência de impulso de volume | -0.471% | +3.187% | -1.302% | -1.153% | +1.962% | +1.772% |
| Modelo com book: somente 30 min | +0.000% | +0.179% | +0.000% | +0.000% | +0.219% | +0.000% |
| Modelo com book: somente 60 min | +0.000% | +0.674% | +0.000% | +0.614% | +0.043% | +0.000% |
| Modelo com book: somente 180 min | +0.276% | -5.763% | +0.217% | -1.560% | -0.577% | +0.000% |

## O que cada mudança entregou

As diferenças abaixo usam os mesmos dados, limites de risco e custos entre os componentes, salvo a retirada explícita das pausas. Modelos sem book e com book usam as mesmas linhas válidas de book, inclusive no treino; assim a diferença não vem de negociar em calendários diferentes. Os intervalos são bootstrap pareado de blocos de sete dias, 500 trajetórias; são descritivos e não corrigem seleção entre modelos ou reutilização do histórico.

| Componente acrescentado | Diferença de retorno total (p.p.) | Intervalo descritivo de 95% (p.p.) |
|---|---:|---:|
| Ganho/perda previstos versus Probabilidade + ganhos/perdas médios | +3.104 | [-1.051; +7.251] |
| Ganho/perda + duração versus Ganho/perda previstos | +0.000 | [+0.000; +0.000] |
| Ganho/perda + duração + book versus Ganho/perda + duração | +0.713 | [-3.951; +6.950] |
| Retorno direto + duração + book versus Ganho/perda + duração + book | -11.286 | [-22.580; -1.197] |
| Retorno direto com penalização versus Retorno direto + duração + book | +17.345 | [+7.123; +28.165] |
| Ganho/perda + duração + book versus Ganho/perda + duração + book, sem pausas | -0.256 | [-2.017; +1.470] |

## Qualidade preditiva fora do treino

RMSE de retorno é medido em R bruto por oportunidade, antes dos custos. A referência constante é estimada apenas no mês de calibração. Ganhar em RMSE médio não prova rentabilidade nas poucas oportunidades escolhidas. Duração compara MAE em minutos com duração constante da calibração.

| Janela | Horizonte | Features | RMSE direto | RMSE constante | RMSE condicional | MAE duração | MAE constante | Brier | Brier constante |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-07 | 30 min | price | 0.7724 | 0.7719 | 0.7721 | 5.29 | 5.78 | 0.2492 | 0.2497 |
| 2026-07 | 30 min | book | 0.7724 | 0.7719 | 0.7722 | 5.26 | 5.78 | 0.2493 | 0.2497 |
| 2026-07 | 60 min | price | 0.8799 | 0.8799 | 0.8796 | 13.88 | 13.94 | 0.2482 | 0.2492 |
| 2026-07 | 60 min | book | 0.8797 | 0.8799 | 0.8799 | 13.68 | 13.94 | 0.2483 | 0.2492 |
| 2026-07 | 180 min | price | 0.9491 | 0.9512 | 0.9493 | 49.82 | 49.23 | 0.2452 | 0.2477 |
| 2026-07 | 180 min | book | 0.9490 | 0.9512 | 0.9496 | 49.74 | 49.23 | 0.2451 | 0.2477 |
| 2026-08 | 30 min | price | 0.7187 | 0.7165 | 0.7179 | 4.07 | 4.87 | 0.2496 | 0.2497 |
| 2026-08 | 30 min | book | 0.7192 | 0.7165 | 0.7178 | 4.04 | 4.87 | 0.2494 | 0.2497 |
| 2026-08 | 60 min | price | 0.8336 | 0.8281 | 0.8318 | 11.34 | 13.08 | 0.2504 | 0.2495 |
| 2026-08 | 60 min | book | 0.8338 | 0.8281 | 0.8315 | 11.28 | 13.08 | 0.2501 | 0.2495 |
| 2026-08 | 180 min | price | 0.9721 | 0.9573 | 0.9646 | 45.93 | 49.01 | 0.2507 | 0.2487 |
| 2026-08 | 180 min | book | 0.9714 | 0.9573 | 0.9650 | 45.77 | 49.01 | 0.2503 | 0.2487 |
| 2026-09 | 30 min | price | 0.7944 | 0.7927 | 0.7935 | 5.19 | 4.98 | 0.2491 | 0.2496 |
| 2026-09 | 30 min | book | 0.7944 | 0.7927 | 0.7935 | 5.08 | 4.98 | 0.2491 | 0.2496 |
| 2026-09 | 60 min | price | 0.8873 | 0.8848 | 0.8861 | 13.13 | 13.10 | 0.2489 | 0.2491 |
| 2026-09 | 60 min | book | 0.8874 | 0.8848 | 0.8859 | 12.80 | 13.10 | 0.2489 | 0.2491 |
| 2026-09 | 180 min | price | 0.9684 | 0.9608 | 0.9639 | 44.13 | 48.86 | 0.2478 | 0.2478 |
| 2026-09 | 180 min | book | 0.9683 | 0.9608 | 0.9637 | 42.44 | 48.86 | 0.2477 | 0.2478 |
| 2026-10 | 30 min | price | 0.7524 | 0.7510 | 0.7517 | 4.52 | 5.21 | 0.2491 | 0.2498 |
| 2026-10 | 30 min | book | 0.7521 | 0.7510 | 0.7516 | 4.30 | 5.21 | 0.2491 | 0.2498 |
| 2026-10 | 60 min | price | 0.8569 | 0.8551 | 0.8569 | 12.23 | 13.47 | 0.2494 | 0.2496 |
| 2026-10 | 60 min | book | 0.8567 | 0.8551 | 0.8561 | 11.96 | 13.47 | 0.2492 | 0.2496 |
| 2026-10 | 180 min | price | 0.9723 | 0.9674 | 0.9699 | 44.85 | 48.43 | 0.2478 | 0.2485 |
| 2026-10 | 180 min | book | 0.9697 | 0.9674 | 0.9692 | 43.98 | 48.43 | 0.2473 | 0.2485 |
| 2026-11 | 30 min | price | 0.8451 | 0.8418 | 0.8433 | 5.80 | 5.53 | 0.2495 | 0.2495 |
| 2026-11 | 30 min | book | 0.8453 | 0.8418 | 0.8434 | 5.83 | 5.53 | 0.2495 | 0.2495 |
| 2026-11 | 60 min | price | 0.8951 | 0.8928 | 0.8943 | 13.05 | 13.52 | 0.2492 | 0.2492 |
| 2026-11 | 60 min | book | 0.8950 | 0.8928 | 0.8944 | 13.12 | 13.52 | 0.2491 | 0.2492 |
| 2026-11 | 180 min | price | 0.9548 | 0.9418 | 0.9465 | 42.47 | 48.35 | 0.2487 | 0.2484 |
| 2026-11 | 180 min | book | 0.9544 | 0.9418 | 0.9484 | 42.52 | 48.35 | 0.2494 | 0.2484 |

## Decomposição financeira (julho a outubro)

Capital inicial de referência: 10.000 unidades de cotação. Agregados encadeados; PnL de preço já contém spread e slippage. Líquido = PnL de preço − taxas + funding. Valores em unidades de cotação.

| Variante | PnL preço após execução | Taxas | Funding | Líquido | Trades 30/60/180 min |
|---|---:|---:|---:|---:|---|
| Probabilidade + ganhos/perdas médios | -746.68 | 241.26 | 0.45 | -987.49 | 0/13/167 |
| Ganho/perda previstos | -416.28 | 260.36 | -0.46 | -677.10 | 2/9/160 |
| Ganho/perda + duração | -416.28 | 260.36 | -0.46 | -677.10 | 3/8/160 |
| Ganho/perda + duração + book | -303.28 | 302.74 | 0.22 | -605.81 | 0/5/191 |
| Retorno direto + duração + book | -810.42 | 926.70 | 2.66 | -1734.46 | 9/22/602 |
| Retorno direto com penalização | 0.00 | 0.00 | 0.00 | 0.00 | 0/0/0 |
| Ganho/perda + duração + book, sem pausas | -250.99 | 328.84 | -0.42 | -580.24 | 1/7/205 |
| Momentum determinístico | -2721.98 | 2931.77 | -5.28 | -5659.03 | 0/0/2971 |
| Referência de impulso de volume | 46.09 | 23.78 | -2.94 | 19.37 | 0/0/0 |
| Modelo com book: somente 30 min | 24.55 | 6.67 | 0.00 | 17.88 | 5/0/0 |
| Modelo com book: somente 60 min | 153.46 | 24.26 | 0.00 | 129.21 | 0/16/0 |
| Modelo com book: somente 180 min | -379.33 | 298.32 | 0.11 | -677.54 | 0/0/193 |

## Diagnóstico direto e decisão

**Não chegamos perto de 5% a 10% ao mês. A maioria das alternativas perdeu dinheiro. Não recomendo incorporá-las ao robô principal.**

1. O horizonte isolado de 60 minutos foi o melhor indício: +1,292% em julho–outubro, equivalente a +0,318% ao mês, DD de 0,496% e PF de 2,925. Porém foram só 16 operações e apenas dois meses positivos. Em novembro parcial ganhou +0,043% com uma única operação. No cenário 2x, o filtro passa a aceitar apenas uma operação no período de desenvolvimento, que ganhou +0,050%; isso não é evidência robusta e tampouco é estresse da mesma lista fixa de trades. Não ampliar posição nem alavancagem com essa amostra.
2. Estimar ganho/perda reduziu o prejuízo de −9,875% para −6,771% no desenvolvimento. Dividir pela duração não mudou as operações nem o resultado nessa comparação. Acrescentar book melhorou para −6,058%, ainda ruim; os intervalos pareados dessas melhorias incluem zero.
3. A regressão direta piorou para −17,345% e −9,641% em novembro parcial. O erro médio de previsão de retorno é pior que o de uma média constante da calibração. Há falha de generalização e superestimação das oportunidades aceitas; aumentar árvores, operar mais ou alavancar não resolve essa evidência. A duração foi estimada melhor que a constante, mas isso não se converteu em lucro.
4. O horizonte de três horas respondeu por 191 das 196 operações do modelo combinado e perdeu −6,775% quando isolado. Esse resultado domina a combinação; 30 minutos teve só cinco trades no desenvolvimento. A prioridade de investigação futura é uma réplica independente do teste de 60 minutos, não promover retrospectivamente o melhor recorte.
5. O momentum determinístico perdeu −56,590% no agregado das quatro avaliações mensais e deve ser descartado nessa formulação. O risco corta perdas em cada janela, mas não cria vantagem. O agregado pode passar de 20% porque o estado de risco reinicia mensalmente; não é um circuit breaker contínuo de produção.
6. A penalização conservadora não aceitou nenhuma ordem. Retorno zero aqui significa abstenção, não desempenho de um robô lucrativo.

**O que incorporar agora:** somente infraestrutura de previsão de magnitudes/duração, diagnóstico por horizonte, verificação causal/contábil e relatórios como ferramentas de pesquisa isoladas. Nenhum sinal novo foi aprovado para produção. **Próxima hipótese justificável:** congelar a política de 60 minutos sem ajustes e medir novas oportunidades em dados ainda não consultados e paper contínuo com custos reais; exigir amostra bem maior e estabilidade antes de qualquer integração. Não existe resultado desta rodada que justifique prometer retorno exponencial.


## Método e dados

- BTCUSDT, ETHUSDT e SOLUSDT em futuros USDT-M: 1.550.880 candles de um minuto entre 01/12/2025 e 24/11/2026. Book público real desde abril: 1.994.457 snapshots. 837 ZIPs oficiais com SHA256 verificado; três arquivos de book de 08/10/2026 indisponíveis. Fontes e hashes na R17.26 e em `INPUT_HASHES.json`.
- Trinta conjuntos horizonte/features, cada um com cinco modelos: classificador, ganho condicional, perda condicional, duração e retorno direto. Total de 150 modelos LightGBM, mais calibração sigmoide. 132 árvores por cabeça; hiperparâmetros fixados antes de conhecer estes resultados.
- Treino móvel de dois meses, calibração de um mês, teste no mês seguinte; expurgo de 181 minutos em ambas as fronteiras, todos os ativos/direções agrupados no tempo. Nenhuma feature usa preço após a decisão. Entradas com um minuto de atraso.
- Stop por ATR escalado à raiz do horizonte, limitado a 0,3%–2%; alvo 2R; encerramento em 30/60/180 minutos. Dimensionamento por risco de 0,25%, teto 20% por ativo, exposição bruta 60%, até três posições, sem alavancagem. Controle preserva limite original de 15%.
- Pausa após três perdas, redução de risco com DD de 8%, parada a 20% e perda diária de 4%. Os tetos são gatilhos; custos e gaps podem ultrapassá-los. O estado reinicia em cada avaliação mensal.
- Cenário normal por lado: taxa de 0,06%, meio spread de 0,02%, slippage de 0,04%; custo estimado de ida e volta 0,24%, além de funding. Estresse dobra taxa e fricção. Ordens são taker; lote, tick, valor mínimo e limite de 0,1% do volume do minuto anterior são aplicados.
- Seleção entre sete candidatos usa apenas julho–outubro: PF >1,2; pelo menos 100 operações; três meses positivos; DD ≤20%; retorno superior ao controle e positivo no estresse. Três testes de horizonte isolado e a regra de momentum são diagnósticos, excluídos da seleção.

## Limitações e interpretação

**Todo esse histórico já foi consultado na R17.26.** A validação é cronológica fora do treino de cada janela, mas retrospectiva e não independente da pesquisa. Novembro foi separado da seleção desta rodada, porém também era conhecido em pesquisa anterior. Não chame estes resultados de prova prospectiva.

Spread/slippage são cenários; snapshots de book não reconstroem fila, latência real ou fills. Os filtros de execução são os atuais, não filtros históricos point-in-time. Funding utiliza preço de abertura como proxy de mark. O controle é o adaptador documentado da R17.26, sem alegar equivalência integral com a baseline de produção R16.24.2. O teste mensal liquida posições ao fim da janela e reinicia o risco; o encadeamento não representa execução contínua sem reinícios. Retornos não incluem impostos. Não houve execução com dinheiro real.

## Verificação e artefatos

17 testes unitários passaram; 120 replays reconciliados; 1800 labels confrontados com implementação escalar independente; três verificações causais em prefixes reais. Hashes dos cinco arquivos de modelos e previsões, expurgo temporal e drawdown conferidos por rotina independente, incluindo código MIT do Vibe-Trading.

- `protocol.json`: regras pré-definidas; `results/selection_before_final.json`: seleção congelada.
- `COMPARISON.json`, `FORECAST_DIAGNOSTICS.json` e `VERIFICATION.json`: métricas e evidência legíveis por máquina.
- `R17_27_RESULTS.zip`: código, cinco conjuntos completos de modelos, relatórios e todas as operações/curvas.
- `README.md`: reprodução; scripts herdados e licenças permanecem intactos na R17.26.
