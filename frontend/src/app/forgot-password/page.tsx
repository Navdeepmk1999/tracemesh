import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/auth/auth-ui";

import { ForgotPasswordForm } from "./forgot-password-form";

export const metadata: Metadata = { title: "Reset password · TraceMesh" };

export default async function ForgotPasswordPage({ searchParams }: PageProps<"/forgot-password">) {
  const { email } = await searchParams;
  return (
    <AuthShell
      title="Reset your password"
      footer={
        <Link href="/login" className="hover:underline">
          Back to sign in
        </Link>
      }
    >
      <ForgotPasswordForm initialEmail={typeof email === "string" ? email : ""} />
    </AuthShell>
  );
}
