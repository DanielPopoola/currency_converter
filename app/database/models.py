from sqlalchemy import (
    DECIMAL,
    TIMESTAMP,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class CurrencyPair(Base):
    """Stores supported currency combinations"""
    __tablename__ = "currency_pairs"

    id = Column(Integer, primary_key=True)
    base_currency = Column(String(3), nullable=False)
    target_currency = Column(String(3), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)

    # Relationship to exchange rates
    exchange_rates = relationship("ExchangeRate", back_populates="currency_pair")

    __table_args__  = (
        UniqueConstraint(
            "base_currency", "target_currency", name="uq_base_target_currency"
        ),
        {"sqlite_autoincrement": True},
    )

    def __repr__(self):
        return f"<CurrencyPair({self.base_currency}->{self.target_currency})>"
    
class APIProvider(Base):
    """Tracks external API providers with priority and status"""
    __tablename__ = "api_providers"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    base_url = Column(String(100), nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    priority_order = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)

    # Relationships
    exchange_rates = relationship("ExchangeRate", back_populates="provider")
    api_call_logs = relationship("APICallLog", back_populates="provider")
    circuit_breaker_logs = relationship("CircuitBreakerLog", back_populates="provider")

    def __repr__(self):
        status = "PRIMARY" if self.is_primary else f"SECONDARY({self.priority_order})"
        return f"<APIProvider({self.name}, {status})>"
    

class ExchangeRate(Base):
    """Historical exchange rate data"""
    __tablename__ = "exchange_rates"

    id = Column(Integer, primary_key=True)
    currency_pair_id = Column(Integer, ForeignKey("currency_pairs.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("api_providers.id"), nullable=False)
    rate = Column(DECIMAL(15, 8), nullable=False)
    fetched_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    is_successful = Column(Boolean, default=True, nullable=False)
    confidence_level = Column(String(20), default="high", nullable=False)

    # Relationships
    currency_pair = relationship("CurrencyPair", back_populates="exchange_rates")
    provider = relationship("APIProvider", back_populates="exchange_rates")

    __table_args__  = (
        {"sqlite_autoincrement": True},
    )

    def __repr__(self):
        return f"<ExchangeRate({self.rate}, {self.confidence_level}, {self.fetched_at})>"


class APICallLog(Base):
    """Detailed API monitoring for debugging and performance analysis"""
    __tablename__ = "api_call_logs"

    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("api_providers.id"), nullable=False)
    endpoint = Column(String(255), nullable=False)
    http_status_code = Column(Integer, nullable=True)  # None if network error
    response_time_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    called_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    was_successful = Column(Boolean, nullable=False)
    
    # Relationships
    provider = relationship("APIProvider", back_populates="api_call_logs")
    
    def __repr__(self):
        status = "SUCCESS" if self.was_successful else "FAILED"
        return f"<APICallLog({self.provider.name}, {status}, {self.response_time_ms}ms)>"


class CircuitBreakerLog(Base):
    """Circuit breaker state changes - for HYBRID persistence approach"""
    __tablename__ = "circuit_breaker_logs"
    
    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("api_providers.id"), nullable=False)
    previous_state = Column(String(20), nullable=True)  # CLOSED/OPEN/HALF_OPEN
    new_state = Column(String(20), nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    state_changed_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    reason = Column(String(255), nullable=True)  # "5_consecutive_failures", "recovery_successful", etc.
    
    # Relationships
    provider = relationship("APIProvider", back_populates="circuit_breaker_logs")
    
    def __repr__(self):
        return f"<CircuitBreakerLog({self.provider.name}: {self.previous_state}->{self.new_state})>"

class SupportedCurrency(Base):
    """Stores all currencies supported by at least one provider"""
    __tablename__ = "supported_currencies"

    id = Column(Integer, primary_key=True)
    code = Column(String(10), nullable=False, unique=True)  # USD, EUR, etc.
    name = Column(String(100), nullable=True)  # US Dollar, Euro
    is_popular = Column(Boolean, default=False)  # For your top 10 cache
    provider_count = Column(Integer, default=1)  # How many APIs support it
    created_at = Column(TIMESTAMP, default=func.now())