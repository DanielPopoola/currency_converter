import { useState, useCallback } from "react";
import { ArrowLeftRight, Calculator, RefreshCw, Sparkles, TrendingUp } from "lucide-react";
import { CurrencySelector } from "../components/ui/CurrencySelector";
import { ResultCard } from "../components/ui/ResultCard";
import { currencies, Currency } from "../data/currencies";
import { motion } from "motion/react";

export function ConversionPage() {
  const [from, setFrom] = useState<Currency>(currencies[0]); // USD
  const [to, setTo] = useState<Currency>(currencies[1]); // EUR
  const [amount, setAmount] = useState<string>("1000.00");
  const [isLoading, setIsLoading] = useState(false);
  const [hasConverted, setHasConverted] = useState(false);
  const [rate, setRate] = useState(0.923456);

  const handleSwap = () => {
    setFrom(to);
    setTo(from);
  };

  const handleConvert = useCallback(() => {
    setIsLoading(true);
    // Mocking an API call with delay
    setTimeout(() => {
      setRate(0.85 + Math.random() * 0.2);
      setIsLoading(false);
      setHasConverted(true);
    }, 800);
  }, []);

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold text-white tracking-tight">Convert Currency</h1>
        <p className="text-gray-500 max-w-lg">
          Get real-time exchange rates aggregated from premium data providers.
          Precision financial tooling for modern fintech workflows.
        </p>
      </header>

      <div className="bg-[#111827] border border-[#1F2937] rounded-3xl p-6 md:p-8 shadow-2xl relative overflow-hidden">
        {/* Subtle background glow */}
        <div className="absolute top-0 left-0 w-64 h-64 bg-teal-500/5 blur-[100px] pointer-events-none" />
        <div className="absolute bottom-0 right-0 w-64 h-64 bg-teal-500/5 blur-[100px] pointer-events-none" />

        <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-end relative z-10">
          <div className="md:col-span-3">
            <label className="block text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1.5 px-0.5">
              Amount
            </label>
            <div className="relative">
              <input
                type="text"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-full bg-[#1F2937]/50 border border-[#374151] focus:border-teal-500/50 focus:bg-[#1F2937] focus:ring-1 focus:ring-teal-500/20 px-4 py-3 rounded-xl transition-all font-mono text-lg font-bold text-white"
                placeholder="0.00"
              />
              <div className="absolute right-4 top-1/2 -translate-y-1/2 text-[11px] font-bold text-gray-500 font-mono">
                {from.code}
              </div>
            </div>
          </div>

          <div className="md:col-span-4">
            <CurrencySelector
              label="From"
              selected={from}
              onSelect={setFrom}
              exclude={to.code}
            />
          </div>

          <div className="md:col-span-1 flex items-center justify-center pb-2">
            <button
              onClick={handleSwap}
              className="p-3 rounded-full bg-[#1F2937] border border-[#374151] hover:bg-[#374151] hover:border-teal-500/50 transition-all text-gray-400 hover:text-white"
            >
              <ArrowLeftRight className="w-4 h-4" />
            </button>
          </div>

          <div className="md:col-span-4">
            <CurrencySelector
              label="To"
              selected={to}
              onSelect={setTo}
              exclude={from.code}
            />
          </div>
        </div>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-between gap-6 pt-6 border-t border-[#1F2937]">
          <div className="flex items-center gap-6 text-xs text-gray-500">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-3.5 h-3.5" />
              <span>Real-time market rates</span>
            </div>
            <div className="flex items-center gap-2">
              <Calculator className="w-3.5 h-3.5" />
              <span>Precision: 6 decimal places</span>
            </div>
          </div>

          <button
            onClick={handleConvert}
            disabled={isLoading}
            className="w-full sm:w-auto px-8 py-3 bg-teal-500 hover:bg-teal-400 disabled:opacity-50 text-[#0F1117] font-bold rounded-xl transition-all shadow-[0_0_20px_rgba(20,184,166,0.3)] flex items-center justify-center gap-2"
          >
            {isLoading ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            {isLoading ? "Converting..." : "Convert Now"}
          </button>
        </div>
      </div>

      {hasConverted || isLoading ? (
        <ResultCard
          amount={parseFloat(amount) || 0}
          from={from}
          to={to}
          rate={rate}
          isLoading={isLoading}
        />
      ) : (
        <div className="p-10 border border-dashed border-[#1F2937] rounded-3xl flex flex-col items-center justify-center gap-4 text-center">
          <div className="w-12 h-12 rounded-full bg-[#1F2937] flex items-center justify-center text-gray-600">
            <Calculator className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-white font-medium">Ready to convert</h3>
            <p className="text-sm text-gray-500">Enter an amount and select currency pairs to start.</p>
          </div>
        </div>
      )}
    </div>
  );
}
