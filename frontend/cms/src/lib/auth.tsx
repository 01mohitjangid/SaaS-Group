import { useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { request } from "@shared/api";

export interface Me {
  email: string;
  display_name: string;
  role: "editor" | "admin";
  can_publish: boolean;
}

const STORAGE_KEY = "peblo.cms.token";

interface AuthValue {
  token: string | null;
  me: Me | null;
  loading: boolean;
  error: unknown;
  signIn: (token: string) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(STORAGE_KEY));

  const signIn = useCallback((next: string) => {
    localStorage.setItem(STORAGE_KEY, next);
    setToken(next);
  }, []);

  const signOut = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setToken(null);
  }, []);

  // Asking the API who we are is what lets the publish button be disabled *with a
  // reason* instead of being a button that always fails for an editor.
  const { data, isPending, error } = useQuery({
    queryKey: ["me", token],
    queryFn: () => request<Me>("/admin/me", { token: token! }),
    enabled: Boolean(token),
    retry: false,
  });

  const value = useMemo<AuthValue>(
    () => ({
      token,
      me: data ?? null,
      loading: Boolean(token) && isPending,
      error,
      signIn,
      signOut,
    }),
    [token, data, isPending, error, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** The token for API calls. Throws rather than sending an unauthenticated request, which
 *  would come back as a confusing 401 from inside a screen that assumed it was signed in. */
export function useToken(): string {
  const { token } = useAuth();
  if (!token) throw new Error("not signed in");
  return token;
}
