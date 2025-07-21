import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from cryptography.fernet import Fernet

from rich.console import Console
from rich.prompt import Prompt, Confirm

console = Console()
logger = logging.getLogger(__name__)

class EmailAccount:
    def __init__(self, email: str, password: str = None, is_office365: bool = False, dest_email: str = None):
        self.email = email
        self.password = password
        self.is_office365 = is_office365
        self.dest_email = dest_email or email
        self.sync_stats = {
            'total_messages': 0,
            'synced_messages': 0,
            'failed_messages': 0,
            'last_sync': None
        }

    def to_dict(self):
        return {
            'email': self.email,
            'password': self.password,
            'is_office365': self.is_office365,
            'dest_email': self.dest_email,
            'sync_stats': self.sync_stats
        }

class ConfigManager:
    def __init__(self, script_dir: Path):
        self.script_dir = script_dir
        self.config_dir = script_dir / "config"
        self.tokens_dir = script_dir / "tokens"
        self.accounts_config = self.config_dir / "accounts.json"
        self.encryption_key_file = self.config_dir / "encryption.key"
        self.accounts: List[EmailAccount] = []
        self.dest_config: Dict = {}
        self.oauth_config: Dict = {}
        self._fernet = None
        self.load_encryption_key()
    
    def load_encryption_key(self):
        if self.encryption_key_file.exists():
            with open(self.encryption_key_file, 'rb') as f:
                key = f.read()
            self._fernet = Fernet(key)
        else:
            key = Fernet.generate_key()
            with open(self.encryption_key_file, 'wb') as f:
                f.write(key)
            os.chmod(self.encryption_key_file, 0o600)
            self._fernet = Fernet(key)
            logger.info("Generated new encryption key for sensitive data")
    
    def encrypt(self, data: str) -> str:
        return self._fernet.encrypt(data.encode()).decode()
    
    def decrypt(self, encrypted: str) -> str:
        try:
            decrypted = self._fernet.decrypt(encrypted.encode()).decode()
            # Check if result is still encrypted (double encryption case)
            if decrypted.startswith('gAAAAAB'):
                try:
                    return self._fernet.decrypt(decrypted.encode()).decode()
                except:
                    return decrypted  # Return single-decrypted if double decryption fails
            return decrypted
        except Exception as e:
            # Migration for legacy plain-text data
            logger.warning(f'Decryption failed (likely legacy plain text): {e}. Migrating to encrypted format.')
            return encrypted  # Treat as plain text for now
    
    def load_configuration(self, oauth_manager):
        self.accounts = []  # Clear before loading
        try:
            if self.accounts_config.exists():
                with open(self.accounts_config, 'r') as f:
                    config = json.load(f)
                self.dest_config = config.get('destination', {})
                if 'passwords' not in self.dest_config:
                    self.dest_config['passwords'] = {}
                # Decrypt passwords (with migration handling)
                needs_migration = False
                for email, pwd in list(self.dest_config['passwords'].items()):
                    if self._fernet is None:
                        raise ValueError("Encryption not initialized")
                    try:
                        decrypted = self.decrypt(pwd)
                    except:
                        needs_migration = True
                        decrypted = pwd  # Legacy plain text
                    self.dest_config['passwords'][email] = decrypted
                # Load oauth_config if present
                if 'oauth_config' in config:
                    oc = config['oauth_config']
                    if self._fernet is None:
                        raise ValueError("Encryption not initialized")
                    self.oauth_config = {
                        'client_id': oc['client_id'],
                        'client_secret': self.decrypt(oc['client_secret']),
                        'tenant_id': oc.get('tenant_id', 'common')
                    }
                # Similar for accounts
                for acc_data in config.get('accounts', []):
                    password = acc_data.get('password')
                    if password:
                        if self._fernet is None:
                            raise ValueError("Encryption not initialized")
                        try:
                            password = self.decrypt(password)
                        except:
                            needs_migration = True
                            password = password  # Legacy
                    account = EmailAccount(
                        acc_data['email'],
                        password,
                        acc_data.get('is_office365', False),
                        acc_data.get('dest_email')
                    )
                    account.sync_stats = acc_data.get('sync_stats', account.sync_stats)
                    self.accounts.append(account)
                # If migration needed, re-save with encryption
                if needs_migration:
                    console.print('[yellow]Migrating legacy configuration to encrypted format...[/yellow]')
                    self.save_configuration(oauth_manager)
                    console.print('[green]Migration complete! Configuration now encrypted.[/green]')
                logger.info(f'Loaded configuration with {len(self.accounts)} accounts')
        except Exception as e:
            logger.error(f'Error loading configuration: {e}')
    
    def save_configuration(self, oauth_manager):
        config = {
            'destination': self.dest_config,
            'accounts': [acc.to_dict() for acc in self.accounts]
        }
        # Encrypt passwords
        if 'passwords' in config['destination']:
            for email, pwd in config['destination']['passwords'].items():
                if self._fernet is None:
                    raise ValueError("Encryption not initialized")
                config['destination']['passwords'][email] = self.encrypt(pwd)
        for acc in config['accounts']:
            if acc.get('password'):
                if self._fernet is None:
                    raise ValueError("Encryption not initialized")
                acc['password'] = self.encrypt(acc['password'])
        # Save oauth_config if oauth_manager present
        if oauth_manager:
            if self._fernet is None:
                raise ValueError("Encryption not initialized")
            config['oauth_config'] = {
                'client_id': oauth_manager.client_id,
                'client_secret': self.encrypt(oauth_manager.client_secret),
                'tenant_id': oauth_manager.tenant_id
            }
        try:
            with open(self.accounts_config, 'w') as f:
                json.dump(config, f, indent=2)
            os.chmod(self.accounts_config, 0o600)
            logger.info("Configuration saved with encrypted sensitive data")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")

    def _clear_config_files(self):
        """Helper method to clear configuration files without prompting"""
        files_to_clear = []
        if self.accounts_config.exists():
            files_to_clear.append(self.accounts_config)
        oauth_tokens = self.tokens_dir / "oauth_tokens.json"
        if oauth_tokens.exists():
            files_to_clear.append(oauth_tokens)
        imap_tokens = self.tokens_dir / "imap_oauth_tokens.json"
        if imap_tokens.exists():
            files_to_clear.append(imap_tokens)
        for file_path in files_to_clear:
            try:
                file_path.unlink()
                logger.info(f"Cleared {file_path}")
            except Exception as e:
                logger.warning(f"Failed to clear {file_path}: {e}") 