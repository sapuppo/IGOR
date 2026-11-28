# IGOR R17.31 — pesquisador e avaliação de risco

Implementação da primeira camada da referência enviada: coleta pública → contexto estruturado → teses com evidências → avaliação determinística de admissão → relatório e revisão. **Ainda não é o agente autônomo completo da imagem.**

## Entrega executada

- Dois ciclos reais de coleta pública, com BTC, ETH, SOL, BNB, XRP e DOGE. O segundo consultou 36 fontes/endpoints e não registrou falhas. Dados integrais, hashes e horários estão no pacote de evidências.
- Uma revisão das seis teses feita neste chat, importada com hash do snapshot e horário próprio de conhecimento. Não foi uma chamada a um modelo externo. A revisão tardia não recebe retroativamente o horário da coleta.
- 36 testes offline aprovados no módulo novo; 16 testes anteriores da R17.30 continuam aprovados. Os testes do transporte do modelo usam resposta simulada, não uma chamada paga real.
- Todas as propostas permaneceram HOLD. Não houve ordens, fills, carteira simulada negociada ou rentabilidade medida. O componente de paper é uma **avaliação de admissão e orçamento hipotético**, não um simulador de negociação pronto.

## Dados e decisões

| Componente | Implementado | Limite |
|---|---|---|
| Mercado | Candles 1h/4h fechados, ATR, tendência, retorno 24h, volatilidade, book REST, funding e open interest | Snapshot de 20 níveis não revela fila; open interest é estoque atual, não fluxo/delta |
| Contexto | Dominância BTC, oferta de stablecoins USD e variação em 7d | Oferta é proxy de liquidez sistêmica; rotação narrativa não apurada |
| Fundamentos | Oferta circulante/total/máxima, market cap/FDV, TVL por rede quando disponível | TVL da rede não é receita do token; desbloqueios, receita, taxas, usuários, concentração e captura de valor ainda desconhecidos |
| Notícias | Manchetes recentes dos feeds oficiais Ethereum e Federal Reserve | Não são cobertura universal de notícias nem catalisadores verificados por token |
| Cérebro | Baseline determinística, importação de revisão deste chat e adaptador JSON para um modelo configurável | API externa sem endpoint/modelo/chave nesta sessão; transporte real não testado |
| Risco | Limites R17.29, orçamento hipotético incluindo custos e funding adverso estimado, kill switch e rejeição de dados inválidos | Não há adaptador de execução; nenhum candidato pode se declarar autorizado ou calibrado |
| Revisão | Brier descritivo somente com labels maduras e referência de proveniência | Formato de hash não verifica sozinho a verdade de um label; nenhum label real foi medido aqui |
| Loop | Execução pontual ou processo em primeiro plano, journal, lock e deduplicação por snapshot | Não foi instalado nem deixado um serviço 24h ligado |

O ranking inicial ordena força técnica absoluta de 4h; não é retorno esperado, probabilidade nem identificação comprovada de assimetria. Nenhum limiar foi otimizado para os resultados desta coleta. Dados atuais não são projetados sobre o passado.

## Uso

Python 3.10+ com biblioteca padrão, sem instalar dependências. Na raiz do repositório:

```bash
python r16_edge_lab/r17_31_research_agent/run.py --brain rules
python r16_edge_lab/r17_31_research_agent/run.py --brain auto --cycles 0 --interval 900
python -m unittest discover -s r16_edge_lab/r17_31_research_agent -p 'test_*.py' -v
```

No Windows, `INICIAR_PESQUISA.bat` inicia o segundo comando; exige Python disponível. O BAT foi revisado, mas não executado num Windows nesta sessão. Ctrl+C encerra o processo. Um arquivo `KILL_SWITCH` na pasta ativa a trava na avaliação de risco. O loop permanece somente enquanto o processo e o computador estiverem ativos.

Cada ciclo salva `snapshot.json`, `research.json`, `RESULTADO_PT.md` e `MANIFEST.json`. O journal guarda hashes e identifica replays; o diretório raiz recebe `latest.json`. Um lock antigo após falha abrupta exige verificar o processo antes de remover o arquivo. Use diretórios de saída diferentes para comparar cérebros no mesmo snapshot: a deduplicação é por snapshot, não por configuração de modelo. Requisições têm limite de tamanho/tempo; falhas não são preenchidas com dados inventados.

## IA configurável

As variáveis opcionais são `IGOR_LLM_ENDPOINT` (URL completa de Chat Completions), `IGOR_LLM_MODEL` e `IGOR_LLM_API_KEY`. Não gravar chaves no código ou no Git. Nenhum provedor/modelo pago é escolhido por padrão. Um servidor local compatível pode usar HTTP em loopback; um provedor remoto exige HTTPS e não pode redirecionar a chamada autenticada.

`--brain auto` usa o modelo apenas se endpoint e modelo estiverem configurados; caso contrário usa regras e registra `deterministic_baseline`. `--brain llm` tenta o adaptador; falhas são registradas por tipo, mantêm HOLD e ficam visíveis no relatório. A chamada envia somente o resumo público da pesquisa, sem estado de conta ou credenciais de corretora. O provider/modelo deve suportar JSON e `max_completion_tokens`; compatibilidade real depende da configuração.

O modelo só pode retornar símbolo, direção, qualidade, opinião de confiança, tese, risco, invalidação, referências e catalisadores. Campos de risco ou referências inventadas são rejeitados. Confiança é sempre tratada como **não calibrada** e uma citação existente não comprova a veracidade de sua interpretação. Não há ferramentas executáveis nem acesso a conta no prompt.

Para reproduzir a revisão deste chat após extrair as evidências:

```bash
python r16_edge_lab/r17_31_research_agent/run.py --brain rules --brain-file r16_edge_lab/r17_31_research_agent/evidence/session_review.json --snapshot r16_edge_lab/r17_31_research_agent/evidence/live_run/1795829590592_8eff401019dd/snapshot.json --output r16_edge_lab/r17_31_research_agent/replay_session
```

O documento de revisão deve corresponder ao hash exato da análise determinística e informar `reviewed_ms`. Não há retroação de decisões ou promoção com esse import.

## O que falta para cumprir a imagem inteira

1. Cobrir as lacunas fundamentais com provedores e fontes verificadas e ampliar a pesquisa de catalisadores por ativo.
2. Configurar e testar um backend de IA para ciclos contínuos. A revisão deste chat não cria um serviço de inferência permanente.
3. Aprender/calibrar probabilidades com labels independentes e verificar expectativa líquida fora da amostra. Confiança declarada por IA e Kelly não substituem essa etapa.
4. Construir/testar os adaptadores de execução simulada, reconciliação e, para maker, fila e latência com a base da R17.30. Somente depois cabem gates para paper prospectivo e eventual produção.

Nenhuma promessa de 81 ms, AgentKit/Jev, autoalteração de código ou rentabilidade foi implementada em nome da imagem. A mudança foi isolada da baseline operacional.

## Fontes de implementação

- [Binance — market data USD-M](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
- [CoinGecko — schema oficial de mercados](https://github.com/coingecko/coingecko-typescript/blob/main/src/resources/coins/markets.ts)
- [DefiLlama — API pública](https://github.com/DefiLlama/api-docs/blob/main/llms-free.txt)
- [OpenAI — contrato Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Feed Ethereum](https://blog.ethereum.org/feed.xml) e [feed Federal Reserve](https://www.federalreserve.gov/feeds/press_all.xml)
