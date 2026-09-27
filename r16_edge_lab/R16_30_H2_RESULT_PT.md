# R16.30 pesquisa H2 — short CORE no portfólio H1

**Decisão: rejeitar H2 neste protocolo histórico.** O motor vendido elevou o uso de capital, mas piorou retorno e drawdown nos cenários BASE e STRESS em comparação com H1. Nenhum dos dois candidatos se aproxima de 20% mensais compostos; nenhum foi validado em dados futuros intocados.

## Método e correção do motor

O [protocolo H2](R16_30_H2_PREREG_PT.md) foi registrado em `b57d53559b79e2e746ae4cd50c148ced82f20625` antes dos resultados. O motor estende o replay da R16.29.2 **apenas na branch de pesquisa** e acrescenta CORE_SHORT ao portfólio H1. A lógica dos alfas CORE/REV1H e seus parâmetros continuam congelados. O teste de regressão reproduziu os ledgers H1 integrais antes de ativar o short; foram executados testes de stop gap, candle ambíguo, payoff, funding e caixa para side −1.

Na primeira execução, uma asserção parou H2 porque uma entrada short atingiu exposição bruta/equity de 1,00000996. A causa foi aplicar ao short a conversão de slippage de entrada usada para longs; o notional marcado pela referência ficou maior do que o notional de fill. Corrigimos **somente o cap de entrada do motor de pesquisa** com o fator de marcação para side −1; os dois ledgers H1 continuaram byte a byte iguais. No replay final, a maior exposição de entrada ficou em torno de 1x (erro numérico da ordem de 10⁻¹⁶), e o maior risco de stop agregado observado ficou abaixo de 6%.

## Comparação retrospectiva de 66 meses

| Métrica | H1 BASE | H2 BASE | H1 STRESS | H2 STRESS |
|---|---:|---:|---:|---:|
| Retorno mensal composto | **1,32%** | 1,20% | **1,22%** | 1,00% |
| Retorno acumulado | **137,55%** | 119,22% | **123,34%** | 92,62% |
| Drawdown máximo MTM | **19,94%** | 23,59% | **21,88%** | 27,66% |
| Uso médio de capital | 9,83% | 13,22% | 10,08% | 12,84% |
| Operações fechadas | 776 | 977 | 783 | 974 |

Em H2, o CORE_SHORT fez 263 trades e **−385,17 USDT** líquidos no BASE; no STRESS, 254 trades e **−210,68 USDT**. Mais atividade e maior uso de capital não produziram melhor P&L. O portfólio H2 também mudou as posições CORE e REV1H em razão da caixa e da ordem de alocação compartilhadas; os números vêm do replay completo, não de somar carteiras isoladas.

Os dois replays finais H2 foram repetidos com ledger SHA-256 idêntico: BASE `d6282512d31fc63fd906e4151d60641bfc74b5e4839b426c4ccffc284489e4c4` e STRESS `8ed9fd5350606fc46407865aabbfdd821453f365c89f6dd4b21012b8ce9d9d60`. Um corte em 30/06/2023 coincidiu com os **98.697 eventos** do prefixo integral no BASE, inclusive após perturbar dados futuros. A prova é restrita à causalidade desses replays e não cria OOS estatístico.

Funding ainda depende de preços substitutos em parte do histórico (9.442 avaliações shadow/portfólio no BASE, 9.384 no STRESS). O Gate 3 completo do novo motor short **não foi aprovado**; os controles locais acima não substituem esse gate. Mesmo para H1, o invariante de funding e o OOS futuro permanecem pendentes. Não promover nenhuma dessas versões para paper ou dinheiro real.

Arquivos: [resultado JSON](R16_30_H2_RESULT.json), `r16_30_short_engine.py`, `r16_30_h2_replay.py` e artefatos completos de trades/diagnósticos entregues separadamente.
