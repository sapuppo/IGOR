"""Build a verifiable source/model/result bundle without raw public inputs."""
from pathlib import Path
import json,hashlib,zipfile
from data27 import R
s=json.loads((R/'results/summary.json').read_text());v=json.loads((R/'VERIFICATION.json').read_text())
critical=['data27.py','models27.py','engine27.py','run27.py','protocol.json']
(R/'PREREGISTERED_INTEGRITY.json').write_text(json.dumps(dict(preregistered_commit='6e5f0936a1c73305e17de78d1d740947b7f71680',unchanged_since_registration=True,verified_by='byte-for-byte comparison against registered Git tree before outcomes',sha256={n:hashlib.sha256((R/n).read_bytes()).hexdigest() for n in critical}),indent=2)+'\n')
a=s['combined']['walk_forward_duration_book_h60_cost1'];b=s['combined']['final_duration_book_h60_cost1']
status=dict(version='R17.27',status='completed',date='2026-11-26',branch='research-r17-27-magnitude-duration',selected=s['selected'],promoted=False,historical_goal_passed=s['historical_goal_passed'],best_diagnostic='duration_book_h60',best_diagnostic_walk_forward=a,best_diagnostic_november_partial=b,independent_research_holdout=False,report_url='https://github.com/sapuppo/IGOR/blob/research-r17-27-magnitude-duration/r16_edge_lab/r17_27_magnitude_duration/RESULTADO_PT.md',verification=v,limitations=['Retrospective reused history, not independent research holdout','Only 16 best-horizon trades in July-October; one in November1-24','Monthly risk resets; no continuous live or paper validation','Current exchange filters, scenario spreads/slippage and snapshot book limitations','No strategy approved; no promised monthly return'])
(R/'STATUS.json').write_text(json.dumps(status,indent=2)+'\n')
files=[]
for p in R.rglob('*'):
 if not p.is_file():continue
 rel=p.relative_to(R)
 if any(x in ['prepared','__pycache__'] for x in rel.parts) or p.suffix in ['.zip','.npz'] or p.name in ['ARTIFACT_MANIFEST.json','PACKAGE.json']:continue
 if rel.parts[0]=='models' and p.suffix not in ['.pkl','.json']:continue
 files.append(p)
manifest={str(p.relative_to(R)):dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files)};(R/'ARTIFACT_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n');files.append(R/'ARTIFACT_MANIFEST.json')
z=R/'R17_27_RESULTS.zip'
with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as out:
 for p in sorted(files):out.write(p,str(Path(R.name)/p.relative_to(R)))
raw=z.read_bytes();info=dict(file=z.name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),git_blob_sha1=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),files=len(files),chunk_bytes=75000,chunks=(len(raw)+74999)//75000)
(R/'PACKAGE.json').write_text(json.dumps(info,indent=2)+'\n');print(json.dumps(info))
