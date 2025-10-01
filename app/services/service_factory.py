import os
from datetime import datetime

from dotenv import load_dotenv

from app.cache.redis_manager import RedisManager
from app.config.database import DatabaseManager
from app.database.models import APIProvider as APIProviderModel
from app.monitoring.logger import logger
from app.providers import APIProvider, CurrencyAPIProvider, FixerIOProvider, OpenExchangeProvider
from app.services import CircuitBreaker, CurrencyManager, RateAggregatorService

load_dotenv()



class ServiceFactory:
    """Factory to create and wire up all services with dependencies"""

    def __init__(self):
        # Initialize core infrastructure
        self.redis_manager = RedisManager(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379")
        )

        self.db_manager = DatabaseManager(
            database_url=os.getenv("DATABASE_URL", "database_url")
        )

        self.providers: dict[str, APIProvider] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.rate_aggregator: RateAggregatorService = None
        self.currency_manager: CurrencyManager
        self.logger = logger.bind(service="ServiceFactory")

    async def create_rate_aggregator(self) -> RateAggregatorService:
        """Create fully configured rate aggregator with all providers and circuit breakers"""

        # Step 1: Create API Providers
        self.providers = {
            "FixerIO": FixerIOProvider(
                api_key=os.getenv("FIXERIO_API_KEY", "demo_key")
            ),

            "OpenExchange": OpenExchangeProvider(
                api_key=os.getenv("OPENEXCHANGE_APP_ID", "your_app_id")
            ),

            "CurrencyAPI": CurrencyAPIProvider(
                api_key=os.getenv("CURRENCYAPI_KEY", "your_api_key")
            )
        }

        # Step 2: Get provider IDs from database
        provider_ids = await self._get_provider_ids()

        # Step 3: Create circuit breakers for each provider
        self.circuit_breakers = {}
        for provider_name, _ in self.providers.items():
            provider_id = provider_ids.get(provider_name, 1)  # Fallback ID
            
            circuit_breaker = CircuitBreaker(
                provider_id=provider_id,
                provider_name=provider_name,
                redis_manager=self.redis_manager,
                db_manager=self.db_manager,
                failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
                recovery_timeout=int(os.getenv("CB_RECOVERY_TIMEOUT", "60")),
                success_threshold=int(os.getenv("CB_SUCCESS_THRESHOLD", "2"))
            )
            
            self.circuit_breakers[provider_name] = circuit_breaker

        # Step 4: Crete currency manager
        self.currency_manager = CurrencyManager(self.db_manager, self.redis_manager)
        await self.currency_manager.populate_if_needed(self.providers)
        
        # Step 5: Create rate aggregator
        self.rate_aggregator = RateAggregatorService(
            providers=self.providers,
            circuit_breakers=self.circuit_breakers,
            redis_manager=self.redis_manager,
            db_manager=self.db_manager,
            primary_provider=os.getenv("PRIMARY_PROVIDER", "FixerIO"),
            currency_manager=self.currency_manager,
        )
        
        self.logger.info(
            "Rate aggregator created with {provider_count} providers",
            provider_count=len(self.providers),
            timestamp=datetime.now(),
            event_type="SERVICE_LIFECYCLE"
        )
        return self.rate_aggregator
    
    async def _get_provider_ids(self) -> dict[str, int]:
        """Get provider IDs from database"""
        try:
            with self.db_manager.get_session() as session:
                providers = session.query(APIProviderModel).all()
                return {provider.name: provider.id for provider in providers}
        except Exception as e:
            self.logger.error(
                "Failed to get provider IDs: {error}",
                timestamp=datetime.now(),
                error=str(e),
                event_type="DATABASE_OPERATION"
            )
            return {}
    
    async def cleanup(self):
        """Clean up all services"""
        # Close HTTP clients
        for provider in self.providers.values():
            await provider.close()
        
        self.logger.info(
            "Services cleaned up successfully",
            event_type="SERVICE_LIFECYCLE",
            timestamp=datetime.now(),
        )
    
    def get_redis_manager(self) -> RedisManager:
        """Get Redis manager instance"""
        return self.redis_manager
    
    def get_db_manager(self) -> DatabaseManager:
        """Get database manager instance"""  
        return self.db_manager
    
    async def get_health_status(self) -> dict:
        """Get health status of all services"""
        if not self.rate_aggregator:
            return {"status": "not_initialized"}
        
        return await self.rate_aggregator.get_health_status()

# Global service factory instance
service_factory = ServiceFactory()

