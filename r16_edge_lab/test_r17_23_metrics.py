import unittest,tempfile,io,zipfile,hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import collect_r17_23_oi as c
class ArchiveSafety(unittest.TestCase):
 def fake(self,checksum_ok=True):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('x.csv','create_time,symbol,sum_open_interest\n2025-01-01 03:50:00,X,100\n2025-01-01 03:55:00,X,120\n2025-01-01 04:00:00,X,130\n')
  raw=b.getvalue();sha=hashlib.sha256(raw).hexdigest() if checksum_ok else '0'*64
  def get(url,timeout):return SimpleNamespace(status_code=200,content=raw,text=sha+'  x.zip',raise_for_status=lambda:None)
  return get
 def test_conservative_availability_at_boundary(self):
  with tempfile.TemporaryDirectory() as td,patch.object(c,'C',Path(td)),patch.object(c,'get',self.fake()):r=c.task('X','2025-01-01')
  self.assertEqual(r['status'],'verified');self.assertEqual(len(r['samples']),2)
  self.assertEqual(r['samples'][0]['oi'],100)
  self.assertEqual(r['samples'][0]['timestamp']%c.BAR,c.BAR-300000)
 def test_hash_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as td,patch.object(c,'C',Path(td)),patch.object(c,'get',self.fake(False)):r=c.task('X','2025-01-01')
  self.assertEqual(r['status'],'error');self.assertIn('SHA256',r['error'])
 def test_missing_archive_not_imputed(self):
  with tempfile.TemporaryDirectory() as td,patch.object(c,'C',Path(td)),patch.object(c,'get',return_value=SimpleNamespace(status_code=404)):r=c.task('X','2025-01-01')
  self.assertEqual(r['status'],'missing_404');self.assertNotIn('samples',r)
if __name__=='__main__':unittest.main()
