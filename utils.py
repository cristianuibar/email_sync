import logging
import signal
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console()

def setup_logging(debug: bool = False, sync_log: Path = None) -> logging.Logger:
    log_level = logging.DEBUG if debug else logging.INFO
    
    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Set up file handler for all logs
    file_handler = logging.FileHandler(sync_log)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    # Set up console handler for only warnings and errors
    console_handler = RichHandler(console=console, show_time=False, show_path=False)
    console_handler.setLevel(logging.WARNING)  # Only show WARNING and ERROR in console
    console_handler.setFormatter(logging.Formatter('%(message)s'))  # Clean format for console
    
    # Configure root logger
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)

def signal_handler(shutdown_event, active_processes):
    def handler(signum, frame):
        console.print("\n[yellow]Received shutdown signal. Cleaning up...[/yellow]")
        shutdown_event.set()
        for proc in active_processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except:
                try:
                    proc.kill()
                except:
                    pass
        console.print("[green]Cleanup complete. Goodbye![/green]")
        sys.exit(0) 