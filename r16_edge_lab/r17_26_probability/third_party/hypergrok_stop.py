"""Exact extracted pure sizing primitives from HyperGrok (MIT).
Copyright retained in LICENSE_HYPERGROK. Source version in THIRD_PARTY.json.
Network/CLI helpers intentionally not copied. Functions below unchanged.
"""
from decimal import Decimal, ROUND_DOWN
BPS=Decimal(10000)
MIN_ORDER_VALUE_USD=Decimal(10)
class UnpriceableStop(ValueError):
    """The slippage the market implies leaves no positive stop fill to size from."""

def lot(sz_decimals: int) -> Decimal:
    return Decimal(1).scaleb(-sz_decimals)

def round_down(size: Decimal, sz_decimals: int) -> Decimal:
    return size.quantize(lot(sz_decimals), rounding=ROUND_DOWN)

def price_stop(entry: Decimal, stop: Decimal, equity: Decimal, risk_pct: Decimal,
               taker_fee_pct: Decimal, slip_bps: Decimal, sz_decimals: int) -> dict:
    """The desk's stressed-stop arithmetic, sized both ways."""
    if entry == stop:
        raise ValueError("stop must differ from entry")
    long = stop < entry
    risk_usd = equity * risk_pct / Decimal(100)
    drawn = abs(entry - stop)
    slip = entry * slip_bps / BPS
    stop_fill = stop - slip if long else stop + slip
    if stop_fill <= 0:
        raise UnpriceableStop(f"{slip_bps:,.1f} bps of slippage leaves the stop fill at or below zero")
    fees = (entry + stop_fill) * taker_fee_pct / Decimal(100)
    stressed = abs(entry - stop_fill) + fees

    def sized(distance: Decimal) -> dict:
        size = round_down(risk_usd / distance, sz_decimals)
        loss = size * stressed
        return {
            "size": size,
            "notional": size * entry,
            "loss_if_triggered": loss,
            "loss_pct_of_equity": loss / equity * Decimal(100),
            "over_budget_usd": loss - risk_usd,
            "meets_min_order_value": size * entry >= MIN_ORDER_VALUE_USD,
            "at_least_one_lot": size >= lot(sz_decimals),
        }

    return {
        "side": "long" if long else "short",
        "risk_usd": risk_usd,
        "drawn_distance": drawn,
        "slip_bps": slip_bps,
        "slip": slip,
        "stop_fill": stop_fill,
        "fees_per_unit": fees,
        "stressed_distance": stressed,
        "drawn_stop": sized(drawn),
        "stressed_stop": sized(stressed),
    }
