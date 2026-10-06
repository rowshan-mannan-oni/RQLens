import { ArrowLeft, CircleCheck, FileSpreadsheet } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { deleteDataset } from "@/app/projects/[id]/actions";
import { AutoRefresh } from "@/components/auto-refresh";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ColumnsTable } from "@/components/profile/columns-table";
import { DictionaryUpload } from "@/components/profile/dictionary-upload";
import {
  Associations,
  MissingPatterns,
} from "@/components/profile/relationships";
import {
  SEVERITY_ORDER,
  SEVERITY_STYLE,
  SeverityBadge,
} from "@/components/profile/severity";
import { ApiError, apiFetch } from "@/lib/api";
import { formatInt, formatPct } from "@/lib/format";
import type { DatasetProfile } from "@/lib/types";

import { redescribe } from "./actions";

export default async function DatasetProfilePage(
  props: PageProps<"/projects/[id]/datasets/[datasetId]">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id, datasetId } = await props.params;

  let data: DatasetProfile;
  try {
    data = await apiFetch<DatasetProfile>(
      `/projects/${id}/datasets/${datasetId}/profile`,
    );
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  const { dataset, table, warnings, columns } = data;
  const original = new Map(
    columns.map((c) => [c.name, c.original_name ?? c.name]),
  );

  const tiles: [string, string][] = table
    ? [
        ["Rows", formatInt(table.row_count)],
        ["Columns", formatInt(table.column_count)],
        ["Missing cells", formatPct(table.missing_cells_pct)],
        ["Duplicate rows", formatInt(table.duplicate_rows)],
        [
          "Candidate keys",
          table.candidate_keys.map((k) => original.get(k) ?? k).join(", ") ||
            "none",
        ],
      ]
    : [];

  return (
    <div className="flex flex-col gap-8">
      <AutoRefresh
        active={
          dataset.describe_status === "pending" ||
          dataset.describe_status === "running"
        }
        ms={3000}
      />
      <div>
        <Link
          href={`/projects/${id}`}
          className="text-subtle hover:text-fg inline-flex items-center gap-1 text-xs"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
          All datasets
        </Link>
        <div className="mt-2 flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="bg-brand-soft text-brand-fg grid h-10 w-10 shrink-0 place-items-center rounded-xl">
              <FileSpreadsheet className="h-5 w-5" aria-hidden />
            </span>
            <h2 className="truncate text-xl font-semibold tracking-tight">
              {dataset.original_filename}
            </h2>
          </div>
          {dataset.status === "ready" || dataset.status === "failed" ? (
            <ConfirmDialog
              triggerLabel="Delete dataset"
              triggerClassName="btn btn-sm btn-danger"
              title={`Delete ${dataset.original_filename}?`}
              confirmLabel="Delete dataset"
              action={deleteDataset.bind(
                null,
                Number(id),
                Number(datasetId),
                true,
              )}
            >
              <p>
                This removes the table, its profile, column descriptions and
                detected links. Combined datasets built from it are kept.
              </p>
              <p className="mt-2 font-medium">This cannot be undone.</p>
            </ConfirmDialog>
          ) : null}
        </div>
        <p className="lead mt-2 max-w-3xl">
          Profile of table <code>{dataset.table_name}</code>. Every number on
          this page comes from a SQL query over the data; associations use a
          fixed sample on large tables.
        </p>
      </div>

      {dataset.status !== "ready" ? (
        <p className="text-muted">
          This dataset is {dataset.status}. The profile appears when it is
          ready.
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            {tiles.map(([label, value]) => (
              <div key={label} className="card p-4">
                <dt className="text-muted text-xs font-medium">{label}</dt>
                <dd className="mt-1 truncate text-xl font-semibold tracking-tight tabular-nums">
                  {value}
                </dd>
              </div>
            ))}
          </dl>

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="section-title">Warnings</h2>
              {SEVERITY_ORDER.map((s) => {
                const n = warnings.filter((w) => w.severity === s).length;
                return n ? (
                  <SeverityBadge key={s} severity={s} count={n} />
                ) : null;
              })}
            </div>
            {warnings.length === 0 ? (
              <p className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-300">
                <CircleCheck className="h-4 w-4" aria-hidden />
                No data-quality warnings for this table.
              </p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {[...warnings]
                  .sort(
                    (a, b) =>
                      SEVERITY_ORDER.indexOf(a.severity) -
                      SEVERITY_ORDER.indexOf(b.severity),
                  )
                  .map((w, i) => (
                    <li
                      key={i}
                      className={`rounded-md border px-3 py-2 text-sm ${SEVERITY_STYLE[w.severity].className}`}
                    >
                      <span aria-hidden>
                        {SEVERITY_STYLE[w.severity].icon}{" "}
                      </span>
                      <span className="sr-only">
                        {SEVERITY_STYLE[w.severity].label}:{" "}
                      </span>
                      {w.message}
                    </li>
                  ))}
              </ul>
            )}
          </section>

          {table?.relationships && (
            <>
              <Associations
                data={table.relationships}
                label={(n) => original.get(n) ?? n}
              />
              <MissingPatterns
                data={table.relationships}
                label={(n) => original.get(n) ?? n}
              />
            </>
          )}

          <section className="flex flex-col gap-3">
            <h2 className="section-title">
              Columns{" "}
              <span className="text-subtle text-sm font-normal">
                (click a row for details; click a header to sort)
              </span>
            </h2>
            <DescribeStatus
              status={dataset.describe_status}
              error={dataset.describe_error}
              retry={redescribe.bind(null, Number(id), Number(datasetId))}
            />
            <DictionaryUpload
              projectId={Number(id)}
              datasetId={Number(datasetId)}
            />
            <ColumnsTable
              columns={columns}
              warnings={warnings}
              projectId={Number(id)}
              datasetId={Number(datasetId)}
            />
          </section>
        </>
      )}
    </div>
  );
}

function DescribeStatus({
  status,
  error,
  retry,
}: {
  status: string | null;
  error: string | null;
  retry: () => Promise<void>;
}) {
  if (status === "pending" || status === "running") {
    return (
      <p className="text-muted animate-pulse text-sm">
        Writing column descriptions with AI…
      </p>
    );
  }
  if (status === "failed" || status === "skipped") {
    return (
      <form
        action={retry}
        className="flex flex-wrap items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
      >
        <span>
          <span aria-hidden>⚠ </span>
          AI descriptions {status === "failed" ? "failed" : "were skipped"}
          {error ? `: ${error.slice(0, 200)}` : "."}
        </span>
        <button className="rounded-md border border-amber-300 px-2 py-1 text-xs font-medium hover:bg-amber-100 dark:border-amber-800 dark:hover:bg-amber-900/40">
          Try again
        </button>
      </form>
    );
  }
  return null;
}
