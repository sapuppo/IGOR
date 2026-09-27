# R16.31 — fonte e replay de funding com preço oficial

**Resultado do subteste técnico: `SOURCE_AND_SCOPED_FUNDING_PASS`. Classificação geral do robô: `TECHNICALLY_INVALID`; `OOS_VALIDATED=false`; nenhum capital real autorizado.** A baseline R16.24.2 indicada pelo usuário não foi alterada. A H1 (CORE + REV1H) permanece hipótese de pesquisa escolhida depois de ver o histórico.

Pré-registro de período, insumos e critérios: [R16_31_FUNDING_SCOPE_PREREG_PT.md](R16_31_FUNDING_SCOPE_PREREG_PT.md), commit `5e408fa85bd852186597e891ea105a298208fe58`, anterior ao replay restrito. Janela única: **01/11/2023 00:00 UTC a 01/07/2026 00:00 UTC exclusivo**. As features anteriores à data inicial foram usadas apenas para aquecimento causal; a carteira reiniciou sem importar posições abertas antes do corte. Não foram consultados, otimizados ou publicados retornos do recorte.

## Evidência de cobertura

| Verificação | Resultado |
|---|---:|
| Símbolos elegíveis e auditados | 38 |
| Eventos oficiais de funding na janela do corte | 121.758 |
| Eventos sem `markPrice` na janela | **0** |
| Eventos no dataset congelado completo 2021–jun/2026 | 207.704 |
| Preços ausentes no período completo | **85.882** |
| Ledger original BASE após o corte | 2.727 eventos, 0 divergências de preço/taxa/fluxo |
| Ledger original STRESS após o corte | 2.989 eventos, 0 divergências de preço/taxa/fluxo |

O auditor verificou SHA-256 de cada CSV de funding e de cada suplemento JSON, IDs de símbolos, contagem, ordenação, timestamp, taxa e preço. Os 85.882 valores ausentes se concentram em 2021–out/2023. A primeira marca oficial presente no suplemento aparece em 31/10/2023; o corte foi fixado em 01/11/2023 pela data da mudança documentada do endpoint, antes de executar o replay. [Histórico oficial de mudanças USD-M](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log) e [definição do campo `markPrice`](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History).

## Replay restrito H1, dois cenários congelados

| Cenário | Funding nos shadows com preço exato | Preço substituto | Eventos no ledger com preço exato | Buracos ativos |
|---|---:|---:|---:|---:|
| BASE | 5.988 | **0** | 3.057 | **0** |
| STRESS | 6.031 | **0** | 3.109 | **0** |

Os hashes dos ledgers restritos são `4f29c9046ea921dfc676616670f63987422d75474ea7419feaac1482ee9fe151` (BASE) e `1499a6fb2ef83f56d0054f1354c3a2f7d4164fa2a8c4584066cfb027801782cc` (STRESS). Não compare o resultado deste replay iniciado com carteira vazia aos retornos do replay original iniciado em 2021: a população de posições e os saldos iniciais diferem.

**Interpretação:** foi removido o bloqueio de **disponibilidade de markPrice somente para esse recorte técnico**. O contrato antigo cobria 2021–2026 e segue bloqueado; não foi reclassificado por escolher uma janela posterior. Taxas reais da conta, spread, liquidez, preenchimentos, regras históricas, seleção retrospectiva da coorte e OOS independente continuam pendentes. O verificador de execução de R16.30 aguarda ordens/fills/extrato de conta independente. Mesmo uma reconciliação futura não provaria ganho de 20% ao mês.

**Arquivos de evidência:** `R16_31_FUNDING_COVERAGE.json` (SHA-256 `da9a0f1da0570641b2f7e01bc3251ff3aad7ad944c3399d9847e35572dffed43`) e `R16_31_SCOPED_H1_FUNDING.json` (SHA-256 `b02688132eae99ab4bcf1fc2f0d56366c2e45bc3e4c7d3773cd7dc5079168d85`). Os testes sintéticos do auditor verificam fonte adulterada, ausência de marca após o corte e fluxo de caixa divergente; 4/4 PASS localmente. Scripts: `r16_31_funding_source_gate.py`, `r16_31_scoped_funding_replay.py` e `test_r16_31_funding_source_gate.py`.

**Próximo passo mensurável:** reconciliar taxas/fills de uma conta isolada com o verificador R16.30 e decidir formalmente se é possível obter fonte exata para 2021–2023. Caso não seja, só uma nova avaliação com contrato, universo e janela predefinidos, depois de resolver custos e antes de observar retornos futuros, poderá avançar; não reutilizar 2023–2026 como OOS.
