from collections import defaultdict,deque
import json
from analyze_export import iterator
from inventory import Interval,DIRECTIONS
x=defaultdict(Interval);prev=defaultdict(lambda:deque(maxlen=8));out={}
for i,t,r in iterator():
 c=r['coin'];dr=r['dir']
 if dr not in DIRECTIONS:continue
 prev[c].append(dict(index=i,time=t,direction=dr,size=r['sz'],price=r['px']))
 before=x[c].valid;x[c].add(dr,r['sz'])
 if before and not x[c].valid and c not in out:out[c]=dict(bounds=x[c].asdict(),first_contradiction=list(prev[c]))
print(json.dumps(out,indent=2));open('ORDER_DIAGNOSTICS.json','w').write(json.dumps(out,indent=2)+'\n')
