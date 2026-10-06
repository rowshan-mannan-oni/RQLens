import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { AutoRefresh } from "@/components/auto-refresh";
import { UploadForm } from "@/components/upload-form";
import { ApiError, apiFetch } from "@/lib/api";
import { formatBytes, formatInt, formatPct } from "@/lib/format";
import type {
  Dataset,
  DatasetStatus,
  Project,
  Relationship,
} from "@/lib/types";

const STATUS_LABEL: Record<DatasetStatus, string> = {
  queued: "Queued",
  loading: "Loading",
  profiling: "Profiling",
  ready: "Ready",
  failed: "Failed",
};

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
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {project.title}
        </h1>
        {project.topic && (
          <p className="mt-1 text-zinc-600 dark:text-zinc-400">
            {project.topic}
          </p>
        )}
      </div>

      <UploadForm projectId={project.id} />

      <section className="flex flex-col gap-3">
        <h2 className="font-medium">Datasets</h2>
        {datasets.length === 0 ? (
          <p className="text-zinc-600 dark:text-zinc-400">
            No datasets yet. Upload a CSV to profile it.
          </p>
        ) : (
          <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {datasets.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between gap-4 p-3"
              >
                <div className="min-w-0">
                  {d.status === "ready" ? (
                    <Link
                      href={`/projects/${project.id}/datasets/${d.id}`}
                      className="font-medium hover:underline"
                    >
                      {d.original_filename}
                    </Link>
                  ) : (
                    <p className="font-medium">{d.original_filename}</p>
                  )}
                  <p className="text-xs text-zinc-500">
                    table <code>{d.table_name}</code> ·{" "}
                    {formatBytes(d.size_bytes)}
                    {d.status === "ready" &&
                      ` · ${formatInt(d.row_count)} rows × ${formatInt(d.column_count)} columns`}
                  </p>
                  {d.status === "failed" && d.error && (
                    <p className="mt-1 text-xs break-words text-red-600">
                      {d.error}
                    </p>
                  )}
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                    d.status === "ready"
                      ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                      : d.status === "failed"
                        ? "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200"
                        : "animate-pulse bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                  }`}
                >
                  {STATUS_LABEL[d.status]}
                </span>
              </li>
            ))}
          </ul>
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
