import { createBrowserRouter } from "react-router";
import { DashboardLayout } from "./components/layouts/DashboardLayout";
import { ConversionPage } from "./pages/ConversionPage";
import { RateLookupPage } from "./pages/RateLookupPage";
import { CurrenciesPage } from "./pages/CurrenciesPage";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: DashboardLayout,
    children: [
      {
        index: true,
        Component: ConversionPage,
      },
      {
        path: "lookup",
        Component: RateLookupPage,
      },
      {
        path: "currencies",
        Component: CurrenciesPage,
      },
    ],
  },
]);
