# tests/test_providers/fixtures/api_responses.py
"""
Sample API responses for testing all providers.
These are real-world examples of what each API returns.
"""

from datetime import UTC, datetime

# FixerIO API Responses
FIXERIO_RESPONSES = {
    "single_rate_success": {
        "success": True,
        "timestamp": 1519296206,
        "base": "EUR",
        "date": "2025-09-20",
        "rates": {
            "USD": 1.23396,
        }
    },
    
    "all_rates_success":{
        "success": True,
        "timestamp": 1519296206,
        "base": "EUR",
        "date": "2025-09-20",
        "rates": {
            "AUD": 1.566015,
            "CAD": 1.560132,
            "CHF": 1.154727,
            "CNY": 7.827874,
            "GBP": 0.882047,
            "JPY": 132.360679,
            "USD": 1.23396,
        }
    },
    
    "api_error": {
        "success": False,
        "error": {
            "code": 429,
            "info": "Your monthly usage limit has been reached."
        }
    },
    
    "currencies_success": {
        "success": True,
        "symbols": {
            "USD": "United States Dollar",
            "EUR": "Euro",
            "GBP": "British Pound Sterling",
            "JPY": "Japanese Yen"
        }
    },
    
    "missing_target_currency": {
        "success": True,
        "timestamp": 1700870399,
        "base": "USD",
        "date": "2023-11-24",
        "rates": {
            "GBP": 0.79123  # EUR is missing
        }
    }
}


# OpenExchange API Responses  
OPENEXCHANGE_RESPONSES = {
    "single_rate_success": {
        "disclaimer": "Usage subject to terms",
        "license": "Data license",
        "timestamp": 1700870399,
        "base": "USD",
        "rates": {
            "EUR": 0.85432
        }
    },
    
    "all_rates_success": {
        "disclaimer": "Usage subject to terms", 
        "license": "Data license",
        "timestamp": 1700870399,
        "base": "USD",
        "rates": {
            "EUR": 0.85432,
            "GBP": 0.79123,
            "JPY": 149.756,
            "CAD": 1.36789
        }
    },
    
    "api_error": {
        "error": True,
        "status": 401,
        "message": "invalid_app_id",
        "description": "Invalid App ID provided"
    },
    
    "currencies_success": {
        "USD": "United States Dollar",
        "EUR": "Euro", 
        "GBP": "British Pound Sterling",
        "JPY": "Japanese Yen"
    },
    
    "missing_base": {
        "error": True,
        "status": 400,
        "message": "invalid_base",
        "description": "Client requested rates for an unsupported base currency"
    }
}


# CurrencyAPI Responses
CURRENCYAPI_RESPONSES = {
    "single_rate_success": {
        "meta": {
            "last_updated_at": "2023-11-24T23:59:59Z"
        },
        "data": {
            "EUR": {
                "code": "EUR",
                "value": 0.85432
            }
        }
    },
    
    "all_rates_success": {
        "meta": {
            "last_updated_at": "2023-11-24T23:59:59Z"
        },
        "data": {
            "EUR": {
                "code": "EUR", 
                "value": 0.85432
            },
            "GBP": {
                "code": "GBP",
                "value": 0.79123
            },
            "JPY": {
                "code": "JPY",
                "value": 149.756
            },
            "CAD": {
                "code": "CAD",
                "value": 1.36789
            }
        }
    },
    
    "api_error": {
        "message": "Your subscription plan does not support this endpoint.",
        "status": 403
    },
    
    "currencies_success": {
        "data": {
            "USD": {
                "symbol": "$",
                "name": "US Dollar", 
                "symbol_native": "$",
                "decimal_digits": 2,
                "rounding": 0,
                "code": "USD",
                "name_plural": "US dollars"
            },
            "EUR": {
                "symbol": "€",
                "name": "Euro",
                "symbol_native": "€", 
                "decimal_digits": 2,
                "rounding": 0,
                "code": "EUR",
                "name_plural": "euros"
            }
        }
    },
    
    "missing_data_field": {
        "meta": {
            "last_updated_at": "2023-11-24T23:59:59Z"
        }
        # Missing 'data' field
    }
}


# Network Error Scenarios (these simulate httpx responses)
NETWORK_ERROR_SCENARIOS = {
    "timeout": {
        "exception_type": "TimeoutException",
        "message": "Request timed out"
    },
    
    "connection_error": {
        "exception_type": "ConnectError", 
        "message": "Failed to establish connection"
    },
    
    "http_500": {
        "status_code": 500,
        "response_text": "Internal Server Error"
    },
    
    "http_404": {
        "status_code": 404,
        "response_text": "Not Found"
    },
    
    "invalid_json": {
        "status_code": 200,
        "response_text": "This is not valid JSON {{"
    }
}


# Expected parsed responses (for verification)
EXPECTED_PARSED_RESPONSES = {
    "usd_to_eur": {
        "base_currency": "USD",
        "target_currency": "EUR", 
        "rate": 0.85432,
        "is_successful": True,
        "error_message": None
    },
    
    "parsing_error": {
        "base_currency": "USD",
        "target_currency": "EUR",
        "rate": 0.0,
        "is_successful": False,
        "error_message": "Parsing error: 'rates'"  # Will contain actual error
    }
}