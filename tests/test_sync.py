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