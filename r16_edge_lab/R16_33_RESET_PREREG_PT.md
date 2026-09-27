# R16.33 — hipóteses de reparo registradas antes dos replays

**Decisão inicial:** manter R16.24.2 intacta. Não prometer nem ajustar backtest até exibir +20% ao mês. A H1 (CORE + REV1H) tem apenas −0,53% acumulado no STRESS janeiro–junho/2026, CORE perde no semestre e o portfólio trabalha com taxa/deslizamento presumidos. Esses resultados já foram vistos: todo o histórico 2021–junho/2026 é desenvolvimento retrospectivo, **sem OOS intocado**.

## Problema de implementação a isolar

O replay congelado rejeita REV1H se a média líquida dos seus shadows fechados em seis meses é negativa, mas abre uma exceção para `CORE` quando a carteira não está em regime HOT: `if scores[e] < 0 and not (e == "CORE" and not hot)`. Essa exceção permite aceitar sinais CORE de histórico recente perdedor. Ela foi identificada por inspeção do código após o relatório 2026, portanto corrigir esse caso é hipótese retrospectiva e não resultado independente.

## Duas variantes, nenhuma outra busca neste ciclo

| ID | Motores | Mudança única face à H1 |
|---|---|---|
| H3, gate estrito | CORE + REV1H | Aplicar `scores[e] < 0` também ao CORE; mantêm-se todos os demais parâmetros, sombra, custos e carteira. |
| H4, especialização | REV1H | Remover CORE e REV15M; preservar risco, stop e alvo do REV1H e calcular regime HOT quando o único motor elegível tiver score positivo (o critério de dois motores da carteira antiga seria inalcançável). |

Janela predefinida para as variantes: **01/11/2023 00:00 UTC a 01/07/2026 exclusivo**, começando cada carteira vazia com 10.000 USDT. Os dados anteriores só aquecem sinais causais. Usa os 38 símbolos, os 6.650 sinais congelados da R16.29.2 filtrados pelos motores permitidos, o dataset `a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041`, suplemento de gaps e marks verificados, custos BASE/STRESS originais, e o replay original do commit `f8c2307533265653f1faf0832fda836b21641f85`. É proibido alterar risco, regra do alpha, stops, metas, coorte, janela, fill, ordem de motores ou fees após olhar os resultados. R16.31 confirma markPrice exato nessa janela, mas comissões e fills reais continuam sem prova.

## Antes de ver o resultado

1. Reproduzir a H1 no mesmo recorte com hashes de ledger conhecidos: BASE `4f29c9046ea921dfc676616670f63987422d75474ea7419feaac1482ee9fe151`, STRESS `1499a6fb2ef83f56d0054f1354c3a2f7d4164fa2a8c4584066cfb027801782cc`. Bloquear tudo se a cópia do replay divergir.
2. Executar H3 e H4 **uma vez por cenário**; publicar ambas e H1 na mesma carteira e janela: retorno total, retorno mensal composto na janela, drawdown MTM, seis meses de 2026, trades, fees/slip/funding, máximos de risco e exposição, contagem de proxies de funding (esperado zero), buracos ativos (esperado zero), e hashes.
3. Classificar `DESCARTAR` se cenário STRESS piorar retorno ou drawdown ante H1 no recorte, mesmo que BASE melhore. Marcar `MERECE_TESTE_FUTURO` somente se STRESS melhorar retorno sem piorar drawdown, 2026 não for negativo, e testes de integridade da amostra passarem. Isso **não promove** estratégia, pois 2026 e os anos anteriores já foram vistos. Mostrar qualquer falha também.
4. Se ambas falharem, encerrar ajustes retroativos neste histórico e priorizar custo de execução real e um período futuro independente. Não multiplicar alavancagem para mascarar perda.

**Classificação fixa independentemente do resultado:** `TECHNICALLY_INVALID`, `OOS_VALIDATED=false`, `LIVE=false`; os 85.882 eventos históricos pré-novembro/2023 sem `markPrice` oficial e os custos de conta ausentes impedem reclassificar o backtest antigo.
