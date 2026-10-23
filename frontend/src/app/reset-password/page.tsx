import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-ui";
import { requireUser } from "@/lib/auth";

import { ResetPasswordForm } from "./reset-password-form";

export const metadata: Metadata = { title: "Choose a new password · TraceMesh" };

export default async function ResetPasswordPage() {
  // The recovery code (or link) signs the user in; without a session there
  // is no account to set a password on.
  const user = await requireUser("/reset-password");
  return (
    <AuthShell title="Choose a new password" subtitle={user.email ? `For ${user.email}` : undefined}>
      <ResetPasswordForm />
    </AuthShell>
  );
}
