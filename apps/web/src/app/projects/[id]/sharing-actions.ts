"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import type { ActionState } from "@/components/confirm-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { CommentTarget, Member, ProjectComment } from "@/lib/types";

// The API checks every permission (owner, editor, viewer); these only forward the request.

async function requireUser() {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");
}

function message(e: ApiError): string {
  try {
    const { detail } = JSON.parse(e.message);
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  } catch {}
  return `Something went wrong (${e.status}).`;
}

async function call<T>(
  projectId: number,
  url: string,
  init: RequestInit = {},
): Promise<{ error: string | null; data?: T }> {
  await requireUser();
  try {
    const data = await apiFetch<T>(`/projects/${projectId}${url}`, init);
    revalidatePath(`/projects/${projectId}`, "layout");
    return { error: null, data };
  } catch (e) {
    if (e instanceof ApiError) return { error: message(e) };
    throw e;
  }
}

export async function listMembers(projectId: number) {
  return call<Member[]>(projectId, "/members");
}

export async function addMember(
  projectId: number,
  email: string,
  role: "viewer" | "editor",
) {
  return call<Member>(projectId, "/members", {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

export async function changeRole(
  projectId: number,
  memberId: number,
  role: "viewer" | "editor",
) {
  return call<Member>(projectId, `/members/${memberId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export async function removeMember(
  projectId: number,
  memberId: number,
): Promise<ActionState> {
  return call(projectId, `/members/${memberId}`, { method: "DELETE" });
}

export async function leaveProject(
  projectId: number,
  memberId: number,
): Promise<ActionState> {
  const res = await call(projectId, `/members/${memberId}`, {
    method: "DELETE",
  });
  if (res.error) return res;
  revalidatePath("/projects");
  redirect("/projects");
}

export async function addComment(
  projectId: number,
  targetType: CommentTarget,
  targetId: number | null,
  body: string,
) {
  return call<ProjectComment>(projectId, "/comments", {
    method: "POST",
    body: JSON.stringify({
      target_type: targetType,
      target_id: targetId,
      body,
    }),
  });
}

export async function resolveComment(
  projectId: number,
  commentId: number,
  resolved: boolean,
) {
  return call<ProjectComment>(projectId, `/comments/${commentId}`, {
    method: "PATCH",
    body: JSON.stringify({ resolved }),
  });
}

export async function deleteComment(projectId: number, commentId: number) {
  return call(projectId, `/comments/${commentId}`, { method: "DELETE" });
}
