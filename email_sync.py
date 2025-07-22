#!/usr/bin/env python3
"""
Enhanced Email Sync Script
Streamlined email synchronization with OAuth2 and password authentication
"""

import json
import os
import sys
import time
import subprocess
import getpass
import threading
import signal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import requests
import base64
import urllib.parse
import webbrowser
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from rich.console import Console
from rich.progress import Progress, TaskID, track
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.logging import RichHandler
from rich.live import Live
from rich.layout import Layout
from rich.align import Align
from rich.status import Status
import ssl
import imaplib

import argparse
import getpass
import threading
import webbrowser
from datetime import datetime

from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from config import ConfigManager, EmailAccount
from oauth import OAuth2Manager
from sync import SyncManager
from utils import setup_logging, signal_handler

# Configuration
SCRIPT_DIR = Path(__file__).parent
CONFIG_DIR = SCRIPT_DIR / "config"
LOGS_DIR = SCRIPT_DIR / "logs"
TOKENS_DIR = SCRIPT_DIR / "tokens"
IMAPSYNC_LOGS_DIR = LOGS_DIR / "imapsync"

# Ensure directories exist
for dir_path in [CONFIG_DIR, LOGS_DIR, TOKENS_DIR, IMAPSYNC_LOGS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Files
ACCOUNTS_CONFIG = CONFIG_DIR / "accounts.json"
SYNC_LOG = LOGS_DIR / "sync.log"
OAUTH_TOKENS = TOKENS_DIR / "oauth_tokens.json"

# Office 365 OAuth2 Configuration
OAUTH_CONFIG = {
    "tenant_id": "common",  # Will be updated with user input
    "redirect_uri": os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8080/callback"),
    "scopes": [
        "https://outlook.office365.com/IMAP.AccessAsUser.All",
        "offline_access"
    ]
}

# Console setup
console = Console()

# Global variables for graceful shutdown
shutdown_event = threading.Event()
active_processes = []

def valid_port(port):
    """Validate port number is in valid range"""
    try:
        port_int = int(port)
        if 1 <= port_int <= 65535:
            return port_int
        else:
            raise argparse.ArgumentTypeError(f"Port {port} is not in valid range 1-65535")
    except ValueError:
        raise argparse.ArgumentTypeError(f"Port {port} is not a valid integer")

def main():
    parser = argparse.ArgumentParser(description="Enhanced Email Sync Script")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Setup command - accepts OAuth and destination server configuration
    setup_parser = subparsers.add_parser('setup', help='Configure OAuth2 and destination server settings')
    setup_parser.add_argument('--client-id', required=True, help='Azure App Client ID')
    setup_parser.add_argument('--client-secret', required=True, help='Azure App Client Secret')
    setup_parser.add_argument('--tenant-id', default='common', help='Tenant ID (default: common)')
    setup_parser.add_argument('--host', default=os.getenv('DEST_IMAP_HOST', 'localhost'), help='Destination IMAP server host (default: localhost)')
    setup_parser.add_argument('--port', type=valid_port, default=int(os.getenv('DEST_IMAP_PORT', '993')), help='Destination IMAP server port (default: 993)')
    setup_parser.add_argument('--ssl', action='store_true', default=os.getenv('DEST_IMAP_SSL', 'true').lower() == 'true', help='Use SSL for destination server (default: True)')
    setup_parser.add_argument('--no-ssl', action='store_true', help='Disable SSL for destination server')
    setup_parser.add_argument('--ssl-verify', action='store_true', help='Verify SSL certificates')
    setup_parser.add_argument('--no-ssl-verify', action='store_true', default=os.getenv('DEST_IMAP_SSL_VERIFY', 'false').lower() == 'false', help='Skip SSL certificate verification (default)')

    # Add-account command - accepts user email and sync configuration
    addaccount_parser = subparsers.add_parser('add-account', help='Add a new email account for synchronization')
    addaccount_parser.add_argument('--email', required=True, help='Source email address')
    addaccount_parser.add_argument('--source-folder', default='INBOX', help='Source folder to sync (default: INBOX)')
    addaccount_parser.add_argument('--dest-email', help='Destination email address (defaults to source email)')
    addaccount_parser.add_argument('--filters', help='Email filters (comma-separated)')
    addaccount_parser.add_argument('--office365', action='store_true', help='Mark as Office 365 account')
    addaccount_parser.add_argument('--password', help='Password for non-Office365 accounts (will prompt if not provided)')

    # Legacy monolithic command (deprecated)
    legacy_parser = subparsers.add_parser('legacy-setup', help='DEPRECATED: Use setup and add-account instead')
    legacy_parser.add_argument('--all-options', help='Legacy option - use new commands instead')

    # Other existing commands
    sync_parser = subparsers.add_parser('sync', help='Start email synchronization')
    sync_parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    sync_parser.add_argument('--dry-run', action='store_true', help='Simulate sync without changes')

    subparsers.add_parser('status', help='Show current status of configured accounts')
    subparsers.add_parser('clear', help='Clear all configuration files and tokens')
    subparsers.add_parser('help', help='Show detailed help information')

    # Global options
    parser.add_argument('--debug', action='store_true', help='Enable debug logging (global)')

    args = parser.parse_args()
    
    global logger
    logger = setup_logging(args.debug, SYNC_LOG)
    
    signal_handler(shutdown_event, active_processes)
    
    config_manager = ConfigManager(SCRIPT_DIR)
    oauth_manager: Optional[OAuth2Manager] = None
    config_manager.load_configuration(oauth_manager)  # Note: oauth_manager might be None initially
    if config_manager.oauth_config:
        oauth_manager = OAuth2Manager(
            config_manager.oauth_config['client_id'],
            config_manager.oauth_config['client_secret'],
            config_manager.oauth_config.get('tenant_id', 'common'),
            TOKENS_DIR
        )
        logger.info("OAuth manager loaded from config")
    else:
        logger.warning("No OAuth config found, OAuth not available. Run 'setup' to configure.")
    logger.info(f"Accounts loaded: {[(acc.email, acc.is_office365) for acc in config_manager.accounts]}")
    sync_manager = SyncManager(config_manager, oauth_manager, LOGS_DIR, IMAPSYNC_LOGS_DIR, shutdown_event, active_processes)
    
    if args.command == 'setup':
        new_setup_command(config_manager, args)
    elif args.command == 'sync':
        # Handle both --debug from sync command and global --debug
        debug_mode = getattr(args, 'debug', False) or args.debug
        dry_run = getattr(args, 'dry_run', False)
        sync_manager.sync_accounts(debug_mode, dry_run)
    elif args.command == 'status':
        show_status(config_manager, oauth_manager)
    elif args.command == 'clear':
        clear_config(config_manager)
    elif args.command == 'add-account':
        new_add_account_command(config_manager, args)
    elif args.command == 'legacy-setup':
        console.print("[bold red]DEPRECATED: The legacy-setup command is deprecated![/bold red]")
        console.print("[yellow]Please use the new commands instead:[/yellow]")
        console.print("  • [cyan]setup[/cyan] --client-id YOUR_ID --client-secret YOUR_SECRET [options]")
        console.print("  • [cyan]add-account[/cyan] --email user@example.com [options]")
        console.print("\n[yellow]For interactive setup, use:[/yellow] python3 email_sync.py setup --interactive")
        if Confirm.ask("Would you like to run the legacy interactive setup instead?"):
            interactive_setup(config_manager, oauth_manager)
    elif args.command == 'help':
        show_help()
    elif args.command is None:
        parser.print_help()
    else:
        console.print("Invalid command. Use 'help' for usage.")

def interactive_setup(config_manager: ConfigManager, oauth_manager: Optional[OAuth2Manager]):
    if config_manager.accounts_config.exists() or (TOKENS_DIR / "oauth_tokens.json").exists():
        console.print(Panel.fit(
            "[bold yellow]Existing Configuration Detected[/bold yellow]\n\n"
            "[yellow]The setup wizard can only configure one Office 365 tenant at a time.[/yellow]\n"
            "[yellow]Running setup again will clear your existing configuration.[/yellow]\n\n"
            "[red]This will remove:[/red]\n"
            "• All configured email accounts\n"
            "• OAuth tokens and app credentials\n"
            "• Destination server settings\n"
            "• Saved passwords",
            title="Warning"
        ))
        if not Confirm.ask("Do you want to clear existing configuration and start fresh?", default=False):
            console.print("[green]Setup cancelled. Existing configuration preserved.[/green]")
            return False
        console.print("[yellow]Clearing existing configuration...[/yellow]")
        config_manager._clear_config_files()  # Assume this method is added to ConfigManager
        config_manager.accounts = []
        oauth_manager = None
        config_manager.dest_config = {}
        console.print("[green]✓ Configuration cleared successfully![/green]\n")
    
    print("\n" + "="*60)
    print("Welcome to the Enhanced Email Sync Setup!")
    print("")
    print("This wizard will help you configure email synchronization")
    print("with both OAuth2 (Office 365) and password authentication.")
    print("Note: This setup supports ONE Office 365 tenant at a time.")
    print("="*60)
    
    # OAuth2 Setup
    print("\nStep 1: OAuth2 Configuration (for Office 365 accounts)")
    print("-" * 50)
    client_id = input("Enter your Azure App Client ID (app_id): ").strip()
    client_secret = getpass.getpass("Enter your Azure App Client Secret (secret_value): ")
    tenant_id_input = input("Enter your Tenant ID (or 'common' for multi-tenant) [common]: ").strip()
    tenant_id = tenant_id_input if tenant_id_input else "common"
    oauth_manager = OAuth2Manager(client_id, client_secret, tenant_id, TOKENS_DIR)
    
    # Destination server setup (unchanged, but save via config_manager)
    print("\nStep 2: Destination Server Configuration")
    print("-" * 50)
    
    # Get destination host
    default_host = os.getenv('DEST_IMAP_HOST', 'localhost')
    host_input = input(f"Destination IMAP server host [{default_host}]: ").strip()
    host = host_input if host_input else default_host
    
    # Get port with validation
    while True:
        try:
            port_input = input("Destination IMAP server port [993]: ").strip()
            port_str = port_input if port_input else "993"
            port = int(port_str)
            if 1 <= port <= 65535:
                break
            else:
                print("Port must be between 1 and 65535")
        except ValueError:
            print("Please enter a valid port number")
    
    # Get SSL settings
    ssl_input = input("Use SSL for destination server? [Y/n]: ").strip().lower()
    use_ssl = ssl_input not in ['n', 'no', 'false']
    
    ssl_verify_input = input("Verify SSL certificates (disable for self-signed certificates)? [y/N]: ").strip().lower()
    ssl_verify = ssl_verify_input in ['y', 'yes', 'true']
    
    config_manager.dest_config = {
        'host': host,
        'port': port,
        'ssl': use_ssl,
        'ssl_verify': ssl_verify,
        'passwords': {}  # Will store destination account passwords
    }
    
    # Email accounts setup
    print("\nStep 3: Email Accounts Configuration")
    print("-" * 50)
    
    # Get Office 365 accounts
    office365_emails = input("Enter comma-separated Office 365 email addresses (leave empty if none): ").strip()
    o365_set = set()
    if office365_emails.strip():
        for email in office365_emails.split(','):
            email = email.strip()
            if email:
                config_manager.accounts.append(EmailAccount(email, is_office365=True))
                o365_set.add(email)
    
    # Get other accounts (with passwords)
    other_emails = input("Enter comma-separated email addresses for local/other accounts (leave empty if none): ").strip()
    
    if other_emails.strip():
        print("Now enter passwords for each local/other account:")
        for email in other_emails.split(','):
            email = email.strip()
            if email and email not in o365_set:
                password = getpass.getpass(f"Password for {email}: ")
                config_manager.accounts.append(EmailAccount(email, password, is_office365=False))
    
    # Prompt for destination passwords for all accounts
    unique_emails = set(acc.email for acc in config_manager.accounts)
    config_manager.dest_config['passwords'] = {}
    print("\nNow enter destination passwords for each account:")
    for email in unique_emails:
        dest_password = getpass.getpass(f"Destination password for {email}: ")
        config_manager.dest_config['passwords'][email] = dest_password
    
    # Optional: different destination emails
    use_same_dest = input("Use same email addresses for destination? [Y/n]: ").strip().lower() or 'y'
    if use_same_dest in ['n', 'no']:
        dest_emails_input = input("Enter comma-separated destination email addresses (must match number of source emails): ").strip()
        dest_emails = [e.strip() for e in dest_emails_input.split(',') if e.strip()]
        if len(dest_emails) != len(config_manager.accounts):
            print("Number of destination emails must match source accounts!")
            return False
        for i, acc in enumerate(config_manager.accounts):
            acc.dest_email = dest_emails[i]
            # Remap password to dest_email
            if acc.email in config_manager.dest_config['passwords']:
                config_manager.dest_config['passwords'][acc.dest_email] = config_manager.dest_config['passwords'].pop(acc.email)
    
    # Setup OAuth2 authorization for Office 365 accounts
    office365_accounts = [acc for acc in config_manager.accounts if acc.is_office365]
    if office365_accounts:
        print("\nStep 4: Acquiring App-Only Token")
        print("-" * 50)
        if oauth_manager:
            oauth_manager.acquire_token()
            print("✓ App-only token acquired successfully!")
            config_manager.save_configuration(oauth_manager)
        else:
            print("✗ Failed to acquire app-only token!")
            return False
    
    config_manager.save_configuration(oauth_manager)
    print("\n✓ Setup complete!")
    return True

def show_status(config_manager: ConfigManager, oauth_manager: Optional[OAuth2Manager]):
    console.print(Panel.fit("[bold blue]Email Sync Status[/bold blue]", title="Status"))
    if not config_manager.accounts:
        console.print("[yellow]No accounts configured.[/yellow]")
        return
    table = Table(title="Account Status")
    table.add_column("Email", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Last Sync", style="green")
    table.add_column("Status", style="yellow")
    for account in config_manager.accounts:
        account_type = "Office 365" if account.is_office365 else "Local/Other"
        last_sync = account.sync_stats.get('last_sync', 'Never')
        if last_sync != 'Never' and last_sync is not None:
            last_sync = datetime.fromisoformat(last_sync).strftime('%Y-%m-%d %H:%M:%S')
        status = "Ready"
        if account.is_office365 and oauth_manager:
            token = oauth_manager.get_valid_token()
            if not token:
                status = "Token Invalid"
        table.add_row(account.email, account_type, last_sync, status)
    console.print(table)

def clear_config(config_manager: ConfigManager):
    console.print(Panel.fit("[bold red]Clear Configuration[/bold red]", title="Warning"))
    console.print("[yellow]This will remove all configuration files and tokens.[/yellow]")
    console.print("[yellow]You will need to set up your accounts again.[/yellow]")
    if not Confirm.ask("Are you sure you want to clear all configuration?", default=False):
        console.print("[green]Operation cancelled.[/green]")
        return
    config_manager._clear_config_files()  # Implement in ConfigManager
    console.print("[bold green]Configuration cleared. Run 'setup' to reconfigure.[/bold green]")

def add_account(config_manager: ConfigManager):
    """
    Adds a new Office 365 account to the configuration using the new thread-safe utilities.
    """
    # First try to load configuration - this will ensure we have the latest state
    try:
        config_manager.load_configuration(None)
    except Exception:
        # If loading fails, we might not have configuration yet
        pass
        
    # Check if initial setup has been completed by checking for config file existence
    # OR by checking if we have some basic configuration in memory
    has_basic_config = (config_manager.accounts_config.exists() or 
                       config_manager.dest_config or 
                       hasattr(config_manager, 'oauth_config'))
    
    if not has_basic_config:
        console.print("[red]❌ No configuration found![/red]")
        console.print("[yellow]Please run 'python3 email_sync.py setup' first to create the initial configuration.[/yellow]")
        return
    
    # For testing purposes, allow OAuth config to be set in memory even if not in file
    if not config_manager.oauth_config:
        console.print("[red]❌ OAuth2 configuration not found![/red]")
        console.print("[yellow]Please run 'python3 email_sync.py setup' first to configure OAuth2 for Office 365 accounts.[/yellow]")
        return
    
    # Display current configuration info
    console.print(Panel.fit(
        "[bold blue]Adding New Office 365 Account[/bold blue]\n\n"
        "This will add a new Office 365 account using your existing:\n"
        "• OAuth2 configuration (Azure App credentials)\n"
        "• Destination server settings\n\n"
        "[yellow]Note: Only Office 365 accounts are supported with this command.[/yellow]",
        title="Add Account"
    ))

    # Prompt for user inputs with validation
    while True:
        source_email = input("Enter the source Office 365 email address: ").strip()
        if source_email and '@' in source_email:
            # Check if account already exists
            if any(acc.email == source_email for acc in config_manager.accounts):
                console.print(f"[yellow]⚠ Account '{source_email}' is already configured.[/yellow]")
                continue
            break
        console.print("[red]Please enter a valid email address.[/red]")
    
    while True:
        dest_email = input("Enter the destination email address: ").strip()
        if dest_email and '@' in dest_email:
            break
        console.print("[red]Please enter a valid destination email address.[/red]")
    
    dest_password = getpass.getpass("Enter the destination IMAP password (hidden): ")
    if not dest_password:
        console.print("[red]Password cannot be empty.[/red]")
        return

    # Create EmailAccount and use new thread-safe utility
    new_account = EmailAccount(email=source_email, is_office365=True, dest_email=dest_email)
    
    try:
        # Use the new thread-safe method instead of manual manipulation
        config_manager.add_or_update_account(new_account, dest_password)
        console.print("[green]✅ Account added successfully![/green]")
        console.print(f"[green]Source: {source_email} → Destination: {dest_email}[/green]")
        console.print("[blue]You can now run 'python3 email_sync.py sync' to start synchronization.[/blue]")
    except RuntimeError as e:
        # Re-raise the exception so tests can see it - don't silently ignore
        raise

def new_setup_command(config_manager: ConfigManager, args):
    """
    New command-line based setup that accepts parameters via arguments.
    """
    console.print(Panel.fit("[bold blue]Email Sync Setup[/bold blue]", title="Setup"))
    
    # Check for existing configuration
    if config_manager.accounts_config.exists() or (TOKENS_DIR / "oauth_tokens.json").exists():
        console.print("[yellow]⚠️  Existing configuration detected![/yellow]")
        if not Confirm.ask("Do you want to overwrite the existing configuration?", default=False):
            console.print("[green]Setup cancelled. Existing configuration preserved.[/green]")
            return
        config_manager._clear_config_files()
        config_manager.accounts = []
        config_manager.dest_config = {}
        console.print("[green]✓ Previous configuration cleared.[/green]")
    
    # Configure OAuth2
    console.print("[cyan]Configuring OAuth2 settings...[/cyan]")
    oauth_manager = OAuth2Manager(args.client_id, args.client_secret, args.tenant_id, TOKENS_DIR)
    
    # Configure destination server
    console.print("[cyan]Configuring destination server...[/cyan]")
    
    # Handle SSL settings
    use_ssl = args.ssl and not args.no_ssl
    ssl_verify = args.ssl_verify and not args.no_ssl_verify
    
    config_manager.dest_config = {
        'host': args.host,
        'port': args.port,
        'ssl': use_ssl,
        'ssl_verify': ssl_verify,
        'passwords': {}
    }
    
    # Try to acquire OAuth token
    console.print("[cyan]Acquiring OAuth2 token...[/cyan]")
    try:
        oauth_manager.acquire_token()
        console.print("[green]✓ OAuth2 token acquired successfully![/green]")
    except Exception as e:
        console.print(f"[red]✗ Failed to acquire OAuth2 token: {e}[/red]")
        console.print("[yellow]You can still proceed, but Office 365 accounts may not work.[/yellow]")
    
    # Save configuration
    config_manager.save_configuration(oauth_manager)
    
    console.print("[bold green]✅ Setup complete![/bold green]")
    console.print("[yellow]Next steps:[/yellow]")
    console.print("  • Use [cyan]add-account[/cyan] to add email accounts")
    console.print("  • Use [cyan]sync[/cyan] to start synchronization")

def new_add_account_command(config_manager: ConfigManager, args):
    """
    New command-line based add-account that accepts parameters via arguments.
    """
    console.print(Panel.fit("[bold blue]Adding Email Account[/bold blue]", title="Add Account"))
    
    # Check if setup has been completed
    if not config_manager.accounts_config.exists():
        console.print("[red]❌ No configuration found![/red]")
        console.print("[yellow]Please run the setup command first:[/yellow]")
        console.print("  python3 email_sync.py setup --client-id YOUR_ID --client-secret YOUR_SECRET")
        return
    
    # Load current configuration to get OAuth config
    oauth_manager: Optional[OAuth2Manager] = None
    config_manager.load_configuration(oauth_manager)
    if config_manager.oauth_config:
        oauth_manager = OAuth2Manager(
            config_manager.oauth_config['client_id'],
            config_manager.oauth_config['client_secret'],
            config_manager.oauth_config.get('tenant_id', 'common'),
            TOKENS_DIR
        )
    
    # Validate email
    if '@' not in args.email:
        console.print(f"[red]Invalid email address: {args.email}[/red]")
        return
    
    # Check if account already exists
    if any(acc.email == args.email for acc in config_manager.accounts):
        console.print(f"[yellow]⚠️  Account '{args.email}' already exists![/yellow]")
        if not Confirm.ask("Do you want to update the existing account?", default=False):
            console.print("[green]Operation cancelled.[/green]")
            return
        # Remove existing account
        config_manager.accounts = [acc for acc in config_manager.accounts if acc.email != args.email]
    
    # Set destination email
    dest_email = args.dest_email or args.email
    
    # Handle password for non-Office365 accounts
    password = None
    if not args.office365:
        if args.password:
            password = args.password
        else:
            password = getpass.getpass(f"Enter password for {args.email}: ")
            if not password:
                console.print("[red]Password is required for non-Office365 accounts.[/red]")
                return
    
    # Check OAuth2 configuration for Office 365 accounts
    if args.office365 and not config_manager.oauth_config:
        console.print("[red]❌ OAuth2 not configured![/red]")
        console.print("[yellow]Office 365 accounts require OAuth2 configuration.[/yellow]")
        console.print("[yellow]Please run setup first with --client-id and --client-secret.[/yellow]")
        return
    
    # Create account
    new_account = EmailAccount(
        email=args.email,
        password=password,
        is_office365=args.office365,
        dest_email=dest_email
    )
    
    # Add source folder and filters if provided
    if hasattr(new_account, 'source_folder'):
        new_account.source_folder = args.source_folder
    if hasattr(new_account, 'filters') and args.filters:
        new_account.filters = [f.strip() for f in args.filters.split(',')]
    
    # Add account to configuration
    config_manager.accounts.append(new_account)
    
    # Get destination password
    dest_password = getpass.getpass(f"Enter destination IMAP password for {dest_email}: ")
    if not dest_password:
        console.print("[red]Destination password is required.[/red]")
        return
    
    # Store destination password
    if 'passwords' not in config_manager.dest_config:
        config_manager.dest_config['passwords'] = {}
    config_manager.dest_config['passwords'][dest_email] = dest_password
    
    # Save configuration
    config_manager.save_configuration(oauth_manager)
    
    console.print("[bold green]✅ Account added successfully![/bold green]")
    console.print(f"[green]Source: {args.email} → Destination: {dest_email}[/green]")
    if args.office365:
        console.print("[blue]Account type: Office 365 (OAuth2)[/blue]")
    else:
        console.print("[blue]Account type: Local/Other (Password)[/blue]")
    console.print("[yellow]Use [cyan]sync[/cyan] to start synchronization.[/yellow]")

def show_help():
    console.print("[bold]Enhanced Email Sync - Command Line Interface[/bold]")
    console.print("\n[bold]Usage:[/bold] python3 email_sync.py <command> [options]")
    
    console.print("\n[bold]Commands:[/bold]")
    
    # Setup command
    console.print("\n  [cyan]setup[/cyan] - Configure OAuth2 and destination server")
    console.print("    [bold]Required:[/bold]")
    console.print("      --client-id CLIENT_ID     Azure App Client ID")
    console.print("      --client-secret SECRET    Azure App Client Secret")
    console.print("    [bold]Optional:[/bold]")
    console.print("      --tenant-id TENANT        Tenant ID (default: common)")
    console.print("      --host HOST               Destination server (default: localhost)")
    console.print("      --port PORT               Destination port (default: 993)")
    console.print("      --ssl/--no-ssl            Use SSL (default: enabled)")
    console.print("      --ssl-verify/--no-ssl-verify  SSL verification (default: disabled)")
    
    # Add-account command
    console.print("\n  [cyan]add-account[/cyan] - Add email account for synchronization")
    console.print("    [bold]Required:[/bold]")
    console.print("      --email EMAIL             Source email address")
    console.print("    [bold]Optional:[/bold]")
    console.print("      --dest-email EMAIL        Destination email (default: same as source)")
    console.print("      --office365               Mark as Office 365 account")
    console.print("      --password PASSWORD        Password (for non-O365, prompts if not provided)")
    console.print("      --source-folder FOLDER    Source folder (default: INBOX)")
    console.print("      --filters FILTERS         Email filters (comma-separated)")
    
    # Other commands
    console.print("\n  [cyan]sync[/cyan] - Start email synchronization")
    console.print("    --debug                   Enable debug logging")
    console.print("    --dry-run                 Simulate without making changes")
    
    console.print("\n  [cyan]status[/cyan] - Show account status")
    console.print("  [cyan]clear[/cyan] - Clear all configuration")
    console.print("  [cyan]help[/cyan] - Show this help message")
    
    # Deprecated command warning
    console.print("\n  [red]legacy-setup[/red] - [strike]DEPRECATED[/strike] Use setup + add-account instead")
    
    console.print("\n[bold]Examples:[/bold]")
    console.print("  [dim]# Initial setup[/dim]")
    console.print("  python3 email_sync.py setup --client-id abc123 --client-secret def456")
    
    console.print("\n  [dim]# Setup with custom destination server[/dim]")
    console.print("  python3 email_sync.py setup --client-id abc123 --client-secret def456 \\")
    console.print("                               --host mail.company.com --port 143 --no-ssl")
    
    console.print("\n  [dim]# Add Office 365 account[/dim]")
    console.print("  python3 email_sync.py add-account --email user@company.com --office365")
    
    console.print("\n  [dim]# Add local account with different destination[/dim]")
    console.print("  python3 email_sync.py add-account --email local@domain.com \\")
    console.print("                                     --dest-email backup@backup.com")
    
    console.print("\n  [dim]# Start synchronization[/dim]")
    console.print("  python3 email_sync.py sync")
    console.print("  python3 email_sync.py sync --dry-run --debug")
    
    console.print("\n[bold]Migration from Legacy Command:[/bold]")
    console.print("  [yellow]Old monolithic command is deprecated.[/yellow] Use the new structured approach:")
    console.print("  [dim]1.[/dim] Run [cyan]setup[/cyan] once with OAuth and server configuration")
    console.print("  [dim]2.[/dim] Run [cyan]add-account[/cyan] for each email account to sync")
    console.print("  [dim]3.[/dim] Run [cyan]sync[/cyan] to start synchronization")

if __name__ == "__main__":
    main()
