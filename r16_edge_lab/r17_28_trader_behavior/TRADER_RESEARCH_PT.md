# IGOR — pesquisa de comportamento de traders públicos

Consulta: 27/11/2026. Base de código preservada: R17.27, commit 94aef86d4e1b0b47fb1cafd2818fb308f19d8f56.

**Resultado desta etapa: triagem documental de nove carteiras, treze exemplos de movimentação reportados e uma rota de obtenção do histórico. A reconstrução de todas as operações dos dois anos NÃO foi executada. Nenhum histórico bruto foi baixado; nenhuma estratégia foi inferida quantitativamente, testada ou promovida.**

Janela alvo: 27/11/2024 00:00 UTC a 27/11/2026 00:00 UTC, fim exclusivo. Painéis consultados podem estar atualizados após esse corte; suas métricas servem para triagem, não para medir o retorno dessa janela.

## O que encontramos de aproveitável

A prioridade de estudo é a diferença entre provisão de liquidez/arbitragem e tomada de posições direcionais. As informações públicas não revelam os pesos, sinais privados ou regras completas de nenhum desses operadores. Não existe base para afirmar que usam SuperTrend, RSI ou uma IA específica.

| Caso | Evidência pública consultada | Hipótese para o IGOR | Decisão atual |
|---|---|---|---|
| Wintermute, carteira atribuída 0xecb6…2b00 | A empresa descreve negociação algorítmica, arbitragem delta neutra e presença em múltiplas venues [WIN_OFFICIAL]. | Separar receita de execução/liquidez de aposta direcional; medir inventário e hedges. | Prioridade de pesquisa; não copiar uma perna isolada. |
| BobbyBigSize, rótulo 0x7fda…17d1 | O observador reporta duração média de 4d 2h em 55 encerramentos vistos. São amostras de polling, não o ledger completo [BOBBY_EVENTS]. | Medir construção/redução parcelada, duração por campanha e risco agregado. | Prioridade de pesquisa; gatilho de entrada ainda desconhecido. |
| Abraxas atribuída, 0x5b5d…c060 e 0xb83d…6e36 | No recorte observado há encerramentos de shorts e retiradas/transferências. O rótulo da segunda carteira varia entre provedores [ABRAXAS, B83_LABEL]. | Distinguir trade direcional de hedge, funding e movimentação de capital. | Estudar separadas até comprovar vínculo; não somar automaticamente. |
| Loracle, duas atribuições | O painel da 0x8def…2dae reporta resultado acumulado de −US$35,09 milhões desde jun/2024; a 0xefe4…194b só aparece desde ago/2026 e também está negativa [LORACLE, LORACLE_SUB]. | Contraprova de fama, persistência de viés e risco de posições longas no tempo. | Controle negativo, sem aprovação para copiar. |
| AguilaTrades, atribuição | O provedor reporta −US$27,69 milhões acumulados desde jun/2025, apesar de mês recente positivo, e DD de 98,6% na janela de 30 dias [AGUILA]. | Verificar perdas extremas, fluxo de depósitos e recuperação aparente. | Controle negativo. |
| James Wynn, atribuição | O painel reporta acumulado negativo e movimentações rotuladas como possíveis liquidações em 20/11/2026 [WYNN]. | Detectar aumento de exposição perto de perda de margem. | Controle negativo; eventos precisam de confirmação bruta. |
| 0x15a4…dfdb, identidade desconhecida | A tabela diária concentra a maior realização publicada em 30/10/2026 [CONCENTRATED]. | Medir quanto do resultado depende de um único evento. | Controle de concentração; não assumir repetibilidade. |

Esses rótulos não são comprovação de identidade. Nem a melhor carteira desta amostra representa, por si só, os melhores traders do mundo. Operações em contas privadas e em outras bolsas não ficam visíveis por este método.

## Por que lucro alto não revela automaticamente uma estratégia copiável

O relatório de outubro da Perpex atribui à carteira Wintermute US$19,23 milhões de PnL após taxas e US$12,33 bilhões de volume, com 4.604.441 preenchimentos; a BobbyBigSize, US$17,93 milhões, US$2,36 bilhões e 1.422.691 preenchimentos. O ranking exclui funding. A mesma pesquisa relata que o grupo dos cem maiores ganhadores de setembro perdeu US$94,1 milhões em outubro [OCTOBER].

Minha conta sobre os valores arredondados do relatório: PnL/volume foi aproximadamente 15,60 pontos-base para a primeira carteira e 75,97 para a segunda. Isso é uma razão sobre volume negociado, não retorno sobre capital e não margem por trade independente. Fills também não são operações completas. A R17.27 não replica esse mecanismo simplesmente acionando mais ordens taker por candle.

A Wintermute confirma atuação de baixa latência e arbitragem em sua descrição institucional; isso não comprova o motivo econômico de cada fill da carteira atribuída. Para a BobbyBigSize, entradas parceladas e posições multidiárias são comportamentos a quantificar; ainda não identificamos uma regra de decisão [WIN_OFFICIAL, BOBBY_EVENTS].

O HLP é outro caso distinto: a documentação descreve receitas de market making, liquidações, Earn e parte das taxas. Não é um único sinal direcional que possa ser copiado olhando apenas buys e sells [HLP].

## Exemplos concretos, com o limite da evidência

OBSERVED_EVENTS.json registra treze exemplos reportados, dentro da janela alvo. São mudanças de posição publicadas por um observador, **não preenchimentos de ordens baixados e auditados**. Os valores em dólares são tamanho aproximado da movimentação, não lucro ou prejuízo.

| Data UTC | Carteira | Evento reportado | Preço reportado |
|---|---|---|---:|
| 12/07/2025 16:52 | Wintermute atribuída | Liquidação de short PUMP, aproximadamente US$1,1 milhão de tamanho | 0,006645 |
| 23/05/2026 20:55 | BobbyBigSize | Liquidação de long CL, aproximadamente US$1,3 milhão de tamanho | 89,127 |
| 16/11/2026 22:25 | Abraxas atribuída 0x5b5d | Encerramento de short ZEC | 907,69 |
| 17/11/2026 19:22 → 19:41 | 0xb83d | Reduções e encerramento de short WLD | 0,2623 → 0,2626 |
| 20/11/2026 03:27 → 16:07 | James Wynn atribuída | Aumento de long BTC e posterior indicação de possível liquidação | 62.094 → 59.484 |

Fontes: [WIN_EVENTS], [BOBBY_EVENTS], [ABRAXAS], [B83], [WYNN]. Os exemplos não mostram o caminho completo da posição; não provam martingale, hedge, gatilho técnico ou prejuízo igual ao notional. Sem hash e fill ID verificáveis nesta etapa, os campos correspondentes permanecem nulos.

## Como obter os dois anos, de fato

A API oficial limita userFillsByTime aos 10.000 preenchimentos mais recentes, com até 2.000 por resposta. Paginar não remove o limite do arquivo retido [HL_API].

A documentação oficial indica o exportador independente da Enigma/Hypedexer. O fornecedor anuncia exportação gratuita CSV/JSON desde jan/2024, sem conta. Isso torna possível buscar a janela solicitada sem presumir compra de assinatura. Não testei o download do portal nem sua completude nesta sessão [HL_ARCHIVE, EXPORT, PROVIDER].

A documentação de cobertura do fornecedor informa perdas de campos em parte da janela: antes de 22/03/2025, faltam direção de abertura/fechamento, posição inicial, PnL fechado e taxas; de 22/03 a 25/05/2025 faltam taxas e tid. A partir de 25/05/2025 ela informa preenchimento dos campos usuais [COVERAGE]. Ausência de taxa não equivale a taxa zero. O retorno líquido observado dos 24 meses não pode ser declarado sem resolver essas lacunas e funding.

## Protocolo de reconstrução e validação

1. Exportar separadamente cada endereço e cada mês; registrar solicitação, URL, instante de coleta, tamanho, hash e cobertura declarada. Meses sem linhas precisam de comprovação de inatividade, não simples ausência de resposta.
2. Obter também ledger de depósitos, saques, funding, liquidações e vínculos reais de subcontas. Reconstituir o estado anterior ao início do período; uma posição já aberta em 27/11/2024 não começa com inventário zero.
3. Ordenar por chave estável de evento e reconstruir inventário assinado. Agrupar fills parciais por campanha de posição, dividir inversões entre fechamento e nova abertura e tratar cada venue/dex/ativo corretamente. Não deduplicar eventos antigos apenas por tid quando esse identificador falta ou vale zero.
4. Conciliar PnL, custos, funding e movimentações de capital. Marcar campos observados, reconstruídos e estimados. Retorno de capital precisa de curva de patrimônio ajustada por fluxos; lucro em dólares dividido pelo saldo atual é inadequado.
5. Medir entrada, reforços, saídas parciais, tempo, exposição, concentração, maker/taker quando disponível, preço contra VWAP/volatilidade e regime. Identificar se o lucro some sem o melhor trade, ativo ou mês.
6. Para estudar gatilhos, construir features disponíveis antes de cada decisão e comparar ações com períodos de inatividade e oportunidades equivalentes. Não concluir uma regra apenas porque um indicador se alinhava depois da compra.
7. Classificar padrões em direcional, hedge/carry, liquidez/arbitragem ou evento concentrado. Testar as hipóteses com separação cronológica; uma réplica que se ajusta ao histórico não é o algoritmo original do trader.
8. Validar economicamente a réplica e a cópia atrasada com custos e latências compatíveis. Comparar com R17.27, comprar/manter quando aplicável e caixa. Selecionar usando somente dados anteriores ao período avaliado. Concluir com avaliação futura sem dinheiro real.

A watchlist foi escolhida depois de observar painéis atuais: ela serve para gerar hipóteses, não para uma prova imparcial de que seria possível escolher esses vencedores em 2024. Uma alegação sobre os melhores exige universo histórico com perdedores, inativos e contas encerradas; estas nove carteiras não satisfazem esse requisito.

## Encaminhamento para o IGOR

- Prioridade 1: reconstruir BobbyBigSize e as duas atribuições de Abraxas para investigar campanhas, duração e saídas; não importar qualquer regra de entrada sem medição.
- Prioridade 2: usar Wintermute para estudar execução, inventário e neutralização, reconhecendo que hedges fora da carteira e infraestrutura podem impedir uma réplica econômica.
- Controles: incluir Loracle, AguilaTrades, James Wynn e o vencedor concentrado para testar se a análise confunde risco, seleção e lucro eventual com vantagem.
- Preservar a R17.27. Nenhum candidato passou nesta etapa e nenhuma alteração de estratégia foi feita.

**Bloqueio concreto:** o ambiente de processamento está indisponível e não há conexão com o arquivo histórico. A leitura pública permitiu esta triagem; o portal foi encontrado, mas os CSVs, o ledger e o estado inicial não foram extraídos. Logo, não há backtest, rentabilidade calculada por nós ou estudo completo dos dois anos a comunicar. Nenhum job ficou rodando em segundo plano.

## Fontes consultadas

- [HL_API] https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- [HL_ARCHIVE] https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data
- [EXPORT] https://trade-export.hypedexer.com/?v=1
- [COVERAGE] https://docs.hypedexer.com/guides/historical-trade-archive
- [PROVIDER] https://app.hypedexer.com/blog/hyperliquid-wallet-trade-history
- [OCTOBER] https://perpex.co/research/hyperliquid-top-traders-october-2026
- [WIN_OFFICIAL] https://www.wintermute.com/algorithmic-trading
- [WIN] https://perpex.co/copy-trading/0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00
- [WIN_EVENTS] https://blockmetric.io/wallet/0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00
- [BOBBY] https://perpex.co/copy-trading/0x7fdafde5cfb5465924316eced2d3715494c517d1
- [BOBBY_EVENTS] https://blockmetric.io/wallet/0x7fdafde5cfb5465924316eced2d3715494c517d1
- [ABRAXAS] https://blockmetric.io/wallet/0x5b5d51203a0f9079f8aeb098a6523a13f298c060
- [B83] https://blockmetric.io/wallet/0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36
- [B83_LABEL] https://perpex.co/copy-trading/0xb83de012dba672c76a7dbbbf3e459cb59d7d6e36
- [LORACLE] https://perpex.co/copy-trading/0x8def9f50456c6c4e37fa5d3d57f108ed23992dae
- [LORACLE_SUB] https://perpex.co/copy-trading/0xefe4c06b6d310978bead596e1798a4fc1d9d194b
- [AGUILA] https://perpex.co/copy-trading/0x1f250df59a777d61cb8bd043c12970f3afe4f925
- [WYNN] https://blockmetric.io/wallet/0x5078c2fbea2b2ad61bc840bc023e35fce56bedb6
- [CONCENTRATED] https://perpex.co/copy-trading/0x15a4f009bb324a3fb9e36137136b201e3fe0dfdb
- [HLP] https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults/protocol-vaults
