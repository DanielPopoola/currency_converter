import { useState, useRef, useEffect } from "react";
import { ChevronDown, Search } from "lucide-react";
import { currencies as defaultCurrencies, Currency } from "../../data/currencies";
import { motion, AnimatePresence } from "motion/react";

interface CurrencySelectorProps {
  currencies?: Currency[];
  label: string;
  selected: Currency;
  onSelect: (currency: Currency) => void;
  exclude?: string;
}

export function CurrencySelector({ label, selected, onSelect, exclude, currencies = defaultCurrencies }: CurrencySelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const filteredCurrencies = currencies.filter(
    (c) =>
      c.code !== exclude &&
      (c.code.toLowerCase().includes(searchTerm.toLowerCase()) ||
        c.name.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  return (
    <div className="relative" ref={dropdownRef}>
      <label className="block text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1.5 px-0.5">
        {label}
      </label>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between bg-[#1F2937]/50 border border-[#374151] hover:border-teal-500/50 hover:bg-[#1F2937] px-4 py-3 rounded-xl transition-all"
      >
        <div className="flex items-center gap-3">
          <span className="text-xl">{selected.flag}</span>
          <div className="flex flex-col items-start">
            <span className="text-lg font-bold leading-tight text-white font-mono">{selected.code}</span>
            <span className="text-[10px] text-gray-500 font-medium truncate max-w-[120px]">
              {selected.name}
            </span>
          </div>
        </div>
        <ChevronDown className={`w-4 h-4 text-gray-500 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="absolute z-50 mt-2 w-full bg-[#1F2937] border border-[#374151] rounded-xl shadow-2xl overflow-hidden"
          >
            <div className="p-2 border-b border-[#374151] flex items-center gap-2">
              <Search className="w-4 h-4 text-gray-500" />
              <input
                autoFocus
                type="text"
                placeholder="Search currency..."
                className="w-full bg-transparent border-none text-sm text-white focus:ring-0 placeholder-gray-600"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>
            <div className="max-h-60 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-700">
              {filteredCurrencies.map((currency) => (
                <button
                  key={currency.code}
                  type="button"
                  onClick={() => {
                    onSelect(currency);
                    setIsOpen(false);
                  }}
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-[#374151] transition-colors"
                >
                  <span className="text-xl">{currency.flag}</span>
                  <div className="flex flex-col items-start">
                    <span className="text-sm font-bold text-white font-mono">{currency.code}</span>
                    <span className="text-[11px] text-gray-500">{currency.name}</span>
                  </div>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
