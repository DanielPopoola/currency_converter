import { useState } from "react";
import { Search, Globe, Filter, Star, Clock } from "lucide-react";
import { currencies } from "../data/currencies";

export function CurrenciesPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [favorites, setFavorites] = useState<string[]>(["USD", "EUR", "GBP"]);

  const toggleFavorite = (code: string) => {
    setFavorites(prev =>
      prev.includes(code) ? prev.filter(c => c !== code) : [...prev, code]
    );
  };

  const filteredCurrencies = currencies.filter(
    (c) =>
      c.code.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const sortedCurrencies = [...filteredCurrencies].sort((a, b) => {
    const aFav = favorites.includes(a.code);
    const bFav = favorites.includes(b.code);
    if (aFav && !bFav) return -1;
    if (!aFav && bFav) return 1;
    return 0;
  });

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold text-white tracking-tight">Supported Currencies</h1>
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <p className="text-gray-500 max-w-lg">
            {currencies.length} currencies currently supported via our aggregation API.
            All rates are provided in real-time.
          </p>
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-teal-500/10 border border-teal-500/20">
            <Globe className="w-3 h-3 text-teal-500" />
            <span className="text-[10px] font-bold text-teal-500 uppercase tracking-widest">Global Coverage</span>
          </div>
        </div>
      </header>

      <div className="relative group max-w-xl">
        <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none transition-colors group-focus-within:text-teal-500 text-gray-500">
          <Search className="w-5 h-5" />
        </div>
        <input
          type="text"
          placeholder="Search for a currency code or name..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full bg-[#111827] border border-[#1F2937] hover:border-[#374151] focus:border-teal-500/50 focus:bg-[#1F2937] focus:ring-1 focus:ring-teal-500/20 pl-12 pr-4 py-4 rounded-2xl transition-all font-medium text-white placeholder-gray-600"
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {sortedCurrencies.map((currency) => (
          <div
            key={currency.code}
            className="group relative bg-[#111827] border border-[#1F2937] hover:border-teal-500/30 p-5 rounded-2xl transition-all shadow-sm hover:shadow-teal-500/5 hover:-translate-y-1"
          >
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <span className="text-2xl">{currency.flag}</span>
                <div className="flex flex-col">
                  <span className="text-lg font-mono font-bold text-white tracking-tight">{currency.code}</span>
                  <span className="text-[11px] font-medium text-gray-500 truncate max-w-[140px]">{currency.name}</span>
                </div>
              </div>
              <button
                onClick={() => toggleFavorite(currency.code)}
                className={`p-1.5 rounded-lg border transition-all ${
                  favorites.includes(currency.code)
                    ? "bg-teal-500/10 border-teal-500/30 text-teal-500"
                    : "bg-[#1F2937] border-[#374151] text-gray-600 hover:text-white"
                }`}
              >
                <Star className={`w-3.5 h-3.5 ${favorites.includes(currency.code) ? "fill-teal-500" : ""}`} />
              </button>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-[#1F2937]">
              <div className="flex items-center gap-1.5">
                <Clock className="w-3 h-3 text-gray-600" />
                <span className="text-[10px] text-gray-600 uppercase font-bold tracking-widest">Updated: 1m ago</span>
              </div>
              <div className="flex -space-x-1">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="w-2.5 h-2.5 rounded-full border border-[#111827] bg-emerald-500/80" />
                ))}
              </div>
            </div>
          </div>
        ))}

        {filteredCurrencies.length === 0 && (
          <div className="col-span-full py-20 flex flex-col items-center justify-center gap-4 text-center">
            <div className="w-16 h-16 rounded-full bg-[#111827] flex items-center justify-center text-gray-600">
              <Search className="w-8 h-8" />
            </div>
            <div>
              <h3 className="text-white font-medium">No currencies found</h3>
              <p className="text-sm text-gray-500">Try searching for a different code or name.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
