import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { ShareDialog } from "@/components/sharing/share-dialog";
import { ProjectTabs } from "@/components/shell/project-tabs";
import { ApiError, apiFetch } from "@/lib/api";
import type { Project } from "@/lib/types";

export default async function ProjectLayout({
  children,
  params,
}: LayoutProps<"/projects/[id]">) {
  const { id } = await params;
  let project: Project;
  const session = await auth();
  try {
    project = await apiFetch<Project>(`/projects/${id}`);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  return (
    <>
      <div className="border-line bg-surface border-b">
        <div className="mx-auto w-full max-w-6xl px-4 pt-5 sm:px-6">
          <nav
            aria-label="Breadcrumb"
            className="text-subtle flex items-center gap-1 text-xs"
          >
            <Link href="/projects" className="hover:text-fg">
              Projects
            </Link>
            <ChevronRight className="h-3 w-3" aria-hidden />
            <span className="text-muted truncate">{project.title}</span>
          </nav>
          <div className="mt-1.5 flex items-center gap-3">
            <h1 className="min-w-0 flex-1 truncate text-2xl font-semibold tracking-tight">
              {project.title}
            </h1>
            <ShareDialog
              projectId={project.id}
              role={project.role}
              myEmail={session?.user?.email?.toLowerCase() ?? null}
            />
          </div>
          {project.role !== "owner" && (
            <p className="text-muted mt-1 text-xs">
              Shared by {project.owner ?? "its owner"} ·{" "}
              {project.role === "viewer"
                ? "you can view and comment"
                : "you can edit; AI use counts against the owner's limit"}
            </p>
          )}
          {project.topic && (
            <p className="text-muted mt-1 line-clamp-2 max-w-3xl text-sm">
              {project.topic}
            </p>
          )}
          <div className="mt-4">
            <ProjectTabs projectId={project.id} />
          </div>
        </div>
      </div>
      <div
        data-role={project.role}
        className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6"
      >
        {children}
      </div>
    </>
  );
}
