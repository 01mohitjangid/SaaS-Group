import { ArrowLeft, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "@shared/api";
import { duration, sectionName } from "@shared/format";
import type { ArtworkKind, Episode } from "@shared/types";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  Table,
  Td,
  Textarea,
  Th,
} from "@shared/ui/primitives";
import { Button } from "@shared/ui/button";
import { Alert, ErrorState, LoadingState } from "@shared/ui/states";

import { ArtworkSlot } from "../components/ArtworkSlot";
import {
  useDeleteEpisode,
  useReference,
  useSaveEpisode,
  useSaveShow,
  useShow,
} from "../lib/queries";

const SHOW_SLOTS: ArtworkKind[] = ["poster", "banner"];

function FieldError({ error, field }: { error: unknown; field: string }) {
  const problem = error instanceof ApiError ? error.problemFor(field) : undefined;
  if (!problem) return null;
  return (
    <p className="text-xs text-destructive">
      {problem.message}
      {problem.hint ? <span className="block opacity-80">{problem.hint}</span> : null}
    </p>
  );
}

function EpisodeForm({ showId, onDone }: { showId: string; onDone: () => void }) {
  const reference = useReference();
  const save = useSaveEpisode(undefined, showId);
  const [form, setForm] = useState({
    season_number: 1,
    episode_number: 1,
    title: "",
    duration_seconds: 600,
    language: "en",
    content_group: "",
  });

  return (
    <form
      className="grid gap-3 sm:grid-cols-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(form, { onSuccess: onDone });
      }}
    >
      <div className="flex flex-col gap-1.5 sm:col-span-3">
        <Label htmlFor="ep-title">Episode title</Label>
        <Input
          id="ep-title"
          required
          value={form.title}
          onChange={(event) => setForm({ ...form, title: event.target.value })}
        />
        <FieldError error={save.error} field="title" />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="ep-season">Season (0 = trailer)</Label>
        <Input
          id="ep-season"
          type="number"
          min={0}
          value={form.season_number}
          onChange={(event) => setForm({ ...form, season_number: Number(event.target.value) })}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="ep-number">Episode number</Label>
        <Input
          id="ep-number"
          type="number"
          min={0}
          value={form.episode_number}
          onChange={(event) => setForm({ ...form, episode_number: Number(event.target.value) })}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="ep-duration">Run time (seconds)</Label>
        <Input
          id="ep-duration"
          type="number"
          min={1}
          value={form.duration_seconds}
          onChange={(event) => setForm({ ...form, duration_seconds: Number(event.target.value) })}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="ep-language">Language</Label>
        <Select
          id="ep-language"
          value={form.language}
          onChange={(event) => setForm({ ...form, language: event.target.value })}
        >
          {reference.data?.languages.map((code) => (
            <option key={code} value={code}>
              {code.toUpperCase()}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-col gap-1.5 sm:col-span-2">
        <Label htmlFor="ep-group">Content group</Label>
        <Input
          id="ep-group"
          required
          value={form.content_group}
          onChange={(event) => setForm({ ...form, content_group: event.target.value })}
          placeholder="motis-many-lives-s01e01"
        />
        <p className="text-xs text-muted-foreground">
          Give every language version of the same episode the same group — that is what makes them
          one entry with a language choice instead of two episodes.
        </p>
      </div>

      {save.error ? (
        <div className="sm:col-span-3">
          <Alert tone="danger" title="Could not add the episode">
            {(save.error as ApiError).message}
          </Alert>
        </div>
      ) : null}

      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" size="sm" disabled={save.isPending}>
          {save.isPending ? "Adding…" : "Add episode"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** One episode row.
 *
 * Each row owns its own mutation. A single shared one meant the status select PATCHed
 * nothing (it had no episode id) and any error appeared under every row at once.
 */
function EpisodeRow({ episode }: { episode: Episode }) {
  const save = useSaveEpisode(episode.id);
  const remove = useDeleteEpisode();
  const spec = {
    aspect: "16:9",
    target: "640×360",
    min_width: 640,
    min_height: 360,
    max_kb: 200,
    used_for: "episodes" as const,
  };
  const error = (save.error ?? remove.error) as ApiError | null;

  return (
    <tr className="align-top">
      <Td>
        <span className="font-medium">{episode.title}</span>
        <p className="text-xs text-muted-foreground">{episode.content_group}</p>
      </Td>
      <Td className="text-muted-foreground">
        {episode.season_number === 0 ? (
          <Badge variant="outline">Trailer</Badge>
        ) : (
          `S${episode.season_number}E${episode.episode_number}`
        )}
      </Td>
      <Td className="text-muted-foreground">{episode.language.toUpperCase()}</Td>
      <Td className="text-muted-foreground">{duration(episode.duration_seconds)}</Td>
      <Td className="w-44">
        <ArtworkSlot
          kind="thumbnail"
          spec={spec}
          existing={episode.artwork.find((a) => a.kind === "thumbnail")}
          episodeId={episode.id}
        />
      </Td>
      <Td>
        <Select
          className="h-8 w-28 text-xs"
          value={episode.status}
          disabled={save.isPending}
          onChange={(event) => save.mutate({ status: event.target.value })}
          aria-label={`Status for ${episode.title}`}
        >
          <option value="draft">draft</option>
          <option value="published">published</option>
        </Select>
        {error ? (
          <p className="mt-1 max-w-56 text-xs text-destructive">
            {error.message}
            {error.problems[0]?.hint ? (
              <span className="block opacity-80">{error.problems[0].hint}</span>
            ) : null}
          </p>
        ) : null}
      </Td>
      <Td>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Delete ${episode.title}`}
          disabled={remove.isPending}
          onClick={() => {
            // Deleting an episode also deletes its artwork; nothing here is undoable.
            if (confirm(`Delete “${episode.title}”? This cannot be undone.`))
              remove.mutate(episode.id);
          }}
        >
          <Trash2 className="text-muted-foreground" aria-hidden />
        </Button>
      </Td>
    </tr>
  );
}

function EpisodeTable({ episodes }: { episodes: Episode[] }) {
  return (
    <Table>
      <thead className="border-b border-border">
        <tr>
          <Th>Episode</Th>
          <Th>Season</Th>
          <Th>Lang</Th>
          <Th>Run time</Th>
          <Th>Thumbnail</Th>
          <Th>Status</Th>
          <Th />
        </tr>
      </thead>
      <tbody className="divide-y divide-border/60">
        {episodes.map((episode) => (
          <EpisodeRow key={episode.id} episode={episode} />
        ))}
        {episodes.length === 0 ? (
          <tr>
            <Td colSpan={7} className="py-8 text-center text-sm text-muted-foreground">
              No episodes yet. Add the first one below.
            </Td>
          </tr>
        ) : null}
      </tbody>
    </Table>
  );
}

export function ShowEditPage() {
  const { showId } = useParams();
  const navigate = useNavigate();
  const reference = useReference();
  const show = useShow(showId);
  const save = useSaveShow(showId);
  const [adding, setAdding] = useState(false);

  const [form, setForm] = useState({
    slug: "",
    title: "",
    synopsis: "",
    section: "",
    categories: [] as string[],
    status: "draft",
  });

  // Seed the form from the server **once**. Re-seeding on every refetch meant an
  // artwork upload (which invalidates the show) silently reverted unsaved text edits.
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    if (show.data && !seeded) {
      setSeeded(true);
      setForm({
        slug: show.data.slug,
        title: show.data.title,
        synopsis: show.data.synopsis,
        section: show.data.section ?? "",
        categories: show.data.categories,
        status: show.data.status,
      });
    }
  }, [show.data, seeded]);

  if (showId && show.isPending) return <LoadingState />;
  if (showId && show.error) return <ErrorState error={show.error} onRetry={() => show.refetch()} />;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const body: Record<string, unknown> = {
      title: form.title,
      synopsis: form.synopsis,
      section: form.section || null,
      categories: form.categories,
      status: form.status,
    };
    if (!showId) body.slug = form.slug;
    save.mutate(body, {
      onSuccess: (created) => {
        if (!showId) navigate(`/shows/${created.id}`, { replace: true });
      },
    });
  };

  const error = save.error instanceof ApiError ? save.error : null;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3">
        <Button asChild variant="ghost" size="sm">
          <Link to="/shows">
            <ArrowLeft aria-hidden />
            Shows
          </Link>
        </Button>
        <h1 className="text-xl font-semibold tracking-tight">
          {showId ? show.data?.title : "New show"}
        </h1>
        {show.data ? (
          <Badge variant={show.data.status === "published" ? "published" : "draft"}>
            {show.data.status}
          </Badge>
        ) : null}
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="title">Title</Label>
                <Input
                  id="title"
                  required
                  value={form.title}
                  onChange={(event) => setForm({ ...form, title: event.target.value })}
                  aria-invalid={Boolean(error?.problemFor("title"))}
                />
                <FieldError error={save.error} field="title" />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="slug">Web address (slug)</Label>
                <Input
                  id="slug"
                  required
                  disabled={Boolean(showId)}
                  value={form.slug}
                  onChange={(event) => setForm({ ...form, slug: event.target.value })}
                  placeholder="motis-many-lives"
                  aria-invalid={Boolean(error?.problemFor("slug"))}
                />
                <FieldError error={save.error} field="slug" />
                {showId ? (
                  <p className="text-xs text-muted-foreground">
                    The address cannot change once viewers have it.
                  </p>
                ) : null}
              </div>

              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <Label htmlFor="synopsis">Synopsis</Label>
                <Textarea
                  id="synopsis"
                  value={form.synopsis}
                  onChange={(event) => setForm({ ...form, synopsis: event.target.value })}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="section">Section</Label>
                <Select
                  id="section"
                  value={form.section}
                  onChange={(event) => setForm({ ...form, section: event.target.value })}
                >
                  <option value="">No section yet</option>
                  {reference.data?.sections.map((key) => (
                    <option key={key} value={key}>
                      {sectionName(key)}
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">
                  A show cannot be published without one — it is the row it appears in.
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="status">Status</Label>
                <Select
                  id="status"
                  value={form.status}
                  onChange={(event) => setForm({ ...form, status: event.target.value })}
                >
                  <option value="draft">Draft</option>
                  <option value="published">Published</option>
                </Select>
              </div>

              <fieldset className="flex flex-col gap-1.5 sm:col-span-2">
                <legend className="mb-1.5 text-sm font-medium">Categories</legend>
                {reference.error ? (
                  <p className="text-xs text-destructive">
                    Could not load the category list. Reload the page to try again.
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-1.5">
                  {reference.data?.categories.map((category) => {
                    const on = form.categories.includes(category);
                    return (
                      <button
                        key={category}
                        type="button"
                        aria-pressed={on}
                        onClick={() =>
                          setForm({
                            ...form,
                            categories: on
                              ? form.categories.filter((c) => c !== category)
                              : [...form.categories, category],
                          })
                        }
                        className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                          on
                            ? "border-primary bg-primary/15 text-foreground"
                            : "border-border text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {category}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              {error ? (
                <div className="sm:col-span-2">
                  <Alert tone="danger" title="Could not save">
                    <p>{error.message}</p>
                    {error.problems.length > 1 ? (
                      <ul className="mt-1 space-y-0.5">
                        {error.problems.map((problem, index) => (
                          <li key={index}>• {problem.message}</li>
                        ))}
                      </ul>
                    ) : null}
                  </Alert>
                </div>
              ) : null}

              {save.isSuccess && !save.isPending ? (
                <div className="sm:col-span-2">
                  <Alert tone="success">Saved.</Alert>
                </div>
              ) : null}

              <div className="sm:col-span-2">
                <Button type="submit" disabled={save.isPending}>
                  <Save aria-hidden />
                  {save.isPending ? "Saving…" : "Save show"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Artwork</CardTitle>
            <p className="text-xs text-muted-foreground">
              The poster fills browse rows; the banner fills the featured hero.
            </p>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {!showId ? (
              <p className="text-sm text-muted-foreground">
                Save the show first, then upload its artwork here.
              </p>
            ) : reference.isPending ? (
              <LoadingState label="Loading the artwork rules…" />
            ) : reference.error ? (
              <ErrorState error={reference.error} onRetry={() => reference.refetch()} />
            ) : (
              SHOW_SLOTS.map((kind) => {
                const spec = reference.data?.artwork[kind];
                return spec ? (
                  <ArtworkSlot
                    key={kind}
                    kind={kind}
                    spec={spec}
                    existing={show.data?.artwork.find((a) => a.kind === kind)}
                    showId={showId}
                  />
                ) : null;
              })
            )}
          </CardContent>
        </Card>
      </div>

      {showId ? (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Episodes</CardTitle>
            <Button size="sm" variant="secondary" onClick={() => setAdding((value) => !value)}>
              <Plus aria-hidden />
              Add episode
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            <EpisodeTable episodes={show.data?.episodes ?? []} />
            {adding ? (
              <div className="border-t border-border p-4">
                <EpisodeForm showId={showId} onDone={() => setAdding(false)} />
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
