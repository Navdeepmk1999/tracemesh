import type { EmailOtpType } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";

import { safeNextPath } from "@/lib/redirect";
import { createClient } from "@/lib/supabase/server";

/**
 * Landing route for links in Supabase auth emails (sign-up confirmation and
 * password reset). Handles both link styles:
 *  - ?code=...                 the default templates (PKCE flow); must be
 *                              opened in the browser that requested it
 *  - ?token_hash=...&type=...  custom templates using {{ .TokenHash }};
 *                              work in any browser
 * On success the session cookie is set and the user continues to `next`.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const next = safeNextPath(params.get("next"), "/workflows");
  const code = params.get("code");
  const tokenHash = params.get("token_hash");
  const type = params.get("type") as EmailOtpType | null;

  const supabase = await createClient();
  let failed = true;
  if (code) {
    failed = Boolean((await supabase.auth.exchangeCodeForSession(code)).error);
  } else if (tokenHash && type) {
    failed = Boolean((await supabase.auth.verifyOtp({ token_hash: tokenHash, type })).error);
  }

  if (!failed) return NextResponse.redirect(new URL(next, request.url));

  const login = new URL("/login", request.url);
  login.searchParams.set("error", "That link is invalid or has expired. Sign in, or request a new one.");
  return NextResponse.redirect(login);
}
