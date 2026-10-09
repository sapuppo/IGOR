# R17.13 — rejeição de estratégias

Data: 9/10/2026. **Nenhuma das oito alternativas justifica substituir a carteira atual.** Foram 16 execuções: oito variantes, cada uma com custos normais e dobrados. A baseline R16.24.2 e o paper R17.12 não foram modificados.

## Resultados — janeiro de 2023 a junho de 2026

Retorno mensal = média geométrica de todo o período; não é promessa de retorno recorrente. DD = maior queda da equity marcada a cada 4 horas. Valores em %.

| Variante | Mensal | Mensal custos 2× | DD | 2023–2024 | 2025 | Jan–jun/2026 |
|---|---:|---:|---:|---:|---:|---:|
| filtered_breakout_long_3_18 | -2.02 | -3.62 | 66.94 | -51.41 | -7.80 | -5.21 |
| filtered_breakout_long_5_42 | -0.76 | -1.60 | 49.75 | -15.44 | -3.03 | -11.64 |
| filtered_breakout_short_3_18 | 0.38 | -0.51 | 26.07 | -20.87 | 15.70 | 27.90 |
| filtered_breakout_short_5_42 | -0.15 | -0.80 | 41.41 | -32.45 | -3.76 | 44.62 |
| trend_pullback_long_3_18 | -4.70 | -6.88 | 88.77 | -66.20 | -51.62 | -19.16 |
| trend_pullback_long_5_42 | -1.10 | -2.51 | 73.75 | 30.36 | -41.20 | -18.14 |
| trend_pullback_short_3_18 | 0.83 | -0.47 | 34.49 | -8.24 | 15.77 | 33.22 |
| trend_pullback_short_5_42 | 1.04 | 0.11 | 39.61 | 4.01 | 34.72 | 10.00 |

## O que está ruim

- Rompimentos filtrados e recuos em tendência para compras perderam dinheiro no período completo. Devem ser rejeitados nestas configurações.
- A melhor alternativa de venda ficou em 1,04% ao mês com DD de 39,61%. O lucro médio caiu para 0,11% ao dobrar custos. Isso é uma relação retorno/risco ruim; não representa avanço sobre a referência híbrida de 1,38% ao mês.
- As variantes mais rentáveis em 2026 falharam em outros períodos. Escolhê-las porque 2026 ficou bonito seria selecionar o resultado retrospectivamente.
- SHORT20D original: 564 operações, acerto de 39,36% e profit factor de 1,065 após custos. O lucro histórico de US$ 2.651 é pequeno frente às perdas brutas das operações perdedoras. O teste anterior de custos dobrados já havia eliminado seu ganho total.
- CORE/REV1H original: 507 operações e profit factor de 1,353. É melhor que o short nesse diagnóstico, mas o ritmo de retorno permanece distante da meta. Não houve novo teste de custos desse componente nesta etapa.

Não existe evidência nesta rodada que sustente buscar 20% mensais por aumento de exposição ou troca para uma dessas variantes. Aumentar alavancagem não corrige a instabilidade constatada.

## Critérios e verificação

O protocolo foi escrito antes de executar esta rodada. A escolha usaria apenas 2023–2024: retorno positivo e DD diário de no máximo 20%. Nenhuma variante foi elegível. Também se exigiria desempenho positivo em 2025 e no primeiro semestre de 2026, inclusive no cenário de custos dobrados. Não há promoção para operação.

Os 76 arquivos efetivamente usados — 38 séries de 4h e 38 de funding — tiveram SHA verificado contra o manifesto original. A reconciliação capital inicial + resultados líquidos = saldo final passou nas 16 execuções. Retirar os dados futuros não alterou os sinais anteriores nas oito variantes verificadas.

Há um bloqueio adicional na base completa: TAOUSDT de 15 minutos tem hash divergente. Os outros 151 arquivos passaram. Não foi encontrada cópia original nos dois caminhos consultados do repositório. O arquivo divergente foi preservado e seu hash esperado não foi alterado. Ele não entra nesses testes de 4h, mas a base completa não está liberada para o paper.

Limitações: dados de 2023 a junho/2026 já consultados, universo previamente selecionado de 38 moedas, funding com preço de fechamento como proxy, ausência de book histórico, stops em OHLC com prioridade pessimista no caso ambíguo. Esta é pesquisa retrospectiva, não validação fora da amostra. A fonte pública já apresentou HTTP 451; nenhum paper contínuo foi iniciado nesta rodada.

## Decisão

**Rejeitar as oito alternativas nesta configuração.** Não alterar a carteira para encaixar o melhor mês. Manter os resultados ruins no registro de tentativas.

Próxima investigação útil: conferir concentração do lucro por moeda e regime e testar se a vantagem de CORE/REV1H sobrevive ao retirar seus principais contribuintes. Uma hipótese nova só merece paper depois de passar por custos, estabilidade entre períodos e limites de perda. A recuperação do arquivo divergente e a atualização da fonte continuam pendentes.

Os retornos mensais individuais, inclusive janeiro a junho de 2026, estão em `r17_13_results/summary.json`. Não há dados ou percentuais apurados para julho a outubro de 2026.
