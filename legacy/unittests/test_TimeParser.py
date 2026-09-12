
import unittest
from DateTimeParser import TimeParser
from datetime import datetime

class TestTimeParser(unittest.TestCase):
    """Unit tests for TimeParser class."""

    def setUp(self):
        """Set up test environment for TimeParser."""
        self.parser = TimeParser()

    def test_parse_valid_date(self):
        """Test parsing of a valid date string."""
        self.assertEqual(self.parser.parse_date('2021-12-25'), datetime(2021, 12, 25))

    def test_parse_invalid_date(self):
        """Test parsing of an invalid date string."""
        with self.assertRaises(ValueError):
            self.parser.parse_date('invalid-date')

if __name__ == '__main__':
    unittest.main()
