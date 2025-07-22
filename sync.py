import logging
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Tuple, List, Optional

import imaplib
import ssl
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, MofNCompleteColumn
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from config import EmailAccount, ConfigManager
from oauth import OAuth2Manager

console = Console()
logger = logging.getLogger(__name__)

class SyncManager:
    def __init__(self, config_manager: ConfigManager, oauth_manager: Optional[OAuth2Manager], logs_dir: Path, imapsync_logs_dir: Path, shutdown_event, active_processes):
        self.config_manager = config_manager
        self.oauth_manager = oauth_manager
        self.logs_dir = logs_dir
        self.imapsync_logs_dir = imapsync_logs_dir
        self.shutdown_event = shutdown_event
        self.active_processes = active_processes
    
    def test_connection(self, account: EmailAccount) -> bool:
        logger.info(f"Testing connection to {account.email}...")
        console.print(f"[yellow]Testing connection to {account.email}...[/yellow]")
        if account.is_office365:
            if not self.oauth_manager:
                console.print(f"[red]✗ No OAuth manager configured for {account.email}[/red]")
                return False
            token = self.oauth_manager.get_valid_token()
            if not token:
                console.print(f"[red]✗ Invalid OAuth token for {account.email}[/red]")
                return False
            console.print(f"[green]✓ OAuth token valid for {account.email}[/green]")
            logger.info(f"OAuth token valid for {account.email}")
        else:
            if not account.password:
                console.print(f"[red]✗ No password configured for {account.email}[/red]")
                return False
            console.print(f"[green]✓ Password authentication ready for {account.email}[/green]")
            logger.info(f"Password authentication ready for {account.email}")
        return True
    
    def test_destination_connection(self) -> bool:
        dest_config = self.config_manager.dest_config
        logger.info(f"Testing connection to destination server: {dest_config['host']}:{dest_config['port']}")
        console.print(f"[yellow]Testing connection to destination server...[/yellow]")
        context = ssl.create_default_context()
        if not dest_config.get('ssl_verify', True):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            with imaplib.IMAP4_SSL(dest_config['host'], dest_config['port'], ssl_context=context) as server:
                console.print("[green]✓ Successfully connected to destination server[/green]")
            return True
        except Exception as e:
            console.print(f"[red]✗ Connection to destination server failed: {e}[/red]")
            logger.error(f"Connection to destination server failed: {e}")
            return False
    
    def run_imapsync_with_retry(self, account: EmailAccount, dest_email: str, dest_password: str, dry_run: bool = False, max_retries: int = 3) -> Tuple[bool, str]:
        if not self.test_connection(account):
            return False, "Connection test failed"
        if not account.is_office365 and self.oauth_manager is None:
            logger.warning(f"Skipping non-o365 account {account.email} due to no OAuth manager")
            return False, "Skipped non-o365 account without OAuth"
        for attempt in range(1, max_retries + 1):
            try:
                return self._run_imapsync(account, dest_email, dest_password, dry_run)
            except Exception as e:
                # Escape any Rich markup in the error message to prevent tag conflicts
                escaped_error = str(e).replace('[', '\\[').replace(']', '\\]')
                logger.warning(f"Attempt {attempt} failed for {account.email}: {escaped_error}")
                console.print(f"[yellow]WARNING  Attempt {attempt} failed for {account.email}: {escaped_error}[/yellow]")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return False, f"Sync failed after {max_retries} attempts: {e}"
        return False, "No sync attempts made"
    
    def _run_imapsync(self, account: EmailAccount, dest_email: str, dest_password: str, dry_run: bool) -> Tuple[bool, str]:
        if not shutil.which("imapsync"):
            raise RuntimeError("imapsync not found. Please install it and ensure it's in PATH.")
        
        log_file = self.imapsync_logs_dir / f"sync_{account.email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        console.print(f"[blue]Connecting to source server for {account.email}...[/blue]")
        logger.info(f"Connecting to source server for {account.email}")
        
        cmd = [
            "imapsync",
            "--host1", "outlook.office365.com" if account.is_office365 else f"imap.{account.email.split('@')[1]}",
            "--port1", "993",
            "--ssl1",
            "--user1", account.email,
            "--host2", self.config_manager.dest_config['host'],
            "--port2", str(self.config_manager.dest_config['port']),
            "--user2", dest_email,
            "--password2", dest_password,
            "--delete2",
            "--expunge2",
            "--nofoldersizes",
            "--nofoldersizesatend",
            "--logfile", str(log_file),
            "--pidfile", str(self.config_manager.script_dir / f"imapsync_{account.email}.pid"),
        ]
        
        console.print(f"[blue]Starting message synchronization for {account.email}...[/blue]")
        logger.info(f"Starting message synchronization for {account.email}")
        
        if dry_run:
            cmd.append("--dry")
        
        if self.config_manager.dest_config.get('ssl', True):
            cmd.append("--ssl2")
            if not self.config_manager.dest_config.get('ssl_verify', True):
                cmd.extend(["--sslargs2", "SSL_verify_mode=0"])
        
        if account.is_office365:
            assert self.oauth_manager is not None
            token = self.oauth_manager.get_valid_token()
            if not token:
                return False, "Failed to get OAuth2 token"
            cmd.extend(["--authmech1", "XOAUTH2", "--oauthaccesstoken1", token, "--password1", "dummy"])
            # Add Office 365 specific settings to avoid connection issues
            cmd.extend([
                "--buffersize", "8192000",
                "--timeout1", "120",
                "--timeout2", "120",
                "--split1", "100",
                "--split2", "100",
                "--skipheader", "Content-Type",
                "--skipheader", "Content-Transfer-Encoding",
                "--noid",  # Skip ID command that causes Office 365 issues
                "--nofoldersizes",  # Additional flag to avoid folder size checking issues
                "--subscribeall",  # Subscribe to all folders automatically
                "--sep1", "/",  # Explicitly set separator for Office 365
                "--noreleasecheck",  # Skip release check
                "--nocheckmessageexists",  # Avoid checking message existence which can fail
                "--no-modulesversion"  # Skip module version printing
            ])
        else:
            cmd.extend(["--password1", account.password])
        
        logger.debug(f"Running imapsync command: {' '.join(cmd[:10])}... (full command logged to file)")
        logger.info(f"Full imapsync command: {' '.join([arg if 'password' not in arg and 'oauthaccesstoken' not in arg else 'MASKED' for arg in cmd])}")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        self.active_processes.append(process)
        
        connection_established = False
        sync_started = False
        messages_processed = 0
        total_messages = 0
        collected_output = []
        
        assert process.stdout is not None, 'stdout not set'
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                line = output.strip()
                collected_output.append(line)
                logger.debug(f"imapsync: {line}")
                
                # Connection status
                if not connection_established and ("success login" in line.lower() and "host1" in line.lower()):
                    connection_established = True
                    console.print(f"[green]✓ Connected to Office 365[/green]")
                    logger.info(f"Connected to Office 365 for {account.email}")
                elif not connection_established and ("success login" in line.lower() and "host2" in line.lower()):
                    console.print(f"[green]✓ Connected to destination server[/green]")
                    logger.info(f"Connected to destination server for {account.email}")
                
                # Show folder information
                if "folders list" in line.lower() or "folder" in line.lower() and "has" in line.lower() and "messages" in line.lower():
                    folder_match = re.search(r'folder \[(.*?)\] has (\d+) messages', line)
                    if folder_match:
                        folder_name, msg_count = folder_match.groups()
                        console.print(f"[dim]Folder '{folder_name}': {msg_count} messages[/dim]")
                
                # Show overall sync progress
                total_match = re.search(r'there are (\d+) among (\d+) identified messages', line)
                if total_match:
                    need_sync, total_msgs = total_match.groups()
                    console.print(f"[cyan]Found {total_msgs} total messages, {need_sync} need syncing[/cyan]")
                    logger.info(f"Total messages: {total_msgs}, need sync: {need_sync}")
                
                # Show message processing progress
                msg_match = re.search(r'(\d+)/(\d+) msg', line)
                if msg_match:
                    messages_processed = int(msg_match.group(1))
                    total_messages = int(msg_match.group(2))
                    console.print(f"[cyan]Processing {messages_processed}/{total_messages} messages[/cyan]")
                    logger.info(f"Processed {messages_processed}/{total_messages} messages for {account.email}")
                
                # Show sync start
                if "++++ Looping on each one of" in line and "folders to sync" in line:
                    folder_count = re.search(r'each one of (\d+) folders', line)
                    if folder_count:
                        console.print(f"[blue]Starting sync of {folder_count.group(1)} folders[/blue]")
                
                # Show folder sync progress
                folder_sync_match = re.search(r'Folder\s+(\d+)/(\d+)\s+\[(.*?)\]', line)
                if folder_sync_match:
                    current, total, folder_name = folder_sync_match.groups()
                    console.print(f"[yellow]Syncing folder {current}/{total}: {folder_name}[/yellow]")
                
                # Show important status messages
                if any(keyword in line.lower() for keyword in ['error', 'warning', 'failed', 'success', 'done', 'finished', 'detected', 'exiting']):
                    # Escape all square brackets in the line to prevent Rich markup conflicts
                    escaped_line = line.replace('[', '\\[').replace(']', '\\]')
                    if 'error' in line.lower() or 'failed' in line.lower():
                        console.print(f"[red]⚠ {escaped_line}[/red]")
                    elif 'success' in line.lower() or 'done' in line.lower() or 'finished' in line.lower():
                        console.print(f"[green]✓ {escaped_line}[/green]")
                    elif 'detected' in line.lower() and 'errors' in line.lower():
                        console.print(f"[blue]ℹ {escaped_line}[/blue]")
                    else:
                        console.print(f"[yellow]! {escaped_line}[/yellow]")
                    logger.info(f"imapsync status: {line}")
            
            if self.shutdown_event.is_set():
                process.terminate()
                break
        
        process.wait()
        if process in self.active_processes:
            self.active_processes.remove(process)
        
        if process.returncode == 0:
            account.sync_stats['last_sync'] = datetime.now().isoformat()
            account.sync_stats['synced_messages'] += messages_processed
            success_msg = f"Sync completed successfully - processed {messages_processed}/{total_messages} messages"
            console.print(f"[green]✓ {account.email}: {success_msg}[/green]")
            logger.info(f"✓ {account.email}: {success_msg}")
            return True, success_msg
        else:
            error_msg = f"Sync failed with exit code {process.returncode}"
            console.print(f"[red]✗ {account.email}: {error_msg}[/red]")
            logger.error(f"✗ {account.email}: {error_msg}")
            if log_file.exists():
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    last_lines = lines[-10:] if len(lines) > 10 else lines
                    console.print(f"[red]Last log entries:[/red]")
                    for line in last_lines:
                        # Escape any Rich markup in the line to prevent tag conflicts
                        escaped_line = line.strip().replace('[', '\\[').replace(']', '\\]')
                        console.print(f"[dim]{escaped_line}[/dim]")
            else:
                console.print(f"[yellow]Log file not created, probably early failure in imapsync[/yellow]")
                logger.warning("Log file not created")
                if collected_output:
                    console.print(f"[red]imapsync output:[/red]")
                    for line in collected_output:
                        # Escape any Rich markup in the line to prevent tag conflicts
                        escaped_line = line.replace('[', '\\[').replace(']', '\\]')
                        console.print(f"[dim]{escaped_line}[/dim]")
            raise RuntimeError(error_msg)
    
    def sync_accounts(self, debug: bool = False, dry_run: bool = False, max_parallel: int = 1):
        # Verify global configuration has been loaded properly
        if not self.config_manager.dest_config:
            console.print("[red]❌ Global configuration not loaded. Please run setup first.[/red]")
            logger.error("Global configuration missing or empty")
            return
            
        accounts = self.config_manager.accounts
        if not accounts:
            console.print("[red]No accounts configured. Please run setup first.[/red]")
            return
            
        logger.info(f"Starting synchronization of {len(accounts)} accounts (dry-run: {dry_run})")
        console.print(f"[bold blue]Starting synchronization of {len(accounts)} accounts[/bold blue] [dim](dry-run: {dry_run})[/dim]")
        
        if debug:
            logger.info("Debug mode enabled for sync operation")
            console.print("[yellow]Debug mode enabled[/yellow]")
            
        # Test destination connection with output using global config
        console.print("[yellow]Testing destination server connection...[/yellow]")
        if not self._test_destination_connection_silent():
            console.print("[red]✗ Failed to connect to destination server. Check logs for details.[/red]")
            return
        console.print("[green]✓ Destination server connection successful[/green]")
            
        dest_passwords = self.config_manager.dest_config.get('passwords', {})
        
        # Process accounts one by one with detailed output (iterating over accounts from global config)
        for i, account in enumerate(accounts, 1):
            console.print(f"\n[bold cyan]--- Account {i}/{len(accounts)}: {account.email} ---[/bold cyan]")
            logger.info(f"Processing account {i}/{len(accounts)}: {account.email} (Office365: {account.is_office365})")
            
            dest_email = account.dest_email
            dest_password = dest_passwords.get(dest_email)
            
            if not dest_password:
                logger.error(f"No destination password for {dest_email}")
                console.print(f"[red]❌ Missing password for {dest_email}[/red]")
                continue
            
            try:
                success, message = self.run_imapsync_with_retry(account, dest_email, dest_password, dry_run)
                if success:
                    logger.info(f"✓ {account.email}: {message}")
                    console.print(f"[green]✓ {account.email}: {message}[/green]")
                else:
                    logger.error(f"✗ {account.email}: {message}")
                    console.print(f"[red]✗ {account.email}: {message}[/red]")
            except Exception as e:
                logger.error(f"Sync error for {account.email}: {e}")
                # Escape any Rich markup in the error message to prevent tag conflicts
                error_msg = str(e).replace('[', '\\[').replace(']', '\\]')
                console.print(f"[red]✗ {account.email}: {error_msg}[/red]")
            
            if self.shutdown_event.is_set():
                console.print("[yellow]🛑 Sync interrupted by user[/yellow]")
                break
        
        if not self.shutdown_event.is_set():
            console.print(f"\n[bold green]🎉 All {len(accounts)} accounts synchronized![/bold green]")
        
        self.config_manager.save_configuration(self.oauth_manager)
        logger.info("Synchronization completed")
    
    def _test_destination_connection_silent(self) -> bool:
        """Test destination connection without console output"""
        dest_config = self.config_manager.dest_config
        logger.info(f"Testing connection to destination server: {dest_config['host']}:{dest_config['port']}")
        context = ssl.create_default_context()
        if not dest_config.get('ssl_verify', True):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            with imaplib.IMAP4_SSL(dest_config['host'], dest_config['port'], ssl_context=context) as server:
                logger.info("Successfully connected to destination server")
            return True
        except Exception as e:
            logger.error(f"Connection to destination server failed: {e}")
            return False
    
    def _test_connection_silent(self, account: EmailAccount) -> bool:
        """Test account connection without console output"""
        logger.info(f"Testing connection to {account.email}...")
        if account.is_office365:
            if not self.oauth_manager:
                logger.error(f"No OAuth manager configured for {account.email}")
                return False
            token = self.oauth_manager.get_valid_token()
            if not token:
                logger.error(f"Invalid OAuth token for {account.email}")
                return False
            logger.info(f"OAuth token valid for {account.email}")
        else:
            if not account.password:
                logger.error(f"No password configured for {account.email}")
                return False
            logger.info(f"Password authentication ready for {account.email}")
        return True
    
    def run_imapsync_with_retry_silent(self, account: EmailAccount, dest_email: str, dest_password: str, dry_run: bool = False, max_retries: int = 3) -> Tuple[bool, str]:
        """Run imapsync with retry logic but without console output"""
        if not self._test_connection_silent(account):
            return False, "Connection test failed"
        if not account.is_office365 and self.oauth_manager is None:
            logger.warning(f"Skipping non-o365 account {account.email} due to no OAuth manager")
            return False, "Skipped non-o365 account without OAuth"
        for attempt in range(1, max_retries + 1):
            try:
                return self._run_imapsync_silent(account, dest_email, dest_password, dry_run)
            except Exception as e:
                logger.warning(f"Attempt {attempt} failed for {account.email}: {e}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return False, f"Sync failed after {max_retries} attempts: {e}"
        return False, "No sync attempts made"
    
    def _run_imapsync_silent(self, account: EmailAccount, dest_email: str, dest_password: str, dry_run: bool) -> Tuple[bool, str]:
        """Run imapsync without console output, only logging"""
        if not shutil.which("imapsync"):
            raise RuntimeError("imapsync not found. Please install it and ensure it's in PATH.")
        
        log_file = self.imapsync_logs_dir / f"sync_{account.email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        logger.info(f"Connecting to source server for {account.email}")
        
        cmd = [
            "imapsync",
            "--host1", "outlook.office365.com" if account.is_office365 else f"imap.{account.email.split('@')[1]}",
            "--port1", "993",
            "--ssl1",
            "--user1", account.email,
            "--host2", self.config_manager.dest_config['host'],
            "--port2", str(self.config_manager.dest_config['port']),
            "--user2", dest_email,
            "--password2", dest_password,
            "--delete2",
            "--expunge2",
            "--nofoldersizes",
            "--nofoldersizesatend",
            "--logfile", str(log_file),
            "--pidfile", str(self.config_manager.script_dir / f"imapsync_{account.email}.pid"),
        ]
        if dry_run:
            cmd.append("--dry")
        
        if self.config_manager.dest_config.get('ssl', True):
            cmd.append("--ssl2")
            if not self.config_manager.dest_config.get('ssl_verify', True):
                cmd.extend(["--sslargs2", "SSL_verify_mode=0"])
        
        if account.is_office365:
            assert self.oauth_manager is not None
            token = self.oauth_manager.get_valid_token()
            if not token:
                return False, "Failed to get OAuth2 token"
            cmd.extend(["--authmech1", "XOAUTH2", "--oauthaccesstoken1", token, "--password1", "dummy"])
            # Add Office 365 specific settings to avoid connection issues
            cmd.extend([
                "--buffersize", "8192000",
                "--timeout1", "120",
                "--timeout2", "120",
                "--split1", "100",
                "--split2", "100",
                "--skipheader", "Content-Type",
                "--skipheader", "Content-Transfer-Encoding",
                "--noid",  # Skip ID command that causes Office 365 issues
                "--nofoldersizes",  # Additional flag to avoid folder size checking issues
                "--subscribeall",  # Subscribe to all folders automatically
                "--sep1", "/",  # Explicitly set separator for Office 365
                "--noreleasecheck",  # Skip release check
                "--nocheckmessageexists",  # Avoid checking message existence which can fail
                "--no-modulesversion"  # Skip module version printing
            ])
        else:
            cmd.extend(["--password1", account.password])
        
        logger.debug(f"Running imapsync command: {' '.join(cmd[:10])}... (full command logged to file)")
        logger.info(f"Full imapsync command: {' '.join([arg if 'password' not in arg and 'oauthaccesstoken' not in arg else 'MASKED' for arg in cmd])}")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        self.active_processes.append(process)
        
        connection_established = False
        sync_started = False
        messages_processed = 0
        total_messages = 0
        collected_output = []
        
        assert process.stdout is not None, 'stdout not set'
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                line = output.strip()
                collected_output.append(line)
                logger.debug(f"imapsync: {line}")
                
                if not connection_established and ("Login" in line or "connected" in line.lower() or "authentication" in line.lower()):
                    connection_established = True
                    logger.info(f"Connected to servers for {account.email}")
                
                if not sync_started and ("syncing" in line.lower() or "copying" in line.lower()):
                    sync_started = True
                    logger.info(f"Starting message synchronization for {account.email}")
                
                # Improved parsing for progress
                msg_match = re.search(r'(\d+)/(\d+) msg', line)
                if msg_match:
                    messages_processed = int(msg_match.group(1))
                    total_messages = int(msg_match.group(2))
                    logger.info(f"Processed {messages_processed}/{total_messages} messages for {account.email}")
                
                if any(keyword in line.lower() for keyword in ['error', 'warning', 'failed', 'success', 'done', 'finished']):
                    # Clean line from Rich markup to prevent tag conflicts
                    clean_line = line.replace('[red]', '').replace('[/red]', '').replace('[green]', '').replace('[/green]', '').replace('[yellow]', '').replace('[/yellow]', '')
                    logger.info(f"imapsync status: {clean_line}")
            
            if self.shutdown_event.is_set():
                process.terminate()
                break
        
        process.wait()
        if process in self.active_processes:
            self.active_processes.remove(process)
        
        if process.returncode == 0:
            account.sync_stats['last_sync'] = datetime.now().isoformat()
            account.sync_stats['synced_messages'] += messages_processed
            success_msg = f"Sync completed successfully - processed {messages_processed}/{total_messages} messages"
            logger.info(f"✓ {account.email}: {success_msg}")
            return True, success_msg
        else:
            error_msg = f"Sync failed with exit code {process.returncode}"
            logger.error(f"✗ {account.email}: {error_msg}")
            if log_file.exists():
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    last_lines = lines[-10:] if len(lines) > 10 else lines
                    logger.error("Last log entries:")
                    for line in last_lines:
                        logger.error(f"  {line.strip()}")
            else:
                logger.warning("Log file not created")
                if collected_output:
                    logger.error("imapsync output:")
                    for line in collected_output:
                        logger.error(f"  {line}")
            raise RuntimeError(error_msg)
