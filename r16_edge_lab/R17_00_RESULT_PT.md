# R17.00 — primeiro candidato de reconstrução: rejeitado

Relatório de pesquisa, 27/09/2026. Protocolo congelado no commit `04c566499a4fbff43e61e5ebba8fa1ae4a6c59f2` **antes** deste resultado. Baseline R16.24.2 intocada; nenhum sinal R17 pode abrir ordens reais.

## O que foi executado

`R17-CSMOM-W1`: 2 compras e 2 vendas semanais entre 38 pares USD-M, ranking causal de 7 dias, 15% do patrimônio por posição, stop individual de 4%, próximo rebalanceamento em 7 dias. Dados 4h verificados por SHA-256: 152/152 arquivos iguais ao manifesto `a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041`. Os 38 pares são a coorte histórica congelada, não reconstrução sem sobrevivência.

Geração: 139 semanas entre 06/11/2023 e 29/06/2026, todas com 20 ou mais pares aptos (mínimo 21), 556 posições fechadas. Entrada na abertura das 04:00 UTC após cada sinal de segunda-feira às 00:00. Custos presumidos BASE e STRESS predefinidos no protocolo; funding usa `fundingTime`, `fundingRate` e **`markPrice` oficial** no recorte e confere SHA do suplemento. Capital inicial de 10.000 USDT, janela 01/11/2023 a 01/07/2026 exclusivo, 32 meses. Códigos e resultados têm testes de causalidade das velas, lacunas e conciliação offline; nenhuma execução real.

| Cenário | Saldo simulado final | Retorno acumulado | Equivalente mensal composto | Queda máxima diária MTM | Jan–jun/2026 | Stops / trades |
|---|---:|---:|---:|---:|---:|---:|
| BASE | 6.935,57 USDT | −30,64% | −1,14% | 34,47% | −16,51% | 433 / 556 |
| STRESS | 6.571,79 USDT | **−34,28%** | −1,30% | **35,65%** | **−17,36%** | **433 / 556** |

No STRESS, comissões presumidas consumiram 842,38 USDT e o funding líquido foi −18,28 USDT. O comparativo H1 no mesmo recorte tinha +30,63% e drawdown 21,88%; este candidato perde e cai mais. Não houve ganho consistente de 20%/mês: só novembro de 2024 ficou acima de +20% (+27,72%), isoladamente em 32 meses.

As 278 compras perderam 1.433,70 USDT líquidos e as 278 vendas perderam 1.994,51 USDT líquidos. Mesmo antes de comissões e funding, as compras perderam 915,98 USDT nas saídas e as vendas 1.651,58 USDT; o problema não se resume a taxas elevadas.

| Mês de 2026 | Retorno STRESS simulado |
|---|---:|
| Janeiro | −5,41% |
| Fevereiro | −5,13% |
| Março | −1,93% |
| Abril | +3,37% |
| Maio | −3,37% |
| Junho | −5,98% |

**Limite de sequência intrabar:** em 236 velas STRESS houve stop e evento de funding no mesmo candle 4h; a ordem dos dois não é recuperável dessas velas. Mesmo dando ao candidato a hipótese mais favorável para **todos** esses eventos, o retorno STRESS permaneceria no máximo em −33,90% (variação máxima de 38,16 USDT). Isso é um limite para esse problema específico, não um intervalo completo de incerteza de mercado. A exposição bruta de entrada foi aproximadamente 60%; barras ativas ausentes: zero. Fills, spreads e comissões efetivos da conta não foram fornecidos; a simulação segue `TECHNICALLY_INVALID`, `OOS_VALIDATED=false`, `LIVE=false`.

## Decisão e causa operacional

**DESCARTAR R17-CSMOM-W1 sem alterar parâmetros.** O stop foi acionado em 433 das 556 posições (78%), e a tentativa de neutralizar mercado não trouxe vantagem líquida nesta amostra. Ampliar stop, trocar semana, inverter sinal, remover símbolos ou aumentar risco após ver o resultado violaria o protocolo de tentativa única e deixaria o resultado ajustado ao passado.

A ferramenta `r17_execution_audit.py` foi criada para comparar `userTrades`, `income` e referências de preço das decisões do robô, rejeitando fills duplicados, comissões em moedas sem conversão, divergências de comissão/PNL e decisões registradas depois do fill. Ela **não aprova conta ou estratégia**: mesmo com entradas sintéticas completas continua `NOT_READY` até haver cobertura comprovada e saldo inicial/final. Não havia extratos reais do usuário entre os arquivos do projeto; portanto nenhum custo real foi declarado medido.

Próxima decisão técnica: obter extratos oficiais das operações **se existirem**, referências de preço contemporâneas do robô e saldos da conta; apenas depois definir custos observados e registrar a hipótese **de outro candidato** antes de testá-la. A Binance documenta `userTrades` por símbolo, `income` com `FUNDING_FEE` e `COMMISSION`, e exportações assíncronas de histórico de trades/transações. Não enviar senhas/chaves de API para a pesquisa. Até surgirem dados novos e uma vantagem demonstrável, não há base para substituir o baseline ou prometer 20% ao mês.

Artefatos locais: `R17_CSMOM_W1_REPLAY.json` (SHA-256 `68a9d757ab7d31c63d1cb5ac6c73e27520a9c69dc429c9d7293800bae0cbeee2`), `R17_CSMOM_W1_DIAGNOSTICO_SINAIS.json` (SHA-256 `91a730e3fedf92f1625e5242aaa5eba8b05b13c6977cb00d3e7f12c315c4f892`). O JSON do replay inclui hashes do código, protocolo e suplemento de funding usados.
