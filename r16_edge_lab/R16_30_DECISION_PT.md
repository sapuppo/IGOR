# R16.30 — decisão sobre as tentativas de buscar 20% ao mês

**Conclusão:** nenhuma estratégia examinada demonstrou 20% mensais. A melhor comparação retrospectiva entre estas tentativas foi a H1, que remove REV15M: 1,22% mensais compostos no cenário STRESS, drawdown MTM de 21,88% e **zero dos 66 meses com retorno de pelo menos 20%**. Houve 29 meses negativos e o pior mês foi −9,52%. A H2, com short de tendência em 4h, foi rejeitada por piorar retorno e drawdown. Não modificar a baseline validada R16.24.2 nem implantar nenhuma das candidatas em capital real.

## Registro das tentativas e trilha de auditoria

| Versão/hipótese | STRESS: retorno mensal composto | Drawdown MTM | Resultado |
|---|---:|---:|---|
| R16.29.2, CORE + REV1H + REV15M | 0,75% | 27,96% | Diagnóstico tecnicamente bloqueado |
| [R16.30 H1](R16_30_H1_RESULT_PT.md), CORE + REV1H | **1,22%** | **21,88%** | Melhora retrospectiva, candidata apenas à pesquisa |
| [R16.30 H2](R16_30_H2_RESULT_PT.md), H1 + CORE_SHORT | 1,00% | 27,66% | Hipótese rejeitada conforme critério prévio |

H1 foi pré-registrada no commit `aeb7cda316953c2a5a2c8d88d1a4d856a0d33a46`; H2 no commit `b57d53559b79e2e746ae4cd50c148ced82f20625`. Os resultados e scripts estão na branch `r16-30-research`. Artefato de trades, métricas e hashes: `IGOR_R16_30_RESEARCH_EVIDENCE.zip`, SHA-256 `3a9d35fa6d835f6e4aa297a0573a3f2d6282880997c6ab0bd453f94616128c3c`. A reconstrução do portfólio original foi reproduzida com os mesmos hashes de ledger antes de cada ablação; H2 repetiu os próprios hashes e passou em corte causal com perturbação futura. Apenas um arquivo local divergente de LTCUSDT 15m foi isolado e recuperado para a cópia de pesquisa, preservando seu SHA-256 congelado.

## Onde se perde a meta

1. **Vantagem líquida insuficiente:** a H1 STRESS usa capital por cerca de 10,08% do tempo, apresenta fator de lucro de 1,222, mediana mensal de +0,21% e 29 meses negativos. A H2 elevou o uso de capital para 12,84%, mas reduziu a taxa mensal composta para 1,00%. A mera ocupação de capital não cria lucro.
2. **Sensibilidade à execução:** o REV15M original cai de +1.496 USDT líquidos no BASE para −3.373 USDT no STRESS. Retirá-lo melhora a simulação, mas essa escolha foi feita *após olhar a amostra*: o ganho não é evidência OOS.
3. **Short específico sem edge:** CORE_SHORT perde 385 USDT líquidos no BASE e 211 USDT no STRESS, além de deslocar CORE/REV1H dentro da carteira compartilhada. A H2 falha no critério de melhora em STRESS com drawdown não maior.
4. **Integridade ainda bloqueada:** falta preço oficial exato para parte dos pagamentos históricos de funding; o arquivo de candle por minuto é diferente do preço cobrado em 11/27 exemplos verificáveis. Tarifas históricas específicas da conta, fills reais, book e restrições históricas ainda não foram reconciliados; a coorte de 39 símbolos foi fixada retrospectivamente. [Auditoria R16.29.2](R16_29_2_AUDIT_REPORT_PT.md) e [estudo do preço de funding](R16_29_2_FUNDING_SOURCE_CHECK_PT.md).
5. **Sem avaliação futura independente:** a amostra 2021–2026 já foi usada para escolher alfas e para escolher H1/H2. Repetir ajustes até ver 20% nela seria seleção retrospectiva. O inventário completo das tentativas anteriores é desconhecido.

Vinte por cento compostos por 12 meses seriam aproximadamente **791,6% em um ano**. Alcançar a meta atual exigiria um salto de 16,3 vezes sobre o retorno mensal composto observado na H1 STRESS; isso é somente comparação aritmética, **não** projeção de que alavancar 16,3x a estratégia produziria esse retorno. O drawdown simulado da H1 já é 21,88% sem essa alavancagem.

## Sequência de trabalho que preserva a validade

1. **Resolver o invariante de funding** com preço efetivo documentado em cada evento antigo; se indisponível, revisar explicitamente o contrato e o período antes de consultar retornos de outra janela. Nem H1 nem H2 altera esse bloqueio.
2. **Reconciliar execução USD-M** com amostras independentes de operações paper e extratos reais ou exportados: comissão efetivamente cobrada, spread, slippage, ordens parciais, filtros históricos e marcação de margem. Sem dados da conta, a taxa fixa continua hipótese.
3. **Congele um candidato para observações futuras** apenas depois da aprovação técnica; H1 pode ser levada ao protocolo prospectivo como hipótese histórica conhecida, jamais como comprovadamente lucrativa. Registrar data de início, código e tentativa, limites de perda e sucesso *antes* do primeiro dado. Aplicar os 180 dias/100 trades predefinidos e marcar INCONCLUSIVO se não alcançar amostra suficiente.
4. **Desenvolver novos motores apenas com orçamento de tentativas registrado e futuras janelas independentes.** Próximas ideias exigem sinal realmente novo líquido de custos, e não tamanho maior, taxas irreais ou seleção de símbolos vencedores. Para qualquer nova ideia, exigir valor incremental no portfólio compartilhado BASE e STRESS, queda controlada e ausência de violação de Gate 3 antes de pensar em paper.

**Classificação final:** pesquisa retrospectiva; `TECHNICALLY_INVALID`, `OOS_VALIDATED=false`, capital real não autorizado. A R16.24.2 permanece a última baseline validada; lucro de 20% ao mês continua **não demonstrado**.
