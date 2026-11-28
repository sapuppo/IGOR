# IGOR R17.30 — preparação da pesquisa de execução

Data: 27/11/2026. Base: R17.29, commit `1f051ae18cf6a4f46cfc3ff50cde70f530ccd49e`.

## Resultado desta etapa

Auditoria de arquitetura e validador offline de gravações normalizadas de livro e negócios. **16 testes passaram. Nenhum teste econômico novo, captura ao vivo, modelo de fila ou integração com corretora foi executado.** A R17.29 continua reprovada para promoção; esta etapa não altera esse resultado.

## O que já existe e o que falta

| Camada da referência enviada | Evidência no IGOR | Lacuna concreta |
|---|---|---|
| Pesquisa e seleção | `r17_29_role_regime/policy29.py`, protocolo e seleção walk-forward | Estratégias avaliadas não demonstraram vantagem suficiente; acrescentar um agente não resolve isso por si só. |
| Decisão estruturada | `r17_26_probability/paper_adapter.py`: candidatos com probabilidade, expectativa, horizonte e ranking | Contrato offline; falta integração validada com fluxo prospectivo e estado persistente. |
| Motor de estado | `r17_29_role_regime/engine29.py`: posições, custos, funding e patrimônio | Replay horário taker; não reconstrói fila, cancelamentos nem latência de ordens maker. |
| Livro de ofertas | `r17_26_probability/live_book.py`: profundidade agregada de 0,2% e 1% | Não contém níveis individuais, sequência de deltas nem negócios agressivos necessários à pesquisa de preenchimentos. |
| Risco determinístico | `engine29.py`: dimensionamento, exposição, perda diária, drawdown e pausa | Validação operacional e reconciliação no adaptador real continuam pendentes. |
| Revisão e evidências | Relatórios, manifestos, testes e comparação de custos R17.29 | Mudanças automáticas de estratégia precisam de nova versão congelada e avaliação independente antes de promoção. |

Nenhuma dependência AgentKit/Jev foi acrescentada. As alegações de latência e calibração da imagem não foram verificadas. Limiares como confiança de 0,80 e Kelly não são adotados sem validação própria. Os limites de risco existentes não foram alterados.

## Validador implementado

`audit_feed.py` recebe um JSONL de **um único símbolo**, em ordem de recebimento local. Preços e quantidades são strings decimais. Rejeita timestamps futuros, eventos atrasados, livro obsoleto, níveis duplicados/desordenados, livro cruzado, negócios repetidos, agressor desconhecido e quebra de continuidade declarada.

Eventos de livro contêm o livro completo reconstruído no instante conhecido. O adaptador futuro deve verificar a sincronização específica da corretora e somente então emitir `continuity_verified=true`. `sequence` é o identificador final da atualização; `previous_sequence` referencia a última atualização emitida. Não pressupomos incremento de um em um. O primeiro evento inicia um segmento já sincronizado. Uma desconexão ou lacuna exige novo arquivo/segmento e invalida ordens simuladas anteriores.

Exemplo exclusivamente sintético, sem evidência de mercado:

```json
{"type":"book","symbol":"BTCUSDT","exchange_ms":100,"received_ms":110,"continuity_verified":true,"sequence":42,"previous_sequence":null,"bids":[["100","2"]],"asks":[["101","3"]]}
{"type":"trade","symbol":"BTCUSDT","exchange_ms":120,"received_ms":130,"trade_id":"t1","aggressor":"sell","price":"100","quantity":"1"}
```

```bash
python -m unittest discover -s r16_edge_lab/r17_30_execution_readiness -p 'test_*.py' -v
python r16_edge_lab/r17_30_execution_readiness/audit_feed.py /caminho/captura.jsonl --max-book-age-ms 1000
```

Saída inclui SHA256 do arquivo, contagens, atraso máximo e spread médio observado. O limite de idade de 1.000 ms é uma configuração inicial de validação, não latência medida nem parâmetro de estratégia. O relógio local deve estar sincronizado: atraso de rede e diferença entre relógios não podem ser separados apenas por esses campos. A ordem entre canais é a de recebimento; não inferimos ordem global de matching a partir de timestamps iguais.

O resultado `CAPTURE_SCHEMA_VALID_ONLY` valida somente este contrato. Não comprova integridade do adaptador, completude de captura, preenchimento ou rentabilidade. `promotion=BLOCKED`, `fills_estimated=0`, sem envio de ordens. O validador carrega o arquivo em memória; dividir capturas longas em segmentos sincronizados antes de uso.

## Próximo experimento: protocolo antes dos resultados

1. Implementar e validar um capturador público de depth + trades com recuperação de gaps, horários de recebimento e manifesto de cobertura. Não há gravação real com esse contrato nesta entrega.
2. Congelar universo, período, regras de cotação, risco, inventário e cancelamento antes de calcular resultados. Dados já pesquisados permanecem exploratórios.
3. Construir replay de eventos: sinal, envio, chegada estimada, aceite, parcial, cancelamento solicitado e confirmação são eventos distintos. Uma ordem continua exposta até confirmação do cancelamento. Post-only que cruza deve ser rejeitada.
4. Tratar fila como estimativa: iniciar atrás da quantidade exibida na chegada; não antecipar execução por redução de book sem negócios compatíveis. L2 não revela ordens individuais ou liquidez oculta. Reportar sensibilidade e ambiguidades; toque no candle não é fill.
5. Conciliar patrimônio e inventário em cada evento. Separar spread bruto, comissão maker/taker, funding, saída agressiva e perdas por seleção adversa. Rebates só entram se comprovados para a conta e período. Medir markout em horizontes congelados, como 1s/5s/30s.
6. Comparar com caixa e controles simples usando o mesmo feed e custos. Piorar taxas, fila e latência de forma explícita; não declarar monotonicidade do PnL apenas porque a latência aumentou, pois a seleção de fills muda.
7. Registrar parâmetros, hashes, tentativas e limites antes de avaliação prospectiva. Exigir reconciliação e evidência econômica antes de avançar a paper; qualquer operação real exige etapa posterior autorizada.

## Verificação e limites

16 testes offline com dados sintéticos passaram, incluindo rejeição de dados inválidos, determinismo e ausência de mutação dos dados. Isso valida o contrato implementado, não o funcionamento em mercado. Nenhuma rentabilidade ou meta mensal foi medida nesta etapa. A baseline operacional não foi modificada.
