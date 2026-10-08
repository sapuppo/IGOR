# R17.12 — integração de execução em paper trade

Data: 8 de outubro de 2026. Baseline principal preservada: R16.24.2 — Portfolio Integration.

A R17.12 implementa a execução simulada da carteira híbrida da R17.11. O código está preparado e verificado; a operação contínua ainda não começou. Não há resultado mensal novo desta versão.

## O que foi desenvolvido

- Carteiras independentes: 80% do capital simulado para CORE/REV1H e 20% para SHORT20D. Capital inicial configurado: US$ 10.000.
- Limites separados de exposição, posições e risco de stop. Não há transferência automática de capital entre as carteiras.
- Entradas e saídas ao bid/ask observado, com taxa de 0,06% e slippage adverso de 0,04% por execução. Marcação das posições pelo mark price oficial; funding registrado com taxa e mark price do evento.
- Velas fechadas e sinais calculados pelos geradores congelados. Importação histórica alimenta indicadores; não cria operações retroativas ou lucros.
- Diário SQLite transacional com hashes, identidade de código/configuração, retomada idempotente e rejeição de alterações ou duplicação de funding.
- Falhas de observação bloqueiam novas entradas. Dados incompletos, desatualizados ou fora de ordem não autorizam preenchimentos simulados.
- Coletor de dados públicos e modelos de serviço/timer para captura a cada 15 minutos.

## Verificação

Os 19 testes automatizados passaram. Incluem segregação de carteiras, posições opostas na mesma moeda, custos, funding, limites de risco, preços atuais, interrupções, retomada e integridade do diário.

A comparação de sinais também passou nos pontos históricos verificados: um sinal CORE/REV1H e um sinal SHORT20D coincidiram com os geradores originais. Isso verifica a integração nesses casos; não equivale a validar toda a distribuição de resultados ou a rentabilidade da nova execução.

## Bloqueios observados

1. O histórico auditado disponível termina em 1º de julho de 2026, exclusive. Na checagem de 8 de outubro, as 114 séries necessárias (38 moedas × 3 intervalos) precisavam de atualização.
2. A chamada ao endpoint público de horário da Binance retornou HTTP 451 neste ambiente. O coletor não contorna essa restrição.
3. Não foi provisionado nem ativado um servidor de captura contínua.

Não há operação real, serviço contínuo ativo ou lucro novo contabilizado. O pacote contém os comandos para atualizar dados e iniciar a coleta em um ambiente com acesso autorizado.

## Resultado financeiro que de fato temos

O histórico da R17.11 80/20, de janeiro de 2023 a junho de 2026, apresentou aproximadamente 1,38% de retorno mensal composto, 15,13% de drawdown sobre a série diária e 3,11% acumulados no primeiro semestre de 2026. Nenhum dos 42 meses chegou a 20%. Esses números são históricos e não são desempenho da R17.12.

A R17.12 usa preenchimentos ao preço observado, monitoramento de 15 minutos e histórico shadow iniciado vazio. Por isso é uma nova variante de execução, que precisa de observação prospectiva própria. A etapa concluída permite medir o comportamento operacional; não demonstrou vantagem adicional nem aproximação comprovada à meta de 20% ao mês.

Próximo marco concreto: resolver o acesso à fonte, atualizar o aquecimento dos indicadores e iniciar uma fase de paper trade com código congelado. Registrar custos, funding, perdas, lacunas de captura e retorno por mês antes de decidir qualquer alteração de estratégia ou uso de capital real.

Arquivos de evidência: `R17_12_TESTS.txt`, `R17_12_ADAPTER_PARITY.json`, `R17_12_PREFLIGHT.json` e `R17_12_OPERATIONAL_STATUS.json`.
