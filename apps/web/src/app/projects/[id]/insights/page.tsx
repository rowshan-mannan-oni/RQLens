import {
  ChevronRight,
  LoaderCircle,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { AutoRefresh } from "@/components/auto-refresh";
import { EmptyState } from "@/components/empty-state";
import { InsightCard, Queries } from "@/components/insights/insight-card";
import { ApiError, apiFetch } from "@/lib/api";
import { generateInsights } from "./actions";
import type {
  Dataset,
  Insights,
  Project,
  ResearchQuestions,
} from "@/lib/types";

export default async function InsightsPage(
  props: PageProps<"/projects/[id]/insights">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id } = await props.params;

  let project: Project;
  let data: Insights;
  let rqs: ResearchQuestions;
  let datasets: Dataset[];
  try {
    [project, data, rqs, datasets] = await Promise.all([
      apiFetch<Project>(`/projects/${id}`),
      apiFetch<Insights>(`/projects/${id}/insights`),
      apiFetch<ResearchQuestions>(`/projects/${id}/rqs`),
      apiFetch<Dataset[]>(`/projects/${id}/datasets`),
    ]);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  const hasData = datasets.some((d) => d.status === "ready");
  const running =
    data.run?.status === "queued" || data.run?.status === "running";
  const rqText = new Map(rqs.questions.map((q) => [q.id, q.text]));
  const analyses = data.insights.filter((i) => i.kind === "analysis");
  const findings = analyses.filter((i) => i.status === "finding");
  const others = analyses.filter((i) => i.status !== "finding");
  const quality = data.insights.filter((i) => i.kind === "data_quality");

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <AutoRefresh active={running} ms={2500} />
      <div className="flex min-w-0 flex-col gap-6">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Insights</h2>
          <p className="lead mt-1 max-w-3xl">
            Up to 20 analyses, chosen from your research questions and the
            strongest patterns in the profile. Each one runs a fixed statistical
            test. P-values are corrected for testing many patterns at once, and
            results are ranked by relevance, effect size and sample size, not by
            p-value. Every insight is{" "}
            <span className="text-fg font-medium">exploratory</span>: a
            hypothesis to test, not a result to report.
          </p>
        </div>

        {!hasData && (
          <EmptyState
            title="No data yet"
            text="Upload a dataset on the Overview tab, then generate insights."
            href={`/projects/${project.id}`}
            action="Go to Overview"
          />
        )}
        {hasData && data.insights.length === 0 && !running && (
          <EmptyState
            title="No insights yet"
            text="Generate insights to see ranked, corrected findings with the query behind each one."
          />
        )}
        {running && data.insights.length === 0 && (
          <div className="card text-muted flex items-center gap-3 p-5 text-sm">
            <LoaderCircle
              className="text-brand h-4 w-4 animate-spin"
              aria-hidden
            />
            Running analyses…
          </div>
        )}

        {quality.length > 0 && (
          <section className="flex flex-col gap-3">
            <h3 className="section-title">
              Data quality affecting your questions
            </h3>
            <ul className="flex flex-col gap-2">
              {quality.map((q) => (
                <li
                  key={q.id}
                  className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-sm dark:border-amber-900/60 dark:bg-amber-950/20"
                >
                  <TriangleAlert
                    className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400"
                    aria-hidden
                  />
                  <div className="flex min-w-0 flex-col gap-1">
                    <p>{q.statement}</p>
                    {q.rq_id && rqText.get(q.rq_id) && (
                      <p className="text-muted text-xs">
                        RQ: {rqText.get(q.rq_id)}
                      </p>
                    )}
                    {q.queries.length > 0 && <Queries queries={q.queries} />}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {findings.length > 0 && (
          <section className="flex flex-col gap-4">
            <h3 className="section-title">
              Findings{" "}
              <span className="text-subtle text-sm font-normal">
                {findings.length}, ranked
              </span>
            </h3>
            {findings.map((i, k) => (
              <InsightCard
                key={i.id}
                insight={i}
                rank={k + 1}
                rqText={i.rq_id ? (rqText.get(i.rq_id) ?? null) : null}
                chartOpen={k < 3}
              />
            ))}
          </section>
        )}

        {others.length > 0 && (
          <details className="group flex flex-col gap-4">
            <summary className="flex cursor-pointer list-none items-center gap-2 select-none">
              <ChevronRight
                className="text-subtle h-4 w-4 transition group-open:rotate-90"
                aria-hidden
              />
              <span className="section-title">Weak or no evidence</span>
              <span className="text-subtle text-sm">
                {others.length} analyses
              </span>
            </summary>
            <div className="mt-4 flex flex-col gap-4">
              {others.map((i, k) => (
                <InsightCard
                  key={i.id}
                  insight={i}
                  rank={findings.length + k + 1}
                  rqText={i.rq_id ? (rqText.get(i.rq_id) ?? null) : null}
                  chartOpen={false}
                />
              ))}
            </div>
          </details>
        )}
      </div>

      <aside className="flex flex-col gap-4 lg:sticky lg:top-20 lg:self-start">
        {hasData && (
          <div className="card flex flex-col gap-3 p-4">
            <p className="eyebrow">Generation</p>
            <form data-edit action={generateInsights.bind(null, project.id)}>
              <button disabled={running} className="btn btn-primary w-full">
                {running ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Sparkles className="h-4 w-4" aria-hidden />
                )}
                {running
                  ? "Generating…"
                  : data.insights.length > 0
                    ? "Generate again"
                    : "Generate insights"}
              </button>
            </form>
            {data.run?.status === "failed" && (
              <p
                role="alert"
                className="text-xs text-red-700 dark:text-red-400"
              >
                Generation failed: {data.run.error}
              </p>
            )}
            {data.run?.status === "done" && (
              <dl className="border-line grid grid-cols-2 gap-3 border-t pt-3 text-sm">
                <Stat label="Analyses run" value={data.run.planned ?? 0} />
                <Stat label="Findings" value={findings.length} />
                <Stat label="No evidence" value={others.length} />
                <Stat label="Data quality" value={quality.length} />
              </dl>
            )}
            {data.run?.status === "done" && (
              <p className="text-subtle text-xs">
                {data.run.used_llm
                  ? "AI-assisted plan and wording."
                  : "Planned by rules; template wording."}
                {(data.run.failed_json?.length ?? 0) > 0 &&
                  ` ${data.run.failed_json!.length} analyses could not run.`}
              </p>
            )}
          </div>
        )}
        {hasData && rqs.questions.length === 0 && (
          <div className="card-muted text-muted p-4 text-sm">
            Add research questions to focus the analyses on what you are
            studying.{" "}
            <Link href={`/projects/${project.id}/rqs`} className="link">
              Add questions
            </Link>
          </div>
        )}
      </aside>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-subtle text-xs">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
