"""Recover truncated compressed output; freeze selections and assert same metrics."""
import gzip,json
from pathlib import Path
import numpy as np,pandas as pd
from data import load,ms,DAY,STEP
from engine import replay
R=Path(__file__).resolve().parent;O=R/'results';p=json.loads((R/'protocol.json').read_text());sel=json.loads((O/'selection_frozen.json').read_text());ds=None;repaired=[]
for f in O.glob('*intraday.csv.gz'):
 try:
  raw=gzip.decompress(f.read_bytes());assert raw
  continue
 except Exception:pass
 key=f.name[:-16];j=int(key.split('_')[0].replace('validation',''));family=key.split('_')[1];cost=int(key[-1]);a,b,c=p['folds'][j];spec=sel[str(j)][family]
 if spec is None:marks=[dict(timestamp=t,equity=10000.) for t in range(ms(b)+STEP,ms(c)+1,STEP)]
 else:
  if ds is None:ds=load(False)
  r,d,tr=replay(ds,spec,ms(b),ms(c),cost);old=json.loads((O/(key+'.json')).read_text())
  for field in ['total_return','max_15m_dd','trades','sharpe']:assert np.isclose(r[field],old[field]),(key,field)
  marks=r.pop('intraday_details')
 raw=pd.DataFrame(marks).to_csv(index=False).encode();tmp=f.with_suffix('.tmp');tmp.write_bytes(gzip.compress(raw,mtime=0));tmp.replace(f);assert gzip.decompress(f.read_bytes())==raw;repaired.append(key)
print(repaired);(O/'output_recovery.json').write_text(json.dumps(dict(repaired=repaired,metrics_unchanged=True),indent=2)+'\n')
