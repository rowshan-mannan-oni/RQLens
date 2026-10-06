import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { LoaderCircle, Plus, Sparkles } from "lucide-react";

import { AutoRefresh } from "@/components/auto-refresh";
import { EmptyState } from "@/components/empty-state";
import { AddQuestionForm } from "@/components/rq/add-question-form";
import { RQCard } from "@/components/rq/rq-card";
import { ApiError, apiFetch } from "@/lib/api";
import { addQuestion, addSuggestion, requestSuggestions } from "./actions";
import type { Dataset, Project, ResearchQuestions } from "@/lib/types";

export default async function ResearchQuestionsPage(
  props: PageProps<"/projects/[id]/rqs">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id } = await props.params;

  let project: Project;
  let data: ResearchQuestions;
  let datasets: Dataset[];
  try {
    [project, data, datasets] = await Promise.all([
      apiFetch<Project>(`/projects/${id}`),
      apiFetch<ResearchQuestions>(`/projects/${id}/rqs`),
      apiFetch<Dataset[]>(`/projects/${id}/datasets`),
    ]);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  const hasData = datasets.some((d) => d.status === "ready");
  const working =
    data.questions.some(
      (q) => q.status === "queued" || q.status === "running",
    ) || data.suggestions_status === "running";
  const counts = {
    answerable: 0,
    partial: 0,
    not_answerable: 0,
  };
  for (const q of data.questions)
    if (q.assessment && q.status === "done") counts[q.assessment.verdict] += 1;

  const assessed = counts.answerable + counts.partial + counts.not_answerable;

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <AutoRefresh active={working} ms={2500} />
      <div className="flex min-w-0 flex-col gap-6">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            Research question fit
          </h2>
          <p className="lead mt-1 max-w-3xl">
            For each question, the AI maps its concepts to columns. Checks then
            run as queries: rows in scope, missing values, group sizes,
            variation, time coverage and a rough power check. Fixed rules turn
            those checks into a verdict. Treat it as guidance, and look at the
            evidence behind it.
          </p>
        </div>

        {!hasData ? (
          <EmptyState
            title="No data yet"
            text="Upload a dataset on the Overview tab before assessing research questions."
            href={`/projects/${project.id}`}
            action="Go to Overview"
          />
        ) : (
          <div className="card p-5">
            <AddQuestionForm action={addQuestion.bind(null, project.id)} />
          </div>
        )}

        {data.questions.length > 0 && (
          <section className="flex flex-col gap-4">
            {data.questions.map((q) => (
              <RQCard
                key={q.id}
                projectId={project.id}
                rq={q}
                columns={data.columns}
              />
            ))}
          </section>
        )}
      </div>

      <aside className="flex flex-col gap-4 lg:sticky lg:top-20 lg:self-start">
        {data.questions.length > 0 && (
          <div className="card flex flex-col gap-3 p-4">
            <p className="eyebrow">Summary</p>
            <VerdictBar counts={counts} total={assessed} />
            <ul className="flex flex-col gap-1.5 text-sm">
              <SummaryRow
                dot="bg-emerald-500"
                label="Answerable"
                n={counts.answerable}
              />
              <SummaryRow
                dot="bg-amber-500"
                label="Partly answerable"
                n={counts.partial}
              />
              <SummaryRow
                dot="bg-red-500"
                label="Not answerable"
                n={counts.not_answerable}
              />
            </ul>
          </div>
        )}

        {hasData && (
          <section className="card flex flex-col gap-3 p-4">
            <div className="flex items-center gap-2">
              <Sparkles className="text-brand h-4 w-4" aria-hidden />
              <h3 className="text-sm font-semibold">
                Questions the data could answer
              </h3>
            </div>
            <form action={requestSuggestions.bind(null, project.id)}>
              <button
                disabled={data.suggestions_status === "running"}
                className="btn btn-secondary btn-sm"
              >
                {data.suggestions_status === "running" && (
                  <LoaderCircle
                    className="h-3.5 w-3.5 animate-spin"
                    aria-hidden
                  />
                )}
                {data.suggestions_status === "running"
                  ? "Suggesting…"
                  : data.suggestions
                    ? "Suggest again"
                    : "Suggest questions"}
              </button>
            </form>
            {data.suggestions_status === "failed" && (
              <p
                role="alert"
                className="text-xs text-red-700 dark:text-red-400"
              >
                Suggestions failed: {data.suggestions_error}
              </p>
            )}
            {data.suggestions && data.suggestions.length > 0 && (
              <ul className="divide-line border-line -mx-4 divide-y border-t text-sm">
                {data.suggestions.map((s) => (
                  <li key={s.text} className="flex flex-col gap-2 px-4 py-3">
                    <p className="font-medium">{s.text}</p>
                    <p className="text-muted text-xs">
                      <span className="badge badge-neutral mr-1">{s.type}</span>
                      {s.columns.map((c) => (
                        <code key={c} className="text-subtle mr-1">
                          {c}
                        </code>
                      ))}
                    </p>
                    {s.reason && (
                      <p className="text-subtle text-xs">{s.reason}</p>
                    )}
                    <form action={addSuggestion.bind(null, project.id, s.text)}>
                      <button className="btn btn-ghost btn-sm text-brand-fg dark:text-brand -ml-2.5">
                        <Plus className="h-3.5 w-3.5" aria-hidden />
                        Add and assess
                      </button>
                    </form>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </aside>
    </div>
  );
}

function VerdictBar({
  counts,
  total,
}: {
  counts: { answerable: number; partial: number; not_answerable: number };
  total: number;
}) {
  if (!total)
    return <p className="text-subtle text-sm">Nothing assessed yet.</p>;
  const part = (n: number) => `${(100 * n) / total}%`;
  return (
    <div
      className="bg-surface-3 flex h-2 overflow-hidden rounded-full"
      role="img"
      aria-label={`${counts.answerable} answerable, ${counts.partial} partly, ${counts.not_answerable} not answerable`}
    >
      <span
        className="bg-emerald-500"
        style={{ width: part(counts.answerable) }}
      />
      <span className="bg-amber-500" style={{ width: part(counts.partial) }} />
      <span
        className="bg-red-500"
        style={{ width: part(counts.not_answerable) }}
      />
    </div>
  );
}

function SummaryRow({
  dot,
  label,
  n,
}: {
  dot: string;
  label: string;
  n: number;
}) {
  return (
    <li className="flex items-center justify-between">
      <span className="text-muted flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
        {label}
      </span>
      <span className="font-medium tabular-nums">{n}</span>
    </li>
  );
}
