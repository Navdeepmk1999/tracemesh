import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/auth/auth-ui";

import { VerifyForm } from "./verify-form";

export const metadata: Metadata = { title: "Confirm your email · TraceMesh" };

export default async function VerifyPage({ searchParams }: PageProps<"/verify">) {
  const { email, next, resend } = await searchParams;

  if (typeof email !== "string" || !email) {
    return (
      <AuthShell title="Confirm your email">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Start from{" "}
          <Link href="/signup" className="font-medium text-violet-700 hover:underline dark:text-violet-400">
            sign up
          </Link>{" "}
          to get a confirmation code.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Check your email"
      subtitle="Enter the code we sent to finish creating your account."
      footer={
        <Link href="/signup" className="hover:underline">
          Use a different email
        </Link>
      }
    >
      {/* resend=1: arrived from sign-in with an unconfirmed account, so no
          code was sent just now and resending is allowed straight away. */}
      <VerifyForm email={email} next={typeof next === "string" ? next : undefined} justSent={resend !== "1"} />
    </AuthShell>
  );
}
