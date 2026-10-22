import { createClient } from "@/lib/supabase/client";

import { ApiError } from "./client";

/**
 * The signed-in user's Supabase access token, for the backend's
 * Authorization header and WebSocket auth message. getSession() refreshes
 * the token first if it has expired, so callers always get a usable one.
 */
export async function getSupabaseAccessToken(): Promise<string> {
  const { data, error } = await createClient().auth.getSession();
  const token = data.session?.access_token;
  if (error || !token) throw new ApiError(401, "Your session has ended. Sign in again.");
  return token;
}
