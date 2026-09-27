# R16.30 H2 — short de tendência 4h em portfólio com CORE e REV1H

Status: hipótese separada registrada **antes de qualquer replay H2**. A escolha nasceu da observação de que os três motores anteriores só compram e o calendário de 2022 foi negativo. Logo, os resultados históricos desta nova regra serão contaminados pela inspeção anterior; não serão OOS nem comprovação de 20% ao mês. Experimentos históricos acumulados nesta linha de pesquisa: H1 (remoção de REV15M), H2 (nova regra short), além da exploração anterior sem registro completo.

## Regra congelada CORE_SHORT

- Usar os mesmos dados USD-M, os 38 símbolos elegíveis e candles 4h já fechados; entrada apenas na próxima abertura observável de 15m.
- Sinal de rompimento para baixo: fechamento atual abaixo da mínima dos **55 candles 4h anteriores** e fechamento anterior acima ou igual ao limite equivalente anterior; EMA50 do símbolo abaixo de EMA200; ADX14 >=30.
- Contexto BTC em 4h, conhecido ao fechamento: fechamento < EMA200, EMA50 < EMA200 e retorno de 42 candles <0. Proporção de símbolos elegíveis com fechamento acima de EMA200 <=0,45, calculada apenas com dados fechados.
- Short 1x isolado; stop na entrada +3 ATR14, alvo na entrada −6 ATR14, prazo máximo 30 candles 4h. Risco por operação 0,75% multiplicado pelo regime congelado, máximo cinco shorts, fração por posição no máximo 40%, risco agregado de stop 6%, exposição bruta total no máximo 1x **na entrada**. Não permitir simultaneamente long e short do mesmo símbolo.
- Funding recebido quando taxa positiva e pago quando negativa para a posição vendida. Stop prevalece se alvo e stop forem atingidos no mesmo candle; gap desfavorável executa na abertura. A mesma taxa taker, slippage e latência dos cenários BASE/STRESS se aplica aos dois lados.
- O regime pode aceitar CORE_SHORT com histórico de perdas apenas enquanto COLD, como já ocorre com CORE; demais controles mantidos. Esse detalhe é parte congelada desta hipótese.

## Protocolo de comparação

Comparator H1 registrado em `aeb7cda316953c2a5a2c8d88d1a4d856a0d33a46`, resultados em `2bdf30e9b56424e7f4d108fadb5b08d322aa34e2`. H2 adiciona CORE_SHORT ao portfólio H1; CORE/REV1H e a configuração original permanecem com os mesmos parâmetros. Executar BASE e STRESS integrais 2021–2026; publicar **todos** os resultados e eventuais falhas.

Antes de olhar desempenho: testar ordem e payoff de short, stop gap e candle ambíguo, sinal após candle fechado, funding com sinal correto, soma de caixa/posição e risco/exposição. Asserções de ausência de candle ativo faltante, stop risk <=6% e limite bruto de entrada <=1x. Se qualquer asserção falhar, não publicar retorno como comparável; corrigir o motor com nova versão de pesquisa e registrar a falha.

Comparar CAGR, mensal composto, P&L, drawdown MTM, pior mês, distribuição anual e contribuição CORE_SHORT vs H1. Hipótese exploratória de interesse requer no STRESS P&L maior que H1 e drawdown MTM não maior; não é gate de produção. Não aumentar alavancagem nem reduzir custos supostos para forçar a meta.

O bloqueio de liquidação por markPrice e a falta de OOS intocado persistem. A baseline validada continua R16.24.2.
