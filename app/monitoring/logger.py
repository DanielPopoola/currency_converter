import json
import logging
import time
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass, asdict
from contextlib import contextmanager


from app.config.database import DatabaseManager
from app.database.models import APICallLog, ExchangeRate


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(Enum):
    """Different types of events we want to track"""
    CURRENCY_VALIDATION = "currency_validation"
    API_CALL = "api_call"
    CIRCUIT_BREAKER = "circuit_breaker"
    CACHE_OPERATION = "cache_operation"
    RATE_AGGREGATION = "rate_aggregation"
    USER_REQUEST = "user_request"


@dataclass
class LogEvent:
    """Structured log event with all the context needed"""
    event_type: EventType
    level: LogLevel
    message: str
    timestamp: datetime
    duration_ms: Optional[float] = None

    # Context data (varies by event type)
    user_context: Optional[Dict[str, Any]] = None
    api_context: Optional[Dict[str, Any]] = None
    performance_context: Optional[Dict[str, Any]] = None
    error_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON logging"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['event_type'] = self.event_type.value
        data['level'] = self.level.value
        return data
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), default=str)
    


class ProductionLogger:
    """Enhanced logger for production monitoring and debugging"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger("currency_converter")

        self._setup_structured_logging()

    def _setup_structured_logging(self):
        """Configure JSON structured logging"""
        # Create custom formatter for JSON logs
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_data = {
                    "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "module": record.module,
                    "function": record.funcName,
                    "line": record.lineno
                }

                # Add structured data if present
                if hasattr(record, 'structured_data'):
                    log_data.update(record.structured_data)

                return json.dumps(log_data)
            
        # Add JSON handler
        json_handler = logging.StreamHandler()
        json_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(json_handler)
        self.logger.setLevel(logging.INFO)

    def log_event(self, event: LogEvent):
        """Log a structured event"""
        # Log to standard logger with structured data
        extra = {"structured_data": event.to_dict()}

        if event.level == LogLevel.DEBUG:
            self.logger.debug(event.message, extra=extra)
        elif event.level == LogLevel.INFO:
            self.logger.info(event.message, extra=extra)
        elif event.level == LogLevel.WARNING:
            self.logger.warning(event.message, extra=extra)
        elif event.level == LogLevel.ERROR:
            self.logger.error(event.message, extra=extra)
        elif event.level == LogLevel.CRITICAL:
            self.logger.critical(event.message, extra=extra)

    def log_currency_validation(self, from_currency: str, to_currency: str,
                                validation_result: Dict[str, Any],  duration_ms: float):
        """Log currency validation events with performance metrics"""
        event = LogEvent(
            event_type=EventType.CURRENCY_VALIDATION,
            level=LogLevel.INFO if validation_result['valid'] else LogLevel.WARNING,
            message=f"Currency validation: {from_currency}->{to_currency} ({'valid' if validation_result['valid'] else 'invalid'})",
            timestamp=datetime.now(UTC),
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
                     error_message: Optional[str] = None, rate_data: Optional[Dict[str, Any]] = None):
        """Log API calls with detailed context"""
        event = LogEvent(
            event_type=EventType.API_CALL,
            level=LogLevel.INFO if success else LogLevel.ERROR,
            message=f"API call to {provider_name}/{endpoint}: {'SUCCESS' if success else 'FAILED'}",
            timestamp=datetime.now(UTC),
            duration_ms=response_time_ms,
            api_context={
                "provider": provider_name,
                "endpoint": endpoint,
                "success": success,
                "response_time_ms": response_time_ms,
                "rate_data": rate_data
            },
            error_context={
                "error_message": error_message,
            } if error_message else None
        )

        self.log_event(event)

    def log_circuit_breaker_event(self, provider_name: str, old_state: str, 
                                 new_state: str, failure_count: int, reason: str):
        """Log circuit breaker state changes"""
        event = LogEvent(
            event_type=EventType.CIRCUIT_BREAKER,
            level=LogLevel.WARNING if new_state == "OPEN" else LogLevel.INFO,
            message=f"Circuit breaker {provider_name}: {old_state} -> {new_state} ({reason})",
            timestamp=datetime.now(UTC),
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
                          duration_ms: float, data_age_minutes: Optional[int] = None):
        """Log cache operations (hit/miss/set)"""
        event = LogEvent(
            event_type=EventType.CACHE_OPERATION,
            level=LogLevel.DEBUG,
            message=f"Cache {operation} for {cache_key}: {'HIT' if hit else 'MISS'}",
            timestamp=datetime.now(UTC),
            duration_ms=duration_ms,
            performance_context={
                "operation": operation,
                "cache_key": cache_key,
                "hit": hit,
                "duration_ms": duration_ms,
                "data_age_minutes": data_age_minutes
            }
        )
        self.log_event(event)
    
    def log_rate_aggregation(self, base: str, target: str, final_rate: float, 
                           confidence_level: str, sources_used: List[str],
                           is_primary_used: bool, was_cached: bool, 
                           total_duration_ms: float, warnings: Optional[List[str]] = None):
        """Log the final rate aggregation result with full context"""
        event = LogEvent(
            event_type=EventType.RATE_AGGREGATION,
            level=LogLevel.WARNING if confidence_level == "low" else LogLevel.INFO,
            message=f"Rate aggregation {base}->{target}: {final_rate} ({confidence_level} confidence)",
            timestamp=datetime.now(UTC),
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

    def log_user_request(self, endpoint: str, request_data: Dict[str, Any],
                        success: bool, response_time_ms: float, 
                        error_message: Optional[str] = None):
        """Log user API requests"""
        event = LogEvent(
            event_type=EventType.USER_REQUEST,
            level=LogLevel.INFO if success else LogLevel.ERROR,
            message=f"User request to {endpoint}: {'SUCCESS' if success else 'FAILED'}",
            timestamp=datetime.now(UTC),
            duration_ms=response_time_ms,
            user_context={
                "endpoint": endpoint,
                "request_data": request_data,
                "success": success
            },
            performance_context={
                "response_time_ms": response_time_ms
            },
            error_context={
                "error_message": error_message
            } if error_message else None
        )
        self.log_event(event)
    
    @contextmanager
    def time_operation(self, operation_name: str):
        """Context manager to time operations"""
        start_time = time.time()
        try:
            yield
        finally:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.debug(f"{operation_name} took {duration_ms:.2f}ms")


# Global logger instance
production_logger: Optional[ProductionLogger] = None


def get_production_logger(db_manager: DatabaseManager) -> ProductionLogger:
    """Get or create production logger instance"""
    global production_logger
    if production_logger is None:
        production_logger = ProductionLogger(db_manager)
    return production_logger