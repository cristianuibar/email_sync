import pytest
import tempfile
import shutil
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from email_sync import main
from config import ConfigManager, EmailAccount
from oauth import OAuth2Manager
from sync import SyncManager


class TestIntegration:
    """Integration tests for the complete workflow"""
    
    def setup_method(self):
        """Set up test environment for each test"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.script_dir = self.temp_dir / "email_sync"
        self.script_dir.mkdir()
        
        # Create subdirectories
        (self.script_dir / "config").mkdir()
        (self.script_dir / "tokens").mkdir()
        (self.script_dir / "logs").mkdir()
        (self.script_dir / "logs" / "imapsync").mkdir()
        
    def teardown_method(self):
        """Clean up after each test"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    @patch('email_sync.OAuth2Manager')
    @patch('email_sync.ConfigManager')
    @patch('email_sync.SyncManager')
    def test_setup_add_account_dry_run_sync_workflow(self, mock_sync_manager_class, mock_config_manager_class, mock_oauth_manager_class):
        """Integration test: setup -> add-account -> dry-run sync"""
        
        # Step 1: Mock setup command
        mock_config_manager = MagicMock()
        mock_oauth_manager = MagicMock()
        mock_sync_manager = MagicMock()
        
        mock_config_manager_class.return_value = mock_config_manager
        mock_oauth_manager_class.return_value = mock_oauth_manager
        mock_sync_manager_class.return_value = mock_sync_manager
        
        # Configure mock config manager
        mock_config_manager.accounts = []
        mock_config_manager.dest_config = {}
        mock_config_manager.accounts_config.exists.return_value = False
        
        # Step 1: Run setup
        with patch('sys.argv', ['email_sync.py', 'setup', '--client-id', 'test_client_id', '--client-secret', 'test_client_secret']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    with patch('rich.prompt.Confirm.ask', return_value=False):  # Mock confirmation
                        try:
                            main()
                        except SystemExit:
                            pass
        
        # Verify OAuth manager was configured
        mock_oauth_manager_class.assert_called_with('test_client_id', 'test_client_secret', 'common', mock_config_manager.script_dir / "tokens")
        mock_oauth_manager.acquire_token.assert_called_once()
        mock_config_manager.save_configuration.assert_called_with(mock_oauth_manager)
        
        # Step 2: Mock add-account command
        # Reset mocks for the next command
        mock_config_manager.reset_mock()
        mock_oauth_manager.reset_mock()
        
        # Configure for add-account
        mock_config_manager.accounts = []
        mock_config_manager.dest_config = {'passwords': {}}
        mock_config_manager.accounts_config.exists.return_value = True
        
        with patch('sys.argv', ['email_sync.py', 'add-account', '--email', 'test@office365.com', '--office365']):
            with patch('getpass.getpass', return_value='dest_password'):
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        try:
                            main()
                        except SystemExit:
                            pass
        
        # Verify account was added
        assert len(mock_config_manager.accounts) == 1
        added_account = mock_config_manager.accounts[0]
        assert added_account.email == 'test@office365.com'
        assert added_account.is_office365 == True
        
        # Step 3: Mock sync command with dry-run
        # Reset mocks for the sync command
        mock_config_manager.reset_mock()
        mock_oauth_manager.reset_mock()
        mock_sync_manager.reset_mock()
        
        # Configure for sync
        mock_config_manager.accounts = [EmailAccount('test@office365.com', is_office365=True)]
        mock_config_manager.dest_config = {'host': 'localhost', 'port': 993, 'passwords': {'test@office365.com': 'dest_password'}}
        mock_config_manager.oauth_config = {'client_id': 'test_client_id', 'client_secret': 'test_client_secret', 'tenant_id': 'common'}
        
        with patch('sys.argv', ['email_sync.py', 'sync', '--dry-run']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    try:
                        main()
                    except SystemExit:
                        pass
        
        # Verify sync was called with dry-run parameter
        mock_sync_manager.sync_accounts.assert_called_once()
        call_args = mock_sync_manager.sync_accounts.call_args
        assert call_args[0][1] == True  # dry_run parameter should be True
    
    def test_real_config_manager_workflow(self):
        """Test with real ConfigManager to ensure persistence works"""
        config_manager = ConfigManager(self.script_dir)
        
        # Step 1: Simulate setup by saving initial configuration
        config_manager.dest_config = {
            'host': 'localhost',
            'port': 993,
            'ssl': True,
            'ssl_verify': False,
            'passwords': {}
        }
        # Create a mock OAuth manager to save OAuth config
        mock_oauth = MagicMock()
        mock_oauth.client_id = 'test_client_id'
        mock_oauth.client_secret = 'test_client_secret'
        mock_oauth.tenant_id = 'common'
        config_manager.save_configuration(mock_oauth)
        
        # Step 2: Add an account
        account = EmailAccount(
            email='integration@office365.com',
            is_office365=True,
            dest_email='integration@localhost.com'
        )
        config_manager.accounts.append(account)
        config_manager.dest_config['passwords']['integration@localhost.com'] = 'integration_password'
        config_manager.save_configuration(None)
        
        # Step 3: Create a new ConfigManager to simulate loading
        new_config_manager = ConfigManager(self.script_dir)
        new_config_manager.load_configuration(None)
        
        # Verify configuration persistence
        assert len(new_config_manager.accounts) == 1
        assert new_config_manager.accounts[0].email == 'integration@office365.com'
        assert new_config_manager.accounts[0].is_office365 == True
        assert new_config_manager.accounts[0].dest_email == 'integration@localhost.com'
        
        assert new_config_manager.dest_config['host'] == 'localhost'
        assert new_config_manager.dest_config['port'] == 993
        assert new_config_manager.dest_config['ssl'] == True
        assert new_config_manager.dest_config['passwords']['integration@localhost.com'] == 'integration_password'
        
        assert new_config_manager.oauth_config['client_id'] == 'test_client_id'
        assert new_config_manager.oauth_config['client_secret'] == 'test_client_secret'
        assert new_config_manager.oauth_config['tenant_id'] == 'common'
    
    def test_command_argument_validation_flow(self):
        """Test that commands validate arguments correctly"""
        
        # Test setup without required arguments
        with patch('sys.argv', ['email_sync.py', 'setup']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    with pytest.raises(SystemExit):  # Should exit due to missing required args
                        main()
        
        # Test add-account without required arguments
        with patch('sys.argv', ['email_sync.py', 'add-account']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    with pytest.raises(SystemExit):  # Should exit due to missing required args
                        main()
        
        # Test sync command works without additional arguments
        mock_config_manager = MagicMock()
        mock_config_manager.accounts = []
        mock_config_manager.dest_config = {}
        mock_config_manager.oauth_config = None
        
        with patch('sys.argv', ['email_sync.py', 'sync']):
            with patch('email_sync.ConfigManager', return_value=mock_config_manager):
                with patch('email_sync.SyncManager') as mock_sync_manager_class:
                    mock_sync_manager = MagicMock()
                    mock_sync_manager_class.return_value = mock_sync_manager
                    with patch('email_sync.setup_logging') as mock_logging:
                        mock_logging.return_value = MagicMock()
                        with patch('email_sync.signal_handler'):
                            try:
                                main()
                            except SystemExit:
                                pass
                            # Verify sync was called
                            mock_sync_manager.sync_accounts.assert_called_once()
