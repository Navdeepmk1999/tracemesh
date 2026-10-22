import { NextResponse, type NextRequest } from "next/server";

import { safeNextPath } from "@/lib/redirect";
import { updateSession } from "@/lib/supabase/proxy";

const PROTECTED_PREFIXES = ["/workflows"];

export async function proxy(request: NextRequest) {
  const { response, userId } = await updateSession(request);
  const { pathname, search } = request.nextUrl;

  if (!userId && PROTECTED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    return redirectWithCookies(loginUrl, response);
  }

  if (userId && pathname === "/login") {
    const target = safeNextPath(request.nextUrl.searchParams.get("next"));
    return redirectWithCookies(new URL(target, request.url), response);
  }

  return response;
}

/** A redirect that keeps any cookies updateSession set, so a refreshed (or
 * cleared) session isn't lost on the way. */
function redirectWithCookies(url: URL, from: NextResponse) {
  const redirect = NextResponse.redirect(url);
  from.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
  from.headers.forEach((value, key) => {
    if (key.toLowerCase() !== "location") redirect.headers.set(key, value);
  });
  return redirect;
}

export const config = {
  matcher: [
    // Every route except static assets, so sessions stay fresh everywhere.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
