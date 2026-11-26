"""Deterministic version of disclosed BrainAI article screening rules.

Experimental adapter only; NOT connected to Telegram, wallets or token feeds.
No missing input is converted into a favourable observation. Not anti-rug proof.
"""
from dataclasses import dataclass
@dataclass(frozen=True)
class ScreeningDecision:
 passed: bool
 reason: str

def screen_token(token):
 checks=[('liquidity_usd',lambda x:x>=15000,'liquidity_below_15000'),('liquidity_locked_or_burned',lambda x:x is True,'lp_not_locked_or_burned'),('top10_share',lambda x:x<.30,'top10_concentration'),('dev_share',lambda x:x<.05,'dev_concentration'),('mint_enabled',lambda x:x is False,'mint_enabled'),('freeze_enabled',lambda x:x is False,'freeze_enabled'),('blacklist_enabled',lambda x:x is False,'blacklist_enabled'),('adjustable_tax',lambda x:x is False,'adjustable_tax'),('distinct_successful_sellers',lambda x:x>=5,'insufficient_distinct_sellers'),('age_minutes',lambda x:x>=20,'too_young')]
 for key,predicate,reason in checks:
  if key not in token or token[key] is None:return ScreeningDecision(False,'missing_'+key)
  try:
   if not predicate(token[key]):return ScreeningDecision(False,reason)
  except (TypeError,ValueError):return ScreeningDecision(False,'invalid_'+key)
 return ScreeningDecision(True,'all_disclosed_checks_passed')
