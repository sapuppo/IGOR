"""Finite, read-only recent samples. Explicitly not two-year history."""
import json,time,hashlib,datetime
from pathlib import Path
from fetch_public import request
R=Path(__file__).resolve().parent;O=R/'raw';end=int(time.time()*1000)
wallets={'bobby':'0x7fdafde5cfb5465924316eced2d3715494c517d1','wintermute':'0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00'}
manifest=[]
for name,address in wallets.items():
 cursor=1704067200000;rows=[];pages=[];warning=[]
 for page in range(6):
  payload=dict(type='userFillsByTime',user=address,startTime=cursor,endTime=end,aggregateByTime=False);z=request(payload)
  if not isinstance(z,list):raise ValueError(z)
  raw=(json.dumps(z,separators=(',',':'))+'\n').encode();p=O/f'{name}_recent_fills_{page}.json';p.write_bytes(raw);pages.append(dict(file=p.name,sha256=hashlib.sha256(raw).hexdigest(),count=len(z),request=payload));rows.extend(z);print('RECENT',name,page,len(z),flush=True)
  if not z or len(z)<2000:break
  last=max(x['time'] for x in z)
  if last<=cursor:warning.append('Pagination stalled at timestamp cap; incomplete even within retained window');break
  cursor=last;time.sleep(7)
 def key(x):return tuple(x.get(k) for k in ['coin','time','tid','oid','side','sz','px','startPosition'])
 unique={key(x):x for x in rows};z=sorted(unique.values(),key=lambda x:(x['time'],str(x['coin']),x.get('tid',0)));(O/f'{name}_recent_fills_all.json').write_text(json.dumps(z,separators=(',',':'))+'\n')
 time.sleep(7);twap=request(dict(type='userTwapSliceFills',user=address));(O/f'{name}_recent_twap.json').write_text(json.dumps(twap,separators=(',',':'))+'\n')
 manifest.append(dict(name=name,address=address,rows=len(z),first_time=min((x['time'] for x in z),default=None),last_time=max((x['time'] for x in z),default=None),pages=pages,twap_rows=len(twap),snapshot_end_inclusive=end,full_history=False,warning=warning+['Retained recent window only. Older fills unavailable through native endpoint. TWAP slices separate, not merged into campaign accounting.']))
(R/'RECENT_COLLECTION.json').write_text(json.dumps(manifest,indent=2)+'\n');print('DONE_RECENT',[(m['name'],m['rows']) for m in manifest],flush=True)
