# IGOR R17.27 — magnitude, perda e duração

Pesquisa isolada, sem integração com conta ou envio de ordens. A branch deriva da R17.26 congelada; nenhum arquivo anterior foi alterado.

## Reprodução

Python 3.12. Instale `python -m pip install -r requirements.txt` em ambiente próprio.

1. Reconstrua as entradas da R17.26 pelos scripts `../r17_26_probability/collect.py` e `prepare.py`, respectivos manifestos e arquivos de funding de novembro. Consulte o README da R17.26. Os arquivos públicos `.CHECKSUM` são verificados pelo coletor. Os hashes exatos consumidos nesta etapa constam de `INPUT_HASHES.json`.
2. Execute `python data27.py`: verifica novamente os 837 arquivos ZIP e produz features causais e labels de 30, 60 e 180 minutos.
3. Execute `python -m unittest test_r27 -v`.
4. Execute `OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 python run27.py`.
5. Execute `python verify27.py`.

A pasta `results/` contém cada replay, operações CSV, patrimônio diário e por minuto, amostras de decisões e seleção congelada antes do replay de novembro. Os modelos completos são `models/YYYY-MM.pkl`; metadados e hashes acompanham cada modelo. O ZIP de resultados inclui modelos e contabilidade, mas exclui dados públicos brutos, prepared e previsões densas NPZ. Estas previsões são reproduzíveis e seus hashes constam de `VERIFICATION.json`.

`protocol.json` especifica os testes. Sete variantes ML participam da seleção; a regra determinística, a referência e três horizontes isolados são controles diagnósticos. Nenhuma variante pode ser escolhida por seu resultado de novembro. Seleção em caixa significa que nenhum modelo passou, não uma estratégia lucrativa.

## Dependências do projeto existente

`data27.py` importa os leitores e labels da R17.26. `engine27.py` reutiliza os filtros públicos, entradas, funding e funções MIT de dimensionamento HyperGrok. A verificação de drawdown usa o módulo MIT do Vibe-Trading já incluído na R17.26. Licenças e commits originais estão em `../r17_26_probability/third_party/` e `PESQUISA_MODELOS_PT.md`. A comparação é com o adaptador de referência da R17.26, não uma alegação de paridade bit a bit com a produção R16.24.2.

## Limitações essenciais

Todos os meses já foram consultados pela R17.26: a separação temporal evita treinar com o futuro em cada janela, mas não torna esse histórico independente da pesquisa. Cada replay mensal reinicia patrimônio e estado de risco; os agregados encadeiam retornos com reinvestimento teórico e são avaliação mensal, não simulação contínua de um serviço persistente. Custos são cenários, spread/slippage não são reconstrução de fila; filtros da bolsa são atuais e não point-in-time. Funding usa preço de abertura como proxy de mark. O book tem snapshots e três lacunas de arquivos em 8/out. Predição de duração é uma média condicional estimada, não tempo garantido. A penalização conservadora é uma heurística, não um intervalo de confiança. Não há validação prospectiva nem lucro real comprovado.
