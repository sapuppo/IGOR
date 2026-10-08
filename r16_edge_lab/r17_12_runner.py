#!/usr/bin/env python3
"""One transaction per observed capture; run at 15m boundary +30s on a host."""
import argparse,json,time
from pathlib import Path
from r17_12_hybrid_paper import Journal,PaperError,CONFIG,BAR,canonical,digest
from r17_12_history_adapter import History,source_hash
from r17_12_binance_feed import PublicBinance,capture,universe

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--history-root',required=True)
    p.add_argument('--epoch-ms',type=int,required=True);p.add_argument('--snapshot');p.add_argument('--capture',action='store_true')
    p.add_argument('--check',action='store_true');p.add_argument('--boundary-ms',type=int);p.add_argument('--import-dir')
    a=p.parse_args()
    journal=Journal(a.db,a.epoch_ms,source_hash());history=History(a.history_root,journal.conn)
    if a.import_dir:
        paths=sorted(Path(a.import_dir).glob('*.json'));rows=0
        for path in paths:
            packet=json.loads(path.read_text())
            if packet.get('class')!='BACKFILL' or packet.get('venue')!=CONFIG['venue']:raise PaperError('wrong historical import')
            rows+=history.import_bars(packet)
        print(json.dumps({'mode':'FEATURE_IMPORT_ONLY','packets':len(paths),'rows':rows,'paper_orders':0}));return
    if a.check:
        boundary=a.boundary_ms or int(time.time()*1000)//BAR*BAR
        _,gaps=history.frames(boundary);state,_=journal.latest()
        print(json.dumps({'version':CONFIG['version'],'ready':not gaps,'gap_count':len(gaps),'gap_examples':gaps[:6],
               'epoch_ms':a.epoch_ms,'paper_started':state['last_server_ms'] is not None,'live_orders':False},indent=2));return
    if bool(a.snapshot)==bool(a.capture):p.error('choose --snapshot OR --capture')
    old,_=journal.latest()
    if a.capture:
        snap=capture(PublicBinance(),history.symbols,a.epoch_ms,old['last_server_ms'] or a.epoch_ms)
        directory=Path(a.db).parent/'captures';directory.mkdir(exist_ok=True)
        path=directory/(digest(snap)+'.json')
        if not path.exists():path.write_text(canonical(snap))
    else:snap=json.loads(Path(a.snapshot).read_text())
    history.import_bars(snap)
    signals,gaps=history.signals(snap)
    if gaps:
        snap=dict(snap);snap['status']='INCOMPLETE';snap['problems']=['WARMUP_OR_CANDLE_GAP']
    signals=[s for s in signals if s['knowledge_ms']>=a.epoch_ms]
    payload,changed=journal.process(snap,signals,int(time.time()*1000))
    print(json.dumps({'version':CONFIG['version'],'committed':changed,'events':payload['events'],
                     'warmup_gaps':len(gaps),'live_orders':False},indent=2))
if __name__=='__main__':main()
