import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { CombineForm } from "@/components/combine-form";
import { ApiError, apiFetch } from "@/lib/api";
import { formatInt, formatNum, formatPct } from "@/lib/format";
import type { CompareResponse, ComparisonCell } from "@/lib/types";

const KIND: Record<string, string> = {
  numeric: "number",
  text: "text",
  datetime: "date",
  boolean: "yes/no",
};

const ISSUE_LABEL: Record<string, string> = {
  type_mismatch: "type differs",
  scale_mismatch: "scale differs",
  category_mismatch: "categories differ",
  missing_gap: "missingness differs",
};

function Cell({ cell }: { cell?: ComparisonCell }) {
  if (!cell) return <span className="text-zinc-400">not in file</span>;
  return (
    <span className="flex flex-col">
      <span>
        {KIND[cell.kind ?? ""] ?? cell.kind}
        {cell.semantic_type && cell.semantic_type !== cell.kind && (
          <span className="text-zinc-500"> · {cell.semantic_type}</span>
        )}
      </span>
      <span className="text-xs text-zinc-500 tabular-nums">
        {formatPct(cell.missing_pct, 0)} missing
        {cell.median != null && ` · median ${formatNum(cell.median)}`}
      </span>
    </span>
  );
}

export default async function ComparePage(
  props: PageProps<"/projects/[id]/compare">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id } = await props.params;
  const { ids } = await props.searchParams;
  const selection = typeof ids === "string" ? ids : "";
  if (!/^\d+(,\d+)*$/.test(selection)) notFound();

  let data: CompareResponse;
  try {
    data = await apiFetch<CompareResponse>(
      `/projects/${id}/compare?ids=${selection}`,
    );
  } catch (e) {
    if (e instanceof ApiError && [404, 409, 422].includes(e.status)) notFound();
    throw e;
  }
  const { comparison: c, links } = data;
  const totalRows = c.tables.reduce((n, t) => n + t.row_count, 0);
  const columnsByTable: Record<number, { name: string; label: string }[]> =
    Object.fromEntries(
      c.tables.map((t) => [
        t.dataset_id,
        c.columns
          .filter((col) => col.cells[String(t.dataset_id)])
          .map((col) => ({
            name: col.cells[String(t.dataset_id)].name,
            label: col.cells[String(t.dataset_id)].original_name,
          })),
      ]),
    );

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-10">
      <div>
        <Link
          href={`/projects/${id}`}
          className="text-sm text-zinc-500 hover:underline"
        >
          ← Project
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          Compare {c.tables.length} dataset{c.tables.length === 1 ? "" : "s"}
        </h1>
        <p className="text-sm text-zinc-500">
          {c.tables.map((t) => t.label).join(" · ")}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Files", formatInt(c.tables.length)],
          ["Rows in total", formatInt(totalRows)],
          [
            "Columns in every file",
            `${formatInt(c.shared_columns)} of ${formatInt(c.total_columns)}`,
          ],
          ["Mismatches", formatInt(c.issues.length)],
        ].map(([label, value]) => (
          <div
            key={label}
            className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
          >
            <dt className="text-xs text-zinc-500">{label}</dt>
            <dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      {c.issues.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="font-medium">Differences between files</h2>
          <ul className="flex flex-col gap-1.5">
            {c.issues.map((i) => (
              <li
                key={`${i.code}-${i.column}`}
                className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
              >
                <span aria-hidden>⚠ </span>
                <span className="sr-only">Warning: </span>
                {i.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      {c.tables.length > 1 && (
        <section className="flex flex-col gap-2">
          <h2 className="font-medium">How the files link</h2>
          {links.length === 0 ? (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              No shared key columns were detected between these files.
            </p>
          ) : (
            <ul className="flex flex-col gap-1 text-sm">
              {links.map((l) => (
                <li key={l.id}>
                  {l.left.filename} ·{" "}
                  <span className="font-medium">{l.left.column_label}</span> ↔{" "}
                  {l.right.filename} ·{" "}
                  <span className="font-medium">{l.right.column_label}</span>{" "}
                  <span className="text-zinc-500">
                    ({l.cardinality}, {formatInt(l.shared_values)} shared
                    values)
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="font-medium">Columns across files</h2>
        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-50 text-left text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">
                  Column
                </th>
                {c.tables.map((t) => (
                  <th
                    key={t.dataset_id}
                    scope="col"
                    className="px-3 py-2 font-medium"
                  >
                    {t.label}
                    <span className="block font-normal">
                      {formatInt(t.row_count)} rows
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {c.columns.map((col) => (
                <tr key={col.key}>
                  <th scope="row" className="px-3 py-2 text-left font-medium">
                    {col.label}
                    {col.issues.map((code) => (
                      <span
                        key={code}
                        className="ml-2 rounded-full border border-amber-300 px-1.5 py-0.5 text-xs font-normal text-amber-800 dark:border-amber-800 dark:text-amber-300"
                      >
                        ⚠ {ISSUE_LABEL[code] ?? code}
                      </span>
                    ))}
                  </th>
                  {c.tables.map((t) => (
                    <td key={t.dataset_id} className="px-3 py-2 align-top">
                      <Cell cell={col.cells[String(t.dataset_id)]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {c.tables.length > 1 ? (
        <CombineForm
          projectId={Number(id)}
          tables={c.tables.map((t) => ({ id: t.dataset_id, label: t.label }))}
          columns={columnsByTable}
          links={links}
          stackable={c.stackable}
        />
      ) : (
        <p className="text-sm text-zinc-500">
          Select at least two datasets on the project page to combine them.
        </p>
      )}
    </main>
  );
}
