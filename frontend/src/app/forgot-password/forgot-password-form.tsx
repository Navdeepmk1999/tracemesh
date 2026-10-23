"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { Field, FormError, FormNotice, SubmitButton } from "@/components/auth/auth-ui";
import { OtpForm } from "@/components/auth/otp-form";
import { createClient } from "@/lib/supabase/client";

export function ForgotPasswordForm({ initialEmail }: { initialEmail: string }) {
  const router = useRouter();
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    setError(null);
    startTransition(async () => {
      const { error } = await createClient().auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/auth/confirm?next=/reset-password`,
      });
      if (error) {
        setError(error.message);
        return;
      }
      setSentTo(email);
    });
  }

  if (sentTo) {
    return (
      <div className="flex flex-col gap-4">
        {/* Supabase responds the same whether or not the account exists. */}
        <FormNotice>If an account exists for {sentTo}, we&apos;ve emailed it a reset code.</FormNotice>
        <OtpForm email={sentTo} type="recovery" onVerified={() => router.replace("/reset-password")} />
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <p className="text-sm text-zinc-500">Enter your account&apos;s email and we&apos;ll send you a code to reset your password.</p>
      <Field label="Email" name="email" type="email" autoComplete="email" required defaultValue={initialEmail} />
      {error && <FormError>{error}</FormError>}
      <SubmitButton pending={pending} pendingLabel="Sending…">
        Send reset code
      </SubmitButton>
    </form>
  );
}
