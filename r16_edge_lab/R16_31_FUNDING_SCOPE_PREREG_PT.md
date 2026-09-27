# R16.31 — pré-registro do teste técnico de funding com preço de liquidação

**Registrado antes de executar replay restrito e antes de consultar qualquer retorno dessa janela.** Hipótese única: no intervalo de `2023-11-01T00:00:00Z` até `2026-07-01T00:00:00Z` exclusivo, a fonte congelada USD-M contém `markPrice` oficial para cada evento de funding dos 38 símbolos elegíveis, portanto o replay da H1 sem REV15M consegue processar funding sem preço substituto. A data deriva da adição documentada de `markPrice` ao endpoint USD-M em 01/11/2023. No próprio arquivo o campo começa em 31/10; usar 01/11 como corte conservador.

## Entradas imutáveis

- Código de simulação R16.29.2 commit `f8c2307533265653f1faf0832fda836b21641f85`; sem alteração na baseline do usuário R16.24.2.
- Manifest do dataset `a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041` e configuração R16.29.2, sem mudança em capital, taxas, deslizamento, alavancagem, riscos, símbolo ou alpha.
- Sinais congelados SHA-256 `c6a01e1e0a7f32640861213e3dba83fcdfebbef5eb8d172dc1ecc955579be71d`; apenas os motores CORE e REV1H da H1, já escolhida após inspeção histórica.
- Suplemento de funding já coletado com taxas e preços do endpoint oficial, verificado por SHA-256 e por evento com a fonte original congelada.

## Procedimento e critério antes do teste

1. Auditar todos os arquivos de funding e de marcação frente aos hashes e taxas congelados; conferir ledgers BASE/STRESS originais de 2023-11 em diante contra preço, taxa e fluxo de caixa.
2. Reiniciar a carteira em 10.000 USDT no instante de corte, **sem importar posições** anteriores. Histórico anterior ao corte somente para aquecer features causais. Executar H1 BASE e STRESS com a política congelada até 30/06/2026. Não calcular nem publicar retorno ou ranking nessa etapa.
3. Para cada cenário, exigir `funding_settlement_evidence.proxy == 0` nos shadows, todos os eventos de funding do ledger com marca oficial e nenhum buraco de candle ativo; qualquer falha = `BLOCKED` no escopo restrito.
4. Publicar apenas contagens, hashes e status da **cobertura de fonte e replay de funding**. Isso não resolve a falta do período 2021–out/2023, não torna a R16.29.2 ou a H1 tecnicamente válidas no todo e não cria janela OOS, pois esse histórico já foi consultado na pesquisa.

**Decisão predefinida:** sucesso apenas no subteste `SOURCE_AND_SCOPED_FUNDING_PASS`; classificação geral permanece `TECHNICALLY_INVALID`, sem aprovação de capital real. Qualquer nova janela de avaliação econômica precisará de contrato técnico separado, custos reais reconciliados e observações futuras intocadas.
