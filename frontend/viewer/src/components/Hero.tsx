import { Info, Play } from "lucide-react";
import { Link } from "react-router-dom";

import { languageName, sectionName } from "@shared/format";
import type { CatalogShow } from "@shared/types";
import { Badge } from "@shared/ui/primitives";
import { Button } from "@shared/ui/button";

/** The featured hero.
 *
 * Uses the **banner** (16:9) — the only surface that artwork was cut for. The image sits
 * behind two gradients rather than one: a vertical fade into the first row so the page
 * reads as continuous, and a horizontal fade so white text stays legible over whatever
 * the artwork happens to be doing on the left.
 */
export function Hero({ show }: { show: CatalogShow }) {
  const episodes = show.seasons.reduce((total, season) => total + season.episodes.length, 0);

  return (
    <section className="relative">
      <div className="relative h-[52vw] max-h-[560px] min-h-[320px] w-full overflow-hidden">
        {show.artwork.banner ? (
          <img
            src={show.artwork.banner}
            alt=""
            // The hero is the largest paint on the page and above the fold: it is the one
            // image worth fetching eagerly.
            fetchPriority="high"
            decoding="async"
            className="size-full object-cover"
          />
        ) : (
          <div className="size-full bg-accent" />
        )}
        <div className="absolute inset-0 bg-linear-to-t from-background via-background/40 to-transparent" />
        <div className="absolute inset-0 bg-linear-to-r from-background via-background/60 to-transparent" />
      </div>

      <div className="absolute inset-x-0 bottom-0 mx-auto max-w-[1600px] px-4 pb-6 sm:px-8 sm:pb-10">
        <div className="max-w-xl">
          <h1 className="text-3xl font-black tracking-tight drop-shadow-lg sm:text-5xl">
            {show.title}
          </h1>
          <p className="mt-3 line-clamp-3 text-sm text-foreground/85 sm:text-base">
            {show.synopsis}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Badge variant="outline">
              {episodes} episode{episodes === 1 ? "" : "s"}
            </Badge>
            {show.languages.map((code) => (
              <Badge key={code} variant="outline">
                {languageName(code)}
              </Badge>
            ))}
            {show.categories.slice(0, 3).map((category) => (
              <Badge key={category}>{sectionName(category)}</Badge>
            ))}
          </div>

          <div className="mt-5 flex gap-3">
            <Button asChild size="lg" variant="light">
              <Link to={`/shows/${show.slug}`}>
                <Play className="fill-current" aria-hidden />
                Play
              </Link>
            </Button>
            <Button asChild size="lg" variant="secondary">
              <Link to={`/shows/${show.slug}`}>
                <Info aria-hidden />
                More info
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
