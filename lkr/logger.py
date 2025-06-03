import logging
import os

import structlog
from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

from lkr.custom_types import LogLevel

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

# Define a custom theme for our logging
theme = Theme(
    {
        "logging.level.debug": "dim blue",
        "logging.level.info": "bold green",
        "logging.level.warning": "bold yellow",
        "logging.level.error": "bold red",
        "logging.level.critical": "bold white on red",
    }
)

# Create a console for logging
console = Console(theme=theme)

# Configure the logging handler
handler = RichHandler(
    console=console,
    show_time=True,
    show_path=True,
    markup=True,
    rich_tracebacks=True,
    tracebacks_show_locals=True,
)

# Get log level from environment variable, defaulting to INFO
DEFAULT_LOG_LEVEL = "INFO"
log_level = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()

# Configure the root logger
logging.basicConfig(
    level=getattr(
        logging, log_level, logging.INFO
    ),  # Fallback to INFO if invalid level
    format="%(message)s",
    datefmt="[%X]",
    handlers=[handler],
)

# Create a logger for the application
logger = logging.getLogger("lkr")
structured_logger = structlog.get_logger("lkr.structured")


# Configure the requests_transport logger to only show debug messages when LOG_LEVEL is DEBUG
requests_logger = logging.getLogger("looker_sdk.rtl.requests_transport")
if log_level != "DEBUG":
    requests_logger.setLevel(logging.WARNING)


def set_log_level(level: LogLevel):
    """Set the logging level for the application."""
    logger.setLevel(getattr(logging, level.value))
    logging.getLogger("lkr.structured").setLevel(getattr(logging, level.value))
    # Update requests_transport logger level based on the new level
    requests_logger.setLevel(
        logging.DEBUG if level == LogLevel.DEBUG else logging.WARNING
    )
