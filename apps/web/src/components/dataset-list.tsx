"use client";

import Link from "next/link";
import { useState } from "react";

import { deleteDataset } from "@/app/projects/[id]/actions";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { formatBytes, formatInt } from "@/lib/format";
import type { Dataset, DatasetStatus } from "@/lib/types";

const STATUS_LABEL: Record<DatasetStatus, string> = {
  queued: "Queued",
  loading: "Loading",
  profiling: "Profiling",
  ready: "Ready",
  failed: "Failed",
};

const MAX_SELECTED = 20;

function sourceSummary(d: Dataset): string | null {
  const spec = d.source_json;
  if (d.kind !== "combined" || !spec) return null;
  const labels = spec.labels ?? [];
  return spec.mode === "stack"
    ? `Stacked from ${labels.join(", ")}`
    : `${labels[0]} joined with ${labels[1]} (${spec.how} join)`;
}

export function DatasetList({
  projectId,
  datasets,
}: {
  projectId: number;
  datasets: Dataset[];
}) {
  const [selected, setSelected] = useState<number[]>([]);
  const ready = datasets.filter((d) => d.status === "ready");

  function toggle(id: number) {
    setSelected((s) =>
      s.includes(id)
        ? s.filter((x) => x !== id)
        : s.length < MAX_SELECTED
          ? [...s, id]
          : s,
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {ready.length > 1 && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-zinc-600 dark:text-zinc-400">
            Tick datasets to compare them or combine them into one.
          </span>
          {selected.length > 0 && (
            <>
              <Link
                href={`/projects/${projectId}/compare?ids=${selected.join(",")}`}
                className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
              >
                Compare and combine ({selected.length})
              </Link>
              <button
                onClick={() => setSelected([])}
                className="text-xs text-zinc-500 hover:underline"
              >
                Clear selection
              </button>
            </>
          )}
        </div>
      )}
      <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
        {datasets.map((d) => {
          const summary = sourceSummary(d);
          return (
            <li key={d.id} className="flex items-center gap-3 p-3">
              <input
                type="checkbox"
                aria-label={`Select ${d.original_filename}`}
                disabled={d.status !== "ready"}
                checked={selected.includes(d.id)}
                onChange={() => toggle(d.id)}
                className="h-4 w-4 shrink-0 accent-zinc-900 disabled:opacity-30 dark:accent-zinc-100"
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  {d.status === "ready" ? (
                    <Link
                      href={`/projects/${projectId}/datasets/${d.id}`}
                      className="font-medium hover:underline"
                    >
                      {d.original_filename}
                    </Link>
                  ) : (
                    <p className="font-medium">{d.original_filename}</p>
                  )}
                  {d.kind === "combined" && (
                    <span className="rounded-full border border-zinc-300 px-1.5 py-0.5 text-xs text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
                      Combined
                    </span>
                  )}
                </div>
                <p className="text-xs text-zinc-500">
                  table <code>{d.table_name}</code>
                  {d.kind === "upload" && ` · ${formatBytes(d.size_bytes)}`}
                  {d.status === "ready" &&
                    ` · ${formatInt(d.row_count)} rows × ${formatInt(d.column_count)} columns`}
                </p>
                {summary && <p className="text-xs text-zinc-500">{summary}</p>}
                {d.status === "failed" && d.error && (
                  <p className="mt-1 text-xs break-words text-red-600">
                    {d.error}
                  </p>
                )}
              </div>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                  d.status === "ready"
                    ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                    : d.status === "failed"
                      ? "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200"
                      : "animate-pulse bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                }`}
              >
                {STATUS_LABEL[d.status]}
              </span>
              {(d.status === "ready" || d.status === "failed") && (
                <ConfirmDialog
                  triggerLabel="Delete"
                  title={`Delete ${d.original_filename}?`}
                  confirmLabel="Delete dataset"
                  action={deleteDataset.bind(null, projectId, d.id, false)}
                >
                  <p>
                    This removes the table, its profile, column descriptions and
                    detected links
                    {d.kind === "upload" ? ", and the uploaded file" : ""}.
                    Combined datasets built from it are kept.
                  </p>
                  <p className="mt-2 font-medium">This cannot be undone.</p>
                </ConfirmDialog>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
