import json,urllib.request,urllib.parse,datetime
from pathlib import Path
now=datetime.datetime.now(datetime.timezone.utc)
d=(now.date()-datetime.timedelta(days=1)).isoformat()
url="https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical?"+urllib.parse.urlencode({"date":d,"start":1,"limit":300,"convert":"USD"})
req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
with urllib.request.urlopen(req,timeout=30) as r: p=json.loads(r.read())
rows=[x for x in (p.get("data") or []) if 101<=int(x.get("cmcRank",0))<=300]
Path("v09_cmc_now").mkdir(exist_ok=True)
Path("v09_cmc_now/rank101_300.json").write_text(json.dumps({"date":d,"rows":rows},indent=2),encoding="utf-8")
print(d,len(rows))
