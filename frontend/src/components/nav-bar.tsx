import { Waypoints } from "lucide-react";
import Link from "next/link";

import { SignOutButton } from "@/components/sign-out-button";
import { getUser } from "@/lib/auth";

export async function NavBar() {
  const user = await getUser();

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-zinc-200 bg-white/80 px-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
      <div className="flex min-w-0 items-center gap-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <Waypoints className="size-5 text-violet-600 dark:text-violet-400" aria-hidden />
          TraceMesh
        </Link>
        {user && (
          <nav className="hidden items-center gap-4 text-sm text-zinc-600 sm:flex dark:text-zinc-400">
            <Link href="/workflows/new" className="hover:text-zinc-950 dark:hover:text-zinc-50">
              Canvas
            </Link>
          </nav>
        )}
      </div>

      <div className="flex min-w-0 items-center gap-3 text-sm">
        {user ? (
          <>
            <span className="hidden truncate text-zinc-500 md:inline" title={user.email ?? undefined}>
              {user.email}
            </span>
            <SignOutButton />
          </>
        ) : (
          <Link
            href="/login"
            className="rounded-md bg-zinc-900 px-3 py-1.5 font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            Sign in
          </Link>
        )}
      </div>
    </header>
  );
}
