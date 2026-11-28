"""One-shot or foreground research loop; offline paper admission only."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import time
from collector import collect, canonical, digest, now_ms
from research import build_research
from brain import enrich, apply_session_review
from risk import evaluate, initial_state
from review import review


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(canonical(value))
    temp.replace(path)


def report_text(result):
    r = result['research']
    stamp = datetime.fromtimestamp(r['as_of_ms']/1000,timezone(timedelta(hours=-3))).isoformat()
    lines = [f'# IGOR R17.31 — pesquisa ({stamp})', '',
             f'Cérebro: `{r["brain"]}`. Estado: pesquisa; ordens reais: 0.', '',
             '**Não houve execução, preenchimento ou medição de rentabilidade neste ciclo.**', '',
             '| Ativo | Contexto 4h | Hipótese | 24h | Spread bps | Funding observado | Decisão |',
             '|---|---|---|---:|---:|---:|---|']
    gates={x['symbol']:x for x in result['paper_admission']}
    for c in r['candidates']:
        f=c['features']
        lines.append(f'| {c["symbol"]} | {f["regime"]} | {c["direction"]} | {f["return_24h"]:.2%} | {f["spread_bps"]:.3f} | {f["funding_rate_observed"]:.5%} | HOLD |')
    lines += ['', 'O ranking é força técnica descritiva; não é expectativa de lucro nem probabilidade calibrada.', '']
    for c in r['candidates']:
        lines += [f'## {c["symbol"]}', '', c['thesis'], '', f'Risco da tese: {c["bear_case"]}', '',
                  f'Invalidação: {c["invalidation"]}', '',
                  'Pendências: '+', '.join(c['missing_evidence'])+'.', '',
                  'Dados fundamentais disponíveis (sem inferir receita do token): '+json.dumps(c['fundamentals'],ensure_ascii=False)+'.', '',
                  'Bloqueios: '+', '.join(gates[c['symbol']]['blockers'])+'.', '',
                  'Fontes de dados: '+', '.join(c['evidence_ids'])+'.', '']
    lines += ['## Cobertura e limitações', '',
              'Snapshot REST não fornece fila maker. Funding observado não garante o próximo pagamento.', '',
              'Dominância BTC: '+str(r['global_context']['btc_dominance'])+'.', '',
              'Stablecoins (proxy de oferta, não liquidez executável): '+json.dumps(r['global_context']['stablecoin_liquidity'])+'. Rotação narrativa: não apurada.', '',
              f'Símbolos rejeitados: {len(r["invalid_symbols"])}. Erros de coleta: {len(r["collection_errors"])}.', '',
              '## Notícias de fontes primárias', '']
    if not r['primary_headlines']:
        lines += ['Nenhuma manchete recente com data verificável disponível neste ciclo.', '']
    for n in r['primary_headlines'][:10]:
        lines += [f'- [{n["title"].replace(chr(10), " ")}]({n["url"]})']
    lines += ['', 'Manchetes não foram classificadas como catalisadores confirmados dos tokens.', '',
              '## Revisão', '', json.dumps(result['review'],ensure_ascii=False,indent=2), '',
              '## O QUE PODEMOS ESTAR ERRANDO?', '',
              'O contexto técnico pode não ter vantagem líquida; há lacunas fundamentais, custos variáveis, '
              'seleção adversa e risco de sobreajuste. A opinião da IA não é uma probabilidade calibrada. '
              'Esquema/citações válidos não comprovam a verdade das interpretações do modelo.', '']
    if result.get('brain_error'):
        lines += ['Falha do modelo: '+result['brain_error']+'. Permaneceu a análise por regras, sem promoção.', '']
    lines += ['## Proveniência', '',
              f'Snapshot SHA256: `{r["snapshot_sha256"]}`. Pesquisa SHA256: `{r["research_sha256"]}`.', '',
              'As respostas públicas integrais e horários de recebimento estão em snapshot.json.', '']
    return '\n'.join(lines)


def cycle(snapshot, *, output, brain='rules', state=None, labels=(), decision_ms=None, kill_switch=False, session_review=None):
    # Refuse modified input rather than silently attributing decisions to an old hash.
    original=dict(snapshot); claimed=original.pop('snapshot_sha256',None)
    if claimed is not None and digest(original)!=claimed:
        raise ValueError('snapshot fingerprint mismatch')
    research=build_research(snapshot)
    brain_error=None
    configured=bool(os.getenv('IGOR_LLM_ENDPOINT') and os.getenv('IGOR_LLM_MODEL'))
    if brain=='llm' or (brain=='auto' and configured):
        try:
            research=enrich(research)
        except (OSError,ValueError,KeyError,IndexError,TypeError) as exc:
            brain_error=type(exc).__name__
    if session_review is not None:
        research=apply_session_review(research,session_review)
    decision_ms=now_ms() if decision_ms is None else decision_ms
    if session_review is not None:
        decision_ms=max(decision_ms,session_review['reviewed_ms'])
    state=initial_state() if state is None else state
    gates=[dict(symbol=c['symbol'], **evaluate(c,state,now_ms=decision_ms,kill_switch=kill_switch)) for c in research['candidates']]
    result=dict(research=research,paper_admission=gates,review=review(labels,as_of_ms=decision_ms),
                decision_ms=decision_ms,brain_error=brain_error,orders_sent=0,
                portfolio_state_kind='SIMULATED_ADMISSION_ONLY',portfolio_state=state)
    folder=Path(output); folder.mkdir(parents=True,exist_ok=True)
    atomic_json(folder/'snapshot.json',snapshot)
    atomic_json(folder/'research.json',result)
    (folder/'RESULTADO_PT.md').write_text(report_text(result),encoding='utf-8')
    atomic_json(folder/'MANIFEST.json',dict(version='17.31',orders_sent=0,files={
        name:__import__('hashlib').sha256((folder/name).read_bytes()).hexdigest()
        for name in ('snapshot.json','research.json','RESULTADO_PT.md')}))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'runs')
    parser.add_argument('--snapshot',type=Path,help='replay public snapshot; original knowledge time is retained')
    parser.add_argument('--brain',choices=('rules','auto','llm'),default='auto')
    parser.add_argument('--brain-file',type=Path,help='this chat review, bound to an exact snapshot; replay only')
    parser.add_argument('--cycles',type=int,default=1,help='0 runs continuously in foreground')
    parser.add_argument('--interval',type=int,default=900)
    parser.add_argument('--kill-switch',type=Path,default=Path(__file__).parent/'KILL_SWITCH')
    parser.add_argument('--labels',type=Path,help='optional JSON array of independently sourced matured labels')
    args=parser.parse_args()
    if args.cycles<0 or (args.cycles!=1 and args.interval<60):
        parser.error('cycles must be >=0 and repeated cycles need interval>=60 seconds')
    if args.snapshot and args.cycles!=1:
        parser.error('snapshot replay is one-shot')
    if args.brain_file and (not args.snapshot or args.brain!='rules'):
        parser.error('brain-file needs --snapshot and --brain rules')
    args.output.mkdir(parents=True,exist_ok=True)
    # Exclusive lock prevents concurrent journal writers. Removed on clean exit.
    lock=args.output/'.runner.lock'
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        parser.error('output has an active or stale runner lock; inspect the process before removing it')
    try:
        os.write(fd,str(os.getpid()).encode());os.close(fd)
        done=0
        while args.cycles==0 or done<args.cycles:
            try:
                snapshot=json.loads(args.snapshot.read_text()) if args.snapshot else collect()
                labels=json.loads(args.labels.read_text()) if args.labels else []
                run_id=str(snapshot['as_of_ms'])+'_'+snapshot['snapshot_sha256'][:12]
                path=args.output/run_id
                # Identical snapshot is not appended twice to the prospective journal.
                if not (path/'MANIFEST.json').exists():
                    result=cycle(snapshot,output=path,brain=args.brain,labels=labels,
                                 decision_ms=snapshot['as_of_ms'] if args.snapshot else None,
                                 kill_switch=args.kill_switch.exists(),
                                 session_review=json.loads(args.brain_file.read_text()) if args.brain_file else None)
                    record=dict(run_id=run_id,as_of_ms=snapshot['as_of_ms'],snapshot_sha256=snapshot['snapshot_sha256'],
                                research_sha256=result['research']['research_sha256'],orders_sent=0,
                                replay=bool(args.snapshot),candidate_count=len(result['research']['candidates']),
                                brain=result['research']['brain'])
                    with (args.output/'journal.jsonl').open('ab') as journal:
                        journal.write(canonical(record)+b'\n')
                    atomic_json(args.output/'latest.json',record)
                    print(json.dumps(record),flush=True)
                else:
                    print(json.dumps(dict(run_id=run_id,status='DUPLICATE_SKIPPED')),flush=True)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                # Error type only; source content and secrets are not logged as instructions.
                print(json.dumps(dict(status='CYCLE_FAILED',error=type(exc).__name__,orders_sent=0)),flush=True)
                if args.cycles==1:
                    return 2
            done+=1
            if args.cycles==0 or done<args.cycles:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print(json.dumps(dict(status='STOPPED',orders_sent=0)),flush=True)
    finally:
        lock.unlink(missing_ok=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
