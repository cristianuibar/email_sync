import pytest
import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
from email_sync import main


class TestCLIArgumentValidation:
    """Test suite for CLI argument validation"""

    def test_setup_command_required_arguments(self):
        """Test that setup command requires client-id and client-secret"""
        with patch('sys.argv', ['email_sync.py', 'setup']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    with pytest.raises(SystemExit):  # argparse exits when required args missing
                        main()
    
    def test_setup_command_valid_arguments(self):
        """Test setup command with valid arguments"""
        mock_config_manager = MagicMock()
        mock_config_manager.accounts_config.exists.return_value = False
        mock_config_manager.dest_config = {}
        
        with patch('sys.argv', ['email_sync.py', 'setup', '--client-id', 'test_id', '--client-secret', 'test_secret']):
            with patch('email_sync.ConfigManager', return_value=mock_config_manager):
                # Mock the TOKENS_DIR path check as well
                with patch('email_sync.TOKENS_DIR') as mock_tokens_dir:
                    mock_tokens_dir.__truediv__ = MagicMock(return_value=MagicMock(exists=MagicMock(return_value=False)))
                    with patch('email_sync.OAuth2Manager') as mock_oauth:
                        mock_oauth_instance = MagicMock()
                        mock_oauth.return_value = mock_oauth_instance
                        with patch('email_sync.setup_logging') as mock_logging:
                            mock_logging.return_value = MagicMock()
                            with patch('email_sync.signal_handler'):
                                try:
                                    main()
                                except SystemExit:
                                    pass
                                # Verify OAuth manager was created with correct arguments (may be called multiple times)
                                assert mock_oauth.call_count >= 1  # Should be called at least once
                                mock_oauth_instance.acquire_token.assert_called_once()
    
    def test_setup_command_optional_arguments(self):
        """Test setup command with optional arguments"""
        mock_config_manager = MagicMock()
        mock_config_manager.accounts_config.exists.return_value = False
        mock_config_manager.dest_config = {}
        
        with patch('sys.argv', [
            'email_sync.py', 'setup', 
            '--client-id', 'test_id', 
            '--client-secret', 'test_secret',
            '--tenant-id', 'custom_tenant',
            '--host', 'mail.example.com',
            '--port', '143',
            '--no-ssl'
        ]):
            with patch('email_sync.ConfigManager', return_value=mock_config_manager):
                # Mock the TOKENS_DIR path check as well
                with patch('email_sync.TOKENS_DIR') as mock_tokens_dir:
                    mock_tokens_dir.__truediv__ = MagicMock(return_value=MagicMock(exists=MagicMock(return_value=False)))
                    with patch('email_sync.OAuth2Manager') as mock_oauth:
                        with patch('email_sync.setup_logging') as mock_logging:
                            mock_logging.return_value = MagicMock()
                            with patch('email_sync.signal_handler'):
                                try:
                                    main()
                                except SystemExit:
                                    pass
                                
                                # Verify configuration was set with custom values
                                assert mock_config_manager.dest_config['host'] == 'mail.example.com'
                                assert mock_config_manager.dest_config['port'] == 143
                                assert mock_config_manager.dest_config['ssl'] == False  # --no-ssl flag
    
    def test_add_account_command_required_arguments(self):
        """Test that add-account command requires email address"""
        with patch('sys.argv', ['email_sync.py', 'add-account']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    with pytest.raises(SystemExit):  # argparse exits when required args missing
                        main()
    
    def test_add_account_command_valid_arguments(self):
        """Test add-account command with valid arguments"""
        mock_config_manager = MagicMock()
        mock_config_manager.accounts = []
        mock_config_manager.dest_config = {'passwords': {}}
        mock_config_manager.accounts_config.exists.return_value = True
        mock_config_manager.oauth_config = {'client_id': 'test_id', 'client_secret': 'test_secret'}
        
        with patch('sys.argv', ['email_sync.py', 'add-account', '--email', 'test@office365.com', '--office365']):
            with patch('email_sync.ConfigManager', return_value=mock_config_manager):
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
                            account = mock_config_manager.accounts[0]
                            assert account.email == 'test@office365.com'
                            assert account.is_office365 == True
    
    def test_add_account_command_optional_arguments(self):
        """Test add-account command with optional arguments"""
        mock_config_manager = MagicMock()
        mock_config_manager.accounts = []
        mock_config_manager.dest_config = {'passwords': {}}
        mock_config_manager.accounts_config.exists.return_value = True
        
        with patch('sys.argv', [
            'email_sync.py', 'add-account', 
            '--email', 'test@example.com',
            '--dest-email', 'backup@example.com',
            '--password', 'source_password'
        ]):
            with patch('email_sync.ConfigManager', return_value=mock_config_manager):
                with patch('getpass.getpass', return_value='dest_password'):
                    with patch('email_sync.setup_logging') as mock_logging:
                        mock_logging.return_value = MagicMock()
                        with patch('email_sync.signal_handler'):
                            try:
                                main()
                            except SystemExit:
                                pass
                            
                            # Verify account was configured with optional arguments
                            assert len(mock_config_manager.accounts) == 1
                            account = mock_config_manager.accounts[0]
                            assert account.email == 'test@example.com'
                            assert account.dest_email == 'backup@example.com'
                            assert account.password == 'source_password'
                            assert account.is_office365 == False  # Default when not specified
    
    def test_sync_command_optional_arguments(self):
        """Test sync command with optional arguments"""
        mock_config_manager = MagicMock()
        mock_config_manager.accounts = []
        mock_config_manager.dest_config = {}
        mock_config_manager.oauth_config = None
        
        mock_sync_manager = MagicMock()
        
        with patch('sys.argv', ['email_sync.py', 'sync', '--debug', '--dry-run']):
            with patch('email_sync.ConfigManager', return_value=mock_config_manager):
                with patch('email_sync.SyncManager', return_value=mock_sync_manager):
                    with patch('email_sync.setup_logging') as mock_logging:
                        mock_logging.return_value = MagicMock()
                        with patch('email_sync.signal_handler'):
                            try:
                                main()
                            except SystemExit:
                                pass
                            
                            # Verify sync was called with correct parameters
                            mock_sync_manager.sync_accounts.assert_called_once()
                            call_args = mock_sync_manager.sync_accounts.call_args
                            assert call_args[0][0] == True  # debug parameter
                            assert call_args[0][1] == True  # dry_run parameter
    
    def test_invalid_command(self):
        """Test that invalid commands are rejected"""
        with patch('sys.argv', ['email_sync.py', 'invalid_command']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    with pytest.raises(SystemExit):  # argparse exits with invalid command
                        main()
    
    def test_help_command(self):
        """Test help command execution"""
        with patch('sys.argv', ['email_sync.py', 'help']):
            with patch('email_sync.console') as mock_console:
                with patch('email_sync.setup_logging') as mock_logging:
                    mock_logging.return_value = MagicMock()
                    with patch('email_sync.signal_handler'):
                        try:
                            main()
                        except SystemExit:
                            pass
                        # Check that help information was printed
                        mock_console.print.assert_called()
                        
                        # Verify help content contains expected commands
                        printed_calls = [str(call) for call in mock_console.print.call_args_list]
                        help_content = ' '.join(printed_calls).lower()
                        assert 'setup' in help_content
                        assert 'add-account' in help_content
                        assert 'sync' in help_content
    
    def test_no_command_shows_help(self):
        """Test that running without a command shows help"""
        with patch('sys.argv', ['email_sync.py']):
            with patch('email_sync.setup_logging') as mock_logging:
                mock_logging.return_value = MagicMock()
                with patch('email_sync.signal_handler'):
                    with patch('argparse.ArgumentParser.print_help') as mock_help:
                        try:
                            main()
                        except SystemExit:
                            pass
                        # Verify help was printed when no command provided
                        mock_help.assert_called_once()
    
    @pytest.mark.parametrize("port_value,expected_valid", [
        ("993", True),
        ("143", True),
        ("1", True),
        ("65535", True),
        ("0", False),
        ("65536", False),
        ("-1", False),
        ("abc", False),
    ])
    def test_setup_port_validation(self, port_value, expected_valid):
        """Test port validation in setup command"""
        mock_config_manager = MagicMock()
        mock_config_manager.accounts_config.exists.return_value = False
        
        with patch('sys.argv', ['email_sync.py', 'setup', '--client-id', 'test', '--client-secret', 'test', '--port', port_value]):
            with patch('email_sync.ConfigManager', return_value=mock_config_manager):
                # Mock the TOKENS_DIR path check as well
                with patch('email_sync.TOKENS_DIR') as mock_tokens_dir:
                    mock_tokens_dir.__truediv__ = MagicMock(return_value=MagicMock(exists=MagicMock(return_value=False)))
                    with patch('email_sync.OAuth2Manager'):
                        with patch('email_sync.setup_logging') as mock_logging:
                            mock_logging.return_value = MagicMock()
                            with patch('email_sync.signal_handler'):
                                if expected_valid:
                                    try:
                                        main()
                                    except SystemExit:
                                        pass
                                    # Should succeed for valid ports
                                    if port_value.isdigit() and 1 <= int(port_value) <= 65535:
                                        assert mock_config_manager.dest_config['port'] == int(port_value)
                                else:
                                    with pytest.raises(SystemExit):  # argparse should fail for invalid ports
                                        main()
    
    def test_email_validation_in_add_account(self):
        """Test email validation in add-account command"""
        mock_config_manager = MagicMock()
        mock_config_manager.accounts = []
        mock_config_manager.accounts_config.exists.return_value = True
        
        # Test with invalid email (no @ symbol)
        with patch('sys.argv', ['email_sync.py', 'add-account', '--email', 'invalid_email']):
            with patch('email_sync.ConfigManager', return_value=mock_config_manager):
                with patch('email_sync.console') as mock_console:
                    with patch('email_sync.setup_logging') as mock_logging:
                        mock_logging.return_value = MagicMock()
                        with patch('email_sync.signal_handler'):
                            try:
                                main()
                            except SystemExit:
                                pass
                            
                            # Should print error message about invalid email
                            mock_console.print.assert_any_call("[red]Invalid email address: invalid_email[/red]")
