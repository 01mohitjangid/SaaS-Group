import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { query, request } from "@shared/api";
import type {
  Episode,
  Paged,
  PublishResult,
  PublishRun,
  Reference,
  Show,
  ShowDetail,
  ValidationReport,
} from "@shared/types";

import { useToken } from "./auth";

export function useReference() {
  const token = useToken();
  return useQuery({
    queryKey: ["reference"],
    queryFn: () => request<Reference>("/admin/reference", { token }),
    // The content vocabulary changes when someone edits reference.json, not per session.
    staleTime: Infinity,
  });
}

export interface ShowFilters {
  q?: string;
  section?: string;
  status?: string;
  language?: string;
  limit?: number;
  offset?: number;
}

export function useShows(filters: ShowFilters) {
  const token = useToken();
  return useQuery({
    queryKey: ["shows", filters],
    queryFn: () => request<Paged<Show>>(`/admin/shows${query({ ...filters })}`, { token }),
    placeholderData: (previous) => previous,
  });
}

export function useShow(showId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: ["show", showId],
    queryFn: () => request<ShowDetail>(`/admin/shows/${showId}`, { token }),
    enabled: Boolean(showId),
  });
}

export interface EpisodeFilters {
  q?: string;
  show_slug?: string;
  status?: string;
  language?: string;
  season_number?: number;
  limit?: number;
  offset?: number;
}

export function useEpisodes(filters: EpisodeFilters) {
  const token = useToken();
  return useQuery({
    queryKey: ["episodes", filters],
    queryFn: () => request<Paged<Episode>>(`/admin/episodes${query({ ...filters })}`, { token }),
    placeholderData: (previous) => previous,
  });
}

export function useValidationReport() {
  const token = useToken();
  return useQuery({
    queryKey: ["validation-report"],
    queryFn: () => request<ValidationReport>("/admin/validation-report", { token }),
  });
}

export function usePublishRuns() {
  const token = useToken();
  return useQuery({
    queryKey: ["publish-runs"],
    queryFn: () => request<PublishRun[]>("/admin/publish-runs?limit=20", { token }),
  });
}

/** Anything that changes content invalidates the report: the publish button's reasons
 *  are derived from it, and a stale one would let someone publish into a known failure. */
function useContentMutation<TArgs, TResult>(fn: (token: string, args: TArgs) => Promise<TResult>) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: TArgs) => fn(token, args),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["shows"] });
      void client.invalidateQueries({ queryKey: ["show"] });
      void client.invalidateQueries({ queryKey: ["episodes"] });
      void client.invalidateQueries({ queryKey: ["validation-report"] });
    },
  });
}

export function useSaveShow(showId?: string) {
  return useContentMutation<Record<string, unknown>, ShowDetail>((token, body) =>
    request<ShowDetail>(showId ? `/admin/shows/${showId}` : "/admin/shows", {
      token,
      method: showId ? "PATCH" : "POST",
      body,
    }),
  );
}

export function useSaveEpisode(episodeId?: string, showId?: string) {
  return useContentMutation<Record<string, unknown>, Episode>((token, body) =>
    request<Episode>(
      episodeId ? `/admin/episodes/${episodeId}` : `/admin/shows/${showId}/episodes`,
      { token, method: episodeId ? "PATCH" : "POST", body },
    ),
  );
}

export function useDeleteEpisode() {
  return useContentMutation<string, void>((token, id) =>
    request<void>(`/admin/episodes/${id}`, { token, method: "DELETE" }),
  );
}

export function useUploadArtwork() {
  return useContentMutation<
    { kind: string; file: File; showId?: string; episodeId?: string },
    unknown
  >((token, { kind, file, showId, episodeId }) => {
    const form = new FormData();
    form.set("kind", kind);
    form.set("file", file);
    if (showId) form.set("show_id", showId);
    if (episodeId) form.set("episode_id", episodeId);
    return request("/admin/artwork", { token, method: "POST", form });
  });
}

export function useDeleteArtwork() {
  return useContentMutation<string, void>((token, id) =>
    request<void>(`/admin/artwork/${id}`, { token, method: "DELETE" }),
  );
}

export function usePublish() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<PublishResult>("/admin/catalog/publish", { token, method: "POST" }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["publish-runs"] });
      void client.invalidateQueries({ queryKey: ["validation-report"] });
    },
  });
}

export function useRollback() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      request<PublishResult>(`/admin/catalog/rollback/${runId}`, { token, method: "POST" }),
    onSettled: () => void client.invalidateQueries({ queryKey: ["publish-runs"] }),
  });
}

export function useCancelRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      request<PublishRun>(`/admin/publish-runs/${runId}/cancel`, { token, method: "POST" }),
    onSettled: () => void client.invalidateQueries({ queryKey: ["publish-runs"] }),
  });
}
