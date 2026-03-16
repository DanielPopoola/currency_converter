import { useEffect, useState } from "react";
import { Currency, currencies as fallbackCurrencies, getCurrenciesFromCodes } from "../data/currencies";
import { fetchSupportedCurrencies } from "../../lib/api";

export function useSupportedCurrencies() {
  const [currencies, setCurrencies] = useState<Currency[]>(fallbackCurrencies);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    const loadCurrencies = async () => {
      try {
        const codes = await fetchSupportedCurrencies();
        if (codes.length > 0) {
          setCurrencies(getCurrenciesFromCodes(codes));
        }
      } catch (error) {
        console.error("Failed to load supported currencies", error);
      } finally {
        setIsLoaded(true);
      }
    };

    void loadCurrencies();
  }, []);

  return {
    currencies,
    isLoaded,
  };
}
