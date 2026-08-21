/** Loading, empty, error and permission-denied — the four states the brief asks for.
 *
 * They live together because they are one decision, not four: every screen that fetches
 * has to answer "what does the reader see instead of the data", and answering it in one
 * place is what stops a screen quietly rendering nothing.
 */

import { AlertTriangle, Inbox, Loader2, Lock, WifiOff } from "lucide-react";
import type * as React from "react";

import { ApiError } from "../api";
import { Button } from "./button";
import { cn } from "./utils";

export function Alert({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "info" | "danger" | "warning" | "success";
  title?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const tones = {
    info: "border-border bg-muted text-foreground",
    danger: "border-destructive/40 bg-destructive/10 text-destructive",
    warning: "border-warning/40 bg-warning/10 text-warning",
    success: "border-success/40 bg-success/10 text-success",
  };
  return (
    <div className={cn("rounded-md border px-3 py-2 text-sm", tones[tone], className)} role="alert">
      {title ? <p className="font-medium">{title}</p> : null}
      {children ? <div className={cn(title && "mt-1 opacity-90")}>{children}</div> : null}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div
      className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground"
      role="status"
      aria-live="polite"
    >
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
  icon: Icon = Inbox,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-6 py-14 text-center">
      <Icon className="size-6 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">{title}</p>
      {hint ? <p className="max-w-md text-sm text-muted-foreground">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** Errors an editor can act on.
 *
 * A 401/403 is not a failure to retry — it is a different account. Saying "you do not
 * have permission" and hiding the retry button is the difference between a dead end and
 * a wrong turn.
 */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null;
  const permission = api?.isPermission ?? false;
  const offline = api?.code === "network_error";
  const Icon = permission ? Lock : offline ? WifiOff : AlertTriangle;

  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-14 text-center">
      <Icon className="size-6 text-destructive" aria-hidden />
      <div>
        <p className="text-sm font-medium text-foreground">
          {permission
            ? api?.status === 401
              ? "You are signed out"
              : "You do not have permission"
            : offline
              ? "Cannot reach the API"
              : "Something went wrong"}
        </p>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          {api?.message ?? (error instanceof Error ? error.message : "Unknown error")}
        </p>
      </div>
      {api?.problems.length ? (
        <ul className="max-w-md space-y-1 text-left text-xs text-muted-foreground">
          {api.problems.map((problem, index) => (
            <li key={index}>
              • {problem.message}
              {problem.hint ? <span className="opacity-70"> {problem.hint}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {onRetry && !permission ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
