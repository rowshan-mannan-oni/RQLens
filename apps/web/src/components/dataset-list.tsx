"use client";

import {
  Combine,
  FileSpreadsheet,
  GitCompareArrows,
  LoaderCircle,
  Trash2,
} from "lucide-react";
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
    <div className="flex flex-col gap-3">
      {ready.length > 1 && (
        <div className="flex min-h-9 flex-wrap items-center gap-3 text-sm">
          {selected.length === 0 ? (
            <span className="text-subtle text-xs">
              Tick datasets to compare them or combine them into one.
            </span>
          ) : (
            <>
              <Link
                href={`/projects/${projectId}/compare?ids=${selected.join(",")}`}
                className="btn btn-primary btn-sm"
              >
                <GitCompareArrows className="h-3.5 w-3.5" aria-hidden />
                Compare and combine ({selected.length})
              </Link>
              <button
                onClick={() => setSelected([])}
                className="btn btn-ghost btn-sm"
              >
                Clear selection
              </button>
            </>
          )}
        </div>
      )}
      <ul className="card divide-line divide-y">
        {datasets.map((d) => {
          const summary = sourceSummary(d);
          const isReady = d.status === "ready";
          return (
            <li
              key={d.id}
              className="group has-[a:hover]:bg-surface-2 relative flex items-center gap-3 px-4 py-3.5 transition-colors first:rounded-t-xl last:rounded-b-xl"
            >
              {ready.length > 1 && (
                <input
                  type="checkbox"
                  aria-label={`Select ${d.original_filename}`}
                  disabled={!isReady}
                  checked={selected.includes(d.id)}
                  onChange={() => toggle(d.id)}
                  className="relative z-10 h-4 w-4 shrink-0 accent-(--brand) disabled:opacity-30"
                />
              )}
              <span className="bg-surface-3 text-muted grid h-9 w-9 shrink-0 place-items-center rounded-lg">
                {d.kind === "combined" ? (
                  <Combine className="h-4 w-4" aria-hidden />
                ) : (
                  <FileSpreadsheet className="h-4 w-4" aria-hidden />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  {isReady ? (
                    <Link
                      href={`/projects/${projectId}/datasets/${d.id}`}
                      className="truncate font-medium after:absolute after:inset-0"
                    >
                      {d.original_filename}
                    </Link>
                  ) : (
                    <p className="truncate font-medium">
                      {d.original_filename}
                    </p>
                  )}
                  {d.kind === "combined" && (
                    <span className="badge badge-neutral">Combined</span>
                  )}
                </div>
                <p className="text-subtle mt-0.5 truncate text-xs">
                  <code>{d.table_name}</code>
                  {d.kind === "upload" && ` · ${formatBytes(d.size_bytes)}`}
                  {isReady &&
                    ` · ${formatInt(d.row_count)} rows × ${formatInt(d.column_count)} columns`}
                </p>
                {summary && (
                  <p className="text-subtle truncate text-xs">{summary}</p>
                )}
                {d.status === "failed" && d.error && (
                  <p className="mt-1 text-xs break-words text-red-600 dark:text-red-400">
                    {d.error}
                  </p>
                )}
              </div>
              <span
                className={`badge ${
                  isReady
                    ? "badge-success"
                    : d.status === "failed"
                      ? "badge-danger"
                      : "badge-brand"
                }`}
              >
                {!isReady && d.status !== "failed" && (
                  <LoaderCircle className="h-3 w-3 animate-spin" aria-hidden />
                )}
                {STATUS_LABEL[d.status]}
              </span>
              {(isReady || d.status === "failed") && (
                <div className="relative z-10">
                  <ConfirmDialog
                    triggerLabel={
                      <>
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        <span className="sr-only">
                          Delete {d.original_filename}
                        </span>
                      </>
                    }
                    triggerClassName="btn btn-sm btn-ghost"
                    title={`Delete ${d.original_filename}?`}
                    confirmLabel="Delete dataset"
                    action={deleteDataset.bind(null, projectId, d.id, false)}
                  >
                    <p>
                      This removes the table, its profile, column descriptions
                      and detected links
                      {d.kind === "upload" ? ", and the uploaded file" : ""}.
                      Combined datasets built from it are kept.
                    </p>
                    <p className="mt-2 font-medium">This cannot be undone.</p>
                  </ConfirmDialog>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
