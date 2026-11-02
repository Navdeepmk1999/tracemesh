import type { InputHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 mb-6 text-sm text-zinc-500">{subtitle}</p>}
        {!subtitle && <div className="mb-6" />}
        {children}
        {footer && <div className="mt-6 text-center text-sm text-zinc-500">{footer}</div>}
      </div>
    </div>
  );
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string | null; hint?: ReactNode };

export function Field({ label, error, hint, id, className, ...input }: FieldProps) {
  const fieldId = id ?? input.name;
  const describedBy = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={fieldId} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={fieldId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(
          "rounded-md border border-zinc-300 bg-white px-3 py-2 outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/30 dark:border-zinc-700 dark:bg-zinc-900",
          error && "border-red-500 focus:border-red-500 focus:ring-red-500/30",
          className,
        )}
        {...input}
      />
      {error ? (
        <p id={`${fieldId}-error`} className="text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${fieldId}-hint`} className="text-xs text-zinc-500">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

export function FormError({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
      {children}
    </p>
  );
}

export function FormNotice({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="rounded-md bg-violet-50 px-3 py-2 text-sm text-violet-800 dark:bg-violet-950/50 dark:text-violet-200">
      {children}
    </p>
  );
}

export function SubmitButton({ pending, children, pendingLabel }: { pending: boolean; children: ReactNode; pendingLabel: string }) {
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded-md bg-violet-600 px-4 py-2 font-medium text-white hover:bg-violet-500 disabled:opacity-60"
    >
      {pending ? pendingLabel : children}
    </button>
  );
}
