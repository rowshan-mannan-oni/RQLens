"use client";

import { useActionState, useId, useRef } from "react";

export type ActionState = { error: string | null };

/**
 * A button that opens a modal asking for confirmation before running a server action.
 * Uses the native <dialog> element: focus is trapped, Esc closes it, the page behind is inert.
 */
export function ConfirmDialog({
  triggerLabel,
  triggerClassName,
  title,
  children,
  confirmLabel,
  action,
}: {
  triggerLabel: React.ReactNode;
  triggerClassName?: string;
  title: string;
  children: React.ReactNode;
  confirmLabel: string;
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [state, formAction, pending] = useActionState(action, { error: null });

  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          dialog.current?.showModal();
        }}
        className={
          triggerClassName ??
          "rounded-md border border-zinc-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50 dark:border-zinc-700 dark:text-red-400 dark:hover:bg-red-950/40"
        }
      >
        {triggerLabel}
      </button>
      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        onClick={(e) => {
          // Clicking the backdrop (the dialog element itself) closes it.
          if (e.target === dialog.current && !pending) dialog.current.close();
        }}
        className="m-auto w-[calc(100%-2rem)] max-w-md rounded-lg border border-zinc-200 bg-white p-0 text-zinc-900 shadow-xl backdrop:bg-black/40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
      >
        <form action={formAction} className="flex flex-col gap-4 p-5">
          <h2 id={titleId} className="text-lg font-semibold">
            {title}
          </h2>
          <div className="text-sm text-zinc-600 dark:text-zinc-300">
            {children}
          </div>
          {state.error && (
            <p role="alert" className="text-sm text-red-600">
              {state.error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              autoFocus
              disabled={pending}
              onClick={() => dialog.current?.close()}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={pending}
              className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {pending ? "Deleting…" : confirmLabel}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
