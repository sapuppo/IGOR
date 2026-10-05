import unittest
import pandas as pd
from run_r17_06_funding_feasibility import month_statistics

class FundingCoverageTest(unittest.TestCase):
    def fixture(self):
        start=pd.Timestamp('2026-01-01',tz='UTC')
        end=pd.Timestamp('2026-02-01',tz='UTC')
        times=pd.date_range(start,end,freq='8h',inclusive='left')
        frame=pd.DataFrame({'fundingTime':[int(x.timestamp()*1000)+2 for x in times],
                            'fundingRate':[.0001]*len(times)})
        return frame,start,end

    def test_known_cash_component_and_complete_month(self):
        frame,start,end=self.fixture()
        r=month_statistics(frame,'BTCUSDT',start,end)
        self.assertTrue(r['full_month_coverage'])
        self.assertEqual(r['events'],93)
        self.assertAlmostEqual(r['inventory_normalized_component'],.00465)

    def test_missing_and_prelisting_months_are_not_complete(self):
        frame,start,end=self.fixture()
        gap=frame.drop(frame.index[20:26])
        self.assertFalse(month_statistics(gap,'BTCUSDT',start,end)['full_month_coverage'])
        late=frame.iloc[3:]
        self.assertFalse(month_statistics(late,'BTCUSDT',start,end)['full_month_coverage'])

if __name__=='__main__':
    unittest.main()
