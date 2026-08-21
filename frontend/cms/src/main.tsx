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
      <BrowserRouter>
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
