import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { AutoRefresh } from "@/components/auto-refresh";
import { ReviewTableView } from "@/components/literature/review-table";
import { ApiError, apiFetch } from "@/lib/api";
import type {
  Project,
  ProjectComment,
  ResearchQuestions,
  ReviewTable,
} from "@/lib/types";

export default async function ReviewTablePage(
  props: PageProps<"/projects/[id]/literature/[tableId]">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id, tableId } = await props.params;
  let table: ReviewTable;
  let rqs: ResearchQuestions;
  let comments: ProjectComment[];
  let project: Project;
  try {
    [table, rqs, comments, project] = await Promise.all([
      apiFetch<ReviewTable>(`/projects/${id}/review-tables/${tableId}`),
      apiFetch<ResearchQuestions>(`/projects/${id}/rqs`),
      apiFetch<ProjectComment[]>(`/projects/${id}/comments?target_type=cell`),
      apiFetch<Project>(`/projects/${id}`),
    ]);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  const working =
    table.cells.some((c) => c.status === "queued" || c.status === "running") ||
    table.papers.some((p) => p.status === "queued" || p.status === "parsing");
  return (
    <>
      <AutoRefresh active={working} ms={2500} />
      {/* Wider than the page column, since review tables have many columns. Centred with
          margins rather than a transform, which would break the reader's fixed panel. */}
      <div
        style={{
          width: "min(100vw - 3rem, 110rem)",
          marginLeft: "calc((100% - min(100vw - 3rem, 110rem)) / 2)",
        }}
      >
        <ReviewTableView
          projectId={Number(id)}
          table={table}
          questions={rqs.questions.map((q) => ({ id: q.id, text: q.text }))}
          comments={comments}
          canModerate={project.role !== "viewer"}
        />
      </div>
    </>
  );
}
