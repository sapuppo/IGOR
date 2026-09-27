# R16.32 — relatório mensal do robô em 2026 (simulação)

**Resultado principal, janeiro–junho de 2026:** a candidata de pesquisa H1 (CORE + REV1H) entregou **−0,53% acumulados no STRESS**, equivalentes a **−0,09% ao mês composto observado**. No BASE, o acumulado foi **+2,68%**, ou **+0,44% ao mês composto**. Foram **2 meses positivos, 4 negativos e nenhum mês com +20%**, nos dois cenários. Isto é *backtest*, não lucro de uma conta em negociação. A última baseline designada pelo usuário, R16.24.2, não foi alterada nem medida por este replay.

## Percentual de cada mês (equity marcado a mercado, USD-M, UTC)

| Mês 2026 | H1 BASE | H1 STRESS |
|---|---:|---:|
| Janeiro | +5,19% | +3,66% |
| Fevereiro | +1,44% | +0,15% |
| Março | −0,26% | −0,24% |
| Abril | −2,70% | −2,32% |
| Maio | −0,40% | −0,84% |
| Junho | −0,45% | −0,84% |
| **Janeiro–junho, composto** | **+2,68%** | **−0,53%** |
| **Equivalente mensal composto do semestre** | **+0,44%** | **−0,09%** |

Os arquivos congelados terminam em **30/06/2026**. Não há resultado de julho, agosto, setembro ou meses seguintes neste replay. O período de 2026 representado aqui é de seis meses, não o ano civil completo.

## Por que ficou abaixo da meta

Na carteira reiniciada em 01/11/2023 com 10.000 USDT, a equity em 31/12/2025 era 13.133,00 USDT no STRESS e fechou junho/2026 em 13.062,85 USDT. O ganho bruto realizado no semestre foi 102,54 USDT; **100,35 USDT em comissões modeladas, 66,90 USDT de slippage modelado e 5,44 USDT líquidos pagos em funding** geraram uma perda líquida de 70,15 USDT. As quatro parcelas conciliam exatamente com a variação de equity. Houve 51 operações fechadas no semestre (52 no BASE).

| Motor H1, STRESS em 2026 | Trades fechados | Resultado líquido simulado |
|---|---:|---:|
| CORE | 35 | −254,492 USDT |
| REV1H | 16 | +184,345 USDT |
| **Carteira** | **51** | **−70,147 USDT** |

CORE foi o maior detrator nesse semestre. Isso justifica investigá-lo, **sem desligá-lo porque este resultado retrospectivo foi visto**. BASE versus STRESS muda custos, preenchimento e até operações aceitas; a diferença entre os cenários não pode ser atribuída somente às taxas. No BASE, ganho bruto de 493,36 USDT menos 73,93 USDT de comissões, 36,96 USDT de slippage e 6,12 USDT de funding resultou em +376,35 USDT líquidos.

## Método e limites

O [método foi registrado antes da leitura do retorno](R16_32_2026_METHOD_PT.md), commit `498febaf8d17607e537dcb9bafa4ed6ed9a8425a`. A H1 reiniciada em novembro/2023 é a janela em que o subteste de `markPrice` de funding passou sem proxies, conforme R16.31; as mesmas porcentagens mensais foram verificadas independentemente no replay H1 contínuo iniciado em 2021, com diferença menor que `1e−10` no acumulado semestral. Os saldos absolutos dos dois pontos de partida diferem. O custo de comissão do BASE (0,04% por lado) e do STRESS (0,06% por lado), além de slippage (0,02% e 0,04% por lado), **continua uma hipótese do simulador**, pendente de fills e extratos de uma conta isolada. O arquivo `R16_32_2026_MONTHLY.json`, SHA-256 `458c4f47463428a005d2afb4943784e545838373fe2124a4a89d47ff6b47e91e`, registra todos os percentuais, equity mensal, custos, atribuição e hashes dos ledgers.

Como contexto, o candidato R16.29.2 original com REV15M teve **−3,27% no STRESS** em janeiro–junho/2026, enquanto a H1 teve −0,53%. A retirada de REV15M foi escolhida depois de examinar a amostra, de modo que essa comparação é diagnóstica e não uma validação fora da amostra.

**Estado:** `TECHNICALLY_INVALID`; `OOS_VALIDATED=false`; rendimento real da conta **não medido**. O subteste de funding exato após 01/11/2023 não conserta o funding de 2021–outubro/2023 no contrato integral nem prova que o spread, as tarifas específicas ou os preenchimentos reais são os da simulação. O próximo trabalho é reconciliar os três registros independentes já especificados em [R16_30_EXECUTION_GATE_PT.md](R16_30_EXECUTION_GATE_PT.md): planos de ordens, fills USD-M e extrato de todos os lançamentos da mesma conta/janela. **Meta de +20% ao mês: não demonstrada.**
