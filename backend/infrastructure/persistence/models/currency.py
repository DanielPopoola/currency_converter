from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
	pass


class SupportedCurrencyDB(Base):
	__tablename__ = 'supported_currencies'

	code: Mapped[str] = mapped_column(String(5), primary_key=True)
	name: Mapped[str | None] = mapped_column(String(100), nullable=True)


class RateHistoryDB(Base):
	__tablename__ = 'rate_history'

	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	from_currency: Mapped[str] = mapped_column(String(5), nullable=False)
	to_currency: Mapped[str] = mapped_column(String(5), nullable=False)
	rate: Mapped[Decimal] = mapped_column(DECIMAL(precision=18, scale=6), nullable=False)
	timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
	source: Mapped[str | None] = mapped_column(String(50), nullable=False)

	__table_args__ = (
		Index('idx_from_currency', 'from_currency'),
		Index('idx_to_currency', 'to_currency'),
		UniqueConstraint(
			'from_currency', 'to_currency', 'timestamp', name='uq_base_target_currency'
		),
	)
