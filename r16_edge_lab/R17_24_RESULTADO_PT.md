# R17.24 — Estratégias públicas adaptadas ao IGOR

Concluído em 25/10/2026. **Nenhuma das seis adaptações superou a referência anterior em retorno mensal equivalente, nem atingiu a meta de 15–20% ao mês.** A baseline R16.24.2 não foi alterada. Integração realizada no laboratório de estratégias do próprio projeto; nenhum executor de dinheiro real foi ativado.

## Fontes verificadas e implementação

Implementação matemática independente dos sinais de entrada publicados pelos projetos. Fontes e versões fixadas em `r17_24_sources.json`:
- Hummingbot: [controllers/directional_trading/bollinger_v1.py](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/controllers/directional_trading/bollinger_v1.py); blob `afa0d77241972276b88a0e287bbc37e38b6988c1`.
- Hummingbot: [controllers/directional_trading/macd_bb_v1.py](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/controllers/directional_trading/macd_bb_v1.py); blob `151a2990dbdf7f344c12d39d93cb4749b2f04344`.
- Freqtrade strategies: [user_data/strategies/Strategy001.py](https://github.com/freqtrade/freqtrade-strategies/blob/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/Strategy001.py); blob `352c344fdb07a56274357e1f534206cac8cc4995`.

- **Hummingbot Bollinger:** compra abaixo da banda inferior e vende a descoberto acima da superior; média de 100 períodos, dois desvios populacionais.
- **Hummingbot MACD+Bollinger:** mesmas bandas, com histograma MACD positivo e MACD negativo para compra; condições opostas para venda. MACD 21/42/9.
- **Freqtrade Strategy001:** compra no cruzamento ascendente EMA20/EMA50, com fechamento Heikin-Ashi acima da EMA20 e vela Heikin-Ashi positiva. Sem posições vendidas nesta adaptação.

**Não são reproduções completas dos robôs originais.** Os exemplos consultados usam 3 minutos (Hummingbot) e 5 minutos (Freqtrade); nossa avaliação usa 4 horas. As saídas e a execução são as do IGOR. Não usamos o ROI escalonado, saída por indicador ou ordens limitadas da Strategy001. Portanto, os resultados abaixo avaliam as adaptações e não demonstram o desempenho dos projetos originais.

## Protocolo fixado antes das simulações

Código e protocolo registrados no commit `7a1ec0ffb9cff0869929d106e057426ac76ff9a1` antes dos replays. Nenhum parâmetro foi otimizado após observar os resultados.
38 moedas do conjunto histórico existente, de 01/01/2023 a 30/06/2026: 42 meses completos. Os 152 arquivos de preços/funding tiveram SHA256 conferido. A seleção das moedas e o histórico já foram utilizados em pesquisas anteriores: isto é uma comparação retrospectiva, não teste independente fora da amostra.
Foram 14 replays: três sinais × dois filtros BTC × dois níveis de custo, mais dois controles. O controle é o volume impulse auditado da R17.21, reaplicado às mesmas 38 moedas, e não a R17.23 de cinco moedas.
Entrada na abertura posterior à vela de sinal; quatro posições no máximo; risco planejado de 0,25% por entrada; peso máximo de 15%; limite de exposição bruta na entrada de 60%; stop 2 ATR, limitado a 2–12%; alvo 15%; saída por tempo em 42 velas (sete dias). Risco realizado pode superar o planejado em gaps.
Taxa de 0,06% e slippage adverso de 0,04% por lado, ambos dobrados no estresse. Funding histórico incluído com preço negociado como aproximação do mark price. Liquidez: mediana de volume financeiro das últimas 42 velas >= USDT 5 milhões. Filtro BTC, quando ativo, exige direção alinhada ao fechamento versus média de 180 velas.
As entradas do Hummingbot permanecem elegíveis enquanto a condição persistir, com apenas uma posição por moeda. EMA com semente SMA e histórico causal completo; diferenças de aquecimento/biblioteca em relação ao feed original estão documentadas.

## Todos os resultados

Retorno mensal equivalente = (patrimônio final / inicial)^(1/42) − 1. Não representa lucro constante por mês. Queda máxima medida nos fechamentos de 4h e na liquidação final.

| Estratégia / filtro BTC | Custo | Mensal equivalente | Total 42 meses | Queda máxima | Operações | Jan–jun/2026 |
|---|---:|---:|---:|---:|---:|---:|
| hb_bollinger_gate0 | 1× | -1.107% | -37.34% | 37.96% | 1525 | -12.84% |
| hb_bollinger_gate0 | 2× | -1.392% | -44.49% | 44.85% | 1534 | -13.99% |
| hb_bollinger_gate1 | 1× | -0.216% | -8.68% | 17.49% | 607 | -0.21% |
| hb_bollinger_gate1 | 2× | -0.337% | -13.21% | 19.74% | 611 | -1.03% |
| hb_macd_bb_gate0 | 1× | -0.187% | -7.57% | 9.82% | 368 | -3.92% |
| hb_macd_bb_gate0 | 2× | -0.242% | -9.69% | 10.84% | 368 | -4.08% |
| hb_macd_bb_gate1 | 1× | 0.071% | 3.02% | 1.62% | 30 | 1.63% |
| hb_macd_bb_gate1 | 2× | 0.064% | 2.72% | 1.61% | 30 | 1.53% |
| ft_ema_ha_gate0 | 1× | 0.164% | 7.13% | 13.39% | 761 | -5.74% |
| ft_ema_ha_gate0 | 2× | -0.044% | -1.82% | 15.36% | 765 | -7.54% |
| ft_ema_ha_gate1 | 1× | 0.375% | 17.04% | 10.83% | 493 | -2.13% |
| ft_ema_ha_gate1 | 2× | 0.250% | 11.04% | 11.47% | 494 | -2.69% |
| control_volume_gate1 | 1× | 0.650% | 31.25% | 11.89% | 1051 | 5.42% |
| control_volume_gate1 | 2× | 0.402% | 18.35% | 12.45% | 1049 | 3.94% |

`gate0` = sem filtro BTC; `gate1` = com filtro BTC. Custos dobrados podem alterar quantidades e número de operações porque o dimensionamento inclui custos.

## Diagnóstico

Bollinger sem filtro foi rejeitada: perdeu dinheiro em todos os segmentos anuais apresentados, mesmo com dimensionamento de risco baixo. O filtro BTC reduziu o prejuízo, mas não produziu vantagem positiva nessa variante.
MACD+Bollinger com filtro foi positiva, mas executou somente 30 operações em 42 meses e rendeu 0,071% ao mês equivalente (0,064% com custos dobrados). Essa amostra e esse retorno são insuficientes para a meta.
EMA+Heikin-Ashi com filtro foi a melhor adaptação nova por retorno total: 0,375% ao mês equivalente, queda máxima de 10,83% e 493 operações. Porém perdeu 4,80% em 2025 e 2,13% no primeiro semestre de 2026. Com custos dobrados, o mensal cai para 0,250%. Não há melhoria consistente que justifique promovê-la.
Controle anterior: 0,650% ao mês equivalente, queda máxima 11,89%, 1.051 operações. Também está muito distante da meta. Não houve estratégia aprovada pelos critérios simultâneos de retorno >=15% mensal equivalente, queda <=25%, pelo menos 100 operações e retorno positivo em cada segmento, nos dois cenários de custo.

## Retornos mensais de 2026 — custo normal

| Mês | Bollinger + BTC | MACD+Bollinger + BTC | EMA+HA + BTC | Controle |
|---|---:|---:|---:|---:|
| 2026-01 | -2.79% | +0.00% | +1.51% | +3.52% |
| 2026-02 | +0.06% | +0.00% | +0.00% | -0.71% |
| 2026-03 | +0.31% | +0.34% | -1.08% | -2.99% |
| 2026-04 | -0.24% | +0.46% | -3.56% | -4.40% |
| 2026-05 | -1.02% | +0.53% | +1.06% | +5.87% |
| 2026-06 | +3.58% | +0.29% | +0.00% | +4.46% |

Julho a outubro de 2026 não fazem parte desta base; não há resultado anual completo de 2026.

## Verificação e limitações

14 testes unitários aprovados (sete novos e sete de regressão do motor auditado), seis comparações de sinais entre histórico completo e prefixos encerrados em 2025/2026; conciliação independente dos CSVs de patrimônio, operações e retornos mensais dos 14 replays. Os testes iniciais identificaram um conflito de nome de coluna com método pandas; corrigido antes do protocolo final e de qualquer simulação de rentabilidade.
As limitações incluem histórico previamente consultado, seleção/sobrevivência das moedas, funding por preço proxy, ausência de livro de ofertas e latência, slippage modelado, e queda de 4h que pode omitir extremos intrabar. Não há lucro real nem validação de execução contínua. As regras originais de outros intervalos ainda não foram testadas nesta etapa.
## Reprodução

Na pasta `r16_edge_lab`, com Python, numpy e pandas instalados e a base `usdm_history` original disponível:
```sh
python -W ignore -m unittest test_r17_24_online test_r17_21_audit -v
python run_r17_24_online.py
```
Código: `r17_24_online_strategies.py`; runner: `run_r17_24_online.py`; parâmetros: `r17_24_protocol.json`; resultados completos e operações: `r17_24_results/`. O pacote de resultados não duplica os 328 MB da base histórica.

Conclusão: implementação e testes concluídos; estratégias disponíveis para pesquisa, sem promoção para operação real. Não há testes desta etapa ainda rodando.
