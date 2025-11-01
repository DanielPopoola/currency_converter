from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ExchangeRate:
    from_currency: str
    to_currency: str
    rate: Decimal
    timestamp: datetime
    source: str


@dataclass(frozen=True)
class SupportedCurrency:
    code: str
    name: str | None


@dataclass(frozen=True)
class AggregatedRate:
    from_currency: str
    to_currency: str
    rate: Decimal  # The averaged/final rate
    timestamp: datetime
    sources: list[str]  # Which providers contributed
    individual_rates: dict[str, Decimal]