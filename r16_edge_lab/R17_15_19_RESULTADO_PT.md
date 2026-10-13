# R17.15–R17.19 — busca de uma estratégia com 5% ao mês

Data: 12/10/2026. **Não encontramos estratégia que atinja 5% ao mês nos critérios registrados.** Foram 32 configurações novas e 64 replays com custos normais e dobrados. Os resultados negativos foram preservados. A baseline R16.24.2 e o executor R17.12 não foram alterados.

## O que mudou de verdade

- R17.15: novos sinais de rompimento de 20/55 barras, expansão após compressão de volatilidade, recuo em tendência e reversões de 1h; diferentes stops/alvos e duração.
- R17.16: reversão após extremos e reentrada nas bandas, com compras, vendas ou ambas.
- R17.17: hipótese oposta à R17.16, operando a favor do movimento anterior após um recuo; todos os fluxos foram simulados novamente. Não houve simples inversão do lucro.
- R17.18: seleção mensal por momentum de 30/90/180 dias, com compras ou compras/vendas, para reduzir giro.
- R17.19: rompimentos com stop móvel de 2/3/4 ATR, sem alvo fixo e duração máxima de 30/90 dias.

Cada rodada teve um protocolo escrito antes de executar suas variantes. As rodadas seguintes foram informadas pelos fracassos anteriores: isso precisa entrar na avaliação do risco de seleção. Não aumentamos alavancagem para fabricar 5%. As saídas e alocações específicas estão nos protocolos; as rodadas não têm modelos de execução idênticos.

## Resultados completos

Histórico: janeiro/2023 a junho/2026. Mensal = taxa composta equivalente em 42 meses. Não é retorno em todos os meses. DD é medido nos eventos do simulador de 15m na R17.15 e nas marcações de 4h nas demais; não compare as precisões como se fossem iguais. Percentuais de 2026 referem-se apenas ao primeiro semestre.

| Rodada / configuração | Mensal | Mensal custos 2× | DD | 2025 | Jan–jun/2026 |
|---|---:|---:|---:|---:|---:|
| R17.15 / breakout20_runner | 1.04% | 0.85% | 20.93% | -10.35% | 6.68% |
| R17.15 / breakout55_runner | 1.38% | 1.16% | 18.86% | 0.17% | 8.28% |
| R17.15 / squeeze20_runner | 0.31% | 0.08% | 34.97% | -3.36% | 0.41% |
| R17.15 / pullback_trend | -1.29% | -1.61% | 56.19% | -30.26% | -6.95% |
| R17.15 / reversal4 | -0.89% | -0.83% | 37.54% | -22.72% | -5.37% |
| R17.15 / reversal8_runner | 0.40% | 0.25% | 11.96% | 12.58% | 2.11% |
| R17.15 / pair_break20_rev4 | 1.07% | 0.41% | 25.74% | 4.53% | -4.80% |
| R17.15 / pair_squeeze_rev8 | 0.91% | 0.82% | 28.24% | 25.24% | 0.14% |
| R17.16 / band_reversion_long_3 | -2.99% | -3.92% | 73.01% | -21.27% | -19.15% |
| R17.16 / band_reversion_long_5 | -1.14% | -1.88% | 52.25% | 2.57% | -30.82% |
| R17.16 / band_reversion_short_3 | -2.66% | -4.19% | 73.88% | -23.63% | 11.27% |
| R17.16 / band_reversion_short_5 | -1.96% | -3.01% | 77.03% | -2.86% | 35.68% |
| R17.16 / band_reversion_both_3 | -5.13% | -7.41% | 89.69% | -34.07% | -5.98% |
| R17.16 / band_reversion_both_5 | -2.50% | -4.11% | 68.62% | 8.02% | -12.95% |
| R17.17 / continuation_3_6 | -1.32% | -3.70% | 53.62% | -30.97% | -9.52% |
| R17.17 / continuation_6_3 | -1.61% | -3.92% | 58.72% | -26.00% | -21.76% |
| R17.17 / continuation_5_10 | -0.11% | -1.91% | 49.50% | -31.58% | 4.51% |
| R17.17 / continuation_10_5 | -2.87% | -4.47% | 79.99% | -43.47% | -15.31% |
| R17.17 / continuation_btc_3_6 | -0.86% | -2.71% | 47.07% | -24.47% | 12.33% |
| R17.17 / continuation_btc_5_10 | 0.72% | -0.92% | 42.68% | -25.16% | 18.50% |
| R17.18 / monthly_mom_30d_long | 0.60% | 0.51% | 19.80% | 0.09% | 12.21% |
| R17.18 / monthly_mom_30d_both | 0.13% | -0.03% | 34.23% | -12.52% | 18.33% |
| R17.18 / monthly_mom_90d_long | 0.16% | 0.08% | 33.19% | -8.52% | 16.39% |
| R17.18 / monthly_mom_90d_both | -0.24% | -0.40% | 53.88% | -27.27% | 20.42% |
| R17.18 / monthly_mom_180d_long | -0.95% | -1.02% | 39.84% | -8.01% | 1.52% |
| R17.18 / monthly_mom_180d_both | -1.12% | -1.27% | 55.02% | -22.54% | 12.83% |
| R17.19 / trail2_hold180 | -2.12% | -3.28% | 69.98% | -22.46% | -14.01% |
| R17.19 / trail2_hold540 | -2.12% | -3.28% | 69.98% | -22.46% | -14.01% |
| R17.19 / trail3_hold180 | -0.12% | -0.72% | 63.41% | -20.47% | -8.99% |
| R17.19 / trail3_hold540 | -0.13% | -0.72% | 63.41% | -20.47% | -8.99% |
| R17.19 / trail4_hold180 | 1.92% | 1.23% | 58.29% | 5.33% | 10.93% |
| R17.19 / trail4_hold540 | 1.83% | 1.15% | 58.29% | 6.07% | 11.58% |

## O resultado menos ruim não é uma solução

O maior retorno médio foi 1.92% ao mês em `trail4_hold180`. Essa escolha usa todo o histórico e serve só como diagnóstico. O drawdown foi 58.29%, e a média caiu para 1.23% com custos dobrados. Uma carteira que perde mais da metade do patrimônio nesse modelo não é um resultado decente para a meta. Não foi selecionada nem promovida.

O rompimento de 55 barras com saídas longas da R17.15 ficou em 1,38% ao mês, DD de 18,86% e 1,16% ao mês com custos dobrados. Também ficou abaixo da referência CORE/REV1H de 1,54% ao mês no mesmo histórico. Sua alta de 8,28% em janeiro–junho de 2026 é um resultado retrospectivo, não prova de melhoria futura. Não escolhemos a variante porque esse semestre parece melhor.

## Critérios usados

Alvo inicial: média composta líquida de pelo menos 5% ao mês. Isso equivale a aproximadamente 79,6% ao ano se repetido e reinvestido, e é diferente de exigir 5% em cada mês.

Exigimos também retorno positivo na janela de seleção de 2023–2024, queda máxima de até 25% nessa janela, retorno positivo em 2025 e janeiro–junho/2026, queda máxima de até 25% no período completo e manutenção dos critérios completos no cenário de custos dobrados. A escolha de cada rodada usou apenas o retorno da janela de seleção entre os elegíveis. Nenhuma das cinco escolhas se qualificou para a meta. Esses limites são triagem definida para a pesquisa, não garantia de segurança.

Se a sua exigência for 5% em cada mês, nenhum resultado apresentado satisfaz isso. Não trocamos essa exigência por média sem explicitar a diferença.

## Verificação e limites

Os 152 arquivos de entrada passaram na comparação de hashes. Todos os novos grupos de sinais permaneceram iguais no passado ao retirar os dados futuros. A carteira reconciliou capital e resultados líquidos nas 64 execuções. Dois testes adicionais confirmaram que o stop móvel de compra e de venda só passa a valer na vela seguinte, sem saída retroativa na vela que forneceu a informação.

O mercado foi representado por OHLC histórico, não book de ordens. Funding usa taxas arquivadas e proxy de preço negociado; custos são hipóteses fixas, não extratos de conta. O universo fixo de 38 moedas tem viés de seleção, e o histórico já foi consultado muitas vezes. A diferença de monitoramento entre 15m e 4h é outra limitação. Não há validação fora da amostra independente nem lucro executado.

Nenhuma rodada usa dados posteriores a junho/2026. Os meses de julho a outubro não têm lucro calculado. Não foi ativado paper contínuo; permanece necessário atualizar os dados e dispor de acesso autorizado à fonte que anteriormente respondeu HTTP 451.

## Decisão

**Meta não atingida. Não substituir a baseline por nenhuma dessas configurações.** A maior parte das mudanças piorou o resultado, e a que elevou a média trouxe perda máxima inaceitável para o critério da rodada.

A busca não está concluída, mas continuar ajustando o mesmo histórico até aparecer um número bonito não confirma vantagem. O próximo marco de evidência deve ser ampliar/atualizar a base com universo reconstruído por data e reservar dados ainda não utilizados antes de testar novas hipóteses. Não há fundamento para prometer que mais tentativas produzirão 5% sustentáveis.

O pacote contém os cinco protocolos, código, séries de operações/equity e resumos. É um complemento ao repositório IGOR e exige seus módulos originais e histórico auditado para reprodução. Nenhum código real de envio de ordens foi incluído.
