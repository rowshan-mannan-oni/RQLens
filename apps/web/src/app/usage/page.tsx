import { Activity, Coins, Database, Gauge, Timer } from "lucide-react";
import Link from "next/link";

import { apiFetch } from "@/lib/api";
import { formatInt } from "@/lib/format";
import type { Usage } from "@/lib/types";

const STEP_LABEL: Record<string, string> = {
  chat_agent: "Chat",
  describe_columns: "Column descriptions",
  column_retrieval: "Column search (embeddings)",
  rq_parse: "RQ parsing",
  rq_map: "RQ mapping",
  rq_explain: "RQ explanation",
  rq_suggest: "RQ suggestions",
  insights_plan: "Insight planning",
  insights_write: "Insight wording",
};

function usd(v: string | number): string {
  const n = Number(v);
  return n === 0 ? "$0" : n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
}

function ms(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`;
}

export default async function UsagePage(props: PageProps<"/usage">) {
  const { period } = await props.searchParams;
  const p = period === "all" ? "all" : "month";
  const u = await apiFetch<Usage>(`/usage?period=${p}`);
  const totalCalls = u.projects.reduce((n, x) => n + x.calls, 0);
  const totalCost = u.projects.reduce((n, x) => n + Number(x.cost_usd), 0);
  const totalQueries = u.projects.reduce((n, x) => n + x.queries, 0);
  const callShare = u.call_limit
    ? Math.min(1, u.month_calls / u.call_limit)
    : 0;
  const costShare = u.budget_usd
    ? Math.min(1, Number(u.month_cost_usd) / u.budget_usd)
    : 0;
  const resets = new Date(u.resets_on).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
  });

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-10 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Usage and limits
          </h1>
          <p className="lead mt-1">
            AI calls, cost and latency per project. Every AI call is logged,
            including failed ones.
          </p>
        </div>
        <nav
          aria-label="Period"
          className="border-line bg-surface flex rounded-lg border p-0.5 text-sm"
        >
          {(["month", "all"] as const).map((v) => (
            <Link
              key={v}
              href={`/usage?period=${v}`}
              aria-current={p === v ? "page" : undefined}
              className="text-muted aria-[current=page]:bg-brand-soft aria-[current=page]:text-brand-fg rounded-md px-3 py-1.5 aria-[current=page]:font-medium"
            >
              {v === "month" ? "This month" : "All time"}
            </Link>
          ))}
        </nav>
      </div>

      <section className="grid gap-4 md:grid-cols-2">
        <Meter
          icon={Gauge}
          label="AI calls this month"
          value={`${formatInt(u.month_calls)}${u.call_limit ? ` of ${formatInt(u.call_limit)}` : ""}`}
          share={callShare}
          note={
            u.call_limit
              ? `Resets on ${resets}.`
              : "No monthly call limit is set."
          }
        />
        <Meter
          icon={Coins}
          label="AI spend this month"
          value={`${usd(u.month_cost_usd)}${u.budget_usd ? ` of ${usd(u.budget_usd)}` : ""}`}
          share={costShare}
          note="Models without prices in LLM_PRICES count as free."
        />
      </section>

      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile icon={Activity} label="AI calls" value={formatInt(totalCalls)} />
        <Tile icon={Coins} label="AI cost" value={usd(totalCost)} />
        <Tile
          icon={Database}
          label="Queries run"
          value={formatInt(totalQueries)}
        />
        <Tile
          icon={Timer}
          label="Limits"
          value={`${u.limits.projects} projects`}
          note={`${u.limits.datasets_per_project} datasets each · ${formatInt(u.limits.upload_mb)} MB per file`}
        />
      </dl>

      <section className="flex flex-col gap-3">
        <h2 className="section-title">By project</h2>
        {u.projects.length === 0 ? (
          <p className="text-muted text-sm">No projects yet.</p>
        ) : (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-subtle text-left text-xs">
                <tr className="border-line border-b">
                  <th className="px-4 py-2.5 font-medium">Project</th>
                  <th className="px-3 py-2.5 text-right font-medium">
                    AI calls
                  </th>
                  <th className="px-3 py-2.5 text-right font-medium">Tokens</th>
                  <th className="px-3 py-2.5 text-right font-medium">Cost</th>
                  <th className="px-3 py-2.5 text-right font-medium">
                    Latency (avg / p95)
                  </th>
                  <th className="px-3 py-2.5 text-right font-medium">
                    Queries
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    Where the calls went
                  </th>
                </tr>
              </thead>
              <tbody className="divide-line divide-y">
                {u.projects.map((x) => (
                  <tr key={x.project_id} className="align-top">
                    <td className="px-4 py-3">
                      <Link
                        href={`/projects/${x.project_id}`}
                        className="hover:text-brand-fg dark:hover:text-brand font-medium"
                      >
                        {x.title}
                      </Link>
                      {x.failed_calls > 0 && (
                        <p className="mt-0.5 text-xs text-red-600 dark:text-red-400">
                          {x.failed_calls} failed
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">
                      {formatInt(x.calls)}
                    </td>
                    <td className="text-muted px-3 py-3 text-right tabular-nums">
                      {formatInt(x.input_tokens + x.output_tokens)}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">
                      {usd(x.cost_usd)}
                    </td>
                    <td className="text-muted px-3 py-3 text-right tabular-nums">
                      {x.calls
                        ? `${ms(x.avg_latency_ms)} / ${ms(x.p95_latency_ms)}`
                        : "–"}
                    </td>
                    <td className="text-muted px-3 py-3 text-right tabular-nums">
                      {formatInt(x.queries)}
                      {x.queries > 0 && (
                        <span className="text-subtle block text-xs">
                          avg {ms(x.avg_query_ms)}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <StepBars steps={x.steps} total={x.calls} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

function Meter({
  icon: Icon,
  label,
  value,
  share,
  note,
}: {
  icon: typeof Gauge;
  label: string;
  value: string;
  share: number;
  note: string;
}) {
  const tone =
    share >= 1 ? "bg-red-500" : share >= 0.8 ? "bg-amber-500" : "bg-brand";
  return (
    <div className="card flex flex-col gap-3 p-5">
      <p className="text-muted flex items-center gap-1.5 text-xs font-medium">
        <Icon className="text-subtle h-3.5 w-3.5" aria-hidden />
        {label}
      </p>
      <p className="text-2xl font-semibold tracking-tight tabular-nums">
        {value}
      </p>
      <div
        className="bg-surface-3 h-2 overflow-hidden rounded-full"
        role="meter"
        aria-label={label}
        aria-valuenow={Math.round(share * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full rounded-full ${tone}`}
          style={{ width: `${share * 100}%` }}
        />
      </div>
      <p className="text-subtle text-xs">{note}</p>
    </div>
  );
}

function Tile({
  icon: Icon,
  label,
  value,
  note,
}: {
  icon: typeof Gauge;
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="card flex flex-col gap-1 p-4">
      <dt className="text-muted flex items-center gap-1.5 text-xs font-medium">
        <Icon className="text-subtle h-3.5 w-3.5" aria-hidden />
        {label}
      </dt>
      <dd className="text-xl font-semibold tracking-tight tabular-nums">
        {value}
      </dd>
      {note && <dd className="text-subtle text-xs">{note}</dd>}
    </div>
  );
}

function StepBars({
  steps,
  total,
}: {
  steps: Usage["projects"][number]["steps"];
  total: number;
}) {
  if (!total) return <span className="text-subtle text-xs">No AI calls</span>;
  return (
    <ul className="flex min-w-48 flex-col gap-1.5">
      {steps.slice(0, 5).map((s) => (
        <li key={s.step} className="flex items-center gap-2 text-xs">
          <span className="text-muted w-36 shrink-0 truncate">
            {STEP_LABEL[s.step] ?? s.step}
          </span>
          <span className="bg-surface-3 h-1.5 flex-1 overflow-hidden rounded-full">
            <span
              className="bg-brand/70 block h-full rounded-full"
              style={{ width: `${(100 * s.calls) / total}%` }}
            />
          </span>
          <span className="text-subtle w-6 text-right tabular-nums">
            {s.calls}
          </span>
        </li>
      ))}
    </ul>
  );
}
