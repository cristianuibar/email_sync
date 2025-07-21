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
    "redirect_uri": "http://localhost:8080/callback",
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

def main():
    parser = argparse.ArgumentParser(description="Enhanced Email Sync Script")
    parser.add_argument('command', choices=['setup', 'sync', 'status', 'clear', 'help'], help="Command to run")
    parser.add_argument('--debug', action='store_true', help="Enable debug logging")
    parser.add_argument('--dry-run', action='store_true', help="Simulate sync without changes")
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
        interactive_setup(config_manager, oauth_manager)
    elif args.command == 'sync':
        sync_manager.sync_accounts(args.debug, args.dry_run)
    elif args.command == 'status':
        show_status(config_manager, oauth_manager)
    elif args.command == 'clear':
        clear_config(config_manager)
    elif args.command == 'help':
        show_help()
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
    host_input = input("Destination IMAP server host [localhost]: ").strip()
    host = host_input if host_input else "localhost"
    
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

def show_help():
    console.print("[bold]Usage:[/bold] python3 email_sync.py <command> [options]")
    console.print("Commands:")
    console.print("  setup    Run interactive setup wizard")
    console.print("  sync     Start synchronization (--dry-run for simulation, --debug for verbose logs)")
    console.print("  status   Show current status")
    console.print("  clear    Clear all configuration")
    console.print("  help     Show this message")

if __name__ == "__main__":
    main()
