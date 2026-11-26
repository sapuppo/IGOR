"""Execute installed trained model on the final archived snapshot, no network."""
import json
import pandas as pd
from prepare import R,BASE_FEATURES,BOOK_FEATURES
from paper_adapter import infer
f=pd.read_pickle(R/'prepared/BTCUSDT_features.pkl');row=f.loc[f.book_valid].iloc[-1];features={k:float(row[k]) for k in BASE_FEATURES+BOOK_FEATURES+['stop_fraction']};features['available_at_ms']=int(row.name)
item=dict(symbol='BTCUSDT',decision_ms=int(row.name),features=features,label='historical archived snapshot; not a live quote')
(R/'paper_fixture.json').write_text(json.dumps(item,indent=2)+'\n')
result=infer(features,symbol='BTCUSDT',decision_ms=int(row.name));(R/'PAPER_SMOKE_RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(result['mode'],result['orders_sent'],[x['decision'] for x in result['candidates']])
