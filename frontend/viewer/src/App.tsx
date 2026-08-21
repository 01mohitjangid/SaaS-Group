import { Search } from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { cn } from "@shared/ui/utils";

export function App() {
  const onSearch = useLocation().pathname === "/search";

  return (
    <div className="min-h-dvh bg-background">
      {/* The bar sits over the hero, so it fades from transparent-ish into solid rather
          than cutting a hard line across the artwork. */}
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-6 px-4 sm:px-8">
          <Link to="/" className="flex items-center gap-2" aria-label="Peblo TV home">
            <span className="text-xl font-black tracking-tight text-primary">PEBLO</span>
            <span className="text-xl font-light tracking-[0.3em] text-foreground">TV</span>
          </Link>

          <nav className="flex items-center gap-4 text-sm">
            <NavLink
              to="/"
              className={({ isActive }) =>
                cn(
                  "transition-colors hover:text-foreground",
                  isActive ? "text-foreground" : "text-muted-foreground",
                )
              }
            >
              Home
            </NavLink>
          </nav>

          <div className="ml-auto">
            <Link
              to="/search"
              className={cn(
                "flex items-center gap-2 rounded-full border border-border px-3 py-1.5 text-sm transition-colors",
                onSearch
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Search className="size-4" aria-hidden />
              Search
            </Link>
          </div>
        </div>
      </header>

      <main>
        <Outlet />
      </main>

      <footer className="mx-auto max-w-[1600px] px-4 py-10 text-xs text-muted-foreground sm:px-8">
        Peblo TV reads only the published catalogue.
      </footer>
    </div>
  );
}
