import {
  CheckCircle2,
  CircleAlert,
  History,
  RotateCcw,
  Rocket,
  ShieldAlert,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";

import { ApiError } from "@shared/api";
import { relativeTime } from "@shared/format";
import type { PublishRun } from "@shared/types";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Skeleton,
  Table,
  Td,
  Th,
} from "@shared/ui/primitives";
import { Button } from "@shared/ui/button";
import { Alert, EmptyState, ErrorState } from "@shared/ui/states";

import { useAuth } from "../lib/auth";
import {
  useCancelRun,
  usePublish,
  usePublishRuns,
  useRollback,
  useValidationReport,
} from "../lib/queries";

function RunStatus({ run }: { run: PublishRun }) {
  if (run.status === "succeeded") {
    return (
      <Badge variant="published" className="gap-1">
        <CheckCircle2 className="size-3" aria-hidden />
        {run.rolled_back_to ? "rolled back" : run.reused ? "no changes" : "published"}
      </Badge>
    );
  }
  if (run.status === "failed") {
    return (
      <Badge variant="blocker" className="gap-1">
        <XCircle className="size-3" aria-hidden />
        failed
      </Badge>
    );
  }
  return <Badge variant="warning">running</Badge>;
}

export function PublishPage() {
  const { me } = useAuth();
  const report = useValidationReport();
  const runs = usePublishRuns();
  const publish = usePublish();
  const cancel = useCancelRun();

  const canPublish = me?.can_publish ?? false;
  const blockers = report.data?.blocker_count ?? 0;

  // Every reason the button is off, in the order they matter. Showing them all at once
  // beats a disabled button that makes you guess which rule you tripped.
  const reasons: string[] = [];
  if (!canPublish) reasons.push("Only an admin can publish. Ask an admin to run it.");
  if (report.isPending) reasons.push("Checking the catalogue…");
  if (report.error) reasons.push("The validation report could not be loaded.");
  if (blockers > 0)
    reasons.push(`${blockers} problem${blockers === 1 ? "" : "s"} must be fixed first.`);

  const blocked = reasons.length > 0;
  const stuck = runs.data?.find((run) => run.status === "running");
  const publishError = publish.error instanceof ApiError ? publish.error : null;

  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-xl font-semibold tracking-tight">Publish</h1>

      {!canPublish ? (
        <Alert tone="warning" title="You are signed in as an editor">
          You can fix everything on this page. Publishing itself is an admin action.
        </Alert>
      ) : null}

      <Card>
        <CardContent className="flex flex-wrap items-center gap-4 p-4">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              {report.isPending
                ? "Checking…"
                : report.data?.can_publish
                  ? "Everything is ready to publish"
                  : `${blockers} problem${blockers === 1 ? "" : "s"} blocking publish`}
            </p>
            <p className="text-xs text-muted-foreground">
              {report.data ? `${report.data.warning_count} warning(s) — these do not block.` : ""}
            </p>
          </div>

          <div className="flex flex-col items-end gap-1">
            <Button
              size="lg"
              disabled={blocked || publish.isPending}
              onClick={() => publish.mutate()}
              title={blocked ? reasons.join(" ") : "Build the catalogue and make it live"}
            >
              <Rocket aria-hidden />
              {publish.isPending ? "Publishing…" : "Publish catalogue"}
            </Button>
            {blocked ? (
              <ul className="text-right text-xs text-muted-foreground">
                {reasons.map((reason) => (
                  <li key={reason} className="flex items-center justify-end gap-1">
                    {reason.startsWith("Only an admin") ? (
                      <ShieldAlert className="size-3" aria-hidden />
                    ) : null}
                    {reason}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {publish.isSuccess ? (
        <Alert tone="success" title={publish.data.reused ? "Nothing had changed" : "Published"}>
          {publish.data.reused
            ? "The catalogue already matched, so the live file was left alone."
            : `Live now: ${Object.entries(publish.data.run.counts)
                .map(([key, value]) => `${value} ${key}`)
                .join(", ")}.`}
        </Alert>
      ) : null}

      {publishError ? (
        <Alert tone="danger" title={publishError.message}>
          <ul className="mt-1 space-y-1">
            {publishError.problems.map((problem, index) => (
              <li key={index}>
                • {problem.message}
                {problem.hint ? (
                  <span className="block opacity-80 pl-3">{problem.hint}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </Alert>
      ) : null}

      {stuck && canPublish ? (
        <Alert tone="warning" title="A publish is still marked as running">
          <p>
            {stuck.created_by_email} started it {relativeTime(stuck.started_at)}. If that process
            stopped, release the slot so publishing can continue.
          </p>
          <Button
            size="sm"
            variant="secondary"
            className="mt-2"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate(stuck.id)}
          >
            Cancel that run
          </Button>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CircleAlert className="size-4" aria-hidden />
            What needs fixing
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {report.isPending ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : report.error ? (
            <div className="p-4">
              <ErrorState error={report.error} onRetry={() => report.refetch()} />
            </div>
          ) : report.data.groups.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={CheckCircle2}
                title="Nothing to fix"
                hint="Every published show and episode passes its checks."
              />
            </div>
          ) : (
            <ul className="divide-y divide-border/60">
              {report.data.groups.map((group) => (
                <li key={group.show_slug ?? "catalogue"} className="p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <p className="text-sm font-medium">
                      {group.show_title ?? group.show_slug ?? "Across the catalogue"}
                    </p>
                    {group.blockers.length > 0 ? (
                      <Badge variant="blocker">{group.blockers.length} blocking</Badge>
                    ) : null}
                    {group.warnings.length > 0 ? (
                      <Badge variant="warning">{group.warnings.length} warning</Badge>
                    ) : null}
                    {group.show_slug ? (
                      <Link
                        to={`/shows?q=${encodeURIComponent(group.show_slug)}`}
                        className="ml-auto text-xs text-muted-foreground hover:text-foreground hover:underline"
                      >
                        Open show
                      </Link>
                    ) : null}
                  </div>

                  <ul className="space-y-1.5">
                    {[...group.blockers, ...group.warnings].map((issue) => (
                      <li key={`${issue.code}-${issue.entity}`} className="flex gap-2 text-sm">
                        {issue.severity === "blocker" ? (
                          <XCircle
                            className="mt-0.5 size-4 shrink-0 text-destructive"
                            aria-hidden
                          />
                        ) : (
                          <TriangleAlert
                            className="mt-0.5 size-4 shrink-0 text-warning"
                            aria-hidden
                          />
                        )}
                        <span>
                          {issue.message}
                          <span className="block text-xs text-muted-foreground">
                            {issue.fix_hint}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="size-4" aria-hidden />
            Run history
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {runs.isPending ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-9 w-full" />
              ))}
            </div>
          ) : runs.error ? (
            <div className="p-4">
              <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
            </div>
          ) : runs.data.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={Rocket}
                title="Nothing published yet"
                hint="The first publish will appear here with its counts and who ran it."
              />
            </div>
          ) : (
            <Table>
              <thead className="border-b border-border">
                <tr>
                  <Th>When</Th>
                  <Th>Who</Th>
                  <Th>Result</Th>
                  <Th>Contents</Th>
                  <Th />
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {runs.data.map((run) => (
                  <tr key={run.id}>
                    <Td className="whitespace-nowrap text-muted-foreground">
                      {relativeTime(run.started_at)}
                    </Td>
                    <Td className="text-muted-foreground">{run.created_by_email}</Td>
                    <Td>
                      <RunStatus run={run} />
                      {run.error ? (
                        <p className="mt-1 max-w-72 text-xs text-muted-foreground">{run.error}</p>
                      ) : null}
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {run.counts.shows !== undefined
                        ? `${run.counts.shows} shows · ${run.counts.episodes} episodes`
                        : "—"}
                    </Td>
                    <Td>
                      {run.status === "succeeded" && run.catalog_key && canPublish ? (
                        <RollbackButton runId={run.id} />
                      ) : null}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** Rolling back re-points the live catalogue at an earlier run. It is cheap because run
 *  objects are immutable — but it is still a change viewers see, so it confirms first. */
function RollbackButton({ runId }: { runId: string }) {
  const rollback = useRollback();
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={rollback.isPending}
      onClick={() => {
        if (confirm("Make this run the live catalogue again?")) rollback.mutate(runId);
      }}
    >
      <RotateCcw aria-hidden />
      Roll back
    </Button>
  );
}
