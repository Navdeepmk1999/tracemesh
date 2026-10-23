"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { Field, FormError, SubmitButton } from "@/components/auth/auth-ui";
import { safeNextPath } from "@/lib/redirect";
import { createClient } from "@/lib/supabase/client";

export function LoginForm({ next, linkError }: { next?: string; linkError?: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(linkError ?? null);
  const [unconfirmedEmail, setUnconfirmedEmail] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");

    setError(null);
    setUnconfirmedEmail(null);
    startTransition(async () => {
      const { error } = await createClient().auth.signInWithPassword({ email, password });
      if (error) {
        if (error.code === "email_not_confirmed") setUnconfirmedEmail(email);
        // Supabase deliberately doesn't say whether the email exists.
        else setError(error.message);
        return;
      }
      router.replace(safeNextPath(next, "/workflows"));
      // Re-render Server Components (the nav) with the new session cookie.
      router.refresh();
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <Field label="Email" name="email" type="email" autoComplete="email" required />
      <div className="flex flex-col gap-1.5">
        <Field label="Password" name="password" type="password" autoComplete="current-password" required />
        <Link href="/forgot-password" className="self-end text-xs text-violet-700 hover:underline dark:text-violet-400">
          Forgot password?
        </Link>
      </div>

      {error && <FormError>{error}</FormError>}
      {unconfirmedEmail && (
        <FormError>
          Confirm your email before signing in.{" "}
          <Link
            href={`/verify?email=${encodeURIComponent(unconfirmedEmail)}&resend=1${next ? `&next=${encodeURIComponent(next)}` : ""}`}
            className="font-medium underline"
          >
            Enter your code
          </Link>
        </FormError>
      )}

      <SubmitButton pending={pending} pendingLabel="Signing in…">
        Sign in
      </SubmitButton>
    </form>
  );
}
