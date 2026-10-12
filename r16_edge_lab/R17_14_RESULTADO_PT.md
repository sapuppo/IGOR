# R17.14 — concentração, custos e regime

Data: 12/10/2026. **CORE/REV1H mantém lucro simulado após retirar as maiores contribuintes, mas continua fraca para a meta de 20% ao mês.** Nenhuma nova configuração foi promovida para o robô principal.

## Resultado dos replays completos

Período: janeiro/2023 a junho/2026. Mensal = taxa composta equivalente dos 42 meses, não lucro recorrente garantido. DD = queda máxima da equity marcada nos eventos do simulador. 2026 = primeiro semestre, não ano completo. Valores em %.

| Teste | Mensal | DD | 2025 | Jan–jun/2026 |
|---|---:|---:|---:|---:|
| CORE/REV1H original | 1.54 | 18.74 | 15.14 | 0.29 |
| Custos dobrados | 1.33 | 20.15 | 13.78 | -0.90 |
| Sem ALGO (top 1 de 2023–2024) | 1.47 | 18.83 | 16.05 | 1.08 |
| Sem ALGO, BNB e BCH | 1.29 | 15.66 | 15.46 | 2.99 |
| Sem top 3 + custos dobrados | 1.04 | 17.05 | 12.10 | 1.81 |
| Sem BNB, XRP e ALGO (diagnóstico retrospectivo) | 1.29 | 15.08 | 10.36 | 2.00 |

A retirada foi feita antes da simulação, eliminando sinais e respectivos históricos shadow; o capital e as vagas foram recalculados pela carteira. Não é subtração posterior dos lucros de determinadas moedas.

As três maiores contribuintes do período completo representam 35.36% do lucro líquido monetário das operações originais. Essa concentração merece acompanhamento, mas a vantagem não desaparece sem elas. O ranking para os testes de exclusão principal usou somente operações iniciadas e encerradas em 2023–2024; o ranking do período completo é um teste de fragilidade retrospectivo.

## Onde está o problema

O custo não elimina todo o lucro histórico de CORE/REV1H: a média cai de 1,54% para 1,33% ao mês. Porém, em janeiro–junho de 2026, os custos dobrados tornam o retorno da carteira negativo: −0,90%. O componente é mais resistente que o short da rodada anterior, mas a vantagem recente é insuficiente.

Retirar as moedas mais lucrativas não criou uma estratégia melhor: reduz o retorno mensal de longo prazo. O resultado favorável de algumas exclusões em 2026 não autoriza remover moedas porque o semestre ficou bonito.

## Regime de mercado

Classificação disponível antes da entrada: retorno do BTC nos 180 últimos intervalos de 4 horas fechados, aproximadamente 30 dias. Acima de +5% = alta; abaixo de −5% = baixa; entre eles = lateral. Esses nomes são uma definição operacional específica, não a descrição universal de todo o mercado.

| Regime na informação do sinal | Operações | Lucro líquido monetário simulado | Profit factor |
|---|---:|---:|---:|
| Alta | 345 | US$ 3887.91 | 1.21 |
| Baixa | 55 | US$ 2165.59 | 2.16 |
| Lateral | 107 | US$ 2977.72 | 1.53 |

As contribuições são P&L de operações classificadas pelo regime no sinal. Não são retornos de carteiras separadas nem garantem que o regime permaneceu igual até a saída.

A carteira combinada ganhou nos três grupos no histórico completo; não há base para proibir todas as entradas em um regime. Na amostra de operações abertas em 2026, CORE apresentou perdas em alta e lateralização; REV1H compensou parte delas em baixa. Isso descreve o diagnóstico retrospectivo e não define uma regra nova.

## Filtro de regime: nenhuma regra elegível

Regra registrada antes da rodada: por engine, bloquear apenas o regime de menor lucro monetário em 2023–2024 se ele fosse negativo e tivesse ao menos 30 operações encerradas. CORE tinha apenas uma operação no grupo negativo; REV1H tinha 28 no seu grupo negativo. Nenhum grupo satisfez a regra.

Os dois replays de filtro, com custos normais e dobrados, repetiram seus controles porque não havia regime elegível para bloquear. Eles não são novas estratégias independentes. O mínimo de 30 é um critério de triagem, não uma prova estatística. Não baixamos esse limite depois de ver os resultados nem criamos um filtro a partir das perdas de 2026.

## Retorno mensal de 2026 — CORE/REV1H

| Mês | Original | Custos dobrados | Sem top 3 de 2023–2024 |
|---|---:|---:|---:|
| 2026-01 | 1.85% | 1.42% | 3.79% |
| 2026-02 | 2.01% | 1.90% | 2.01% |
| 2026-03 | -0.49% | -0.61% | -0.49% |
| 2026-04 | -4.60% | -4.81% | -3.86% |
| 2026-05 | 2.24% | 1.93% | 2.24% |
| 2026-06 | -0.56% | -0.57% | -0.56% |

Sem dados verificados posteriores a junho: julho a outubro não têm retorno apurado. Esta tabela trata CORE/REV1H isolada; não deve ser confundida com a carteira híbrida 80/20 da R17.11.

## Verificação e recuperação dos dados

O arquivo de TAOUSDT/15m foi recuperado do pacote auditado `r16-29-audit-data-10.zip`, com SHA idêntico ao manifesto original. A cópia divergente foi preservada separadamente. Os 152 arquivos passaram; o manifesto não foi alterado.

O controle reproduziu as 507 operações, seus identificadores, P&L líquido e retorno de R17.07 pair_fixed. As oito execuções reconciliaram o caixa. A classificação de regime permaneceu igual no passado ao truncar ou alterar preços futuros do BTC. O cache de sinais e os três arquivos originais do simulador passaram na verificação de hashes.

Limitações: 38 moedas previamente selecionadas, histórico já consultado, funding com proxy de preço negociado, ausência de book/mark histórico oficial e saídas em OHLC. Os parâmetros de regime e o próprio teste foram escolhidos após exposição anterior ao conjunto. Não há validação independente fora da amostra, execução real ou paper contínuo nesta etapa. O problema de integridade foi resolvido; atualização dos dados e acesso autorizado à fonte continuam necessários.

## Decisão

**Preservar CORE/REV1H como referência de pesquisa, rejeitar a retirada de moedas como melhoria e não implantar filtro de regime sem evidência.** Há vantagem histórica distribuída, mas não progresso financeiro demonstrado nesta rodada. A meta de 20% mensais continua sem suporte.

O próximo teste útil deve mudar uma hipótese concreta de geração de lucro: separar CORE e REV1H, investigar a perda recente do CORE e validar uma regra causal previamente congelada. Dados ainda não usados são necessários para confirmar qualquer melhoria. Não compensar o retorno baixo aumentando alavancagem.

Reprodução: executar `python run_r17_14_concentration.py` dentro de `r16_edge_lab`, com o histórico auditado e os artefatos anteriores disponíveis. O pacote desta etapa contém o código, protocolo, relatórios e séries de trades/equity; não inclui o histórico volumoso nem a cópia divergente.
