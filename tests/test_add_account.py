import pytest
import tempfile
import shutil
import json
from unittest.mock import patch, MagicMock
from pathlib import Path

from config import ConfigManager, EmailAccount
from email_sync import add_account


class TestAddAccount:
    """Test suite for add_account functionality"""

    def setup_method(self):
        """Set up test environment for each test"""
        self.temp_dir = Path(tempfile.mkdtemp())
        # Create required directories
        (self.temp_dir / "config").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "tokens").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "logs").mkdir(parents=True, exist_ok=True)
        
        self.config_manager = ConfigManager(self.temp_dir)
        # Start with empty configuration
        self.config_manager.accounts = []
        self.config_manager.dest_config = {}
    
    def _setup_oauth_prerequisites(self):
        """Helper to set up OAuth config and accounts.json file"""
        self.config_manager.oauth_config = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'tenant_id': 'common'
        }
        # Create accounts.json file so add_account doesn't exit early
        self.config_manager.save_configuration(None)

    def teardown_method(self):
        """Clean up after each test"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_add_account_basic_functionality(self):
        """Test that add_account adds a new Office 365 account with correct attributes"""
        # Set up required prerequisites
        self.config_manager.oauth_config = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'tenant_id': 'common'
        }
        # Create accounts.json file so add_account doesn't exit early
        self.config_manager.save_configuration(None)
        
        # Mock user inputs
        inputs = [
            "test@office365.com",  # source email
            "dest@example.com",    # destination email
        ]
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value="password123"):
                with patch('rich.console.Console.print'):  # Mock console output
                    add_account(self.config_manager)

        # Verify account was added
        assert len(self.config_manager.accounts) == 1
        account = self.config_manager.accounts[0]
        assert account.email == "test@office365.com"
        assert account.dest_email == "dest@example.com"
        assert account.is_office365 is True
        
        # Verify password is stored in dest_config (in plain text in memory)
        assert 'passwords' in self.config_manager.dest_config
        assert self.config_manager.dest_config['passwords']["dest@example.com"] == "password123"

    def test_add_account_persists_to_configuration_file(self):
        """Test that the new account appears in the configuration file"""
        self._setup_oauth_prerequisites()
        
        # Mock user inputs
        inputs = [
            "persistent@office365.com",
            "persistent_dest@example.com",
        ]
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value="persistent_password"):
                with patch('rich.console.Console.print'):
                    add_account(self.config_manager)

        # Verify the configuration file was created and contains the account
        config_file = self.temp_dir / "config" / "accounts.json"
        assert config_file.exists()
        
        # Load the configuration file and verify contents
        with open(config_file, 'r') as f:
            config_data = json.load(f)
        
        assert 'accounts' in config_data
        assert len(config_data['accounts']) == 1
        
        account_data = config_data['accounts'][0]
        assert account_data['email'] == "persistent@office365.com"
        assert account_data['dest_email'] == "persistent_dest@example.com"
        assert account_data['is_office365'] is True
        
        # Verify password is stored (encrypted)
        assert 'destination' in config_data
        assert 'passwords' in config_data['destination']
        assert "persistent_dest@example.com" in config_data['destination']['passwords']
        # Password should be encrypted, so it won't match the plain text
        stored_password = config_data['destination']['passwords']['persistent_dest@example.com']
        assert stored_password != "persistent_password"  # Should be encrypted

    def test_add_account_password_encryption(self):
        """Test that passwords are stored encrypted in the configuration"""
        self._setup_oauth_prerequisites()
        
        # Mock user inputs
        inputs = [
            "encrypted@office365.com",
            "encrypted_dest@example.com",
        ]
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value="secret_password"):
                with patch('rich.console.Console.print'):
                    add_account(self.config_manager)

        # Create a new ConfigManager to test loading the encrypted password
        new_config_manager = ConfigManager(self.temp_dir)
        new_config_manager.load_configuration(None)
        
        # Verify the password can be decrypted correctly
        decrypted_password = new_config_manager.dest_config['passwords']['encrypted_dest@example.com']
        assert decrypted_password == "secret_password"

    def test_add_account_to_existing_configuration(self):
        """Test adding a new account to existing configuration with other accounts"""
        # Set up existing account
        existing_account = EmailAccount(
            email="existing@example.com",
            password="existing_password",
            is_office365=False
        )
        self.config_manager.accounts = [existing_account]
        self.config_manager.dest_config = {
            'host': 'localhost',
            'port': 993,
            'ssl': True,
            'passwords': {'existing@example.com': 'existing_dest_password'}
        }
        
        # Set up OAuth configuration for Office 365 accounts  
        self.config_manager.oauth_config = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'tenant_id': 'common'
        }
        
        # Save the existing configuration
        self.config_manager.save_configuration(None)
        
        # Mock user inputs for new account
        inputs = [
            "new@office365.com",
            "new_dest@example.com",
        ]
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value="new_password"):
                with patch('rich.console.Console.print'):
                    add_account(self.config_manager)

        # Verify both accounts exist
        assert len(self.config_manager.accounts) == 2
        
        # Find the new account
        new_account = next(acc for acc in self.config_manager.accounts 
                          if acc.email == "new@office365.com")
        assert new_account.is_office365 is True
        assert new_account.dest_email == "new_dest@example.com"
        
        # Verify both passwords are stored
        assert len(self.config_manager.dest_config['passwords']) == 2
        assert 'existing@example.com' in self.config_manager.dest_config['passwords']
        assert 'new_dest@example.com' in self.config_manager.dest_config['passwords']

    def test_add_account_initializes_passwords_dict(self):
        """Test that passwords dict is initialized if it doesn't exist in dest_config"""
        # Start with dest_config that doesn't have passwords key
        self.config_manager.dest_config = {
            'host': 'localhost',
            'port': 993,
            'ssl': True
        }
        
        # Set up OAuth configuration
        self.config_manager.oauth_config = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'tenant_id': 'common'
        }
        
        # Mock save_configuration to prevent encryption during test
        self.config_manager.save_configuration = MagicMock()
        
        inputs = [
            "init@office365.com",
            "init_dest@example.com",
        ]
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value="init_password"):
                with patch('rich.console.Console.print'):
                    add_account(self.config_manager)

        # Verify passwords dict was created and populated
        assert 'passwords' in self.config_manager.dest_config
        assert self.config_manager.dest_config['passwords']['init_dest@example.com'] == "init_password"

    def test_add_account_with_mocked_config_manager(self):
        """Test add_account using a mocked ConfigManager to verify method calls"""
        mock_config_manager = MagicMock()
        mock_config_manager.accounts = []
        mock_config_manager.dest_config = {}
        mock_config_manager.oauth_config = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'tenant_id': 'common'
        }
        mock_config_manager.accounts_config.exists.return_value = True
        
        # Mock the add_or_update_account method to simulate successful account addition
        def mock_add_or_update_account(account, dest_password):
            mock_config_manager.accounts.append(account)
            if 'passwords' not in mock_config_manager.dest_config:
                mock_config_manager.dest_config['passwords'] = {}
            mock_config_manager.dest_config['passwords'][account.dest_email] = dest_password
            # Simulate calling save_configuration
            mock_config_manager.save_configuration(None)
        
        mock_config_manager.add_or_update_account.side_effect = mock_add_or_update_account
        
        inputs = [
            "mock@office365.com",
            "mock_dest@example.com",
        ]
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value="mock_password"):
                with patch('rich.console.Console.print'):
                    add_account(mock_config_manager)

        # Verify load_configuration was called
        mock_config_manager.load_configuration.assert_called_once_with(None)
        
        # Verify add_or_update_account was called
        mock_config_manager.add_or_update_account.assert_called_once()
        
        # Verify save_configuration was called (through the mock_add_or_update_account)
        mock_config_manager.save_configuration.assert_called_once_with(None)
        
        # Verify account was appended
        assert len(mock_config_manager.accounts) == 1
        added_account = mock_config_manager.accounts[0]
        assert added_account.email == "mock@office365.com"
        assert added_account.is_office365 is True
        assert added_account.dest_email == "mock_dest@example.com"

    def test_add_account_strips_whitespace_from_input(self):
        """Test that add_account properly strips whitespace from user inputs"""
        inputs = [
            "  whitespace@office365.com  ",  # source email with whitespace
            "  whitespace_dest@example.com  ",  # destination email with whitespace
        ]
        
        # Set up OAuth configuration
        self.config_manager.oauth_config = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'tenant_id': 'common'
        }
        
        # Mock save_configuration to prevent encryption during test
        self.config_manager.save_configuration = MagicMock()
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value="whitespace_password"):
                with patch('rich.console.Console.print'):
                    add_account(self.config_manager)

        # Verify whitespace was stripped
        assert len(self.config_manager.accounts) == 1
        account = self.config_manager.accounts[0]
        assert account.email == "whitespace@office365.com"
        assert account.dest_email == "whitespace_dest@example.com"
        
        # Verify password key has no whitespace
        assert 'whitespace_dest@example.com' in self.config_manager.dest_config['passwords']
        assert self.config_manager.dest_config['passwords']['whitespace_dest@example.com'] == "whitespace_password"

    def test_add_account_console_output(self):
        """Test that add_account displays success message"""
        # Set up OAuth configuration
        self.config_manager.oauth_config = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'tenant_id': 'common'
        }
        
        inputs = [
            "output@office365.com",
            "output_dest@example.com",
        ]
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value="output_password"):
                with patch('rich.console.Console.print') as mock_print:
                    add_account(self.config_manager)

        # Verify success message was printed
        mock_print.assert_called_with("[blue]You can now run 'python3 email_sync.py sync' to start synchronization.[/blue]")

    @pytest.mark.parametrize("source_email,dest_email,password", [
        ("test1@office365.com", "dest1@example.com", "password1"),
        ("test2@company.office365.com", "dest2@company.com", "complex_pass!@#"),
        ("user@tenant.onmicrosoft.com", "user@local.server", "simple123"),
    ])
    def test_add_account_various_inputs(self, source_email, dest_email, password):
        """Test add_account with various email addresses and passwords"""
        # Set up OAuth configuration
        self.config_manager.oauth_config = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'tenant_id': 'common'
        }
        
        inputs = [source_email, dest_email]
        
        # Mock save_configuration to prevent encryption during test
        self.config_manager.save_configuration = MagicMock()
        
        with patch('builtins.input', side_effect=inputs):
            with patch('getpass.getpass', return_value=password):
                with patch('rich.console.Console.print'):
                    add_account(self.config_manager)

        # Verify account was added correctly
        assert len(self.config_manager.accounts) == 1
        account = self.config_manager.accounts[0]
        assert account.email == source_email
        assert account.dest_email == dest_email
        assert account.is_office365 is True
        
        # Verify password was stored correctly
        assert self.config_manager.dest_config['passwords'][dest_email] == password
