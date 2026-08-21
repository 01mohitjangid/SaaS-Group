import { useQuery } from "@tanstack/react-query";

import { query, request } from "@shared/api";
import type { Catalog, SearchResponse } from "@shared/types";

/** The viewer sends no credentials, ever. These endpoints are public by design and the
 *  app has no token to leak — which is also why nothing here can reach admin data. */

export function useCatalog() {
  return useQuery({
    queryKey: ["catalog"],
    queryFn: () => request<Catalog>("/catalog"),
    // A published run never changes, so re-fetching on every focus is pure waste.
    staleTime: 60_000,
  });
}

export function useSearch(params: {
  q?: string;
  category?: string;
  language?: string;
  section?: string;
}) {
  const active = Boolean(params.q || params.category || params.language || params.section);
  return useQuery({
    queryKey: ["search", params],
    queryFn: () => request<SearchResponse>(`/catalog/search${query({ ...params, limit: 60 })}`),
    enabled: active,
    staleTime: 30_000,
  });
}
