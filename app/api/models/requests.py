from pydantic import BaseModel, Field, field_validator, ValidationInfo
from decimal import Decimal


class ConvertRequest(BaseModel):
    """Request model for currency conversion"""

    from_currency: str = Field(..., min_length=3, max_length=3, description="Source currency code (e.g., 'USD')")
    to_currency: str = Field(..., min_length=3, max_length=3, description="Target currency code (e.g., 'EUR')")
    amount: Decimal = Field(..., gt=0, description="Amount to convert (must be positive)")


    @field_validator('from_currency', 'to_currency')
    @classmethod
    def currency_must_be_uppercase(cls, v: str):
        return v.upper()
    
    @field_validator('amount')
    @classmethod
    def amount_precision(cls, v: Decimal):
        return round(v, 2)

    @field_validator('to_currency')
    @classmethod
    def currencies_must_be_different(cls, v: str, info: ValidationInfo):
        if info.data and 'from_currency' in info.data and v == info.data['from_currency']:
            raise ValueError('from_currency and to_currency must be different')
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "from_currency": "USD",
                "to_currency": "EUR", 
                "amount": 100.00
            }
        }

class ExchangeRateRequest(BaseModel):
    """Request model for getting exchange rates without conversion"""
    
    from_currency: str = Field(..., min_length=3, max_length=3, description="Base currency code")
    to_currency: str = Field(..., min_length=3, max_length=3, description="Target currency code")
    
    @field_validator('from_currency', 'to_currency')
    @classmethod
    def currency_must_be_uppercase(cls, v):
        return v.upper()
    
    @field_validator('to_currency')
    @classmethod
    def currencies_must_be_different(cls, v: str, info: ValidationInfo):
        if info.data and 'from_currency' in info.data and v == info.data['from_currency']:
            raise ValueError('from_currency and to_currency must be different')
        return v

    class Config:
        schema_extra = {
            "example": {
                "from_currency": "USD",
                "to_currency": "EUR"
            }
        }
