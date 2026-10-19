# R17.21 — Auditoria e mudanças de risco/estratégia

## Resultado executivo

Auditoria concluída no motor de pesquisa usado nas R17.19–20. Não é auditoria integral de cada módulo da baseline R16.24.2 ou do executor ao vivo. 28 replays: 16 comparações de motor/risco, 4 benchmarks passivos e 8 testes de direção/controle. Sete testes de regressão passaram. Nenhuma candidata atingiu 15–20% ao mês. Baseline preservada; nenhuma ordem real.

## Achados corrigidos

1. O drawdown não era recalculado após as taxas/slippage da liquidação final. Agora inclui esse patrimônio final e zera a exposição terminal. Continua sendo drawdown de fechamento 4h, não máxima perda intrabar.
2. Funding exatamente na abertura era omitido em certas saídas e aplicado a posições novas naquela mesma abertura. Definida convenção explícita: posições preexistentes liquidam funding antes das saídas; entradas ocorrem depois. Usa preço de abertura como proxy, não mark oficial; ordenar eventos no mesmo instante é uma hipótese de simulação. Funding dentro da vela continua conservador em casos ambíguos.
3. Logs de trades não expunham quantidade, preços e taxas suficientes para conferência independente. Agora expõem preço de entrada/saída, quantidade, taxas por lado e P&L de preço, com reconciliação independente.

## Mudanças implementadas

- Stop inicial de 2 ATR da vela anterior, limitado a 2–12% do preço.
- Risco planejado por operação de 0,25% do patrimônio, incluindo estimativa de custos de ida e volta; não é teto garantido diante de gaps.
- Máximo de 15% por posição e exposição de entrada até 60%; quatro posições. Movimentos posteriores podem alterar a exposição.
- Pausa opcional de 24h por moeda após trade negativo, testada separadamente.
- Seleção de direção usando somente trades encerrados antes de 2025; avaliação com carteira nova em 2025, comparada com controle ambas direções igualmente reiniciado.

## Comparação janeiro 2023 a junho 2026

| Variante | Mensal composto | Queda máxima 4h | Mensal custos 2× |
|---|---:|---:|---:|
| trail55_legacy | 1.92% | 58.29% | 1.23% |
| trail55_corrected | 1.94% | 58.22% | 1.25% |
| trail55_risk | 0.66% | 11.47% | 0.50% |
| trail55_risk_cooldown | 0.62% | 12.16% | 0.46% |
| volume_impulse_legacy | 0.99% | 61.90% | -0.28% |
| volume_impulse_corrected | 1.02% | 61.72% | -0.25% |
| volume_impulse_risk | 0.65% | 11.89% | 0.40% |
| volume_impulse_risk_cooldown | 0.66% | 11.44% | 0.43% |
| BTCUSDT_passive_perpetual | 2.25% | 62.05% | 2.24% |
| ETHUSDT_passive_perpetual | -0.89% | 80.79% | -0.90% |

Benchmark passivo = compra e manutenção de contrato perpétuo BTC/ETH, exposição inicial 1×, funding e custos incluídos, sem rebalanceamento. Não é compra spot; não modela margens de manutenção ou liquidação e não é proposta de execução.

## Diagnóstico das perdas

No rompimento corrigido, os shorts somaram −5.663,75 e os longs +18.042,95, em unidades da conta simulada com capital inicial 10.000. Isso descreve o período inteiro e não autoriza excluir shorts retrospectivamente. No impulso, longs somaram −2.676,63 e shorts +7.968,14.

No impulso corrigido, saídas STOP somaram −118.966,64, TARGET +106.902,80 e TIME +17.355,35. São somas de centenas de trades com capital reutilizado, não percentuais da banca. Funding e taxas corroem uma vantagem já pequena. A redução de risco melhorou drawdown principalmente por menor exposição, não por criar previsão superior.

A correção de funding mudou o rompimento de 1,92% para 1,94% ao mês; não havia erro contábil escondendo uma estratégia de 20%.

## Direção congelada: janeiro 2025 a junho 2026

Seleção no período 2023–24 por soma de retorno líquido normalizado pelo notional, mínimo 30 trades e score positivo: rompimento LONG; impulso SHORT. Trades são os executados pela carteira de treino, não universo independente de todos os sinais.

| Estratégia | Direção | Mensal composto | DD 4h | Mensal custos 2× |
|---|---|---:|---:|---:|
| trail55 | Ambas (controle) | 0.58% | 6.22% | 0.39% |
| trail55 | Long | 0.24% | 5.31% | 0.15% |
| volume_impulse | Ambas (controle) | 0.29% | 10.48% | 0.11% |
| volume_impulse | Short | 0.46% | 7.27% | 0.36% |

Restringir rompimento a longs piorou retorno; não aprovado como melhoria. Impulso short melhorou retorno e risco versus controle no mesmo intervalo, mas é melhoria pequena, não solução para a meta. A pausa após perda não ajudou uniformemente e não deve virar regra universal.

## Validação e limites

152 arquivos passaram SHA256; replay original reproduziu exatamente os hashes de trades das duas estratégias, em ambos custos. Sinais e ATR passaram invariância ao remover futuro. Sete testes cobrem reconciliação independente, funding antes de saída, funding de entrada, drawdown terminal, stop antes de alvo ambíguo, dimensionamento e pausa após stop. Todos os replays reconciliaram caixa e trades.

Dados já consultados nas rodadas anteriores, universo fixo de 38 moedas: há viés de seleção/sobrevivência. O teste cronológico não é validação independente e não foi realizado walk-forward completo com diversas janelas. Não há livro histórico, mark de funding oficial nem validação contínua ao vivo. Resultados são simulações e retorno composto equivalente, não lucro garantido todo mês.

## Decisão

Manter as correções do motor e o dimensionamento por risco como infraestrutura de pesquisa. Manter impulso short como hipótese comparativa; rejeitar a restrição long do rompimento como ganho de desempenho. Nenhuma promoção ao robô principal. Meta permanece 15–20% ao mês. Próxima evidência necessária: dados ainda não usados e execução paper; não alegar que repetição de backtests resolve isso.
