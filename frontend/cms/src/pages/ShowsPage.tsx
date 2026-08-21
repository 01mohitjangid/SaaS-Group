import { Film, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { relativeTime, sectionName } from "@shared/format";
import { Badge, Input, Select, Skeleton, Table, Td, Th } from "@shared/ui/primitives";
import { Button } from "@shared/ui/button";
import { EmptyState, ErrorState } from "@shared/ui/states";

import { Pagination } from "../components/Pagination";
import { useReference, useShows } from "../lib/queries";

const LIMIT = 20;

export function ShowsPage() {
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const reference = useReference();

  const set = (key: string, value: string) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (value) next.set(key, value);
      else next.delete(key);
      // Any filter change invalidates the page you were on.
      if (key !== "offset") next.delete("offset");
      return next;
    });

  const filters = {
    q: params.get("q") ?? undefined,
    section: params.get("section") ?? undefined,
    status: params.get("status") ?? undefined,
    language: params.get("language") ?? undefined,
    limit: LIMIT,
    offset: Number(params.get("offset") ?? 0),
  };
  const shows = useShows(filters);
  const filtered = Boolean(filters.q || filters.section || filters.status || filters.language);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Shows</h1>
        <Button asChild size="sm" className="ml-auto">
          <Link to="/shows/new">
            <Plus aria-hidden />
            New show
          </Link>
        </Button>
      </div>

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
          placeholder="Search title or slug…"
          aria-label="Search shows"
        />
        <Select
          value={params.get("section") ?? ""}
          onChange={(event) => set("section", event.target.value)}
          aria-label="Section"
        >
          <option value="">All sections</option>
          {reference.data?.sections.map((key) => (
            <option key={key} value={key}>
              {sectionName(key)}
            </option>
          ))}
        </Select>
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
        {shows.isPending ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : shows.error ? (
          <div className="p-4">
            <ErrorState error={shows.error} onRetry={() => shows.refetch()} />
          </div>
        ) : shows.data.items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={Film}
              title={filtered ? "No shows match those filters" : "No shows yet"}
              hint={
                filtered
                  ? "Try a different word, or clear a filter."
                  : "Create the first show to get started."
              }
              action={
                filtered ? (
                  <Button size="sm" variant="secondary" onClick={() => setParams({})}>
                    Clear filters
                  </Button>
                ) : (
                  <Button asChild size="sm">
                    <Link to="/shows/new">New show</Link>
                  </Button>
                )
              }
            />
          </div>
        ) : (
          <>
            <Table>
              <thead className="border-b border-border">
                <tr>
                  <Th>Show</Th>
                  <Th>Section</Th>
                  <Th>Status</Th>
                  <Th>Episodes</Th>
                  <Th>Languages</Th>
                  <Th>Artwork</Th>
                  <Th>Updated</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {shows.data.items.map((show) => (
                  <tr key={show.id} className="transition-colors hover:bg-accent/40">
                    <Td>
                      <Link to={`/shows/${show.id}`} className="font-medium hover:underline">
                        {show.title}
                      </Link>
                      <p className="text-xs text-muted-foreground">{show.slug}</p>
                    </Td>
                    <Td className="text-muted-foreground">
                      {show.section ? (
                        sectionName(show.section)
                      ) : (
                        <Badge variant="warning">No section</Badge>
                      )}
                    </Td>
                    <Td>
                      <Badge variant={show.status === "published" ? "published" : "draft"}>
                        {show.status}
                      </Badge>
                    </Td>
                    <Td className="text-muted-foreground">{show.episode_count}</Td>
                    <Td className="text-muted-foreground">
                      {show.languages.map((c) => c.toUpperCase()).join(" · ") || "—"}
                    </Td>
                    <Td>
                      <span
                        className={
                          show.artwork.length === 2 ? "text-success" : "text-muted-foreground"
                        }
                      >
                        {show.artwork.length}/2
                      </span>
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {relativeTime(show.updated_at)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={shows.data.page}
              onChange={(offset) => set("offset", String(offset))}
            />
          </>
        )}
      </div>
    </div>
  );
}
