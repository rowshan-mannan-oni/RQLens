import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { AutoRefresh } from "@/components/auto-refresh";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DatasetList } from "@/components/dataset-list";
import { UploadForm } from "@/components/upload-form";
import { ApiError, apiFetch } from "@/lib/api";
import { formatInt, formatPct } from "@/lib/format";
import { deleteProject, setShareSamples } from "./actions";
import type { Dataset, Project, Relationship } from "@/lib/types";

export default async function ProjectPage(props: PageProps<"/projects/[id]">) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id } = await props.params;

  let project: Project;
  let datasets: Dataset[];
  let joins: Relationship[];
  try {
    [project, datasets, joins] = await Promise.all([
      apiFetch<Project>(`/projects/${id}`),
      apiFetch<Dataset[]>(`/projects/${id}/datasets`),
      apiFetch<Relationship[]>(`/projects/${id}/relationships`),
    ]);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  const working = datasets.some(
    (d) => d.status !== "ready" && d.status !== "failed",
  );

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10">
      <AutoRefresh active={working} />
      <div>
        <Link
          href="/projects"
          className="text-sm text-zinc-500 hover:underline"
        >
          ← Projects
        </Link>
        <div className="mt-2 flex items-start justify-between gap-4">
          <h1 className="text-2xl font-semibold tracking-tight">
            {project.title}
          </h1>
          <ConfirmDialog
            triggerLabel="Delete project"
            title={`Delete the project “${project.title}”?`}
            confirmLabel="Delete project"
            action={deleteProject.bind(null, project.id)}
          >
            <p>
              This permanently removes all {datasets.length} dataset
              {datasets.length === 1 ? "" : "s"}, uploaded files, profiles,
              descriptions, query logs and AI call logs in this project.
            </p>
            <p className="mt-2 font-medium">This cannot be undone.</p>
          </ConfirmDialog>
        </div>
        {project.topic && (
          <p className="mt-1 text-zinc-600 dark:text-zinc-400">
            {project.topic}
          </p>
        )}
      </div>

      <form
        action={setShareSamples.bind(null, project.id, !project.share_samples)}
        className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800"
      >
        <p>
          <span className="font-medium">
            Sample values {project.share_samples ? "are" : "are not"} shared
            with the AI.
          </span>{" "}
          <span className="text-zinc-600 dark:text-zinc-400">
            {project.share_samples
              ? "The AI sees column statistics and a few masked example values, never full rows. Personal-data columns are never shown."
              : "The AI sees only column names and aggregate statistics."}
          </span>
        </p>
        <button className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
          {project.share_samples ? "Stop sharing samples" : "Share samples"}
        </button>
      </form>

      {datasets.some((d) => d.status === "ready") && (
        <Link
          href={`/projects/${project.id}/chat`}
          className="flex items-center justify-between rounded-lg border border-zinc-200 p-3 text-sm hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900"
        >
          <span>
            <span className="font-medium">Chat with your data</span>{" "}
            <span className="text-zinc-600 dark:text-zinc-400">
              Ask questions; every answer shows the queries behind it.
            </span>
          </span>
          <span aria-hidden>→</span>
        </Link>
      )}

      <UploadForm projectId={project.id} />

      <section className="flex flex-col gap-3">
        <h2 className="font-medium">Datasets</h2>
        {datasets.length === 0 ? (
          <p className="text-zinc-600 dark:text-zinc-400">
            No datasets yet. Upload a CSV to profile it.
          </p>
        ) : (
          <DatasetList projectId={project.id} datasets={datasets} />
        )}
      </section>

      {joins.length > 0 && (
        <section className="flex flex-col gap-3">
          <div>
            <h2 className="font-medium">Possible joins between tables</h2>
            <p className="text-sm text-zinc-500">
              Column pairs that share values. Coverage is the share of each
              side&apos;s distinct values found on the other side.
            </p>
          </div>
          <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 text-sm dark:divide-zinc-800 dark:border-zinc-800">
            {joins.map((j) => (
              <li key={j.id} className="flex flex-col gap-1 p-3">
                <p>
                  <code>{j.left.table_name}</code>.
                  <span className="font-medium">{j.left.column_label}</span>
                  <span className="text-zinc-500"> ↔ </span>
                  <code>{j.right.table_name}</code>.
                  <span className="font-medium">{j.right.column_label}</span>
                  <span className="ml-2 rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
                    {j.cardinality}
                  </span>
                  {j.name_match && (
                    <span className="ml-1 text-xs text-zinc-500">
                      names match
                    </span>
                  )}
                </p>
                <p className="text-xs text-zinc-600 dark:text-zinc-400">
                  {formatInt(j.shared_values)} shared values ·{" "}
                  {formatPct(j.left.coverage, 0)} of {j.left.table_name}.
                  {j.left.column_label} found in {j.right.table_name} ·{" "}
                  {formatPct(j.right.coverage, 0)} of {j.right.table_name}.
                  {j.right.column_label} found in {j.left.table_name}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
