import { Tv } from "lucide-react";

import { EmptyState, ErrorState } from "@shared/ui/states";
import { Skeleton } from "@shared/ui/primitives";

import { Hero } from "../components/Hero";
import { Row } from "../components/Row";
import { useCatalog } from "../lib/queries";

function HomeSkeleton() {
  return (
    <div className="animate-pulse">
      <Skeleton className="h-[52vw] max-h-[560px] min-h-[320px] w-full rounded-none" />
      {[0, 1].map((row) => (
        <div key={row} className="px-4 py-4 sm:px-8">
          <Skeleton className="mb-3 h-5 w-32" />
          <div className="flex gap-3">
            {Array.from({ length: 7 }).map((_, index) => (
              <Skeleton
                key={index}
                className="aspect-2/3 w-[136px] shrink-0 sm:w-[160px] md:w-[184px]"
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function HomePage() {
  const { data, isPending, error, refetch } = useCatalog();

  if (isPending) return <HomeSkeleton />;
  if (error)
    return (
      <div className="p-8">
        <ErrorState error={error} onRetry={() => refetch()} />
      </div>
    );

  const sections = data.sections.filter((section) => section.shows.length > 0);
  if (sections.length === 0) {
    return (
      <div className="p-8">
        <EmptyState
          icon={Tv}
          title="Nothing has been published yet"
          hint="Once the content team publishes a catalogue, it appears here."
        />
      </div>
    );
  }

  // The hero is the first show of the first section — `featured` leads in reference.json
  // and the catalogue preserves that order, so the content team decides what is featured
  // rather than the UI guessing. It is then dropped from its own row: showing the same
  // title twice, once enormous and once as a lone card beneath it, reads as a bug.
  const featured = sections[0]?.shows[0];
  const rows = sections
    .map((section) => ({
      ...section,
      shows: section.shows.filter((show) => show.slug !== featured?.slug),
    }))
    .filter((section) => section.shows.length > 0);

  return (
    <div className="pb-10">
      {featured ? <Hero show={featured} /> : null}
      <div className="relative z-10 -mt-4 sm:-mt-8">
        {rows.map((section) => (
          <Row key={section.key} title={section.key} shows={section.shows} />
        ))}
      </div>
    </div>
  );
}
