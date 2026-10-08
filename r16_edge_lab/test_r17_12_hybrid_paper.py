import copy,json,math,sqlite3,tempfile,unittest
from pathlib import Path
from r17_12_hybrid_paper import BAR,CONFIG,PaperError,Journal,advance,init_state,values,reconcile
from r17_12_binance_feed import PublicBinance,normalize

T=BAR*1000

def capture(t=T,price=100):
    clock=t+30000
    return {'venue':CONFIG['venue'],'boundary_ms':t,'server_ms':clock,'class':'TIMELY','status':'COMPLETE',
            'quotes':{s:{'bid':price-.01,'ask':price+.01,'time_ms':clock} for s in ['BTCUSDT','ETHUSDT','SOLUSDT']},
            'marks':{s:{'mark':price,'time_ms':clock} for s in ['BTCUSDT','ETHUSDT','SOLUSDT']},
            'funding':[],'funding_complete_through_ms':t,'closed_15m':{}}
def signal(e='CORE',s='BTCUSDT',t=T):return {'engine':e,'symbol':s,'knowledge_ms':t-1,'atr':1.}
def step(old,c,signals):return advance(old,c,signals,c['server_ms'])
def opened():
    a,_=step(init_state(0),capture(),[signal(),signal('SHORT20D')])
    b,_=step(a,capture(T+BAR),[])
    return b

class PaperTests(unittest.TestCase):
    def test_long_latency_and_current_ask(self):
        a,ev=step(init_state(0),capture(),[signal()]);self.assertFalse(a['wallets']['LONG']['positions'])
        b,ev=step(a,capture(T+BAR,price=110),[]);p=next(iter(b['wallets']['LONG']['positions'].values()))
        self.assertAlmostEqual(p['entry'],110.01*(1+CONFIG['slip']))
        self.assertEqual(p['entered_ms'],T+BAR+30000)
    def test_short_current_bid_no_cross_wallet_borrow(self):
        a,ev=step(init_state(0),capture(),[signal('SHORT20D')]);p=next(iter(a['wallets']['SHORT']['positions'].values()))
        self.assertAlmostEqual(p['entry'],99.99*(1-CONFIG['slip']))
        self.assertLessEqual(p['qty']*p['entry'],500+1e-7)
        self.assertEqual(a['wallets']['LONG']['cash'],8000)
    def test_same_coin_opposite_sides_in_segregated_wallets(self):
        s=opened();self.assertEqual(len(s['wallets']['LONG']['positions']),1);self.assertEqual(len(s['wallets']['SHORT']['positions']),1)
    def test_funding_sign_and_dedup(self):
        s=opened();c=capture(T+2*BAR)
        event={'symbol':'BTCUSDT','time_ms':T+2*BAR,'mark':100,'rate':.001};c['funding']=[event]
        a,ev=step(s,c,[])
        self.assertLess(a['wallets']['LONG']['funding'],0);self.assertGreater(a['wallets']['SHORT']['funding'],0)
        d=capture(T+3*BAR);d['funding']=[event];b,_=step(a,d,[])
        self.assertEqual(a['wallets']['LONG']['funding'],b['wallets']['LONG']['funding']);reconcile(b)
    def test_late_funding_fails_instead_of_losing_closed_trade_charge(self):
        s=opened();c=capture(T+2*BAR);c['funding']=[{'symbol':'BTCUSDT','time_ms':T+BAR,'mark':100,'rate':.001}]
        with self.assertRaises(PaperError):step(s,c,[])
    def test_stop_exit_uses_fresh_bid_not_old_stop(self):
        s=opened();c=capture(T+2*BAR,price=80);a,ev=step(s,c,[])
        t=a['wallets']['LONG']['trades'][0];self.assertEqual(t['reason'],'STOP')
        self.assertAlmostEqual(t['exit'],79.99*(1-CONFIG['slip']));reconcile(a)
    def test_short_loss_and_fee_reconciliation(self):
        s,_=step(init_state(0),capture(),[signal('SHORT20D')]);a,_=step(s,capture(T+BAR,price=120),[])
        w=a['wallets']['SHORT'];self.assertLess(w['trades'][0]['net'],0)
        self.assertAlmostEqual(w['initial']+sum(t['net'] for t in w['trades']),w['cash'])
    def test_out_of_order_fails(self):
        s=opened()
        with self.assertRaises(PaperError):step(s,capture(),[])
    def test_stale_and_backfill_cannot_enter(self):
        c=capture();c['class']='BACKFILL';s,ev=step(init_state(0),c,[signal('SHORT20D')]);self.assertFalse(s['wallets']['SHORT']['positions'])
        c=capture();s,ev=advance(init_state(0),c,[signal('SHORT20D')],c['server_ms']+120001);self.assertFalse(s['wallets']['SHORT']['positions'])
    def test_stale_book_cannot_fill(self):
        c=capture();c['quotes']['BTCUSDT']['time_ms']-=5001
        s,ev=step(init_state(0),c,[signal('SHORT20D')]);self.assertFalse(s['wallets']['SHORT']['positions'])
    def test_incomplete_funding_with_open_positions_rejected(self):
        c=capture(T+2*BAR);c['funding_complete_through_ms']=0
        with self.assertRaises(PaperError):step(opened(),c,[])
    def test_gap_freezes_future_entries(self):
        a,_=step(init_state(0),capture(),[]);b,ev=step(a,capture(T+3*BAR),[signal('SHORT20D',t=T+3*BAR)])
        self.assertTrue(b['halted']);self.assertFalse(b['wallets']['SHORT']['positions'])
    def test_future_signal_and_pre_epoch_signal(self):
        s=signal('SHORT20D');s['knowledge_ms']=T
        with self.assertRaises(PaperError):step(init_state(0),capture(),[s])
        a,_=step(init_state(T),capture(),[signal('SHORT20D')]);self.assertFalse(a['wallets']['SHORT']['positions'])
    def test_risk_gross_and_collateral_after_every_entry(self):
        c=capture();signals=[signal('SHORT20D',s) for s in c['quotes']];a,_=step(init_state(0),c,signals)
        for key,w in a['wallets'].items():
            eq,gross,reserve,risk=values(w);self.assertLessEqual(gross,eq+1e-7);self.assertLessEqual(reserve,w['cash']+1e-7)
            self.assertLessEqual(risk,eq*CONFIG['wallets'][key]['max_stop_risk']+1e-7)
    def test_journal_restart_idempotence_and_config_pin(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'paper.db';j=Journal(path,0,'source-a');c=capture();p,changed=j.process(c,[signal('SHORT20D')],c['server_ms']);self.assertTrue(changed);j.conn.close()
            j=Journal(path,0,'source-a');p2,changed=j.process(c,[signal('SHORT20D')],c['server_ms']);self.assertFalse(changed);self.assertEqual(p,p2)
            self.assertEqual(j.conn.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],1)
            with self.assertRaises(PaperError):Journal(path,0,'source-b')
            j.conn.close()
    def test_official_mark_values_position_and_missing_mark_blocks_risk(self):
        s=opened();c=capture(T+2*BAR)
        c['marks']['BTCUSDT']['mark']=102
        a,_=step(s,c,[])
        self.assertEqual(next(iter(a['wallets']['LONG']['positions'].values()))['mark'],102)
        c=capture(T+3*BAR);del c['marks']['BTCUSDT']
        with self.assertRaises(PaperError):step(a,c,[])
    def test_revised_funding_rejected(self):
        s=opened();c=capture(T+2*BAR);f={'symbol':'BTCUSDT','time_ms':T+2*BAR,'mark':100,'rate':.001};c['funding']=[f]
        a,_=step(s,c,[]);d=capture(T+3*BAR);d['funding']=[dict(f,rate=.002)]
        with self.assertRaises(PaperError):step(a,d,[])
    def test_transaction_rollback_and_tamper_detect(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'paper.db',0,'source');c=capture();j.process(c,[],c['server_ms'])
            bad=capture(T+BAR);bad['venue']='OKX'
            with self.assertRaises(PaperError):j.process(bad,[],bad['server_ms'])
            self.assertEqual(j.conn.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],1)
            j.conn.execute("UPDATE decisions SET payload='{}'");j.conn.commit()
            with self.assertRaises(PaperError):j.latest()
            j.conn.close()
    def test_open_candle_is_excluded_and_nonpublic_endpoint_rejected(self):
        rows=[[T,'100','101','99','100','1',T+BAR-1,'100'],[T+BAR,'100','101','99','100','1',T+2*BAR-1,'100']]
        self.assertEqual(len(normalize(rows,'15m',T+BAR)),1)
        with self.assertRaises(PaperError):PublicBinance().get('/fapi/v1/order')

if __name__=='__main__':unittest.main()
