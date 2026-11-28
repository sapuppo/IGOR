import copy
import unittest
from audit_feed import audit, InvalidFeed


def fixture():
    return [
        dict(type='book', symbol='BTCUSDT', exchange_ms=100, received_ms=110,
             continuity_verified=True, sequence=42, previous_sequence=None,
             bids=[['100', '2']], asks=[['101', '3']]),
        dict(type='trade', symbol='BTCUSDT', exchange_ms=120, received_ms=130,
             trade_id='t1', aggressor='sell', price='100', quantity='1'),
    ]


class CaptureTests(unittest.TestCase):
    def rejected(self, events):
        with self.assertRaises(InvalidFeed):
            audit(events)

    def test_valid_is_not_profit_or_fill_evidence(self):
        r = audit(fixture())
        self.assertEqual(r['promotion'], 'BLOCKED')
        self.assertFalse(r['profit_estimated'])
        self.assertEqual(r['fills_estimated'], 0)

    def test_future_timestamp(self):
        e = fixture(); e[1]['exchange_ms'] = 131; self.rejected(e)

    def test_receive_reordering(self):
        e = fixture(); e[1].update(received_ms=109, exchange_ms=100); self.rejected(e)

    def test_delayed_event(self):
        e = fixture(); e[1]['received_ms'] = 2000; self.rejected(e)

    def test_stale_book_with_fresh_trade(self):
        e = fixture(); e[1].update(received_ms=2000, exchange_ms=1999); self.rejected(e)

    def test_sequence_gap(self):
        e = fixture(); b = copy.deepcopy(e[0]); b.update(received_ms=140, sequence=44, previous_sequence=43)
        self.rejected(e + [b])

    def test_venue_sequences_need_not_increment_by_one(self):
        e = fixture(); b = copy.deepcopy(e[0]); b.update(received_ms=140, sequence=50, previous_sequence=42)
        self.assertEqual(audit(e + [b])['counts']['book'], 2)

    def test_duplicate_trade(self):
        e = fixture(); self.rejected(e + [e[1]])

    def test_crossed_book(self):
        e = fixture(); e[0]['bids'][0][0] = '102'; self.rejected(e)

    def test_nonfinite_or_negative_or_zero_quantity(self):
        for value in ('NaN', 'Infinity', '-1', '0'):
            e = fixture(); e[1]['quantity'] = value; self.rejected(e)

    def test_unverified_continuity(self):
        e = fixture(); e[0]['continuity_verified'] = False; self.rejected(e)

    def test_no_book_and_no_trades(self):
        self.rejected([]); self.rejected(fixture()[:1]); self.rejected(fixture()[1:])

    def test_unknown_aggressor(self):
        e = fixture(); e[1]['aggressor'] = 'unknown'; self.rejected(e)

    def test_mixed_symbols(self):
        e = fixture(); e[1]['symbol'] = 'ETHUSDT'; self.rejected(e)

    def test_unsorted_and_duplicate_levels(self):
        for rows in ([['99', '1'], ['100', '1']], [['100', '1'], ['100', '2']]):
            e = fixture(); e[0]['bids'] = rows; self.rejected(e)

    def test_reproducible_and_input_not_mutated(self):
        e = fixture(); before = copy.deepcopy(e)
        self.assertEqual(audit(e), audit(e)); self.assertEqual(e, before)


if __name__ == '__main__':
    unittest.main()
