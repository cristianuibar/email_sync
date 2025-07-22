# New Configuration Schema Design

## Overview

This document outlines the new configuration schema that splits the current monolithic configuration into two distinct sections:

1. **Global Configuration** - Contains OAuth and destination server settings (managed by `setup`)
2. **Accounts Configuration** - Contains individual user account data (managed by `add-account`)

## Current Configuration Structure

The current system stores everything in a single `config/accounts.json` file:

```json
{
  "destination": {
    "host": "localhost",
    "port": 993,
    "ssl": true,
    "ssl_verify": false,
    "passwords": {
      "user1@dest.com": "encrypted_password1",
      "user2@dest.com": "encrypted_password2"
    }
  },
  "oauth_config": {
    "client_id": "azure_app_id",
    "client_secret": "encrypted_client_secret",
    "tenant_id": "common"
  },
  "accounts": [
    {
      "email": "user1@office365.com",
      "password": null,
      "is_office365": true,
      "dest_email": "user1@dest.com",
      "sync_stats": {...}
    }
  ]
}
```

## New Configuration Schema

### 1. Global Configuration File: `config/global.json`

**Purpose**: Stores system-wide settings that are shared across all accounts
**Managed by**: `setup` command
**Contents**:

```json
{
  "version": "2.0",
  "created_at": "2024-01-15T10:30:00Z",
  "last_updated": "2024-01-15T10:30:00Z",
  "oauth": {
    "client_id": "azure_app_id",
    "client_secret": "encrypted_client_secret",
    "tenant_id": "common",
    "redirect_uri": "http://localhost:8080/callback",
    "scopes": [
      "https://outlook.office365.com/IMAP.AccessAsUser.All",
      "offline_access"
    ]
  },
  "destination": {
    "host": "localhost",
    "port": 993,
    "ssl": true,
    "ssl_verify": false,
    "connection_timeout": 30,
    "max_retries": 3
  },
  "sync": {
    "batch_size": 100,
    "max_concurrent": 4,
    "dry_run_default": false,
    "log_level": "INFO"
  }
}
```

### 2. Accounts Configuration File: `config/accounts.json`

**Purpose**: Stores individual user account configurations
**Managed by**: `add-account` command
**Contents**:

```json
{
  "version": "2.0",
  "accounts": {
    "user1@office365.com": {
      "id": "acc_001",
      "email": "user1@office365.com",
      "dest_email": "user1@dest.com",
      "dest_password": "encrypted_password1",
      "auth_type": "oauth2",
      "source_password": null,
      "is_office365": true,
      "enabled": true,
      "created_at": "2024-01-15T10:30:00Z",
      "last_updated": "2024-01-15T10:30:00Z",
      "sync_stats": {
        "total_messages": 0,
        "synced_messages": 0,
        "failed_messages": 0,
        "last_sync": null,
        "last_success": null,
        "last_error": null
      },
      "sync_settings": {
        "folders": ["INBOX", "Sent", "Drafts"],
        "exclude_folders": ["Junk", "Deleted"],
        "date_range_days": 90,
        "delete_duplicates": true
      }
    },
    "user2@local.com": {
      "id": "acc_002",
      "email": "user2@local.com",
      "dest_email": "user2@dest.com",
      "dest_password": "encrypted_password2",
      "auth_type": "password",
      "source_password": "encrypted_source_password",
      "is_office365": false,
      "enabled": true,
      "created_at": "2024-01-15T11:00:00Z",
      "last_updated": "2024-01-15T11:00:00Z",
      "sync_stats": {...},
      "sync_settings": {...}
    }
  }
}
```

## File Layout and Locations

```
email_sync/
├── config/
│   ├── global.json         # Global configuration (setup command)
│   ├── accounts.json       # Accounts configuration (add-account command)
│   └── encryption.key      # Encryption key (existing)
├── tokens/
│   └── oauth_tokens.json   # OAuth tokens (existing)
└── logs/
    └── sync.log            # Logs (existing)
```

## Configuration Management

### Setup Command Responsibilities
- Creates/updates `config/global.json`
- Initializes OAuth configuration
- Sets up destination server settings
- Configures global sync parameters
- Can optionally create initial accounts

### Add-Account Command Responsibilities
- Reads `config/global.json` for validation
- Creates/updates `config/accounts.json`
- Adds individual account entries
- Manages account-specific settings
- Validates account uniqueness

## Validation Rules

### Global Configuration Validation
```python
GLOBAL_CONFIG_SCHEMA = {
    "version": {"type": "string", "required": True},
    "oauth": {
        "client_id": {"type": "string", "required": True, "min_length": 1},
        "client_secret": {"type": "string", "required": True, "min_length": 1},
        "tenant_id": {"type": "string", "default": "common"}
    },
    "destination": {
        "host": {"type": "string", "required": True},
        "port": {"type": "integer", "min": 1, "max": 65535, "default": 993},
        "ssl": {"type": "boolean", "default": True},
        "ssl_verify": {"type": "boolean", "default": False}
    }
}
```

### Accounts Configuration Validation
```python
ACCOUNTS_CONFIG_SCHEMA = {
    "version": {"type": "string", "required": True},
    "accounts": {
        "type": "dict",
        "key_schema": {"type": "string", "format": "email"},
        "value_schema": {
            "email": {"type": "string", "format": "email", "required": True},
            "dest_email": {"type": "string", "format": "email", "required": True},
            "dest_password": {"type": "string", "required": True, "encrypted": True},
            "auth_type": {"type": "string", "allowed": ["oauth2", "password"]},
            "enabled": {"type": "boolean", "default": True}
        }
    }
}
```

## Migration Strategy

### Phase 1: Backward Compatibility
1. Keep existing `accounts.json` format working
2. Add detection logic to identify old vs new format
3. Provide automatic migration utility

### Phase 2: Gradual Migration
1. Update `setup` command to create new format
2. Update `add-account` command to work with new format
3. Maintain read compatibility with old format

### Phase 3: Complete Migration
1. Remove old format support
2. Clean up migration code
3. Update documentation

## Benefits of New Schema

### Separation of Concerns
- **Global settings** are managed separately from **user accounts**
- Setup wizard only deals with system-wide configuration
- Account management is isolated and simpler

### Improved Security
- OAuth credentials separated from account data
- Different access patterns for different data types
- Granular encryption of sensitive fields

### Better Scalability
- Easier to add new global settings
- Account data can grow independently
- Easier to implement account-specific features

### Enhanced Maintainability
- Clear ownership of configuration sections
- Easier testing of individual components
- Reduced complexity in each configuration manager

## Implementation Classes

### GlobalConfigManager
```python
class GlobalConfigManager:
    def __init__(self, config_dir: Path):
        self.global_config_file = config_dir / "global.json"
        
    def load_global_config(self) -> GlobalConfig
    def save_global_config(self, config: GlobalConfig)
    def validate_global_config(self, config: dict) -> bool
    def migrate_from_legacy(self, legacy_config: dict)
```

### AccountsConfigManager  
```python
class AccountsConfigManager:
    def __init__(self, config_dir: Path):
        self.accounts_config_file = config_dir / "accounts.json"
        
    def load_accounts_config(self) -> AccountsConfig
    def save_accounts_config(self, config: AccountsConfig)
    def add_account(self, account: EmailAccount)
    def remove_account(self, email: str)
    def validate_accounts_config(self, config: dict) -> bool
```

## File Permissions and Security

- `config/global.json`: `0o600` (read/write owner only)
- `config/accounts.json`: `0o600` (read/write owner only)  
- `config/encryption.key`: `0o600` (existing, unchanged)

All sensitive fields (passwords, client_secret) will be encrypted using the existing Fernet encryption system.

## Error Handling

### Missing Configuration Files
- If `global.json` is missing → prompt user to run `setup`
- If `accounts.json` is missing → create empty accounts structure
- If both missing → first-time setup flow

### Invalid Configuration  
- Schema validation on load
- Graceful degradation where possible
- Clear error messages with remediation steps

### Migration Errors
- Backup original files before migration
- Rollback capability on migration failure
- Detailed logging of migration process

This schema provides a clean separation between global system settings and individual account configurations, making the system more maintainable and easier to extend in the future.
