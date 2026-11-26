# R17.26 — Probabilidades, livro real e ranking por capital/tempo

**Implementação e testes concluídos em 26/11/2026. Nenhum modelo aprovado. A meta de 5–10% ao mês não foi atingida.** Os dois backends recusaram todas as operações: a expectativa estimada não superou os custos definidos no protocolo. Isso é ausência de uma estratégia rentável demonstrada, não sucesso de rentabilidade nem prova de que esses métodos nunca funcionem.
Código em `research-r17-26-probability-turnover`, criado a partir de `7268aadabc68ca76b9231a6f95d5085fdad9bfb3`. Alterações restritas a `r16_edge_lab/r17_26_probability/`. Nenhuma branch anterior foi movida, nenhum executor real foi ativado, nenhuma ordem foi enviada. O desenvolvimento paralelo foi preservado.
## O que foi implementado de verdade

- Dois ensembles existentes: `HistGradientBoostingClassifier` do scikit-learn 1.8.0 e `LGBMClassifier` do LightGBM 4.6.0, a família de estimador usada no wrapper público do FreqAI. São bibliotecas publicadas, treinadas aqui com nossos dados; não são pesos secretos obtidos dos vídeos.
- 132 árvores por classificador, profundidade máxima 3, sete folhas, mínimo de 200 amostras por folha, regularização L2 e sementes fixas. Quatro classificadores por bundle: horizonte 8/20 minutos × com/sem livro. Dez bundles (cinco meses × dois backends), total de 40 classificadores e seus calibradores logísticos.
- Probabilidades calibradas em mês separado do ajuste das árvores; Kalman causal em log-odds; previsão separada para long e short; estimativa de payoff e duração por classe usando somente o mês de calibração.
- Ranking por retorno esperado líquido dividido pelo capital empregado e pelo tempo esperado. Sem alavancagem, por dólar de notional e por minuto. A política só aceita expectativa positiva. A estimativa de payoff usa médias condicionais por classe; não é um modelo perfeito de distribuição de preços nem de magnitude condicional a todos os atributos.
- Ablations: ranking por probabilidade (ainda com filtro de expectativa), por EV sem tempo, por EV/tempo, com Kalman, sem livro e com margem extra de cinco pontos-base. As seis variantes foram fixadas antes de olhar os resultados.
- Gerenciamento por volatilidade, ATR, limites de exposição, proteção de drawdown e perdas consecutivas, custos e restrições de execução. Primitivas de dimensionamento de stop do HyperGrok foram reaproveitadas sem alteração funcional sob MIT; verificação independente de drawdown usa código MIT do Vibe-Trading.
- Contrato de inferência somente leitura (`paper_adapter.py`) e teste executado com pesos salvos e snapshot histórico (`PAPER_SMOKE_RESULT.json`), com zero ordens. Não há processo contínuo de paper trading nem execução em background.
- Filtro experimental de tokens (`onchain_filter.py`) traduz as regras declaradas no artigo do segundo vídeo em verificações determinísticas: liquidez, concentração, permissões, vendedores e idade; dado ausente reprova. Apenas testes de contrato foram feitos. Ele não consulta blockchain, grupos privados, carteiras ou Telegram, e não prova proteção contra rugs.

## Dados reais utilizados

BTCUSDT, ETHUSDT e SOLUSDT; candles USD-M de um minuto de 01/12/2025 a 24/11/2026, inclusive. Foram 1.550.880 candles nos três ativos. Profundidade publicada de 01/04/2026 a 24/11/2026: 1.994.457 snapshots utilizados.
De 840 arquivos planejados, 837 foram baixados e conferidos contra SHA256 oficial; três arquivos de bookDepth de 08/10/2026 retornaram 404, um por moeda. Não foram inventados ou substituídos por volume. Cada URL e hash está em `manifest.json`.
Features do livro usam notional comprador/vendedor nos intervalos de ±0,2% e ±1%. Informação disponível = timestamp do snapshot + 1 segundo; apenas snapshots estritamente anteriores à decisão e com até 120 segundos de idade. Cobertura dos pares de dados nesta série: aproximadamente 98,72% por moeda. A ausência bloqueia variantes com livro; a ablation sem livro pode continuar.
Este arquivo de profundidade contém agregados por faixa, não uma reconstrução completa de L2, da fila ou do bid/ask. Não inferimos micropreço, spread histórico exato, OI ou compras de whales a partir desses dados.
Funding mensal de abril a outubro foi verificado no arquivo público; novembro foi coletado pelo conector público Binance, 72 eventos por moeda até 24/11 às 16:00 UTC. Dados e respostas usados ficam no pacote e têm hashes. Preço negociado é proxy de mark price no replay; não há reconstrução perfeita do mark no instante de todos os eventos.
## Treino, calibração e avaliação temporal

Quatro avaliações mensais de julho a outubro de 2026. Para cada mês, duas mensalidades anteriores para ajuste e a última mensalidade anterior para calibração. Exemplo de julho: ajuste abril/maio, calibração junho, avaliação julho. Sem divisão aleatória por linhas; moedas e lados respeitam as mesmas fronteiras.
Expurgo de 21 minutos em cada fronteira, superior à janela máxima de label e à latência. Amostragem de treino/calibração a cada oito minutos por timestamp absoluto; avaliação a cada minuto. Labels usam entrada um minuto após a decisão e saída por stop, alvo 2R ou limite de 8/20 minutos. Se stop e alvo aparecem na mesma vela, considera-se o stop primeiro.
A família escolhida para novembro foi congelada após julho–outubro e antes da inferência de novembro. Em ambos os backends, a escolha foi **CAIXA**. Todas as variantes continuam apresentadas como diagnóstico. O histórico anterior já foi parcialmente consultado por outras pesquisas R17: walk-forward temporal não equivale a histórico inteiramente virgem.
A extensão LightGBM foi registrada após o pedido adicional do usuário por modelos públicos prontos; só o backend mudou, com profundidade e regularização fixas. Seus resultados ficam separados dos HGB. Não se escolhe retrospectivamente o melhor backend de novembro como se fosse uma seleção independente.
O protocolo está em `protocol.json`; a extensão em `lightgbm_extension.json`; cortes exatos, amostras e hashes de cada bundle em `models*/YYYY-MM.json`.

## Custos e execução

Taxa taker 0,06% por lado; meio spread 0,02% e slippage adverso 0,04% por lado. O custo aproximado de ida e volta é **0,24% do notional** no cenário normal e **0,48%** no estresse. São hipóteses conservadoras fixadas, não observação do spread histórico ou da taxa pessoal do usuário. Não se reproduzem as taxas nem a execução do Hyperliquid mostrado no post.
Entradas na abertura posterior a uma latência completa de um minuto; quantidade respeita tick, lote, mínimo e máximo atuais da Binance consultados em 26/11. O dimensionamento é reduzido novamente depois do preço arredondado; participação limitada a 0,1% do volume financeiro do minuto anterior. Regras atuais são cenário de execução, não arquivo de mudanças históricas dos filtros.
Capital simulado USDT 10.000, sem alavancagem, até três posições, peso máximo 20% por ativo, exposição bruta até 60%, orçamento de risco 0,25% por entrada. Stop entre 0,2% e 0,8% conforme ATR; orçamento reduzido pela metade em DD de 8%, bloqueio após DD de 20%, pausa de uma hora após três perdas e proteção diária de 4%. Gaps podem ultrapassar a perda planejada.
Funding das posições antigas é agregado à fronteira de minuto; para entradas com sequência intrabar incerta não há crédito favorável inventado. O lucro de uma saída intrabar não pode financiar outra entrada no começo da mesma vela. Todas as curvas incluem custos de liquidação final.
## Resultados principais — julho a outubro/2026

Os seis seletores probabilísticos tiveram 0% e zero operações nos dois backends, com custos normais e dobrados. PF sem perdas/operações é indefinido; Sharpe zero por convenção de série constante não demonstra segurança ou qualidade.
| Política | Retorno total líquido | Equivalente mensal | DD 1m | Sharpe diário anualizado | PF líquido | Operações |
|---|---:|---:|---:|---:|---:|---:|
| HGB / turnover_kalman | +0.000% | +0.000% | 0.00% | 0.000 | indefinido | 0 |
| HGB / price_only_turnover_kalman | +0.000% | +0.000% | 0.00% | 0.000 | indefinido | 0 |
| LightGBM / turnover_kalman | +0.000% | +0.000% | 0.00% | 0.000 | indefinido | 0 |
| LightGBM / price_only_turnover_kalman | +0.000% | +0.000% | 0.00% | 0.000 | indefinido | 0 |
| Controle anterior / normal | +0.194% | +0.048% | 3.43% | 0.141 | 1.044 | 28 |
| Controle anterior / custos2x | -0.563% | -0.140% | 3.46% | -0.349 | 0.878 | 28 |

O controle reaplica as regras econômicas de volume impulse da R17.24/R17.25 no mesmo universo e motor de um minuto, com stop ATR 2–12%, alvo 15% e até sete dias. É um adaptador de comparação, não equivalência bit a bit com toda a baseline de produção R16.24.2. Não foi provada paridade de todas as diferenças de inicialização de ATR entre motores.
## Novembro — 01/11 a 24/11/2026

| Política | Retorno total líquido | Equivalente mensal | DD 1m | Sharpe diário anualizado | PF líquido | Operações |
|---|---:|---:|---:|---:|---:|---:|
| HGB / seletor probabilístico (caixa) | +0.000% | +0.000% | 0.00% | 0.000 | indefinido | 0 |
| LightGBM / seletor probabilístico (caixa) | +0.000% | +0.000% | 0.00% | 0.000 | indefinido | 0 |
| Controle anterior / normal | +1.962% | +2.494% | 1.14% | 5.384 | 3.591 | 8 |
| Controle anterior / custos2x | +1.772% | +2.253% | 1.07% | 5.153 | 3.410 | 8 |

**O +1,962% do controle é acumulado em 24 dias, com apenas oito operações.** O equivalente mensal de aproximadamente +2,494% é uma normalização matemática da duração, não retorno mensal observado completo nem promessa. Não existe resultado anual de 2026 nesta etapa.
## Retorno mensal observado — controle e modelos

| Período | Controle normal | Controle custos2x | Modelos probabilísticos |
|---|---:|---:|---:|
| 2026-07 | -0.471% | -0.723% | 0% / sem operações |
| 2026-08 | +3.187% | +2.768% | 0% / sem operações |
| 2026-09 | -1.302% | -1.350% | 0% / sem operações |
| 2026-10 | -1.153% | -1.203% | 0% / sem operações |
| 2026-11 (até dia24) | +1.962% | +1.772% | 0% / sem operações |

## Por que a hipótese falhou

As probabilidades calibradas ficaram próximas das frequências históricas. Há pequenas melhorias de Brier em algumas janelas, mas isso não equivale a margem de lucro após custos. O ranking não apresentou oportunidades com EV líquido positivo.

| Backend / mês | Máxima probabilidade após Kalman | Melhor EV líquido previsto | Entradas elegíveis |
|---|---:|---:|---:|
| hist_gradient_boosting / 2026-07 | 52.18% | -0.192% | 0 |
| hist_gradient_boosting / 2026-08 | 56.78% | -0.151% | 0 |
| hist_gradient_boosting / 2026-09 | 55.41% | -0.170% | 0 |
| hist_gradient_boosting / 2026-10 | 55.96% | -0.103% | 0 |
| hist_gradient_boosting / 2026-11 | 58.60% | -0.150% | 0 |
| lightgbm / 2026-07 | 53.98% | -0.190% | 0 |
| lightgbm / 2026-08 | 55.46% | -0.144% | 0 |
| lightgbm / 2026-09 | 56.07% | -0.159% | 0 |
| lightgbm / 2026-10 | 55.46% | -0.110% | 0 |
| lightgbm / 2026-11 | 57.58% | -0.143% | 0 |

No exemplo de julho, o retorno positivo médio do label de oito minutos foi aproximadamente 0,65R e a perda não positiva média aproximadamente −0,59R. Mesmo uma previsão um pouco acima de 50% não compensa um custo de 0,24% com stops frequentemente próximos de 0,2%. O número de árvores e a velocidade de reciclagem do capital não corrigem essa desigualdade.
As diferenças entre EV, EV/tempo e Kalman não chegaram a ser economicamente discriminadas: todas as políticas foram bloqueadas pelo filtro de custos. O ranking foi testado em fixtures com operações, mas os dados reais desta matriz não permitiram demonstrar sua vantagem de alocação.
Isso não demonstra que todo scalping seja inviável. Demonstra que estes atributos, estimadores, calibração, payoff médio e cenários de custo não apresentaram uma estratégia executável lucrativa nesta amostra. Não afrouxamos o custo ou desligamos o filtro para fabricar atividade.
## Pesquisa dos vídeos e reuso

Foi produzido `PESQUISA_MODELOS_PT.md`, com oito repositórios e revisões fixadas. Os posts e artigos foram recuperados por texto/metadados; os vídeos não foram visualmente reproduzidos nesta auditoria. Não declaramos ter auditado uma carteira ou o saldo dos vídeos.
O artigo vinculado ao segundo post declara que os tickers são inventados e que operações/simulações nos vídeos são exemplos. O primeiro post descreve árvores, Kalman e ranking, mas os materiais consultados não forneceram os pesos, dados de treino e implementação exata desse sistema que permitiriam reproduzir o lucro alegado.
**Reuso efetivo:** código MIT de `price_stop`, `lot`, `round_down` e `UnpriceableStop` do HyperGrok é chamado no replay; módulo MIT de risco do Vibe-Trading confere drawdowns; scikit-learn e LightGBM são as implementações existentes dos modelos. Licenças e hashes em `THIRD_PARTY.json` e `third_party/`. Nenhum código GPL do Freqtrade foi copiado para o IGOR.
## Verificação e limitações

17 testes aprovados, incluindo causalidade, snapshot futuro/desatualizado, vazamento por prefixo, aritmética dos labels, Kalman, ranking sensível a custo e duração, tamanho após arredondamento, stop-first, funding e reconciliação ponta a ponta. O erro de tipo de duração int16 detectado no primeiro início de treino foi corrigido para int64 antes de qualquer resultado de performance desse treino; teste de regressão incluído.
140 execuções da matriz (dois backends × cinco meses × sete políticas × dois custos), sendo 120 simulações probabilísticas sem operações e 20 execuções do mesmo controle repetidas nos dois backends. São 130 cenários distintos se os dez controles duplicados forem contados uma única vez. Dez bundles verificam os cortes temporais de 40 classificadores; três prefixos de dados reais; todas as operações e curvas conciliadas, com DD conferido por biblioteca externa.
Um embaralhamento de labels com semente fixa por backend foi executado como teste de sanidade. Não é um teste de permutação completo de toda a busca nem um p-valor de significância. Bootstrap em blocos de sete dias (500 caminhos) foi calculado para o controle; como a seleção foi caixa, não há alpha escolhido a validar. Nenhuma robustez estatística de lucro dos modelos é alegada.
Universo pequeno e fixo, ausência de fila/ticks sequenciais, taxas hipotéticas, proxy de mark price, erro de estimação de payoff/duração, dependência entre amostras sobrepostas, treinamento recente, apenas quatro meses de seleção e 24 dias finais limitam conclusões. Curvas encadeadas normalizam cada janela a10mil e escalam os resultados; não são replay contínuo com lotes redimensionados sobre patrimônio composto.
## O que incorporar ao IGOR

Nenhum novo sinal merece promoção ao principal nesta etapa. Os componentes estão implementados na branch de pesquisa: contrato de features com informação temporal explícita, inferência calibrada, ranking, filtros de custos, dimensionamento reaproveitado e rastros de decisão. São infraestrutura verificável; ainda não uma fonte comprovada de lucro.
Para testar outra hipótese, o diagnóstico aponta para magnitude/duração condicional e custos reais do venue, com avaliação independente. O filtro de memecoins exige dados on-chain e simulação de saída/liquidez próprios; um scanner de Solana não pode ser validado com candles de BTC/ETH/SOL nem conectado cegamente à execução de futuros.

## Reprodução e arquivos

```sh
cd r16_edge_lab/r17_26_probability
python -m pip install -r requirements.txt
python collect.py
python prepare.py
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 python -m unittest test_research -v
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 python run.py
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 python run_lightgbm.py
python verify.py
python diagnose.py
python paper_smoke.py
python report.py
```
Os JSONs públicos de funding de novembro e filtros atuais usados estão incluídos; substituí-los por consultas novas altera o experimento e deve ser registrado. `raw/` e `prepared/` não são duplicados no pacote: manifestos com URLs, SHA256 e scripts permitem reconstrução. Pacote inclui todos os dez bundles de pesos e metadados, resultados, curvas diárias, marcas de minuto e testes. Matrizes densas de previsões podem ser regeneradas pelos scripts. Pickles são artefatos locais verificados por hash; não carregar pickles de origem desconhecida.
`STATUS.json`, `VERIFICATION.json`, `FORECAST_DIAGNOSTICS.json`, `PAPER_SMOKE_RESULT.json`, `THIRD_PARTY.json`, `SHA256.json` e os CSVs nos diretórios de resultados documentam a entrega. Não há teste desta etapa rodando nem tarefa automática de paper ativada.
