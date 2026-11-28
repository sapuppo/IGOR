import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from collector import digest, headlines, collect
from research import build_research, HOUR, stablecoin_context
from brain import enrich, validate, apply_session_review
from risk import evaluate, initial_state
from review import review
from run import cycle


def fixture():
    as_of=1000*HOUR+5000
    def bars(interval):
        finish=(as_of//interval)*interval
        return [[finish-(100-i)*interval,'100','103','99',str(100+i*.02),'1',
                 finish-(99-i)*interval-1,'1000000'] for i in range(100)]
    sources={
        'hourly':bars(HOUR),'four_hourly':bars(4*HOUR),
        'book':dict(E=as_of-2000,bids=[['101.9','100']],asks=[['102','100']]),
        'funding':dict(time=as_of-2000,lastFundingRate='0.0001',nextFundingTime=as_of+HOUR),
        'open_interest':dict(time=as_of-2000,openInterest='1000')}
    snap=dict(version='17.31',as_of_ms=as_of,universe=['BTCUSDT'],market={'BTCUSDT':{
        k:dict(data=v,source_id='BTCUSDT:'+k,known_ms=as_of-1000) for k,v in sources.items()}},news=[],errors=[])
    snap['snapshot_sha256']=digest(snap)
    return snap


def model_payload(research):
    return dict(candidates=[dict(symbol=c['symbol'],direction='long',setup_quality=3,confidence=.99,
                                 thesis='Hipótese de teste.',bear_case='Reversão.',invalidation='Falha de contexto.',
                                 evidence_ids=c['evidence_ids'],catalysts=[]) for c in research['candidates']])


class ResearchTests(unittest.TestCase):
    def test_closed_candles_and_missing_fundamentals(self):
        r=build_research(fixture());c=r['candidates'][0]
        self.assertLess(c['features']['last_closed_ms'],r['as_of_ms'])
        self.assertIsNone(c['confidence']);self.assertEqual(len(c['missing_evidence']),6)
        self.assertFalse(c['edge_validated'])

    def test_future_candle_price_cannot_change_features(self):
        snap=fixture(); original=build_research(snap)
        rows=snap['market']['BTCUSDT']['hourly']['data'];start=1000*HOUR
        rows.append([start,'100','100000','1','50000','1',start+HOUR-1,'1000000'])
        self.assertEqual(original['candidates'][0]['features'],build_research(snap)['candidates'][0]['features'])

    def test_candle_gap_rejected(self):
        s=fixture();s['market']['BTCUSDT']['hourly']['data'].pop(2)
        self.assertEqual(build_research(s)['candidates'],[])

    def test_stale_exchange_book_rejected(self):
        s=fixture();s['market']['BTCUSDT']['book']['data']['E']-=200000
        self.assertEqual(build_research(s)['candidates'],[])

    def test_future_observation_rejected(self):
        s=fixture();s['market']['BTCUSDT']['book']['known_ms']=s['as_of_ms']+1
        self.assertEqual(build_research(s)['candidates'],[])

    def test_crossed_book_rejected(self):
        s=fixture();s['market']['BTCUSDT']['book']['data']['bids'][0][0]='104'
        self.assertEqual(build_research(s)['candidates'],[])

    def test_nonfinite_price_rejected(self):
        s=fixture();s['market']['BTCUSDT']['hourly']['data'][0][4]='NaN'
        self.assertEqual(build_research(s)['candidates'],[])

    def test_future_headline_excluded(self):
        s=fixture();s['news']=[dict(known_ms=s['as_of_ms'],published_ms=s['as_of_ms']+1)]
        self.assertEqual(build_research(s)['primary_headlines'],[])

    def test_collector_preserves_partial_errors(self):
        def fail(url):
            return dict(url=url,requested_ms=1,received_ms=2,sha256=None,raw=None,error='HTTPError')
        with patch('collector.fetch',side_effect=fail):
            s=collect(['BTCUSDT'])
        self.assertEqual(len(s['errors']),11)
        self.assertEqual(build_research(s)['candidates'],[])

    def test_headline_without_date_not_evidence(self):
        record=dict(error=None,raw='<rss><channel><item><title>X</title><link>https://example.com</link></item></channel></rss>')
        self.assertEqual(headlines(record),[])

    def test_stablecoin_supply_change_is_not_tradable_liquidity(self):
        s=fixture();t=(s['as_of_ms']//(24*HOUR))*(24*HOUR)
        s['stablecoins']=dict(known_ms=s['as_of_ms']-1,source_id='CONTEXT:stablecoins',data=[
            dict(date=str((t-7*24*HOUR)//1000),totalCirculatingUSD={'peggedUSD':100}),
            dict(date=str(t//1000),totalCirculatingUSD={'peggedUSD':110})])
        result=stablecoin_context(s)
        self.assertAlmostEqual(result['change_7d_fraction'],.1)
        self.assertIn('not executable',result['scope'])

    def test_future_global_metric_is_unknown(self):
        s=fixture();s['global']=dict(known_ms=s['as_of_ms']-1,source_id='GLOBAL:global',
            data={'data':{'updated_at':s['as_of_ms']//1000+1,'market_cap_percentage':{'btc':50}}})
        self.assertIsNone(build_research(s)['global_context']['btc_dominance'])

    def test_chain_tvl_not_token_revenue(self):
        s=fixture();s['chains']=dict(known_ms=s['as_of_ms']-1,source_id='CONTEXT:chains',data=[dict(name='Bitcoin',tvl=100)])
        f=build_research(s)['candidates'][0]['fundamentals']
        self.assertEqual(f['chain_tvl_usd'],100);self.assertIsNone(f['revenue'])

    def test_stale_supply_is_unknown(self):
        s=fixture();s['supply']=dict(known_ms=s['as_of_ms']-1,source_id='CONTEXT:supply',data=[
            dict(id='bitcoin',last_updated='1970-01-01T00:00:00Z',circulating_supply=20)])
        # Deliberately stale provider time is not accepted as fresh fundamentals.
        self.assertIsNone(build_research(s)['candidates'][0]['fundamentals']['circulating_supply'])

    def test_supply_does_not_imply_unlock_schedule(self):
        s=fixture();s['supply']=dict(known_ms=s['as_of_ms']-1,source_id='CONTEXT:supply',data=[
            dict(id='bitcoin',last_updated='1970-02-11T16:00:00Z',circulating_supply=20)])
        f=build_research(s)['candidates'][0]['fundamentals']
        self.assertEqual(f['circulating_supply'],20);self.assertIsNone(f['unlocks'])


class ModelTests(unittest.TestCase):
    def test_unknown_risk_field_rejected(self):
        r=build_research(fixture());p=model_payload(r);p['candidates'][0]['order_notional']=100000
        with self.assertRaises(ValueError):validate(p,r)

    def test_fabricated_citation_rejected(self):
        r=build_research(fixture());p=model_payload(r);p['candidates'][0]['evidence_ids']=['fake']
        with self.assertRaises(ValueError):validate(p,r)

    def test_nan_probability_rejected(self):
        r=build_research(fixture());p=model_payload(r);p['candidates'][0]['confidence']=float('nan')
        with self.assertRaises(ValueError):validate(p,r)

    def test_missing_symbol_rejected(self):
        with self.assertRaises(ValueError):validate(dict(candidates=[]),build_research(fixture()))

    def test_llm_opinion_cannot_promote_or_self_calibrate(self):
        r=build_research(fixture())
        response=dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(model_payload(r))))])
        with patch.dict(os.environ,{'IGOR_LLM_ENDPOINT':'http://127.0.0.1:11434/v1/chat/completions','IGOR_LLM_MODEL':'test-only'}):
            out=enrich(r,request_fn=lambda body:response)
        c=out['candidates'][0]
        self.assertEqual(c['confidence'],.99);self.assertFalse(c['confidence_calibrated'])
        gate=evaluate(c,initial_state(),now_ms=r['as_of_ms'])
        self.assertEqual(gate['action'],'HOLD');self.assertEqual(gate['order_notional'],0)

    def test_remote_plain_http_rejected(self):
        with patch.dict(os.environ,{'IGOR_LLM_ENDPOINT':'http://example.com/v1/chat/completions','IGOR_LLM_MODEL':'x'}):
            with self.assertRaises(ValueError):enrich(build_research(fixture()),request_fn=lambda b:{})

    def test_chat_review_bound_to_exact_snapshot(self):
        r=build_research(fixture());doc=dict(research_sha256=r['research_sha256'],reviewed_ms=r['as_of_ms']+1,**model_payload(r))
        out=apply_session_review(r,doc)
        self.assertEqual(out['brain'],'chat_session_review')
        self.assertFalse(out['candidates'][0]['edge_validated'])
        doc['research_sha256']='0'*64
        with self.assertRaises(ValueError):apply_session_review(r,doc)


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.r=build_research(fixture());self.c=self.r['candidates'][0];self.now=self.r['as_of_ms']

    def gate(self, state=None, **kwargs):
        return evaluate(self.c,initial_state() if state is None else state,now_ms=self.now,**kwargs)

    def test_kill_switch_zeroes_budget(self):
        g=self.gate(kill_switch=True);self.assertEqual(g['hypothetical_risk_budget_notional'],0)

    def test_drawdown_halt(self):
        s=initial_state();s['equity']=7900
        self.assertIn('KILL_SWITCH_OR_DRAWDOWN_HALT',self.gate(s)['blockers'])

    def test_daily_limit(self):
        s=initial_state();s['equity']=9599
        self.assertIn('DAILY_LOSS_LIMIT',self.gate(s)['blockers'])

    def test_max_positions(self):
        s=initial_state();s['positions']=3
        self.assertEqual(self.gate(s)['hypothetical_risk_budget_notional'],0)

    def test_invalid_state(self):
        s=initial_state();s['equity']=float('nan')
        self.assertEqual(self.gate(s)['blockers'],['INVALID_PORTFOLIO_STATE'])

    def test_risk_budget_includes_friction(self):
        g=self.gate();p=g['policy'];stop=g['hypothetical_stop_fraction'];budget=g['hypothetical_risk_budget_notional']
        self.assertLessEqual(budget*(stop+g['assumed_roundtrip_cost_fraction']+g['adverse_funding_estimate']),10000*p['risk_per_trade']+1e-8)

    def test_stale_candidate(self):
        self.c['features']['available_at_ms']-=300000
        self.assertIn('STALE_OR_FUTURE_MARKET',self.gate()['blockers'])


class ReviewAndRunnerTests(unittest.TestCase):
    def test_brier_only_matured_labels(self):
        rows=[dict(decision_id='a',probability=.8,outcome=1,decision_ms=1,matured_ms=2,label_known_ms=3,label_source_sha256='a'*64)]
        self.assertAlmostEqual(review(rows,as_of_ms=3)['brier_score'],.04)
        self.assertIsNone(review(rows,as_of_ms=2)['brier_score'])

    def test_duplicate_label_not_double_counted(self):
        row=dict(decision_id='a',probability=.8,outcome=1,decision_ms=1,matured_ms=2,label_known_ms=3,label_source_sha256='a'*64)
        r=review([row,row],as_of_ms=3);self.assertEqual(r['label_count'],1);self.assertEqual(r['rejected_labels'],1)

    def test_no_labels_means_no_claim_of_calibration(self):
        r=review([],as_of_ms=100);self.assertIsNone(r['brier_score']);self.assertEqual(r['automatic_code_changes'],0)

    def test_cycle_provenance_and_no_orders(self):
        s=fixture()
        with tempfile.TemporaryDirectory() as folder:
            r=cycle(s,output=folder,decision_ms=s['as_of_ms'])
            self.assertEqual(r['orders_sent'],0)
            m=json.loads((Path(folder)/'MANIFEST.json').read_text())
            for name,sha in m['files'].items():
                self.assertEqual(hashlib.sha256((Path(folder)/name).read_bytes()).hexdigest(),sha)

    def test_tampered_snapshot_rejected(self):
        s=fixture();s['market']['BTCUSDT']['book']['data']['bids'][0][0]='101'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):cycle(s,output=folder)

    def test_failed_model_keeps_orders_blocked(self):
        s=fixture()
        with tempfile.TemporaryDirectory() as folder, patch('run.enrich',side_effect=ValueError('bad model')):
            r=cycle(s,output=folder,brain='llm',decision_ms=s['as_of_ms'])
        self.assertEqual(r['brain_error'],'ValueError');self.assertEqual(r['paper_admission'][0]['action'],'HOLD')

    def test_cli_replay_idempotence(self):
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'input.json';src.write_text(json.dumps(fixture()))
            out=Path(folder)/'output'
            cmd=[sys.executable,str(Path(__file__).parent/'run.py'),'--brain','rules','--snapshot',str(src),'--output',str(out)]
            a=subprocess.run(cmd,capture_output=True,text=True);b=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(a.returncode,0,a.stderr+a.stdout);self.assertEqual(b.returncode,0,b.stderr+b.stdout)
            self.assertEqual(len((out/'journal.jsonl').read_text().splitlines()),1)
            self.assertIn('DUPLICATE_SKIPPED',b.stdout)
            self.assertFalse((out/'.runner.lock').exists())


if __name__=='__main__':
    unittest.main()
