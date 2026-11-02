"use client";

import { useRouter } from "next/navigation";

import { OtpForm } from "@/components/auth/otp-form";
import { safeNextPath } from "@/lib/redirect";

export function VerifyForm({ email, next, justSent }: { email: string; next?: string; justSent: boolean }) {
  const router = useRouter();
  return (
    <OtpForm
      email={email}
      type="signup"
      initialCooldown={justSent ? undefined : 0}
      onVerified={() => {
        router.replace(safeNextPath(next, "/workflows"));
        router.refresh(); // re-render the nav with the new session
      }}
    />
  );
}
