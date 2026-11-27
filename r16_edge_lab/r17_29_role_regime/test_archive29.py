import unittest
from archive_fetch29 import validate_page
class ArchiveTests(unittest.TestCase):
 def test_short_page_does_not_imply_complete(self):
  rows,more,cursor=validate_page(dict(success=True,data=[],has_more=True,next_cursor='next'));self.assertTrue(more);self.assertEqual(cursor,'next')
 def test_missing_cursor_rejected(self):
  with self.assertRaises(ValueError):validate_page(dict(success=True,data=[{}],has_more=True))
 def test_missing_completion_flag_rejected(self):
  with self.assertRaises(ValueError):validate_page(dict(success=True,data=[]))
 def test_provider_rejection_stays_rejected(self):
  with self.assertRaises(ValueError):validate_page(dict(success=False,data=[],has_more=False))
 def test_explicit_last_page(self):
  self.assertFalse(validate_page(dict(success=True,data=[{}],has_more=False))[1])
if __name__=='__main__':unittest.main()
