"""Public read-only coarse histories. These are not transaction archives."""
from pathlib import Path
import json
from fetch_public import request
R=Path(__file__).resolve().parent
for name,address in [('bobby','0x7fdafde5cfb5465924316eced2d3715494c517d1'),('wintermute','0xecb63caa47c7c4e77f60f1ce858cf28dc2b82b00')]:
 (R/f'raw/{name}_portfolio.json').write_text(json.dumps(request(dict(type='portfolio',user=address)),separators=(',',':'))+'\n')
