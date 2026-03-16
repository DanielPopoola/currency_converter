export interface Currency {
  code: string;
  name: string;
  symbol: string;
  countryCode?: string;
  flag: string;
}

interface CurrencyMetadata {
  name: string;
  symbol: string;
  countryCode?: string;
}

const currencyMetadata: Record<string, CurrencyMetadata> = {
  USD: { name: "United States Dollar", symbol: "$", countryCode: "US" },
  EUR: { name: "Euro", symbol: "€", countryCode: "EU" },
  GBP: { name: "British Pound Sterling", symbol: "£", countryCode: "GB" },
  JPY: { name: "Japanese Yen", symbol: "¥", countryCode: "JP" },
  AUD: { name: "Australian Dollar", symbol: "A$", countryCode: "AU" },
  CAD: { name: "Canadian Dollar", symbol: "C$", countryCode: "CA" },
  CHF: { name: "Swiss Franc", symbol: "Fr.", countryCode: "CH" },
  CNY: { name: "Chinese Yuan", symbol: "¥", countryCode: "CN" },
  INR: { name: "Indian Rupee", symbol: "₹", countryCode: "IN" },
  NZD: { name: "New Zealand Dollar", symbol: "NZ$", countryCode: "NZ" },
  BRL: { name: "Brazilian Real", symbol: "R$", countryCode: "BR" },
  SGD: { name: "Singapore Dollar", symbol: "S$", countryCode: "SG" },
  HKD: { name: "Hong Kong Dollar", symbol: "HK$", countryCode: "HK" },
  SEK: { name: "Swedish Krona", symbol: "kr", countryCode: "SE" },
  KRW: { name: "South Korean Won", symbol: "₩", countryCode: "KR" },
  MXN: { name: "Mexican Peso", symbol: "$", countryCode: "MX" },
  TWD: { name: "Taiwan New Dollar", symbol: "NT$", countryCode: "TW" },
  ZAR: { name: "South African Rand", symbol: "R", countryCode: "ZA" },
  THB: { name: "Thai Baht", symbol: "฿", countryCode: "TH" },
  MYR: { name: "Malaysian Ringgit", symbol: "RM", countryCode: "MY" },
};

function countryCodeToFlag(countryCode?: string): string {
  if (!countryCode || countryCode.length !== 2) {
    return "🏳️";
  }

  const upper = countryCode.toUpperCase();
  const chars = [...upper].map((char) => 127397 + char.charCodeAt(0));
  return String.fromCodePoint(...chars);
}

function buildCurrency(code: string): Currency {
  const upperCode = code.toUpperCase();
  const metadata = currencyMetadata[upperCode];

  if (!metadata) {
    return {
      code: upperCode,
      name: upperCode,
      symbol: upperCode,
      flag: "🏳️",
    };
  }

  return {
    code: upperCode,
    name: metadata.name,
    symbol: metadata.symbol,
    countryCode: metadata.countryCode,
    flag: countryCodeToFlag(metadata.countryCode),
  };
}

export function getCurrenciesFromCodes(codes: string[]): Currency[] {
  return codes.map((code) => buildCurrency(code));
}

export const currencyCatalog: Currency[] = Object.keys(currencyMetadata).map((code) => buildCurrency(code));

export const currencies = currencyCatalog;
