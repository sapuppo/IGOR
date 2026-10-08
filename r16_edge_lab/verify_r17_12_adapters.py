"""Real frozen-data signal parity; no economic performance claim."""
import gzip,json,sqlite3,hashlib
from pathlib import Path
from r17_12_history_adapter import History
HERE=Path(__file__).resolve().parent

def main():
    cache=HERE/'r16_29_2_audit/signals.jsonl.gz'
    if hashlib.sha256(cache.read_bytes()).hexdigest()!='0389c6b3218b1cb971a72e2bda03539b24fa33d8def98fb1a1352be8954a0ada':raise ValueError('signal cache hash')
    with gzip.open(cache,'rt') as f:signals=[json.loads(x) for x in f]
    chosen=next(x for x in reversed(signals) if x['engine']=='CORE')
    boundary=chosen['knowledge_ts']+1
    conn=sqlite3.connect(':memory:');history=History(HERE/'usdm_history',conn)
    got,gaps=history.signals({'boundary_ms':boundary})
    assert not gaps,gaps
    expected={(x['engine'],x['symbol'],x['knowledge_ts']) for x in signals if x['engine'] in ('CORE','REV1H') and x['knowledge_ts']==boundary-1}
    actual={(x['engine'],x['symbol'],x['knowledge_ms']) for x in got if x['engine']!='SHORT20D'}
    assert actual==expected,(actual,expected)
    from run_r17_10_breakouts import precompute
    frames,_=history.frames(boundary)
    data={s:frames[s,'4h'].set_index('open_time') for s in history.symbols}
    plan,_=precompute(data,[{'lookback_bars':120}])
    shorts={s for s,_,_ in plan[120,-1].get(boundary,[])}
    assert {s['symbol'] for s in got if s['engine']=='SHORT20D'}==shorts
    import pandas as pd
    short_boundary=int(pd.read_csv(HERE/'r17_10_results/short_20d_7d_trades.csv')['entry'].max())
    second,second_gaps=history.signals({'boundary_ms':short_boundary})
    assert not second_gaps
    second_frames,_=history.frames(short_boundary)
    second_data={s:second_frames[s,'4h'].set_index('open_time') for s in history.symbols}
    second_plan,_=precompute(second_data,[{'lookback_bars':120}])
    expected_shorts={s for s,_,_ in second_plan[120,-1].get(short_boundary,[])}
    actual_shorts={s['symbol'] for s in second if s['engine']=='SHORT20D'}
    assert actual_shorts==expected_shorts and len(actual_shorts)>0
    result={'status':'PASS','mode':'HISTORICAL_SIGNAL_PARITY_ONLY','boundary_ms':boundary,
            'core_rev1h_signal_count':len(expected),'short_signal_count_at_core_boundary':len(shorts),'second_short_boundary_ms':short_boundary,'nonzero_short_signal_count':len(actual_shorts),
            'warmup_gap_count':0,'live_orders':False,'performance_result':None}
    (HERE/'R17_12_ADAPTER_PARITY.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));conn.close()
if __name__=='__main__':main()
