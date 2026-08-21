/** Response shapes from the Peblo TV API. Kept beside the client so both apps agree. */

export type Status = "draft" | "published";
export type ArtworkKind = "poster" | "banner" | "thumbnail";

export interface Artwork {
  id: string;
  kind: ArtworkKind;
  url: string;
  width: number;
  height: number;
  byte_size: number;
}

export interface Episode {
  id: string;
  external_id: string | null;
  show_id: string;
  show_slug: string;
  show_title: string;
  season_number: number;
  episode_number: number;
  title: string;
  duration_seconds: number | null;
  language: string;
  content_group: string;
  status: Status;
  artwork: Artwork[];
}

export interface Show {
  id: string;
  slug: string;
  title: string;
  synopsis: string;
  section: string | null;
  categories: string[];
  status: Status;
  episode_count: number;
  languages: string[];
  artwork: Artwork[];
  updated_at: string;
}

export interface ShowDetail extends Show {
  episodes: Episode[];
}

export interface Page {
  total: number;
  limit: number;
  offset: number;
}

export interface Paged<T> {
  items: T[];
  page: Page;
}

export interface ArtworkSpec {
  aspect: string;
  target: string;
  min_width: number;
  min_height: number;
  max_kb: number;
  used_for: "shows" | "episodes";
}

export interface Reference {
  sections: string[];
  categories: string[];
  languages: string[];
  statuses: Status[];
  artwork: Record<ArtworkKind, ArtworkSpec>;
}

export interface Issue {
  code: string;
  severity: "blocker" | "warning";
  entity: string;
  message: string;
  fix_hint: string;
  show_slug: string | null;
}

export interface IssueGroup {
  show_slug: string | null;
  show_title: string | null;
  blockers: Issue[];
  warnings: Issue[];
}

export interface ValidationReport {
  can_publish: boolean;
  blocker_count: number;
  warning_count: number;
  groups: IssueGroup[];
}

export interface PublishRun {
  id: string;
  status: "running" | "succeeded" | "failed";
  started_at: string;
  finished_at: string | null;
  created_by_email: string;
  catalog_key: string | null;
  checksum_sha256: string | null;
  counts: Record<string, number>;
  blocker_count: number;
  error: string | null;
  rolled_back_to: string | null;
  reused: boolean;
}

export interface PublishResult {
  run: PublishRun;
  reused: boolean;
  warnings: Issue[];
}

// --- the published catalogue the viewer reads -------------------------------

export interface CatalogEpisode {
  ref: string;
  content_group: string;
  episode_number: number;
  title: string;
  duration_seconds: number | null;
  languages: string[];
  artwork: Partial<Record<ArtworkKind, string>>;
}

export interface CatalogSeason {
  season_number: number;
  title: string;
  episodes: CatalogEpisode[];
}

export interface CatalogShow {
  slug: string;
  title: string;
  synopsis: string;
  categories: string[];
  languages: string[];
  artwork: Partial<Record<ArtworkKind, string>>;
  seasons: CatalogSeason[];
  trailers: CatalogEpisode[];
}

export interface CatalogSection {
  key: string;
  shows: CatalogShow[];
}

export interface Catalog {
  version: string;
  generated_at: string | null;
  counts: Record<string, number>;
  sections: CatalogSection[];
}

export interface SearchResult {
  section: string;
  slug: string;
  title: string;
  synopsis: string;
  categories: string[];
  languages: string[];
  artwork: Partial<Record<ArtworkKind, string>>;
}

export interface SearchResponse {
  query: {
    q: string | null;
    category: string | null;
    language: string | null;
    section: string | null;
  };
  catalog_version: string | null;
  total: number;
  limit: number;
  offset: number;
  results: SearchResult[];
}
