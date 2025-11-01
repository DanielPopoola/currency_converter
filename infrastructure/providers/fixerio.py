from decimal import Decimal
from typing import Any
import requests

from .base import ExchangeRateProvider


class FixerIO(ExchangeRateProvider):
    @property
    def name(self):
        return "fixerio"
    
    async def 