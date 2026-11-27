"""Package auditable research, without duplicating public raw ZIP archives."""
from pathlib import Path
import json,hashlib,zipfile
R=Path(__file__).resolve().parent
def main():
 excluded={'__pycache__','raw'};files=sorted([p for p in R.rglob('*') if p.is_file() and not any(x in excluded for x in p.relative_to(R).parts) and p.name not in ['ARTIFACT_MANIFEST.json','PACKAGE.json','R17_29_RESULTS.zip','R17_29_DATA.zip']])
 rows=[dict(file=str(p.relative_to(R)),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files];(R/'ARTIFACT_MANIFEST.json').write_text(json.dumps(rows,indent=2)+'\n');files.append(R/'ARTIFACT_MANIFEST.json');archives=[]
 for filename,isdata in [('R17_29_RESULTS.zip',False),('R17_29_DATA.zip',True)]:
  z=R/filename;chosen=[p for p in files if (p.relative_to(R).parts[0]=='prepared')==isdata]
  with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as out:
   for p in chosen:out.write(p,str(p.relative_to(R)))
  with zipfile.ZipFile(z) as out:assert out.testzip() is None
  b=z.read_bytes();archives.append(dict(file=z.name,bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),git_blob_sha=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),files=len(chosen)))
 meta=dict(archives=archives,files=len(files),public_raw_archive_count=510,public_raw_archives_included=False,prepared_hourly_data_included_in='R17_29_DATA.zip',extract_both_to_same_research_folder=True,minute_copy_inputs='Rebuild R17.26 prepared inputs and use preserved R17.28 export; not bundled here',initial_protocol_commit='7a6191467dae311e6dbc48b95d72217ebe2f628f',pre_replay_implementation_commit='01ca9e4abadb7d32ca50831c55bd509d2cb70000')
 (R/'PACKAGE.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta,indent=2))
if __name__=='__main__':main()
