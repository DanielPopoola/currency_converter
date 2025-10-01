import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.database.models import APIProvider, Base, CurrencyPair
from app.monitoring.logger import logger

load_dotenv()


class DatabaseManager:
    """Manages PostgreSQL connections and session handling"""

    def __init__(self, database_url: str):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL", 
            "postgresql://user:password@localhost/currency_converter"
        )
    
        # Engine config
        self.engine = create_engine(
            self.database_url,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False
        )

        # Session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )

    def create_tables(self):
        """Create all tables and indexes"""
        try:
            # Create tables
            Base.metadata.create_all(bind=self.engine)

            # Add custom indexes
            with self.engine.connect() as conn:
                try:
                    # Index for rate history
                    conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS idx_exchange_rates_currency_fetched
                        ON exchange_rates (currency_pair_id, fetched_at DESC);
                    """))

                    # Index for provider performance monitoring
                    conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_api_call_logs_provider_called
                    ON api_call_logs (provider_id, called_at DESC);
                    """))

                    # Index for circuit breaker state tracking
                    conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS idx_circuit_breaker_provider_changed
                        ON circuit_breaker_logs (provider_id, state_changed_at DESC);
                    """))

                    # Composite index for finding successful rates by provider and time
                    conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS idx_exchange_rates_success_provider_time
                        ON exchange_rates (is_successful, provider_id, fetched_at DESC) 
                        WHERE is_successful = true;
                    """))
                    
                    conn.commit()
                    logger.info("Database tables and indexes created successfully", timestamp=datetime.now())
                    
                except Exception as index_error:
                    logger.warning(
                        "Index creation warning (may already exist): {error}",
                        error=str(index_error),
                        timestamp=datetime.now()
                    )

        except Exception as e:
            logger.error(
                "Failed to create database tables: {error}",
                error=str(e),
                timestamp=datetime.now()
            )
            raise

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Context manager for database sessions with automatic cleanup"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(
                "Database session error: {error}",
                error=str(e),
                timestamp=datetime.now()
            )
            raise
        finally:
            session.close()

    async def health_check(self):
        """Check database connectivity and performance"""
        try:
            with self.get_session() as session:
                start_time = session.execute(text("SELECT NOW()")).scalar()
                response_time = (session.execute(text("SELECT NOW()")).scalar() - start_time).total_seconds() * 1000 # type: ignore

                # Get some basic stats for monitoring
                provider_count = session.query(APIProvider).filter(APIProvider.is_active).count()
                currency_count = session.query(CurrencyPair).filter(CurrencyPair.is_active).count()
                
                return {
                    "status": "healthy",
                    "response_time_ms": round(response_time, 2),
                    "active_providers": provider_count,
                    "active_currency_pairs": currency_count
                }
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
        
    def seed_initial_data(self):
        """Populate initial data for API providers and currency pairs"""
        try:
            with self.get_session() as session:
                # Seed API providers
                providers_data = [
                    {
                        "name": "FixerIO",
                        "base_url": "http://data.fixer.io/api/",
                        "is_primary": True,
                        "priority_order": 1
                    },
                    {
                        "name": "OpenExchange",
                        "base_url": "https://openexchangerates.org/api/",
                        "is_primary": False,
                        "priority_order": 2
                    },
                    {
                        "name": "CurrencyAPI",
                        "base_url": "https://api.currencyapi.com/v3/",
                        "is_primary": False,
                        "priority_order": 3
                    }
                ]

                for provider_data in providers_data:
                    existing = session.query(APIProvider).filter(
                        APIProvider.name == provider_data["name"]
                    ).first()

                    if not existing:
                        provider = APIProvider(**provider_data)
                        session.add(provider)
                        logger.info(
                            "Seeded API provider: {provider_name}",
                            provider_name=provider_data['name'],
                            timestamp=datetime.now()
                        )

                currency_pairs = [
                    ("USD", "EUR"), ("EUR", "USD"),
                    ("USD", "GBP"), ("GBP", "USD"),
                    ("USD", "JPY"), ("JPY", "USD"),
                    ("EUR", "GBP"), ("GBP", "EUR"),
                    ("USD", "CAD"), ("CAD", "USD"),
                    ("USD", "AUD"), ("AUD", "USD"),
                    ("NGN", "USD"), ("USD", "NGN"),
                    ("NGN", "EUR"), ("EUR", "NGN"),
                    ("NGN", "GBP"), ("GBP", "NGN"),
                ]

                for base, target in currency_pairs:
                    existing = session.query(CurrencyPair).filter(
                        CurrencyPair.base_currency == base,
                        CurrencyPair.target_currency == target
                    ).first()

                    if not existing:
                        pair = CurrencyPair(base_currency=base, target_currency=target)
                        session.add(pair)
                        logger.debug(
                            "Seeded currency pair: {base_currency}->{target_currency}",
                            base_currency=base,
                            target_currency=target,
                            timestamp=datetime.now()
                        )
                
                session.commit()
                logger.info("Database seeding completed successfully", timestamp=datetime.now())
                
        except Exception as e:
            logger.error(
                "Failed to seed database: {error}",
                error=str(e),
                timestamp=datetime.now()
            )
            raise

    def get_or_create_currency_pair(self, session: Session, base: str, target: str) -> CurrencyPair:
        """Helper method to get or create currency pair"""
        pair = session.query(CurrencyPair).filter(
            CurrencyPair.base_currency == base,
            CurrencyPair.target_currency == target
        ).first()
        
        if not pair:
            pair = CurrencyPair(base_currency=base, target_currency=target)
            session.add(pair)
            session.flush()  # Get the ID without committing
            
        return pair