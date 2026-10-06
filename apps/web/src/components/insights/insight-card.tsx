import { ChartColumn } from "lucide-react";

import { AnswerChart } from "@/components/chat/answer-chart";
import { formatInt } from "@/lib/format";
import type { Insight, RQQuery } from "@/lib/types";

const STATUS: Record<string, { label: string; cls: string }> = {
  finding: {
    label: "Exploratory finding",
    cls: "badge-brand",
  },
  weak: {
    label: "Significant but negligible",
    cls: "badge-neutral",
  },
  no_evidence: {
    label: "No clear evidence",
    cls: "badge-neutral",
  },
};

const TEST_LABEL: Record<string, string> = {
  spearman: "Spearman correlation",
  mann_whitney: "Mann-Whitney U",
  kruskal_wallis: "Kruskal-Wallis",
  chi_square: "Chi-square",
  trend: "Mann-Kendall trend",
};

const EFFECT_LABEL: Record<string, string> = {
  rho: "Spearman's rho",
  tau: "Kendall's tau",
  rank_biserial: "Rank-biserial r",
  cramers_v: "Cramér's V",
  epsilon_squared: "Epsilon squared",
};

function pText(p: number | null | undefined): string {
  if (p == null) return "–";
  return p < 0.001 ? "< 0.001" : Number(p.toPrecision(2)).toString();
}

function num(v: number | null | undefined, digits = 3): string {
  if (v == null) return "–";
  if (v !== 0 && Math.abs(v) < 0.001) return v.toExponential(1);
  return Number(v.toPrecision(digits)).toString();
}

export function InsightCard({
  insight,
  rqText,
  rank,
  chartOpen = true,
}: {
  insight: Insight;
  rqText: string | null;
  rank: number;
  chartOpen?: boolean;
}) {
  const s = STATUS[insight.status ?? ""] ?? STATUS.finding;
  const r = insight.result ?? {};
  return (
    <article className="card flex flex-col gap-4 p-5">
      <header className="flex items-start gap-3">
        <span className="bg-surface-3 text-muted grid h-8 w-8 shrink-0 place-items-center rounded-lg text-sm font-semibold tabular-nums">
          {rank}
        </span>
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`badge ${s.cls}`}>{s.label}</span>
            {r.magnitude && insight.status !== "no_evidence" && (
              <span className="badge badge-neutral">{r.magnitude} effect</span>
            )}
          </div>
          <h3 className="text-base font-semibold tracking-tight">
            {insight.title}
          </h3>
          {rqText && (
            <p className="text-subtle truncate text-xs" title={rqText}>
              Research question: {rqText}
            </p>
          )}
        </div>
      </header>

      <p className="text-sm leading-relaxed">{insight.statement}</p>
      {insight.grounding && !insight.grounding.ok && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <span className="font-medium">Check these numbers:</span>{" "}
          {insight.grounding.unsupported.join(", ")} do not appear in the test
          result.
        </p>
      )}

      {insight.chart &&
        insight.chart.data.length > 0 &&
        (chartOpen ? (
          <AnswerChart chart={insight.chart} />
        ) : (
          <details className="group">
            <summary className="text-muted hover:text-fg flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium select-none">
              <ChartColumn className="h-3.5 w-3.5" aria-hidden />
              <span className="group-open:hidden">Show chart</span>
              <span className="hidden group-open:inline">Hide chart</span>
            </summary>
            <div className="mt-3">
              <AnswerChart chart={insight.chart} />
            </div>
          </details>
        ))}

      <dl className="bg-surface-2 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg p-3 text-xs sm:grid-cols-4">
        <Stat label="Test" value={TEST_LABEL[r.test ?? ""] ?? r.test ?? "–"} />
        <Stat
          label={EFFECT_LABEL[r.effect_size_name ?? ""] ?? "Effect size"}
          value={num(insight.effect_size)}
          mono
        />
        <Stat
          label="Adjusted p"
          value={pText(insight.p_adjusted)}
          title={`Raw p = ${num(insight.p_value, 2)}; adjusted for multiple testing (Benjamini-Hochberg).`}
          mono
        />
        <Stat label="n" value={r.n != null ? formatInt(r.n) : "–"} mono />
      </dl>

      {insight.caveats.length > 0 && (
        <ul className="text-muted ml-5 list-disc text-xs">
          {insight.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}

      {(r.confounders?.length ?? 0) > 0 && (
        <details className="text-xs">
          <summary className="text-muted cursor-pointer">
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

function Stat({
  label,
  value,
  mono,
  title,
}: {
  label: string;
  value: string;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div title={title}>
      <dt className="text-subtle">{label}</dt>
      <dd
        className={`text-fg mt-0.5 text-sm font-medium ${mono ? "tabular-nums" : ""}`}
      >
        {value}
      </dd>
    </div>
  );
}

export function Queries({ queries }: { queries: RQQuery[] }) {
  return (
    <details className="text-xs">
      <summary className="text-muted cursor-pointer">
        How this was computed · {queries.length} quer
        {queries.length === 1 ? "y" : "ies"}
      </summary>
      <ol className="mt-1 flex flex-col gap-2">
        {queries.map((q) => (
          <li key={q.id}>
            <p className="text-subtle">
              Query #{q.id}
              {q.duration_ms != null && <> · {q.duration_ms} ms</>}
              {q.row_count != null && <> · {formatInt(q.row_count)} rows</>}
            </p>
            <pre className="code-block mt-1">{q.sql}</pre>
          </li>
        ))}
      </ol>
    </details>
  );
}
