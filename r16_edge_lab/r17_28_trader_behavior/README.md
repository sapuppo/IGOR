# Pesquisa de traders públicos — parcial, sem ordens

A R17.27 continua preservada. Este diretório contém dados e código de investigação; nenhuma estratégia nova foi validada ou integrada.

## Entradas preservadas

- `raw/bobby_2026-10.csv.gz`: exportação do portal público de 01/10/2026 inclusive a 01/11/2026 exclusivo, carteira `0x7fdafde5cfb5465924316eced2d3715494c517d1`. O arquivo de 65MB foi preservado separadamente; referência e SHA256 estão em `RAW_RECEIPT.json`. Ele não foi duplicado no ZIP de evidência.
- O ZIP contém respostas públicas originais de funding, ledger, fills recentes, TWAPs e portfolio. Suas datas e intervalos são explícitos. Esses dados recentes não completam os dois anos e as consultas API podem retornar amostras diferentes no futuro.
- O gráfico de preço usa as mesmas entradas Binance congeladas na R17.26; hashes em `PRICE_INPUT_HASHES.json`. Não são preços de execução ou marks Hyperliquid.

## Reproduzir análises sobre os arquivos congelados

Python3.12, dependências em requirements.txt. Coloque o CSV preservado em raw/ e extraia as respostas JSON do ZIP na mesma pasta.

```
python -m unittest test_inventory -v
python profile_raw.py
python analyze_export.py
python diagnose_order.py
python behavior.py
python relative_flow.py
python portfolio_history.py
python check_pnl_semantics.py
python verify_research.py
python report_research.py
```

`fetch_public.py` e `collect_recent.py` repetem consultas somente de leitura à API pública, mas NÃO recuperam necessariamente os snapshots arquivados. Nenhuma função envia ordens, abre conta ou usa chaves privadas.

A API de portfolio foi consultada com `{"type":"portfolio","user":"ENDERECO"}` para as duas carteiras. As séries allTime são esparsas: não interpolamos retornos ou drawdowns que elas não permitem observar.

## Reconstrução e decisão

`inventory.py` mantém a posição inicial desconhecida e exige que restrições de direção identifiquem um valor único antes de construir campanhas completas. O CSV não passou nessa exigência: não se assumiu saldo zero nem se inventou ordem intrassegundo. Testes unitários aprovados não equivalem a uma auditoria de rentabilidade aprovada.

`DAILY_MAJOR_FLOW.csv` é fluxo líquido executado. Não é posição absoluta da carteira. `CAMPAIGNS.csv.gz` e `MAJOR_INVENTORY.csv.gz` têm cabeçalho e zero linhas porque a reconstrução não foi aprovada. Custos ausentes não viram zero e PnL realizado não vira retorno mensal sobre capital.

O portal informou um teto de 6,25milhões de registros por arquivo e uma exportação por IP a cada24h. Não se contornou esse limite nem se contratou serviço. Os dois anos continuam incompletos e nenhum processo fica executando após a entrega.
