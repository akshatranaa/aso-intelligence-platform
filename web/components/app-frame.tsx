"use client";

/**
 * Auth gate + app shell. Unauthenticated users are sent to /login (which
 * renders bare, without the sidebar); everyone else gets the full shell.
 */

import { Suspense, useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Sidebar, Topbar } from "@/components/shell";

export function AppFrame({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/login";

  useEffect(() => {
    if (!loading && !session && !isLogin) router.replace("/login");
  }, [loading, session, isLogin, router]);

  // The login page renders standalone (no shell).
  if (isLogin) return <>{children}</>;

  // Gate everything else behind a valid session.
  if (loading || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="size-8 animate-spin text-neutral-300" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Suspense>
        <Sidebar />
      </Suspense>
      <div className="flex min-w-0 flex-1 flex-col">
        <Suspense>
          <Topbar />
        </Suspense>
        <main className="flex-1 px-8 py-6">{children}</main>
      </div>
    </div>
  );
}
