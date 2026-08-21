import { ListVideo } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { duration } from "@shared/format";
import { Badge, Input, Select, Skeleton, Table, Td, Th } from "@shared/ui/primitives";
import { EmptyState, ErrorState } from "@shared/ui/states";

import { Pagination } from "../components/Pagination";
import { useEpisodes, useReference } from "../lib/queries";

const LIMIT = 25;

export function EpisodesPage() {
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const reference = useReference();

  const set = (key: string, value: string) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== "offset") next.delete("offset");
      return next;
    });

  const episodes = useEpisodes({
    q: params.get("q") ?? undefined,
    status: params.get("status") ?? undefined,
    language: params.get("language") ?? undefined,
    show_slug: params.get("show_slug") ?? undefined,
    limit: LIMIT,
    offset: Number(params.get("offset") ?? 0),
  });

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold tracking-tight">Episodes</h1>

      <form
        className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          set("q", term);
        }}
      >
        <Input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          onBlur={() => set("q", term)}
          placeholder="Search episode titles…"
          aria-label="Search episodes"
        />
        <Input
          defaultValue={params.get("show_slug") ?? ""}
          onBlur={(event) => set("show_slug", event.target.value)}
          placeholder="Filter by show slug…"
          aria-label="Show slug"
        />
        <Select
          value={params.get("status") ?? ""}
          onChange={(event) => set("status", event.target.value)}
          aria-label="Status"
        >
          <option value="">Any status</option>
          <option value="draft">Draft</option>
          <option value="published">Published</option>
        </Select>
        <Select
          value={params.get("language") ?? ""}
          onChange={(event) => set("language", event.target.value)}
          aria-label="Language"
        >
          <option value="">Any language</option>
          {reference.data?.languages.map((code) => (
            <option key={code} value={code}>
              {code.toUpperCase()}
            </option>
          ))}
        </Select>
      </form>

      <div className="rounded-lg border border-border bg-card">
        {episodes.isPending ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        ) : episodes.error ? (
          <div className="p-4">
            <ErrorState error={episodes.error} onRetry={() => episodes.refetch()} />
          </div>
        ) : episodes.data.items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={ListVideo}
              title="No episodes match those filters"
              hint="Try a different word, or clear a filter."
            />
          </div>
        ) : (
          <>
            <Table>
              <thead className="border-b border-border">
                <tr>
                  <Th>Episode</Th>
                  <Th>Show</Th>
                  <Th>Season</Th>
                  <Th>Language</Th>
                  <Th>Run time</Th>
                  <Th>Status</Th>
                  <Th>Thumb</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {episodes.data.items.map((episode) => (
                  <tr key={episode.id} className="transition-colors hover:bg-accent/40">
                    <Td>
                      <span className="font-medium">{episode.title}</span>
                      <p className="text-xs text-muted-foreground">{episode.content_group}</p>
                    </Td>
                    <Td>
                      <Link
                        to={`/shows/${episode.show_id}`}
                        className="text-muted-foreground hover:text-foreground hover:underline"
                      >
                        {episode.show_title}
                      </Link>
                    </Td>
                    <Td className="text-muted-foreground">
                      {episode.season_number === 0 ? (
                        <Badge variant="outline">Trailer</Badge>
                      ) : (
                        `S${episode.season_number}E${episode.episode_number}`
                      )}
                    </Td>
                    <Td className="text-muted-foreground">{episode.language.toUpperCase()}</Td>
                    <Td className="text-muted-foreground">{duration(episode.duration_seconds)}</Td>
                    <Td>
                      <Badge variant={episode.status === "published" ? "published" : "draft"}>
                        {episode.status}
                      </Badge>
                    </Td>
                    <Td>
                      {episode.artwork.length > 0 ? (
                        <span className="text-success">✓</span>
                      ) : (
                        <Badge variant="blocker">Missing</Badge>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={episodes.data.page}
              onChange={(offset) => set("offset", String(offset))}
            />
          </>
        )}
      </div>
    </div>
  );
}
