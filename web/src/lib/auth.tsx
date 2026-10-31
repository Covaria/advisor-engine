// Sign-in. With VITE_DEV_USER set the app skips Supabase and identifies itself with the
// X-Dev-User header, which only an API running dev auth accepts (and that API always
// uses the mock assistant). Otherwise it signs in with Supabase and sends the session's
// access token, which the API verifies.

import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const DEV_USER = import.meta.env.VITE_DEV_USER as string | undefined;
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined;

export const supabase: SupabaseClient | null =
  !DEV_USER && SUPABASE_URL && SUPABASE_KEY ? createClient(SUPABASE_URL, SUPABASE_KEY) : null;

export interface AuthState {
  ready: boolean;
  email: string | null;
  dev: boolean;
  headers: () => Record<string, string>;
  signIn: (email: string, password: string) => Promise<string | null>;
  signUp: (email: string, password: string) => Promise<string | null>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(Boolean(DEV_USER));

  useEffect(() => {
    if (!supabase) {
      setReady(true);
      return;
    }
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  const state: AuthState = {
    ready,
    dev: Boolean(DEV_USER),
    email: DEV_USER ? `${DEV_USER}@dev.local` : (session?.user.email ?? null),
    headers: (): Record<string, string> => {
      if (DEV_USER) return { "X-Dev-User": DEV_USER };
      return session ? { Authorization: `Bearer ${session.access_token}` } : {};
    },
    signIn: async (email, password) => {
      if (!supabase) return "Sign-in is not configured (VITE_SUPABASE_URL / key).";
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      return error?.message ?? null;
    },
    signUp: async (email, password) => {
      if (!supabase) return "Sign-up is not configured (VITE_SUPABASE_URL / key).";
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: window.location.origin },
      });
      return error?.message ?? null;
    },
    signOut: async () => {
      await supabase?.auth.signOut();
    },
  };
  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
