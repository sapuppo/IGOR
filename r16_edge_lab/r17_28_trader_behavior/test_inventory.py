import unittest
from decimal import Decimal as D
from inventory import Interval,CampaignTracker,legs
class TestInventory(unittest.TestCase):
 def test_identifies_inherited_position(self):
  x=Interval();x.add('Close Long','2');x.add('Open Short','1');self.assertTrue(x.identified);self.assertEqual(x.lower,D(2))
 def test_not_assume_zero(self):
  x=Interval();x.add('Open Long','1');x.add('Close Long','.5');self.assertTrue(x.valid);self.assertFalse(x.identified)
 def test_detect_missing_fill_or_bad_label(self):
  x=Interval();x.add('Open Long','1');x.add('Close Long','2');x.add('Open Long','1');x.add('Open Short','1');self.assertFalse(x.valid)
 def test_exact_decimal(self):
  x=Interval();x.add('Open Long','.1');x.add('Open Long','.2');x.add('Close Long','.3');x.add('Open Short','.1');self.assertEqual(x.lower,D(0));self.assertTrue(x.identified)
 def test_split_reversal(self):
  q,o,c=legs('2','Long > Short','3');self.assertEqual((q,o,c),(D(-1),D(1),D(2)))
 def test_reversal_constraint(self):
  x=Interval();x.add('Long > Short','3');self.assertFalse(x.identified);self.assertTrue(x.lower_strict and x.upper_strict)
 def test_partial_close_campaign(self):
  t=CampaignTracker(D(0));t.add('Open Long','2',100,0,2,None);t.add('Close Long','1',110,60000,1,10);self.assertEqual(len(t.completed),0);t.add('Close Long','1',120,120000,1,20);z=t.completed[0];self.assertEqual(z['hold_minutes'],2);self.assertEqual(z['net_before_funding'],26)
 def test_rebate_and_flip_fee(self):
  t=CampaignTracker(D(0));t.add('Open Long','2',100,0,-1,None);t.add('Long > Short','3',110,60000,3,20);self.assertEqual(t.completed[0]['net_before_funding'],19);self.assertEqual(t.q,D(-1));self.assertEqual(t.current.fees_reported,1)
 def test_missing_fees_never_zero(self):
  t=CampaignTracker(D(0));t.add('Open Long','1',100,0,None,None);t.add('Close Long','1',110,60000,1,10);self.assertIsNone(t.completed[0]['net_before_funding'])
 def test_missing_close_pnl_never_zero(self):
  t=CampaignTracker(D(0));t.add('Open Long','1',100,0,1,None);t.add('Close Long','1',110,60000,1,None);self.assertTrue(t.completed[0]['gross_missing_close']);self.assertIsNone(t.completed[0]['net_before_funding'])
 def test_inherited_no_fake_hold(self):
  t=CampaignTracker(D(1));t.add('Close Long','1',110,60000,1,10);self.assertIsNone(t.completed[0]['hold_minutes']);self.assertIsNone(t.completed[0]['net_before_funding'])
 def test_fee_currency_not_merged(self):
  t=CampaignTracker(D(0));t.add('Open Long','1',100,0,1,None,'HYPE');t.add('Close Long','1',110,60000,1,10);self.assertIsNone(t.completed[0]['net_before_funding'])
 def test_unfinished_campaign_not_closed(self):
  t=CampaignTracker(D(0));t.add('Open Long','1',100,0,1,None);self.assertEqual(len(t.completed),0);self.assertIsNotNone(t.current)
if __name__=='__main__':unittest.main(verbosity=2)
