"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

type ModalProps = {
  title: string;
  onClose: () => void;
  /** While true, Esc and the close button are disabled (a request is in flight). */
  busy?: boolean;
  children: ReactNode;
};

/**
 * A native <dialog> shown with showModal(): the browser handles focus
 * trapping, Esc, and making the rest of the page inert.
 *
 * Mark the element that should get initial focus with `data-autofocus`.
 * React's autoFocus doesn't work here: it fires on mount, before the dialog
 * is open, and showModal() then moves focus to the first focusable element
 * (the close button).
 */
export function Modal({ title, onClose, busy = false, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) {
      dialog.showModal();
      dialog.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    }
    return () => dialog?.close();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby="modal-title"
      onCancel={(event) => {
        event.preventDefault(); // we close via state, so React stays in charge
        if (!busy) onClose();
      }}
      // Click on the backdrop (the dialog element itself, outside its content).
      onClick={(event) => {
        if (event.target === ref.current && !busy) onClose();
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-xl border border-zinc-200 bg-white p-0 text-zinc-900 shadow-xl backdrop:bg-zinc-950/40 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100"
    >
      <div className="p-5">
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 id="modal-title" className="text-lg font-semibold">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-40 dark:hover:bg-zinc-800"
          >
            <X className="size-4" />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}
