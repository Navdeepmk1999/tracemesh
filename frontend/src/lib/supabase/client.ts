import { createBrowserClient } from "@supabase/ssr";

import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./env";

/**
 * Supabase client for Client Components. The session lives in cookies (not
 * localStorage), so the proxy and Server Components can read it too.
 * createBrowserClient returns a singleton, so calling this repeatedly is cheap.
 */
export function createClient() {
  return createBrowserClient(SUPABASE_URL, SUPABASE_ANON_KEY);
}
