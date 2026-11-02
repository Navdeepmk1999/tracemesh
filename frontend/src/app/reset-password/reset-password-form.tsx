"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { FormError, SubmitButton } from "@/components/auth/auth-ui";
import { PasswordFields, validatePasswords, type PasswordErrors } from "@/components/auth/password-fields";
import { createClient } from "@/lib/supabase/client";

export function ResetPasswordForm() {
  const router = useRouter();
  const [fieldErrors, setFieldErrors] = useState<PasswordErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    const errors = validatePasswords(password, String(form.get("confirm") ?? ""));
    setFieldErrors(errors);
    setError(null);
    if (Object.keys(errors).length > 0) return;

    startTransition(async () => {
      const { error } = await createClient().auth.updateUser({ password });
      if (error) {
        // e.g. "New password should be different from the old password."
        setError(error.message);
        return;
      }
      router.replace("/workflows");
      router.refresh();
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <PasswordFields errors={fieldErrors} label="New password" />
      {error && <FormError>{error}</FormError>}
      <SubmitButton pending={pending} pendingLabel="Saving…">
        Update password
      </SubmitButton>
    </form>
  );
}
