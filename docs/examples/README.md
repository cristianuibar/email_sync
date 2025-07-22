# Email Sync Configuration Examples

This directory contains sample configuration files for the Email Sync tool. These files demonstrate different use cases and configuration patterns.

## Configuration Files

### 1. office365-config.json
**Use Case**: Single Office 365 account synchronization

This configuration shows:
- Office 365 account with OAuth2 authentication
- Local destination server (localhost)
- SSL enabled with certificate verification disabled
- OAuth configuration with client credentials

**Key Features**:
- `is_office365: true` - Enables OAuth2 authentication
- `password: null` - Office 365 accounts don't use password authentication
- OAuth client credentials stored encrypted

### 2. local-config.json
**Use Case**: Local email server synchronization

This configuration shows:
- Non-Office365 account with password authentication
- External destination server with SSL verification enabled
- No OAuth configuration required

**Key Features**:
- `is_office365: false` - Uses password authentication
- `ssl_verify: true` - Certificate verification enabled
- Source and destination passwords stored encrypted

### 3. multi-account-config.json
**Use Case**: Multiple accounts with mixed authentication types

This configuration shows:
- Mixed Office 365 and local accounts
- Different destination email addresses
- Sync statistics tracking
- Non-SSL destination server configuration

**Key Features**:
- Multiple accounts with different authentication methods
- Custom destination email mappings
- Historical sync statistics preserved
- Flexible destination server configuration

## Important Notes

### Security
All configuration files store sensitive data encrypted:
- Account passwords are encrypted using Fernet symmetric encryption
- Destination passwords are encrypted
- OAuth client secrets are encrypted
- Only `[ENCRYPTED_*_PLACEHOLDER]` values shown in examples

### File Structure
```json
{
  "accounts": [
    {
      "email": "source email address",
      "password": "encrypted password (null for Office 365)",
      "is_office365": true/false,
      "dest_email": "destination email address",
      "sync_stats": {
        "total_messages": 0,
        "synced_messages": 0,
        "failed_messages": 0,
        "last_sync": null
      }
    }
  ],
  "destination": {
    "host": "destination server hostname",
    "port": 993,
    "ssl": true,
    "ssl_verify": false,
    "passwords": {
      "dest_email": "encrypted destination password"
    }
  },
  "oauth_config": {
    "client_id": "Azure app client ID",
    "client_secret": "encrypted client secret",
    "tenant_id": "tenant ID or 'common'"
  }
}
```

### Field Descriptions

#### Account Fields
- `email`: Source email address to sync from
- `password`: Source account password (encrypted, null for Office 365)
- `is_office365`: Whether to use OAuth2 authentication
- `dest_email`: Destination email address (defaults to source email)
- `sync_stats`: Statistics tracking sync progress

#### Destination Fields  
- `host`: Destination IMAP server hostname
- `port`: IMAP server port (typically 993 for SSL, 143 for non-SSL)
- `ssl`: Whether to use SSL/TLS encryption
- `ssl_verify`: Whether to verify SSL certificates
- `passwords`: Map of destination email addresses to encrypted passwords

#### OAuth Fields (Office 365 only)
- `client_id`: Azure application client ID
- `client_secret`: Azure application client secret (encrypted)
- `tenant_id`: Azure tenant ID or "common" for multi-tenant

## Usage with Email Sync Tool

These configurations are automatically generated and managed by the email sync tool:

1. **Setup**: Run `setup` command to configure OAuth and destination server
2. **Add Accounts**: Use `add-account` command to add email accounts
3. **Sync**: Run `sync` command to synchronize emails

### Example Commands
```bash
# Initial setup
python3 email_sync.py setup --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET

# Add Office 365 account
python3 email_sync.py add-account --email user@office365.com --office365

# Add local account
python3 email_sync.py add-account --email user@company.com --password SOURCE_PASSWORD

# Start synchronization
python3 email_sync.py sync

# Dry run (test without changes)
python3 email_sync.py sync --dry-run
```

## Configuration Location
The actual configuration file is stored at:
```
config/accounts.json
```

## Backup and Migration
To backup your configuration:
1. Copy the entire `config/` directory
2. Copy the `tokens/` directory (contains OAuth tokens)
3. Store securely as it contains encrypted passwords

To migrate to a new system:
1. Restore the `config/` and `tokens/` directories
2. Ensure the same encryption key is used (stored in `config/encryption.key`)
3. Test with `--dry-run` before full sync
