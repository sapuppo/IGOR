# R17.07 — comparação executada e alterações de pesquisa

Rodada concluída em 5 de outubro de 2026. A baseline de produção R16.24.2 não foi substituída. A comparação usa o simulador de pesquisa R16.29.2, com o mesmo capital inicial de US$ 10.000 e janela de janeiro de 2023 a junho de 2026 para todas as alternativas.

## Resultado principal

A configuração `pair_fixed`, selecionada pelo retorno de 2023–2024 entre alternativas com queda máxima de até 20% nessa janela, passou de 0.61% para 1.54% ao mês em média geométrica. O retorno acumulado passou de 28.90% para 90.31%, e a queda máxima sobre o patrimônio marcado a mercado caiu de 31.69% para 18.74%.

Isso é uma melhora retrospectiva, não lucro real nem evidência de 20% mensais. A configuração escolhida não alcançou 20% em nenhum dos 42 meses. Seu primeiro semestre de 2026 rendeu somente 0.29%.

## Alterações concretas no candidato

- Retirar REV15M da carteira de pesquisa. Seu resultado anterior com custos e atraso era negativo; a retirada foi confirmada em replay completo da carteira, incluindo competição por capital.
- Manter CORE (tendência 4h) e REV1H (reversão 1h), sem novos ajustes nos indicadores, stops, alvos ou duração máxima.
- Trocar os multiplicadores de dimensionamento 0,5/1,5 por 1,0 fixo. O filtro causal de resultados dos sinais simulados nos seis meses anteriores permanece.
- Manter risco nominal por entrada CORE 0,75% e REV1H 1%, teto por posição 40%, limite agregado de risco de stop 6%, garantia de entrada sem alavancagem superior a 1x e cinco posições por motor. Stops podem sofrer gaps e não garantem perda máxima.
- Preservar exclusão de posições simultâneas na mesma moeda e as regras de agrupamento de reversões.

O arquivo `r17_07_candidate_config.json` documenta essas regras. O executor desta rodada aplica as configurações em memória sobre o motor original, sem alterar seu código. A integração em um executor prospectivo ainda não foi realizada; nenhuma ordem real foi enviada.

## Oito configurações registradas antes da execução

Taxa de 0,06% e slippage de 0,04% por lado, entrada atrasada 15 minutos, funding histórico incluído conforme o modelo disponível. Sem aumento de alavancagem.

| Configuração | Acumulado | Média composta mensal | Maior queda | 2026 jan–jun | Meses ≥20% |
|---|---:|---:|---:|---:|---:|
| Controle: três motores, regras R16.29.2 | 28.90% | 0.61% | 31.69% | -4.43% | 0/42 |
| Somente tendência, multiplicador original | 22.73% | 0.49% | 9.27% | -1.14% | 0/42 |
| Somente reversão 1h, multiplicador original | 14.17% | 0.32% | 4.45% | 1.38% | 0/42 |
| Tendência + reversão 1h, multiplicador original | 62.79% | 1.17% | 24.13% | -1.73% | 0/42 |
| Somente tendência, multiplicador fixo 1 | 47.62% | 0.93% | 17.84% | -2.38% | 0/42 |
| Tendência + reversão 1h, multiplicador fixo 1 | 90.31% | 1.54% | 18.74% | 0.29% | 0/42 |
| Dupla fixa, risco por entrada +50% | 109.06% | 1.77% | 30.15% | -0.43% | 1/42 |
| Dupla fixa, risco +50%, teto por posição 60% | 109.03% | 1.77% | 30.42% | 0.50% | 1/42 |

As duas alternativas de risco aumentado atingiram 20% em apenas um mês, com quedas próximas de 30%. Foram rejeitadas pelo critério registrado. Aumentar o teto por posição de 40% para 60% quase não ajudou. Não há evidência de que mais exposição resolva a meta.

## Candidato escolhido: resultados anuais

| Ano | Retorno líquido simulado |
|---|---:|
| 2023 | 28.41% |
| 2024 | 28.36% |
| 2025 | 15.14% |
| 2026 (janeiro–junho) | 0.29% |

## 2026 mês a mês

| Mês | Candidato | Controle |
|---|---:|---:|
| 2026-01 | 1.85% | 3.66% |
| 2026-02 | 2.01% | 0.15% |
| 2026-03 | -0.49% | -0.24% |
| 2026-04 | -4.60% | -2.32% |
| 2026-05 | 2.24% | -2.03% |
| 2026-06 | -0.56% | -3.57% |

Julho a dezembro não têm resultados nesta rodada. O dataset verificado termina em junho; não foram inventados números para completar o ano. A média geométrica mensal do candidato no primeiro semestre foi 0.05%. A melhora desse semestre em relação ao controle foi de 4.72 pontos percentuais.

## Sensibilidade: custos dobrados

Uma execução adicional, prevista no protocolo e aplicada somente ao candidato escolhido, dobrou taxa para 0,12% e slippage para 0,08% por lado, mantendo o atraso de entrada.

- Acumulado: 74.30%.
- Média composta mensal: 1.33%.
- Maior queda: 20.15%.
- Primeiro semestre de 2026: -0.90%.

O resultado de 2026 torna-se negativo. A rentabilidade recente ainda é pequena e sensível aos custos.

## O que foi verificado e o que falta

Foram recuperados três arquivos locais truncados, sem modificar os preços, a partir dos artefatos originais de GitHub Actions. Depois, os 152 arquivos passaram na verificação SHA-256 do manifesto congelado. O cache de sinais e o código do motor também correspondem às assinaturas da auditoria anterior.

Os nove replays reconciliaram caixa/patrimônio. A soma independente dos resultados líquidos de cada operação coincide com o patrimônio final; o produto dos retornos mensais coincide com o acumulado. Nenhuma barra faltou enquanto havia posições ativas nesta janela. Os testes existentes do livro contábil passaram, incluindo garantia, risco agregado, funding, ordem temporal e determinismo. `verification.json` registra a conferência.

Os dados de 2023–2026 já tinham sido consultados em pesquisas anteriores. Portanto, nem 2025 nem 2026 são teste fora da amostra intocado. A seleção desta rodada usou apenas 2023–2024, mas isso não apaga a contaminação anterior. As 38 moedas foram selecionadas anteriormente e não representam um universo livre de viés de sobrevivência. O funding usa preços negociados como aproximação, sem a série oficial completa de mark price. Não foram calculadas significância estatística corrigida pela busca histórica nem probabilidade validada de atingir a meta.

## Próxima decisão fundamentada

O candidato merece validação prospectiva em simulação com captura pontual e custos reais observados; não merece promoção automática para produção. O caminho preparado em R17.06 para coleta em horários fixos precisa de um host permanente, e o motor desse candidato ainda precisa ser integrado a ele. É necessário também ampliar o histórico verificado além de junho e obter mark price para funding antes de afirmar uma vantagem operacional validada.

A meta de 20% ao mês continua sem suporte. A mudança executada melhora o histórico, mas o resultado recente não permite afirmar que passamos a ter retorno significativo e consistente em 2026. Repetir ajustes até forçar essa meta no mesmo histórico não constitui validação.

## Reprodução e arquivos

Executar `python run_r17_07_portfolio_ablation.py` dentro de `r16_edge_lab`, com dependências R16 e o dataset original `usdm_history`, além do cache `r16_29_2_audit/signals.jsonl.gz`. O driver recusa arquivos cujas assinaturas não correspondam à auditoria. O protocolo foi registrado antes das execuções no commit `94be4d81c58613164fb168b521520bb3b2efe47b`.

`r17_07_results/summary.json` contém as nove configurações, retornos mensais, atribuições, diagnósticos, hashes dos CSVs e dos livros de eventos. Os CSVs de operações e patrimônio permitem conferir os cálculos. As assinaturas dos livros permitem conferir uma reprodução, mas os livros completos de eventos não são exportados nesta rodada.
