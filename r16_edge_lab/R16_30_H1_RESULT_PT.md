# R16.30 pesquisa H1 — portfólio CORE + REV1H

**Resultado retrospectivo:** remover os sinais REV15M melhorou o cenário de execução STRESS, mas a taxa mensal composta alcançou **1,22%**, longe da meta de 20%. Trata-se de teste de hipótese selecionada após observar os resultados históricos; não é OOS, não confirma lucro futuro e não promove a R16.24.2 como baseline nem a R16.30 como validada.

## Método e integridade

- O [protocolo H1](R16_30_PREREG_PT.md) foi registrado no commit `aeb7cda316953c2a5a2c8d88d1a4d856a0d33a46` antes deste replay.
- O código do replay, a configuração, os 152 arquivos originais, os suplementos e os 6.650 sinais de origem são os da R16.29.2 final, commit `f8c2307533265653f1faf0832fda836b21641f85`, run [36282775646](https://github.com/sapuppo/IGOR/actions/runs/36282775646). Entrada original `a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041`.
- Antes da ablação, a execução local reproduziu **exatamente** os ledgers íntegros: BASE `8f97b40aa7161fbe8e03241551b5939a1ac4c89c6692beb30c0a234aafe5582c` e STRESS `2559948cc5f95d68dba300b8e96e0f64fd3fa7ecb9cf3c1a7e243984c81d4ad4`. Métricas centrais também coincidiram.
- Um arquivo LTCUSDT 15m da cópia de trabalho local falhou no hash congelado. O arquivo correto foi restaurado **apenas na cópia de pesquisa** a partir do pacote preservado `IGOR_R16_29_2_DADOS_VERIFICADOS.zip` (SHA-256 `06214bf63e833d11efbfa69b0a1f4667c0452ca5483983cb741518642ee65c3d`) e confirmado contra o manifesto. Não alterei a fonte original da workspace.
- O filtro remove sinais REV15M antes do replay completo. Caixa, colisões, posições, regime, funding, stop e exposição foram recalculados para CORE e REV1H; valores abaixo não provêm de subtração estática de trades do portfólio anterior.

## Comparação dos 66 meses de 2021–junho/2026

| Métrica | Original BASE | H1 BASE | Original STRESS | H1 STRESS |
|---|---:|---:|---:|---:|
| Retorno mensal composto | 1,29% | **1,32%** | 0,75% | **1,22%** |
| Retorno acumulado | 133,59% | 137,55% | 63,74% | 123,34% |
| Drawdown máximo MTM | 40,39% | **19,94%** | 27,96% | **21,88%** |
| Operações fechadas | 1.360 | 776 | 1.010 | 783 |
| P&L bruto, USDT | 21.669,85 | 17.106,50 | 13.186,26 | 16.894,42 |
| Comissões, USDT | 4.434,71 | 1.256,80 | 3.287,37 | 1.894,56 |
| Slippage, USDT | 2.217,35 | 628,40 | 2.191,58 | 1.263,04 |
| Funding líquido, USDT | −1.658,40 | −1.465,89 | −1.333,32 | −1.403,04 |
| Uso ponderado de capital | 10,53% | 9,83% | 10,38% | 10,08% |

No STRESS H1, CORE respondeu por **+6.672,18 USDT** líquidos (505 fechamentos) e REV1H por **+5.661,60 USDT** (278). O risco agregado de stop mais alto observado permaneceu abaixo dos 6% configurados, cerca de **5,89%**. A exposição de entrada permaneceu limitada a 1x. Mesmo os números superiores da H1 incluem preços substitutos de funding e comissões assumidas.

## Interpretação sem seleção retrospectiva disfarçada

O contraste mostra que o REV15M atual tem sensibilidade grande a custos e à latência. Também mostra uma limitação estrutural: retirar essa estratégia não aumentou o tempo de uso de capital, que permaneceu em torno de 10%. Uma taxa de 20% por mês teria de vir de novas fontes de vantagem econômica demonstrável; multiplicar posição ou escolher só anos/símbolos vencedores não validaria tal vantagem.

O invariante 11 do Gate 3 continua bloqueado por `markPrice` histórico ausente. Os anos 2021–2026 foram consultados na escolha dos alfas e na presente decisão de ablação; não haverá `TECHNICALLY_VALID`, `OOS_VALIDATED`, `PAPER_CANDIDATE` nem autorização de capital real com este teste. O próximo teste separado deve ser pré-registrado como outra tentativa e confrontado com H1 em ambos os cenários. Um holdout futuro intocado permanece indispensável.

Arquivos: [resultado JSON](R16_30_H1_RESULT.json), script reproduzível `r16_30_h1_replay.py` e artefatos de trades/diagnósticos entregues separadamente.
