import { Tv } from "lucide-react";

import { BootScreen } from "@shared/ui/loader";
import { EmptyState, ErrorState } from "@shared/ui/states";

import { Hero } from "../components/Hero";
import { Row } from "../components/Row";
import { useCatalog } from "../lib/queries";

export function HomePage() {
  const { data, isPending, error, refetch } = useCatalog();

  // `isPending` is true only when nothing is cached, so this is the arrival on the site
  // and nothing else — a return visit to the home route reads from cache and never shows
  // it. A content-shaped skeleton was here before; it promised "almost there", which is
  // the wrong promise when the free-tier API is cold and the wait is measured in seconds.
  if (isPending) return <BootScreen />;
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
