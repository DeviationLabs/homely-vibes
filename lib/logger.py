"""Generic logging configuration for the water tracking system."""

import logging
import os
import sys
from pathlib import Path
from typing import Optional


class SystemLogger:
    """Centralized logger configuration for all water tracking modules."""

    _initialized = False
    _log_file: Optional[Path] = None

    @classmethod
    def setup(
        cls,
        level: int = logging.INFO,
        log_file: Optional[str] = None,
        console_output: bool = True,
        format_string: Optional[str] = None,
        default_log_dir: str = "~/logs",
    ) -> None:
        """Set up logging configuration for the entire application.

        Args:
            level: Logging level (default: INFO)
            log_file: Optional file path for log output (if relative, uses default_log_dir)
            console_output: Whether to output to console (default: True)
            format_string: Custom format string (optional)
            default_log_dir: Default directory for log files (default: ~/logs)
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

        # File handler
        if log_file:
            # Handle relative paths by using default_log_dir
            if not os.path.isabs(log_file):
                log_dir = os.path.expanduser(default_log_dir)
                cls._log_file = Path(log_dir) / log_file
            else:
                cls._log_file = Path(log_file)

            cls._log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(cls._log_file)
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

        cls._initialized = True

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger instance for a specific module.

        Args:
            name: Module name (typically __name__)

        Returns:
            Configured logger instance
        """
        if not cls._initialized:
            cls.setup()

        return logging.getLogger(name)

    @classmethod
    def reset(cls) -> None:
        """Reset logger configuration (mainly for testing)."""
        cls._initialized = False
        cls._log_file = None

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

    @classmethod
    def add_file_output(cls, log_file: str) -> None:
        """Add file output to existing logger configuration.

        Args:
            log_file: Path to log file
        """
        if cls._log_file:
            return  # File handler already exists

        cls._log_file = Path(log_file)
        cls._log_file.parent.mkdir(parents=True, exist_ok=True)

        root_logger = logging.getLogger()

        # Use same format as existing handlers
        formatter = None
        if root_logger.handlers:
            formatter = root_logger.handlers[0].formatter
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"
            )

        file_handler = logging.FileHandler(cls._log_file)
        file_handler.setLevel(root_logger.level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


# Convenience function for simple usage
def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with default configuration.

    Args:
        name: Module name (typically __name__)

    Returns:
        Configured logger instance
    """
    return SystemLogger.get_logger(name)
