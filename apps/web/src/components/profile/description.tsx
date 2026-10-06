"use client";

import { useFormStatus } from "react-dom";

import { updateDescription } from "@/app/projects/[id]/datasets/[datasetId]/actions";
import type { Column } from "@/lib/types";

const SOURCE_LABEL: Record<string, string> = {
  user: "Written by you",
  dictionary: "From data dictionary",
  llm: "AI suggestion",
};

export function DescriptionLabel({
  column,
  compact = false,
}: {
  column: Column;
  compact?: boolean;
}) {
  if (!column.description) {
    return <span className="text-zinc-400">–</span>;
  }
  const guess =
    column.description_source === "llm" &&
    column.description_confidence === "low";
  return (
    <span className="flex flex-col gap-0.5">
      <span className={compact ? "line-clamp-2" : undefined}>
        {column.description}
      </span>
      <span className="text-xs text-zinc-500">
        {SOURCE_LABEL[column.description_source ?? ""] ?? ""}
        {column.description_source === "llm" &&
          column.description_confidence &&
          ` · ${guess ? "low confidence, please check" : `${column.description_confidence} confidence`}`}
      </span>
    </span>
  );
}

function SubmitButtons({ hasDescription }: { hasDescription: boolean }) {
  const { pending } = useFormStatus();
  return (
    <div className="flex gap-2">
      <button
        name="intent"
        value="save"
        disabled={pending}
        className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
      >
        {pending ? "Saving…" : "Save description"}
      </button>
      {hasDescription && (
        <button
          name="intent"
          value="clear"
          disabled={pending}
          className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Clear
        </button>
      )}
    </div>
  );
}

export function DescriptionEditor({
  column,
  projectId,
  datasetId,
}: {
  column: Column;
  projectId: number;
  datasetId: number;
}) {
  return (
    <form
      action={updateDescription.bind(null, projectId, datasetId, column.id)}
      className="flex flex-col gap-2"
    >
      <label
        htmlFor={`desc-${column.id}`}
        className="text-xs font-medium text-zinc-600 dark:text-zinc-400"
      >
        Description{" "}
        <span className="font-normal">
          ({SOURCE_LABEL[column.description_source ?? ""] ?? "none yet"}
          {column.description_source === "llm" &&
            column.description_confidence &&
            `, ${column.description_confidence} confidence`}
          )
        </span>
      </label>
      <textarea
        id={`desc-${column.id}`}
        name="description"
        rows={2}
        maxLength={2000}
        defaultValue={column.description ?? ""}
        placeholder="What does this column record? Include units or coding."
        className="w-full rounded-md border border-zinc-300 bg-transparent px-3 py-2 text-sm dark:border-zinc-700"
      />
      <SubmitButtons hasDescription={Boolean(column.description)} />
    </form>
  );
}
