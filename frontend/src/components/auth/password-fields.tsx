"use client";

import { Field } from "./auth-ui";

// Supabase's default minimum is 6; ask for more. A stricter server setting
// still wins, and its error is shown as-is.
export const MIN_PASSWORD_LENGTH = 8;

export type PasswordErrors = { password?: string; confirm?: string };

/** Validate a new password and its confirmation. Empty object = valid. */
export function validatePasswords(password: string, confirm: string): PasswordErrors {
  const errors: PasswordErrors = {};
  if (password.length < MIN_PASSWORD_LENGTH) errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (confirm !== password) errors.confirm = "Passwords don't match.";
  return errors;
}

/** "New password" + "Confirm password" inputs; read them with FormData. */
export function PasswordFields({ errors, label = "Password" }: { errors: PasswordErrors; label?: string }) {
  return (
    <>
      <Field
        label={label}
        name="password"
        type="password"
        autoComplete="new-password"
        required
        minLength={MIN_PASSWORD_LENGTH}
        error={errors.password}
        hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
      />
      <Field
        label="Confirm password"
        name="confirm"
        type="password"
        autoComplete="new-password"
        required
        error={errors.confirm}
      />
    </>
  );
}
