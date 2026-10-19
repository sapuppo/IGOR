# R17.20 — Novas hipóteses, meta de 15–20% ao mês

Meta corrigida por instrução do usuário: mínimo de 15% ao mês composto equivalente, objetivo superior de 20%. Não é garantia de lucro mensal nem exigência de todos os meses positivos.

## Resultado

12 configurações × 2 cenários de custos = 24 simulações. Nenhuma passou. Nenhuma elegível sequer pelo filtro de treino: retorno positivo em 2023–2024 e queda diária máxima até 25%. Baseline R16.24.2 preservada. Nenhuma ordem real.

| Configuração | Mensal composto | Queda máxima 4h | Mensal custos 2× | Jan–jun 2026 |
|---|---:|---:|---:|---:|
| failed_break_gate0_hold18 | -4.90% | 89.75% | -8.87% | -27.57% |
| failed_break_gate0_hold42 | -2.25% | 64.69% | -4.52% | -40.48% |
| failed_break_gate1_hold18 | -2.35% | 69.57% | -4.11% | -3.82% |
| failed_break_gate1_hold42 | -1.18% | 55.41% | -2.41% | -7.26% |
| relative_btc_gate0_hold18 | -2.78% | 81.73% | -7.08% | 30.07% |
| relative_btc_gate0_hold42 | -1.50% | 73.42% | -3.56% | 6.35% |
| relative_btc_gate1_hold18 | -3.68% | 87.24% | -6.83% | 43.49% |
| relative_btc_gate1_hold42 | -2.82% | 86.98% | -4.76% | 29.48% |
| volume_impulse_gate0_hold18 | -0.18% | 52.60% | -4.00% | 0.10% |
| volume_impulse_gate0_hold42 | -0.31% | 69.41% | -2.06% | 29.37% |
| volume_impulse_gate1_hold18 | -0.98% | 51.32% | -3.29% | -7.45% |
| volume_impulse_gate1_hold42 | 0.99% | 61.90% | -0.28% | 38.52% |

## Método e limites

Dados de janeiro de 2023 a junho de 2026, 38 moedas e 152 arquivos verificados. Estratégias novas: falso rompimento de 20 velas; cruzamento da força relativa ao BTC em 7 dias; impulso de 24h com volume >=2× mediana anterior. Dois conjuntos de stop/alvo/prazo, com/sem filtro BTC. Sinais de velas fechadas; entrada na abertura seguinte. Quatro posições no máximo, 25% por posição, exposição total de entrada limitada ao patrimônio. Comissão 0,06% + slippage 0,04% por lado, ambos dobrados no estresse. Funding histórico incluído como aproximação pelo preço negociado.

Critérios registrados antes dos resultados: mensal composto >=15%, queda máxima <=25% e retorno positivo em treino, 2025 e primeiro semestre de 2026, em ambos cenários de custos. Invariância dos sinais ao truncar dados futuros passou; reconciliação caixa/trades passou em 24 replays.

Período já consultado em pesquisas anteriores: não é teste fora da amostra independente. Universo fixo tem viés de sobrevivência/seleção; falta histórico de livro/spread e mark price de funding. Drawdown de fechamento 4h pode subestimar perda intrabar. Resultados simulados não são lucros observados.

## Integridade

Quatro arquivos locais divergiam do manifesto: BTCUSDT 15m, FETUSDT 15m, ICPUSDT 1h e VETUSDT 15m. Restaurados a partir dos arquivos ZIP originais com igualdade SHA256 antes da execução. Cópias divergentes preservadas localmente. data_recovery.json contém os três últimos recuperados; ICP foi restaurado na primeira tentativa, interrompida ao encontrar outro ZIP inválido. Verificação final dos 152 arquivos passou.

## Conclusão

As hipóteses desta rodada foram reprovadas. Aumentar a alavancagem destes resultados não demonstra uma vantagem estatística robusta. Ainda não há estratégia validada para 15–20% ao mês. A regra diária de +0,5% não foi implementada nesta rodada.

Referência sobre custos de funding: https://www.binance.com/en/support/faq/detail/360033525031 — funding pode mudar de periodicidade; o replay usa os eventos históricos disponíveis.
