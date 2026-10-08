# R17.08–R17.11 — pesquisa ampliada, 5 de outubro de 2026

**Conclusão:** os 22 novos testes de estratégia e quatro combinações de capital não produziram 20% mensais consistentes. O melhor candidato com queda inferior a 20% continua rendendo cerca de 1%–1,5% por mês no histórico. Mais alavancagem, alta rotatividade e escolha pelo melhor semestre de 2026 geraram quedas inaceitáveis. Nenhuma ordem real foi emitida; a baseline R16.24.2 permanece intacta.

## Resultado que muda 2026

As fontes de dados são as mesmas 38 moedas USD-M do histórico congelado, janeiro de 2023 a junho de 2026. Em R17.10, o rompimento de mínima de 20 dias vendido, stop 5%, alvo 10%, permanência máxima sete dias e até 1x bruto por carteira apresentou +24,12% no primeiro semestre de 2026, mas 41,33% de queda máxima na trajetória completa. O resultado acumulado do componente vendido foi +26,51%. A seleção desse componente usou o resultado de 2026 já conhecido: não constitui teste fora da amostra.

O modelo R17.11 dedica parcelas fixas e separadas da banca a esse componente e ao candidato R17.07 (tendência 4h + reversão 1h). Cada subcarteira mantém 1x de exposição máxima **na entrada** e contabiliza suas próprias operações, taxas e funding. Não há transferência nem rebalanceamento entre subcarteiras. A queda combinada foi medida nos fechamentos diários; picos dentro das velas podem ser piores.

| Carteira | Média composta mensal 2023–jun/2026 | Acumulado | Queda diária máxima | 2026 jan–jun | Meses ≥20% |
|---|---:|---:|---:|---:|---:|
| Controle R16.29.2 | 0,61% | +28,90% | 31,69% | -4,43% | 0/42 |
| R17.07 comprado | 1,54% | +90,31% | 18,74% | +0,29% | 0/42 |
| R17.11: 80% comprado + 20% vendido | 1,38% | +77,55% | 15,13% | +3,11% | 0/42 |
| R17.11: 60% comprado + 40% vendido | 1,20% | +64,79% | 12,81% | +6,57% | 0/42 |

A proporção 80/20 foi a escolhida pela regra de 2023–2024 registrada antes do cálculo das combinações: maior retorno nesse intervalo entre carteiras com queda diária até 20%. A 60/40 melhorou 2026, mas teve menor retorno na janela de seleção; não foi promovida apenas por ter se saído melhor nos dados recentes já conhecidos. A 20/80 deu +16,55% em 2026, mas teve resultado de treino negativo e queda de 24,76%.

## Ano de 2026 mês a mês

| Mês | Controle | R17.07 | 80/20 | 80/20 com custo dobrado na venda |
|---|---:|---:|---:|---:|
| 2026-01 | +3,66% | +1,85% | +2,61% | +2,38% |
| 2026-02 | +0,15% | +2,01% | +3,25% | +2,01% |
| 2026-03 | -0,24% | -0,49% | -1,15% | -1,04% |
| 2026-04 | -2,32% | -4,60% | -4,43% | -4,51% |
| 2026-05 | -2,03% | +2,24% | +2,91% | +2,68% |
| 2026-06 | -3,57% | -0,56% | +0,11% | -0,21% |

O histórico auditado termina em junho de 2026; não há resultado calculado para julho–dezembro. A média composta dos seis meses do híbrido 80/20 foi +0,51%, muito abaixo de 20% ao mês.

## As outras alternativas que foram testadas

**R17.08 — força relativa diária:** oito regras predeterminadas, incluindo compras, vendas, neutras, filtro BTC e 1,5x bruto. Todas perderam entre 54,99% e 99,21% do capital no período. As quatro posições compradas e quatro vendidas trocaram mais de 10 mil operações; essa frequência tornou taxas e slippage determinantes. Nenhuma passou no critério de seleção.

**R17.09 — manter posições enquanto continuassem no ranking:** sete regras com menor giro. A regra comprada de 20 dias terminou com +85,59% acumulados e dez meses acima de 20%, mas passou por uma queda de 82,37% e perdeu 50,63% no primeiro semestre de 2026. A regra filtrada pelo BTC ganhou 37,43% em 2026 após perda acumulada de 69,19% e queda máxima de 94,43%. Nenhuma passou no critério de seleção. Esses meses chamativos ilustram por que o alvo mensal sozinho é inadequado.

**R17.10 — rompimento de máximas/mínimas em 4 horas:** sete regras com stops, alvos, prazo máximo e compras/vendas. Apenas a venda da mínima de 20 dias fechou com ganho acumulado (+26,51%); sua queda de 41,33% inviabiliza uso isolado sob o limite de risco estabelecido. Nenhuma passou no critério de 2023–2024.

**R17.11 — quatro proporções fixas de capital:** 80/20, 60/40, 40/60 e 20/80. Somente 80/20, 60/40 e 40/60 satisfizeram retorno positivo e queda diária até 20% em 2023–2024; a 80/20 venceu pela regra predeterminada. Essa seleção ainda sofre contaminação porque o componente vendido foi escolhido depois de observados os resultados de 2026.

## Custos e robustez

Nos replays comuns: comissão de 0,06% e slippage adverso de 0,04% por lado, com execução na abertura seguinte ao sinal; funding histórico por aproximação de preço negociado. O custo dobrado aplica comissão 0,12% e slippage 0,08% por lado **à estratégia vendida**, mantendo o componente R17.07 com seus custos originais. Resultado vendido: acumulado -12,74%, queda 44,68%, 2026 +8,95%. O híbrido 80/20 cai para 1,27% mensais compostos e +1,11% em 2026; queda diária de 15,69%. Sem a série oficial completa de mark price e book de ofertas, o cálculo de funding e spread ainda exige validação operacional.

## Conferência e limites

O manifesto dos 152 arquivos foi verificado pelo carregador. A auditoria independente `r17_11_results/verification.json` conferiu 26 carteiras: patrimônio final versus soma líquida das operações, 1.277 dias e 42 meses, composição dos retornos mensais e pesos segregados. Cada replay verificou a ausência de barras faltantes em posições abertas. Os seis meses de 2026 continuam expostos no relatório, sem preencher dados ausentes do restante do ano.

Todos os resultados são simulações retroativas de uma coorte previamente selecionada de 38 moedas. 2023–2026 já haviam sido consultados em pesquisas anteriores; o componente vendido foi explicitamente escolhido olhando 2026. A taxa histórica de sucesso de 20% por mês não é inferível desses replays. Como referência matemática, manter 20% compostos por 12 meses exigiria 791,61% no ano. A pesquisa não demonstrou vantagem com esse perfil e limite de queda; rodar indefinidamente novas combinações sobre as mesmas velas só aumentaria a chance de ajustar ruído.

## Continuação executável

A melhor hipótese incremental é submeter o candidato 80/20 e o R17.07 puro a observação prospectiva com decisões em horários pontuais, regras congeladas, custos reais e patrimônio marcado a mercado; o executor de relógio preparado em R17.06 requer host permanente. Antes de financiar posições, precisamos dados oficiais de mark/funding e histórico atualizado além de junho. O componente vendido precisa de implementação no executor de paper e testes com os dados novos; nenhuma implantação em conta real foi realizada.

Protocolos foram registrados antes de cada família: commits `defe5013` (R17.08), `56e0cd52` (R17.09), `77fcc40c` (R17.10) e `8b9938c3` (R17.11). Todos os drivers e CSVs estão no pacote de reprodução. Estudos que motivaram o teste diário, sem servir como prova para esta carteira: https://onlinelibrary.wiley.com/doi/10.1002/fut.22425 e https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178 .
