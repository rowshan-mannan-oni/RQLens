"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import type { ActionState } from "@/components/confirm-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type {
  CellValue,
  RelatedPapers,
  ReviewTable,
  ReviewTemplate,
  TemplateColumn,
} from "@/lib/types";

// The API checks that the signed-in user owns the project, paper, table and template.

async function requireUser() {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");
}

function message(e: ApiError): string {
  try {
    const { detail } = JSON.parse(e.message);
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg)
      return String(detail[0].msg).replace(/^Value error, /, "");
  } catch {}
  return `Something went wrong (${e.status}).`;
}

const base = (projectId: number) => `/projects/${projectId}/literature`;

async function call<T>(
  url: string,
  init: RequestInit,
  revalidate: string,
): Promise<{ error: string | null; data?: T }> {
  await requireUser();
  try {
    const data = await apiFetch<T>(url, init);
    revalidatePath(revalidate);
    return { error: null, data };
  } catch (e) {
    if (e instanceof ApiError) return { error: message(e) };
    throw e;
  }
}

// --- papers --------------------------------------------------------------------------------

export async function deletePaper(
  projectId: number,
  paperId: number,
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/papers/${paperId}`,
    { method: "DELETE" },
    base(projectId),
  );
}

export async function reparsePaper(
  projectId: number,
  paperId: number,
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/papers/${paperId}/reparse`,
    { method: "POST" },
    base(projectId),
  );
}

export async function updatePaper(
  projectId: number,
  paperId: number,
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const text = (k: string) => String(formData.get(k) ?? "").trim() || null;
  const year = text("year");
  if (year && !/^\d{4}$/.test(year))
    return { error: "Year must have four digits." };
  const authors = text("authors");
  return call(
    `/projects/${projectId}/papers/${paperId}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        title: text("title"),
        authors: authors
          ? authors
              .split(/;|\n/)
              .map((a) => a.trim())
              .filter(Boolean)
          : null,
        year: year ? Number(year) : null,
        venue: text("venue"),
        doi: text("doi"),
      }),
    },
    base(projectId),
  );
}

export async function clearReferences(projectId: number): Promise<ActionState> {
  return call(
    `/projects/${projectId}/papers/references`,
    { method: "DELETE" },
    base(projectId),
  );
}

// --- tables --------------------------------------------------------------------------------

export async function createTable(
  projectId: number,
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const res = await call<ReviewTable>(
    `/projects/${projectId}/review-tables`,
    {
      method: "POST",
      body: JSON.stringify({
        template_key: String(formData.get("template_key") ?? ""),
        name: String(formData.get("name") ?? "").trim() || null,
      }),
    },
    base(projectId),
  );
  if (res.error || !res.data) return { error: res.error };
  redirect(`${base(projectId)}/${res.data.id}`);
}

export async function renameTable(
  projectId: number,
  tableId: number,
  name: string,
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}`,
    { method: "PATCH", body: JSON.stringify({ name }) },
    `${base(projectId)}/${tableId}`,
  );
}

export async function deleteTable(
  projectId: number,
  tableId: number,
): Promise<ActionState> {
  const res = await call(
    `/projects/${projectId}/review-tables/${tableId}`,
    { method: "DELETE" },
    base(projectId),
  );
  if (res.error) return res;
  redirect(base(projectId));
}

export async function addColumn(
  projectId: number,
  tableId: number,
  column: Partial<TemplateColumn>,
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}/columns`,
    { method: "POST", body: JSON.stringify({ column }) },
    `${base(projectId)}/${tableId}`,
  );
}

export async function updateColumn(
  projectId: number,
  tableId: number,
  key: string,
  patch: { label?: string; instructions?: string },
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}/columns/${encodeURIComponent(key)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
    `${base(projectId)}/${tableId}`,
  );
}

export async function deleteColumn(
  projectId: number,
  tableId: number,
  key: string,
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}/columns/${encodeURIComponent(key)}`,
    { method: "DELETE" },
    `${base(projectId)}/${tableId}`,
  );
}

export async function reorderColumns(
  projectId: number,
  tableId: number,
  keys: string[],
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}/columns`,
    { method: "PUT", body: JSON.stringify({ keys }) },
    `${base(projectId)}/${tableId}`,
  );
}

// --- cells ---------------------------------------------------------------------------------

export async function editCell(
  projectId: number,
  tableId: number,
  cellId: number,
  value: CellValue,
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}/cells/${cellId}`,
    { method: "PATCH", body: JSON.stringify({ value }) },
    `${base(projectId)}/${tableId}`,
  );
}

export async function revertCell(
  projectId: number,
  tableId: number,
  cellId: number,
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}/cells/${cellId}/revert`,
    { method: "POST" },
    `${base(projectId)}/${tableId}`,
  );
}

export async function reviewCell(
  projectId: number,
  tableId: number,
  cellId: number,
  decision: "accepted" | "rejected" | null,
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}/cells/${cellId}/review`,
    { method: "POST", body: JSON.stringify({ decision }) },
    `${base(projectId)}/${tableId}`,
  );
}

export async function rerun(
  projectId: number,
  tableId: number,
  scope: { paper_id?: number; column_key?: string },
): Promise<ActionState> {
  return call(
    `/projects/${projectId}/review-tables/${tableId}/rerun`,
    { method: "POST", body: JSON.stringify(scope) },
    `${base(projectId)}/${tableId}`,
  );
}

export async function relatedPapers(
  projectId: number,
  tableId: number,
  rqId: number,
): Promise<{ error: string | null; data?: RelatedPapers }> {
  await requireUser();
  try {
    const data = await apiFetch<RelatedPapers>(
      `/projects/${projectId}/review-tables/${tableId}/related?rq_id=${rqId}`,
    );
    return { error: null, data };
  } catch (e) {
    if (e instanceof ApiError) return { error: message(e) };
    throw e;
  }
}

// --- templates -----------------------------------------------------------------------------

export async function saveTemplate(
  projectId: number,
  templateKey: string | null,
  body: { name: string; description: string; columns: TemplateColumn[] },
): Promise<ActionState & { key?: string }> {
  const userId = templateKey?.startsWith("user:") ? templateKey.slice(5) : null;
  const res = await call<ReviewTemplate>(
    userId ? `/templates/${userId}` : "/templates",
    { method: userId ? "PUT" : "POST", body: JSON.stringify(body) },
    `${base(projectId)}/templates`,
  );
  revalidatePath(base(projectId));
  return { error: res.error, key: res.data?.key };
}

export async function deleteTemplate(
  projectId: number,
  templateKey: string,
): Promise<ActionState> {
  const id = templateKey.replace(/^user:/, "");
  const res = await call(
    `/templates/${id}`,
    { method: "DELETE" },
    `${base(projectId)}/templates`,
  );
  revalidatePath(base(projectId));
  return res;
}
