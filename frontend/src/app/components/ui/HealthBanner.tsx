import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchHealth, type ProviderHealth } from "../../../lib/api";

type ProviderStatus = "operational" | "degraded" | "down";

interface Provider {
  name: string;
  status: ProviderStatus;
}

const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  fixerio: "Fixer.io",
  openexchange: "OpenExchangeRates",
  currencyapi: "CurrencyAPI",
};

function toBannerStatus(status: ProviderHealth["status"]): ProviderStatus {
  return status === "operational" ? "operational" : "down";
}

export function HealthBanner() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const loadHealth = async () => {
      try {
        const result = await fetchHealth();

        if (!mounted) {
          return;
        }

        setProviders(
          result.providers.map((provider) => ({
            name: PROVIDER_DISPLAY_NAMES[provider.name] ?? provider.name,
            status: toBannerStatus(provider.status),
          })),
        );
        setError(null);
      } catch {
        if (!mounted) {
          return;
        }

        setError("Unable to load provider health");
      }
    };

    void loadHealth();
    const intervalId = window.setInterval(() => {
      void loadHealth();
    }, 30000);

    return () => {
      mounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  const downProviders = providers.filter((p) => p.status === "down").length;
  const operationalCount = providers.filter((p) => p.status === "operational").length;

  const getStatusColor = (status: ProviderStatus) => {
    switch (status) {
      case "operational":
        return "bg-emerald-500";
      case "degraded":
        return "bg-amber-500";
      case "down":
        return "bg-rose-500";
      default:
        return "bg-gray-500";
    }
  };

  return (
    <div className="h-10 bg-[#111827] border-b border-[#1F2937] flex items-center justify-between px-4 md:px-6 sticky top-0 z-30">
      <div className="flex items-center gap-6 overflow-x-auto scrollbar-none">
        <div className="flex items-center gap-4 shrink-0">
          {providers.map((provider) => (
            <div key={provider.name} className="flex items-center gap-2">
              <div
                className={`w-1.5 h-1.5 rounded-full ${getStatusColor(provider.status)} shadow-[0_0_8px_rgba(16,185,129,0.3)]`}
              />
              <span className="text-[10px] md:text-[11px] font-medium text-gray-400 uppercase tracking-wider">
                {provider.name}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0 ml-4">
        {(error || downProviders > 0) && (
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">
            <AlertTriangle className="w-3 h-3 text-amber-500" />
            <span className="text-[10px] font-medium text-amber-500 whitespace-nowrap">
              {error ?? `${downProviders} provider(s) down`}
            </span>
          </div>
        )}
        {!error && downProviders === 0 && providers.length > 0 && (
          <div className="hidden sm:flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20">
            <CheckCircle2 className="w-3 h-3 text-emerald-500" />
            <span className="text-[10px] font-medium text-emerald-500 uppercase tracking-widest">System Stable</span>
          </div>
        )}
        {!error && providers.length > 0 && operationalCount < providers.length && (
          <div className="hidden sm:flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">
            <AlertTriangle className="w-3 h-3 text-amber-500" />
            <span className="text-[10px] font-medium text-amber-500 whitespace-nowrap">
              {operationalCount}/{providers.length} providers operational
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
