#!/usr/bin/env python3
"""Causal portfolio accounting core for IGOR research.

This module contains no alpha logic. It owns cash/equity, positions, collateral,
fees, funding, stop-risk and the immutable event ledger.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Optional
import hashlib, json, math

EPS=1e-9

@dataclass
class Position:
    position_id: str
    engine: str
    symbol: str
    side: int                 # +1 long, -1 short
    qty: float
    entry_price: float
    mark_price: float
    stop_price: float
    opened_at: int
    entry_fee: float
    entry_reference: float = 0.0
    collateral: float = 0.0
    funding_cashflow: float = 0.0
    exit_fee_rate: float = 0.0
    exit_slip_rate: float = 0.0

    def notional(self) -> float:
        return abs(self.qty*self.mark_price)

    def unrealized(self) -> float:
        return self.side*self.qty*(self.mark_price-self.entry_reference)

    def stop_loss_cash(self, exit_fee_rate: float=0.0) -> float:
        raw=max(0.0, -self.side*self.qty*(self.stop_price-self.entry_price))
        fee=max(exit_fee_rate,self.exit_fee_rate)
        return raw + abs(self.qty*self.stop_price)*(fee+self.exit_slip_rate)

class PortfolioLedger:
    def __init__(self, start_cash: float, leverage: float=1.0,
                 max_stop_risk_fraction: float=0.06):
        if start_cash<=0 or leverage<=0: raise ValueError("invalid capital/leverage")
        self.start_cash=float(start_cash)
        self.cash=float(start_cash)
        self.leverage=float(leverage)
        self.max_stop_risk_fraction=float(max_stop_risk_fraction)
        self.positions: Dict[str,Position]={}
        self.events=[]
        self.realized_gross=0.0
        self.commissions=0.0
        self.slippage_cost=0.0
        self.funding=0.0
        self._last_ts=-1
        self._seq=0
        self._record(0,"INIT",{})

    def _check_time(self, ts:int):
        if ts<self._last_ts: raise AssertionError(f"non-monotonic event time {ts} < {self._last_ts}")
        self._last_ts=ts

    def equity(self)->float:
        return self.cash+sum(p.unrealized() for p in self.positions.values())

    def gross_notional(self)->float:
        return sum(p.notional() for p in self.positions.values())

    def net_notional(self)->float:
        return sum(p.side*p.qty*p.mark_price for p in self.positions.values())

    def reserved_margin(self)->float:
        return sum(p.collateral+p.funding_cashflow for p in self.positions.values())

    def available_collateral(self)->float:
        # Isolated wallets do not lend unrealized profit to other positions.
        return self.cash-self.reserved_margin()

    def aggregate_stop_risk(self, exit_fee_rate:float=0.0)->float:
        return sum(p.stop_loss_cash(exit_fee_rate) for p in self.positions.values())

    def _snapshot(self):
        eq=self.equity(); gross=self.gross_notional()
        return {
          "cash":self.cash,"equity":eq,
          "unrealized":eq-self.cash,
          "gross_notional":gross,"net_notional":self.net_notional(),
          "reserved_margin":self.reserved_margin(),
          "available_collateral":self.available_collateral(),
          "gross_to_equity":gross/eq if eq>EPS else math.inf,
          "open_stop_risk":self.aggregate_stop_risk(),
          "positions":len(self.positions),
          "realized_gross":self.realized_gross,
          "commissions":self.commissions,
          "slippage_cost":self.slippage_cost,
          "funding":self.funding,
          "minimum_isolated_equity":min((p.collateral+p.funding_cashflow+p.unrealized() for p in self.positions.values()),default=0.0),
        }

    def _record(self,ts:int,event:str,data:dict):
        self._seq+=1
        row={"seq":self._seq,"timestamp":int(ts),"event":event,**data,**self._snapshot()}
        self.events.append(row)

    def mark(self,ts:int,symbol:str,price:float):
        self._check_time(ts)
        if price<=0: raise ValueError("invalid mark")
        for p in self.positions.values():
            if p.symbol==symbol:p.mark_price=float(price)
        self._record(ts,"MARK",{"symbol":symbol,"price":float(price)})
        self.assert_reconciles()

    def mark_many(self,ts:int,prices:dict):
        """Atomic market observation avoids mixing old/new prices across symbols."""
        self._check_time(ts)
        if any(not math.isfinite(float(p)) or p<=0 for p in prices.values()):
            raise ValueError("invalid mark")
        for p in self.positions.values():
            if p.symbol in prices:p.mark_price=float(prices[p.symbol])
        self._record(ts,"MARK_BATCH",{"prices":{s:float(prices[s]) for s in sorted(prices)}})
        self.assert_reconciles()

    def can_open(self, *, side:int, qty:float, fill_price:float, stop_price:float,
                 entry_fee_rate:float, exit_fee_rate:float, reference_price:Optional[float]=None,
                 exit_slip_rate:float=0.0)->tuple[bool,str]:
        if side not in (-1,1) or qty<=0 or fill_price<=0:return False,"invalid_order"
        eq=self.equity()
        if eq<=0:return False,"nonpositive_equity"
        new_notional=abs(qty*fill_price)
        entry_fee=new_notional*entry_fee_rate
        ref=fill_price if reference_price is None else float(reference_price)
        entry_slip=max(0.0,side*qty*(fill_price-ref))
        # After paying entry commission, margin must still fit inside equity.
        projected_equity=eq-entry_fee-entry_slip
        new_margin=new_notional/self.leverage
        if new_margin+entry_fee+entry_slip>self.available_collateral()+EPS:return False,"collateral"
        new_risk=max(0.0,-side*qty*(stop_price-fill_price))+abs(qty*stop_price)*(exit_fee_rate+exit_slip_rate)
        # Reserve the risk budget against equity remaining if all current stops
        # execute. Using today's MTM alone lets ordinary open losses push the
        # same already-accepted stop commitments beyond the 6% ceiling.
        remaining_loss=sum(max(0.0,p.side*p.qty*(p.mark_price-p.stop_price))+
                           abs(p.qty*p.stop_price)*(max(exit_fee_rate,p.exit_fee_rate)+p.exit_slip_rate)
                           for p in self.positions.values())
        new_remaining_loss=max(0.0,side*qty*(ref-stop_price))+abs(qty*stop_price)*(exit_fee_rate+exit_slip_rate)
        stop_floor_equity=projected_equity-remaining_loss-new_remaining_loss
        if self.aggregate_stop_risk(exit_fee_rate)+new_risk > stop_floor_equity*self.max_stop_risk_fraction+EPS:
            return False,"aggregate_stop_risk"
        return True,"ok"

    def open(self,ts:int,position_id:str,engine:str,symbol:str,side:int,qty:float,
             fill_price:float,stop_price:float,entry_fee_rate:float=0.0,
             exit_fee_rate:float=0.0,reference_price:Optional[float]=None,exit_slip_rate:float=0.0):
        self._check_time(ts)
        if position_id in self.positions:raise AssertionError("duplicate position id")
        ok,reason=self.can_open(side=side,qty=qty,fill_price=fill_price,stop_price=stop_price,
                                entry_fee_rate=entry_fee_rate,exit_fee_rate=exit_fee_rate,
                                reference_price=reference_price,exit_slip_rate=exit_slip_rate)
        if not ok:
            self._record(ts,"REJECT",{"position_id":position_id,"engine":engine,"symbol":symbol,"reason":reason})
            return False,reason
        notional=abs(qty*fill_price);fee=notional*entry_fee_rate
        slip=0.0 if reference_price is None else max(0.0,side*qty*(fill_price-reference_price))
        ref=float(fill_price if reference_price is None else reference_price)
        self.cash-=fee+slip;self.commissions+=fee;self.slippage_cost+=slip
        self.positions[position_id]=Position(position_id,engine,symbol,side,float(qty),float(fill_price),
                                             ref,float(stop_price),int(ts),fee,ref,notional/self.leverage,
                                             0.0,float(exit_fee_rate),float(exit_slip_rate))
        self._record(ts,"OPEN",{"position_id":position_id,"engine":engine,"symbol":symbol,"side":side,
                               "qty":qty,"fill_price":fill_price,"stop_price":stop_price,
                               "reference_price":ref,"commission":fee,"slippage_cost_event":slip})
        self.assert_reconciles()
        # Entry invariant: no order may consume collateral that does not exist.
        if self.available_collateral() < -EPS:raise AssertionError("entry collateral invariant")
        return True,"ok"

    def funding_event(self,ts:int,symbol:str,rate:float):
        """Historical funding rate at its actual timestamp. Positive rate: longs pay, shorts receive."""
        self._check_time(ts)
        net=0.0;allocations=[]
        for p in self.positions.values():
            if p.symbol!=symbol:continue
            payment=-p.side*p.notional()*float(rate)
            self.cash+=payment;net+=payment;p.funding_cashflow+=payment
            allocations.append({"position_id":p.position_id,"engine":p.engine,"qty":p.qty,
                                "mark_price":p.mark_price,"side":p.side,"cashflow":payment})
        self.funding+=net
        self._record(ts,"FUNDING",{"symbol":symbol,"rate":float(rate),"funding_cashflow":net,"allocations":allocations})
        self.assert_reconciles()

    def close(self,ts:int,position_id:str,fill_price:float,exit_fee_rate:float=0.0,
              reason:str="EXIT",reference_price:Optional[float]=None):
        self._check_time(ts)
        p=self.positions[position_id]
        p.mark_price=float(fill_price)
        ref=float(fill_price if reference_price is None else reference_price)
        gross=p.side*p.qty*(ref-p.entry_reference)
        fee=abs(p.qty*fill_price)*exit_fee_rate
        slip=0.0 if reference_price is None else max(0.0,-p.side*p.qty*(fill_price-reference_price))
        self.cash+=gross-fee-slip;self.realized_gross+=gross;self.commissions+=fee;self.slippage_cost+=slip
        del self.positions[position_id]
        self._record(ts,"CLOSE",{"position_id":position_id,"engine":p.engine,"symbol":p.symbol,
                                "fill_price":fill_price,"gross_pnl_event":gross,"commission":fee,
                                "reference_price":ref,"entry_reference":p.entry_reference,"qty":p.qty,
                                "slippage_cost_event":slip,"reason":reason})
        self.assert_reconciles()
        return gross-fee-slip

    def assert_reconciles(self,tol:float=1e-7):
        expected=self.start_cash+self.realized_gross-self.commissions-self.slippage_cost+self.funding
        # cash excludes unrealized PnL by design.
        if abs(self.cash-expected)>tol*max(1.0,abs(expected)):
            raise AssertionError(f"cash reconciliation: {self.cash} != {expected}")
        eq_expected=expected+sum(p.unrealized() for p in self.positions.values())
        if abs(self.equity()-eq_expected)>tol*max(1.0,abs(eq_expected)):
            raise AssertionError("equity reconciliation")
        return True

    def manifest(self)->dict:
        payload=json.dumps(self.events,sort_keys=True,separators=(",",":"),allow_nan=False)
        return {"ledger_sha256":hashlib.sha256(payload.encode()).hexdigest(),
                "events":len(self.events),"final":self._snapshot()}

    def write_jsonl(self,path):
        with open(path,"w",encoding="utf-8") as f:
            for x in self.events:f.write(json.dumps(x,sort_keys=True,allow_nan=False)+"\n")
