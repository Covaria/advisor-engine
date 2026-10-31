import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useApi } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { Me } from "../lib/types";

export function Brand() {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <span className="border border-ink px-1 py-0.5 font-serif text-sm">KVS</span>
      <span>
        <span className="block font-serif text-base leading-tight">Knowledge Vault System</span>
        <span className="eyebrow block !text-[10px] !text-muted">Registered advisers only</span>
      </span>
    </Link>
  );
}

export function useMe() {
  const api = useApi();
  return useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me") });
}

export default function Layout() {
  const { email, signOut, dev } = useAuth();
  const me = useMe();
  const initials = (email ?? "?").slice(0, 2).toUpperCase();
  return (
    <div className="min-h-screen">
      <header className="no-print border-b border-rule">
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-6 px-4 py-3">
          <Brand />
          <nav className="flex gap-5 text-sm">
            <NavLink to="/" end className={({ isActive }) => (isActive ? "border-b-2 border-gold pb-0.5 font-semibold" : "text-muted")}>
              Clients
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs">
            {me.data && (
              <span className={`border px-2 py-1 ${me.data.llm === "mock" ? "border-rule text-muted" : "border-gold"}`}>
                Assistant: {me.data.llm === "mock" ? "mock (scripted)" : "live"}
              </span>
            )}
            {dev && <span className="border border-bad/40 px-2 py-1 text-bad">Dev sign-in</span>}
            <span className="hidden border border-rule bg-card px-2 py-1 sm:inline">{email}</span>
            <button className="flex h-8 w-8 items-center justify-center rounded-full bg-ink text-[11px] text-card" title="Sign out" onClick={() => signOut()}>
              {initials}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1240px] px-4 py-6">
        <Outlet />
      </main>
      <footer className="no-print mx-auto max-w-[1240px] border-t border-rule px-4 py-4 text-xs text-muted">
        Decision support for registered advisers. Not investment advice. Every figure is computed by the
        engine{me.data ? ` (v${me.data.engine_version})` : ""}; returns are synthetic and illustrative until
        licensed market data is connected.
      </footer>
    </div>
  );
}
