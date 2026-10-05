# R17.06 — funding histórico e diagnóstico do relógio paper

Registro: 05/10/2026 UTC (noite de 04/10 no Brasil). Retomada do estudo da meta de 20% ao mês. R16.24.2 permanece baseline; R17.05 foi rejeitada, e nenhum candidato foi promovido para dinheiro real.

## O que foi concluído

**Ainda não existe evidência de uma estratégia capaz de produzir 20% ao mês com consistência.** Esta etapa identificou a causa de o paper R17.04 continuar sem operações e mediu uma fonte diferente de retorno: funding recebido por um swap vendido, potencialmente protegido com spot comprado.

### Paper: o agendador não está atendendo a janela

Foi lida e revalidada localmente a cadeia original de 22 capturas, com warmup congelado, e lidas as 22 decisões correspondentes. A fotografia da auditoria é o commit de mercado `31c58fcd16807ded62caedd17464d76c1f069b5d` e o estado paper `5d07ac2faa34a315d25111f32ad6cec939fae4aa`.

| Medida até a captura de 04/10 23:02 UTC | Resultado |
| --- | ---: |
| Capturas e decisões | 22 |
| Execuções por evento schedule | 21 |
| Capturas completas | 22 |
| TIMELY_OBSERVATION | **0** |
| Capturas retrospectivas / decisões SKIP | **22 / 22** |
| Atraso mínimo / mediano / máximo dos eventos schedule após fechamento 4h | **20,81 / 114,24 / 220,27 minutos** |
| Maior tempo entre captura e processamento paper nos eventos schedule | 8,95 segundos |
| Posições / trades encerrados | **0 / 0** |
| Retorno mensal prospectivo válido | **N/A** |

Todos os dados de mercado estavam completos; o motor chegou rapidamente depois da captura, porém o agendamento chegou fora da janela de dez minutos. Nenhum desses dias conta como validação prospectiva completa. O GitHub documenta que eventos schedule podem atrasar ou ser descartados: https://docs.github.com/en/actions/how-tos/troubleshoot-workflows .

### Funding: medir componente econômico sem inventar lucro de arbitragem

Foram conferidos os hashes de 38 arquivos oficiais de taxas e examinados os meses de janeiro/2021 a junho/2026. A conta descritiva é `0,5 × soma das taxas do mês`, tomando **notional de referência constante equivalente a 50% do capital**, como referência de uma perna spot e uma perna de swap. Não modela variações de preço, basis, reequilíbrio, comissões, spread, risco da bolsa, margem, liquidação ou reinvestimento. **Não é retorno de uma estratégia, nem teto para o lucro total de cash-and-carry.** Sua finalidade é medir se a escala do funding observado sustenta a meta por si só.

Excluídos da comparação principal os meses parciais de início e os meses com intervalo entre eventos superior a 24h. Esse critério detecta lacunas grandes; não comprova independentemente que todo evento de settlement esteja presente. A coorte foi escolhida em pesquisas anteriores e não é livre de viés de sobrevivência.

| Medida | Componente de funding normalizado |
| --- | ---: |
| Combinações moeda/mês com cobertura suficiente | 2.113 |
| Combinações parciais ou com lacuna, excluídas | 13 |
| Mediana de todas as combinações completas | **+0,227% por mês** |
| Maior combinação | **+6,716%, AAVE, fevereiro/2021** |
| Menor combinação | **−17,746%, SOL, novembro/2022** |
| Combinações >=20% | **0 / 2.113** |
| Mediana BTC / ETH | +0,260% / +0,255% |

O mínimo negativo mostra que vender swaps sem filtrar ou proteger o regime de funding também pode gerar pagamentos severos. A pesquisa do BIS sobre crypto carry descreve risco de margem e liquidação, além da variação do prêmio: https://www.bis.org/publications/working-paper-1087-crypto-carry . Não confundir o prêmio anual de futures com estas somas mensais de funding em perpetuals.

| Mês 2026 | Componente BTC | Componente ETH |
| --- | ---: | ---: |
| Janeiro | +0,229% | +0,205% |
| Fevereiro | −0,032% | −0,154% |
| Março | −0,046% | −0,046% |
| Abril | −0,089% | −0,068% |
| Maio | +0,116% | +0,144% |
| Junho | +0,102% | +0,025% |

Julho–outubro não estão no acervo histórico íntegro usado neste estudo. Estes valores não podem ser somados a retorno do robô nem declarados rendimento executável. Escolher a moeda de maior funding depois de observar o mês usa conhecimento futuro; a série com essa escolha incluída no JSON é rotulada explicitamente como hindsight e não é estratégia.

## Decisão e implementação preparada

1. **Não usar funding isolado para justificar 20% ao mês.** Pode ser uma linha futura de diversificação, dependente de dados sincronizados de spot/perp, preços oficiais de marca, margens e execução nas duas pernas.
2. **Continuar o candidato R17.04 somente depois de trocar o relógio de coleta.** Foi preparado `r17_06_clock_runner.py`, com timer Linux a cada quatro horas UTC, 90 segundos depois do fechamento. Ele preserva o coletor e as regras da R17.04, confere cadeia/hash/warmup, bloqueia execução concorrente local e utiliza apenas APIs públicas e ledger paper.
3. **O executor está preparado, mas não está instalado em um host permanente.** Não houve acesso a servidor ou PC nesta sessão. Os arquivos systemd precisam do diretório e usuário configurados antes de ativar. A programação do timer foi validada sintaticamente; isso não demonstra operação contínua.
4. O executor dedicado deve escrever em uma cópia local independente dos dados, **sem dois processos escrevendo na mesma cadeia e sem enviar resultados para o ramo original**. A mudança da infraestrutura exige novo registro de início prospectivo, identificado como execução dedicada R17.06; não contar os dias anteriores como teste válido. A estratégia e seus parâmetros ficam congelados.

## Verificação

Passaram quatro testes novos: relógio após fechamento, retomada tardia, conta de funding conhecida e exclusão de meses incompletos. Passaram os 16 testes do motor/coletor/warmup da R17.04. A pré-validação do executor reconheceu as 22 capturas e o warmup original. A reprodução offline registrou 22 SKIPs, saldo inicial de 10.000 USDT, zero trades, e uma segunda execução não duplicou nenhuma decisão.

Próxima evidência necessária: coleta no relógio dedicado dentro da janela, arquivamento e decisão paper contemporânea. Só depois iniciar contagem de >=180 dias e >=100 trades para avaliação, sem elevar risco para preencher uma meta de retorno.
