"""
Configuration for the Rate Ingestor Worker.

This file defines which currency pairs the worker continuously monitors.
Modify these lists based on your business requirements.
"""
import os

from dotenv import load_dotenv

load_dotenv()

class WorkerConfig:
    """Configuration for rate ingestion worker"""
    BASE_CURRENCIES: list[str] = [c.strip() for c in os.getenv("WORKER_BASE_CURRENCIES", "USD,EUR").split(",")]

    TARGET_CURRENCIES: set[str] = {
        c.strip() for c in os.getenv("WORKER_TARGET_CURRENCIES", "NGN").split(",")
    }

    UPDATE_INTERVAL = os.getenv("WORKER_UPDATE_INTERVAL", 120)

    RATE_TTL = os.getenv("CACHE_TTL", 30)

    @classmethod
    def get_total_pairs(cls) -> int:
        """Calculate how many currency pairs will be tracked"""
        # Each base pair can map to all targets except itself
        pairs = 0
        for base in cls.BASE_CURRENCIES:
            for target in cls.TARGET_CURRENCIES:
                if base != target:
                    pairs += 1
        return pairs
    
    @classmethod
    def validate_config(cls) -> tuple[bool, str]:
        """
        Validate the configuration.
        Returns (is_valid, error_message)
        """
        if not cls.BASE_CURRENCIES:
            return False, "BASE_CURRENCIES cannot be empty"
        if not cls.TARGET_CURRENCIES:
            return False, "TARGET_CURRENCIES cannot be empty"
        if cls.UPDATE_INTERVAL < 1:
            return False, "UPDATE_INTERVAL must be at least 1 second"
        
        # Check for invalid currency codes (should be min 3 letters)
        all_currencies = set(cls.BASE_CURRENCIES) | cls.TARGET_CURRENCIES
        for currency in all_currencies:
            if not isinstance(currency, str) or len(currency) < 3:
                return False, f"Invalid currency code: {currency} (must be 3 letters)"
            
        return True, "Configuration valid"
    

wc = WorkerConfig()
print(wc.TARGET_CURRENCIES)