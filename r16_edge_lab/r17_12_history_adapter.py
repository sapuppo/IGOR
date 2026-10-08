#!/usr/bin/env python3
"""Immutable Binance warmup + append-only closed candles; frozen alpha adapters."""
import hashlib,json,math,sqlite3
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import r16_usdm_engine as alpha
from r17_12_hybrid_paper import PaperError,BAR,CONFIG,canonical

INTERVAL={'15m':BAR,'1h':4*BAR,'4h':16*BAR}
COLS=['open_time','open','high','low','close','volume','quote_volume']
HERE=Path(__file__).resolve().parent
FROZEN=json.loads((HERE/'r17_07_candidate_config.json').read_text())

def source_hash():
    names=['r17_12_hybrid_paper.py','r17_12_history_adapter.py','r17_12_binance_feed.py',
           'r17_12_runner.py','r17_12_paper_config.json','r17_07_candidate_config.json','r16_usdm_engine.py']
    return hashlib.sha256(''.join(hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in names).encode()).hexdigest()

class History:
    def __init__(self,root,conn):
        self.root=Path(root);self.conn=conn
        manifest=alpha.verify_dataset(root)
        self.symbols=sorted(x['symbol'] for x in manifest['symbols'] if x['eligible'])
        if manifest['dataset_manifest_sha256']!=CONFIG['dataset_manifest_sha256']:raise PaperError('warmup manifest mismatch')
        self.conn.execute('CREATE TABLE IF NOT EXISTS market_bars(symbol TEXT, interval TEXT, opened INTEGER, row TEXT, PRIMARY KEY(symbol,interval,opened))')
        self.conn.commit();self.base={}
        for s in self.symbols:
            for interval in INTERVAL:
                f=pd.read_csv(self.root/'klines'/interval/(s+'.csv.gz'),usecols=COLS)
                self.base[s,interval]=f
    def import_bars(self,snapshot):
        boundary=int(snapshot['boundary_ms']);batch=[]
        for s,intervals in snapshot.get('bars',{}).items():
            if s not in self.symbols:raise PaperError('symbol outside frozen universe')
            for interval,rows in intervals.items():
                if interval not in INTERVAL:raise PaperError('interval mismatch')
                seen=set()
                for row in rows:
                    if set(row)!=set(COLS):raise PaperError('candle fields incomplete')
                    t=int(row['open_time']);values=[float(row[k]) for k in COLS[1:]]
                    if t in seen or t%INTERVAL[interval] or t+INTERVAL[interval]>boundary:raise PaperError('duplicate/open candle')
                    seen.add(t)
                    op,hi,lo,cl,vol,qvol=values
                    if not all(math.isfinite(v) for v in values) or min(op,hi,lo,cl)<=0 or hi<max(op,lo,cl) or lo>min(op,hi,cl) or min(vol,qvol)<0:raise PaperError('invalid candle')
                    normalized=dict(zip(COLS,[t]+values));payload=canonical(normalized)
                    base=self.base[s,interval]
                    idx=int(base.open_time.searchsorted(t))
                    prior=base.iloc[idx] if idx<len(base) and int(base.open_time.iloc[idx])==t else None
                    if prior is not None:
                        if any(not math.isclose(float(prior[k]),normalized[k],rel_tol=1e-10,abs_tol=1e-9) for k in COLS[1:]):raise PaperError('warmup candle revision')
                        continue
                    previous=self.conn.execute('SELECT row FROM market_bars WHERE symbol=? AND interval=? AND opened=?',(s,interval,t)).fetchone()
                    if previous and previous[0]!=payload:raise PaperError('appended candle revision')
                    batch.append((s,interval,t,payload))
        try:
            self.conn.execute('BEGIN IMMEDIATE')
            self.conn.executemany('INSERT OR IGNORE INTO market_bars VALUES(?,?,?,?)',batch);self.conn.commit()
        except Exception:self.conn.rollback();raise
        return len(batch)
    def frames(self,boundary):
        result={};gaps=[]
        for key,base in self.base.items():
            s,interval=key;step=INTERVAL[interval]
            extra=[json.loads(x[0]) for x in self.conn.execute('SELECT row FROM market_bars WHERE symbol=? AND interval=? AND opened+?<=? ORDER BY opened',(s,interval,step,boundary))]
            f=base if not extra else pd.concat([base,pd.DataFrame(extra)],ignore_index=True)
            f=f.loc[f.open_time+step<=boundary].sort_values('open_time').reset_index(drop=True)
            result[key]=f
            n=250 if interval=='4h' else 192 if interval=='15m' else 96
            end=boundary//step*step
            wanted=list(range(end-n*step,end,step))
            tail=f.loc[f.open_time>=wanted[0],'open_time'].astype(int).tolist()
            if tail!=wanted:gaps.append({'symbol':s,'interval':interval,'required_through_ms':end,'last_observed_end_ms':None if f.empty else int(f.open_time.iloc[-1])+step})
        return result,gaps
    def signals(self,snapshot):
        boundary=int(snapshot['boundary_ms']);frames,gaps=self.frames(boundary)
        if gaps:return [],gaps
        dataset=SimpleNamespace(pit={s:0 for s in self.symbols},frames={k:v[['open_time','open','high','low','close','volume']] for k,v in frames.items()})
        previous=alpha.CONFIG.copy()
        try:
            alpha.CONFIG.clear();alpha.CONFIG.update(FROZEN)
            longs=alpha.generate_signals(dataset)
        finally:alpha.CONFIG.clear();alpha.CONFIG.update(previous)
        out=[{'engine':x['engine'],'symbol':x['symbol'],'knowledge_ms':x['knowledge_ts'],'atr':x['atr']} for x in longs if x['knowledge_ts']==boundary-1]
        if boundary%(16*BAR)==0:
            short=[]
            for s in self.symbols:
                f=frames[s,'4h'];close=float(f.close.iloc[-1]);low=float(f.low.iloc[-121:-1].min())
                if close<low and float(f.quote_volume.iloc[-42:].median())>=5_000_000:
                    short.append((s,abs(close/low-1)))
            short.sort(key=lambda x:(-x[1],x[0]))
            out.extend({'engine':'SHORT20D','symbol':s,'knowledge_ms':boundary-1} for s,_ in short)
        return out,[]
