import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/auth/auth-ui";

import { SignupForm } from "./signup-form";

export const metadata: Metadata = { title: "Create account · TraceMesh" };

export default async function SignupPage({ searchParams }: PageProps<"/signup">) {
  const { next } = await searchParams;
  const nextPath = typeof next === "string" ? next : undefined;
  return (
    <AuthShell
      title="Create your account"
      subtitle="We'll email you a code to confirm your address."
      footer={
        <>
          Already have an account?{" "}
          <Link href={nextPath ? `/login?next=${encodeURIComponent(nextPath)}` : "/login"} className="font-medium text-violet-700 hover:underline dark:text-violet-400">
            Sign in
          </Link>
        </>
      }
    >
      <SignupForm next={nextPath} />
    </AuthShell>
  );
}
