"use client";

import { useActionState, useRef } from "react";

import type { ActionState } from "@/components/confirm-dialog";

export function AddQuestionForm({
  action,
}: {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
}) {
  const form = useRef<HTMLFormElement>(null);
  const [state, formAction, pending] = useActionState(
    async (prev: ActionState, data: FormData) => {
      const next = await action(prev, data);
      if (!next.error) form.current?.reset();
      return next;
    },
    { error: null },
  );
  return (
    <form ref={form} action={formAction} className="flex flex-col gap-2">
      <label htmlFor="rq-text" className="text-sm font-medium">
        Add a research question
      </label>
      <textarea
        id="rq-text"
        name="text"
        rows={2}
        maxLength={1000}
        required
        placeholder="e.g. Do union members earn higher hourly wages than non-members?"
        className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-950"
      />
      <div className="flex items-center gap-3">
        <button
          disabled={pending}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {pending ? "Adding…" : "Add and assess"}
        </button>
        {state.error && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            {state.error}
          </p>
        )}
      </div>
    </form>
  );
}
