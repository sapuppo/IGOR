# R17.12 — guia de execução

Este pacote é um complemento ao repositório IGOR, executado dentro de `r16_edge_lab`. Requer Python, NumPy, pandas e os arquivos originais de geração de sinais, a configuração `r17_07_candidate_config.json` e o histórico auditado `usdm_history`. O verificador de paridade também utiliza os caches e resultados históricos das etapas anteriores. O ZIP não inclui os dados de mercado volumosos.

## Atualizar os indicadores

Em um host com acesso autorizado à fonte pública, verifique primeiro:

```bash
python r17_12_binance_feed.py --probe
```

Um HTTP 451 deve ser tratado como acesso indisponível. Não use proxies ou endpoints alternativos para contorná-lo.

Escolha o início da nova fase numa fronteira UTC de 15 minutos, depois da atualização. Os números abaixo são exemplos referentes a 8/10/2026 00:00 UTC; substitua a fronteira e a época pela fase efetivamente escolhida. `1782864000000` corresponde ao fim exclusivo do histórico existente, em 1/7/2026.

```bash
python r17_12_binance_feed.py --history-root usdm_history --backfill-since 1782864000000 --through 1791446400000 --out /var/lib/igor-r17-12/backfill
python r17_12_runner.py --db /var/lib/igor-r17-12/paper.sqlite --history-root usdm_history --epoch-ms 1791446400000 --import-dir /var/lib/igor-r17-12/backfill
python r17_12_runner.py --db /var/lib/igor-r17-12/paper.sqlite --history-root usdm_history --epoch-ms 1791446400000 --check --boundary-ms 1791446400000
```

Continue somente com `ready: true`. Atualize até a fronteira atual; uma época antiga não autoriza reprodução de execuções perdidas. Backfills apenas aquecem indicadores, sem ordens e sem resultados financeiros.

## Captura prospectiva

Para observar uma captura imediatamente após uma fronteira de 15 minutos:

```bash
python r17_12_runner.py --db /var/lib/igor-r17-12/paper.sqlite --history-root usdm_history --epoch-ms 1791446400000 --capture
```

A captura precisa terminar até 120 segundos após a fronteira; as cotações precisam ter no máximo 5 segundos. CORE e REV1H esperam o intervalo seguinte para a entrada. SHORT20D usa a primeira cotação válida após o sinal de 4 horas. Stops e alvos observados nunca são preenchidos retroativamente no preço histórico: o preço de saída é o book atual, com slippage. Intervalos ambíguos são contabilizados.

Não há chave de API, saldo real ou endpoint de envio de ordens. As requisições são GET públicas. As capturas brutas ficam em `captures`, junto do banco. Preserve o banco, capturas e código da fase.

## Serviço periódico

Os arquivos `igor-r17-12-paper.service` e `.timer` são modelos, ainda não instalados. Eles pressupõem:

- Usuário `igor`; código em `/opt/igor/r16_edge_lab`; Python com dependências em `/opt/igor/.venv/bin/python`.
- Diretório `/var/lib/igor-r17-12`, gravável pelo usuário do serviço.
- `/etc/igor-r17-12.env` com `IGOR_PAPER_DB`, `IGOR_HISTORY_ROOT` e `IGOR_EPOCH_MS` definidos para a fase atual.
- Relógio sincronizado e acesso autorizado à fonte.

Exemplo do arquivo de ambiente:

```text
IGOR_PAPER_DB=/var/lib/igor-r17-12/paper.sqlite
IGOR_HISTORY_ROOT=/opt/igor/r16_edge_lab/usdm_history
IGOR_EPOCH_MS=1791446400000
```

Após configurar os caminhos, atualizar o aquecimento e conferir a época, os modelos podem ser instalados em `/etc/systemd/system/` e ativados com `systemctl daemon-reload` e `systemctl enable --now igor-r17-12-paper.timer`. O timer observa cada fronteira UTC +30 segundos. Ele não executa capturas perdidas durante uma parada.

## Falhas, manutenção e medição

Um intervalo de observação perdido coloca o estado em `halted` e bloqueia novas entradas. A rotina continua podendo processar saídas e funding quando há uma captura válida; não existe preenchimento dos preços que deixaram de ser observados. Confira posições, eventos e lacunas antes de encerrar essa fase e iniciar outra com banco e época novos. Não apague perdas ou substitua o banco para apresentar uma sequência artificial de lucro.

O diário fixa hashes de código e configuração. Mudanças exigem nova fase; não misture versões no mesmo banco. O hash detecta alterações, mas não substitui backup ou segurança do servidor. As revisões completas de estado tornam esta implementação adequada a um piloto; acompanhe espaço e tempo de leitura do banco antes de expandir a duração da operação.

Para apurar o retorno mensal, use os eventos `VALUATION` e os registros de custos/funding da fase, com saldo inicial e final marcado, incluindo posições abertas. Identifique meses parciais e lacunas; não estime os meses ausentes nem anualize uma amostra curta como se fosse um resultado observado.

Verificação local:

```bash
python -m unittest test_r17_12_hybrid_paper -v
python verify_r17_12_adapters.py
```

Documentação da fonte: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
