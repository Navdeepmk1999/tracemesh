"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { Field, FormError, SubmitButton } from "@/components/auth/auth-ui";
import { PasswordFields, validatePasswords, type PasswordErrors } from "@/components/auth/password-fields";
import { safeNextPath } from "@/lib/redirect";
import { createClient } from "@/lib/supabase/client";

export function SignupForm({ next }: { next?: string }) {
  const router = useRouter();
  const [fieldErrors, setFieldErrors] = useState<PasswordErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [existingEmail, setExistingEmail] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const destination = safeNextPath(next, "/workflows");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    const errors = validatePasswords(password, String(form.get("confirm") ?? ""));
    setFieldErrors(errors);
    setError(null);
    setExistingEmail(null);
    if (Object.keys(errors).length > 0) return;

    startTransition(async () => {
      const { data, error } = await createClient().auth.signUp({
        email,
        password,
        // Where the link in the confirmation email lands (the code works too).
        options: { emailRedirectTo: `${window.location.origin}/auth/confirm?next=${encodeURIComponent(destination)}` },
      });
      if (error) {
        setError(error.message);
        return;
      }
      if (data.session) {
        // Email confirmation is off for this project: already signed in.
        router.replace(destination);
        router.refresh();
        return;
      }
      // To avoid revealing which emails are registered, Supabase answers a
      // sign-up for an existing account with a user that has no identities
      // (and sends no email) instead of an error.
      if (data.user && data.user.identities?.length === 0) {
        setExistingEmail(email);
        return;
      }
      router.push(`/verify?email=${encodeURIComponent(email)}&next=${encodeURIComponent(destination)}`);
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <Field label="Email" name="email" type="email" autoComplete="email" required />
      <PasswordFields errors={fieldErrors} />
      {error && <FormError>{error}</FormError>}
      {existingEmail && (
        <FormError>
          An account already exists for {existingEmail}.{" "}
          <Link href="/login" className="font-medium underline">
            Sign in
          </Link>{" "}
          or{" "}
          <Link href={`/forgot-password?email=${encodeURIComponent(existingEmail)}`} className="font-medium underline">
            reset your password
          </Link>
          .
        </FormError>
      )}
      <SubmitButton pending={pending} pendingLabel="Creating account…">
        Create account
      </SubmitButton>
    </form>
  );
}
