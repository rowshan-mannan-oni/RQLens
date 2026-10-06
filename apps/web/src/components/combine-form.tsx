"use client";

import { useActionState, useState } from "react";

import {
  type CombineState,
  createCombined,
} from "@/app/projects/[id]/compare/actions";
import type { Relationship } from "@/lib/types";

type Table = { id: number; label: string };
type Col = { name: string; label: string };

const input =
  "rounded-md border border-line-strong bg-transparent px-2 py-1.5 text-sm";

export function CombineForm({
  projectId,
  tables,
  columns,
  links,
  stackable,
}: {
  projectId: number;
  tables: Table[];
  columns: Record<number, Col[]>;
  links: Relationship[];
  stackable: boolean;
}) {
  const canJoin = tables.length === 2;
  const best = links[0];
  const [mode, setMode] = useState<"stack" | "join">(
    canJoin && (!stackable || best) ? "join" : "stack",
  );
  const [left, setLeft] = useState(best?.left.dataset_id ?? tables[0].id);
  const right =
    tables.find((t) => t.id !== left)?.id ?? tables[tables.length - 1].id;
  const link = links.find(
    (l) => l.left.dataset_id === left && l.right.dataset_id === right,
  );
  const reversed = links.find(
    (l) => l.left.dataset_id === right && l.right.dataset_id === left,
  );
  const defaultLeftCol =
    link?.left.column ?? reversed?.right.column ?? columns[left]?.[0]?.name;
  const defaultRightCol =
    link?.right.column ?? reversed?.left.column ?? columns[right]?.[0]?.name;

  const [state, action, pending] = useActionState<CombineState, FormData>(
    createCombined.bind(
      null,
      projectId,
      tables.map((t) => t.id),
    ),
    { error: null },
  );
  const label = (id: number) => tables.find((t) => t.id === id)?.label ?? "";
  const defaultName =
    mode === "stack"
      ? `Stacked ${tables.length} files`
      : `${label(left).replace(/\.(csv|tsv|txt|xlsx|xlsm|sav|zsav|por|dta|parquet|pq)$/i, "")} + ${label(right).replace(/\.(csv|tsv|txt|xlsx|xlsm|sav|zsav|por|dta|parquet|pq)$/i, "")}`;

  return (
    <form action={action} className="card flex flex-col gap-4 p-4">
      <div>
        <h2 className="section-title">Combine into a new dataset</h2>
        <p className="text-subtle text-sm">
          The result is profiled like an uploaded file and can be combined
          again. Your original files are not changed.
        </p>
      </div>

      <fieldset className="flex flex-col gap-2 text-sm">
        <legend className="sr-only">How to combine</legend>
        <label className="flex items-start gap-2">
          <input
            type="radio"
            name="mode"
            value="stack"
            checked={mode === "stack"}
            onChange={() => setMode("stack")}
            className="mt-1"
          />
          <span>
            <span className="font-medium">Stack rows</span>: append the files
            one under another, matching columns by name, with a column saying
            which file each row came from.
            {!stackable && (
              <span className="block text-amber-700 dark:text-amber-400">
                ⚠ Fewer than half of the columns are in every file; many cells
                will be empty.
              </span>
            )}
          </span>
        </label>
        <label
          className={`flex items-start gap-2 ${canJoin ? "" : "opacity-50"}`}
        >
          <input
            type="radio"
            name="mode"
            value="join"
            disabled={!canJoin}
            checked={mode === "join"}
            onChange={() => setMode("join")}
            className="mt-1"
          />
          <span>
            <span className="font-medium">Join on a key</span>: add the columns
            of one file to matching rows of the other.
            {!canJoin && " Select exactly two files to join."}
          </span>
        </label>
      </fieldset>

      {mode === "join" && canJoin && (
        <div
          key={`${left}-${right}`}
          className="grid gap-3 text-sm sm:grid-cols-2"
        >
          <label className="flex flex-col gap-1">
            <span className="text-subtle text-xs">Keep all rows of</span>
            <select
              name="left_dataset"
              value={left}
              onChange={(e) => setLeft(Number(e.target.value))}
              className={input}
            >
              {tables.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-subtle text-xs">Key column in it</span>
            <select
              name="left_column"
              defaultValue={defaultLeftCol}
              className={input}
            >
              {columns[left]?.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-subtle text-xs">Add columns from</span>
            <input type="hidden" name="right_dataset" value={right} />
            <span className="py-1.5">{label(right)}</span>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-subtle text-xs">Matching key column</span>
            <select
              name="right_column"
              defaultValue={defaultRightCol}
              className={input}
            >
              {columns[right]?.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 sm:col-span-2">
            <span className="text-subtle text-xs">Rows without a match</span>
            <select name="how" defaultValue="left" className={input}>
              <option value="left">
                Keep them (left join), with empty added columns
              </option>
              <option value="inner">Drop them (inner join)</option>
            </select>
          </label>
          {(link || reversed) && (
            <p className="text-subtle text-xs sm:col-span-2">
              Key columns pre-filled from the detected link between these files.
            </p>
          )}
        </div>
      )}

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-subtle text-xs">Name of the new dataset</span>
        <input
          key={defaultName}
          name="name"
          required
          maxLength={120}
          defaultValue={defaultName}
          className={input}
        />
      </label>

      {state.error && <p className="text-sm text-red-600">{state.error}</p>}
      <button disabled={pending} className="btn btn-primary self-start">
        {pending ? "Creating…" : "Create combined dataset"}
      </button>
    </form>
  );
}
