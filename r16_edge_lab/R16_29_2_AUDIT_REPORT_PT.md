# R16.29.2 — auditoria do robô principal e diagnóstico da meta de 20% ao mês

**Resultado da auditoria (execução de 27/09/2026 UTC): TECHNICALLY_INVALID.** A R16.24.2 – Portfolio Integration continua sendo a última baseline validada. A R16.29.2 é uma reconstrução diagnóstica dos três alfas congelados; não é aprovação econômica, OOS nem autorização para capital real. A conclusão não depende de perseguir a meta de retorno.

## Proveniência e reprodução

| Campo | Valor |
|---|---|
| Execução final | [GitHub Actions 36282775646](https://github.com/sapuppo/IGOR/actions/runs/36282775646), trabalho 108517683750, concluído com sucesso operacional |
| Código executado | [`f8c2307533265653f1faf0832fda836b21641f85`](https://github.com/sapuppo/IGOR/commit/f8c2307533265653f1faf0832fda836b21641f85) na `r16-edge-first` |
| Workflow | [`0d72beae4a22436644d8829ca109b8d4b4701933`](https://github.com/sapuppo/IGOR/commit/0d72beae4a22436644d8829ca109b8d4b4701933) em `master` |
| Base original imutável, 152 arquivos USD-M | `a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041` |
| Alfa original congelado | `cb1f770e39ee0e3814b0b37047abad71868c8b6ec517bb39cb7cfa47e91e3a5b` |
| Configuração / protocolo | `faa2a68688a311c8bddc73e7db2f21d8d8c0f53114fcbec7d36407977715a355` / `4017cc95e11e2fdc420424b76d148da6daed500bc23735911f06b1fc729aa440` |
| Entrada efetiva, original + suplementos | `3285a4637202cda06e160563b5f579b1b2e95f7c47a49f740e74ab5648c6a2a8` |
| Lacunas recuperadas | 6930 de 6930; suplemento `b9fd79442a25fc2dd4b00c7cf7fab7e00671b284275458a587f98b6854776224` |
| Funding | suplemento `63f647b039737480b4ba375e483d690d404340495e6b6d8b94a0998c984041db`; 85,882 preços de liquidação ausentes |
| Artefato de auditoria | [10919576782](https://github.com/sapuppo/IGOR/actions/runs/36282775646/artifacts/10919576782); SHA-256 `6b9074669d441f0080ec51267d55d0cd69474b13896d3e2d9a0c1a3dc866a80a`; manifesto interno de 20 arquivos conferido |
| Artefatos de funding / gaps | [10919571692](https://github.com/sapuppo/IGOR/actions/runs/36282775646/artifacts/10919571692) / [10919367740](https://github.com/sapuppo/IGOR/actions/runs/36282775646/artifacts/10919367740); SHA-256 `3351335aa9ac62239eb343b793b344f1f13a90ae9050b586a9cb58d5b7bb5f59` / `6e6804438d1bfc683abb5d815bb4c191b23c0b1d3ead44c33effa7c3d1b88eb9` |

A execução operacional bem sucedida indica que o job e os artefatos terminaram; **a classificação do Gate 3 vem do JSON de invariantes**. Todos os arquivos e SHA-256 internos foram conferidos após download. O replay final preservou exatamente os hashes dos ledgers do replay anterior: BASE `8f97b40aa7161fbe8e03241551b5939a1ac4c89c6692beb30c0a234aafe5582c`, STRESS `2559948cc5f95d68dba300b8e96e0f64fd3fa7ecb9cf3c1a7e243984c81d4ad4`.

## O que o teste mediu

Período 01/01/2021–30/06/2026 (66 meses), saldo inicial 10.000 USDT, contrato perpétuo Binance USD-M, coorte fixa de pesquisa com 39 ativos (38 elegíveis); CORE 4h, REV1H e REV15M apenas comprados, portfólio com saldo compartilhado e alocação congelada. Ordem na próxima observação, saída conservadora quando alvo e stop coincidem, custos por lado e funding nos horários históricos. Stop risk agregado limitado a 6%, exposição bruta de cerca de 1x, alavancagem de 1x.

BASE: taker 0,04% e slippage 0,02% por lado. STRESS: taker 0,06%, slippage 0,04% por lado e um candle de 15 minutos de latência. Essas comissões são hipóteses fixas, não extratos históricos. Lucro e drawdown abaixo são estimativas do simulador, com preço de marcação por último negócio e proxies de funding; não representam liquidação confirmada da corretora.

## Números do backtest integral

| Métrica | BASE | STRESS |
|---|---:|---:|
| Retorno acumulado 66 meses | +133.59% | +63.74% |
| Retorno mensal composto | +1.29% | +0.75% |
| CAGR | +16.70% | +9.39% |
| Pior drawdown sobre equity MTM | +40.39% | +27.96% |
| Lucro bruto, USDT | 21,669.85 | 13,186.26 |
| Comissões, USDT | 4,434.71 | 3,287.37 |
| Slippage, USDT | 2,217.35 | 2,191.58 |
| Funding líquido, USDT | -1,658.40 | -1,333.32 |
| Lucro líquido, USDT | 13,359.39 | 6,373.98 |
| Operações fechadas | 1360 | 1010 |
| Mês mediano | +0.48% | +0.17% |
| Meses positivos | +53.03% | +53.03% |
| Pior mês | -16.52% | -13.12% |
| Melhor mês | +27.58% | +15.83% |
| Profit factor líquido | 1.125 | 1.097 |
| Utilização de capital ponderada no tempo | +10.53% | +10.38% |
| Maior risco agregado de stop observado | +5.89% | +5.89% |

Conferência: BASE 21.669,85 − 4.434,71 − 2.217,35 − 1.658,40 = 13.359,39 USDT. STRESS 13.186,26 − 3.287,37 − 2.191,58 − 1.333,32 = 6.373,98 USDT. O menor drawdown observado no cenário STRESS decorre da mudança de ordens e trajetórias de posições; não demonstra que custos maiores reduzem risco.

### Atribuição por motor

| Motor | BASE: operações | BASE: líquido USDT | STRESS: operações | STRESS: líquido USDT |
|---|---:|---:|---:|---:|
| CORE | 458 | 6,834.42 | 479 | 5,440.97 |
| REV1H | 173 | 5,028.66 | 249 | 4,306.24 |
| REV15M | 729 | 1,496.31 | 282 | -3,373.22 |

REV15M tem 6.628,67 USDT brutos no BASE, mas perde 5.085,88 USDT apenas em comissões + slippage; no STRESS seu lucro bruto já é negativo (−503,86 USDT), com perda líquida de 3.373,22 USDT. É a fragilidade econômica mais visível nesta versão. Cortá-lo com base nestes resultados seria uma nova seleção sobre a amostra já examinada: qualquer alteração precisa ser registrada como nova hipótese e avaliada em dados futuros intocados.

### Retornos por calendário (diagnóstico retrospectivo)

| Ano | BASE | STRESS |
|---|---:|---:|
| 2021 | +36.10% | +40.73% |
| 2022 | -15.11% | -19.81% |
| 2023 | +31.65% | +34.54% |
| 2024 | +32.66% | +11.75% |
| 2025 | +12.70% | -0.23% |
| 2026 (jan–jun) | +2.72% | -3.27% |

Janelas cronológicas independentes do código executadas até 31/12/2022, 31/12/2023, 31/12/2024, 31/12/2025 e 30/06/2026 preservam o prefixo do ledger integral (51.977, 80.969, 115.310, 139.137 e 145.355 eventos no BASE). Elas provam causalidade de replay, mas **não são OOS intocado**: o histórico de 2021–2026 já foi consultado na seleção dos alfas. Não há registro completo das tentativas anteriores.

## Gate 3: quinze invariantes

| # | Invariante | Resultado | Evidência principal |
|---:|---|---|---|
| 1 | `future_data_perturbation` | **PASS** | Perturbações futuras e corte intrabar com posição aberta não mudam prefixo conhecido. |
| 2 | `prefix_replay` | **PASS** | Replay do prefixo coincide em 20.349 e 20.404 eventos. |
| 3 | `next_observation_execution` | **PASS** | Entradas na observação seguinte; eventos ORDER/OPEN auditáveis. |
| 4 | `no_prelisting_trades` | **PASS** | Nenhum trade anterior ao primeiro funding arquivado de cada ativo elegível. |
| 5 | `conservative_intrabar_execution` | **PASS** | Stop primeiro e gaps desfavoráveis em candle ambíguo. |
| 6 | `closed_only_realized_regime` | **PASS** | Regime calculado com lucros de trades fechados. |
| 7 | `mtm_equity_reconciliation` | **PASS** | Equity MTM reconciliada; maior erro 1,82 × 10⁻¹² USDT. |
| 8 | `cash_margin_collateral_reconciliation` | **PASS** | Caixa, margem e colateral reconciliados. |
| 9 | `exposure_at_entry` | **PASS** | Exposição máxima próxima de 1x. |
| 10 | `aggregate_stop_risk` | **PASS** | Risco agregado máximo observado 5,893% / 5,891% (limite 6%). |
| 11 | `historical_fee_funding_reconciliation` | **BLOCKED** | 8.480 avaliações de funding BASE+STRESS em shadow/portfólio sem markPrice oficial; proxy explícito; tarifas históricas da conta indisponíveis. |
| 12 | `deterministic_full_replay` | **PASS** | Replay integral determinístico, 145.355 eventos BASE. |
| 13 | `chronological_walkforward_isolation` | **PASS** | Cinco prefixos cronológicos, sem ajuste de parâmetros; contaminação histórica explicitada. |
| 14 | `ledger_monthly_yearly_reconciliation` | **PASS** | Conferência dos 66 meses e seis anos contra ledger. |
| 15 | `baseline_fingerprint` | **PASS** | Commit, versões, hashes de entrada, suplementos e ambiente presentes. |

No endpoint histórico de funding foram reconciliados 207.704 eventos em 38 símbolos, sem divergências de taxa; 85.882 eventos retornaram `markPrice` vazio. No ledger BASE, 4.257 de 10.424 avaliações de funding de shadow/portfólio usam proxy; no STRESS, 4.223 de 10.421. O total de 8.480 conta avaliações dos dois cenários e não 8.480 pagamentos independentes. A reconciliação aritmética de caixa passou, mas não substitui a origem histórica do preço de liquidação exigida pelo invariante 11.

## Diagnóstico e correções na ordem adequada

1. **Resolver o bloqueio metodológico do funding.** Buscar e congelar uma série independente, histórica e verificável do preço de liquidação `markPrice` nos horários dos 8.480 eventos afetados, com proveniência, timestamps, checksum e cobertura. Caso a fonte não exista para o período, é preciso decidir *antes de consultar retornos* se o escopo da validação técnica será prospectivo ou restrito a datas com preços reais verificáveis; registrar a mudança de contrato e executar novamente o Gate 3. Proxies continuam identificados como diagnóstico.
2. **Reconciliar execução real.** Confrontar comissões de cada nível de conta, spread, profundidade, lotes mínimos, filtros de quantidade/preço, partial fills, liquidação, margem por nível, preço de marcação e ordem intrabar contra fills de paper/conta. O modelo atual assume tarifas fixas e quantidades contínuas; seu risco de modelagem não está resolvido pelo job verde.
3. **Reconstruir o universo temporal.** Carimbar listagem e deslistagem a partir de metadados independentes, resolver sobrevivência/seleção da coorte de 39 ativos. Primeiro funding arquivado é só limite inferior de negociabilidade.
4. **Congelar novo protocolo para OOS verdadeiro.** Depois de TECHNICALLY_VALID, registrar código, dados, riscos, custo, hipóteses e critério econômico antes das primeiras observações futuras; holdout já predefinido de 180 dias e pelo menos 100 trades fechados, sem retuning com essas observações. Se a amostra não chegar ao mínimo, classificar como inconclusivo.
5. **Tratar REV15M como hipótese separada após medir OOS.** Sua contribuição fica negativa sob custos/atraso. Registrar ablação e variantes como novas tentativas, validar contra o portfólio congelado em dados ainda não vistos e conferir perdas de diversificação; não remover retroativamente só por esta tabela.
6. **Exigir meta economicamente coerente.** 20% compostos por mês por 12 meses equivalem a 791,61% ao ano. A reconstrução aponta 1,29% ao mês no BASE, 0,75% no STRESS, uso médio de capital de cerca de 10% e drawdown elevado; aumentar alavancagem para fechar a diferença extrapolaria um resultado ainda não validado. Especificar horizonte, tolerância de drawdown e critério de sucesso futuro antes de buscar novos sinais.

## Limites e decisão

A engenharia melhorou: candle faltante recomposto sem alterar os dados originais, replay USD-M nativo do CORE/REV1H/REV15M, portfolio ledger compartilhado, financiamento em horários reais, custos e stress declarados, replays cronológicos e proteção contra olhar preços futuros. Ainda restam preço oficial do funding histórico, marcação por preço de bolsa, execução intrabar com OHLC, viés do universo fixo e ausência de OOS intocado. **Não promover a R16.29.2 a TECHNICALLY_VALID, OOS_VALIDATED, PAPER_CANDIDATE ou produção. R16.24.2 permanece a baseline validada.** A questão metodológica pendente é a origem do preço oficial no período 2021–2026 ou a aprovação prévia de um novo período técnico, sempre sem reclassificar esse retrospecto como OOS.

Arquivos completos no artefato: `integrity_gate3.json`, `summary.json`, `base_metrics.json`, `stress_metrics.json`, `base_ledger.jsonl.gz`, `stress_ledger.jsonl.gz`, trades, MTM diário, protocolos e hashes. SHA-256 de cada entrada no `artifact_manifest.json`.
