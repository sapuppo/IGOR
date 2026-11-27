"""Read-only public Hyperliquid requests. No credentials or order methods."""
from pathlib import Path
import urllib.request,json,datetime,hashlib,time
R=Path(__file__).resolve().parent;RAW=R/'raw';RAW.mkdir(exist_ok=True)
ADDRESS='0x7fdafde5cfb5465924316eced2d3715494c517d1'
def stamp(s):return int(datetime.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)
START=stamp('2026-10-01T00:00:00Z');END=stamp('2026-11-01T00:00:00Z')
def request(payload):
 req=urllib.request.Request('https://api.hyperliquid.xyz/info',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'});r=urllib.request.urlopen(req,timeout=25);return json.load(r)
def main():
 manifest=[]
 for kind in ['userFunding','userNonFundingLedgerUpdates']:
  rows=[];pages=[];cursor=START;complete=False
  for page in range(200):
   payload=dict(type=kind,user=ADDRESS,startTime=cursor,endTime=END-1);z=request(payload)
   if not isinstance(z,list):raise ValueError(str(z)[:400])
   p=RAW/f'bobby_october_{kind}_{page:03}.json';raw=(json.dumps(z,separators=(',',':'))+'\n').encode();p.write_bytes(raw);pages.append(dict(file=p.name,sha256=hashlib.sha256(raw).hexdigest(),count=len(z),request=payload))
   print('PAGE',kind,page,len(z),flush=True)
   rows.extend(z)
   if not z:complete=True;break
   last=max(int(x['time']) for x in z)
   # Seek inclusive last timestamp, not last+1, so tied events are preserved.
   if last<cursor:raise ValueError('Timestamp did not advance')
   if last==cursor:
    # If all rows are tied, API cap may hide events. Never claim complete.
    if len(z)>=500:break
    cursor=last+1
   else:cursor=last
   if len(z)<500:
    # Short page means no more events in range; endpoint limit documented500.
    complete=True;break
   time.sleep(.15)
  # De-duplicate pagination overlap by complete event identity; ledger hash
  # and funding time/coin/amount distinguish ordinary entries. Keep raw pages.
  unique={json.dumps(x,sort_keys=True,separators=(',',':')):x for x in rows};allrows=sorted(unique.values(),key=lambda x:x['time']);(RAW/f'bobby_october_{kind}_all.json').write_text(json.dumps(allrows,separators=(',',':'))+'\n')
  manifest.append(dict(type=kind,complete_within_public_endpoint=complete,rows=len(allrows),raw_rows_with_overlap=len(rows),pages=pages,warning='API response completeness is conditional on endpoint history retention; no archive guarantee inferred.'))
 (R/'PUBLIC_API_COLLECTION.json').write_text(json.dumps(dict(address=ADDRESS,start=START,end_exclusive=END,results=manifest),indent=2)+'\n')
 print('COMPLETE',[(x['type'],x['rows'],x['complete_within_public_endpoint']) for x in manifest],flush=True)
if __name__=='__main__':main()
