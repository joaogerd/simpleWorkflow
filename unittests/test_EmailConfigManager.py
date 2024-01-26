
import unittest
from EmailConfigManager import EmailConfigManager

class TestEmailConfigManager(unittest.TestCase):
    """Unit tests for EmailConfigManager class."""

    def setUp(self):
        """Set up test environment for EmailConfigManager."""
        self.manager = EmailConfigManager()

    def test_encrypt_decrypt(self):
        """Test encryption and decryption of a string."""
        original = 'secret'
        encrypted = self.manager.encrypt_password(original)
        decrypted = self.manager.decrypt_password(encrypted)
        self.assertEqual(original, decrypted)

if __name__ == '__main__':
    unittest.main()
