import { Film, ListVideo, LogOut, Rocket, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { Badge, Card, Input, Label } from "@shared/ui/primitives";
import { Button } from "@shared/ui/button";
import { Alert, ErrorState, LoadingState } from "@shared/ui/states";
import { cn } from "@shared/ui/utils";

import { useAuth } from "./lib/auth";

function SignIn() {
  const { signIn, error } = useAuth();
  const [value, setValue] = useState("");

  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-6">
      <div className="mb-6 flex items-center gap-2">
        <span className="text-2xl font-black tracking-tight text-primary">PEBLO</span>
        <span className="text-2xl font-light tracking-[0.3em]">TV</span>
        <Badge variant="outline" className="ml-1">
          Content
        </Badge>
      </div>

      <Card>
        <form
          className="flex flex-col gap-3 p-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (value.trim()) signIn(value.trim());
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="token">Access token</Label>
            <Input
              id="token"
              type="password"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="Paste the token you were given"
              autoFocus
            />
          </div>

          {error ? (
            <Alert tone="danger" title="That token was not accepted">
              Check it with an admin, or paste it again.
            </Alert>
          ) : null}

          <Button type="submit" disabled={!value.trim()}>
            Sign in
          </Button>

          <p className="text-xs text-muted-foreground">
            Demo tokens: <code className="text-foreground">prod-editor-change-me</code> (edit) or{" "}
            <code className="text-foreground">prod-admin-change-me</code> (edit and publish).
          </p>
        </form>
      </Card>
    </div>
  );
}

const NAV = [
  { to: "/shows", label: "Shows", icon: Film },
  { to: "/episodes", label: "Episodes", icon: ListVideo },
  { to: "/publish", label: "Publish", icon: Rocket },
];

export function App() {
  const { token, me, loading, error, signOut } = useAuth();

  if (!token) return <SignIn />;
  if (loading) return <LoadingState label="Signing in…" />;

  if (error) {
    return (
      <div className="mx-auto max-w-lg p-8">
        <ErrorState error={error} />
        <div className="mt-4 text-center">
          <Button variant="secondary" size="sm" onClick={signOut}>
            Use a different token
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1500px] items-center gap-6 px-4 sm:px-6">
          <div className="flex items-center gap-2">
            <span className="text-lg font-black tracking-tight text-primary">PEBLO</span>
            <span className="text-lg font-light tracking-[0.25em]">TV</span>
            <Badge variant="outline">Content</Badge>
          </div>

          <nav className="flex items-center gap-1">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
                    isActive
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )
                }
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-xs font-medium">{me?.email}</p>
              <p className="text-[11px] text-muted-foreground">
                {me?.can_publish ? "Admin — can publish" : "Editor — cannot publish"}
              </p>
            </div>
            {me && !me.can_publish ? (
              <ShieldAlert className="size-4 text-muted-foreground" aria-label="Editor access" />
            ) : null}
            <Button variant="ghost" size="icon" onClick={signOut} aria-label="Sign out">
              <LogOut aria-hidden />
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
