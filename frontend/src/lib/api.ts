const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

interface ConvertApiResponse {
  converted_amount: string;
  exchange_rate: string;
  timestamp: string;
  source: string;
}

interface RateApiResponse {
  rate: string;
  timestamp: string;
  source: string;
}

interface CurrenciesApiResponse {
  currencies: string[];
}

export interface ConvertResult {
  convertedAmount: number;
  exchangeRate: number;
  timestamp: string;
  source: string;
}

export interface RateResult {
  rate: number;
  timestamp: string;
  source: string;
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);

  if (!response.ok) {
    throw new Error(`Request failed (${response.status}) for ${path}`);
  }

  return response.json() as Promise<T>;
}

export async function fetchSupportedCurrencies(): Promise<string[]> {
  const data = await request<CurrenciesApiResponse>("/api/currencies");
  return data.currencies;
}

export async function fetchConversion(from: string, to: string, amount: number): Promise<ConvertResult> {
  const data = await request<ConvertApiResponse>(`/api/convert/${from}/${to}/${amount}`);

  return {
    convertedAmount: Number.parseFloat(data.converted_amount),
    exchangeRate: Number.parseFloat(data.exchange_rate),
    timestamp: data.timestamp,
    source: data.source,
  };
}

export async function fetchRate(from: string, to: string): Promise<RateResult> {
  const data = await request<RateApiResponse>(`/api/rate/${from}/${to}`);

  return {
    rate: Number.parseFloat(data.rate),
    timestamp: data.timestamp,
    source: data.source,
  };
}
