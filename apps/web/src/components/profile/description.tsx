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
    return <span className="text-subtle">–</span>;
  }
  const guess =
    column.description_source === "llm" &&
    column.description_confidence === "low";
  return (
    <span className="flex flex-col gap-0.5">
      <span className={compact ? "line-clamp-2" : undefined}>
        {column.description}
      </span>
      <span className="text-subtle text-xs">
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
        className="btn btn-primary btn-sm"
      >
        {pending ? "Saving…" : "Save description"}
      </button>
      {hasDescription && (
        <button
          name="intent"
          value="clear"
          disabled={pending}
          className="btn btn-secondary btn-sm"
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
        className="text-muted text-xs font-medium"
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
        className="border-line-strong w-full rounded-md border bg-transparent px-3 py-2 text-sm"
      />
      <SubmitButtons hasDescription={Boolean(column.description)} />
    </form>
  );
}
