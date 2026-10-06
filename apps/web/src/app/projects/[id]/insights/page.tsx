import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { AutoRefresh } from "@/components/auto-refresh";
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
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10">
      <AutoRefresh active={running} ms={2500} />
      <div>
        <Link
          href={`/projects/${project.id}`}
          className="text-sm text-zinc-500 hover:underline"
        >
          ← {project.title}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Insights</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Up to 20 analyses, chosen from your research questions and the
          strongest patterns in the profile. Each runs a fixed statistical test;
          p-values are corrected for testing many patterns at once
          (Benjamini-Hochberg), and results are ranked by relevance, effect size
          and sample size, not by p-value. Every insight is{" "}
          <span className="font-medium">exploratory</span>: a hypothesis to
          test, not a result to report.
        </p>
      </div>

      {!hasData ? (
        <p className="rounded-lg border border-zinc-200 p-4 text-sm dark:border-zinc-800">
          Upload a dataset on the{" "}
          <Link href={`/projects/${project.id}`} className="underline">
            project page
          </Link>{" "}
          first.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <form action={generateInsights.bind(null, project.id)}>
            <button
              disabled={running}
              className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
            >
              {running
                ? "Generating…"
                : data.insights.length > 0
                  ? "Generate again"
                  : "Generate insights"}
            </button>
          </form>
          {data.run?.status === "failed" && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              Generation failed: {data.run.error}
            </p>
          )}
          {data.run?.status === "done" && (
            <p className="text-xs text-zinc-500">
              {data.run.planned} analyses run
              {data.run.used_llm ? " (AI-assisted plan and wording)" : ""}
              {(data.run.failed_json?.length ?? 0) > 0 &&
                ` · ${data.run.failed_json!.length} could not run`}
              {rqs.questions.length === 0 &&
                " · add research questions to focus the analyses"}
            </p>
          )}
        </div>
      )}

      {quality.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="font-medium">Data quality affecting your questions</h2>
          <ul className="flex flex-col gap-2">
            {quality.map((q) => (
              <li
                key={q.id}
                className="flex flex-col gap-1 rounded-lg border border-amber-200 bg-amber-50/50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/20"
              >
                <p>{q.statement}</p>
                {q.rq_id && rqText.get(q.rq_id) && (
                  <p className="text-xs text-zinc-500">
                    RQ: {rqText.get(q.rq_id)}
                  </p>
                )}
                {q.queries.length > 0 && <Queries queries={q.queries} />}
              </li>
            ))}
          </ul>
        </section>
      )}

      {findings.length > 0 && (
        <section className="flex flex-col gap-4">
          <h2 className="font-medium">
            Findings{" "}
            <span className="text-sm font-normal text-zinc-500">
              {findings.length}, ranked
            </span>
          </h2>
          {findings.map((i, k) => (
            <InsightCard
              key={i.id}
              insight={i}
              rank={k + 1}
              rqText={i.rq_id ? (rqText.get(i.rq_id) ?? null) : null}
            />
          ))}
        </section>
      )}

      {others.length > 0 && (
        <details className="group flex flex-col gap-4">
          <summary className="cursor-pointer font-medium">
            Weak or no evidence{" "}
            <span className="text-sm font-normal text-zinc-500">
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
              />
            ))}
          </div>
        </details>
      )}
    </main>
  );
}
