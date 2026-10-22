# R17.22 — Fluxo, funding e posições em aberto

## Conclusão

Etapa executada: implementação, coleta, 14 simulações, 3 testes de causalidade, 5 verificações de invariância ao remover futuro e reconciliação independente das curvas/trades. Meta de 15–20% ao mês NÃO atingida. Nenhuma promoção ao robô principal. Nenhuma operação real.

No histórico, o novo sinal reduziu risco e retorno. Na janela recente, as três variantes novas ficaram em caixa por falta de sinais. Zero trades não valida uma estratégia lucrativa nem o benefício do filtro OI.

## Histórico exploratório — janeiro 2023 a junho 2026

38 moedas do arquivo já consultado. Funding e fluxo de compras agressoras disponíveis; OI não existe nesse arquivo e NÃO foi inventado.

| Variante | Mensal composto equivalente | Queda máxima 4h | Mensal com custos 2× | Trades |
|---|---:|---:|---:|---:|
| Controle R17.21 (impulso, ambas direções) | 0.65% | 11.89% | 0.40% | 1051 |
| Fluxo | 0.29% | 4.14% | 0.25% | 155 |
| Fluxo + funding | 0.31% | 3.33% | 0.27% | 150 |

## Avaliação recente — 23/09 a 21/10/2026 UTC

Universo fixado antes da coleta completa: BTC, ETH, SOL, BNB, XRP. Regras congeladas antes da avaliação, sem ajuste após os resultados. Preflight tinha apenas 2 candles e 3 snapshots BTC mais recentes, fora da janela avaliada. Esta é uma observação curta, não validação estatística suficiente.

| Variante | Retorno do período | Queda máxima 4h | Trades |
|---|---:|---:|---:|
| Controle R17.21 (impulso, ambas direções) | -1.69% | 1.84% | 8 |
| Fluxo | 0.00% | 0.00% | 0 |
| Fluxo + funding | 0.00% | 0.00% | 0 |
| Fluxo + funding + posições em aberto | 0.00% | 0.00% | 0 |

Nenhuma variante nova gerou sinal na janela recente, antes mesmo dos filtros OI/funding. O controle perdeu 1,69%; ficar sem operar evitou essa perda na simulação, mas não demonstrou geração de lucro. Não alteramos os limiares para forçar um resultado nessa janela.

## Resultados mensais de 2026 disponíveis

Tabela histórica de fluxo + funding e controle, custos normais, mesma carteira e período.

| Mês | Controle | Fluxo + funding |
|---|---:|---:|
| 2026-01 | 3.52% | 1.33% |
| 2026-02 | -0.71% | -0.83% |
| 2026-03 | -2.99% | -0.93% |
| 2026-04 | -4.40% | -0.41% |
| 2026-05 | 5.87% | 0.70% |
| 2026-06 | 4.46% | 3.16% |

Julho e agosto não foram avaliados nesta rodada. Setembro recente cobre somente 23–30/09; outubro somente 01–21/10. Na carteira recente, todas as variantes de fluxo tiveram 0% e zero trades nesses trechos. Não unir essas curvas à tabela histórica: universo e capital inicial diferem. Novembro e dezembro ainda são futuros.

## Implementação

Fluxo = soma do volume financeiro de compras agressoras / volume financeiro total nas últimas 6 velas fechadas de 4h. Long: >=55% e preço sobe >=2% em 24h; short: <=45% e preço cai >=2%. Entrada apenas na transição para condição válida, com liquidez mediana >=5 milhões por vela e filtro BTC igual ao controle. Funding usa somente último evento realizado estritamente anterior à decisão, no máximo 16h de idade, custo direcional <=0,03%.

OI usa quantidade de contratos/moedas, não valor em USD, evitando confundir valorização com novas posições; último snapshot estritamente anterior à decisão, <=8h, aumento >=1% versus snapshot 24h anterior. Ausência de OI bloqueia entrada da variante completa. Dados posteriores não são usados.

Mantidos risco planejado 0,25% por trade, máximo 15% por moeda, exposição de entrada <=60%, stop 2 ATR anterior limitado a 2–12%, alvo 15%, prazo máximo 42 velas de 4h. Risco planejado não é perda máxima garantida em gaps. Comissão 0,06% e slippage 0,04% por lado; ambos dobrados no estresse. Funding realizado incluído, usando preço negociado como proxy do mark.

## Dados e limitações

Coletados por conector oficial somente leitura: 492 candles, 246 eventos de funding e 176 snapshots OI por moeda. Período de warmup começa 01/08. Os 15 arquivos de resposta estão no pacote, com hashes. API de estatísticas OI oferece somente o último mês; arquivos públicos mais antigos de métricas não foram baixados nesta rodada. Portanto, hipótese completa de vários anos permanece pendente.

Histórico de 38 moedas passou verificação de 152 arquivos; contém viés de universo/sobrevivência e foi consultado anteriormente. Janela recente usa apenas 5 moedas líquidas. Execução modelada na abertura seguinte não inclui latência observada, livro ou mark de funding oficial. Drawdown é observado no fechamento de 4h. Não há robô contínuo ou ordens reais executadas.

A mesma taxa dobrada pode produzir perda ligeiramente menor no controle recente porque a regra dimensiona a posição pelo risco incluindo custos; a exposição é menor. Isso não significa que taxas maiores sejam benéficas.

## Estado final

Concluídas implementação e avaliação inicial R17.22. Não existe estratégia aprovada para 15–20% ao mês. Pendência para validar a hipótese completa: ampliar histórico verificável de OI e período independente com quantidade suficiente de operações. Nenhum teste segue rodando após esta entrega. Aviso automático configurado para consultar o status de conclusão e enviar uma notificação, desativando-se após o envio.

Fontes técnicas: https://github.com/binance/binance-public-data e https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics
