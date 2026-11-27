# IGOR R17.29 — resultado real da pesquisa

Data: 27/11/2026. Branch independente: `research-r17-29-role-regime`. Nenhuma alteração na versão principal, nenhuma ordem real e nenhum desenvolvimento paralelo sobrescrito.

## Decisão

**Reprovado para promoção.** A seleção walk-forward perdeu **-2.92%**, com drawdown de +9.71%. Com custos dobrados, perdeu -4.34%. A meta de 5–10% ao mês não foi atingida. Não existe evidência aqui que sustente 15–20% mensais.

A melhor configuração isolada foi `breakout_36_r25`: **+5.49% no período inteiro**, equivalente geométrico de **+0.23% ao mês**. Foi identificada depois de comparar os resultados; não é uma escolha independente fora da amostra. Em 2026, ela perdeu -0.26%. Trocar a seleção perdedora pelo vencedor retrospectivo seria esconder o problema.

## O que foi implementado e executado

- 312 replays: 264 janelas de treinamento, 42 comparações contínuas e seis testes de cópia de fluxo. O total inclui controles e custos alternativos; não são 312 estratégias independentes.
- Oito hipóteses fixas: tendências EMA32/96 e EMA64/192, rompimentos de 36/72 candles, duas versões com filtro de regime e força relativa de 72/168 horas. Cada uma teve risco de 0,25% e 0,50% por operação.
- Dimensionamento por ATR/volatilidade, stop e trailing, limite de exposição de 60%, máximo de três posições, redução após drawdown de 8%, trava após 20%, limite diário de 4% e pausa após três perdas. Sem alavancagem e sem reiniciar o drawdown entre trimestres.
- Classificador de execução por inventário inicial: distingue redução, abertura e reversão, usando Decimal. Rejeita inventário desconhecido; compra para fechar short não vira sinal de novo long.
- 26 testes automatizados aprovados; 12 conferências de causalidade em dados reais; 23,820 registros de operações conciliados em 48 replays com extratos completos.

## Dados e execução

510 ZIPs oficiais da Binance com SHA256 conferido. Seis ativos: BTC, ETH, SOL, BNB, XRP e DOGE, em USDT-M. Dados de 01/05/2024 a 25/11/2026, totalizando 22.536 horas por ativo, mais funding histórico. Os seis arquivos diários de 26/11 ainda retornaram 404; todos os ativos foram cortados em 26/11/2026 00:00 UTC, antes do replay. Não foram inventados candles para preencher o dia ausente.

Avaliação contínua: **01/01/2025 a 25/11/2026**, 694 dias. O período anterior serve para aquecimento e treinamento. Oito seleções trimestrais utilizam apenas os seis meses anteriores, com regras registradas antes dos resultados. Os indicadores de 4h só ficam disponíveis após o fechamento; execução com uma hora adicional de atraso. Força relativa usa apenas closes já concluídos.

Custo normal por lado: taxa de 0,06% mais 0,06% de spread/slippage; aproximadamente **0,24% por ida e volta**, antes de funding e arredondamentos. Stress dobra ambos: aproximadamente 0,48%. Funding usa eventos históricos reais, preço de abertura como aproximação de mark e tratamento conservador quando o horário intrabar é ambíguo. Foram aplicados tick, lote, notional mínimo e limite de participação no volume da hora anterior. Nenhum rebate maker foi inventado.

## Comparação contínua líquida

Retornos são sobre o patrimônio total inicial de US$10.000. A coluna mensal é equivalência geométrica, não ganho recebido todos os meses.

| Configuração | Total normal | Total stress | Mensal equivalente normal | DD máximo | Sharpe | PF | Operações |
|---|---:|---:|---:|---:|---:|---:|---:|
| reference | +2.64% | -0.52% | +0.11% | +4.32% | 0.32 | 1.11 | 163 |
| trend_32_96_r25 | -10.00% | -13.19% | -0.46% | +12.60% | -1.08 | 0.77 | 1008 |
| trend_64_192_r25 | -7.11% | -11.73% | -0.32% | +10.32% | -0.63 | 0.86 | 980 |
| breakout_36_r25 | +5.49% | +3.06% | +0.23% | +6.94% | 0.55 | 1.22 | 189 |
| breakout_72_r25 | +3.04% | +1.50% | +0.13% | +6.55% | 0.34 | 1.14 | 165 |
| regime_trend_r25 | -5.31% | -10.42% | -0.24% | +6.65% | -0.49 | 0.85 | 624 |
| regime_breakout_r25 | +1.57% | +0.36% | +0.07% | +7.44% | 0.22 | 1.10 | 113 |
| relative_72_r25 | -13.45% | -19.40% | -0.63% | +14.41% | -3.97 | 0.68 | 1502 |
| relative_168_r25 | -6.77% | -12.30% | -0.31% | +7.78% | -1.52 | 0.85 | 1031 |
| selected_wfo | -2.92% | -4.34% | -0.13% | +9.71% | -0.21 | 0.86 | 90 |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | 0.00 | n/a | 0 |

`reference` é uma adaptação horária congelada das regras de impulso/volume usadas nas pesquisas anteriores, com BTC/ETH/SOL e o mesmo simulador. **Não é reprodução comprovada do executável R16.24.2 em produção**; não se deve vender a diferença como melhora contra toda a baseline original.

## Cenários de risco de 0,50%

| Configuração | Total normal | Total stress | DD normal | 2026 até 25/11 |
|---|---:|---:|---:|---:|
| trend_32_96 | -13.13% | -19.82% | +17.91% | -2.04% |
| trend_64_192 | -12.76% | -19.05% | +17.07% | -8.84% |
| breakout_36 | +1.70% | -1.01% | +11.16% | -4.41% |
| breakout_72 | +3.12% | +0.22% | +10.68% | -5.28% |
| regime_trend | -11.44% | -16.10% | +12.86% | -0.78% |
| regime_breakout | +1.51% | -0.47% | +12.09% | -2.98% |
| relative_72 | -18.24% | -18.77% | +20.02% | -6.31% |
| relative_168 | -10.40% | -20.03% | +11.69% | -5.92% |

Aumentar o risco não resolveu a falta de vantagem; piorou várias curvas. O limite de 20% aciona um bloqueio, mas taxas, gaps e a resolução do replay podem levar a perda observada um pouco além desse valor.

## Seleções feitas somente com o passado

| Início do teste | Escolha congelada |
|---|---|
| 01/01/2025 | breakout_36_r50 |
| 01/04/2025 | breakout_36_r50 |
| 01/07/2025 | cash |
| 01/10/2025 | breakout_72_r50 |
| 01/01/2026 | breakout_72_r50 |
| 01/04/2026 | cash |
| 01/07/2026 | cash |
| 01/10/2026 | cash |

A seleção e o risco persistem no replay inteiro. As posições da política anterior são liquidadas ao trocar de regime trimestral. Um resíduo negativo em um mês de entrada em caixa pode corresponder a esse encerramento.

## Resultado mensal em 2026

Novembro é parcial, de 01 a 25/11. Dezembro ainda não existe neste teste. A melhor isolada é mostrada como diagnóstico retrospectivo, não como versão escolhida para operar.

| Mês | Seleção walk-forward | Melhor isolada breakout_36_r25 | Referência |
|---|---:|---:|---:|
| 2026-01 | -2.77% | -0.82% | -0.13% |
| 2026-02 | -1.10% | -0.25% | +0.16% |
| 2026-03 | -0.89% | -1.14% | -1.01% |
| 2026-04 | -0.02% | -1.18% | -0.96% |
| 2026-05 | +0.00% | -1.83% | -0.27% |
| 2026-06 | +0.00% | +3.19% | +0.91% |
| 2026-07 | +0.00% | -1.18% | -0.74% |
| 2026-08 | +0.00% | +2.84% | +3.18% |
| 2026-09 | +0.00% | -0.44% | -1.37% |
| 2026-10 | +0.00% | -0.72% | -1.12% |
| 2026-11 | +0.00% | +1.40% | +1.34% |
| **Acumulado 2026** | **-4.72%** | **-0.26%** | **-0.11%** |

## Teste de copiar o trader: resultado negativo

Outubro de 2026, somente BTC/ETH/SOL, export público de Bobby selecionado retrospectivamente. Cada decisão usa o fluxo dos últimos 60 minutos, observa o fechamento do minuto, espera mais um minuto para executar, mantém por até 60 minutos, arrisca 0,25%, com stop de ATR e alvo 2R. A cópia executa taker na Binance, enquanto o fluxo original vem da Hyperliquid: é um teste de transferência do sinal, não uma réplica da carteira ou do algoritmo original.

| Regra de cópia | Líquido normal | Líquido stress | DD normal | Operações normais |
|---|---:|---:|---:|---:|
| naive_buy_sell | -20.02% | -20.07% | +20.04% | 662 |
| opening_risk_only | -20.03% | -20.12% | +20.03% | 701 |
| opening_with_regime | -7.30% | -12.26% | +7.33% | 194 |

**As três versões foram rejeitadas.** A trava interrompeu as versões que se aproximaram de 20% de perda; esse teto não demonstra controle suficiente para produção. Corrigir o significado econômico das ordens evita um erro, mas não cria rentabilidade. Foram excluídas reversões no export sem startPosition, porque não é possível separar com segurança a parcela fechada da recém-aberta. O teste ainda supõe acesso a cada fill histórico no fechamento do minuto, sem comprovar uma transmissão ao vivo com essa latência.

## O que os dados dos traders realmente ensinaram

- bobby: amostra recente limitada a 11,955 fills. Das 2,216 compras, 694 apenas reduziram/encerraram short; 1,522 incluíram nova exposição comprada. 84.39% dos fills dessa amostra tinham crossed=false. Isso não representa dois anos nem o resultado de todas as contas/venues.
- wintermute: amostra recente limitada a 11,958 fills. Das 4,183 compras, 2,483 apenas reduziram/encerraram short; 1,700 incluíram nova exposição comprada. 72.49% dos fills dessa amostra tinham crossed=false. Isso não representa dois anos nem o resultado de todas as contas/venues.

Lucro monetário divulgado, percentual sobre o capital, rebate, funding, hedge em outra venue e retorno copiável são medidas distintas. As 1.422.691 linhas de outubro já preservadas na R17.28 não são 1.422.691 operações independentes e não fornecem inventário inicial completo. Não há ranking mundial comprovado de melhores traders nem histórico integral de dois anos concluído.

## Acesso a histórico adicional: o que está pronto e o que falta

O coletor `archive_fetch29.py` foi implementado, com paginação explícita, limite de páginas, manifesto e hashes. Por padrão só produz um plano local. O dry run foi executado; **a integração autenticada ainda não foi testada**, pois não há chave autorizada disponível. Não criou conta, não contratou serviço e não consumiu créditos do provedor. Cinco testes verificam que página curta ou cursor ausente não sejam confundidos com histórico completo.

Fontes consultadas em 27/11/2026:
- [Hypedexer — arquivo histórico](https://docs.hypedexer.com/guides/historical-trade-archive): anuncia fills desde janeiro/2024, com campos ausentes nos períodos antigos. O portal de exportação já havia imposto a cota observada de um export por IP/24h.
- [Hypedexer — autenticação e paginação](https://docs.hypedexer.com/quickstart): exige X-API-Key; a chave habilita consultas, não comprova cobertura, qualidade ou custo adequado.
- [0xArchive — cobertura de fills](https://0xarchive.io/resources/market-data-guides/hyperliquid-trade-history): informa arquivo completo desde 25/05/2025, incluindo TWAP, e funding desde 27/09/2025. Isso não cobre sozinho os dois anos solicitados.
- [0xArchive — preços](https://0xarchive.io/pricing): plano gratuito limita histórico aos últimos 30 dias. Build custa US$49 na cobrança mensal; US$39/mês é equivalente anual com US$468 antecipados. Não foi contratado.

Antes de qualquer contratação: verificar uma amostra com startPosition, timestamps em milissegundos, IDs, custos, TWAP, funding e inventário anterior ao corte. Completar o arquivo antigo não dispensa verificar hedges e transferências externas. Não recomendo pagar por dados como se isso garantisse a meta.

## Vídeo novo enviado

Link recebido: https://x.com/soniacuts/status/2126326311006130476 . A tentativa de leitura direta e a navegação foram bloqueadas. A pesquisa encontrou publicações distintas da mesma conta, mas não confirmou o conteúdo desse vídeo. **Não foi possível assisti-lo ou validar suas alegações; nenhuma regra foi atribuída a ele nem implementada em seu nome.** Um arquivo de vídeo anexado permite analisar o material sem esse bloqueio.

## Diagnóstico e alterações recomendadas

1. **Descartar estas versões de cópia como estratégias de lucro.** O histórico verificável contradiz a ideia de simplesmente copiar fills e cobrar o mesmo retorno do operador original.
2. **Manter a correção de inventário e o risco contínuo como melhorias técnicas em pesquisa.** Esses componentes têm testes, mas ainda exigem integração e teste com o adaptador real do IGOR antes de qualquer uso operacional.
3. **Não adotar EMA/momentum ou aumentar risco para forçar a meta.** O rompimento de 36 barras foi apenas um diagnóstico menos ruim; não se sustentou em 2026 e a seleção treinada falhou.
4. **Próxima hipótese útil: execução e custos, não outro ajuste pós-resultado de indicadores.** Estudar se existe vantagem líquida em prover liquidez com controle de inventário. Isso exige book, fila, cancelamentos, latência, seleção adversa e hedge; candles com toque no preço não comprovam fill maker. Não foi declarada rentabilidade de market making com este simulador taker.
5. **Exigir validação prospectiva antes de promover.** Estes períodos já foram pesquisados e reutilizados. Walk-forward evita olhar o futuro na seleção de cada janela, mas não transforma retrospectiva repetida em evidência independente.

## Limitações materiais

- Baseline original R16.24.2 não reproduzida ponta a ponta; somente referência de pesquisa descrita acima.
- Conjunto de seis moedas escolhido hoje, sem universo point-in-time ou teste de moedas removidas; custos fixos conservadores não são todas as condições de liquidez.
- Filtros de negociação atuais, sem suas versões históricas. Taxas VIP, descontos e preço de mark intrabar não reproduzidos exatamente.
- DD medido nos fechamentos horários; não captura o pior prejuízo flutuante dentro da hora. Stops em gaps não garantem saída no preço nominal.
- Benchmark de manter short deu ganho retrospectivo, mas DD de +34.39% e apenas três posições; não é estratégia adaptativa aprovada nem recomendação de manter vendas permanentes.
- Nenhum replay comprova capacidade de execução ao vivo ou retorno futuro. Não houve promoção, assinatura de dados ou negociação real.

## Evidências e reprodução

Protocolo inicial: `7a6191467dae311e6dbc48b95d72217ebe2f628f`. Implementação congelada antes dos replays: `01ca9e4abadb7d32ca50831c55bd509d2cb70000`. A única correção posterior no script de cópia foi o nome do arquivo Wintermute para incluir sua amostra na auditoria descritiva; não mudou sinal, operação ou resultado de backtest.

- SHA256 do protocolo final pré-replay: `fd62521bb4614f6a49e8198620c4f16f6328d0b7b353ee0ca36f4d00d09d3f60`.
- SHA256 das seleções congeladas antes da avaliação contínua: `371bee529e02c9d44f999744cf3326427995666c2a2717f164f5df44bdb45b8f`.
- `results/COMPARISON.json`, `results/SELECTION_FROZEN.json`, `copy_results/COPY_COMPARISON.json`, extratos CSV, curvas de patrimônio e rastros de decisão.
- `VERIFICATION.json`, `tests.log`, `DATA_MANIFEST.json` e `DATA_COVERAGE.json`: custos/fees/funding conciliados, causalidade, recorte temporal e hashes.
- Extraia R17_29_RESULTS.zip e R17_29_DATA.zip na mesma pasta de pesquisa. Juntos incluem dados horários preparados, scripts e resultados. Dados brutos públicos são recuperáveis por URL/hash; o export original de outubro está preservado na R17.28 e no arquivo disponibilizado anteriormente.
- Para reproduzir com Python3.12, numpy2.3.5 e pandas2.2.3: `python -m unittest test29 test_copy29 test_archive29 -v`, `python collect29.py`, `python data29.py`, `python run29.py`, `python copy_run29.py`, `python verify29.py`. A cópia requer os dados preparados da R17.26 e o export da R17.28, conforme seus manifestos. Nenhum modelo LightGBM é usado na R17.29.

