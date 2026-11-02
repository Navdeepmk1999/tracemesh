import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { getUser } from "@/lib/auth";

export default async function Home() {
  const user = await getUser();

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-4 py-16">
      <h1 className="text-4xl font-semibold tracking-tight">Design, run and trace multi-agent workflows.</h1>
      <p className="text-lg text-zinc-600 dark:text-zinc-400">
        Compose triggers, agents and webhooks on a canvas, then watch every node execute live.
      </p>
      <div>
        {/* The proxy sends signed-out users to /login and back here after. */}
        <Link
          href={user ? "/workflows" : "/signup?next=/workflows"}
          className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 font-medium text-white hover:bg-violet-500"
        >
          {user ? "Open your workflows" : "Get started"}
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
    </div>
  );
}
