import json
import logging
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs structured JSON logs.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        if record.exc_info:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }

        if hasattr(record, 'extra_data'):
            log_entry['data'] = record.extra_data

        return json.dumps(log_entry, ensure_ascii=False, cls=CustomJSONEncoder)


class AppLogger:
    """
    Centralized logging configuration for the application.
    """
    def __init__(self,
                 log_directory: str = "logs",
                 console_level: str = "INFO",
                 file_level: str = "DEBUG",
                 max_file_size: int = 10 * 1024 * 1024,
                 backup_count: int = 5):
        self.log_directory = Path(log_directory)
        self.console_level = getattr(logging, console_level.upper())
        self.file_level = getattr(logging, file_level.upper())
        self.max_file_size = max_file_size
        self.backup_count = backup_count

        self.log_directory.mkdir(exist_ok=True)
        self._setup_logging()

    def _setup_logging(self) -> None:
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.DEBUG)

        logging.getLogger("httpx").setLevel(logging.WARNING)

        self._setup_console_handler(root_logger)
        self._setup_main_file_handler(root_logger)
        self._setup_error_file_handler(root_logger)
        self._setup_api_log_handler()

    def _setup_console_handler(self, logger: logging.Logger) -> None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.console_level)
        console_format = '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
        console_formatter = logging.Formatter(console_format, datefmt='%H:%M:%S')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    def _setup_main_file_handler(self, logger: logging.Logger) -> None:
        from logging.handlers import RotatingFileHandler
        system_log_dir = self.log_directory / "system"
        system_log_dir.mkdir(exist_ok=True)
        main_log_file = system_log_dir / "app.log"

        file_handler = RotatingFileHandler(
            main_log_file,
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(self.file_level)
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)

    def _setup_error_file_handler(self, logger: logging.Logger) -> None:
        from logging.handlers import RotatingFileHandler
        error_log_dir = self.log_directory / "errors"
        error_log_dir.mkdir(exist_ok=True)
        error_log_file = error_log_dir / "errors.log"

        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.WARNING)
        error_handler.setFormatter(JSONFormatter())
        logger.addHandler(error_handler)

    def _setup_api_log_handler(self) -> None:
        from logging.handlers import RotatingFileHandler
        api_logger = logging.getLogger('app.api')
        api_log_dir = self.log_directory / "api"
        api_log_dir.mkdir(exist_ok=True)
        api_log_file = api_log_dir / "api_calls.log"

        api_handler = RotatingFileHandler(
            api_log_file,
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        api_handler.setLevel(logging.DEBUG)
        api_handler.setFormatter(JSONFormatter())
        api_logger.propagate = False
        api_logger.addHandler(api_handler)
        
        # Also add console handler for immediate feedback
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.console_level)
        console_format = '%(asctime)s | API | %(levelname)-8s | %(message)s'
        console_formatter = logging.Formatter(console_format, datefmt='%H:%M:%S')
        console_handler.setFormatter(console_formatter)
        api_logger.addHandler(console_handler)


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(Enum):
    CURRENCY_VALIDATION = "currency_validation"
    API_CALL = "api_call"
    CIRCUIT_BREAKER = "circuit_breaker"
    CACHE_OPERATION = "cache_operation"
    RATE_AGGREGATION = "rate_aggregation"
    USER_REQUEST = "user_request"
    DATABASE_OPERATION = "database_operation"
    SERVICE_LIFECYCLE = "service_lifecycle"
    HEALTH_CHECK = "health_check"


@dataclass
class LogEvent:
    event_type: EventType
    level: LogLevel
    message: str
    timestamp: datetime
    duration_ms: float | None = None
    user_context: dict[str, Any] | None = None
    api_context: dict[str, Any] | None = None
    performance_context: dict[str, Any] | None = None
    error_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['event_type'] = self.event_type.value
        data['level'] = self.level.value
        return data


class ProductionLogger:
    def __init__(self):
        self.system_logger = logging.getLogger()  # Root logger for general events
        self.api_logger = logging.getLogger('app.api') # API-specific logger

    def log_event(self, event: LogEvent):
        logger = self.api_logger if event.event_type in [EventType.API_CALL, EventType.CIRCUIT_BREAKER] else self.system_logger
        
        extra = {"extra_data": event.to_dict()}

        level_map = {
            LogLevel.DEBUG: logger.debug,
            LogLevel.INFO: logger.info,
            LogLevel.WARNING: logger.warning,
            LogLevel.ERROR: logger.error,
            LogLevel.CRITICAL: logger.critical,
        }
        
        log_func = level_map.get(event.level, logger.info)
        log_func(event.message, extra=extra)

    def log_currency_validation(self, from_currency: str, to_currency: str,
                                validation_result: dict[str, Any],  duration_ms: float):
        event = LogEvent(
            event_type=EventType.CURRENCY_VALIDATION,
            level=LogLevel.INFO if validation_result['valid'] else LogLevel.WARNING,
            message=f"Currency validation: {from_currency}->{to_currency} ({'valid' if validation_result['valid'] else 'invalid -not yet in validation cache'})",
            timestamp=datetime.now(),
            duration_ms=duration_ms,
            user_context={
                "from_currency": from_currency,
                "to_currency": to_currency,
                "validation_result": validation_result
            },
            performance_context={
                "validation_duration_ms": duration_ms,
                "cache_hit": validation_result.get('cache_hit', False),
                "db_lookup_required": validation_result.get('db_lookup_required', False)
            }
        )
        self.log_event(event)

    def log_api_call(self, provider_name: str, endpoint: str, success: bool, response_time_ms: float,
                     error_message: str | None = None, rate_data: dict[str, Any] | None = None):
        event = LogEvent(
            event_type=EventType.API_CALL,
            level=LogLevel.INFO if success else LogLevel.ERROR,
            message=f"API call to {provider_name}/{endpoint}: {'SUCCESS' if success else 'FAILED'}",
            timestamp=datetime.now(),
            duration_ms=response_time_ms,
            api_context={
                "provider": provider_name,
                "endpoint": endpoint,
                "success": success,
                "response_time_ms": response_time_ms,
                "rate_data": rate_data
            },
            error_context={"error_message": error_message} if error_message else None
        )
        self.log_event(event)

    def log_circuit_breaker_event(self, provider_name: str, old_state: str, 
                                 new_state: str, failure_count: int, reason: str):
        event = LogEvent(
            event_type=EventType.CIRCUIT_BREAKER,
            level=LogLevel.WARNING if new_state == "OPEN" else LogLevel.INFO,
            message=f"Circuit breaker {provider_name}: {old_state} -> {new_state} ({reason})",
            timestamp=datetime.now(),
            api_context={
                "provider": provider_name,
                "old_state": old_state,
                "new_state": new_state,
                "failure_count": failure_count,
                "reason": reason
            }
        )
        self.log_event(event)

    def log_cache_operation(self, operation: str, cache_key: str, hit: bool, 
                          duration_ms: float, data_age_minutes: int | None = None,
                          level: LogLevel = LogLevel.DEBUG, error_message: str | None = None):
        message = f"Cache {operation} for {cache_key}: {'HIT' if hit else 'MISS'}"
        if error_message:
            message += f" - ERROR: {error_message}"

        event = LogEvent(
            event_type=EventType.CACHE_OPERATION,
            level=level,
            message=message,
            timestamp=datetime.now(),
            duration_ms=duration_ms,
            performance_context={
                "operation": operation,
                "cache_key": cache_key,
                "hit": hit,
                "duration_ms": duration_ms,
                "data_age_minutes": data_age_minutes
            },
            error_context={"error_message": error_message} if error_message else None
        )
        self.log_event(event)
    
    def log_rate_aggregation(self, base: str, target: str, final_rate: float, 
                           confidence_level: str, sources_used: list[str],
                           is_primary_used: bool, was_cached: bool, 
                           total_duration_ms: float, warnings: list[str] | None = None):
        event = LogEvent(
            event_type=EventType.RATE_AGGREGATION,
            level=LogLevel.WARNING if confidence_level == "low" else LogLevel.INFO,
            message=f"Rate aggregation {base}->{target}: {final_rate} ({confidence_level} confidence)",
            timestamp=datetime.now(),
            duration_ms=total_duration_ms,
            user_context={
                "base_currency": base,
                "target_currency": target,
                "final_rate": final_rate,
                "confidence_level": confidence_level
            },
            api_context={
                "sources_used": sources_used,
                "primary_provider_used": is_primary_used,
                "was_cached": was_cached,
                "warnings": warnings or []
            },
            performance_context={
                "total_duration_ms": total_duration_ms,
                "cache_hit": was_cached
            }
        )
        self.log_event(event)

    def log_user_request(self, endpoint: str, request_data: dict[str, Any],
                        success: bool, response_time_ms: float, 
                        error_message: str | None = None):
        event = LogEvent(
            event_type=EventType.USER_REQUEST,
            level=LogLevel.INFO if success else LogLevel.ERROR,
            message=f"User request to {endpoint}: {'SUCCESS' if success else 'FAILED'}",
            timestamp=datetime.now(),
            duration_ms=response_time_ms,
            user_context={
                "endpoint": endpoint,
                "request_data": request_data,
                "success": success
            },
            performance_context={"response_time_ms": response_time_ms},
            error_context={"error_message": error_message} if error_message else None
        )
        self.log_event(event)
    
    @contextmanager
    def time_operation(self, operation_name: str):
        start_time = time.time()
        try:
            yield
        finally:
            duration_ms = (time.time() - start_time) * 1000
            self.system_logger.debug(f"{operation_name} took {duration_ms:.2f}ms")


# Global logger instances
app_logger: AppLogger | None = None
production_logger: ProductionLogger | None = None


def get_production_logger() -> ProductionLogger:
    global app_logger, production_logger
    if app_logger is None:
        app_logger = AppLogger()
    if production_logger is None:
        production_logger = ProductionLogger()
    return production_logger
