import { ArrowRight, FolderOpen, Plus, Sparkles } from "lucide-react";
import Link from "next/link";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { apiFetch } from "@/lib/api";
import type { Project } from "@/lib/types";

import { deleteProject } from "./[id]/actions";
import { createProject, createSampleProject } from "./actions";

export default async function ProjectsPage() {
  const projects = await apiFetch<Project[]>("/projects");

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-10 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="lead mt-1">
            A project holds your datasets, research questions, insights and
            chats about one study.
          </p>
        </div>
        <form action={createSampleProject}>
          <button className="btn btn-secondary">
            <Sparkles className="text-brand h-4 w-4" aria-hidden />
            Try a sample project
          </button>
        </form>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <form
          action={createProject}
          className="card flex flex-col gap-3 border-dashed p-5"
        >
          <div className="flex items-center gap-2">
            <span className="bg-brand-soft text-brand-fg grid h-8 w-8 place-items-center rounded-lg">
              <Plus className="h-4 w-4" aria-hidden />
            </span>
            <h2 className="section-title">New project</h2>
          </div>
          <label className="sr-only" htmlFor="new-title">
            Title
          </label>
          <input
            id="new-title"
            name="title"
            required
            maxLength={200}
            placeholder="Title, e.g. Wage gaps in the 1985 CPS"
            className="input"
          />
          <label className="sr-only" htmlFor="new-topic">
            Research topic
          </label>
          <textarea
            id="new-topic"
            name="topic"
            rows={2}
            maxLength={5000}
            placeholder="Research topic (optional, helps the AI)"
            className="input resize-none"
          />
          <button className="btn btn-primary self-start">Create project</button>
        </form>

        {projects.map((p) => (
          <article
            key={p.id}
            className="card group hover:border-line-strong hover:shadow-pop relative flex flex-col gap-3 p-5 transition"
          >
            <div className="flex items-start justify-between gap-3">
              <span className="bg-surface-3 text-muted grid h-8 w-8 shrink-0 place-items-center rounded-lg">
                <FolderOpen className="h-4 w-4" aria-hidden />
              </span>
              <div className="relative z-10 opacity-100 transition sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
                <ConfirmDialog
                  triggerLabel="Delete"
                  triggerClassName="btn btn-sm btn-ghost"
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
              </div>
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="truncate font-semibold tracking-tight">
                <Link
                  href={`/projects/${p.id}`}
                  className="after:absolute after:inset-0 after:rounded-xl"
                >
                  {p.title}
                </Link>
              </h2>
              <p className="text-muted mt-1 line-clamp-2 text-sm">
                {p.topic || "No research topic yet."}
              </p>
            </div>
            <div className="text-subtle flex items-center justify-between text-xs">
              <span>
                Created{" "}
                {new Date(p.created_at).toLocaleDateString(undefined, {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                })}
              </span>
              <ArrowRight
                className="group-hover:text-brand h-4 w-4 transition group-hover:translate-x-0.5"
                aria-hidden
              />
            </div>
          </article>
        ))}
      </div>

      {projects.length === 0 && (
        <p className="text-muted text-sm">
          No projects yet. Create one to upload your first dataset, or try the
          sample project: a public penguin dataset with three research
          questions, ready to explore.
        </p>
      )}
    </main>
  );
}
