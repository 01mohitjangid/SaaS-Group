import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ApiError } from "@shared/api";

import { App } from "./App";
import { AuthProvider } from "./lib/auth";
import { EpisodesPage } from "./pages/EpisodesPage";
import { PublishPage } from "./pages/PublishPage";
import { ShowEditPage } from "./pages/ShowEditPage";
import { ShowsPage } from "./pages/ShowsPage";
import "./index.css";

//: "/admin/" -> "/admin", "/" -> "/". See the note on <BrowserRouter> below.
const BASENAME = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // Retrying a 401 or a 403 just makes the reader wait longer for the same answer.
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.isPermission) && failureCount < 2,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      {/* Vite's BASE_URL follows the build: "/" standalone, "/admin/" when the CMS
          shares a deployment with the viewer. Reading it here means the router and the
          asset URLs can never disagree.

          The trailing slash has to go: react-router's `stripBasename` requires
          `pathname.startsWith(basename)`, so a basename of "/admin/" matches nothing at
          "/admin" and the router renders an empty page rather than an error. */}
      <BrowserRouter basename={BASENAME}>
        <AuthProvider>
          <Routes>
            <Route element={<App />}>
              <Route index element={<Navigate to="/shows" replace />} />
              <Route path="/shows" element={<ShowsPage />} />
              <Route path="/shows/new" element={<ShowEditPage />} />
              <Route path="/shows/:showId" element={<ShowEditPage />} />
              <Route path="/episodes" element={<EpisodesPage />} />
              <Route path="/publish" element={<PublishPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
