import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Film, Play } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { request } from "@shared/api";
import { duration, languageName, sectionName } from "@shared/format";
import type { CatalogEpisode, CatalogShow } from "@shared/types";
import { Badge, Card } from "@shared/ui/primitives";
import { Button } from "@shared/ui/button";
import { Poster } from "@shared/ui/image";
import { ErrorState, LoadingState } from "@shared/ui/states";

type ShowResponse = CatalogShow & { section: string };

/** One row of the episode list.
 *
 * Uses the **thumbnail** (16:9) — the surface that artwork was cut for. A grouped
 * episode is one row with its languages as choices, never two rows: that is the whole
 * point of `content_group`, and showing it twice would undo it in the UI.
 */
function EpisodeRow({ episode }: { episode: CatalogEpisode }) {
  const [language, setLanguage] = useState(episode.languages[0] ?? "en");

  return (
    <li className="flex gap-4 rounded-lg p-3 transition-colors hover:bg-accent/50">
      <div className="w-32 shrink-0 sm:w-44">
        <Poster src={episode.artwork.thumbnail} alt={episode.title} ratio="16/9" sizes="176px" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-muted-foreground">{episode.episode_number}</span>
          <h3 className="truncate text-sm font-medium">{episode.title}</h3>
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {duration(episode.duration_seconds)}
          </span>
        </div>

        {episode.languages.length > 1 ? (
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs text-muted-foreground" id={`audio-${episode.ref}`}>
              Audio
            </span>
            {/* A radiogroup owes keyboard users a roving tabindex and arrow keys. Rather
                than advertise semantics we do not implement, these are plain toggle
                buttons — each is tabbable and `aria-pressed` says which is on. */}
            <div className="flex gap-1" role="group" aria-labelledby={`audio-${episode.ref}`}>
              {episode.languages.map((code) => (
                <button
                  key={code}
                  type="button"
                  aria-pressed={language === code}
                  onClick={() => setLanguage(code)}
                  className={`rounded-full border px-2 py-0.5 text-xs transition-colors ${
                    language === code
                      ? "border-foreground bg-foreground text-background"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {languageName(code)}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <p className="mt-2 text-xs text-muted-foreground">
            {languageName(episode.languages[0] ?? "en")}
          </p>
        )}
      </div>
    </li>
  );
}

export function ShowPage() {
  const { slug = "" } = useParams();
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["show", slug],
    queryFn: () => request<ShowResponse>(`/catalog/shows/${encodeURIComponent(slug)}`),
    staleTime: 60_000,
  });
  const [season, setSeason] = useState(0);

  if (isPending) return <LoadingState />;
  if (error)
    return (
      <div className="p-8">
        <ErrorState error={error} onRetry={() => refetch()} />
        <div className="mt-4 text-center">
          <Button asChild variant="ghost" size="sm">
            <Link to="/">
              <ArrowLeft aria-hidden />
              Back to browse
            </Link>
          </Button>
        </div>
      </div>
    );

  const current = data.seasons[season] ?? data.seasons[0];

  return (
    <div>
      <div className="relative h-[38vw] max-h-[420px] min-h-[220px] w-full overflow-hidden">
        {data.artwork.banner ? (
          <img
            src={data.artwork.banner}
            alt=""
            fetchPriority="high"
            className="size-full object-cover"
          />
        ) : (
          <div className="size-full bg-accent" />
        )}
        <div className="absolute inset-0 bg-linear-to-t from-background via-background/50 to-transparent" />
      </div>

      <div className="mx-auto -mt-24 max-w-[1100px] px-4 pb-16 sm:px-8">
        <Button asChild variant="ghost" size="sm" className="mb-4">
          <Link to="/">
            <ArrowLeft aria-hidden />
            Browse
          </Link>
        </Button>

        <div className="flex flex-col gap-6 sm:flex-row">
          <div className="w-32 shrink-0 sm:w-48">
            <Poster src={data.artwork.poster} alt={data.title} ratio="2/3" />
          </div>

          <div className="min-w-0">
            <h1 className="text-3xl font-black tracking-tight sm:text-4xl">{data.title}</h1>
            <p className="mt-3 max-w-2xl text-sm text-foreground/85">{data.synopsis}</p>

            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant="outline">{sectionName(data.section)}</Badge>
              {data.languages.map((code) => (
                <Badge key={code} variant="outline">
                  {languageName(code)}
                </Badge>
              ))}
              {data.categories.map((category) => (
                <Badge key={category}>{sectionName(category)}</Badge>
              ))}
            </div>

            {/* Season 0 is trailers, never a season. It gets its own shelf so the season
                picker stays honest about how many seasons the show has. */}
            {data.trailers.length > 0 ? (
              <div className="mt-5">
                <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                  <Film className="size-4" aria-hidden />
                  Trailers
                </h2>
                <div className="flex gap-3">
                  {data.trailers.map((trailer) => (
                    <div key={trailer.ref} className="w-40">
                      <Poster
                        src={trailer.artwork.thumbnail}
                        alt={trailer.title}
                        ratio="16/9"
                        sizes="160px"
                      />
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {trailer.title} · {duration(trailer.duration_seconds)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <Card className="mt-8">
          <div className="flex items-center gap-3 border-b border-border p-3">
            <Play className="size-4 text-primary" aria-hidden />
            <h2 className="text-sm font-semibold">Episodes</h2>
            {data.seasons.length > 1 ? (
              <select
                className="ml-auto rounded-md border border-input bg-muted px-2 py-1 text-sm"
                value={season}
                onChange={(event) => setSeason(Number(event.target.value))}
                aria-label="Season"
              >
                {data.seasons.map((option, index) => (
                  <option key={option.season_number} value={index}>
                    {option.title}
                  </option>
                ))}
              </select>
            ) : (
              <span className="ml-auto text-xs text-muted-foreground">{current?.title}</span>
            )}
          </div>

          {current?.episodes.length ? (
            <ul className="divide-y divide-border/60 p-1">
              {current.episodes.map((episode) => (
                <EpisodeRow key={episode.content_group} episode={episode} />
              ))}
            </ul>
          ) : (
            <p className="p-6 text-center text-sm text-muted-foreground">
              This season has no published episodes yet.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
