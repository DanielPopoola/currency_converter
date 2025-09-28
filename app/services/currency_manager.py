import logging
from typing import Dict, Set, Optional, Tuple

from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

from app.providers.base import APIProvider
from app.database.models import SupportedCurrency

logger = logging.getLogger(__name__)

class CurrencyManager:
    def __init__(self, db_manager, redis_manager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.TOP_CURRENCIES_KEY = "supported_currencies:top"
        self.ALL_CURRENCIES_KEY = "supported_currencies:all" 
        
    async def populate_supported_currencies(self, providers: Dict[str, APIProvider]):
        """Fetch and merge supported currencies from all providers"""
        all_currencies = set()
        
        for provider_name, provider in providers.items():
            try:
                result = await provider.get_supported_currencies()
                if result.was_successful and result.data:
                    currencies = set(result.data)
                    all_currencies.update(currencies)
                    logger.info(f"{provider_name}: {len(currencies)} currencies")
            except Exception as e:
                logger.error(f"Failed to get currencies from {provider_name}: {e}")
        
        # Store in database (no duplicates automatically)
        try:
            await self._store_currencies_in_db(all_currencies)
        except Exception as e:
            logger.error(f"Failed to store currencies in DB: {e}")
        
        # Cache top currencies for fast validation
        try:
            await self._cache_top_currencies(all_currencies)
        except Exception as e:
            logger.error(f"Failed to cache top currencies: {e}")
        
        return list(all_currencies)

    async def _store_currencies_in_db(self, currencies: Set[str]):
        """Store supported currencies in the database."""
        Session = sessionmaker(bind=self.db_manager.engine)
        with Session() as session:
            for code in currencies:
                # Check if currency already exists
                existing_currency = session.query(SupportedCurrency).filter_by(code=code).first()
                if not existing_currency:
                    new_currency = SupportedCurrency(code=code)
                    session.add(new_currency)
            session.commit()
            logger.info(f"Stored {len(currencies)} unique currencies in the database.")

    async def _cache_top_currencies(self, all_currencies: Set[str]):
        """Select top N currencies and cache them in Redis."""
        # This is a simplified example.
        sorted_currencies = sorted(list(all_currencies))
        top_n_currencies = sorted_currencies[:10]  # Example: top 10 currencies

        await self.redis_manager.set_top_currencies(top_n_currencies)
        logger.info(f"Cached top {len(top_n_currencies)} currencies: {top_n_currencies}")

    async def validate_currencies(self, base: str, target: str) -> Tuple[bool, Optional[str]]:
        """
        Returns: (is_valid, error_message)
        
        Strategy:
        1. Check top currencies cache first
        2. If not in cache, check database  
        3. Return specific error for unsupported currency
        """
        
        # Step 1: Quick cache check for common currencies
        top_currencies = await self.redis_manager.get_top_currencies()
        
        if top_currencies:
            if base in top_currencies and target in top_currencies:
                return True, None  # Fast path - both currencies cached
                
            # If either currency not in top cache, they might still be valid
            # Don't return error yet - check full database
        
        # Step 2: Database check for full currency list
        try:
            Session = sessionmaker(bind=self.db_manager.engine)
            with Session() as session:
                supported = session.query(SupportedCurrency.code).all()
                supported_set = {currency.code for currency in supported}
                
                unsupported = []
                if base not in supported_set:
                    unsupported.append(base)
                if target not in supported_set:
                    unsupported.append(target)
                
                if unsupported:
                    error_msg = f"Unsupported currency(ies): {', '.join(unsupported)}"
                    return False, error_msg
                    
                return True, None
                
        except Exception as e:
            logger.error(f"Currency validation error: {e}")
            # Fail open - let API calls proceed and handle errors there
            return True, None