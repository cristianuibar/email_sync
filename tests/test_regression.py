#!/usr/bin/env python3
"""
Regression tests for email_sync.py command-line interface
Tests that setup, sync, status, clear, and help commands still work correctly
"""

import pytest
import subprocess
import tempfile
import shutil
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add the parent directory to sys.path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from email_sync import main
from config import ConfigManager, EmailAccount
from oauth import OAuth2Manager
from sync import SyncManager


class TestEmailSyncRegression:
    """Regression tests to ensure existing functionality is retained"""
    
    def setup_method(self):
        """Set up test environment for each test"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.script_dir = self.temp_dir / "email_sync"
        self.script_dir.mkdir()
        
        # Create subdirectories
        (self.script_dir / "config").mkdir()
        (self.script_dir / "tokens").mkdir()
        (self.script_dir / "logs").mkdir()
        
    def teardown_method(self):
        """Clean up after each test"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def test_help_command(self):
        """Test that help command works and shows expected information"""
        # Test help via argparse directly by mocking sys.argv
        with patch('sys.argv', ['email_sync.py', 'help']):
            with patch('email_sync.console') as mock_console:
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        try:
                            main()
                        except SystemExit:
                            pass
                        # Check that console.print was called with help information
                        assert mock_console.print.called
                        # Get all the print calls
                        calls = [str(call) for call in mock_console.print.call_args_list]
                        printed_text = ' '.join(calls).lower()
                        assert 'setup' in printed_text
                        assert 'sync' in printed_text
                        assert 'status' in printed_text
                        assert 'clear' in printed_text
                        assert 'help' in printed_text
    
    def test_status_command_no_accounts(self):
        """Test status command when no accounts are configured"""
        config_manager = ConfigManager(self.script_dir)
        
        with patch('sys.argv', ['email_sync.py', 'status']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        # This should not raise an exception
                        try:
                            main()
                        except SystemExit:
                            pass
    
    def test_status_command_with_accounts(self):
        """Test status command when accounts are configured"""
        config_manager = ConfigManager(self.script_dir)
        # Add a test account
        test_account = EmailAccount(
            email="test@example.com",
            is_office365=True
        )
        config_manager.accounts = [test_account]
        
        with patch('sys.argv', ['email_sync.py', 'status']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        # This should not raise an exception
                        try:
                            main()
                        except SystemExit:
                            pass
    
    def test_clear_command_confirmation_no(self):
        """Test clear command when user answers 'no' to confirmation"""
        config_manager = ConfigManager(self.script_dir)
        
        with patch('sys.argv', ['email_sync.py', 'clear']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        with patch('rich.prompt.Confirm.ask', return_value=False):
                            # This should not raise an exception
                            try:
                                main()
                            except SystemExit:
                                pass
    
    def test_clear_command_confirmation_yes(self):
        """Test clear command when user answers 'yes' to confirmation"""
        config_manager = ConfigManager(self.script_dir)
        config_manager._clear_config_files = MagicMock()
        
        with patch('sys.argv', ['email_sync.py', 'clear']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        with patch('rich.prompt.Confirm.ask', return_value=True):
                            # This should not raise an exception
                            try:
                                main()
                            except SystemExit:
                                pass
                            # Verify that clear was called
                            config_manager._clear_config_files.assert_called_once()
    
    def test_setup_command_no_existing_config(self):
        """Test setup command when no existing configuration exists"""
        config_manager = ConfigManager(self.script_dir)
        
        with patch('sys.argv', ['email_sync.py', 'setup']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        # Mock input to exit early from setup
                        with patch('builtins.input', side_effect=KeyboardInterrupt):
                            try:
                                main()
                            except (KeyboardInterrupt, SystemExit):
                                pass
    
    def test_setup_command_with_existing_config(self):
        """Test setup command when existing configuration is present"""
        config_manager = ConfigManager(self.script_dir)
        # Create existing config file
        accounts_config = self.script_dir / "config" / "accounts.json"
        accounts_config.write_text('{"accounts": []}')
        
        with patch('sys.argv', ['email_sync.py', 'setup']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        # Mock confirmation dialog to decline clearing config
                        with patch('rich.prompt.Confirm.ask', return_value=False):
                            try:
                                main()
                            except SystemExit:
                                pass
    
    def test_sync_command_dry_run(self):
        """Test sync command with dry-run option"""
        config_manager = ConfigManager(self.script_dir)
        oauth_manager = MagicMock(spec=OAuth2Manager)
        sync_manager = MagicMock(spec=SyncManager)
        
        with patch('sys.argv', ['email_sync.py', 'sync', '--dry-run']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.OAuth2Manager', return_value=oauth_manager):
                    with patch('email_sync.SyncManager', return_value=sync_manager):
                        with patch('email_sync.setup_logging') as mock_logging:
                            mock_logging.return_value = MagicMock()
                            with patch('email_sync.signal_handler'):
                                try:
                                    main()
                                except SystemExit:
                                    pass
                                # Verify sync was called with dry-run option
                                sync_manager.sync_accounts.assert_called_once()
                                args, kwargs = sync_manager.sync_accounts.call_args
                                assert len(args) >= 2
                                assert args[1] == True  # dry_run parameter
    
    def test_sync_command_debug(self):
        """Test sync command with debug option"""
        config_manager = ConfigManager(self.script_dir)
        oauth_manager = MagicMock(spec=OAuth2Manager)
        sync_manager = MagicMock(spec=SyncManager)
        
        with patch('sys.argv', ['email_sync.py', 'sync', '--debug']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.OAuth2Manager', return_value=oauth_manager):
                    with patch('email_sync.SyncManager', return_value=sync_manager):
                        with patch('email_sync.setup_logging') as mock_logging:
                            mock_logging.return_value = MagicMock()
                            with patch('email_sync.signal_handler'):
                                try:
                                    main()
                                except SystemExit:
                                    pass
                                # Verify sync was called with debug option
                                sync_manager.sync_accounts.assert_called_once()
                                args, kwargs = sync_manager.sync_accounts.call_args
                                assert len(args) >= 2
                                assert args[0] == True  # debug parameter
    
    def test_add_account_command(self):
        """Test add-account command"""
        config_manager = ConfigManager(self.script_dir)
        config_manager.load_configuration = MagicMock()
        config_manager.save_configuration = MagicMock()
        config_manager.accounts = []
        config_manager.dest_config = {}
        
        with patch('sys.argv', ['email_sync.py', 'add-account']):
            with patch('email_sync.ConfigManager', return_value=config_manager):
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        # Mock user inputs
                        inputs = [
                            "test@office365.com",  # source email
                            "dest@example.com",    # destination email
                            "password123"          # destination password
                        ]
                        with patch('builtins.input', side_effect=inputs):
                            with patch('getpass.getpass', return_value="password123"):
                                try:
                                    main()
                                except SystemExit:
                                    pass
                                # Verify account was added
                                assert len(config_manager.accounts) == 1
                                assert config_manager.accounts[0].email == "test@office365.com"
                                assert config_manager.accounts[0].is_office365 == True
                                config_manager.save_configuration.assert_called_once()
    
    def test_invalid_command(self):
        """Test that invalid commands are handled gracefully"""
        with patch('sys.argv', ['email_sync.py', 'invalid']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    with pytest.raises(SystemExit):  # argparse will exit with invalid command
                        main()


class TestConfigManagerRegression:
    """Regression tests for ConfigManager functionality"""
    
    def setup_method(self):
        """Set up test environment for each test"""
        self.temp_dir = Path(tempfile.mkdtemp())
        # Create required directories for ConfigManager
        (self.temp_dir / "config").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "tokens").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.config_manager = ConfigManager(self.temp_dir)
    
    def teardown_method(self):
        """Clean up after each test"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def test_load_empty_configuration(self):
        """Test loading configuration when no config file exists"""
        self.config_manager.load_configuration(None)
        assert len(self.config_manager.accounts) == 0
        assert self.config_manager.dest_config == {}
    
    def test_save_and_load_configuration(self):
        """Test saving and loading configuration"""
        # Add test account
        account = EmailAccount(
            email="test@example.com",
            password="test_password",
            is_office365=False
        )
        self.config_manager.accounts = [account]
        self.config_manager.dest_config = {
            'host': 'localhost',
            'port': 993,
            'ssl': True,
            'ssl_verify': True,
            'passwords': {'test@example.com': 'dest_password'}
        }
        
        # Save configuration
        self.config_manager.save_configuration(None)
        
        # Clear and reload
        self.config_manager.accounts = []
        self.config_manager.dest_config = {}
        self.config_manager.load_configuration(None)
        
        # Verify loaded correctly
        assert len(self.config_manager.accounts) == 1
        assert self.config_manager.accounts[0].email == "test@example.com"
        assert self.config_manager.dest_config['host'] == 'localhost'


class TestSyncManagerRegression:
    """Regression tests for SyncManager functionality"""
    
    def setup_method(self):
        """Set up test environment for each test"""
        self.temp_dir = Path(tempfile.mkdtemp())
        # Create required directories for ConfigManager
        (self.temp_dir / "config").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "tokens").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.temp_dir / "logs" / "imapsync").mkdir(parents=True, exist_ok=True)
        self.config_manager = ConfigManager(self.temp_dir)
        self.oauth_manager = MagicMock(spec=OAuth2Manager)
        self.sync_manager = SyncManager(
            self.config_manager,
            self.oauth_manager,
            self.temp_dir / "logs",
            self.temp_dir / "logs" / "imapsync",
            MagicMock(),
            []
        )
    
    def teardown_method(self):
        """Clean up after each test"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def test_connection_test_office365_valid_token(self):
        """Test connection test for Office 365 account with valid token"""
        account = EmailAccount(
            email="test@office365.com",
            is_office365=True
        )
        
        self.oauth_manager.get_valid_token.return_value = "valid_token"
        
        result = self.sync_manager.test_connection(account)
        assert result is True
    
    def test_connection_test_office365_invalid_token(self):
        """Test connection test for Office 365 account with invalid token"""
        account = EmailAccount(
            email="test@office365.com",
            is_office365=True
        )
        
        self.oauth_manager.get_valid_token.return_value = None
        
        result = self.sync_manager.test_connection(account)
        assert result is False
    
    def test_connection_test_non_office365_with_password(self):
        """Test connection test for non-Office 365 account with password"""
        account = EmailAccount(
            email="test@example.com",
            password="test_password",
            is_office365=False
        )
        
        result = self.sync_manager.test_connection(account)
        assert result is True
    
    def test_connection_test_non_office365_no_password(self):
        """Test connection test for non-Office 365 account without password"""
        account = EmailAccount(
            email="test@example.com",
            password=None,
            is_office365=False
        )
        
        result = self.sync_manager.test_connection(account)
        assert result is False


if __name__ == '__main__':
    pytest.main([__file__])
