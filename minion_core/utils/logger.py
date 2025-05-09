import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def setup_logger(name, log_file, level=logging.INFO, add_console_handler=True):
    """Sets up a logger instance."""
    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except OSError as e:
            print(f"CRITICAL: Could not create log directory {log_dir}. Error: {e}", file=sys.stderr)
            # Depending on desired robustness, might exit or raise
            # For now, we'll let it fail on handler creation if dir is truly unwritable.

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # File Handler (Rotating)
    # Max 5MB per file, keep 5 backup files
    try:
        file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
        file_handler.setFormatter(formatter)
    except Exception as e:
        print(f"CRITICAL: Could not create file handler for {log_file}. Error: {e}", file=sys.stderr)
        # Fallback to console only if file logging fails critically
        logger = logging.getLogger(name)
        logger.setLevel(level)
        if not logger.handlers: # Avoid duplicate console handlers if already set up
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(formatter)
            logger.addHandler(ch)
        logger.error(f"File logging to {log_file} failed. Logging to console only for this logger.")
        return logger

    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Clear existing handlers to prevent duplication if this function is called multiple times for the same logger name
    if logger.hasHandlers():
        logger.handlers.clear()
        
    logger.addHandler(file_handler)
    
    if add_console_handler:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    return logger

# BIAS_CHECK: Considered simpler logging, opted for RotatingFileHandler for robustness against large log files.
# BIAS_ACTION: Added error handling for logger setup itself to prevent silent failures.
