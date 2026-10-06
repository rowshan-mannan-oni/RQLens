import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { AutoRefresh } from "@/components/auto-refresh";
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

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10">
      <AutoRefresh active={working} ms={2500} />
      <div>
        <Link
          href={`/projects/${project.id}`}
          className="text-sm text-zinc-500 hover:underline"
        >
          ← {project.title}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          Research question fit
        </h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          For each question, the AI maps its concepts to columns, then checks
          run as queries: rows in scope, missing values, group sizes, variation,
          time coverage and a rough power check. The verdict comes from fixed
          rules over those checks. Treat it as guidance for planning, and look
          at the evidence behind it.
        </p>
      </div>

      {!hasData ? (
        <p className="rounded-lg border border-zinc-200 p-4 text-sm dark:border-zinc-800">
          Upload a dataset on the{" "}
          <Link href={`/projects/${project.id}`} className="underline">
            project page
          </Link>{" "}
          before assessing research questions.
        </p>
      ) : (
        <AddQuestionForm action={addQuestion.bind(null, project.id)} />
      )}

      {data.questions.length > 0 && (
        <section className="flex flex-col gap-4">
          <h2 className="font-medium">
            Your questions{" "}
            <span className="text-sm font-normal text-zinc-500">
              {counts.answerable} answerable · {counts.partial} partly ·{" "}
              {counts.not_answerable} not answerable
            </span>
          </h2>
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

      {hasData && (
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-medium">Questions this data could answer</h2>
            <form action={requestSuggestions.bind(null, project.id)}>
              <button
                disabled={data.suggestions_status === "running"}
                className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                {data.suggestions_status === "running"
                  ? "Suggesting…"
                  : data.suggestions
                    ? "Suggest again"
                    : "Suggest questions"}
              </button>
            </form>
          </div>
          {data.suggestions_status === "failed" && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              Suggestions failed: {data.suggestions_error}
            </p>
          )}
          {data.suggestions && data.suggestions.length > 0 && (
            <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 text-sm dark:divide-zinc-800 dark:border-zinc-800">
              {data.suggestions.map((s) => (
                <li
                  key={s.text}
                  className="flex flex-wrap items-start justify-between gap-3 p-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{s.text}</p>
                    <p className="text-xs text-zinc-600 dark:text-zinc-400">
                      {s.type} · uses{" "}
                      {s.columns.map((c) => (
                        <code key={c} className="mr-1">
                          {c}
                        </code>
                      ))}
                      {s.reason && <>· {s.reason}</>}
                    </p>
                  </div>
                  <form action={addSuggestion.bind(null, project.id, s.text)}>
                    <button className="rounded-md border border-zinc-300 px-2 py-1 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
                      Add and assess
                    </button>
                  </form>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  );
}
