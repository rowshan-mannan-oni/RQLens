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
        data-edit
        onClick={(e) => {
          e.stopPropagation();
          dialog.current?.showModal();
        }}
        className={triggerClassName ?? "btn btn-sm btn-danger"}
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
        className="border-line bg-surface text-fg shadow-pop m-auto w-[calc(100%-2rem)] max-w-md rounded-2xl border p-0 backdrop:bg-black/40 backdrop:backdrop-blur-[2px]"
      >
        <form action={formAction} className="flex flex-col gap-4 p-6">
          <h2 id={titleId} className="text-lg font-semibold tracking-tight">
            {title}
          </h2>
          <div className="text-muted text-sm leading-relaxed">{children}</div>
          {state.error && (
            <p role="alert" className="text-sm text-red-600">
              {state.error}
            </p>
          )}
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              autoFocus
              disabled={pending}
              onClick={() => dialog.current?.close()}
              className="btn btn-secondary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={pending}
              className="btn bg-red-600 text-white shadow-sm hover:bg-red-700"
            >
              {pending ? "Deleting…" : confirmLabel}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
