import { ChevronLeft, ChevronRight } from "lucide-react";

import type { Page } from "@shared/types";
import { Button } from "@shared/ui/button";

export function Pagination({ page, onChange }: { page: Page; onChange: (offset: number) => void }) {
  const from = page.total === 0 ? 0 : page.offset + 1;
  const to = Math.min(page.offset + page.limit, page.total);
  const canBack = page.offset > 0;
  const canForward = to < page.total;

  return (
    <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm">
      <p className="text-muted-foreground">
        {from}–{to} of {page.total}
      </p>
      <div className="flex gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={!canBack}
          onClick={() => onChange(Math.max(0, page.offset - page.limit))}
        >
          <ChevronLeft aria-hidden />
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!canForward}
          onClick={() => onChange(page.offset + page.limit)}
        >
          Next
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </div>
  );
}
