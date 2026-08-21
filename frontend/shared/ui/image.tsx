/** An image that stays pleasant while it loads, and says so when it never does.
 *
 * Browse surfaces are mostly artwork, so a slow bucket should look like a considered
 * placeholder rather than a broken page: the tile holds its exact aspect ratio from the
 * first paint (nothing reflows), shows a shimmer while the bytes arrive, and fades in
 * rather than snapping. A failed load keeps the frame and shows the title, so the row
 * stays navigable instead of collapsing.
 */

import { ImageOff } from "lucide-react";
import { useState } from "react";

import { cn } from "./utils";

export function Poster({
  src,
  alt,
  ratio = "2/3",
  className,
  sizes,
}: {
  src?: string;
  alt: string;
  ratio?: "2/3" | "16/9";
  className?: string;
  sizes?: string;
}) {
  const [state, setState] = useState<"loading" | "ready" | "failed">(src ? "loading" : "failed");

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md bg-muted",
        ratio === "2/3" ? "aspect-2/3" : "aspect-video",
        className,
      )}
      style={{ aspectRatio: ratio === "2/3" ? "2 / 3" : "16 / 9" }}
    >
      {state === "loading" ? (
        <div className="absolute inset-0 animate-pulse bg-accent" aria-hidden />
      ) : null}

      {state === "failed" ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 p-2 text-center">
          <ImageOff className="size-4 text-muted-foreground" aria-hidden />
          <span className="line-clamp-2 text-[11px] leading-tight text-muted-foreground">
            {alt}
          </span>
        </div>
      ) : null}

      {src ? (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          sizes={sizes}
          onLoad={() => setState("ready")}
          onError={() => setState("failed")}
          className={cn(
            "absolute inset-0 size-full object-cover transition-opacity duration-300 motion-safe-only",
            state === "ready" ? "opacity-100" : "opacity-0",
          )}
        />
      ) : null}
    </div>
  );
}
