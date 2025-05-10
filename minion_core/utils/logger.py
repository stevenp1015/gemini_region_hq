import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def setup_logger(name, log_file, level=logging.INFO, add_console_handler=True):
    """Sets up a logger instance with a unique file handler for the specified log_file."""
    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir): # Added check for log_dir to handle relative paths like "app.log"
        try:
            os.makedirs(log_dir)
        except OSError as e:
            print(f"CRITICAL: Could not create log directory {log_dir}. Error: {e}", file=sys.stderr)
            # Fallback to console-only if directory creation fails
            logger = logging.getLogger(name)
            logger.setLevel(level)
            if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
                ch = logging.StreamHandler(sys.stdout)
                ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
                logger.addHandler(ch)
            logger.error(f"Log directory {log_dir} creation failed. Logging to console only for {name}.")
            return logger

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Ensure logger doesn't propagate to root logger if it's a custom one,
    # to prevent duplicate messages if root is also configured.
    # This is generally good practice for library-like loggers.
    if name != "root": # Or some other condition if you have a specific root logger name
        logger.propagate = False

    # Resolve to absolute path for consistent handler checking
    abs_log_file = os.path.abspath(log_file)

    # Check if a file handler for this specific log_file already exists
    file_handler_exists = False
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == abs_log_file:
            file_handler_exists = True
            break
    
    if not file_handler_exists:
        try:
            # File Handler (Rotating)
            # Max 5MB per file, keep 5 backup files
            file_handler = RotatingFileHandler(abs_log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"CRITICAL: Could not create file handler for {abs_log_file}. Error: {e}", file=sys.stderr)
            # Fallback to console if file handler creation fails for this specific logger
            if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
                ch = logging.StreamHandler(sys.stdout) # Ensure console handler exists
                ch.setFormatter(formatter)
                logger.addHandler(ch)
            logger.error(f"File logging to {abs_log_file} failed for {name}. Logging to console for this logger if not already.")
            # Do not return here, allow console handler to be added if requested and not present

    if add_console_handler:
        console_handler_exists = any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
        if not console_handler_exists:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
            
    return logger

# BIAS_CHECK: Considered simpler logging, opted for RotatingFileHandler for robustness against large log files.
# BIAS_ACTION: Added error handling for logger setup itself to prevent silent failures.
