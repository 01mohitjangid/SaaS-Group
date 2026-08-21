import { CheckCircle2, ImagePlus, Trash2, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";

import { ApiError } from "@shared/api";
import type { Artwork, ArtworkKind, ArtworkSpec } from "@shared/types";
import { Badge } from "@shared/ui/primitives";
import { Button } from "@shared/ui/button";
import { cn } from "@shared/ui/utils";

import { useDeleteArtwork, useUploadArtwork } from "../lib/queries";

/** One labelled artwork slot.
 *
 * Everything an editor needs to succeed is on the slot *before* they pick a file: what
 * this image is for, the exact size, and the weight limit. The preview is the local file
 * shown immediately — waiting for a round trip to find out you cropped it wrong is the
 * thing that makes this job miserable fifty times a week.
 *
 * The browser never decides whether a file is acceptable. It shows the rules; the API
 * enforces them on real decoded pixels and sends back a sentence, which is what appears
 * under the slot.
 */
export function ArtworkSlot({
  kind,
  spec,
  existing,
  showId,
  episodeId,
  disabled,
}: {
  kind: ArtworkKind;
  spec: ArtworkSpec;
  existing?: Artwork;
  showId?: string;
  episodeId?: string;
  disabled?: boolean;
}) {
  const upload = useUploadArtwork();
  const remove = useDeleteArtwork();
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);

  const error = upload.error instanceof ApiError ? upload.error : null;
  const problems = error?.problems.length
    ? error.problems
    : error
      ? [{ message: error.message, field: null }]
      : [];
  const shown = preview ?? existing?.url;

  const pick = (file: File | undefined) => {
    if (!file) return;
    upload.reset();
    // Show it straight away, so a wrong crop is obvious before the upload finishes.
    setPreview((previous) => {
      if (previous) URL.revokeObjectURL(previous);
      return URL.createObjectURL(file);
    });
    upload.mutate(
      { kind, file, showId, episodeId },
      {
        // A rejected file must not stay on the slot pretending to be the artwork.
        onError: () =>
          setPreview((previous) => {
            if (previous) URL.revokeObjectURL(previous);
            return null;
          }),
      },
    );
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium capitalize">{kind}</span>
        {existing ? (
          <Badge variant="published" className="gap-1">
            <CheckCircle2 className="size-3" aria-hidden />
            Uploaded
          </Badge>
        ) : (
          <Badge variant="draft">Missing</Badge>
        )}
      </div>

      <button
        type="button"
        disabled={disabled || upload.isPending}
        onClick={() => input.current?.click()}
        aria-label={`Upload ${kind}: ${spec.aspect}, at least ${spec.target}, up to ${spec.max_kb} KB`}
        className={cn(
          "relative w-full overflow-hidden rounded-md border border-dashed border-border bg-muted transition-colors",
          "hover:border-ring disabled:cursor-not-allowed disabled:opacity-60",
          error && "border-destructive",
        )}
        style={{ aspectRatio: kind === "poster" ? "2 / 3" : "16 / 9" }}
      >
        {shown ? (
          <img
            src={shown}
            alt={`${kind} preview`}
            className="absolute inset-0 size-full object-cover"
          />
        ) : (
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-muted-foreground">
            <ImagePlus className="size-5" aria-hidden />
            <span className="text-xs">Choose a file</span>
          </span>
        )}
        {upload.isPending ? (
          <span className="absolute inset-0 grid place-items-center bg-background/70 text-xs">
            Uploading…
          </span>
        ) : null}
      </button>

      <input
        ref={input}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="sr-only"
        onChange={(event) => {
          pick(event.target.files?.[0]);
          // Clear it, or choosing the *same* corrected file again fires no change event
          // and the slot looks dead — exactly the loop a rejected upload creates.
          event.target.value = "";
        }}
      />

      {/* The rules, stated before the mistake rather than after it. */}
      <p className="text-xs text-muted-foreground">
        {spec.aspect} · at least {spec.target} · up to {spec.max_kb} KB
        {existing ? (
          <>
            {" · "}
            <span className="text-foreground">
              now {existing.width}×{existing.height}, {Math.round(existing.byte_size / 1024)} KB
            </span>
          </>
        ) : null}
      </p>

      {problems.length > 0 ? (
        <ul className="space-y-1 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
          {problems.map((problem, index) => (
            <li key={index} className="flex gap-1.5">
              <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              <span>
                {problem.message}
                {"hint" in problem && problem.hint ? (
                  <span className="block opacity-80">{problem.hint}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {existing && !disabled ? (
        <Button
          variant="ghost"
          size="sm"
          className="self-start text-muted-foreground"
          disabled={remove.isPending}
          onClick={() => {
            setPreview(null);
            upload.reset();
            remove.mutate(existing.id);
          }}
        >
          <Trash2 aria-hidden />
          Remove
        </Button>
      ) : null}
    </div>
  );
}
