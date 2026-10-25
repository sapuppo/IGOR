"""Independent mathematical adaptations of public HB/FT entry rules.

See r17_24_sources.json for immutable references. This is NOT a reproduction
of either bot: 4h completed bars, IGOR portfolio sizing/exits, no live orders.
"""
from collections import defaultdict
import numpy as np
import pandas as pd
from r17_candidate_signals import BAR_MS

MODES = ('hb_bollinger', 'hb_macd_bb', 'ft_ema_ha')

def seeded_ema(series, length):
    """SMA seed then recursive EMA; preserve initial missing values."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    valid = series.dropna()
    if len(valid) < length:
        return out
    if series.loc[valid.index[0]:].isna().any():
        raise ValueError('interior gap in EMA input')
    x = valid.copy()
    x.iloc[:length-1] = np.nan
    x.iloc[length-1] = valid.iloc[:length].mean()
    out.loc[x.index] = x.ewm(span=length, adjust=False).mean()
    return out

def indicators(frame):
    c = frame.close
    mid = c.rolling(100, min_periods=100).mean()
    sd = c.rolling(100, min_periods=100).std(ddof=0)
    bbp = (c-(mid-2*sd))/(4*sd).replace(0, np.nan)
    macd = seeded_ema(c, 21)-seeded_ema(c, 42)
    histogram = macd-seeded_ema(macd, 9)
    ha_close = frame[['open','high','low','close']].mean(axis=1)
    ha_open = np.full(len(frame), np.nan)
    if len(frame):
        ha_open[0] = (frame.open.iloc[0]+c.iloc[0])/2
        for i in range(1, len(frame)):
            ha_open[i] = (ha_open[i-1]+ha_close.iloc[i-1])/2
    return pd.DataFrame(dict(bbp=bbp,macd=macd,hist=histogram,
        ema20=seeded_ema(c,20),ema50=seeded_ema(c,50),
        ha_open=ha_open,ha_close=ha_close),index=frame.index)

def conditions(x, mode):
    if mode == 'hb_bollinger':
        return x.bbp<0, x.bbp>1
    if mode == 'hb_macd_bb':
        return (x.bbp<0)&(x['hist']>0)&(x.macd<0), (x.bbp>1)&(x['hist']<0)&(x.macd>0)
    if mode == 'ft_ema_ha':
        cross=(x.ema20>x.ema50)&(x.ema20.shift()<=x.ema50.shift())
        return cross&(x.ha_close>x.ema20)&(x.ha_close>x.ha_open), pd.Series(False,index=x.index)
    raise ValueError('unknown strategy '+mode)

def signals(data, mode, start, end):
    maps={(1,side):defaultdict(list) for side in (1,-1)}
    for sym,f in sorted(data.items()):
        if not f.index.is_monotonic_increasing or f.index.has_duplicates:
            raise ValueError('unordered/duplicate candles')
        x=indicators(f)
        liq=f.quote_volume.rolling(42,min_periods=42).median()>=5e6
        masks=conditions(x,mode)
        strength=((x.ema20-x.ema50).abs()/f.close if mode=='ft_ema_ha' else (x.bbp-.5).abs())
        for side,mask in zip((1,-1),masks):
            # Sustained HB signals preserved; executor prevents a second position
            # in the same symbol. FT uses only the actual upward crossover.
            for t in f.index[mask & liq & np.isfinite(strength)]:
                at=int(t)+BAR_MS
                if start<=at<end:
                    maps[1,side][at].append((sym,side,float(strength.at[t])))
    for ev in maps.values():
        for t in ev:
            ev[t].sort(key=lambda z:(-z[2],z[0]))
    return maps
