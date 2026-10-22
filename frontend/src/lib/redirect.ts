/**
 * Where to send the user after login. Only same-origin paths are allowed:
 * "/workflows/x" is fine; "https://evil.test", "//evil.test" (protocol-
 * relative) and "/\evil.test" (which browsers normalize to "//") are not.
 */
export function safeNextPath(next: string | null | undefined, fallback = "/"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return fallback;
  }
  return next;
}
