/** The boot loader: concentric arcs in the brand red over the near-black ground.
 *
 * It earns its place against one real wait rather than decorating a fast one. The
 * deployment's API sleeps on the free tier, so the first `/catalog` of a visit can take
 * seconds while every request after it is instant. A skeleton promises "almost there",
 * and a skeleton that sits for four seconds reads as a broken page; a deliberate brand
 * moment reads as a product starting up.
 *
 * `delayMs` is why it never flashes. A warm load resolves inside the delay and this
 * component never mounts anything at all — an elaborate loader on a 200ms wait feels
 * worse than no loader.
 *
 * Motion is transform and opacity only, so the whole thing composites on the GPU, and
 * the loop is 1.4s: long enough to read as considered, short enough that a slow wait
 * never looks like the page froze on one beat. `theme.css` already freezes it into a
 * static ring under `prefers-reduced-motion`, which is why the label carries the meaning.
 */

import { useEffect, useState } from "react";

import { cn } from "./utils";

/** Ring geometry, in the 120×120 viewBox. Dash patterns are computed against each
 *  radius' circumference so an "arc" stays the same visual fraction at any size. */
const RINGS = [
  { r: 52, width: 2.5, dash: "82 245", duration: "1.4s", reverse: false, opacity: 1 },
  { r: 40, width: 1.5, dash: "6 12", duration: "2.6s", reverse: true, opacity: 0.55 },
  { r: 28, width: 2, dash: "70 106", duration: "1.9s", reverse: false, opacity: 0.8 },
] as const;

export function BrandLoader({ className, size = 120 }: { className?: string; size?: number }) {
  return (
    <div
      className={cn("relative", className)}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {/* The glow is a blurred disc rather than a box-shadow: shadows on a spinning
          element repaint every frame, a sibling disc does not. */}
      <div className="absolute inset-[22%] animate-breathe rounded-full bg-primary/25 blur-2xl" />

      {RINGS.map((ring) => (
        <svg
          key={ring.r}
          viewBox="0 0 120 120"
          className="absolute inset-0 size-full animate-spin"
          style={{
            animationDuration: ring.duration,
            animationDirection: ring.reverse ? "reverse" : "normal",
            animationTimingFunction: "linear",
            opacity: ring.opacity,
          }}
        >
          {/* The track keeps the circle legible while the lit arc is elsewhere. */}
          <circle
            cx="60"
            cy="60"
            r={ring.r}
            fill="none"
            stroke="currentColor"
            strokeWidth={ring.width}
            className="text-border/50"
          />
          <circle
            cx="60"
            cy="60"
            r={ring.r}
            fill="none"
            stroke="currentColor"
            strokeWidth={ring.width}
            strokeLinecap="round"
            strokeDasharray={ring.dash}
            className="text-primary"
          />
          {/* One lit dot riding the outer ring — the detail that reads as "working"
              rather than "spinning". */}
          {ring.r === 52 ? <circle cx="60" cy="8" r="3.5" className="fill-primary" /> : null}
        </svg>
      ))}

      <div className="absolute inset-0 flex items-center justify-center">
        <span className="size-2.5 animate-breathe rounded-full bg-primary" />
      </div>
    </div>
  );
}

/** Full-screen boot state. Renders nothing until `delayMs` has passed. */
export function BootScreen({
  label = "Loading Peblo TV…",
  delayMs = 250,
}: {
  label?: string;
  delayMs?: number;
}) {
  const [visible, setVisible] = useState(delayMs === 0);

  useEffect(() => {
    if (delayMs === 0) return;
    const timer = setTimeout(() => setVisible(true), delayMs);
    return () => clearTimeout(timer);
  }, [delayMs]);

  if (!visible) return null;

  return (
    <div
      className="animate-fade-in flex min-h-[70dvh] flex-col items-center justify-center gap-8 px-6"
      role="status"
      aria-live="polite"
    >
      <BrandLoader />

      <div className="flex flex-col items-center gap-2 text-center">
        <div className="flex items-center gap-2">
          <span className="text-xl font-black tracking-tight text-primary">PEBLO</span>
          <span className="text-xl font-light tracking-[0.3em] text-foreground">TV</span>
        </div>
        <p className="text-sm text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}
