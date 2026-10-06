import Link from "next/link";
import { redirect } from "next/navigation";

import { auth, signOut } from "@/auth";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { apiFetch } from "@/lib/api";
import type { Project } from "@/lib/types";

import { deleteProject } from "./[id]/actions";
import { createProject } from "./actions";

const input =
  "w-full rounded-md border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700";

export default async function ProjectsPage() {
  const session = await auth();
  if (!session?.user) redirect("/");

  const projects = await apiFetch<Project[]>("/projects");

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10">
      <header className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <form
          action={async () => {
            "use server";
            await signOut({ redirectTo: "/" });
          }}
          className="flex items-center gap-3 text-sm text-zinc-600 dark:text-zinc-400"
        >
          <span className="truncate">{session.user.email}</span>
          <button className="underline hover:text-zinc-900 dark:hover:text-zinc-100">
            Sign out
          </button>
        </form>
      </header>

      <form
        action={createProject}
        className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
      >
        <h2 className="font-medium">New project</h2>
        <input
          name="title"
          required
          maxLength={200}
          placeholder="Title"
          className={input}
        />
        <textarea
          name="topic"
          rows={2}
          maxLength={5000}
          placeholder="Research topic (optional)"
          className={input}
        />
        <button className="self-start rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300">
          Create project
        </button>
      </form>

      {projects.length === 0 ? (
        <p className="text-zinc-600 dark:text-zinc-400">No projects yet.</p>
      ) : (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {projects.map((p) => (
            <li
              key={p.id}
              className="flex items-start justify-between gap-4 py-3"
            >
              <div className="min-w-0">
                <Link
                  href={`/projects/${p.id}`}
                  className="font-medium hover:underline"
                >
                  {p.title}
                </Link>
                {p.topic && (
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    {p.topic}
                  </p>
                )}
                <p className="mt-1 text-xs text-zinc-500">
                  {p.status} · created{" "}
                  {new Date(p.created_at).toLocaleDateString()}
                </p>
              </div>
              <ConfirmDialog
                triggerLabel="Delete"
                title={`Delete the project “${p.title}”?`}
                confirmLabel="Delete project"
                action={deleteProject.bind(null, p.id)}
              >
                <p>
                  This permanently removes all datasets, uploaded files,
                  profiles, descriptions, query logs and AI call logs in this
                  project.
                </p>
                <p className="mt-2 font-medium">This cannot be undone.</p>
              </ConfirmDialog>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
