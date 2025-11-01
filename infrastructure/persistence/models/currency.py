from sqlalchemy import DECIMAL, Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class SupportedCurrencyDB(Base):
    __tablename__ = "supported_currencies"

    code = Column(String(5), primary_key=True)
    name = Column(String(100), nullable=True)


class RateHistoryDB(Base):
    __tablename__ = "rate_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_currency = Column(String(3), nullable=False)
    to_currency = Column(String(3), nullable=False)
    rate = Column(DECIMAL(precision=18, scale=6), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    source = Column(String(50), nullable=False)

    __table_args__ = (
        Index('idx_from_currency', 'from_currency'),
        Index('idx_to_currency', 'to_currency'),
        UniqueConstraint(
            "from_currency", "to_currency", "timestamp", name="uq_base_target_currency"
        )
    )