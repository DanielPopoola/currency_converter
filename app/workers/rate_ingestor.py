import asyncio
import signal
import sys
from datetime import datetime

from app.cache.redis_manager import RedisManager
from app.monitoring.logger import LogLevel, logger
from app.services import RateAggregatorService, ServiceFactory
from app.config.worker import WorkerConfig


class RateIngestorWorker:
    """
    Background worker that continuously fetches exchange rates and publishes them.
    
    This runs independently of the FastAPI server, ensuring rates are always fresh
    regardless of user request patterns.
    """
    def __init__(
            self,
            rate_aggregator: RateAggregatorService,
            redis_manager: RedisManager,
            base_currencies: list[str],
            target_currencies: set[str],
            update_interval: int = 5
    ):
        """
        Args:
            rate_aggregator: Service for fetching and aggregating rates
            redis_manager: Redis connection for publishing updates
            base_currencies: List of base currencies to fetch (e.g., ["USD", "EUR"])
            target_currencies: Set of target currencies we care about
            update_interval: Seconds between update cycles (default: 5)
        """
        self.rate_aggregator = rate_aggregator
        self.redis_manager = redis_manager
        self.base_currencies = base_currencies
        self.target_currencies = target_currencies
        self.update_interval = update_interval
        self.is_running = False
        self.logger = logger.bind(worker="RateIngestor")
        
        self.logger.info("Initialized RateIngestorWorker")
        self.logger.info(f"Base currencies: {base_currencies}")
        self.logger.info(f"Target currencies: {target_currencies}")
        self.logger.info(f"Update interval: {update_interval} seconds")

    async def fetch_and_publish_for_base(self, base: str) -> dict[str, bool]:
        """
        Fetch individual rates for a base currency and publish them.
        """
        results = {}
        for target in self.target_currencies:
            try:
                # Fetch individual rate
                rate_result = await self.rate_aggregator.get_exchange_rate(base, target)

                rate_data = {
                    "rate": str(rate_result.rate),
                    "confidence_level": rate_result.confidence_level,
                    "sources_used": rate_result.sources_used,
                    "is_primary_used": rate_result.is_primary_used,
                    "timestamp": rate_result.timestamp.isoformat(),
                    "cached": rate_result.cached,
                    "warnings": rate_result.warnings or []
                }

                # Store in key-value
                await self.redis_manager.set_latest_rate(base, target, rate_data)

                # Publish to pub/sub
                _ = await self.redis_manager.publish_rate_update(base, target, rate_data)

                results[target] = True
            except Exception as e:
                self.logger.error(
                    "Failed to fetch or publish rate for {base}->{target}: {error}",
                    base=base,
                    target=target,
                    error=str(e),
                    event_type="RATE_AGGREGATION",
                    timestamp=datetime.now()
                )
                results[target] = False
        return results
        

    async def update_cycle(self):
        """
        Perform one complete update cycle.
        Fetches all base currencies concurrently.
        """
        cycle_start = datetime.now()
        
        self.logger.info(f"Starting update cycle for {len(self.base_currencies)} base currencies...")

        tasks = [
            self.fetch_and_publish_for_base(base)
            for base in self.base_currencies
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count total pairs processed
        total_pairs = 0
        successful_pairs = 0
        
        for result in results:
            if isinstance(result, dict):
                total_pairs += len(result)
                successful_pairs += sum(1 for success in result.values() if success)

        cycle_duration = (datetime.now() - cycle_start).total_seconds()

        self.logger.info(
            f"Update cycle completed in {cycle_duration:.2f}s: "
            f"{successful_pairs}/{total_pairs} pairs updated"
        )

        self.logger.info(
            f"Worker cycle completed: {successful_pairs}/{total_pairs} pairs",
            event_type="RATE_AGGREGATION",
            cycle_duration_seconds=cycle_duration,
            pairs_attempted=total_pairs,
            pairs_succeeded=successful_pairs,
            api_calls_made=len(self.base_currencies)
        )

    async def run(self):
        """
        Main worker loop. Runs indefinitely until stopped.
        """
        self.is_running = True
        self.logger.info("🚀 Rate Ingestor Worker started!")
        
        self.logger.info(
            "Rate Ingestor Worker started",
            event_type="SYSTEM_EVENT",
            timestamp=datetime.now(),
            pairs_tracked=len(self.base_currencies),
            update_interval=self.update_interval
        )
        
        cycle_count = 0
        
        while self.is_running:
            try:
                cycle_count += 1
                self.logger.info(f"\n{'='*50}")
                self.logger.info(f"Cycle #{cycle_count}")
                self.logger.info(f"{'='*50}")
                
                await self.update_cycle()
                
                # Sleep before next cycle
                self.logger.info(f"Sleeping for {self.update_interval} seconds...")
                await asyncio.sleep(self.update_interval)
                
            except asyncio.CancelledError:
                logger.info("Worker received cancellation signal")
                break
            except Exception as e:
                self.logger.critical(
                    f"Worker cycle failed: {e}",
                    event_type="SYSTEM_EVENT",
                    level=LogLevel.CRITICAL,
                    timestamp=datetime.now(),
                    error_context=str(e)
                )
                self.logger.error(f"Error in worker cycle: {e}", exc_info=True)
                # Sleep and continue on error
                await asyncio.sleep(self.update_interval)
        
        logger.info("Rate Ingestor Worker stopped")
    
    def stop(self):
        """Gracefully stop the worker"""
        self.logger.info("Stopping Rate Ingestor Worker...")
        self.is_running = False


async def main():
    """Entry point for running the worker."""
    # Validate configuration first
    is_valid, error_msg = WorkerConfig.validate_config()
    if not is_valid:
        logger.error(f"Invalid worker configuration: {error_msg}")
        sys.exit(1)
    
    logger.info("="*60)
    logger.info("RATE INGESTOR WORKER STARTING")
    logger.info("="*60)
    logger.info(f"Base currencies: {WorkerConfig.BASE_CURRENCIES}")
    logger.info(f"Target currencies: {WorkerConfig.TARGET_CURRENCIES}")
    logger.info(f"Total pairs to track: {WorkerConfig.get_total_pairs()}")
    logger.info(f"Update interval: {WorkerConfig.UPDATE_INTERVAL}s")
    logger.info(f"API calls per cycle: {len(WorkerConfig.BASE_CURRENCIES)}")
    logger.info("="*60)

    service_factory = ServiceFactory()
    
    logger.info("Initializing services...")
    await service_factory.create_rate_aggregator()

    # Create worker with config
    worker = RateIngestorWorker(
        rate_aggregator=service_factory.rate_aggregator,
        redis_manager=service_factory.redis_manager,
        base_currencies=WorkerConfig.BASE_CURRENCIES,
        target_currencies=WorkerConfig.TARGET_CURRENCIES,
        update_interval=WorkerConfig.UPDATE_INTERVAL
    )
    
    # Setup graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down gracefully...")
        worker.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await worker.run()
    finally:
        await service_factory.cleanup()
        logger.info("Cleanup completed")

if __name__ == "__main__":
    # Run the worker
    asyncio.run(main())