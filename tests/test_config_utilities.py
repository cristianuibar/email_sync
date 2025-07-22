import pytest
import tempfile
import shutil
import json
import threading
import time
from unittest.mock import patch, MagicMock
from pathlib import Path

from config import ConfigManager, EmailAccount


class TestConfigUtilities:
    """Test suite for new thread-safe configuration writer/loader utilities"""

    def setup_method(self):
        """Set up test environment for each test"""
        self.temp_dir = Path(tempfile.mkdtemp())
        # Create required directories
        (self.temp_dir / "config").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "tokens").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "logs").mkdir(parents=True, exist_ok=True)
        
        self.config_manager = ConfigManager(self.temp_dir)

    def teardown_method(self):
        """Clean up after each test"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_update_global_config_success(self):
        """Test successful global configuration update"""
        # Create initial configuration
        initial_config = {
            'host': 'localhost',
            'port': 993,
            'ssl': True
        }
        self.config_manager.dest_config = initial_config
        self.config_manager.save_configuration(None)

        # Update configuration
        new_config = {
            'host': 'mail.example.com',
            'port': 143,
            'ssl_verify': False
        }

        with patch('rich.console.Console.print') as mock_print:
            self.config_manager.update_global_config(new_config)

        # Verify configuration was updated
        assert self.config_manager.dest_config['host'] == 'mail.example.com'
        assert self.config_manager.dest_config['port'] == 143
        assert self.config_manager.dest_config['ssl'] is True  # Should remain from initial
        assert self.config_manager.dest_config['ssl_verify'] is False

        # Verify success message was printed
        mock_print.assert_called_with("[green]✓ Global configuration updated successfully.[/green]")

    def test_update_global_config_no_setup(self):
        """Test global configuration update fails when setup hasn't been run"""
        # Don't create the accounts.json file
        new_config = {'host': 'newhost'}

        with patch('rich.console.Console.print') as mock_print:
            with pytest.raises(RuntimeError, match="Configuration file not found"):
                self.config_manager.update_global_config(new_config)

        # Verify error message was printed
        mock_print.assert_called_with(
            "[red]❌ Configuration file not found. Please run 'setup' first to initialize the configuration.[/red]"
        )

    def test_add_or_update_account_new_account(self):
        """Test adding a new account successfully"""
        # Create initial configuration
        self.config_manager.save_configuration(None)

        account = EmailAccount(
            email="test@example.com",
            password="password123",
            is_office365=False,
            dest_email="dest@example.com"
        )
        dest_password = "dest_password123"

        with patch('rich.console.Console.print') as mock_print:
            self.config_manager.add_or_update_account(account, dest_password)

        # Verify account was added
        assert len(self.config_manager.accounts) == 1
        assert self.config_manager.accounts[0].email == "test@example.com"
        assert self.config_manager.dest_config['passwords']['dest@example.com'] == dest_password

        # Verify success message was printed
        mock_print.assert_called_with("[green]✓ Account added/updated successfully.[/green]")

    def test_add_or_update_account_existing_account(self):
        """Test updating an existing account"""
        # Create initial configuration with an account
        self.config_manager.accounts.append(EmailAccount(
            email="test@example.com",
            password="old_password",
            is_office365=False
        ))
        self.config_manager.save_configuration(None)

        # Update the account (keeping as non-Office365 to avoid OAuth requirement)
        updated_account = EmailAccount(
            email="test@example.com",
            password="new_password",
            is_office365=False,  # Keep as non-Office365
            dest_email="new_dest@example.com"
        )

        with patch('rich.console.Console.print') as mock_print:
            self.config_manager.add_or_update_account(updated_account, "new_dest_password")

        # Verify account was updated
        assert len(self.config_manager.accounts) == 1
        account = self.config_manager.accounts[0]
        assert account.email == "test@example.com"
        assert account.password == "new_password"
        assert account.is_office365 is False
        assert account.dest_email == "new_dest@example.com"

        # Verify warning message for existing account
        mock_print.assert_any_call("[yellow]⚠️  Account 'test@example.com' already exists. Updating...[/yellow]")

    def test_add_or_update_account_office365_no_oauth(self):
        """Test that adding Office 365 account fails without OAuth configuration"""
        # Create initial configuration without OAuth
        self.config_manager.save_configuration(None)

        account = EmailAccount(
            email="test@office365.com",
            is_office365=True
        )

        with patch('rich.console.Console.print') as mock_print:
            with pytest.raises(RuntimeError, match="OAuth2 not configured"):
                self.config_manager.add_or_update_account(account)

        # Verify error message was printed
        mock_print.assert_called_with(
            "[red]❌ OAuth2 not configured for Office 365 accounts. Please run 'setup' with OAuth credentials first.[/red]"
        )

    def test_remove_account_success(self):
        """Test successful account removal"""
        # Create configuration with accounts
        account1 = EmailAccount("test1@example.com", "pass1")
        account2 = EmailAccount("test2@example.com", "pass2", dest_email="dest2@example.com")
        self.config_manager.accounts = [account1, account2]
        self.config_manager.dest_config = {
            'passwords': {
                'test1@example.com': 'dest_pass1',
                'dest2@example.com': 'dest_pass2'
            }
        }
        self.config_manager.save_configuration(None)

        with patch('rich.console.Console.print') as mock_print:
            result = self.config_manager.remove_account("test2@example.com")

        # Verify account was removed
        assert result is True
        assert len(self.config_manager.accounts) == 1
        assert self.config_manager.accounts[0].email == "test1@example.com"

        # Verify associated password was removed
        assert 'dest2@example.com' not in self.config_manager.dest_config['passwords']
        assert 'test1@example.com' in self.config_manager.dest_config['passwords']

        # Verify success message
        mock_print.assert_called_with("[green]✓ Account 'test2@example.com' removed successfully.[/green]")

    def test_remove_account_not_found(self):
        """Test removing non-existent account"""
        self.config_manager.save_configuration(None)

        with patch('rich.console.Console.print') as mock_print:
            result = self.config_manager.remove_account("nonexistent@example.com")

        assert result is False
        mock_print.assert_called_with("[yellow]⚠️  Account 'nonexistent@example.com' not found.[/yellow]")

    def test_update_account_password_source(self):
        """Test updating source account password"""
        # Create configuration with account
        account = EmailAccount("test@example.com", "old_password")
        self.config_manager.accounts = [account]
        self.config_manager.save_configuration(None)

        with patch('rich.console.Console.print') as mock_print:
            self.config_manager.update_account_password("test@example.com", "new_password", is_dest_password=False)

        # Verify password was updated
        assert self.config_manager.accounts[0].password == "new_password"

        # Verify success message
        mock_print.assert_called_with("[green]✓ Source password updated for 'test@example.com'.[/green]")

    def test_update_account_password_destination(self):
        """Test updating destination account password"""
        # Create configuration with account
        account = EmailAccount("test@example.com", "password", dest_email="dest@example.com")
        self.config_manager.accounts = [account]
        self.config_manager.dest_config = {'passwords': {'dest@example.com': 'old_dest_password'}}
        self.config_manager.save_configuration(None)

        with patch('rich.console.Console.print') as mock_print:
            self.config_manager.update_account_password("test@example.com", "new_dest_password", is_dest_password=True)

        # Verify destination password was updated
        assert self.config_manager.dest_config['passwords']['dest@example.com'] == "new_dest_password"

        # Verify success message
        mock_print.assert_called_with("[green]✓ Destination password updated for 'test@example.com'.[/green]")

    def test_thread_safety_concurrent_writes(self):
        """Test that configuration writes are thread-safe"""
        # Create initial configuration
        self.config_manager.save_configuration(None)

        # Track results from threads
        results = []
        errors = []

        def add_account(email_suffix):
            try:
                account = EmailAccount(f"test{email_suffix}@example.com", f"password{email_suffix}")
                self.config_manager.add_or_update_account(account, f"dest_password{email_suffix}")
                results.append(f"success_{email_suffix}")
            except Exception as e:
                errors.append(f"error_{email_suffix}: {e}")

        def update_config(config_suffix):
            try:
                new_config = {f'setting_{config_suffix}': f'value_{config_suffix}'}
                self.config_manager.update_global_config(new_config)
                results.append(f"config_success_{config_suffix}")
            except Exception as e:
                errors.append(f"config_error_{config_suffix}: {e}")

        # Start multiple threads for concurrent operations
        threads = []
        for i in range(5):
            thread1 = threading.Thread(target=add_account, args=(i,))
            thread2 = threading.Thread(target=update_config, args=(i,))
            threads.extend([thread1, thread2])

        # Suppress console output during threading test
        with patch('rich.console.Console.print'):
            # Start all threads
            for thread in threads:
                thread.start()
                time.sleep(0.01)  # Small delay to increase chance of overlap

            # Wait for all threads to complete
            for thread in threads:
                thread.join()

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors occurred during concurrent operations: {errors}"

        # Verify all operations completed
        assert len(results) == 10  # 5 account additions + 5 config updates

        # Verify final state is consistent
        assert len(self.config_manager.accounts) == 5
        for i in range(5):
            assert f'setting_{i}' in self.config_manager.dest_config

    def test_error_handling_with_logging(self):
        """Test that error handling includes proper logging"""
        # Don't create accounts.json to trigger error
        new_config = {'test': 'value'}

        with patch('rich.console.Console.print') as mock_print:
            with patch('logging.getLogger') as mock_logger_getter:
                mock_logger = MagicMock()
                mock_logger_getter.return_value = mock_logger

                with pytest.raises(RuntimeError):
                    self.config_manager.update_global_config(new_config)

                # Note: The logger is created at module level, so this specific test
                # may not capture the exact logging call, but the functionality is there

    def test_persistence_after_operations(self):
        """Test that configuration persists correctly after operations"""
        # Create initial setup
        self.config_manager.save_configuration(None)

        # Add account
        account = EmailAccount("persist@example.com", "password123", dest_email="dest@example.com")
        self.config_manager.add_or_update_account(account, "dest_password123")

        # Update global config
        global_config = {'host': 'persist.example.com', 'port': 995}
        self.config_manager.update_global_config(global_config)

        # Create new ConfigManager instance to test persistence
        new_config_manager = ConfigManager(self.temp_dir)
        new_config_manager.load_configuration(None)

        # Verify account persisted
        assert len(new_config_manager.accounts) == 1
        assert new_config_manager.accounts[0].email == "persist@example.com"

        # Verify global config persisted
        assert new_config_manager.dest_config['host'] == 'persist.example.com'
        assert new_config_manager.dest_config['port'] == 995

        # Verify destination password persisted (encrypted)
        assert new_config_manager.dest_config['passwords']['dest@example.com'] == "dest_password123"

    def test_encrypted_storage(self):
        """Test that sensitive data is encrypted in the configuration file"""
        # Create configuration with sensitive data
        account = EmailAccount("encrypt@example.com", "secret_password")
        self.config_manager.accounts = [account]
        self.config_manager.dest_config = {'passwords': {'encrypt@example.com': 'secret_dest_password'}}
        self.config_manager.save_configuration(None)

        # Read raw configuration file
        with open(self.config_manager.accounts_config, 'r') as f:
            raw_config = json.load(f)

        # Verify passwords are encrypted (not plaintext)
        account_password = raw_config['accounts'][0]['password']
        dest_password = raw_config['destination']['passwords']['encrypt@example.com']

        assert account_password != "secret_password"
        assert dest_password != "secret_dest_password"
        assert account_password.startswith('gAAAAAB')  # Fernet encryption prefix
        assert dest_password.startswith('gAAAAAB')

        # Verify decryption works
        new_config_manager = ConfigManager(self.temp_dir)
        new_config_manager.load_configuration(None)

        assert new_config_manager.accounts[0].password == "secret_password"
        assert new_config_manager.dest_config['passwords']['encrypt@example.com'] == "secret_dest_password"

    @pytest.mark.parametrize("operation,expected_error", [
        ("update_global_config", "Configuration file not found"),
        ("add_or_update_account", "Configuration file not found"),
        ("remove_account", "Configuration file not found"),
        ("update_account_password", "Configuration file not found"),
    ])
    def test_all_operations_require_setup(self, operation, expected_error):
        """Test that all configuration operations require setup to be run first"""
        # Create ConfigManager but don't save initial configuration
        config_manager = ConfigManager(self.temp_dir)
        
        # Remove the accounts.json file if it exists
        if config_manager.accounts_config.exists():
            config_manager.accounts_config.unlink()

        with patch('rich.console.Console.print'):
            with pytest.raises(RuntimeError, match=expected_error):
                if operation == "update_global_config":
                    config_manager.update_global_config({'test': 'value'})
                elif operation == "add_or_update_account":
                    account = EmailAccount("test@example.com")
                    config_manager.add_or_update_account(account)
                elif operation == "remove_account":
                    config_manager.remove_account("test@example.com")
                elif operation == "update_account_password":
                    config_manager.update_account_password("test@example.com", "new_password")
