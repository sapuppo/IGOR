"""Bounded, read-only Hypedexer collector. Defaults to a local dry run.
Needs an authorized existing API key and --execute. Does not create accounts,
buy subscriptions, retry quota denials, trade, or certify full-wallet returns.
"""
import argparse,datetime,hashlib,json,os,re,urllib.parse,urllib.request
from pathlib import Path

def validate_page(p):
 if not isinstance(p,dict) or p.get('success') is not True:raise ValueError('Provider did not return success=true')
 rows=p.get('data');assert isinstance(rows,list),'Provider data must be a list'
 if any(not isinstance(x,dict) for x in rows):raise ValueError('Unexpected fill schema')
 more=p.get('has_more')
 if not isinstance(more,bool):raise ValueError('Explicit has_more required; never infer completeness from a short page')
 if more and not p.get('next_cursor'):raise ValueError('Pagination cursor missing')
 return rows,more,p.get('next_cursor')

def main():
 a=argparse.ArgumentParser();a.add_argument('--wallet',required=True);a.add_argument('--start',required=True);a.add_argument('--end',required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--max-pages',type=int,default=10);a.add_argument('--execute',action='store_true');args=a.parse_args()
 if not re.fullmatch(r'0x[0-9a-fA-F]{40}',args.wallet):a.error('Invalid public wallet address')
 start=datetime.datetime.fromisoformat(args.start.replace('Z','+00:00'));end=datetime.datetime.fromisoformat(args.end.replace('Z','+00:00'))
 if start.utcoffset() is None or end.utcoffset() is None or not start<end:a.error('Use ordered timezone-aware timestamps')
 if not 1<=args.max_pages<=100:a.error('Bound pages to1..100; deliberate separate runs for larger archives')
 base='https://api.hypedexer.com/fills/user/'+args.wallet;params=dict(start_time=args.start,end_time=args.end,limit=1000);url=base+'?'+urllib.parse.urlencode(params)
 plan=dict(provider='Hypedexer',url=url,max_pages=args.max_pages,execute=args.execute,out=str(args.out),note='Read-only; requests may consume provider credits. No orders, account creation or subscriptions. Paginated completion is provider-reported, not proof that missing TWAPs, fees or ledgers were recovered.')
 if not args.execute:print(json.dumps(plan,indent=2));return
 key=os.environ.get('HYPEDEXER_API_KEY')
 if not key:a.error('HYPEDEXER_API_KEY is absent. No network request made.')
 args.out.mkdir(parents=True,exist_ok=False);manifest=dict(plan,pages=[],complete=False,stop_reason='not_started');cursor=None;seen=set()
 try:
  for i in range(args.max_pages):
   q=dict(params)
   if cursor:q['cursor']=cursor
   req=urllib.request.Request(base+'?'+urllib.parse.urlencode(q),headers={'X-API-Key':key,'Accept':'application/json'})
   with urllib.request.urlopen(req,timeout=30) as response:raw=response.read();credit_cost=response.headers.get('X-Credit-Cost');balance=response.headers.get('X-Credit-Balance')
   filename=f'page_{i:05d}.json';(args.out/filename).write_bytes(raw);p=json.loads(raw);rows,more,next_cursor=validate_page(p);manifest['pages'].append(dict(file=filename,sha256=hashlib.sha256(raw).hexdigest(),rows=len(rows),credit_cost=credit_cost,credit_balance=balance))
   if not more:manifest.update(complete=True,stop_reason='provider_has_more_false');break
   if next_cursor in seen:raise ValueError('Provider repeated cursor; stopped without guessing')
   seen.add(next_cursor);cursor=next_cursor;manifest['resume_cursor']=cursor;manifest['stop_reason']='page_cap'
 except Exception as e:
  # Error text does not include the request header or API key.
  manifest.update(complete=False,stop_reason=type(e).__name__);raise
 finally:(args.out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print(json.dumps(dict(complete=manifest['complete'],pages=len(manifest['pages']),stop_reason=manifest['stop_reason']),indent=2))

if __name__=='__main__':main()
