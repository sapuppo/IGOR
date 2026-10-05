import unittest
from r17_forward_capture import BAR_MS
from r17_06_clock_runner import next_deadline, BUFFER_MS

class ClockTest(unittest.TestCase):
    def test_buffer_after_close_and_rollover(self):
        boundary=1000*BAR_MS
        self.assertEqual(next_deadline(boundary),boundary+BUFFER_MS)
        self.assertEqual(next_deadline(boundary+BUFFER_MS-1),boundary+BUFFER_MS)
        self.assertEqual(next_deadline(boundary+BUFFER_MS),boundary+BAR_MS+BUFFER_MS)

    def test_late_restart_does_not_schedule_past_deadline(self):
        boundary=1000*BAR_MS
        late=boundary+12*60000
        self.assertGreater(next_deadline(late),late)
        self.assertEqual(next_deadline(late),boundary+BAR_MS+BUFFER_MS)

if __name__=='__main__':
    unittest.main()
