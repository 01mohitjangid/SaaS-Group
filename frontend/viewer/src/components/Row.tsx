import { ChevronLeft, ChevronRight } from "lucide-react";
import { useRef } from "react";
import { Link } from "react-router-dom";

import { sectionName } from "@shared/format";
import { Poster } from "@shared/ui/image";
import type { CatalogShow } from "@shared/types";

/** A horizontal browse row.
 *
 * Rows use the **poster** (2:3) — that is the artwork cut for this surface, and mixing a
 * 16:9 banner in would break the rhythm of the row as much as the aspect ratio.
 * Scrolling is native so touch and trackpads behave; the arrows are an addition for
 * mouse users, not the mechanism.
 */
export function Row({ title, shows }: { title: string; shows: CatalogShow[] }) {
  const track = useRef<HTMLDivElement>(null);

  const nudge = (direction: 1 | -1) => {
    const node = track.current;
    if (node) node.scrollBy({ left: direction * node.clientWidth * 0.8, behavior: "smooth" });
  };

  if (shows.length === 0) return null;

  return (
    <section className="group/row relative py-4" aria-labelledby={`row-${title}`}>
      <h2
        id={`row-${title}`}
        className="mb-2 px-4 text-base font-semibold tracking-tight sm:px-8 md:text-lg"
      >
        {sectionName(title)}
      </h2>

      <div className="relative">
        <div
          ref={track}
          className="no-scrollbar flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-smooth px-4 pb-2 sm:px-8"
        >
          {shows.map((show) => (
            <Link
              key={show.slug}
              to={`/shows/${show.slug}`}
              className="group/card w-[136px] shrink-0 snap-start sm:w-[160px] md:w-[184px]"
            >
              <Poster
                src={show.artwork.poster}
                alt={show.title}
                ratio="2/3"
                sizes="184px"
                className="transition-transform duration-200 group-hover/card:scale-[1.04] motion-safe-only"
              />
              <p className="mt-2 line-clamp-2 text-xs text-muted-foreground group-hover/card:text-foreground">
                {show.title}
              </p>
            </Link>
          ))}
        </div>

        {[-1, 1].map((direction) => (
          <button
            key={direction}
            type="button"
            aria-label={
              direction === -1
                ? `Scroll ${sectionName(title)} left`
                : `Scroll ${sectionName(title)} right`
            }
            onClick={() => nudge(direction as 1 | -1)}
            className={`absolute top-0 hidden h-full w-10 items-center justify-center bg-background/70 text-foreground opacity-0 transition-opacity group-hover/row:opacity-100 focus-visible:opacity-100 md:flex ${
              direction === -1 ? "left-0" : "right-0"
            }`}
          >
            {direction === -1 ? (
              <ChevronLeft className="size-6" aria-hidden />
            ) : (
              <ChevronRight className="size-6" aria-hidden />
            )}
          </button>
        ))}
      </div>
    </section>
  );
}
