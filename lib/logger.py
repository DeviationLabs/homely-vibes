"""Generic logging configuration for the water tracking system."""

import logging
import os
import sys
from pathlib import Path
from typing import Optional
from lib import Constants


class SystemLogger:
    """Centralized logger configuration for all water tracking modules."""

    _initialized = False

    @classmethod
    def setup(
        cls,
        level: int = logging.INFO,
        console_output: bool = True,
        format_string: Optional[str] = None,
    ) -> None:
        """Set up logging configuration for the entire application.

        Args:
            level: Logging level (default: INFO)
            console_output: Whether to output to console (default: True)
            format_string: Custom format string (optional)
        """
        if cls._initialized:
            return

        # Default format
        if format_string is None:
            format_string = (
                "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"
            )

        # Clear any existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Set root level
        root_logger.setLevel(level)

        formatter = logging.Formatter(format_string)

        # Console handler
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        cls._initialized = True

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger instance for a specific module with automatic file logging.

        Args:
            name: Module name (typically __name__)

        Returns:
            Configured logger instance with file handler for this module
        """
        if not cls._initialized:
            cls.setup()

        # Get logger for this module
        logger = logging.getLogger(name)
        
        # Check if this logger already has file handlers to avoid duplicates
        has_file_handler = any(isinstance(h, logging.FileHandler) for h in logger.handlers)
        if has_file_handler:
            return logger
        
        # Create module-specific log file in LOGGING_DIR
        logs_dir = Path(Constants.LOGGING_DIR)
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Use filename for log file when module is __main__
        if name == '__main__':
            # Extract filename from the main module
            import __main__
            if hasattr(__main__, '__file__') and __main__.__file__:
                file_path = Path(__main__.__file__)
                module_name = file_path.stem  # Get filename without extension
            else:
                module_name = 'main'
        else:
            # Use module name for log file (replace dots with underscores)
            module_name = name.replace('.', '_')
        
        log_file_path = logs_dir / f"{module_name}.log"
        
        # Add file handler for this specific module
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(logging.INFO)
        
        # Use same formatter as console
        if logger.parent and logger.parent.handlers:
            formatter = logger.parent.handlers[0].formatter
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"
            )
        file_handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(file_handler)
        
        return logger

    @classmethod
    def reset(cls) -> None:
        """Reset logger configuration (mainly for testing)."""
        cls._initialized = False

        # Clear all handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.WARNING)  # Reset to default

    @classmethod
    def set_level(cls, level: int) -> None:
        """Change logging level for all loggers.

        Args:
            level: New logging level
        """
        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        # Update all handlers
        for handler in root_logger.handlers:
            handler.setLevel(level)



# Convenience function for simple usage
def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with default configuration.

    Args:
        name: Module name (typically __name__)

    Returns:
        Configured logger instance
    """
    return SystemLogger.get_logger(name)
