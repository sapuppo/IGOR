# R16.32 — método fixado para relatório mensal de 2026

**Registrar antes de ler o retorno da carteira reiniciada em 2023.** Pedido do usuário: informar percentuais mensais no ano de 2026. A fonte congelada vai somente até 30/06/2026, portanto serão publicados janeiro, fevereiro, março, abril, maio e junho; julho a dezembro ficam sem avaliação, sem interpolação. Nenhuma nova estratégia, filtro, símbolo, alavancagem, parâmetro de fee/slip ou escolha entre BASE e STRESS será testada.

## Séries que serão divulgadas

1. **Principal, H1 com funding de origem completo:** reaplicar a mesma política CORE + REV1H de R16.30 nas duas hipóteses congeladas BASE/STRESS; carteira reiniciada em 10.000 USDT em 01/11/2023; 2021–outubro/2023 só para aquecer sinais causais. Verificar SHA-256 do ledger contra os dois valores de R16.31: `4f29c9046ea921dfc676616670f63987422d75474ea7419feaac1482ee9fe151` (BASE) e `1499a6fb2ef83f56d0054f1354c3a2f7d4164fa2a8c4584066cfb027801782cc` (STRESS).
2. **Comparação de sensibilidade ao ponto de partida:** extrair os mesmos seis meses dos relatórios H1 já congelados cujo capital iniciou em 2021. Mostrar diferenças, sem escolher a série mais favorável. Contexto adicional R16.29.2 original apenas se explicitamente identificado como candidato anterior; a R16.24.2 citada pelo usuário não está sendo medida nesse replay.

Retorno de cada mês = `equity MTM do último dia UTC do mês / equity MTM do último dia UTC do mês anterior − 1`, custos modelados e funding incorporados. O total de janeiro–junho é o produto de `1 + retorno mensal` menos 1; a média mensal composta observada é `(1 + retorno acumulado)^(1/6) − 1`. Para janeiro/2026 o denominador é dezembro/2025, já dentro da janela restrita. Verificar datas e continuidade de todos os seis meses e que as duas formas de calcular o total concordem. Relatar número de meses positivos, negativos e pelo menos +20%.

**Estado metodológico:** retornos exclusivamente simulados, escolhidos e pesquisados em janela já vista; a cobertura de preço de funding é um subteste técnico e não constitui garantia de spread, taxas históricas de conta, fills ou OOS. `TECHNICALLY_INVALID`, `OOS_VALIDATED=false`, nenhum capital real liberado. Não alterar a baseline R16.24.2.
