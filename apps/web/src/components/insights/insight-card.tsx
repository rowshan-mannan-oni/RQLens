import { AnswerChart } from "@/components/chat/answer-chart";
import { formatInt } from "@/lib/format";
import type { Insight, RQQuery } from "@/lib/types";

const STATUS: Record<string, { label: string; cls: string }> = {
  finding: {
    label: "Exploratory finding",
    cls: "bg-sky-50 text-sky-800 dark:bg-sky-950/40 dark:text-sky-300",
  },
  weak: {
    label: "Significant but negligible",
    cls: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  },
  no_evidence: {
    label: "No clear evidence",
    cls: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  },
};

function num(v: number | null | undefined, digits = 3): string {
  if (v == null) return "–";
  if (v !== 0 && Math.abs(v) < 0.001) return v.toExponential(1);
  return Number(v.toPrecision(digits)).toString();
}

export function InsightCard({
  insight,
  rqText,
  rank,
}: {
  insight: Insight;
  rqText: string | null;
  rank: number;
}) {
  const s = STATUS[insight.status ?? ""] ?? STATUS.finding;
  const r = insight.result ?? {};
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <header className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-zinc-500">#{rank}</span>
          <span className={`rounded-full px-2 py-0.5 font-medium ${s.cls}`}>
            {s.label}
          </span>
          {r.magnitude && insight.status !== "no_evidence" && (
            <span className="text-zinc-500">{r.magnitude} effect</span>
          )}
          {rqText && (
            <span className="truncate text-zinc-500" title={rqText}>
              · RQ: {rqText}
            </span>
          )}
        </div>
        <h3 className="font-medium">{insight.title}</h3>
      </header>

      <p className="text-sm">{insight.statement}</p>
      {insight.grounding && !insight.grounding.ok && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <span className="font-medium">Check these numbers:</span>{" "}
          {insight.grounding.unsupported.join(", ")} do not appear in the test
          result.
        </p>
      )}

      {insight.chart && insight.chart.data.length > 0 && (
        <AnswerChart chart={insight.chart} />
      )}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <Stat label="Test" value={r.test?.replaceAll("_", " ") ?? "–"} />
        <Stat
          label={r.effect_size_name?.replaceAll("_", " ") ?? "Effect size"}
          value={num(insight.effect_size)}
        />
        <Stat
          label="p (adjusted)"
          value={`${num(insight.p_value, 2)} (${num(insight.p_adjusted, 2)})`}
        />
        <Stat label="n" value={r.n != null ? formatInt(r.n) : "–"} />
      </dl>

      {insight.caveats.length > 0 && (
        <ul className="ml-5 list-disc text-xs text-zinc-600 dark:text-zinc-400">
          {insight.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}

      {(r.confounders?.length ?? 0) > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">
            Confounder check
          </summary>
          <ul className="mt-1 ml-5 list-disc">
            {r.confounders!.map((c) => (
              <li key={c.column}>
                Within groups of <code>{c.column}</code> the pattern{" "}
                <span className="font-medium">{c.verdict}</span>:{" "}
                {c.strata
                  .map((st) => `${st.value} ${num(st.effect, 2)} (n ${st.n})`)
                  .join(", ")}
              </li>
            ))}
          </ul>
        </details>
      )}

      {insight.queries.length > 0 && <Queries queries={insight.queries} />}
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-zinc-500">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  );
}

export function Queries({ queries }: { queries: RQQuery[] }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">
        How this was computed · {queries.length} quer
        {queries.length === 1 ? "y" : "ies"}
      </summary>
      <ol className="mt-1 flex flex-col gap-2">
        {queries.map((q) => (
          <li key={q.id}>
            <p className="text-zinc-500">
              Query #{q.id}
              {q.duration_ms != null && <> · {q.duration_ms} ms</>}
              {q.row_count != null && <> · {formatInt(q.row_count)} rows</>}
            </p>
            <pre className="mt-1 overflow-x-auto rounded bg-zinc-50 p-2 whitespace-pre-wrap dark:bg-zinc-900">
              {q.sql}
            </pre>
          </li>
        ))}
      </ol>
    </details>
  );
}
