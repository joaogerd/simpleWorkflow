from cryptography.fernet import Fernet
from decouple import config
import os

class EmailConfigManager:
    """
    A class for managing email configurations securely.

    This class provides methods to encrypt and decrypt sensitive email configuration data, 
    such as SMTP passwords, using the cryptography library.

    Attributes:
        encryption_key (str): The key used for encryption and decryption operations.

    Methods:
        encrypt_password(password: str) -> str
            Encrypts an SMTP password.

            Args:
                password (str): The SMTP password to encrypt.

            Returns:
                str: The encrypted password.

            Example:
                >>> ecm = EmailConfigManager("my_encryption_key")
                >>> encrypted_pass = ecm.encrypt_password("my_password")

        decrypt_password(encrypted_password: str) -> str
            Decrypts an encrypted SMTP password.

            Args:
                encrypted_password (str): The encrypted SMTP password to decrypt.

            Returns:
                str: The decrypted password.

            Example:
                >>> ecm = EmailConfigManager("my_encryption_key")
                >>> decrypted_pass = ecm.decrypt_password(encrypted_pass)

    """

    def __init__(self):
        self.key_file = '.encryption_key'
        self.password_file = '.encrypted_password'
        self.cipher_suite = None

    def generate_key(self):
        """
        Generate an encryption key and save it to a file.
        """
        key = Fernet.generate_key()
        with open(self.key_file, 'wb') as key_file:
            key_file.write(key)

    def load_key(self):
        """
        Load the encryption key from the file.
        
        Returns:
            bytes: The encryption key.
        """
        with open(self.key_file, 'rb') as key_file:
            return key_file.read()

    def encrypt_password(self, password):
        """
        Encrypt the password and save it to a file.
        
        Args:
            password (str): The plain-text SMTP password.
        """
        if not os.path.exists(self.key_file):
            self.generate_key()

        self.cipher_suite = Fernet(self.load_key())
        encrypted_password = self.cipher_suite.encrypt(password.encode())
        with open(self.password_file, 'wb') as password_file:
            password_file.write(encrypted_password)

    def decrypt_password(self):
        """
        Decrypt the password from the file.
        
        Returns:
            str: The decrypted SMTP password.
        """
        encrypted_password = open(self.password_file, 'rb').read()
        return self.cipher_suite.decrypt(encrypted_password).decode()

    def get_email_config(self):
        """
        Load the encrypted password and create an email configuration dictionary.
        
        Returns:
            dict: The email configuration dictionary.
        """
        if not os.path.exists(self.password_file):
            raise FileNotFoundError("Encrypted password file not found. Run 'encrypt_password' first.")

        email_config = {
            "smtp_server": config('SMTP_SERVER'),
            "smtp_port": config('SMTP_PORT', default=587, cast=int),
            "smtp_username": config('SMTP_USERNAME'),
            "smtp_password": self.decrypt_password(),
            "from_email": config('FROM_EMAIL'),
            "to_email": config('TO_EMAIL'),
        }

        return email_config
