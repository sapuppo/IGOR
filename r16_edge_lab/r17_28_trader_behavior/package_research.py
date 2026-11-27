from pathlib import Path
import json,hashlib,zipfile
R=Path(__file__).resolve().parent;files=[]
for p in R.rglob('*'):
 if not p.is_file():continue
 rel=p.relative_to(R)
 if '__pycache__' in rel.parts or p.name in ['EVIDENCE_MANIFEST.json','PACKAGE.json','R17_28_EVIDENCE.zip']:continue
 if rel.parts[0]=='raw' and p.suffix!='.json':continue
 files.append(p)
manifest={str(p.relative_to(R)):dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files)};(R/'EVIDENCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n');files.append(R/'EVIDENCE_MANIFEST.json');z=R/'R17_28_EVIDENCE.zip'
with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as out:
 for p in sorted(files):out.write(p,str(Path(R.name)/p.relative_to(R)))
with zipfile.ZipFile(z) as f:
 for n,x in manifest.items():
  data=f.read(str(Path(R.name)/n));assert hashlib.sha256(data).hexdigest()==x['sha256'] and len(data)==x['bytes']
 assert f.testzip() is None
raw=z.read_bytes();info=dict(file=z.name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),git_blob_sha1=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),files=len(files),raw_large_export_included=False,raw_export_reference='RAW_RECEIPT.json',chunk_bytes=75000,chunks=(len(raw)+74999)//75000)
(R/'PACKAGE.json').write_text(json.dumps(info,indent=2)+'\n');print(json.dumps(info))
