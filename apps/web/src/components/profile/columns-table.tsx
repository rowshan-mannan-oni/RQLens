"use client";

import { Fragment, useMemo, useState } from "react";

import { formatInt, formatNum, formatPct } from "@/lib/format";
import type { Column, ColumnProfile, DataWarning, Severity } from "@/lib/types";

import { Histogram, PeriodChart, TopValuesChart } from "./charts";
import { DescriptionEditor, DescriptionLabel } from "./description";
import { SEVERITY_ORDER, SEVERITY_STYLE, SeverityBadge } from "./severity";

type SortKey = "position" | "name" | "type" | "missing" | "distinct" | "issues";

type Row = {
  position: number;
  column: Column;
  profile: ColumnProfile | null;
  warnings: DataWarning[];
  worst: Severity | null;
};

const SEVERITY_RANK: Record<Severity, number> = {
  severe: 3,
  warning: 2,
  info: 1,
};

export function ColumnsTable({
  columns,
  warnings,
  projectId,
  datasetId,
}: {
  columns: Column[];
  warnings: DataWarning[];
  projectId: number;
  datasetId: number;
}) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
    key: "position",
    desc: false,
  });
  const [open, setOpen] = useState<string | null>(null);

  const rows = useMemo<Row[]>(
    () =>
      columns.map((column, position) => {
        const own = warnings.filter((w) => w.column === column.name);
        const worst =
          SEVERITY_ORDER.find((s) => own.some((w) => w.severity === s)) ?? null;
        return {
          position,
          column,
          profile: column.profile_json,
          warnings: own,
          worst,
        };
      }),
    [columns, warnings],
  );

  const sorted = useMemo(() => {
    const value = (r: Row): number | string => {
      switch (sort.key) {
        case "name":
          return (r.column.original_name ?? r.column.name).toLowerCase();
        case "type":
          return r.column.semantic_type ?? "";
        case "missing":
          return r.profile?.missing_pct ?? 0;
        case "distinct":
          return r.profile?.distinct ?? 0;
        case "issues":
          return (
            (r.worst ? SEVERITY_RANK[r.worst] * 1000 : 0) + r.warnings.length
          );
        default:
          return r.position;
      }
    };
    return [...rows].sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      const cmp = x < y ? -1 : x > y ? 1 : a.position - b.position;
      return sort.desc ? -cmp : cmp;
    });
  }, [rows, sort]);

  function header(key: SortKey, label: string, align = "text-left") {
    const active = sort.key === key;
    return (
      <th
        scope="col"
        aria-sort={
          active ? (sort.desc ? "descending" : "ascending") : undefined
        }
        className={`px-3 py-2 font-medium ${align}`}
      >
        <button
          onClick={() =>
            setSort({
              key,
              desc: active ? !sort.desc : key !== "position" && key !== "name",
            })
          }
          className="hover:underline"
        >
          {label}
          {active ? (sort.desc ? " ↓" : " ↑") : ""}
        </button>
      </th>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-sm">
        <thead className="border-b border-zinc-200 bg-zinc-50 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            {header("position", "#")}
            {header("name", "Column")}
            {header("type", "Type")}
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Description
            </th>
            {header("missing", "Missing", "text-right")}
            {header("distinct", "Distinct", "text-right")}
            {header("issues", "Issues")}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {sorted.map((r) => {
            const isOpen = open === r.column.name;
            return (
              <Fragment key={r.column.id}>
                <tr
                  onClick={() => setOpen(isOpen ? null : r.column.name)}
                  className="cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900"
                  aria-expanded={isOpen}
                >
                  <td className="px-3 py-2 text-zinc-500 tabular-nums">
                    {r.position + 1}
                  </td>
                  <td className="px-3 py-2">
                    <span className="font-medium">
                      {r.column.original_name ?? r.column.name}
                    </span>
                    <span className="ml-2 font-mono text-xs text-zinc-500">
                      {r.column.physical_type.toLowerCase()}
                    </span>
                    {r.column.is_pii && (
                      <span
                        className="ml-2 rounded-full border border-violet-300 bg-violet-50 px-1.5 py-0.5 text-xs text-violet-900 dark:border-violet-800 dark:bg-violet-950/50 dark:text-violet-200"
                        title={r.column.pii_reason ?? undefined}
                      >
                        Personal data
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">{r.column.semantic_type}</td>
                  <td className="max-w-xs px-3 py-2">
                    <DescriptionLabel column={r.column} compact />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatPct(r.profile?.missing_pct)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatInt(r.profile?.distinct)}
                  </td>
                  <td className="px-3 py-2">
                    {r.worst && (
                      <SeverityBadge
                        severity={r.worst}
                        count={r.warnings.length}
                      />
                    )}
                  </td>
                </tr>
                {isOpen && r.profile && (
                  <tr>
                    <td
                      colSpan={7}
                      className="bg-zinc-50/60 px-3 py-4 dark:bg-zinc-900/40"
                    >
                      <ColumnDetail
                        column={r.column}
                        profile={r.profile}
                        warnings={r.warnings}
                        projectId={projectId}
                        datasetId={datasetId}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function ColumnDetail({
  column,
  profile: p,
  warnings,
  projectId,
  datasetId,
}: {
  column: Column;
  profile: ColumnProfile;
  warnings: DataWarning[];
  projectId: number;
  datasetId: number;
}) {
  const stats: [string, string][] = [
    ["Rows", formatInt(p.count)],
    ["Missing", `${formatInt(p.missing)} (${formatPct(p.missing_pct)})`],
    ["Distinct", formatInt(p.distinct)],
    ["Uniqueness", formatPct(p.uniqueness)],
  ];
  if (p.numeric?.finite) {
    const n = p.numeric;
    stats.push(
      ["Min", formatNum(n.min)],
      ["Median", formatNum(n.median)],
      ["Mean", formatNum(n.mean)],
      ["Max", formatNum(n.max)],
      ["Std dev", formatNum(n.std)],
      ["Skew", formatNum(n.skew)],
      [
        "P5 – P95",
        `${formatNum(n.quantiles.p05)} – ${formatNum(n.quantiles.p95)}`,
      ],
      ["Outliers (IQR)", formatInt(n.outliers)],
      ["Zeros", formatInt(n.zeros)],
      ["Negatives", formatInt(n.negatives)],
    );
  }
  if (p.datetime) {
    stats.push(
      ["From", p.datetime.min.slice(0, 10)],
      ["To", p.datetime.max.slice(0, 10)],
      ["Granularity", p.datetime.granularity],
      ["Empty periods", formatInt(p.datetime.empty_periods)],
    );
  }
  if (p.text) {
    stats.push(
      [
        "Length (min / avg / max)",
        `${p.text.min_length} / ${formatNum(p.text.avg_length)} / ${p.text.max_length}`,
      ],
      ["Avg words", formatNum(p.text.avg_words)],
    );
  }
  if (p.categorical) {
    stats.push(
      ["Rare categories (<1%)", formatInt(p.categorical.rare_categories)],
      [
        "Largest / smallest group",
        `${formatNum(p.categorical.imbalance_ratio)}×`,
      ],
    );
  }

  const showTop =
    p.top_values?.length &&
    (p.semantic_type === "categorical" ||
      p.semantic_type === "boolean" ||
      !p.numeric);

  return (
    <div className="flex flex-col gap-4">
      <DescriptionEditor
        key={`${column.id}-${column.description ?? ""}`}
        column={column}
        projectId={projectId}
        datasetId={datasetId}
      />
      {column.is_pii && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Treated as personal data ({column.pii_reason}). Its values are never
          sent to the AI.
        </p>
      )}
      {warnings.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {warnings.map((w, i) => (
            <li
              key={i}
              className={`rounded-md border px-2.5 py-1.5 text-sm ${SEVERITY_STYLE[w.severity].className}`}
            >
              <span aria-hidden>{SEVERITY_STYLE[w.severity].icon} </span>
              <span className="sr-only">
                {SEVERITY_STYLE[w.severity].label}:{" "}
              </span>
              {w.message}
            </li>
          ))}
        </ul>
      )}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        {stats.map(([label, value]) => (
          <Stat key={label} label={label} value={value} />
        ))}
      </dl>
      {p.numeric?.histogram && p.semantic_type !== "categorical" && (
        <figure>
          <figcaption className="mb-1 text-xs text-zinc-500">
            Distribution ({p.numeric.histogram.length} equal-width bins)
          </figcaption>
          <Histogram bins={p.numeric.histogram} total={p.numeric.finite} />
        </figure>
      )}
      {p.datetime && p.datetime.counts.length > 1 && (
        <figure>
          <figcaption className="mb-1 text-xs text-zinc-500">
            Rows per {p.datetime.period}
          </figcaption>
          <PeriodChart counts={p.datetime.counts} period={p.datetime.period} />
        </figure>
      )}
      {showTop && p.top_values && (
        <figure>
          <figcaption className="mb-1 text-xs text-zinc-500">
            Most common values (share of non-missing rows)
          </figcaption>
          <TopValuesChart values={p.top_values} />
        </figure>
      )}
      {p.text && p.semantic_type !== "categorical" && (
        <div>
          <p className="text-xs text-zinc-500">Sample values</p>
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {p.text.samples.map((s) => (
              <li key={s} className="truncate font-mono text-xs">
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
