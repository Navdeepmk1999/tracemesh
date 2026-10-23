import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/auth/auth-ui";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in · TraceMesh" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next, error } = await searchParams;
  const nextPath = typeof next === "string" ? next : undefined;

  return (
    <AuthShell
      title="Sign in"
      subtitle="Use your TraceMesh email and password."
      footer={
        <>
          New to TraceMesh?{" "}
          <Link
            href={nextPath ? `/signup?next=${encodeURIComponent(nextPath)}` : "/signup"}
            className="font-medium text-violet-700 hover:underline dark:text-violet-400"
          >
            Create an account
          </Link>
        </>
      }
    >
      <LoginForm next={nextPath} linkError={typeof error === "string" ? error : undefined} />
    </AuthShell>
  );
}
