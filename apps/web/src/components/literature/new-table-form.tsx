"use client";

import { Table2 } from "lucide-react";
import Link from "next/link";
import { useActionState, useState } from "react";

import type { ActionState } from "@/components/confirm-dialog";
import type { ReviewTemplate } from "@/lib/types";

export function NewTableForm({
  projectId,
  templates,
  action,
  disabled,
}: {
  projectId: number;
  templates: ReviewTemplate[];
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
  disabled?: boolean;
}) {
  const [state, formAction, pending] = useActionState(action, { error: null });
  const [key, setKey] = useState(templates[0]?.key ?? "");
  const chosen = templates.find((t) => t.key === key);
  return (
    <form action={formAction} className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="label">Template</span>
        <select
          name="template_key"
          className="input"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        >
          <optgroup label="Built in">
            {templates
              .filter((t) => t.builtin)
              .map((t) => (
                <option key={t.key} value={t.key}>
                  {t.name}
                </option>
              ))}
          </optgroup>
          {templates.some((t) => !t.builtin) && (
            <optgroup label="Your templates">
              {templates
                .filter((t) => !t.builtin)
                .map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.name}
                  </option>
                ))}
            </optgroup>
          )}
        </select>
      </label>
      {chosen && (
        <p className="text-subtle text-xs leading-relaxed">
          {chosen.columns.map((c) => c.label).join(" · ")}
        </p>
      )}
      <label className="flex flex-col gap-1">
        <span className="label">Name (optional)</span>
        <input
          name="name"
          className="input"
          placeholder={chosen?.name ?? "Literature review"}
          maxLength={200}
        />
      </label>
      {state.error && (
        <p role="alert" className="text-sm text-red-600">
          {state.error}
        </p>
      )}
      <button
        type="submit"
        className="btn btn-primary"
        disabled={pending || disabled}
      >
        <Table2 className="h-4 w-4" aria-hidden />
        {pending ? "Creating…" : "Create table"}
      </button>
      <Link
        href={`/projects/${projectId}/literature/templates`}
        className="link text-center text-xs"
      >
        Make or edit your own template
      </Link>
    </form>
  );
}
