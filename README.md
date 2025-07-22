# Enhanced Email Sync Script

A streamlined email synchronization tool with OAuth2 and password authentication support.

## Features

- **Mixed Authentication**: OAuth2 for Office 365, passwords for local accounts
- **Interactive Setup**: Easy wizard-based configuration
- **Progress Tracking**: Real-time progress bars and detailed logging
- **Secure Storage**: Encrypted credential storage
- **Multiple Accounts**: Support for multiple email accounts
- **Detailed Logging**: Comprehensive sync logs with statistics

## Quick Start

1. **Initial Setup**:
   ```bash
   python3 email_sync.py setup
   ```

2. **Start Synchronization**:
   ```bash
   python3 email_sync.py sync
   ```

3. **Check Status**:
   ```bash
   python3 email_sync.py status
   ```

4. **Add Additional Office 365 Account** (after initial setup):
   ```bash
   python3 email_sync.py add-account
   ```

## Commands

- `setup` - Run interactive setup wizard
- `sync` - Start synchronization
- `status` - Show current status
- `add-account` - Add a new Office 365 account to existing configuration
- `clear` - Clear all configuration files and tokens
- `help` - Show help message

## Configuration

The script will ask for:
- **Client ID** (Azure App Registration)
- **Client Secret** (Azure App Registration)
- **Email addresses** (comma-separated)
- **Passwords** (for local accounts only)
- **Destination server** settings

## Directory Structure

```
email_sync/
├── email_sync.py          # Main script
├── config/
│   └── accounts.json      # Account configurations
├── logs/
│   ├── sync.log          # Main log file
│   └── imapsync/         # Individual sync logs
└── tokens/
    └── oauth_tokens.json  # OAuth tokens storage
```

## Requirements

- Python 3.6+
- `imapsync` tool installed
- `requests` and `rich` Python packages

## Security

- All configuration files are stored with restricted permissions (600)
- OAuth tokens are automatically refreshed
- Passwords are stored securely in configuration files
- No credentials are logged or displayed in terminal

## Troubleshooting

1. Check logs in `logs/sync.log` for detailed error information
2. Verify OAuth2 setup in Azure portal
3. Ensure `imapsync` is installed and accessible
4. Check network connectivity to email servers

## Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install imapsync (system package):
   - On Ubuntu: `sudo apt install imapsync`
   - Or download from https://imapsync.lamiral.info/

## Adding Additional Accounts

After completing the initial setup, you can add additional Office 365 accounts without reconfiguring the entire system:

```bash
python3 email_sync.py add-account
```

The add-account command will prompt for:
- **Source Office 365 email address** - The Office 365 account you want to sync from
- **Destination email address** - Where the emails should be synced to (can be different from source)
- **Destination IMAP password** - Password for the destination account (input is hidden for security)

**Note:** The add-account command:
- Only supports Office 365 accounts (uses existing OAuth2 configuration)
- Requires that you have already completed the initial setup wizard
- Uses the existing destination server settings
- Does not require re-entering OAuth2 credentials

## New Features

- Encrypted storage for passwords and secrets
- Parallel account syncing (up to 4 concurrent)
- Dry-run mode: `python3 email_sync.py sync --dry-run`
- Retry logic for transient sync errors
- Unit tests: Run `pytest` in the project root

## Example Workflow

1. **Initial Setup** (configures OAuth2, destination server, and first accounts):
   ```bash
   python3 email_sync.py setup
   ```

2. **Add additional Office 365 accounts** (uses existing configuration):
   ```bash
   python3 email_sync.py add-account
   ```
   - Prompts: `user2@company.com` → `user2@destination.com` + password

3. **Add another account**:
   ```bash
   python3 email_sync.py add-account
   ```
   - Prompts: `user3@company.com` → `user3@destination.com` + password

4. **Check status of all accounts**:
   ```bash
   python3 email_sync.py status
   ```

5. **Start synchronization**:
   ```bash
   python3 email_sync.py sync
   ```

## Scheduling

To run sync every hour, add to crontab:
```bash
0 * * * * /usr/bin/python3 /path/to/email_sync.py sync
```

## License

This project is open source and available under the MIT License.
