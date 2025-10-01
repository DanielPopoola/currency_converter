import sys
from enum import Enum
from pathlib import Path

from loguru import logger


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


logger.remove()

# 2. Configure a simple, colored console logger for development
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>",
    colorize=True
)

# 3. Define file sinks with rotation and JSON formatting
log_dir = Path("logs")
(log_dir / "system").mkdir(parents=True, exist_ok=True)
(log_dir / "errors").mkdir(parents=True, exist_ok=True)
(log_dir / "api").mkdir(parents=True, exist_ok=True)


# General application log (system.log)
logger.add(
    log_dir / "system" / "app.log",
    level="DEBUG",
    serialize=True,  # This enables structured JSON logging
    rotation="10 MB",
    retention="5 days",
    catch=True,
    # Filter to EXCLUDE logs intended for the API log
    filter=lambda record: "api_call" not in record["extra"]
)

# Error log (errors.log)
logger.add(
    log_dir / "errors" / "errors.log",
    level="WARNING",
    serialize=True,
    rotation="10 MB",
    retention="5 days",
    catch=True
)

# API calls log (api_calls.log)
logger.add(
    log_dir / "api" / "api_calls.log",
    level="DEBUG",
    serialize=True,
    rotation="10 MB",
    retention="5 days",
    catch=True,
    # Filter to INCLUDE ONLY logs with 'api_call' in extra
    filter=lambda record: "api_call" in record["extra"]
)
