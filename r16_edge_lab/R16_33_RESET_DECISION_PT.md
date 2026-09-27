# R16.33 — decisão após diagnóstico e dois testes registrados

Data: 27/09/2026. Base operacional preservada: **R16.24.2 – Portfolio Integration**. Pesquisa feita na ramificação `r16-33-research`; nenhuma alteração operacional nem promoção de estratégia.

## O que está quebrado

1. A meta de 20% líquidos por mês não aparece na evidência: 20% mensais compostos equivalem a aproximadamente 792% ao ano. O melhor comparativo STRESS do recorte verificável gerou 0,84% ao mês composto; de janeiro a junho de 2026, −0,53% acumulado. Não confundir simulação com rendimento da conta.
2. O CORE aceita entradas mesmo quando seu score de shadows dos últimos seis meses está negativo, desde que o regime não seja HOT. REV1H não tem essa exceção. O CORE perdeu no semestre de 2026, mas contribuiu positivamente em parte do histórico anterior: eliminá-lo com base somente nesse semestre seria ajuste a posteriori.
3. As comissões, o spread, o deslizamento e o preenchimento continuam presumidos; faltam fills reais reconciliados. Parte do histórico anterior a novembro de 2023 tem 85.882 eventos sem preço oficial de funding, razão para limitar a análise de funding exato ao recorte a partir dessa data.
4. A seleção de motores e símbolos, os parâmetros e a leitura dos resultados de 2026 foram feitos antes destes testes; logo o recorte é desenvolvimento retrospectivo, sem amostra independente. O gargalo é demonstrar vantagem líquida reprodutível, não aumentar risco até que apareça um número desejado.

## Ensaios R16.33

Registrados previamente em `R16_33_RESET_PREREG_PT.md`, commit `b12c51ed14b2634b37bf969efd107d4cacab1f0a`. Carteiras independentes com 10.000 USDT, de 01/11/2023 inclusive a 01/07/2026 exclusivo (32 meses), 38 símbolos e sinais congelados, BASE e STRESS. H1 foi reproduzida antes dos ensaios; hashes de ledger BASE `4f29c9046ea921dfc676616670f63987422d75474ea7419feaac1482ee9fe151` e STRESS `1499a6fb2ef83f56d0054f1354c3a2f7d4164fa2a8c4584066cfb027801782cc`. Funding por proxy: zero; buracos de barras ativas: zero; exposição bruta na abertura até 100% e fração de risco até 6%.

| Versão | Mudança | BASE retorno total | STRESS retorno total | STRESS/mês composto | STRESS DD máximo MTM | STRESS jan–jun/2026 | Decisão registrada |
|---|---|---:|---:|---:|---:|---:|---|
| H1 | CORE + REV1H | +44,06% | +30,63% | +0,84% | 21,88% | −0,53% | Comparativo, não validada |
| H3 | Filtro de score negativo também no CORE | +33,26% | +24,34% | +0,68% | 21,88% | +0,27% | DESCARTAR: perda de retorno no recorte |
| H4 | Só REV1H, regime HOT adaptado a um motor | +30,57% | +22,15% | +0,63% | 14,50% | +2,62% | DESCARTAR: perda de retorno no recorte |

H3 fez cerca de 30 trades fechados no semestre STRESS; H4, 15; H1, 51. A melhora do semestre e a menor queda máxima de H4 são observações retrospectivas, não prova de que H4 será melhor adiante. Nenhum ensaio alcançou sequer um mês de +20% no cenário STRESS. Os dois foram rejeitados conforme os critérios publicados antes dos resultados. A consulta anterior a 2021–2026 mostra outros retornos, mas mistura o trecho de funding sem `markPrice` oficial; não deve ser comparada diretamente a esta janela.

**Limite de auditoria desta entrega:** o ambiente temporário apagou os arquivos brutos dos ensaios após a execução. Este relatório registra métricas e hashes H1 observados; os ledgers e hashes H3/H4 precisam ser reproduzidos a partir de código e fontes congeladas antes de qualquer auditoria independente. Isso reforça `TECHNICALLY_INVALID`, `OOS_VALIDATED=false`, `LIVE=false` para as variantes. É incorreto chamar esses números de lucros realizados ou de backtest aprovado.

## Mudança de rumo decidida

- Encerrar a busca de parâmetros em 2021–junho/2026. R16.24.2 continua sendo o último baseline validado; H1, H3 e H4 são pesquisa e não substituem o robô principal.
- Reconstruir a próxima família de estratégias (R17) como projeto separado: testar hipóteses de vantagem em regimes diferentes, inclusive operações compradas e vendidas, com custos medidos por ordem, limite de perdas e capital total compartilhado. A direção de cada operação depende de hipótese predefinida e filtros de risco; não abrir posições vendidas ou aumentar alavancagem só para elevar retorno histórico.
- Para cada candidato, registrar **antes** de usar dados futuros: regras exatas de sinal/saída, símbolos elegíveis, risco, custos, período de treino, período intocado de validação e limite de tentativas. Proibir trocas de universo, parâmetros ou janelas depois de ver o resultado da validação.
- Reconciliar ordens, comissões, funding, preços de execução, latência e saldo com extratos da conta; bloquear uso em produção enquanto os custos reais forem desconhecidos. Descartar candidato se a vantagem desaparecer no STRESS ou se houver dados ausentes, antecipação de informação ou concentração excessiva.
- Liberar qualquer nova estratégia somente após implementação reproduzível e confirmação **prospectiva** de ao menos 180 dias e 100 operações fechadas com resultado líquido positivo, queda máxima aceitável predefinida e relatório por mês. Essa regra é requisito de evidência; não implica que 20% mensais sejam atingíveis ou prováveis.

Próximo experimento executável: congelar custos observados e a especificação R17 **antes** da coleta do novo conjunto de validação, reproduzir os ledgers perdidos para auditoria e construir apenas candidatos cuja hipótese econômica esteja descrita previamente. Com os dados atuais não há base técnica para prometer 20% ao mês nem para modificar a estratégia operacional.
