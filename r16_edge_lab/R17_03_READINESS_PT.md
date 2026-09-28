# R17.03 — auditoria de prontidão em 28/09/2026

Baseline de referência do robô principal: **R16.24.2 – Portfolio Integration**. A tentativa R17.00 foi descartada (STRESS −34,28% e queda máxima 35,65%). Nesta fase não houve ordens reais, paper trades encerrados nem cálculo válido de retorno mensal.

## Entrega verificada

- Coorte predefinida [R17_03_OKX_UNIVERSE.json](https://github.com/sapuppo/IGOR/blob/r17-03-okx-cohort/r16_edge_lab/R17_03_OKX_UNIVERSE.json): 35 swaps lineares USDT correspondentes à lista Binance congelada. SHA-256 do manifesto `6cbd8423bd4a5bb860aa9cd497720c28960540008efe237e8a9c95fc9daea5b9`. Sem correspondência ativa para RUNE, TON e VET; mapeamento do [catálogo real](https://github.com/sapuppo/IGOR/actions/runs/36458124193).
- Hipótese e regras completas de entrada, saída e risco fixadas antes da primeira captura da coorte no [protocolo R17.03](https://github.com/sapuppo/IGOR/blob/r17-03-okx-cohort/r16_edge_lab/R17_03_OKX_BREAKOUT_PROTOCOL_PT.md). `r17_okx_breakout_signal.py` produz apenas candidatos de sinal e rejeita capturas futuras, atrasadas e estado sem 48/49 velas completas. O motor de carteira paper e a conciliação de funding ainda não estão congelados: **não iniciou a janela de validação do retorno**.
- Primeira execução real da [coleta de 35 swaps](https://github.com/sapuppo/IGOR/actions/runs/36459055346): sucesso; [captura bruta](https://github.com/sapuppo/IGOR/blob/r17-03-okx-market-data/r17_03_market_data/capture-1790616886230-4a0ee7e0fe156993.json) arquivada na cadeia separada. Janela 28/09 12:00–16:00 UTC, 35/35 pares completos, cinco eventos de funding e zero problemas. Classe `RETROSPECTIVE_BACKFILL`, pois ocorreu bem depois do fechamento da vela; **não constitui teste prospectivo pontual**.
- A rotina agendada foi configurada com duas tentativas por fronteira de 4h UTC, minutos 07 e 17. O primeiro agendamento futuro desse novo fluxo ainda não aconteceu. No piloto BTC anterior, a tentativa 16:07 UTC não gerou uma execução registrada; um evento cron do GitHub pode atrasar ou se perder. Só reconhecer uma janela após observar logs e arquivo realmente salvo.
- Testes com respostas sintéticas: 17 aprovados para captura Binance pública, piloto OKX, coorte de 35 e causalidade do sinal. Testes sintéticos não contam como resultado financeiro.

## O que falta para medir lucro de forma honesta

1. Verificar a primeira execução **agendada** da coorte e auditar cobertura subsequente; timestamps/quotes atrasados são lacunas, não preços de entrada contemporâneos.
2. Materializar histórico OKX anterior ao congelamento para aquecer as 49 velas sem chamar esse histórico de holdout; registrar hash e fonte. Implementar a carteira paper de entradas, saídas, comissão, deslizamento e financiamento conforme o protocolo, com dados de preço de liquidação do funding ou classificação `UNVERIFIED` quando não existirem.
3. Congelar esse motor de execução e iniciar somente então os 180 dias prospectivos e 100 posições encerradas. Publicar resultado mensal líquido, perdas e drawdown; não alterar regras olhando o primeiro mês nem habilitar dinheiro real sem aprovação de risco.

**Retorno da R17.03 em 2026 até esta entrega: indisponível (zero operações); nenhum percentual mensal de lucro é conhecido.** O objetivo de 20% ao mês permanece uma meta a testar, não um rendimento demonstrado.
