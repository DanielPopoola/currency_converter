import { Outlet, Link, useLocation } from "react-router";
import { Activity, Globe, RefreshCcw, Search, Menu, X } from "lucide-react";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { HealthBanner } from "../ui/HealthBanner";

export function DashboardLayout() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const location = useLocation();

  const navItems = [
    { label: "Conversion", path: "/", icon: RefreshCcw },
    { label: "Rate Lookup", path: "/lookup", icon: Search },
    { label: "Currencies", path: "/currencies", icon: Globe },
  ];

  return (
    <div className="min-h-screen bg-[#0F1117] text-[#E5E7EB] selection:bg-teal-500/30">
      <HealthBanner />

      <div className="flex">
        {/* Desktop Sidebar */}
        <aside className="hidden md:flex flex-col w-64 border-r border-[#1F2937] h-[calc(100vh-40px)] sticky top-10">
          <div className="p-6">
            <div className="flex items-center gap-2 mb-8">
              <div className="w-8 h-8 rounded bg-teal-500 flex items-center justify-center">
                <Activity className="text-[#0F1117] w-5 h-5" />
              </div>
              <span className="font-bold tracking-tight text-white">CURRENCY.API</span>
            </div>

            <nav className="space-y-1">
              {navItems.map((item) => (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center gap-3 px-3 py-2 rounded-md transition-colors ${
                    location.pathname === item.path
                      ? "bg-[#1F2937] text-teal-400"
                      : "text-gray-400 hover:text-white hover:bg-[#1F2937]/50"
                  }`}
                >
                  <item.icon className="w-4 h-4" />
                  <span className="text-sm font-medium">{item.label}</span>
                </Link>
              ))}
            </nav>
          </div>

          <div className="mt-auto p-6 border-t border-[#1F2937]">
            <div className="flex items-center gap-3 px-3 py-2 text-xs text-gray-500 uppercase tracking-widest font-semibold">
              System Status
            </div>
            <div className="mt-2 space-y-2">
              <div className="flex items-center justify-between text-xs px-3">
                <span className="text-gray-400">API Latency</span>
                <span className="text-teal-400 font-mono">24ms</span>
              </div>
              <div className="flex items-center justify-between text-xs px-3">
                <span className="text-gray-400">Cache Hit Rate</span>
                <span className="text-teal-400 font-mono">98.2%</span>
              </div>
            </div>
          </div>
        </aside>

        {/* Mobile Nav */}
        <div className="md:hidden flex items-center justify-between p-4 border-b border-[#1F2937] w-full bg-[#0F1117]/80 backdrop-blur-md sticky top-10 z-20">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-teal-500 flex items-center justify-center">
              <Activity className="text-[#0F1117] w-4 h-4" />
            </div>
            <span className="font-bold text-white text-sm">CURRENCY.API</span>
          </div>
          <button onClick={() => setIsSidebarOpen(true)} className="p-1">
            <Menu className="w-6 h-6" />
          </button>
        </div>

        <AnimatePresence>
          {isSidebarOpen && (
            <motion.div
              initial={{ opacity: 0, x: -100 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -100 }}
              className="fixed inset-0 z-50 bg-[#0F1117] md:hidden"
            >
              <div className="p-6">
                <div className="flex items-center justify-between mb-8">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded bg-teal-500 flex items-center justify-center">
                      <Activity className="text-[#0F1117] w-5 h-5" />
                    </div>
                    <span className="font-bold text-white uppercase tracking-tighter">Currency API</span>
                  </div>
                  <button onClick={() => setIsSidebarOpen(false)}>
                    <X className="w-6 h-6" />
                  </button>
                </div>
                <nav className="space-y-4">
                  {navItems.map((item) => (
                    <Link
                      key={item.path}
                      to={item.path}
                      onClick={() => setIsSidebarOpen(false)}
                      className="flex items-center gap-4 text-xl font-medium"
                    >
                      <item.icon className="w-6 h-6" />
                      {item.label}
                    </Link>
                  ))}
                </nav>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Main Content */}
        <main className="flex-1 min-h-[calc(100vh-40px)] p-6 md:p-10">
          <div className="max-w-4xl mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
