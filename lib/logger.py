"""Generic logging configuration for the water tracking system."""

import logging
import sys
from pathlib import Path
from typing import Optional
from lib import Constants


class SystemLogger:
    """Centralized logger configuration for all water tracking modules."""

    _initialized = False
    _shared_log_file = None

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

        # Determine main script name for shared log file
        if cls._shared_log_file is None:
            main_script = cls._get_main_script_name()
            logs_dir = Path(Constants.LOGGING_DIR)
            logs_dir.mkdir(parents=True, exist_ok=True)
            cls._shared_log_file = logs_dir / f"{main_script}.log"

        # Default format
        if format_string is None:
            format_string = (
                "%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s"
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

        # Shared file handler for all loggers
        file_handler = logging.FileHandler(cls._shared_log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        cls._initialized = True

    @classmethod
    def _get_main_script_name(cls) -> str:
        """Get the name of the main script being executed."""
        try:
            import __main__

            if hasattr(__main__, "__file__") and __main__.__file__:
                return Path(__main__.__file__).name
        except (ImportError, AttributeError):
            pass

        # Fallback to sys.argv[0] if __main__.__file__ not available
        if sys.argv and sys.argv[0]:
            return Path(sys.argv[0]).name

        # Last resort fallback
        return "application"

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger instance that uses the shared log file.

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
        cls._shared_log_file = None

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
