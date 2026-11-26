# Pesquisa de bots públicos e dos dois posts — 26/11/2026

## Conclusão

Foram verificados oito repositórios públicos com revisões fixadas. Encontramos motores, bibliotecas e fluxos de trabalho reaproveitáveis. Não encontramos nos materiais consultados o modelo treinado exato, dataset, parâmetros completos e extrato auditável que reproduzam os saldos alegados nos dois posts. Isso não permite afirmar que todo vídeo seja falso; impede tratá-lo como resultado reproduzido.
## Os dois posts

- [Primeiro post](https://x.com/x_insider4/status/2125878284705525818): descreve ensemble de árvores, Kalman e ranking por capital/tempo em futuros Hyperliquid. A descrição foi usada como hipótese, não como benchmark financeiro comprovado. O texto/artigo consultado não disponibilizou pesos nem código completo do sistema anunciado.
- [Segundo post](https://x.com/ai__brain/status/2125691371004772799): descreve agentes para memecoins, contratos, liquidez, carteiras e saída. Seu [artigo vinculado](https://x.com/i/article/2117326558910185472) declara que os tickers dos vídeos são inventados e as operações/simulações são exemplos. Por isso, o saldo exibido não foi usado como comprovação de lucro real.
Os vídeos não foram reproduzidos visualmente neste trabalho; foram analisados os textos e artigos recuperados. Não instalamos templates dos autores nem demos acesso a carteiras.

## Repositórios verificados

| Projeto | O que o código/documentação fornece | Aplicação no IGOR nesta etapa | Limite |
|---|---|---|---|
| [galleonlabs/hypergrok-trading-desk](https://github.com/galleonlabs/hypergrok-trading-desk) | Processo de mesa, ferramentas públicas, stop com custos e validação de tickets. README informa ausência de estratégia/sinal próprio. | Quatro primitivas puras de stop/tamanho copiadas sob MIT e executadas no replay. | Não entrega o alpha ou pesos do vídeo. |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | FreqAI oferece classificadores e regressões LightGBM/XGBoost, treino e inferência integrados ao bot. | LGBMClassifier4.6.0, a família usada no wrapper público, treinado e testado no IGOR; nenhum fonte GPL copiado. | Framework precisa de dados, labels e validação; exemplo não é carteira lucrativa pronta. |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | README define projeto educacional; interface atual de paper/backtest. Nova árvore de core se declara em desenvolvimento. | Estrutura e módulos de exposição foram revisados, sem conectar execução. | Não é bot de scalp cripto treinado; requer dados e modelos próprios. |
| [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | Ferramentas de pesquisa, análise de risco e backtest; possui módulos de risco explícitos. | Módulo risk.py MIT copiado e usado para verificar DD independentemente. | Infraestrutura não prova retornos dos posts. |
| [bmoscon/cryptofeed](https://github.com/bmoscon/cryptofeed) | Normalização de feeds de trades/livro/funding de múltiplas exchanges. | Avaliado como opção futura de feed; sem código copiado. | Head consultado requerPython3.13+, ambiente3.12; licença AGPL deve ser considerada em integração. |
| [chainstacklabs/pumpfun-bonkfun-bot](https://github.com/chainstacklabs/pumpfun-bonkfun-bot) | Bot de lançamento/sniping em Solana com RPC próprio e regras configuradas. README o posiciona como educacional. | Arquitetura revisada; filtro determinístico do artigo implementado separadamente, sem copiar executor on-chain. | Venue e riscos diferentes de Binance; exige RPC, liquidez e saídas on-chain, não validação com candles de futuros. |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | Framework de reinforcement learning e referências a evolução FinRL-X. | Analisado, não instalado nesta rodada. | Não apareceu um checkpoint pronto e validado para nosso mercado; treino RL não substitui avaliação. |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | Sistema de pesquisa financeira com agentes, ferramentas e fontes; README consultado diz que não coloca trades. | Analisado, sem execução importada. | Pesquisa/relatórios não equivalem a uma estratégia de execução de oito minutos. |

## Revisões fixadas e licença

| Repositório | Commit consultado | Licença informada |
|---|---|---|
| galleonlabs/hypergrok-trading-desk | `98331af5c407f1929a8aa3869d932eb7680760fb` | MIT |
| freqtrade/freqtrade | `38113b83547857a6cc7f9709511fa90a624cc5bc` | GPL-3.0 |
| virattt/ai-hedge-fund | `5c553b5222044f6a5527bd377b4104c50ee0ad28` | MIT |
| HKUDS/Vibe-Trading | `0ec47cd0c92b4bcc1673283621620072a367a698` | MIT |
| bmoscon/cryptofeed | `cb27c73f0e42542e892f46c35de57cc5d8fede97` | NOASSERTION |
| chainstacklabs/pumpfun-bonkfun-bot | `a047c282bca13a5123f484965ac34c9a609430f1` | Apache-2.0 |
| AI4Finance-Foundation/FinRL | `5df023ed3faab4cb529bc7e2837a7fb331067cf2` | MIT |
| TauricResearch/TradingAgents | `121265d18d467ac717f7af99cb0d669c15d2e73c` | Apache-2.0 |

Cryptofeed: metadado GitHub retornou NOASSERTION, mas o LICENSE e README consultados identificam GNU AGPL. LightGBM4.6.0 foi instalado do pacote público; sklearn1.8.0 é a implementação HGB do experimento. Não há promessa de retorno em bibliotecas de ML.
## Reuso em código e evidência

- `third_party/hypergrok_stop.py`: extrai exatamente `price_stop`, `lot`, `round_down` e `UnpriceableStop` da revisão HyperGrok registrada; dependências de CLI/rede ficaram fora. Os ASTs das quatro primitivas foram comparados com o fonte e passaram. Licença MIT mantida.
- `third_party/vibe_risk.py`: módulo de risco copiado da revisão Vibe-Trading registrada. `max_drawdown_analysis` foi executado para conferir as 140 curvas. Licença MIT mantida.
- `run_lightgbm.py`: instancia o estimador publicado e testa com os mesmos dados, custos e divisões do HGB. Não é cópia do runtime inteiro do Freqtrade e não contém código GPL dele.
- `onchain_filter.py`: implementação independente de regras divulgadas no artigo, com testes de aprovação/rejeição e falta de dado. Sem integração com RPC; não foi chamado de estratégia lucrativa.
## Resultado da aplicação

Os dois modelos de árvore foram de fato treinados. Com estes custos e estes dados, todas as seis políticas de cada backend ficaram em caixa. O reuso reduziu trabalho de infraestrutura; não forneceu uma vantagem financeira pronta. Os resultados estão em `RESULTADO_PT.md` e nos artefatos. Nenhuma estratégia foi promovida.
## Limites da pesquisa

Não foi lido todo arquivo de todo projeto, nem milhares de repositórios. Houve revisão direcionada de READMEs, versões, licenças e módulos relevantes, com execução dos componentes escolhidos. Não avaliamos performance financeira de frameworks que não foram integrados. A ausência de um modelo exato nos materiais consultados não prova que ele não possa existir em outro lugar. Não confundimos quantidade de estrelas, quantidade de agentes ou qualidade visual de um painel com rentabilidade auditada.
