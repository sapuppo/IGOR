"""Independent sums from pandas versus streaming CSV; strict research gates."""
from pathlib import Path
import json,hashlib
import pandas as pd,numpy as np
R=Path(__file__).resolve().parent;a=json.loads((R/'EXPORT_ANALYSIS.json').read_text());b=json.loads((R/'BEHAVIOR.json').read_text());receipt=json.loads((R/'RAW_RECEIPT.json').read_text());n=0;fee=0.;pnl=0.;ntl=0.;missing=0;rebates=0
for c in pd.read_csv(R/receipt['file'],chunksize=125000,dtype=str,keep_default_na=False):
 n+=len(c);ff=pd.to_numeric(c.fee,errors='coerce');pp=pd.to_numeric(c.closedPnl,errors='coerce');nn=pd.to_numeric(c.ntl);fee+=ff.sum();pnl+=pp.sum();ntl+=nn.sum();missing+=ff.isna().sum();rebates+=(ff<0).sum()
assert n==a['rows']==receipt['rows']==1422691
assert hashlib.sha256((R/receipt['file']).read_bytes()).hexdigest()==receipt['sha256']==a['raw_sha256']
assert np.isclose(fee,a['observed_fee_sum'],atol=1e-6) and np.isclose(pnl,a['observed_closed_pnl_sum'],atol=1e-5) and np.isclose(ntl,a['notional'],atol=1e-4)
assert int(missing)==a['missing_fee_rows'] and int(rebates)==a['rebate_fills']
assert np.isclose(sum(x['closed_pnl_observed'] for x in b['directions'].values()),pnl,atol=1e-5)
assert np.isclose(sum(x['closed_pnl_observed'] for x in b['by_coin'].values()),pnl,atol=1e-5)
d=pd.read_csv(R/'DAILY_OBSERVED.csv');assert d.fills.sum()==n and len(d)==31 and np.isclose(d.closed_pnl_reported.sum(),pnl,atol=1e-5)
fund=json.loads((R/'raw/bobby_october_userFunding_all.json').read_text());assert np.isclose(sum(float(x['delta']['usdc']) for x in fund),b['funding']['reported_payment_sum'],atol=1e-6)
manifest=json.loads((R/'PUBLIC_API_COLLECTION.json').read_text());files=[]
for x in manifest['results']:
 for p in x['pages']:
  assert hashlib.sha256((R/'raw'/p['file']).read_bytes()).hexdigest()==p['sha256'];files.append(p['file'])
recent=json.loads((R/'RECENT_COLLECTION.json').read_text())
for x in recent:
 for p in x['pages']:
  assert hashlib.sha256((R/'raw'/p['file']).read_bytes()).hexdigest()==p['sha256'];files.append(p['file'])
 assert x['full_history'] is False
for x in b['recent_native_samples']:
 z=json.loads((R/f"raw/{x['name']}_recent_fills_all.json").read_text());assert len(z)==x['fills'] and len(z)==x['makers']+x['takers'];assert all(not y['crossed'] for y in z if float(y['fee'])<0)
assert a['net_monthly_return'] is None and a['equity_drawdown'] is None and a['identified_inventory_coins']==0
assert len(a['contradiction_coins'])==13
out=dict(status='independent_sums_and_provenance_passed_research_gates_not_passed',unit_tests=13,export_rows=n,source_sha256=receipt['sha256'],daily_reconciliations=31,public_api_pages_verified=len(files),recent_samples=[dict(name=x['name'],fills=x['fills']) for x in b['recent_native_samples']],gates=dict(two_year_history=False,exact_inventory_and_campaign_reconstruction=False,portfolio_return_and_drawdown=False,strategy_backtested=False,production_promotion=False),notes=['Accounting contradictions are based on literal CSV row ordering; within-second order ambiguity is a possible cause, not resolved or silently reordered.','No missing fee or closing PnL replaced by zero when asserting complete net profit.','Reported PnL subtotal is distinct from account equity return.'])
(R/'VERIFICATION.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
