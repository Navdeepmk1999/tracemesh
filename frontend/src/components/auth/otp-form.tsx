"use client";

import { useEffect, useState, useTransition, type FormEvent } from "react";

import { createClient } from "@/lib/supabase/client";

import { Field, FormError, FormNotice, SubmitButton } from "./auth-ui";

const RESEND_COOLDOWN_SECONDS = 60; // Supabase rejects resends sooner than this

type OtpFormProps = {
  email: string;
  /** signup: confirm a new account. recovery: sign in to reset a password. */
  type: "signup" | "recovery";
  /** Called once the code is accepted; the user now has a session. */
  onVerified: () => void;
  /** Seconds before "Resend" unlocks; 0 when no email was sent just now. */
  initialCooldown?: number;
};

/**
 * Enter the code Supabase emailed. Requires the email template to include
 * {{ .Token }}; the link in the same email works too (see /auth/confirm).
 */
export function OtpForm({ email, type, onVerified, initialCooldown = RESEND_COOLDOWN_SECONDS }: OtpFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(initialCooldown);
  const [pending, startTransition] = useTransition();
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = String(new FormData(event.currentTarget).get("code") ?? "").replace(/\s+/g, "");
    if (!/^\d{6,10}$/.test(token)) {
      setError("Enter the numeric code from the email.");
      return;
    }
    setError(null);
    startTransition(async () => {
      const { error } = await createClient().auth.verifyOtp({ email, token, type });
      if (error) {
        setError(
          error.code === "otp_expired"
            ? "That code is invalid or has expired. Request a new one below."
            : error.message,
        );
        return;
      }
      onVerified();
    });
  }

  async function resend() {
    setResending(true);
    setError(null);
    setNotice(null);
    const supabase = createClient();
    const redirectTo = `${window.location.origin}/auth/confirm?next=${type === "signup" ? "/workflows" : "/reset-password"}`;
    const { error } =
      type === "signup"
        ? await supabase.auth.resend({ type: "signup", email, options: { emailRedirectTo: redirectTo } })
        : await supabase.auth.resetPasswordForEmail(email, { redirectTo });
    setResending(false);
    if (error) {
      setError(error.message);
      return;
    }
    setNotice(`We sent a new code to ${email}.`);
    setCooldown(RESEND_COOLDOWN_SECONDS);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <Field
        label="Verification code"
        name="code"
        inputMode="numeric"
        autoComplete="one-time-code"
        autoFocus
        required
        placeholder="123456"
        className="font-mono tracking-[0.3em]"
        hint={<>Sent to <span className="font-medium text-zinc-700 dark:text-zinc-300">{email}</span>. You can also click the link in that email.</>}
      />
      {error && <FormError>{error}</FormError>}
      {notice && <FormNotice>{notice}</FormNotice>}
      <SubmitButton pending={pending} pendingLabel="Verifying…">
        Verify
      </SubmitButton>
      <button
        type="button"
        onClick={resend}
        disabled={cooldown > 0 || resending}
        className="text-sm text-violet-700 hover:underline disabled:cursor-not-allowed disabled:text-zinc-400 disabled:no-underline dark:text-violet-400"
      >
        {resending ? "Sending…" : cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
      </button>
    </form>
  );
}
