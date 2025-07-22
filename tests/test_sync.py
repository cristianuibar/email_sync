import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from config import ConfigManager, EmailAccount
from email_sync import add_account

@pytest.fixture
def mock_config_manager():
    return MagicMock()

def test_add_account_with_mock_input(mock_config_manager):
    """Test add_account to ensure account is added and password is stored correctly"""
    mock_config_manager.accounts = []
    mock_config_manager.dest_config = {}
    mock_config_manager.load_configuration = MagicMock()
    mock_config_manager.save_configuration = MagicMock()
    
    # Mock user inputs
    inputs = [
        "test@office365.com",  # source email
        "dest@example.com",    # destination email
    ]
    with patch('builtins.input', side_effect=inputs):
        with patch('getpass.getpass', return_value="password123"):
            add_account(mock_config_manager)

    # Verify account was added
    assert len(mock_config_manager.accounts) == 1
    account = mock_config_manager.accounts[0]
    assert account.email == "test@office365.com"
    assert account.is_office365
    
    # Verify password is stored
    assert mock_config_manager.dest_config['passwords']["dest@example.com"] == "password123"
    
    # Verify that configuration was saved
    mock_config_manager.save_configuration.assert_called_once()

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from sync import SyncManager
# Add more imports as needed

@pytest.fixture
def mock_config_manager():
    return MagicMock()

@pytest.fixture
def mock_oauth_manager():
    return MagicMock()

def test_test_connection(mock_config_manager, mock_oauth_manager):
    sync_manager = SyncManager(mock_config_manager, mock_oauth_manager, Path(), Path(), MagicMock(), [])
    account = MagicMock(is_office365=True)
    mock_oauth_manager.get_valid_token.return_value = "valid_token"
    assert sync_manager.test_connection(account) == True

# Add more tests for retry logic, etc. 