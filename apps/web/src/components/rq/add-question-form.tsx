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
      <label htmlFor="rq-text" className="section-title">
        Add a research question
      </label>
      <textarea
        id="rq-text"
        name="text"
        rows={2}
        maxLength={1000}
        required
        placeholder="e.g. Do union members earn higher hourly wages than non-members?"
        className="input resize-none"
      />
      <div className="flex items-center gap-3">
        <button disabled={pending} className="btn btn-primary">
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
