from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ProviderStatus(Enum):
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    API_ERROR = "api_error" 
    NETWORK_ERROR = "network_error"
    PARSING_ERROR = "parsing_error"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"


@dataclass
class RateResponse:
    """Standardized response from any API provider"""
    rate: Optional[float] = None
    base_currency: Optional[str] = None  
    target_currency: Optional[str] = None
    timestamp: Optional[datetime] = None
    status: ProviderStatus = ProviderStatus.SUCCESS
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None
    raw_response: Optional[Dict[str, Any]] = None

    @property
    def is_successful(self) -> bool:
       """Check if the response contains valid rate data"""
       return (
           self.status == ProviderStatus.SUCCESS and
           self.rate is not None and
           self.rate > 0
       )
    
    @property
    def confidence_level(self) -> str:
        """Determine confidence based on response characteristics"""
        if not self.is_successful:
            return "none"
        
        if self.response_time_ms and self.response_time_ms > 5000:  # Very slow
            return "low"  
        elif self.response_time_ms and self.response_time_ms > 2000:  # Slow
            return "medium"
        else:
            return "high"


class BaseAPIProvider(ABC):
    """Abstract base class for all API providers - defines the contract"""
    
    def __init__(self, name: str, base_url: str, api_key: Optional[str] = None, 
                 timeout: int = 3000, max_retries: int = 3):
        self.name = name
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout_ms = timeout
        self.max_retries = max_retries
        self.logger = logging.getLogger(f"provider.{name}")

    @abstractmethod
    async def get_rate(self, base_currency: str, target_currency: str) -> RateResponse:
        """
        Fetch exchange rate from the API provider
        
        Args:
            base_currency: Source currency code (e.g., 'NGN')
            target_currency: Target currency code (e.g., 'USD')
            
        Returns:
            RateResponse with standardized rate data or error information
        """
        pass

    @abstractmethod
    async def get_supported_currencies(self) -> Dict[str, Any]:
        """
        Get list of currencies supported by this provider
        
        Returns:
            Dictionary with currency codes and metadata
        """
        pass
    
    @abstractmethod
    def _build_rate_url(self, base_currency: str, target_currency: str) -> str:
        """Build API-specific URL for rate requests"""
        pass
    
    @abstractmethod  
    def _parse_rate_response(self, response_data: Dict[str, Any], 
                           base_currency: str, target_currency: str) -> float:
        """Parse API-specific response format to extract rate"""
        pass

    # Common functionality

    def _create_headers(self) -> Dict[str, str]:
        """Build common HTTP headers - can be overridden by specific providers"""
        headers = {
            "User-Agent": "CurrencyConverter/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        if self.api_key:
            # Common API key patterns - specific providers override if needed
            headers["Authorization"] = f"Bearer {self.api_key}"
            
        return headers
    
    def _validate_currency_code(self, currency: str) -> bool:
        """Basic currency code validation"""
        return (
            isinstance(currency, str) and 
            len(currency) == 3 and 
            currency.isupper() and 
            currency.isalpha()
        )
    
    async def _handle_http_error(self, status_code: int, response_text: str) -> ProviderStatus:
        """Map HTTP status codes to provider status"""
        if status_code == 429:
            self.logger.warning(f"{self.name}: Rate limited (429)")
            return ProviderStatus.RATE_LIMITED
        elif status_code in [401, 403]:
            self.logger.error(f"{self.name}: Authentication error ({status_code})")
            return ProviderStatus.API_ERROR
        elif status_code >= 500:
            self.logger.error(f"{self.name}: Server error ({status_code})")
            return ProviderStatus.API_ERROR
        else:
            self.logger.error(f"{self.name}: HTTP error ({status_code}): {response_text}")
            return ProviderStatus.API_ERROR
        
    async def health_check(self) -> Dict[str, Any]:
        """Test provider connectivity - useful for monitoring"""
        try:
            # Try a simple USD->EUR conversion as health check
            start_time = datetime.now()
            response = await self.get_rate("USD", "EUR")
            duration = (datetime.now() - start_time).total_seconds() * 1000
            
            return {
                "provider": self.name,
                "status": "healthy" if response.is_successful else "unhealthy",
                "response_time_ms": round(duration, 2),
                "error": response.error_message if not response.is_successful else None
            }
            
        except Exception as e:
            return {
                "provider": self.name, 
                "status": "unhealthy",
                "error": str(e)
            }
    
    def __repr__(self):
        return f"<{self.__class__.__name__}(name={self.name})>"