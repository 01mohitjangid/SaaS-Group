import { SearchX } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { languageName, sectionName } from "@shared/format";
import { Poster } from "@shared/ui/image";
import { Input, Select } from "@shared/ui/primitives";
import { Alert, EmptyState, ErrorState, LoadingState } from "@shared/ui/states";

import { useCatalog, useSearch } from "../lib/queries";

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");

  const category = params.get("category") ?? "";
  const language = params.get("language") ?? "";
  const section = params.get("section") ?? "";

  // Debounced, so a child typing "kite" makes one request rather than four.
  useEffect(() => {
    const id = setTimeout(() => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (term) next.set("q", term);
          else next.delete("q");
          return next;
        },
        { replace: true },
      );
    }, 250);
    return () => clearTimeout(id);
  }, [term, setParams]);

  const search = useSearch({
    q: params.get("q") ?? undefined,
    category: category || undefined,
    language: language || undefined,
    section: section || undefined,
  });

  // The filter options come from the published catalogue itself, so a filter can never
  // offer a value that returns nothing.
  const catalog = useCatalog();
  const { categories, languages, sections } = useMemo(() => {
    const shows = catalog.data?.sections.flatMap((s) => s.shows) ?? [];
    return {
      categories: [...new Set(shows.flatMap((s) => s.categories))].sort(),
      languages: [...new Set(shows.flatMap((s) => s.languages))].sort(),
      sections: catalog.data?.sections.map((s) => s.key) ?? [],
    };
  }, [catalog.data]);

  const update = (key: string, value: string) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );

  const active = Boolean(params.get("q") || category || language || section);

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-8 sm:px-8">
      <h1 className="text-2xl font-semibold tracking-tight">Search</h1>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="Show, episode or category…"
          aria-label="Search"
          autoFocus
        />
        <Select
          value={section}
          onChange={(event) => update("section", event.target.value)}
          aria-label="Section"
        >
          <option value="">All sections</option>
          {sections.map((key) => (
            <option key={key} value={key}>
              {sectionName(key)}
            </option>
          ))}
        </Select>
        <Select
          value={category}
          onChange={(event) => update("category", event.target.value)}
          aria-label="Category"
        >
          <option value="">All categories</option>
          {categories.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </Select>
        <Select
          value={language}
          onChange={(event) => update("language", event.target.value)}
          aria-label="Language"
        >
          <option value="">Any language</option>
          {languages.map((code) => (
            <option key={code} value={code}>
              {languageName(code)}
            </option>
          ))}
        </Select>
      </div>

      {catalog.error ? (
        <div className="mt-3">
          <Alert tone="warning" title="Filters are unavailable">
            The catalogue could not be loaded, so the filter lists are empty. Searching by name
            still works.
          </Alert>
        </div>
      ) : null}

      <div className="mt-8">
        {!active ? (
          <EmptyState
            title="Search the catalogue"
            hint="Type a show or episode name, or pick a filter to browse."
          />
        ) : search.isPending ? (
          <LoadingState label="Searching…" />
        ) : search.error ? (
          <ErrorState error={search.error} onRetry={() => search.refetch()} />
        ) : search.data.results.length === 0 ? (
          <EmptyState
            icon={SearchX}
            title="Nothing matches that"
            hint={
              params.get("q")
                ? `No show, episode or category matches “${params.get("q")}”. Try a shorter word, or clear the filters.`
                : "No shows match these filters. Try clearing one."
            }
          />
        ) : (
          <>
            <p className="mb-4 text-sm text-muted-foreground" role="status" aria-live="polite">
              {search.data.total} result{search.data.total === 1 ? "" : "s"}
            </p>
            <ul className="grid grid-cols-3 gap-4 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
              {search.data.results.map((show) => (
                <li key={show.slug}>
                  <Link to={`/shows/${show.slug}`} className="group block">
                    <Poster src={show.artwork.poster} alt={show.title} ratio="2/3" />
                    <p className="mt-2 line-clamp-2 text-xs text-muted-foreground group-hover:text-foreground">
                      {show.title}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
