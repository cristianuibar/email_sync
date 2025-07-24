import asyncio
import concurrent.futures
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import imaplib
import ssl
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, SpinnerColumn
from rich.table import Table

from config import EmailAccount, ConfigManager
from oauth import OAuth2Manager

console = Console()
logger = logging.getLogger(__name__)

class FolderBatch:
    """Represents a batch of folders to sync"""
    def __init__(self, folders: List[str], account: EmailAccount):
        self.folders = folders
        self.account = account
        self.completed = False
        self.error = None

class ImprovedSyncManager:
    def __init__(self, config_manager: ConfigManager, oauth_manager: Optional[OAuth2Manager], 
                 logs_dir: Path, imapsync_logs_dir: Path, shutdown_event, active_processes):
        self.config_manager = config_manager
        self.oauth_manager = oauth_manager
        self.logs_dir = logs_dir
        self.imapsync_logs_dir = imapsync_logs_dir
        self.shutdown_event = shutdown_event
        self.active_processes = active_processes
        self.sync_state_file = logs_dir / "sync_state.json"
        self.progress_lock = threading.Lock()
        self.account_progress = {}
        
    def load_sync_state(self) -> Dict:
        """Load previous sync state from file"""
        if self.sync_state_file.exists():
            try:
                with open(self.sync_state_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_sync_state(self, state: Dict):
        """Save sync state to file"""
        with open(self.sync_state_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def get_account_folders(self, account: EmailAccount) -> List[str]:
        """Get list of folders for an account using IMAP"""
        try:
            if account.is_office365:
                host = "outlook.office365.com"
                if not self.oauth_manager:
                    return []
                # For Office 365, we'll use a quick IMAP connection to list folders
                # This is faster than running imapsync --justfolders
            else:
                host = f"imap.{account.email.split('@')[1]}"
            
            # Use imapsync --justfolders to get folder list
            cmd = [
                "imapsync",
                "--host1", host,
                "--port1", "993",
                "--ssl1",
                "--user1", account.email,
                "--justfolders",
                "--nocolor",
                "--host2", self.config_manager.dest_config['host'],  # Dummy host2
                "--port2", str(self.config_manager.dest_config['port']),
                "--user2", "dummy@dummy.com",
                "--password2", "dummy"
            ]
            
            if account.is_office365 and self.oauth_manager:
                token = self.oauth_manager.get_valid_token()
                if token:
                    cmd.extend(["--authmech1", "XOAUTH2", "--oauthaccesstoken1", token, "--password1", "dummy"])
            else:
                cmd.extend(["--password1", account.password])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            # Parse folder list from output
            folders = []
            for line in result.stdout.split('\n'):
                # Look for folder listings in imapsync output
                if "Host1 folder" in line and "[" in line and "]" in line:
                    match = re.search(r'\[(.*?)\]', line)
                    if match:
                        folder = match.group(1)
                        # Skip some system folders if needed
                        if folder not in ['Calendar', 'Contacts', 'Tasks', 'Journal', 'Notes']:
                            folders.append(folder)
            
            return folders
            
        except Exception as e:
            logger.error(f"Failed to get folders for {account.email}: {e}")
            return []
    
    def batch_folders(self, folders: List[str], batch_size: int = 10) -> List[List[str]]:
        """Split folders into batches"""
        return [folders[i:i + batch_size] for i in range(0, len(folders), batch_size)]
    
    def run_imapsync_for_folders(self, account: EmailAccount, dest_email: str, dest_password: str,
                                folders: List[str], dry_run: bool = False) -> Tuple[bool, str, List[str]]:
        """Run imapsync for specific folders only"""
        if not shutil.which("imapsync"):
            raise RuntimeError("imapsync not found. Please install it and ensure it's in PATH.")
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = self.imapsync_logs_dir / f"sync_{account.email}_batch_{timestamp}.log"
        
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
            "--errorsmax", "200",  # Increase error tolerance
            "--exitwhenover", "300",  # Exit after 300 errors
        ]
        
        # Add folder filters
        for folder in folders:
            cmd.extend(["--folder", folder])
        
        if dry_run:
            cmd.append("--dry")
        
        if self.config_manager.dest_config.get('ssl', True):
            cmd.append("--ssl2")
            if not self.config_manager.dest_config.get('ssl_verify', True):
                cmd.extend(["--sslargs2", "SSL_verify_mode=0"])
        
        if account.is_office365:
            if not self.oauth_manager:
                return False, "No OAuth manager", []
            
            token = self.oauth_manager.get_valid_token()
            if not token:
                return False, "Failed to get OAuth2 token", []
                
            cmd.extend([
                "--authmech1", "XOAUTH2",
                "--oauthaccesstoken1", token,
                "--password1", "dummy",
                "--buffersize", "8192000",
                "--timeout1", "300",  # Increase timeout
                "--timeout2", "300",
                "--reconnectretry1", "5",  # Retry reconnections
                "--reconnectretry2", "5",
                "--split1", "100",
                "--split2", "100",
                "--skipheader", "Content-Type",
                "--skipheader", "Content-Transfer-Encoding",
                "--noid",
                "--subscribeall",
                "--sep1", "/",
                "--noreleasecheck",
                "--no-modulesversion"
            ])
        else:
            cmd.extend(["--password1", account.password])
        
        logger.info(f"Syncing folders for {account.email}: {folders}")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self.active_processes.append(process)
            
            synced_folders = []
            failed_folders = []
            current_folder = None
            errors_count = 0
            token_expired = False
            
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                    
                if output:
                    line = output.strip()
                    
                    # Track current folder
                    folder_match = re.search(r'Folder\s+\d+/\d+\s+\[(.*?)\]', line)
                    if folder_match:
                        current_folder = folder_match.group(1)
                        
                    # Detect successful folder sync
                    if "++++ Folder" in line and "ended" in line:
                        folder_end_match = re.search(r'\+\+\+\+ Folder \[(.*?)\] ended', line)
                        if folder_end_match:
                            synced_folders.append(folder_end_match.group(1))
                            
                    # Detect token expiration
                    if "AccessTokenExpired" in line or "AUTHENTICATE failed" in line:
                        token_expired = True
                        logger.warning(f"Token expired for {account.email}")
                        
                    # Count errors
                    if "error" in line.lower() or "failed" in line.lower():
                        errors_count += 1
                        if current_folder and current_folder not in failed_folders:
                            failed_folders.append(current_folder)
                            
                if self.shutdown_event.is_set():
                    process.terminate()
                    break
            
            process.wait()
            if process in self.active_processes:
                self.active_processes.remove(process)
            
            # Update progress
            with self.progress_lock:
                if account.email in self.account_progress:
                    self.account_progress[account.email]['synced_folders'].extend(synced_folders)
                    self.account_progress[account.email]['failed_folders'].extend(failed_folders)
            
            if token_expired:
                return False, "Token expired", failed_folders
            elif process.returncode == 0:
                return True, f"Synced {len(synced_folders)} folders", []
            else:
                return False, f"Exit code {process.returncode}, {errors_count} errors", failed_folders
                
        except Exception as e:
            logger.error(f"Error syncing folders for {account.email}: {e}")
            return False, str(e), folders
    
    def sync_account_parallel(self, account: EmailAccount, dest_email: str, dest_password: str,
                            dry_run: bool, max_workers: int = 3) -> Tuple[bool, str]:
        """Sync an account using parallel folder batches"""
        
        # Initialize progress tracking
        with self.progress_lock:
            self.account_progress[account.email] = {
                'total_folders': 0,
                'synced_folders': [],
                'failed_folders': [],
                'start_time': datetime.now()
            }
        
        # Get folders for the account
        console.print(f"[blue]Getting folder list for {account.email}...[/blue]")
        folders = self.get_account_folders(account)
        
        if not folders:
            # If can't get folders, fall back to syncing all
            console.print(f"[yellow]Could not get folder list, syncing all folders[/yellow]")
            return self.run_imapsync_all_folders(account, dest_email, dest_password, dry_run)
        
        console.print(f"[green]Found {len(folders)} folders to sync[/green]")
        
        with self.progress_lock:
            self.account_progress[account.email]['total_folders'] = len(folders)
        
        # Load previous sync state
        sync_state = self.load_sync_state()
        account_state = sync_state.get(account.email, {})
        previously_synced = set(account_state.get('synced_folders', []))
        
        # Filter out already synced folders if resuming
        folders_to_sync = [f for f in folders if f not in previously_synced]
        
        if len(folders_to_sync) < len(folders):
            console.print(f"[cyan]Resuming sync: {len(previously_synced)} folders already synced[/cyan]")
        
        # Batch the folders
        folder_batches = self.batch_folders(folders_to_sync, batch_size=5)
        
        # Sync batches in parallel
        failed_batches = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all batches
            future_to_batch = {}
            for i, batch in enumerate(folder_batches):
                future = executor.submit(
                    self.run_imapsync_for_folders,
                    account, dest_email, dest_password, batch, dry_run
                )
                future_to_batch[future] = (i, batch)
            
            # Process completed batches
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console
            ) as progress:
                
                task = progress.add_task(
                    f"[cyan]Syncing {account.email}",
                    total=len(folder_batches)
                )
                
                for future in as_completed(future_to_batch):
                    batch_idx, batch_folders = future_to_batch[future]
                    
                    try:
                        success, message, failed_folders = future.result()
                        
                        if success:
                            # Update sync state
                            account_state['synced_folders'] = list(
                                set(account_state.get('synced_folders', [])) | set(batch_folders)
                            )
                            sync_state[account.email] = account_state
                            self.save_sync_state(sync_state)
                        else:
                            failed_batches.append((batch_idx, batch_folders, message))
                            
                            # If token expired, cancel remaining tasks
                            if "Token expired" in message:
                                console.print(f"[red]Token expired, refreshing...[/red]")
                                # Refresh token
                                if self.oauth_manager:
                                    self.oauth_manager.refresh_access_token()
                                
                    except Exception as e:
                        logger.error(f"Batch {batch_idx} failed: {e}")
                        failed_batches.append((batch_idx, batch_folders, str(e)))
                    
                    progress.update(task, advance=1)
        
        # Retry failed batches with fresh token
        if failed_batches and account.is_office365 and self.oauth_manager:
            console.print(f"[yellow]Retrying {len(failed_batches)} failed batches...[/yellow]")
            
            for batch_idx, batch_folders, error in failed_batches:
                success, message, _ = self.run_imapsync_for_folders(
                    account, dest_email, dest_password, batch_folders, dry_run
                )
                
                if success:
                    account_state['synced_folders'] = list(
                        set(account_state.get('synced_folders', [])) | set(batch_folders)
                    )
                    sync_state[account.email] = account_state
                    self.save_sync_state(sync_state)
        
        # Final summary
        with self.progress_lock:
            progress_info = self.account_progress[account.email]
            synced_count = len(progress_info['synced_folders'])
            failed_count = len(progress_info['failed_folders'])
            
        if failed_count == 0:
            return True, f"Successfully synced all {synced_count} folders"
        else:
            return False, f"Synced {synced_count} folders, {failed_count} failed"
    
    def run_imapsync_all_folders(self, account: EmailAccount, dest_email: str, dest_password: str,
                                dry_run: bool) -> Tuple[bool, str]:
        """Fallback method to sync all folders at once"""
        if not shutil.which("imapsync"):
            raise RuntimeError("imapsync not found. Please install it and ensure it's in PATH.")
        
        log_file = self.imapsync_logs_dir / f"sync_{account.email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
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
            "--errorsmax", "200",
        ]
        
        if dry_run:
            cmd.append("--dry")
        
        if self.config_manager.dest_config.get('ssl', True):
            cmd.append("--ssl2")
            if not self.config_manager.dest_config.get('ssl_verify', True):
                cmd.extend(["--sslargs2", "SSL_verify_mode=0"])
        
        if account.is_office365:
            if not self.oauth_manager:
                return False, "No OAuth manager"
                
            token = self.oauth_manager.get_valid_token()
            if not token:
                return False, "Failed to get OAuth2 token"
                
            cmd.extend([
                "--authmech1", "XOAUTH2",
                "--oauthaccesstoken1", token,
                "--password1", "dummy",
                "--buffersize", "8192000",
                "--timeout1", "300",
                "--timeout2", "300",
                "--split1", "100",
                "--split2", "100",
                "--skipheader", "Content-Type",
                "--skipheader", "Content-Transfer-Encoding",
                "--noid",
                "--subscribeall",
                "--sep1", "/",
                "--noreleasecheck",
                "--no-modulesversion"
            ])
        else:
            cmd.extend(["--password1", account.password])
        
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode == 0:
            return True, "Sync completed successfully"
        else:
            return False, f"Sync failed with exit code {process.returncode}"
    
    def sync_accounts_parallel(self, debug: bool = False, dry_run: bool = False, max_parallel: int = 5):
        """Sync all accounts in parallel"""
        
        if not self.config_manager.dest_config:
            console.print("[red]❌ Global configuration not loaded. Please run setup first.[/red]")
            return
            
        accounts = self.config_manager.accounts
        if not accounts:
            console.print("[red]No accounts configured. Please run setup first.[/red]")
            return
        
        console.print(f"[bold blue]Starting parallel synchronization of {len(accounts)} accounts[/bold blue]")
        console.print(f"[dim]Running up to {max_parallel} accounts simultaneously[/dim]")
        
        # Test destination connection
        console.print("[yellow]Testing destination server connection...[/yellow]")
        dest_config = self.config_manager.dest_config
        
        try:
            context = ssl.create_default_context()
            if not dest_config.get('ssl_verify', True):
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                
            with imaplib.IMAP4_SSL(dest_config['host'], dest_config['port'], ssl_context=context):
                console.print("[green]✓ Destination server connection successful[/green]")
        except Exception as e:
            console.print(f"[red]✗ Failed to connect to destination server: {e}[/red]")
            return
        
        dest_passwords = self.config_manager.dest_config.get('passwords', {})
        
        # Create account tasks
        account_tasks = []
        for account in accounts:
            dest_email = account.dest_email
            dest_password = dest_passwords.get(dest_email)
            
            if not dest_password:
                console.print(f"[red]❌ Missing password for {dest_email}[/red]")
                continue
                
            account_tasks.append((account, dest_email, dest_password))
        
        # Create summary table
        table = Table(title="Sync Progress", show_header=True, header_style="bold magenta")
        table.add_column("Account", style="cyan", no_wrap=True)
        table.add_column("Status", style="green")
        table.add_column("Progress", justify="right")
        table.add_column("Time", justify="right")
        
        results = {}
        
        with Live(table, console=console, refresh_per_second=1) as live:
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                # Submit all tasks
                future_to_account = {}
                for account, dest_email, dest_password in account_tasks:
                    future = executor.submit(
                        self.sync_account_parallel,
                        account, dest_email, dest_password, dry_run, max_workers=2
                    )
                    future_to_account[future] = account
                    
                    # Update table
                    table.add_row(
                        account.email,
                        "[yellow]⏳ Queued[/yellow]",
                        "0%",
                        "00:00"
                    )
                
                # Process completed accounts
                completed = 0
                for future in as_completed(future_to_account):
                    account = future_to_account[future]
                    completed += 1
                    
                    try:
                        success, message = future.result()
                        results[account.email] = (success, message)
                        
                        # Update table row
                        for i, row in enumerate(table.rows):
                            if row[0] == account.email:
                                if success:
                                    table.rows[i] = [
                                        account.email,
                                        "[green]✓ Complete[/green]",
                                        "100%",
                                        str(datetime.now() - self.account_progress[account.email]['start_time']).split('.')[0]
                                    ]
                                else:
                                    table.rows[i] = [
                                        account.email,
                                        "[red]✗ Failed[/red]",
                                        "-",
                                        str(datetime.now() - self.account_progress[account.email]['start_time']).split('.')[0]
                                    ]
                                break
                                
                    except Exception as e:
                        results[account.email] = (False, str(e))
                        logger.error(f"Error syncing {account.email}: {e}")
                    
                    # Update remaining accounts status
                    remaining = len(account_tasks) - completed
                    if remaining > 0:
                        for i, row in enumerate(table.rows):
                            if "[yellow]⏳ Queued[/yellow]" in str(row[1]):
                                table.rows[i][1] = f"[cyan]⏳ Running ({remaining} queued)[/cyan]"
                                break
                    
                    live.update(table)
        
        # Print summary
        console.print("\n[bold]Synchronization Summary:[/bold]")
        successful = sum(1 for success, _ in results.values() if success)
        failed = len(results) - successful
        
        if successful > 0:
            console.print(f"[green]✓ {successful} accounts synced successfully[/green]")
        if failed > 0:
            console.print(f"[red]✗ {failed} accounts failed[/red]")
            
        # Show details for failed accounts
        for email, (success, message) in results.items():
            if not success:
                console.print(f"  [red]• {email}: {message}[/red]")
        
        # Save configuration
        self.config_manager.save_configuration(self.oauth_manager)
        console.print("\n[bold green]🎉 Synchronization complete![/bold green]")
