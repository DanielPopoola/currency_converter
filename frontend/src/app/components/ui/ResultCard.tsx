import { ArrowRight, Clock, Info, Loader2 } from "lucide-react";
import { Currency } from "../../data/currencies";
import { motion } from "motion/react";

interface ResultCardProps {
  amount: number;
  from: Currency;
  to: Currency;
  rate: number;
  isLoading?: boolean;
}

export function ResultCard({ amount, from, to, rate, isLoading }: ResultCardProps) {
  const result = (amount * rate).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  });

  if (isLoading) {
    return (
      <div className="w-full bg-[#1F2937]/30 border border-[#374151] rounded-2xl p-10 flex flex-col items-center justify-center gap-4 min-h-[280px]">
        <Loader2 className="w-10 h-10 text-teal-500 animate-spin" />
        <p className="text-gray-500 text-sm font-medium animate-pulse">Fetching latest rates...</p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="w-full bg-[#1F2937]/30 border border-teal-500/20 rounded-2xl p-6 md:p-10 flex flex-col items-center justify-center relative overflow-hidden group hover:border-teal-500/40 transition-all shadow-[0_0_40px_rgba(0,0,0,0.5)]"
    >
      <div className="absolute top-0 right-0 p-4">
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-teal-500/10 border border-teal-500/20 backdrop-blur-sm">
          <div className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
          <span className="text-[10px] font-bold text-teal-500 uppercase tracking-widest">
            Source: Averaged
          </span>
        </div>
      </div>

      <div className="mb-6 flex items-center gap-3 text-gray-500 font-mono text-sm md:text-base">
        <span>{amount.toLocaleString()}</span>
        <span className="font-bold text-gray-400">{from.code}</span>
        <ArrowRight className="w-4 h-4" />
        <span className="font-bold text-white">{to.code}</span>
      </div>

      <div className="flex flex-col items-center gap-2 mb-10">
        <h2 className="text-4xl md:text-6xl lg:text-7xl font-mono font-bold text-white tracking-tight tabular-nums">
          {result}
        </h2>
        <span className="text-xl md:text-2xl font-mono text-gray-500 font-bold">{to.code}</span>
      </div>

      <div className="w-full pt-8 border-t border-[#374151] grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-gray-500 uppercase font-bold tracking-widest">Exchange Rate</span>
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono font-bold text-teal-400">
              1 {from.code} = {rate.toFixed(6)} {to.code}
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-gray-500 uppercase font-bold tracking-widest">Last Updated</span>
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-gray-500" />
            <span className="text-[11px] font-medium text-gray-400">
              Today, {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-gray-500 uppercase font-bold tracking-widest">Providers</span>
          <div className="flex items-center gap-1.5">
            <div className="flex -space-x-1.5">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className={`w-3.5 h-3.5 rounded-full border-2 border-[#111827] ${i === 3 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                />
              ))}
            </div>
            <span className="text-[11px] font-medium text-gray-500">3 sources</span>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
