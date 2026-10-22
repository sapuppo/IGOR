# R17.23 — Histórico longo de posições em aberto

## Entrega

Histórico ampliado para janeiro de 2023 a junho de 2026: 42 meses, BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT e XRPUSDT. Download inclui 25–31/12/2022 para aquecimento. Mesmas cinco moedas da janela recente R17.22; comparação aqui usa somente essas cinco, não o universo anterior de 38.

6,420 arquivos diários ZIP verificados pelo SHA256 oficial; 0 arquivos ausentes/com erro; 1,848,278 linhas brutas lidas; 665 valores OI inválidos excluídos. Dados agregados para snapshots causais em 4h, com proveniência, URLs e hashes no manifesto.

## Resultado simulado

| Variante | Mensal composto equivalente | Retorno total | Queda máxima 4h | Mensal custos 2× | Trades |
|---|---:|---:|---:|---:|---:|
| Controle R17.21 | 0.634% | 30.40% | 6.63% | 0.466% | 454 |
| Fluxo | 0.008% | 0.34% | 0.70% | 0.005% | 6 |
| Fluxo + funding | 0.008% | 0.34% | 0.70% | 0.005% | 6 |
| Fluxo + funding + OI | 0.013% | 0.55% | 0.45% | 0.011% | 2 |

Hipótese completa: 0 de 42 meses atingiram +15%. Critérios de pesquisa para meta (mensal composto >=15%, DD<=25%, segmentos positivos e custos dobrados): NÃO PASSOU. Nenhuma promoção ao robô principal.

## Cobertura por moeda

| Moeda | Dias verificados | Snapshots 4h | Decisões com OI atual e anterior válidos |
|---|---:|---:|---:|
| BTCUSDT | 1284 | 7703 | 99.97% |
| ETHUSDT | 1284 | 7703 | 99.97% |
| SOLUSDT | 1284 | 7703 | 99.97% |
| BNBUSDT | 1284 | 7703 | 99.97% |
| XRPUSDT | 1284 | 7703 | 99.97% |

Dados ausentes não são zeros, não são volume substituindo OI e não são interpolados. O filtro exige OI atual e 24h anterior disponíveis com idade <=8h em cada consulta. A tabela de cobertura mede o suporte dessas decisões.

## Segmentos da hipótese completa

| Período | Retorno no período | DD diário |
|---|---:|---:|
| 2023 | 0.00% | 0.00% |
| 2024 | 0.00% | 0.00% |
| 2025 | 0.63% | 0.17% |
| h1_2026 | -0.08% | 0.27% |

## Meses de 2026

| Mês | Controle | Fluxo | Fluxo + funding | Fluxo + funding + OI |
|---|---:|---:|---:|---:|
| 2026-01 | 3.15% | -0.25% | -0.25% | 0.00% |
| 2026-02 | 0.64% | 0.00% | 0.00% | 0.00% |
| 2026-03 | -1.72% | 0.00% | 0.00% | 0.00% |
| 2026-04 | -1.61% | 0.00% | 0.00% | 0.00% |
| 2026-05 | -1.41% | -0.08% | -0.08% | -0.08% |
| 2026-06 | 2.64% | 0.00% | 0.00% | 0.00% |

Somente janeiro a junho foram avaliados nesta rodada. Não representam todos os meses de 2026. Julho–outubro não foram acrescidos à avaliação longa porque faltam dados de preço/funding completos no arquivo original usado; não misturar carteiras de universos diferentes.

## Diagnóstico

A hipótese completa produziu somente 2 trades em 42 meses, apesar de OI atual e anterior válidos em 99,97% das consultas. Foram 15 oportunidades brutas de fluxo e 8 após OI, antes da seleção pelo filtro BTC/capacidade da carteira. O gargalo é a frequência das condições de entrada, não falta de histórico. O retorno total de apenas 0,55% não sustenta a meta de 15–20% ao mês. Nenhuma evidência de vantagem consistente foi obtida.

## Método preservado

Regras idênticas à R17.22, definidas antes desta rodada: fluxo acumulado em 24h >=55% de compras para long / <=45% para short, preço alinhado >=2%, primeira transição para condição válida, filtro BTC e liquidez. Último funding realizado estritamente anterior, <=16h, custo direcional <=0,03%. OI em quantidade, crescimento >=1% em 24h. Entrada na abertura seguinte.

Stop inicial 2 ATR anterior entre 2–12%, alvo 15%, prazo máximo 42 velas de 4h, risco planejado 0,25% por operação, posição até 15%, exposição de entrada até 60%. Taxa 0,06% e slippage 0,04% por lado, ambos dobrados no estresse. Funding aplicado pelo motor auditado R17.21. Gaps podem exceder risco planejado.

## Horários e qualidade

Aplicado create_time +5min em TODOS os dias, margem conservadora pela ambiguidade dos horários de métricas. Uma issue de comunidade no repositório oficial relata mudança de rotulagem em 25/06/2026; ela não é confirmação da exchange. O atraso uniforme reduz o risco de usar dado futuro sem depender de um corte exato. Mantida a última amostra estritamente dentro de cada bucket de disponibilidade de 4h; timestamp real conservado para asof estritamente anterior.

Arquivos originais ZIP e CHECKSUM ficam em cache reproduzível; pacote entregue contém cinco séries OI agregadas, manifesto com URL/hash de cada ZIP, protocolos, fonte e todos os resultados. Os ZIPs de origem podem ser baixados novamente pelo coletor.

Validação: seis testes de segurança/causalidade passaram, 6 verificações de invariância ao truncar futuro passaram, oito carteiras reconciliadas independentemente pelos CSVs e todos os cinco hashes dos arquivos OI conferidos. Preços/funding originais passaram verificação de 152 arquivos.

## Limites e decisão

O histórico de preço/fluxo já foi consultado antes; adicionar OI não transforma esses anos em teste independente. Universo escolhido de cinco moedas grandes tem viés de seleção/sobrevivência. Não houve ajuste de limiares após ver os resultados longos. Quantidade pequena de trades, se presente, limita qualquer inferência. Livro/latência e mark oficial de funding não estão modelados; drawdown é em fechamentos de 4h. São simulações, não lucro observado.

Meta permanece 15–20% ao mês. O histórico mais longo foi entregue e a hipótese completa foi finalmente avaliada em vários anos; a qualidade deve ser julgada pelos números acima, sem presumir que mais histórico cria rentabilidade. Nenhuma ordem real foi enviada.

Fontes: https://github.com/binance/binance-public-data ; https://github.com/binance/binance-public-data/issues/491 ; https://data.binance.vision/
