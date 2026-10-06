import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { ColumnsTable } from "@/components/profile/columns-table";
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
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-10">
      <div>
        <Link
          href={`/projects/${id}`}
          className="text-sm text-zinc-500 hover:underline"
        >
          ← Project
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {dataset.original_filename}
        </h1>
        <p className="text-sm text-zinc-500">
          Profile of table <code>{dataset.table_name}</code>. Every number on
          this page comes from a SQL query over the full dataset.
        </p>
      </div>

      {dataset.status !== "ready" ? (
        <p className="text-zinc-600 dark:text-zinc-400">
          This dataset is {dataset.status}. The profile appears when it is
          ready.
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {tiles.map(([label, value]) => (
              <div
                key={label}
                className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
              >
                <dt className="text-xs text-zinc-500">{label}</dt>
                <dd className="mt-1 truncate text-lg font-semibold tabular-nums">
                  {value}
                </dd>
              </div>
            ))}
          </dl>

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-medium">Warnings</h2>
              {SEVERITY_ORDER.map((s) => {
                const n = warnings.filter((w) => w.severity === s).length;
                return n ? (
                  <SeverityBadge key={s} severity={s} count={n} />
                ) : null;
              })}
            </div>
            {warnings.length === 0 ? (
              <p className="text-zinc-600 dark:text-zinc-400">No warnings.</p>
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
            <h2 className="font-medium">
              Columns{" "}
              <span className="text-sm font-normal text-zinc-500">
                (click a row for details; click a header to sort)
              </span>
            </h2>
            <ColumnsTable columns={columns} warnings={warnings} />
          </section>
        </>
      )}
    </main>
  );
}
