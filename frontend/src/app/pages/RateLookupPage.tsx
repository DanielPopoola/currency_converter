import { useState } from "react";
import { ArrowUpRight, ArrowDownRight, TrendingUp, Info } from "lucide-react";
import { CurrencySelector } from "../components/ui/CurrencySelector";
import { currencies, Currency } from "../data/currencies";
import { LineChart, Line, ResponsiveContainer, YAxis, XAxis, Tooltip } from "recharts";

const mockData = [
  { value: 0.910 },
  { value: 0.915 },
  { value: 0.912 },
  { value: 0.920 },
  { value: 0.925 },
  { value: 0.922 },
  { value: 0.930 },
  { value: 0.928 },
  { value: 0.935 },
];

export function RateLookupPage() {
  const [from, setFrom] = useState<Currency>(currencies[0]); // USD
  const [to, setTo] = useState<Currency>(currencies[1]); // EUR

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold text-white tracking-tight">Rate Lookup</h1>
        <p className="text-gray-500 max-w-lg">
          Monitor the latest market rates for any currency pair.
          Real-time updates every 60 seconds.
        </p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
        <div className="bg-[#111827] border border-[#1F2937] rounded-3xl p-6 md:p-8 space-y-6">
          <div className="space-y-4">
            <CurrencySelector
              label="Source Currency"
              selected={from}
              onSelect={setFrom}
              exclude={to.code}
            />
            <CurrencySelector
              label="Target Currency"
              selected={to}
              onSelect={setTo}
              exclude={from.code}
            />
          </div>

          <div className="pt-6 border-t border-[#1F2937]">
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Live Rate</span>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                <span className="w-1 h-1 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-[10px] font-bold text-emerald-500 uppercase tracking-widest">Live</span>
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <div className="flex items-baseline gap-3">
                <h2 className="text-5xl font-mono font-bold text-white tracking-tight tabular-nums">
                  0.9234
                </h2>
                <span className="text-xl font-mono font-bold text-gray-500 tracking-tight">
                  {to.code}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-2">
                <div className="flex items-center gap-1 text-emerald-500 font-mono text-sm font-bold">
                  <ArrowUpRight className="w-3.5 h-3.5" />
                  <span>+0.04%</span>
                </div>
                <span className="text-[11px] text-gray-500 font-medium">Last 24h</span>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-[#111827] border border-[#1F2937] rounded-3xl p-6 md:p-8 flex flex-col h-full min-h-[340px]">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-2 text-gray-400">
              <TrendingUp className="w-4 h-4 text-teal-500" />
              <span className="text-xs font-bold uppercase tracking-widest">Market Movement</span>
            </div>
            <span className="text-[10px] text-gray-500">Last 12 hours</span>
          </div>

          <div className="flex-1 w-full min-h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={mockData}>
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#14b8a6"
                  strokeWidth={2}
                  dot={false}
                  animationDuration={2000}
                />
                <YAxis hide domain={['dataMin - 0.005', 'dataMax + 0.005']} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-6 p-4 rounded-xl bg-[#1F2937]/30 border border-[#374151] flex items-start gap-3">
            <Info className="w-4 h-4 text-teal-500 shrink-0 mt-0.5" />
            <p className="text-[11px] text-gray-400 leading-relaxed">
              This chart shows the aggregated market movement across our 3 providers.
              The rate is updated in real-time and cached in our high-performance Redis cluster.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
