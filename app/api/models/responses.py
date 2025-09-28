from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime, UTC
from typing import Dict, Any


class ConvertResponse(BaseModel):
    """Response model for currency conversion"""

    from_currency: str = Field(..., description="Source currency code")
    to_currency: str = Field(..., description="Target currency code") 
    amount: Decimal = Field(..., description="Original amount requested")
    converted_amount: Decimal = Field(..., description="Converted amount")
    exchange_rate: Decimal = Field(..., description="Exchange rate used for conversion")
    confidence_level: str = Field(..., description="Data confidence level (high/medium/low)")
    timestamp: datetime = Field(..., description="When the rate was fetched")

    class Config:
        json_schema_extra = {
            "example": {
                "from_currency": "USD",
                "to_currency": "EUR",
                "amount": 100.00,
                "converted_amount": 85.50,
                "exchange_rate": 0.8550,
                "confidence_level": "high",
                "timestamp": "2025-09-27T10:30:00Z"
            }
        }

class ExchangeRateResponse(BaseModel):
    """Response model for exchange rate queries"""
    
    from_currency: str = Field(..., description="Base currency code")
    to_currency: str = Field(..., description="Target currency code")
    exchange_rate: Decimal = Field(..., description="Current exchange rate")
    confidence_level: str = Field(..., description="Data confidence level")
    timestamp: datetime = Field(..., description="When the rate was fetched")

    class Config:
        json_schema_extra = {
            "example": {
                "from_currency": "USD", 
                "to_currency": "EUR",
                "exchange_rate": 0.8550,
                "confidence_level": "high",
                "timestamp": "2025-09-27T10:30:00Z"
            }
        }


class HealthResponse(BaseModel):
    """Response model for health check"""
    
    status: str = Field(..., description="Overall system status (healthy/degraded/unhealthy)")
    timestamp: datetime = Field(..., description="When health check was performed")
    services: Dict[str, Any] = Field(..., description="Status of individual services")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "timestamp": "2025-09-27T10:30:00Z", 
                "services": {
                    "database": {"status": "healthy", "response_time_ms": 12},
                    "cache": {"status": "healthy", "response_time_ms": 5},
                    "providers": {
                        "FixerIO": {"state": "CLOSED", "failure_count": 0},
                        "OpenExchange": {"state": "CLOSED", "failure_count": 0}
                    }
                }
            }
        }


class ErrorResponse(BaseModel):
    """Standard error response model"""
    
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message") 
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="When error occurred")
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "service_unavailable",
                "message": "Service temporarily unavailable",
                "timestamp": "2025-09-27T10:30:00Z"
            }
        }