"""Deterministic admission evaluation, using R17.29 limits. No order API."""
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class Policy:
    risk_per_trade: float = .0025
    max_gross_exposure: float = .60
    max_symbol_exposure: float = .20
    max_positions: int = 3
    reduce_drawdown: float = .08
    halt_drawdown: float = .20
    daily_loss: float = .04
    fee_per_side: float = .0006
    slippage_per_side: float = .0006


def initial_state():
    return dict(equity=10000., peak_equity=10000., day_start_equity=10000.,
                gross_notional=0., positions=0, halted=False, pause_until_ms=0)


def evaluate(candidate, state, *, now_ms, kill_switch=False, policy=Policy()):
    """A research candidate cannot self-certify calibration or authorization."""
    blockers = ['UNVALIDATED_STRATEGY', 'NO_EXECUTION_ADAPTER']
    required = ('equity','peak_equity','day_start_equity','gross_notional')
    try:
        if any(type(state[k]) not in (int,float) or not math.isfinite(state[k]) for k in required):
            raise ValueError('nonfinite state')
        eq, peak, day, gross = (state[k] for k in required)
        if min(eq,peak,day)<=0 or peak<eq or gross<0:
            raise ValueError('inconsistent state')
        if type(state['positions']) is not int or state['positions']<0 or type(state['halted']) is not bool:
            raise ValueError('invalid state types')
        if type(state['pause_until_ms']) is not int or state['pause_until_ms']<0:
            raise ValueError('invalid pause timestamp')
    except (ValueError, KeyError, TypeError):
        return dict(action='HOLD', blockers=['INVALID_PORTFOLIO_STATE'], order_notional=0., orders_sent=0)
    dd = 1-eq/peak
    if kill_switch or state['halted'] or dd>=policy.halt_drawdown:
        blockers.append('KILL_SWITCH_OR_DRAWDOWN_HALT')
    if eq<=day*(1-policy.daily_loss):
        blockers.append('DAILY_LOSS_LIMIT')
    if state['pause_until_ms']>now_ms:
        blockers.append('LOSS_STREAK_PAUSE')
    if gross>=policy.max_gross_exposure*eq or state['positions']>=policy.max_positions:
        blockers.append('EXPOSURE_OR_POSITION_LIMIT')
    if candidate['confidence'] is None or not candidate['confidence_calibrated']:
        blockers.append('UNCALIBRATED_PROBABILITY')
    if candidate['direction']=='neutral':
        blockers.append('NEUTRAL_DIRECTION')
    if candidate['missing_evidence']:
        blockers.append('INCOMPLETE_FUNDAMENTAL_EVIDENCE')
    f=candidate['features']
    if f['available_at_ms']>now_ms or now_ms-f['available_at_ms']>120000:
        blockers.append('STALE_OR_FUTURE_MARKET')
    if f['spread_bps']>20:
        blockers.append('EXCESSIVE_SPREAD')
    # Diagnostic risk budget only; not an approved order, fill or PnL prediction.
    factor = .5 if dd>=policy.reduce_drawdown else 1.
    stop = max(2.5*f['atr_fraction'], .002)
    cost = 2*(policy.fee_per_side+policy.slippage_per_side)
    direction = 1 if candidate['direction']=='long' else -1 if candidate['direction']=='short' else 0
    # Funding is an observed rate estimate, not a guaranteed future settlement.
    funding = max(0, direction*f['funding_rate_observed'])
    budget = max(0., min(eq*policy.max_symbol_exposure, policy.max_gross_exposure*eq-gross,
                        eq*policy.risk_per_trade*factor/(stop+cost+funding)))
    if any(b in blockers for b in ('KILL_SWITCH_OR_DRAWDOWN_HALT','DAILY_LOSS_LIMIT','LOSS_STREAK_PAUSE','EXPOSURE_OR_POSITION_LIMIT','STALE_OR_FUTURE_MARKET')):
        budget=0.
    return dict(action='HOLD', blockers=blockers, order_notional=0., orders_sent=0,
                hypothetical_risk_budget_notional=budget, hypothetical_stop_fraction=stop,
                assumed_roundtrip_cost_fraction=cost, adverse_funding_estimate=funding,
                drawdown=dd, risk_factor=factor, policy=asdict(policy))
