import pytest
import json
from unittest.mock import patch, MagicMock
from config import ConfigManager, EmailAccount
from oauth import OAuth2Manager
import tempfile
import shutil
from pathlib import Path


class TestConfigReadWriteCycles:
    """Test suite for configuration read/write cycles"""
    
    def setup_method(self):
        """Set up test environment for each test"""
        self.temp_dir = Path(tempfile.mkdtemp())
        # Create required directories
        (self.temp_dir / "config").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "tokens").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "logs").mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        """Clean up after each test"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_basic_config_read_write_cycle(self):
        """Test that saving and loading configurations maintains data integrity"""
        config_manager = ConfigManager(self.temp_dir)
        config_manager.accounts = [EmailAccount(email='test@example.com', password='pass123')]
        config_manager.dest_config = {'host': 'localhost', 'port': 993, 'ssl': True}
        
        # Save the configuration
        config_manager.save_configuration(None)
        
        # Create a new ConfigManager and load the configuration
        new_config_manager = ConfigManager(self.temp_dir)
        new_config_manager.load_configuration(None)
        
        # Verify the accounts
        assert len(new_config_manager.accounts) == 1
        assert new_config_manager.accounts[0].email == 'test@example.com'
        assert new_config_manager.accounts[0].password == 'pass123'
        
        # Verify the destination configuration
        assert new_config_manager.dest_config['host'] == 'localhost'
        assert new_config_manager.dest_config['port'] == 993
        assert new_config_manager.dest_config['ssl'] == True

    def test_oauth_config_read_write_cycle(self):
        """Test saving and loading OAuth configuration"""
        config_manager = ConfigManager(self.temp_dir)
        
        # Create mock OAuth manager
        oauth_manager = MagicMock()
        oauth_manager.client_id = 'test_client_id'
        oauth_manager.client_secret = 'test_client_secret'
        oauth_manager.tenant_id = 'common'
        
        # Save configuration with OAuth manager
        config_manager.save_configuration(oauth_manager)
        
        # Load configuration
        new_config_manager = ConfigManager(self.temp_dir)
        new_config_manager.load_configuration(None)
        
        # Verify OAuth config was loaded
        assert new_config_manager.oauth_config['client_id'] == 'test_client_id'
        assert new_config_manager.oauth_config['client_secret'] == 'test_client_secret'
        assert new_config_manager.oauth_config['tenant_id'] == 'common'

    def test_password_encryption_in_storage(self):
        """Test that passwords are encrypted when stored"""
        config_manager = ConfigManager(self.temp_dir)
        
        # Add account with password
        account = EmailAccount(email='secure@example.com', password='secret_password')
        config_manager.accounts = [account]
        config_manager.dest_config = {'passwords': {'secure@example.com': 'dest_secret'}}
        
        # Save configuration
        config_manager.save_configuration(None)
        
        # Read raw configuration file
        with open(config_manager.accounts_config, 'r') as f:
            raw_config = json.load(f)
        
        # Verify passwords are encrypted (not plaintext)
        stored_account_password = raw_config['accounts'][0]['password']
        stored_dest_password = raw_config['destination']['passwords']['secure@example.com']
        
        assert stored_account_password != 'secret_password'
        assert stored_dest_password != 'dest_secret'
        assert stored_account_password.startswith('gAAAAAB')  # Fernet encryption prefix
        assert stored_dest_password.startswith('gAAAAAB')

    def test_multiple_accounts_read_write_cycle(self):
        """Test configuration with multiple accounts"""
        config_manager = ConfigManager(self.temp_dir)
        
        # Add multiple accounts
        accounts = [
            EmailAccount(email='user1@office365.com', is_office365=True, dest_email='user1@local.com'),
            EmailAccount(email='user2@example.com', password='pass2', is_office365=False, dest_email='user2@local.com'),
            EmailAccount(email='user3@company.com', password='pass3', is_office365=False)
        ]
        config_manager.accounts = accounts
        
        # Set destination configuration with passwords
        config_manager.dest_config = {
            'host': 'mail.local.com',
            'port': 143,
            'ssl': False,
            'ssl_verify': False,
            'passwords': {
                'user1@local.com': 'dest_pass1',
                'user2@local.com': 'dest_pass2',
                'user3@company.com': 'dest_pass3'
            }
        }
        
        # Save configuration
        config_manager.save_configuration(None)
        
        # Load configuration with new manager
        new_config_manager = ConfigManager(self.temp_dir)
        new_config_manager.load_configuration(None)
        
        # Verify all accounts were loaded correctly
        assert len(new_config_manager.accounts) == 3
        
        # Verify first account (Office 365)
        account1 = new_config_manager.accounts[0]
        assert account1.email == 'user1@office365.com'
        assert account1.is_office365 == True
        assert account1.dest_email == 'user1@local.com'
        assert account1.password is None  # Office 365 accounts don't have passwords
        
        # Verify second account
        account2 = new_config_manager.accounts[1]
        assert account2.email == 'user2@example.com'
        assert account2.password == 'pass2'
        assert account2.is_office365 == False
        assert account2.dest_email == 'user2@local.com'
        
        # Verify third account
        account3 = new_config_manager.accounts[2]
        assert account3.email == 'user3@company.com'
        assert account3.password == 'pass3'
        assert account3.is_office365 == False
        assert account3.dest_email == 'user3@company.com'  # Defaults to source email
        
        # Verify destination configuration
        assert new_config_manager.dest_config['host'] == 'mail.local.com'
        assert new_config_manager.dest_config['port'] == 143
        assert new_config_manager.dest_config['ssl'] == False
        assert new_config_manager.dest_config['ssl_verify'] == False
        
        # Verify destination passwords
        dest_passwords = new_config_manager.dest_config['passwords']
        assert dest_passwords['user1@local.com'] == 'dest_pass1'
        assert dest_passwords['user2@local.com'] == 'dest_pass2'
        assert dest_passwords['user3@company.com'] == 'dest_pass3'

    def test_sync_stats_persistence(self):
        """Test that sync statistics are persisted correctly"""
        config_manager = ConfigManager(self.temp_dir)
        
        # Create account with sync statistics
        account = EmailAccount(email='stats@example.com', password='pass')
        account.sync_stats = {
            'total_messages': 1500,
            'synced_messages': 1200,
            'failed_messages': 5,
            'last_sync': '2023-12-01T10:30:00'
        }
        config_manager.accounts = [account]
        
        # Save configuration
        config_manager.save_configuration(None)
        
        # Load configuration
        new_config_manager = ConfigManager(self.temp_dir)
        new_config_manager.load_configuration(None)
        
        # Verify sync stats were preserved
        loaded_account = new_config_manager.accounts[0]
        assert loaded_account.sync_stats['total_messages'] == 1500
        assert loaded_account.sync_stats['synced_messages'] == 1200
        assert loaded_account.sync_stats['failed_messages'] == 5
        assert loaded_account.sync_stats['last_sync'] == '2023-12-01T10:30:00'

    def test_empty_config_read_write(self):
        """Test reading and writing empty configurations"""
        config_manager = ConfigManager(self.temp_dir)
        
        # Save empty configuration
        config_manager.save_configuration(None)
        
        # Load configuration
        new_config_manager = ConfigManager(self.temp_dir)
        new_config_manager.load_configuration(None)
        
        # Verify empty state is maintained
        assert len(new_config_manager.accounts) == 0
        assert new_config_manager.dest_config.get('passwords', {}) == {}
        assert new_config_manager.oauth_config == {}

    def test_config_file_permissions(self):
        """Test that configuration files have correct permissions"""
        config_manager = ConfigManager(self.temp_dir)
        
        # Save configuration
        config_manager.save_configuration(None)
        
        # Check file permissions (should be 0o600 for security)
        import stat
        file_stat = config_manager.accounts_config.stat()
        file_mode = stat.filemode(file_stat.st_mode)
        
        # On Unix systems, should be -rw------- (owner read/write only)
        # We'll check that group and others don't have permissions
        assert not (file_stat.st_mode & stat.S_IRGRP)  # No group read
        assert not (file_stat.st_mode & stat.S_IWGRP)  # No group write
        assert not (file_stat.st_mode & stat.S_IROTH)  # No others read
        assert not (file_stat.st_mode & stat.S_IWOTH)  # No others write

    def test_corrupted_config_handling(self):
        """Test handling of corrupted configuration files"""
        config_manager = ConfigManager(self.temp_dir)
        
        # Create corrupted JSON file
        with open(config_manager.accounts_config, 'w') as f:
            f.write('{ invalid json content }')
        
        # Should not crash when loading corrupted config
        config_manager.load_configuration(None)
        
        # Should have empty configuration after failed load
        assert len(config_manager.accounts) == 0
        assert config_manager.dest_config == {}

    def test_migration_from_legacy_format(self):
        """Test migration from legacy configuration format"""
        config_manager = ConfigManager(self.temp_dir)
        
        # Create legacy format configuration (unencrypted passwords)
        legacy_config = {
            'accounts': [{
                'email': 'legacy@example.com',
                'password': 'plain_text_password',  # Not encrypted
                'is_office365': False,
                'dest_email': 'legacy@local.com',
                'sync_stats': {
                    'total_messages': 100,
                    'synced_messages': 95,
                    'failed_messages': 0,
                    'last_sync': None
                }
            }],
            'destination': {
                'host': 'localhost',
                'port': 993,
                'ssl': True,
                'ssl_verify': False,
                'passwords': {
                    'legacy@local.com': 'plain_dest_password'  # Not encrypted
                }
            }
        }
        
        # Write legacy configuration
        with open(config_manager.accounts_config, 'w') as f:
            json.dump(legacy_config, f, indent=2)
        
        # Load configuration (should trigger migration)
        with patch('rich.console.Console.print'):  # Suppress migration messages
            config_manager.load_configuration(None)
        
        # Verify data was loaded correctly
        assert len(config_manager.accounts) == 1
        account = config_manager.accounts[0]
        assert account.email == 'legacy@example.com'
        assert account.password == 'plain_text_password'
        assert account.is_office365 == False
        assert account.dest_email == 'legacy@local.com'
        
        # Verify destination config
        assert config_manager.dest_config['host'] == 'localhost'
        assert config_manager.dest_config['passwords']['legacy@local.com'] == 'plain_dest_password'
        
        # Read raw file to verify passwords are now encrypted
        with open(config_manager.accounts_config, 'r') as f:
            migrated_config = json.load(f)
        
        # Passwords should now be encrypted
        stored_account_password = migrated_config['accounts'][0]['password']
        stored_dest_password = migrated_config['destination']['passwords']['legacy@local.com']
        
        assert stored_account_password.startswith('gAAAAAB')
        assert stored_dest_password.startswith('gAAAAAB')

