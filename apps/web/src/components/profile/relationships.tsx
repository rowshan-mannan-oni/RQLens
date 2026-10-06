import { formatInt, formatNum, formatPct } from "@/lib/format";
import type { Association, TableRelationships } from "@/lib/types";

const MEASURE: Record<Association["measure"], { label: string; help: string }> =
  {
    spearman: {
      label: "Spearman ρ",
      help: "rank correlation of two numeric columns, −1 to 1",
    },
    cramers_v: {
      label: "Cramér's V",
      help: "association of two categorical columns, 0 to 1",
    },
    eta: {
      label: "η",
      help: "how much a category explains a numeric column, 0 to 1",
    },
  };

const SHOWN = 15;

/** Inline magnitude bar: one series colour, rounded data end, value in text colour. */
function StrengthBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="bg-surface-3 h-2 w-28 shrink-0 rounded-sm">
        <div
          className="h-full rounded-r-[4px]"
          style={{
            width: `${Math.min(Math.abs(value), 1) * 100}%`,
            background: "var(--chart-1)",
          }}
        />
      </div>
      <span className="tabular-nums">
        {value < 0 ? "−" : ""}
        {Math.abs(value).toFixed(2)}
      </span>
    </div>
  );
}

export function Associations({
  data,
  label,
}: {
  data: TableRelationships;
  label: (name: string) => string;
}) {
  const rows = data.associations.slice(0, SHOWN);
  const truncated = Object.entries(data.truncated);
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="section-title">Strongest associations</h2>
        <p className="text-subtle text-sm">
          Exploratory: strong associations can come from chance, shared causes,
          or one column being derived from another. Computed on{" "}
          {formatInt(data.sample_rows)} rows
          {data.sample_rows < 50000 ? " (all rows)" : " (a fixed sample)"}.
        </p>
      </div>
      {rows.length === 0 ? (
        <p className="text-muted">
          No associations of 0.1 or more between analysable columns.
        </p>
      ) : (
        <div className="border-line overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="border-line bg-surface-2 text-muted border-b text-left text-xs">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">
                  Columns
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Measure
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Strength
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  Rows used
                </th>
              </tr>
            </thead>
            <tbody className="divide-line divide-y">
              {rows.map((r) => (
                <tr key={`${r.a}|${r.b}|${r.measure}`}>
                  <td className="px-3 py-2">
                    <span className="font-medium">{label(r.a)}</span>
                    <span className="text-subtle"> × </span>
                    <span className="font-medium">{label(r.b)}</span>
                  </td>
                  <td
                    className="text-muted px-3 py-2"
                    title={MEASURE[r.measure].help}
                  >
                    {MEASURE[r.measure].label}
                  </td>
                  <td className="px-3 py-2">
                    <StrengthBar value={r.value} />
                  </td>
                  <td className="text-muted px-3 py-2 text-right tabular-nums">
                    {formatInt(r.n)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-subtle text-xs">
        {Object.values(MEASURE)
          .map((m) => `${m.label}: ${m.help}`)
          .join(" · ")}
        {truncated.length > 0 &&
          ` · Wide table: ${truncated.map(([k, n]) => `${n} ${k} columns`).join(", ")} were left out.`}
      </p>
    </section>
  );
}

export function MissingPatterns({
  data,
  label,
}: {
  data: TableRelationships;
  label: (name: string) => string;
}) {
  const { co_missing, dependencies } = data.missingness;
  if (co_missing.length === 0 && dependencies.length === 0) {
    return (
      <section className="flex flex-col gap-2">
        <h2 className="section-title">Missing-data patterns</h2>
        <p className="text-muted">
          No columns are missing together, and no missingness depends clearly on
          another column.
        </p>
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="section-title">Missing-data patterns</h2>
        <p className="text-subtle text-sm">
          Missing values that follow a pattern can bias any analysis that drops
          incomplete rows.
        </p>
      </div>
      {dependencies.length > 0 && (
        <div>
          <h3 className="text-sm font-medium">
            Missingness that depends on another column
          </h3>
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {dependencies.slice(0, 10).map((d) => (
              <li key={`${d.column}|${d.by}`}>
                <span className="font-medium">{label(d.column)}</span>{" "}
                {d.kind === "categorical" ? (
                  <>
                    is missing in {formatPct(d.highest.rate, 0)} of rows where{" "}
                    <span className="font-medium">{label(d.by)}</span> is “
                    {d.highest.value}” vs {formatPct(d.lowest.rate, 0)} where it
                    is “{d.lowest.value}” (V = {formatNum(d.strength)})
                  </>
                ) : (
                  <>
                    is missing in rows with {d.smd > 0 ? "higher" : "lower"}{" "}
                    <span className="font-medium">{label(d.by)}</span> (mean{" "}
                    {formatNum(d.mean_when_missing)} vs{" "}
                    {formatNum(d.mean_when_present)})
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {co_missing.length > 0 && (
        <div>
          <h3 className="text-sm font-medium">Columns missing together</h3>
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {co_missing.slice(0, 10).map((c) => (
              <li key={`${c.a}|${c.b}`}>
                <span className="font-medium">{label(c.a)}</span> and{" "}
                <span className="font-medium">{label(c.b)}</span>: both missing
                in {formatInt(c.both_missing)} sampled rows (φ ={" "}
                {formatNum(c.phi)})
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
